#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmpage.h"
#include "fs.h"
#include "swap.h"
#include "vmtrace.h"
#include "mlfeat.h"
#include "mlnet.h"
#include "mlnets.h"

#define NPHYS_PAGES ((PHYSTOP - KERNBASE) / PGSIZE)

// VM_POLICY_ML refault bookkeeping, per swap slot (what Linux's workingset
// keeps in a shadow entry): the owner's scan count when the page was
// written out, and how often it had been refaulted by then. Protected by
// frame_table.lock.
static uint64 slot_evict_scan[NSWAPSLOTS];
static uint32 slot_refaults[NSWAPSLOTS];

static struct {
  struct spinlock lock;
  struct vm_page pages[NPHYS_PAGES];
  struct vm_page *candidates[NPHYS_PAGES];
} frame_table;

static uint64 load_sequence;

static struct vm_page *
page_for_pa(uint64 pa)
{
  if(pa < KERNBASE || pa >= PHYSTOP || pa % PGSIZE != 0)
    return 0;
  return &frame_table.pages[(pa - KERNBASE) / PGSIZE];
}

// owner_next/owner_prev thread every frame owned by a given process onto
// that process's vm.owned_head/owned_tail list. Every caller of these two
// helpers already holds frame_table.lock, matching the fields' documented
// protection (see vmpage.h and vmstate.h).
static void
owned_list_remove(struct vm_page *page)
{
  if(page->owner == 0)
    return;
  struct vmstate *vm = &page->owner->vm;
  if(page->owner_prev)
    page->owner_prev->owner_next = page->owner_next;
  else
    vm->owned_head = page->owner_next;
  if(page->owner_next)
    page->owner_next->owner_prev = page->owner_prev;
  else
    vm->owned_tail = page->owner_prev;
  page->owner_next = 0;
  page->owner_prev = 0;
}

static void
owned_list_insert(struct vm_page *page)
{
  struct vmstate *vm = &page->owner->vm;
  page->owner_prev = vm->owned_tail;
  page->owner_next = 0;
  if(vm->owned_tail)
    vm->owned_tail->owner_next = page;
  else
    vm->owned_head = page;
  vm->owned_tail = page;
}

static void cp_unlink(struct vm_page *page);

static void
clear_page(struct vm_page *page)
{
  uint64 pa = page->pa;
  cp_unlink(page);
  // Must run before memset wipes owner/owner_next/owner_prev below: this is
  // the single choke point (called directly by vm_frame_release(), and via
  // setup_page() for both a fresh frame and a reclaimed/repurposed one) that
  // detaches a frame from whichever process's owned-frame list it was on.
  owned_list_remove(page);
  memset(page, 0, sizeof(*page));
  page->pa = pa;
  page->state = VM_PAGE_FREE;
  page->backing_slot = -1;
  page->policy_index = -1;
}

static void
setup_page(struct vm_page *page, struct proc *p, pagetable_t pagetable,
           uint64 va, int purpose)
{
  clear_page(page);
  page->owner = p;
  page->pagetable = pagetable;
  page->va = va;
  page->state = purpose == VM_FRAME_PREFETCH ? VM_PAGE_RESIDENT_PREFETCH :
                                                VM_PAGE_RESIDENT_DEMAND;
  page->pin_count = 1;
  page->busy = purpose == VM_FRAME_CONSTRUCTION;
  page->load_sequence = ++load_sequence;
  page->aging_counter = 0xff;
  // Count the fault-in touch itself as this page's first access (matches
  // tools/sim.py's own Lfu.access(), which increments frequency on every
  // touch including the one that first loads a page). Without this, a
  // freshly-loaded page starts at frequency=0 -- an unconditional minimum
  // against any already-resident page with frequency>=1 -- so choose_lfu
  // would evict it again before it's ever sampled as accessed even once,
  // a real livelock under memory pressure (see AUSTRA_HANDOFF.md).
  page->frequency = 1;
  // A fault sets PTE_A (kernel/vm.c), so the page counts as seen at the
  // scan it is loaded in; refault fields are filled by vm_frame_set_backing()
  // when it came back from swap.
  page->ml_load_scan = page->ml_last_seen = p->vm.ml_scans;
  owned_list_insert(page);
}

static int
page_is_candidate(struct proc *p, struct vm_page *page)
{
  return page->owner == p && page->pin_count == 0 && page->busy == 0 &&
    (page->state == VM_PAGE_RESIDENT_DEMAND ||
     page->state == VM_PAGE_RESIDENT_PREFETCH);
}

static int
sample_page(struct vm_page *page, int clear_accessed)
{
  pte_t *pte = walk(page->pagetable, page->va, 0);
  if(pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != page->pa)
    return 0;
  int accessed = (*pte & PTE_A) != 0;
  page->referenced_sample = accessed;
  page->dirty_sample = (*pte & PTE_D) != 0;
  if(accessed){
    page->frequency++;
    page->last_access_epoch = load_sequence;
    if(page->state == VM_PAGE_RESIDENT_PREFETCH){
      page->state = VM_PAGE_RESIDENT_DEMAND;
      __sync_fetch_and_add(&page->owner->vm.stats.prefetch_useful, 1);
      vmtrace_emit(page->owner, VMTRACE_PREFETCH_USE, page->va, -1,
                   VM_PAGE_RESIDENT_DEMAND, PTE_FLAGS(*pte),
                   (page->pa - KERNBASE) / PGSIZE, page->backing_slot,
                   VMTRACE_NONE, VMTRACE_NONE, 0);
    }
  }
  if(clear_accessed && accessed)
    *pte &= ~PTE_A;
  return accessed;
}

static struct vm_page *
choose_fifo(struct vm_page **candidates, int count)
{
  struct vm_page *victim = 0;
  uint64 oldest = (uint64)-1;
  for(int i = 0; i < count; i++)
    if(candidates[i]->load_sequence < oldest){
      victim = candidates[i];
      oldest = candidates[i]->load_sequence;
    }
  return victim;
}

static struct vm_page *
choose_clock(struct proc *p, struct vm_page **candidates, int count)
{
  if(count == 0)
    return 0;
  int cleared = 0;
  for(int scanned = 0; scanned < count * 2; scanned++){
    int index = p->vm.clock_hand++ % count;
    struct vm_page *page = candidates[index];
    if(!sample_page(page, 1)){
      if(cleared)
        sfence_vma();
      return page;
    }
    cleared = 1;
  }
  if(cleared)
    sfence_vma();
  return candidates[p->vm.clock_hand++ % count];
}

static struct vm_page *
choose_aging(struct vm_page **candidates, int count)
{
  struct vm_page *victim = 0;
  int cleared = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    int accessed = sample_page(page, 1);
    cleared |= accessed;
    page->aging_counter = (page->aging_counter >> 1) |
      (accessed ? 0x80 : 0);
    if(victim == 0 || page->aging_counter < victim->aging_counter ||
       (page->aging_counter == victim->aging_counter &&
        page->load_sequence < victim->load_sequence))
      victim = page;
  }
  if(cleared)
    sfence_vma();
  return victim;
}

// Least-Frequently-Used: evict the resident candidate with the smallest
// DECAYED access-frequency estimate. page->frequency is halved on every
// scan and then bumped by one if the page was found accessed (the same
// scan-driven approximation choose_clock/choose_aging already make via
// sample_page(), just applied to a magnitude instead of a recency bit).
//
// An earlier version used a raw, never-decaying cumulative count and
// livelocked under real memory pressure: a page that had survived many
// earlier scans kept climbing without bound, while any page reloaded to
// replace an eviction victim restarted from a small fixed value -- so a
// freshly-loaded page was *permanently* disadvantaged against the
// established resident set, got evicted again immediately (before ever
// being sampled as accessed even once), and the very next fault reloaded
// the same page into the same trap, forever. Verified via instrumented
// counter: 40,000+ evictions of one physical page inside a workload that
// can produce at most ~12,000 real faults (see AUSTRA_HANDOFF.md).
// Decaying old counts bounds this: a long-idle survivor's frequency
// shrinks back toward 0 instead of accumulating an unbeatable lead, so a
// newly-loaded page competes on comparable terms rather than being
// structurally locked out.
//
// Tie-break on load_sequence (oldest first), matching choose_aging's own
// tie-break rule.
static struct vm_page *
choose_lfu(struct vm_page **candidates, int count)
{
  struct vm_page *victim = 0;
  int cleared = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    int accessed = sample_page(page, 1);
    cleared |= accessed;
    page->frequency = (page->frequency >> 1) + (accessed ? 1 : 0);
    if(victim == 0 || page->frequency < victim->frequency ||
       (page->frequency == victim->frequency &&
        page->load_sequence < victim->load_sequence))
      victim = page;
  }
  if(cleared)
    sfence_vma();
  return victim;
}

// VM_POLICY_ML: a learned linear score over kernel-observable features,
// integers only (weights from tools/ml2/export_kernel.py; features from
// mlfeat.h, shared with the host simulator so both score a page alike).
// Like choose_aging it scans every candidate: read and clear the accessed
// bit, update the aging counter and the sampled-access count. Then it evicts
// the highest score -- the page predicted to be needed furthest in the
// future -- oldest load first on a tie, skipping pages loaded fewer than
// protect_age scans ago while an older candidate exists (probation: a fresh
// page is otherwise the one a model is most likely to misjudge).
static int
ml_feature(struct proc *p, struct vm_page *page, int f)
{
  uint64 now = p->vm.ml_scans;
  switch(f){
  case ML_F_REF:      return page->ml_seen ? 256 : 0;
  case ML_F_AGING:    return ml_aging_q8(page->aging_counter & 0xff);
  case ML_F_SFREQ:    return ml_log1p_q8(page->ml_sfreq);
  case ML_F_IDLE:     return ml_log1p_q8(now - page->ml_last_seen);
  case ML_F_AGE:      return ml_log1p_q8(now - page->ml_load_scan);
  case ML_F_DIRTY:    return page->dirty_sample ? 256 : 0;
  case ML_F_REFAULTS: return ml_log1p_q8(page->ml_refaults);
  case ML_F_RDIST:    return ml_log1p_q8(page->ml_rdist);
  }
  return 0;
}

// Sampled scoring, like cache_ext's bpf_cache_ext_list_sample: move k distinct
// random candidates to the front (partial Fisher-Yates) and let the policy
// look only at those. Pages outside the sample are neither scanned nor scored
// this time, so their accessed bits keep accumulating until a later sample.
static void
ml_sample(struct proc *p, struct vm_page **candidates, int count, int k)
{
  uint64 x = p->vm.ml_rng ? p->vm.ml_rng : 0x9E3779B97F4A7C15ULL;
  for(int i = 0; i < k; i++){
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    int j = i + (int)(x % (uint64)(count - i));
    struct vm_page *t = candidates[i];
    candidates[i] = candidates[j];
    candidates[j] = t;
  }
  p->vm.ml_rng = x;
}

static struct mlcand ml_cands[MLNET_MAXN];     // scratch for the built-in networks (frame_table.lock held)
static long long ml_scores[MLNET_MAXN];

static struct vm_page *
choose_ml(struct proc *p, struct vm_page **candidates, int count)
{
  const struct vm_ml_weights *w = &p->vm.ml;
  int net = w->model_id > 0 && w->model_id < ML_NNETS;
  int k = w->sample_k;
  if(net && (k == 0 || k > MLNET_MAXN))
    k = MLNET_MAXN;
  if(k > 0 && count > k){
    ml_sample(p, candidates, count, k);
    count = k;
  }
  uint64 now = p->vm.ml_scans;
  int cleared = 0;
  int any_old = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    int accessed = sample_page(page, 1);
    cleared |= accessed;
    page->ml_seen = accessed;
    page->aging_counter = ((page->aging_counter & 0xff) >> 1) | (accessed ? 0x80 : 0);
    if(accessed){
      page->ml_sfreq++;
      page->ml_last_seen = now;
    }
    if(now - page->ml_load_scan >= (uint64)w->protect_age)
      any_old = 1;
  }
  if(cleared)
    sfence_vma();

  if(net){
    for(int i = 0; i < count; i++){
      for(int j = 0; j < 8; j++)
        ml_cands[i].q[j] = ml_feature(p, candidates[i], j);
      ml_cands[i].aging = candidates[i]->aging_counter & 0xff;
    }
    mlnet_score(ml_nets[w->model_id], ml_cands, count, ml_scores);
  }

  struct vm_page *victim = 0;
  long best = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    if(any_old && now - page->ml_load_scan < (uint64)w->protect_age)
      continue;
    long score = 0;
    if(net){
      score = (long)ml_scores[i];
    } else {
      for(int j = 0; j < w->n; j++)
        score += (long)w->qa[j] * ml_feature(p, page, w->feat[j]);
    }
    if(victim == 0 || score > best ||
       (score == best && page->load_sequence < victim->load_sequence)){
      victim = page;
      best = score;
    }
  }
  return victim;
}

// VM_POLICY_ARCK / VM_POLICY_S3FIFO / VM_POLICY_LHD: the classical policies
// ARC, S3-FIFO and LHD in the form a kernel that only sees faults and accessed
// bits can run (the forms of tools/ml2/pagesim.c P_ARCK, P_S3SCAN, P_LHD, which
// tools/ml2/test_baselines.py checks against independent references). Hits are
// not seen when they happen: at each eviction the accessed bit of the pages is
// read, and the touch that loaded a page is ignored (cp_fresh).
//
// One process at a time owns this state (the benchmark under test); another
// process, or a new process in the same slot, starts it afresh. All of it is
// protected by frame_table.lock. Lists are doubly linked over ids: a resident
// page has its frame index, a ghost (an evicted page remembered by the swap
// slot it went to) has NPHYS_PAGES + slot. A ghost only counts as a hit if the
// faulting address and page table match the ones recorded.
#define CP_NID (NPHYS_PAGES + NSWAPSLOTS)
enum { CL_T1, CL_T2, CL_B1, CL_B2 };   // ARC; S3-FIFO: small, main, ghost
#define LHD_CL 16
#define LHD_AGES 256
#define LHD_HS 256
#define LHD_SCALE (1 << 20)

static int cp_nx[CP_NID], cp_pv[CP_NID];
static int cp_in[CP_NID];                      // list of a node, -1 if none
static int cp_head[4], cp_tail[4], cp_len[4];
static uint8 cp_freq[NPHYS_PAGES], cp_fresh[NPHYS_PAGES], cp_hint[NPHYS_PAGES];
static uint16 cp_la1[NPHYS_PAGES], cp_la2[NPHYS_PAGES];
static uint64 cp_gh_va[NSWAPSLOTS];
static pagetable_t cp_gh_pt[NSWAPSLOTS];
static long long cp_lh[LHD_CL][LHD_AGES], cp_le[LHD_CL][LHD_AGES], cp_ld[LHD_CL][LHD_AGES];
static long long cp_lnev;
static int cp_lshift;
static struct proc *cp_owner;
static int cp_pid = -1, cp_policy = -1;
static int cp_arc_p, cp_cap, cp_small_cap, cp_main_cap;
// the fault being served (set by reclaim_frame) and what to do when it commits
static int cp_new_slot;                        // swap slot the faulting page is in, -1 if none
static uint64 cp_new_va;
static pagetable_t cp_new_pt;
static int cp_new_hint;                        // 1: the loaded page goes to the main / T2 list
static int cp_evict_list;                      // ghost list for the page being evicted, -1 if none

static void
cp_remove(int id)
{
  if(id < 0)
    return;
  int l = cp_in[id];
  if(l < 0)
    return;
  if(l > CL_B2){                 // marked as seen, on no list
    cp_in[id] = -1;
    return;
  }
  int a = cp_pv[id], b = cp_nx[id];
  if(a >= 0) cp_nx[a] = b; else cp_head[l] = b;
  if(b >= 0) cp_pv[b] = a; else cp_tail[l] = a;
  cp_len[l]--;
  cp_in[id] = -1;
}

static void
cp_push_head(int l, int id)
{
  cp_pv[id] = -1;
  cp_nx[id] = cp_head[l];
  if(cp_head[l] >= 0) cp_pv[cp_head[l]] = id; else cp_tail[l] = id;
  cp_head[l] = id;
  cp_in[id] = l;
  cp_len[l]++;
}

static int
cp_idx(struct vm_page *page)
{
  return page - frame_table.pages;
}

// A frame is being freed or reused: drop it from the lists and forget its history.
static void
cp_unlink(struct vm_page *page)
{
  int id = cp_idx(page);
  cp_remove(id);
  cp_freq[id] = cp_fresh[id] = cp_hint[id] = 0;
}

static void
cp_reset(struct proc *p, int policy)
{
  for(int i = 0; i < CP_NID; i++)
    cp_in[i] = -1;
  for(int l = 0; l < 4; l++){
    cp_head[l] = cp_tail[l] = -1;
    cp_len[l] = 0;
  }
  for(int i = 0; i < NPHYS_PAGES; i++){
    cp_freq[i] = cp_fresh[i] = cp_hint[i] = 0;
    cp_la1[i] = 0;
    cp_la2[i] = LHD_AGES;
  }
  cp_owner = p;
  cp_pid = p->pid;
  cp_policy = policy;
  cp_arc_p = 0;
  cp_cap = p->vm.resident_limit;
  cp_small_cap = cp_cap / 10 > 0 ? cp_cap / 10 : 1;
  cp_main_cap = cp_cap - cp_small_cap;
  cp_lnev = 0;
  cp_lshift = 0;
  while(((long long)LHD_AGES << cp_lshift) < 4LL * cp_cap)
    cp_lshift++;
  for(int c = 0; c < LHD_CL; c++)
    for(int a = 0; a < LHD_AGES; a++){
      cp_lh[c][a] = cp_le[c][a] = 0;
      cp_ld[c][a] = (long long)LHD_SCALE * (c + 1) / (a + 1);
    }
}

// Every resident page must be in a list: pages loaded since the last eviction
// are not yet (candidates come in load order, as the owned list keeps them).
static void
cp_sync(struct vm_page **candidates, int count, int policy)
{
  for(int i = 0; i < count; i++){
    int id = cp_idx(candidates[i]);
    if(cp_in[id] >= 0)
      continue;
    cp_freq[id] = 0;
    cp_fresh[id] = 1;
    cp_la1[id] = 0;
    cp_la2[id] = LHD_AGES;
    if(policy != VM_POLICY_LHD)
      cp_push_head(cp_hint[id] ? CL_T2 : CL_T1, id);
    else
      cp_in[id] = 7;            // LHD keeps no lists; mark as seen
    cp_hint[id] = 0;
  }
}

// read and clear the accessed bit of a listed page; 1 if it counts as a hit
static int
cp_examine(struct vm_page *page)
{
  int id = cp_idx(page);
  int a = sample_page(page, 1);
  if(cp_fresh[id]){
    cp_fresh[id] = 0;
    return 0;
  }
  return a;
}

static int
cp_ghost_hit(void)
{
  if(cp_new_slot < 0)
    return -1;
  int id = NPHYS_PAGES + cp_new_slot;
  if(cp_in[id] < 0 || cp_gh_va[cp_new_slot] != cp_new_va || cp_gh_pt[cp_new_slot] != cp_new_pt)
    return -1;
  return cp_in[id];
}

static struct vm_page *
cp_page(int id)
{
  return id < 0 ? 0 : &frame_table.pages[id];
}

// ARC with accessed-bit promotion: walk T1 then T2 from the least recent end;
// a page found accessed moves to the head of T2, as an ARC hit would have.
static struct vm_page *
choose_arck(struct vm_page **candidates, int count)
{
  cp_sync(candidates, count, VM_POLICY_ARCK);
  int cleared = 0;
  for(int l = CL_T1; l <= CL_T2; l++){
    int id = cp_tail[l];
    while(id >= 0){
      int toward_head = cp_pv[id];
      struct vm_page *page = &frame_table.pages[id];
      int fresh = cp_fresh[id];
      int hit = cp_examine(page);
      cleared |= hit | fresh;
      if(hit){
        cp_remove(id);
        cp_push_head(CL_T2, id);
      }
      id = toward_head;
    }
  }
  if(cleared)
    sfence_vma();

  int c = cp_cap, v = -1, w = cp_ghost_hit();
  int gid = cp_new_slot >= 0 ? NPHYS_PAGES + cp_new_slot : -1;
  cp_evict_list = -1;
  if(w == CL_B1 || w == CL_B2){
    int in_b2 = w == CL_B2;
    int mine = in_b2 ? CL_B2 : CL_B1, other = in_b2 ? CL_B1 : CL_B2;
    int d = cp_len[mine] >= cp_len[other] ? 1 : cp_len[other] / cp_len[mine];
    if(in_b2)
      cp_arc_p = cp_arc_p - d > 0 ? cp_arc_p - d : 0;
    else
      cp_arc_p = cp_arc_p + d < c ? cp_arc_p + d : c;
    if(cp_len[CL_T1] >= 1 && ((in_b2 && cp_len[CL_T1] == cp_arc_p) || cp_len[CL_T1] > cp_arc_p)){
      v = cp_tail[CL_T1]; cp_evict_list = CL_B1;
    } else {
      v = cp_tail[CL_T2]; cp_evict_list = CL_B2;
    }
    if(v >= 0)
      cp_remove(v);
    cp_remove(gid);
    cp_new_hint = 1;
  } else {
    int l1 = cp_len[CL_T1] + cp_len[CL_B1];
    int tot = l1 + cp_len[CL_T2] + cp_len[CL_B2];
    int replace = 0;
    if(l1 == c){
      if(cp_len[CL_T1] < c){
        cp_remove(cp_tail[CL_B1]);
        replace = 1;
      } else {
        v = cp_tail[CL_T1];
        if(v >= 0)
          cp_remove(v);
      }
    } else if(tot >= c){
      if(tot == 2 * c)
        cp_remove(cp_tail[CL_B2]);
      replace = 1;
    }
    if(replace){
      if(cp_len[CL_T1] >= 1 && cp_len[CL_T1] > cp_arc_p){
        v = cp_tail[CL_T1]; cp_evict_list = CL_B1;
      } else {
        v = cp_tail[CL_T2]; cp_evict_list = CL_B2;
      }
      if(v >= 0)
        cp_remove(v);
    }
    cp_new_hint = 0;
  }
  return cp_page(v);
}

// S3-FIFO: a small queue (a tenth of the memory) in front of the main queue,
// a ghost queue the size of main. A page reaching a queue head has its counter
// raised from the accessed bit (cap 3).
static void
cp_s3_examine(struct vm_page *page, int *cleared)
{
  int id = cp_idx(page);
  int fresh = cp_fresh[id];
  int hit = cp_examine(page);
  *cleared |= hit | fresh;
  if(hit && cp_freq[id] < 3)
    cp_freq[id]++;
}

static int
cp_s3_evict_main(int *cleared)
{
  for(int guard = 0; guard < 4 * NPHYS_PAGES; guard++){
    int t = cp_tail[CL_T2];
    if(t < 0)
      return -1;
    cp_s3_examine(&frame_table.pages[t], cleared);
    cp_remove(t);
    if(cp_freq[t] > 0){
      cp_freq[t]--;
      cp_push_head(CL_T2, t);
    } else {
      return t;
    }
  }
  return -1;
}

static struct vm_page *
choose_s3fifo(struct vm_page **candidates, int count)
{
  cp_sync(candidates, count, VM_POLICY_S3FIFO);
  int cleared = 0, v = -1;
  cp_evict_list = -1;
  if(cp_len[CL_T1] * 10 >= cp_cap || cp_len[CL_T2] == 0){
    while(cp_len[CL_T1] > 0){
      int t = cp_tail[CL_T1];
      cp_s3_examine(&frame_table.pages[t], &cleared);
      cp_remove(t);
      if(cp_freq[t] > 1){
        cp_push_head(CL_T2, t);
        if(cp_len[CL_T2] > cp_main_cap){
          v = cp_s3_evict_main(&cleared);
          break;
        }
      } else {
        v = t;
        cp_evict_list = CL_B1;          // goes to the ghost queue when its slot is known
        break;
      }
    }
  }
  if(v < 0 && cp_evict_list < 0)
    v = cp_s3_evict_main(&cleared);
  if(cleared)
    sfence_vma();
  // a ghost hit puts the loaded page straight into main (checked after the eviction, as in the paper)
  int w = cp_ghost_hit();
  cp_new_hint = w == CL_B1;
  if(w == CL_B1)
    cp_remove(NPHYS_PAGES + cp_new_slot);
  return cp_page(v);
}

// LHD (Beckmann et al., NSDI 2018): evict the page with the lowest expected
// hits per unit of space-time, estimated per (class, age) from histograms of
// the ages at which pages were hit and evicted. Follows cache_ext's port; time
// is counted in eviction scans, a "hit" is a page found accessed at a scan, and
// the estimate is renewed every 4*cap+256 evictions.
static int
cp_lhd_class(long long sum)
{
  if(sum == 0)
    return 0;
  int c = 0;
  while(sum < LHD_AGES && c < LHD_CL - 1){
    sum <<= 1;
    c++;
  }
  return c;
}

static int
cp_lhd_bucket(struct proc *p, struct vm_page *page)
{
  long long a = (long long)(p->vm.ml_scans - page->ml_last_seen) >> cp_lshift;
  return a >= LHD_AGES ? LHD_AGES - 1 : (int)a;
}

static void
cp_lhd_reconfigure(void)
{
  for(int c = 0; c < LHD_CL; c++){
    for(int a = 0; a < LHD_AGES; a++){
      cp_lh[c][a] = cp_lh[c][a] * 9 / 10;
      cp_le[c][a] = cp_le[c][a] * 9 / 10;
    }
    long long hits = cp_lh[c][LHD_AGES - 1], events = hits + cp_le[c][LHD_AGES - 1], life = events;
    for(int a = LHD_AGES - 2; a >= 0; a--){
      hits += cp_lh[c][a];
      events += cp_lh[c][a] + cp_le[c][a];
      life += events;
      cp_ld[c][a] = events > LHD_HS ? hits * LHD_SCALE / life : 0;
    }
  }
}

static struct vm_page *
choose_lhd(struct proc *p, struct vm_page **candidates, int count)
{
  cp_sync(candidates, count, VM_POLICY_LHD);
  cp_evict_list = -1;
  cp_new_hint = 0;
  uint64 now = p->vm.ml_scans;
  int cleared = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    int id = cp_idx(page);
    int fresh = cp_fresh[id];
    int hit = cp_examine(page);
    cleared |= hit | fresh;
    if(!hit)
      continue;
    int b = cp_lhd_bucket(p, page);
    cp_lh[cp_lhd_class((long long)cp_la1[id] + cp_la2[id])][b] += LHD_HS;
    cp_la2[id] = cp_la1[id];
    cp_la1[id] = b;
    page->ml_last_seen = now;
  }
  if(cleared)
    sfence_vma();
  struct vm_page *best = 0;
  long long bd = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    int id = cp_idx(page), b = cp_lhd_bucket(p, page);
    long long d = b == LHD_AGES - 1 ? 0 : cp_ld[cp_lhd_class((long long)cp_la1[id] + cp_la2[id])][b];
    if(best == 0 || d < bd || (d == bd && page->load_sequence < best->load_sequence)){
      best = page;
      bd = d;
    }
  }
  if(best){
    int id = cp_idx(best);
    cp_le[cp_lhd_class((long long)cp_la1[id] + cp_la2[id])][cp_lhd_bucket(p, best)] += LHD_HS;
    if(++cp_lnev >= 4LL * cp_cap + 256){
      cp_lnev = 0;
      cp_lhd_reconfigure();
    }
  }
  return best;
}

static int
cp_policy_is_classic(int policy)
{
  return policy == VM_POLICY_ARCK || policy == VM_POLICY_S3FIFO || policy == VM_POLICY_LHD;
}

// The victim is committed (its slot is known): remember it as a ghost.
static void
cp_on_evict(struct vm_page *victim, int slot, struct proc *p)
{
  if(!cp_policy_is_classic(p->vm.policy) || cp_owner != p)
    return;
  int id = cp_idx(victim);
  cp_remove(id);                     // in case a fallback victim was still listed
  if(cp_evict_list < 0)
    return;
  int g = NPHYS_PAGES + slot;
  cp_remove(g);
  cp_gh_va[slot] = victim->va;
  cp_gh_pt[slot] = victim->pagetable;
  cp_push_head(cp_evict_list, g);
  if(p->vm.policy == VM_POLICY_S3FIFO && cp_len[CL_B1] > cp_main_cap)
    cp_remove(cp_tail[CL_B1]);
  cp_evict_list = -1;
}

static struct vm_page *
choose_policy_victim(struct proc *p, int count, int *fallback)
{
  if(count == 0)
    return 0;
  struct vm_page *victim;
#ifdef VM_DEBUG
  if(p->vm.invalid_policy_once){
    p->vm.invalid_policy_once = 0;
    victim = (struct vm_page *)1;
  } else
#endif
  if(p->vm.policy == VM_POLICY_FIFO)
    victim = choose_fifo(frame_table.candidates, count);
  else if(p->vm.policy == VM_POLICY_CLOCK)
    victim = choose_clock(p, frame_table.candidates, count);
  else if(p->vm.policy == VM_POLICY_AGING)
    victim = choose_aging(frame_table.candidates, count);
  else if(p->vm.policy == VM_POLICY_LFU)
    victim = choose_lfu(frame_table.candidates, count);
  else if(p->vm.policy == VM_POLICY_ML)
    victim = choose_ml(p, frame_table.candidates, count);
  else if(cp_policy_is_classic(p->vm.policy)){
    if(cp_owner != p || cp_pid != p->pid || cp_policy != p->vm.policy)
      cp_reset(p, p->vm.policy);
    cp_new_hint = 0;
    if(p->vm.policy == VM_POLICY_ARCK)
      victim = choose_arck(frame_table.candidates, count);
    else if(p->vm.policy == VM_POLICY_S3FIFO)
      victim = choose_s3fifo(frame_table.candidates, count);
    else
      victim = choose_lhd(p, frame_table.candidates, count);
  } else
    victim = 0;

  int valid = 0;
  for(int i = 0; i < count; i++)
    if(victim == frame_table.candidates[i] && page_is_candidate(p, victim)){
      valid = 1;
      break;
    }
  if(!valid){
    *fallback = 1;
    victim = choose_clock(p, frame_table.candidates, count);
  }
  return victim;
}

static int
reclaim_frame(struct proc *p, pagetable_t newpt, uint64 newva, int purpose,
              uint64 *result)
{
  struct vm_page *victim = 0;
  int fallback = 0;

  uint64 path_start = r_time();
  acquire(&frame_table.lock);
  // Walk only this process's own owned-frame list rather than scanning
  // every physical frame in the system: page_is_candidate() already
  // requires page->owner == p, so every frame reachable from any other
  // process's list can never contribute a candidate here anyway. This
  // bounds eviction cost by the faulting process's own resident set
  // instead of total physical memory.
  int candidate_count = 0;
  for(struct vm_page *candidate = p->vm.owned_head; candidate != 0;
      candidate = candidate->owner_next){
    if(page_is_candidate(p, candidate))
      frame_table.candidates[candidate_count++] = candidate;
  }
  cp_new_slot = -1;
  cp_new_va = newva;
  cp_new_pt = newpt;
  if(cp_policy_is_classic(p->vm.policy)){
    pte_t *npte = walk(newpt, newva, 0);
    if(npte && (*npte & PTE_SWAPPED) && !(*npte & PTE_V))
      cp_new_slot = PTE2SLOT(*npte);
  }
  uint64 select_start = r_time();
  uint64 collect_ticks = select_start - path_start;
  victim = choose_policy_victim(p, candidate_count, &fallback);
  uint64 select_ticks = r_time() - select_start;
  if(victim == 0){
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  if(p->vm.log_victims)
    printk("VICTIM %lu %lx %d\n", p->vm.ml_scans, victim->va >> 12, candidate_count);
  sample_page(victim, 0);
  // The A and D bits the policy actually saw, captured before anything
  // clears them. Without this the trace recorded which page was evicted but
  // nothing about why: VICTIM_SELECTED and EVICT_BEGIN passed VMTRACE_NONE
  // for pte_flags and EVICT_END masked PTE_A and PTE_D out, so "was the
  // victim referenced" -- the single most informative feature a replacement
  // policy has -- was unrecoverable from a capture.
  pte_t *victim_pte = walk(victim->pagetable, victim->va, 0);
  uint64 victim_flags =
    victim_pte ? PTE_FLAGS(*victim_pte) : (uint64)VMTRACE_NONE;
  int wasted_prefetch = victim->state == VM_PAGE_RESIDENT_PREFETCH;
  enum vm_page_state victim_state = victim->state;
  victim->busy = 1;
  victim->state = VM_PAGE_EVICTING;
  victim->pin_count = 1;
  uint64 pa = victim->pa;
  uint64 victimva = victim->va;
  pagetable_t victimpt = victim->pagetable;
  int victim_backing = victim->backing_slot;
  release(&frame_table.lock);

  vmtrace_emit(p, VMTRACE_VICTIM_SELECTED, newva, -1, victim_state,
               victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
               victimva, VMTRACE_NONE, 0);
  vmtrace_emit(p, VMTRACE_EVICT_BEGIN, victimva, -1, victim_state,
               victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
               victimva, VMTRACE_NONE, 0);

  if(fallback){
    acquire(&p->vm.lock);
    p->vm.stats.policy_fallbacks++;
    release(&p->vm.lock);
    vmtrace_emit(p, VMTRACE_POLICY_FALLBACK, newva, -1, victim_state,
                 victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
                 victimva, VMTRACE_NONE, 0);
  }
  if(wasted_prefetch){
    acquire(&p->vm.lock);
    p->vm.stats.prefetch_wasted++;
    release(&p->vm.lock);
    vmtrace_emit(p, VMTRACE_PREFETCH_WASTE, victimva, -1, victim_state,
                 victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
                 VMTRACE_NONE, VMTRACE_NONE, 0);
  }

  pte_t *pte = walk(victimpt, victimva, 0);
  int clean_backing = victim_backing >= 0 && swap_slot_valid(victim_backing) &&
    pte != 0 && (*pte & PTE_D) == 0;
  int slot = clean_backing ? victim_backing : swap_slot_alloc();
  int new_slot = !clean_backing;
  if(slot < 0 || pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != pa){
    if(new_slot && slot >= 0)
      swap_slot_put(slot);
    acquire(&frame_table.lock);
    victim = page_for_pa(pa);
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = victim_state;
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  uint report_flags = PTE_FLAGS(*pte);
  uint flags = report_flags &
    ~(PTE_V | PTE_SWAPPED | PTE_BUSY | PTE_A | PTE_D);
  if(new_slot)
    vmtrace_emit(p, VMTRACE_SWAP_WRITE_BEGIN, victimva, -1, victim_state,
                 report_flags, (pa - KERNBASE) / PGSIZE, slot, VMTRACE_NONE,
                 VMTRACE_NONE, 0);
  uint64 io_start = r_time();
  int wrote = new_slot ? swap_page_write(slot, pa) : 0;
  uint64 io_ticks = r_time() - io_start;     // waiting for the swap-out, excluded from path_ticks
  if(new_slot && wrote < 0){
    vmtrace_emit(p, VMTRACE_SWAP_WRITE_END, victimva, -1, victim_state,
                 report_flags, (pa - KERNBASE) / PGSIZE, slot, VMTRACE_NONE,
                 VMTRACE_NONE, -1);
    swap_slot_put(slot);
    acquire(&frame_table.lock);
    victim = page_for_pa(pa);
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = victim_state;
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  if(new_slot)
    vmtrace_emit(p, VMTRACE_SWAP_WRITE_END, victimva, -1, victim_state,
                 report_flags, (pa - KERNBASE) / PGSIZE, slot, VMTRACE_NONE,
                 VMTRACE_NONE, 0);

  acquire(&frame_table.lock);
  victim = page_for_pa(pa);
  if(victim->owner != p || victim->pagetable != victimpt ||
     victim->va != victimva || victim->state != VM_PAGE_EVICTING ||
     pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != pa){
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = victim_state;
    release(&frame_table.lock);
    if(new_slot)
      swap_slot_put(slot);
    return VM_FRAME_ERROR;
  }
  *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
  slot_evict_scan[slot] = p->vm.ml_scans;
  slot_refaults[slot] = victim->ml_refaults;
  p->vm.ml_scans++;
  cp_on_evict(victim, slot, p);
  setup_page(victim, p, newpt, newva, purpose);
  if(cp_policy_is_classic(p->vm.policy) && cp_owner == p)
    cp_hint[cp_idx(victim)] = cp_new_hint;
  release(&frame_table.lock);
  sfence_vma();
  vmtrace_emit(p, VMTRACE_EVICT_END, victimva, -1, victim_state,
               report_flags, (pa - KERNBASE) / PGSIZE, slot, newva,
               VMTRACE_NONE, 0);

  // A clean page transfers its retained backing reference to the swapped
  // PTE.  A dirty page receives a private slot, so release its old immutable
  // backing only after the new PTE is committed.
  if(new_slot && victim_backing >= 0)
    swap_slot_put(victim_backing);

  acquire(&p->vm.lock);
  p->vm.stats.evictions++;
  p->vm.stats.select_ticks += select_ticks;
  p->vm.stats.candidates_scanned += candidate_count;
  p->vm.stats.collect_ticks += collect_ticks;
  p->vm.stats.path_ticks += r_time() - path_start - io_ticks;
  release(&p->vm.lock);
  *result = pa;
  return VM_FRAME_OK;
}

void
vmpage_init(void)
{
  initlock(&frame_table.lock, "vmpage");
  for(int i = 0; i < CP_NID; i++)
    cp_in[i] = -1;
  for(uint64 i = 0; i < NPHYS_PAGES; i++){
    frame_table.pages[i].pa = KERNBASE + i * PGSIZE;
    clear_page(&frame_table.pages[i]);
  }
}

int
vm_frame_acquire(struct proc *p, pagetable_t pagetable, uint64 va,
                 int purpose, uint64 *pa)
{
  if(p == 0 || pagetable == 0 || pa == 0 || va % PGSIZE != 0)
    return VM_FRAME_ERROR;

#ifdef VM_DEBUG
  if(vmdebug_should_fail(VM_FAIL_FRAME_ALLOC))
    return VM_FRAME_ERROR;
#endif

  acquire(&p->vm.lock);
  if(p->vm.resident_limit != VM_LIMIT_UNLIMITED &&
     p->vm.resident_count >= p->vm.resident_limit){
    release(&p->vm.lock);
    return reclaim_frame(p, pagetable, va, purpose, pa);
  }
  p->vm.resident_count++;
  release(&p->vm.lock);

  uint64 mem = (uint64)kalloc();
  if(mem == 0){
    acquire(&p->vm.lock);
    p->vm.resident_count--;
    release(&p->vm.lock);
    return VM_FRAME_ERROR;
  }

  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(mem);
  if(page == 0 || page->owner != 0)
    panic("vm_frame_acquire metadata");
  setup_page(page, p, pagetable, va, purpose);
  release(&frame_table.lock);
  *pa = mem;
  return VM_FRAME_OK;
}

int
vm_frame_release(uint64 pa)
{
  struct proc *owner;
  int backing_slot;

  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0){
    release(&frame_table.lock);
    return -1;
  }
  owner = page->owner;
  backing_slot = page->backing_slot;
  clear_page(page);
  release(&frame_table.lock);

  acquire(&owner->vm.lock);
  if(owner->vm.resident_count == 0)
    panic("vm_frame_release count");
  owner->vm.resident_count--;
  release(&owner->vm.lock);
  if(backing_slot >= 0 && swap_slot_put(backing_slot) < 0)
    panic("vm_frame_release backing");
  kfree((void *)pa);
  return 0;
}

int
vm_frame_pin(uint64 pa)
{
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0){
    release(&frame_table.lock);
    return -1;
  }
  page->pin_count++;
  release(&frame_table.lock);
  return 0;
}

int
vm_frame_unpin(uint64 pa)
{
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0 || page->pin_count == 0){
    release(&frame_table.lock);
    return -1;
  }
  page->pin_count--;
  if(page->pin_count == 0)
    page->busy = 0;
  release(&frame_table.lock);
  return 0;
}

int
vm_frame_set_backing(uint64 pa, int slot)
{
  if(!swap_slot_valid(slot))
    return -1;
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0 || page->backing_slot >= 0){
    release(&frame_table.lock);
    return -1;
  }
  page->backing_slot = slot;
  // The page came back from swap: a refault, and how many of its owner's
  // evictions ago it was written out.
  page->ml_refaults = slot_refaults[slot] + 1;
  page->ml_rdist = page->owner->vm.ml_scans - slot_evict_scan[slot];
  release(&frame_table.lock);
  return 0;
}

void
vm_frame_note_access(uint64 pa, int dirty)
{
  struct proc *owner = 0;
  uint64 useful_va = VMTRACE_NONE;
  int useful_slot = -1;
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page && page->owner){
    page->referenced_sample = 1;
    page->frequency++;
    if(dirty)
      page->dirty_sample = 1;
    if(page->state == VM_PAGE_RESIDENT_PREFETCH){
      page->state = VM_PAGE_RESIDENT_DEMAND;
      owner = page->owner;
      useful_va = page->va;
      useful_slot = page->backing_slot;
    }
  }
  release(&frame_table.lock);
  if(owner){
    acquire(&owner->vm.lock);
    owner->vm.stats.prefetch_useful++;
    release(&owner->vm.lock);
    vmtrace_emit(owner, VMTRACE_PREFETCH_USE, useful_va, -1,
                 VM_PAGE_RESIDENT_DEMAND, VMTRACE_NONE,
                 (pa - KERNBASE) / PGSIZE, useful_slot, VMTRACE_NONE,
                 VMTRACE_NONE, dirty);
  }
}

int
vm_frame_is_candidate(struct proc *p, uint64 pa)
{
  int result;
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  result = page != 0 && page->owner == p && page->pin_count == 0 &&
           page->busy == 0 && (page->state == VM_PAGE_RESIDENT_DEMAND ||
                               page->state == VM_PAGE_RESIDENT_PREFETCH);
  release(&frame_table.lock);
  return result;
}

int
vm_reclaim_to_limit(struct proc *p)
{
  for(;;){
    acquire(&p->vm.lock);
    uint64 count = p->vm.resident_count;
    uint64 limit = p->vm.resident_limit;
    release(&p->vm.lock);
    if(limit == VM_LIMIT_UNLIMITED || count <= limit)
      return 0;
    uint64 pa;
    if(reclaim_frame(p, p->pagetable, TRAPFRAME, VM_FRAME_CONSTRUCTION, &pa) !=
       VM_FRAME_OK)
      return -1;
    if(vm_frame_release(pa) < 0)
      return -1;
  }
}

int
vmpage_debug_test(int operation)
{
#ifdef VM_DEBUG
  struct proc *p = myproc();
  if(operation == VM_TEST_POLICY_INVALID){
    acquire(&p->vm.lock);
    p->vm.invalid_policy_once = 1;
    release(&p->vm.lock);
    return 0;
  }
  uint64 pa;
  uint64 va = PGROUNDUP(p->sz);
  if(vm_frame_acquire(p, p->pagetable, va, VM_FRAME_DEMAND, &pa) !=
     VM_FRAME_OK)
    return -1;
  if(operation == VM_TEST_FRAME_PIN){
    int ok = !vm_frame_is_candidate(p, pa) && vm_frame_unpin(pa) == 0 &&
             vm_frame_is_candidate(p, pa);
    vm_frame_release(pa);
    return ok ? 0 : -1;
  }
  if(operation == VM_TEST_FRAME_METADATA){
    int test_slot = swap_slot_alloc();
    if(test_slot < 0){
      vm_frame_release(pa);
      return -1;
    }
    acquire(&frame_table.lock);
    struct vm_page *page = page_for_pa(pa);
    int clean = page->owner == p && page->pagetable == p->pagetable &&
                page->va == va && page->backing_slot == -1 &&
                page->prefetch_request_id == 0 && page->frequency == 0 &&
                page->aging_counter == 0xff;
    page->backing_slot = test_slot;
    page->prefetch_request_id = 99;
    page->frequency = 42;
    page->aging_counter = 0x12;
    release(&frame_table.lock);
    vm_frame_release(pa);
    if(!clean)
      return -1;
    uint64 reused;
    if(vm_frame_acquire(p, p->pagetable, va, VM_FRAME_DEMAND, &reused) !=
       VM_FRAME_OK)
      return -1;
    acquire(&frame_table.lock);
    page = page_for_pa(reused);
    clean = reused == pa && page->backing_slot == -1 &&
            page->prefetch_request_id == 0 && page->frequency == 0 &&
            page->aging_counter == 0xff;
    release(&frame_table.lock);
    vm_frame_release(reused);
    return clean ? 0 : -1;
  }
  vm_frame_release(pa);
#endif
  return -1;
}

int
vmpage_check_proc(struct proc *p)
{
  uint64 count = 0;

  acquire(&frame_table.lock);
  for(uint64 i = 0; i < NPHYS_PAGES; i++){
    struct vm_page *page = &frame_table.pages[i];
    if(page->owner != p)
      continue;
    count++;
    if(page->pagetable != p->pagetable || page->va % PGSIZE != 0 ||
       page->state == VM_PAGE_FREE){
      printk("vmcheck pid=%d va=%p pa=%p state=%d owner mismatch\n",
             p->pid, (void *)page->va, (void *)page->pa, page->state);
      release(&frame_table.lock);
      return -1;
    }
    pte_t *pte = walk(page->pagetable, page->va, 0);
    if(pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != page->pa){
      printk("vmcheck pid=%d va=%p pa=%p state=%d pte mismatch\n",
             p->pid, (void *)page->va, (void *)page->pa, page->state);
      release(&frame_table.lock);
      return -1;
    }
  }

  // Cross-check the owned-frame list reclaim_frame() now relies on against
  // the full-table scan above, which remains the independent ground truth:
  // every page found by owner-field alone must also be reachable from
  // p->vm.owned_head exactly once, and the list must contain nothing else.
  uint64 listed = 0;
  for(struct vm_page *page = p->vm.owned_head; page != 0;
      page = page->owner_next){
    if(page->owner != p){
      printk("vmcheck pid=%d owned-list entry pa=%p owner mismatch\n",
             p->pid, (void *)page->pa);
      release(&frame_table.lock);
      return -1;
    }
    listed++;
  }
  if(listed != count){
    printk("vmcheck pid=%d owned-list count=%d scan count=%d mismatch\n",
           p->pid, (int)listed, (int)count);
    release(&frame_table.lock);
    return -1;
  }
  release(&frame_table.lock);

  for(uint64 va = 0; va < p->sz; va += PGSIZE){
    pte_t *pte = walk(p->pagetable, va, 0);
    if(pte == 0)
      continue;
    if((*pte & PTE_V) && (*pte & PTE_SWAPPED)){
      printk("vmcheck pid=%d va=%p valid+swapped\n", p->pid, (void *)va);
      return -1;
    }
    if((*pte & PTE_SWAPPED) && !swap_slot_valid(PTE2SLOT(*pte))){
      printk("vmcheck pid=%d va=%p invalid slot=%d\n", p->pid,
             (void *)va, PTE2SLOT(*pte));
      return -1;
    }
  }

  acquire(&p->vm.lock);
  int ok = count == p->vm.resident_count &&
           (p->vm.resident_limit == VM_LIMIT_UNLIMITED ||
            count <= p->vm.resident_limit) &&
           p->vm.queued_prefetch == 0 && p->vm.inflight_io == 0;
  if(!ok)
    printk("vmcheck pid=%d resident=%d expected=%d limit=%d\n", p->pid,
           (int)count, (int)p->vm.resident_count, (int)p->vm.resident_limit);
  release(&p->vm.lock);
  return ok ? 0 : -1;
}
