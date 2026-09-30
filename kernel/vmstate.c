#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmstats.h"
#include "mlweights.h"

static void
clear_stats(struct vmstate *vm)
{
  uint64 generation = vm->generation;
  memset(&vm->stats, 0, sizeof(vm->stats));
  vm->stats.version = VMSTATS_VERSION;
  vm->stats.generation = generation;
}

void
vmstate_init(struct proc *p)
{
  initlock(&p->vm.lock, "vmstate");
  p->vm.generation = 0;
  vmstate_reset(p);
}

void
vmstate_reset(struct proc *p)
{
  acquire(&p->vm.lock);
  p->vm.resident_limit = VM_LIMIT_UNLIMITED;
  p->vm.resident_count = 0;
  p->vm.policy = VM_POLICY_FIFO;
  p->vm.prefetch_enabled = 0;
  p->vm.prefetch_async = 0;
  p->vm.prefetch_automatic = 0;
  p->vm.exiting = 0;
  p->vm.queued_prefetch = 0;
  p->vm.inflight_io = 0;
  p->vm.clock_hand = 0;
  p->vm.prefetch_head = 0;
  p->vm.prefetch_count = 0;
  p->vm.next_prefetch_id = 1;
  p->vm.ml = ml_default_weights;
  p->vm.ml_scans = 0;
#ifdef VM_DEBUG
  p->vm.invalid_policy_once = 0;
#endif
  p->vm.generation++;
  clear_stats(&p->vm);
  release(&p->vm.lock);
}

void
vmstate_inherit(struct proc *child, struct proc *parent)
{
  acquire(&parent->vm.lock);
  acquire(&child->vm.lock);
  child->vm.resident_limit = parent->vm.resident_limit;
  child->vm.policy = parent->vm.policy;
  child->vm.prefetch_enabled = parent->vm.prefetch_enabled;
  child->vm.prefetch_async = parent->vm.prefetch_async;
  child->vm.prefetch_automatic = parent->vm.prefetch_automatic;
  child->vm.clock_hand = 0;
  child->vm.ml = parent->vm.ml;
  child->vm.ml_scans = 0;
  child->vm.prefetch_head = 0;
  child->vm.prefetch_count = 0;
  child->vm.next_prefetch_id = 1;
  clear_stats(&child->vm);
  release(&child->vm.lock);
  release(&parent->vm.lock);
}

void
vmstate_exec_reset(struct proc *p)
{
  acquire(&p->vm.lock);
  p->vm.prefetch_head = 0;
  p->vm.prefetch_count = 0;
  p->vm.queued_prefetch = 0;
  p->vm.inflight_io = 0;
  clear_stats(&p->vm);
  release(&p->vm.lock);
}

// Checked copy of a user's model into the process: feature ids in range,
// no more than ML_NFEAT of them, a sane probation.
static int
set_ml_weights(struct proc *p, uint64 addr)
{
  struct vm_ml_weights w;
  // copyin can fault (this is a paging system), so it runs before any
  // spinlock is held.
  if(copyin(p->pagetable, p->sz, (char *)&w, addr, sizeof(w)) < 0)
    return -1;
  if(w.n < 1 || w.n > ML_NFEAT || w.protect_age < 0 || w.protect_age > 1024)
    return -1;
  for(int j = 0; j < w.n; j++)
    if(w.feat[j] < 0 || w.feat[j] >= ML_NFEAT)
      return -1;
  acquire(&p->vm.lock);
  p->vm.ml = w;
  release(&p->vm.lock);
  return 0;
}

int
vmstate_ctl(struct proc *p, int command, uint64 value)
{
  int result = 0;

  if(command == VM_SET_ML_WEIGHTS)
    return set_ml_weights(p, value);

  acquire(&p->vm.lock);
  switch(command){
  case VM_SET_LIMIT:
    if(value > VM_MAX_RESIDENT_LIMIT ||
       (value != VM_LIMIT_UNLIMITED && value < p->vm.resident_count))
      result = -1;
    else
      p->vm.resident_limit = value;
    break;
  case VM_SET_POLICY:
    if(value >= VM_POLICY_COUNT)
      result = -1;
    else
      p->vm.policy = value;
    break;
  case VM_PREFETCH_ENABLE:
    if(value > 1)
      result = -1;
    else
      p->vm.prefetch_enabled = value;
    break;
  case VM_RESET_STATS:
    if(value != 0)
      result = -1;
    else
      clear_stats(&p->vm);
    break;
  case VM_PREFETCH_MODE:
    if(value > 1 || p->vm.inflight_io != 0 || p->vm.prefetch_count != 0)
      result = -1;
    else
      p->vm.prefetch_async = value;
    break;
  case VM_PREFETCH_AUTOMATIC:
    if(value > 1)
      result = -1;
    else
      p->vm.prefetch_automatic = value;
    break;
  case VM_TRACE_ENABLE:
  case VM_TRACE_RESET:
  case VM_TRACE_SET_CAPACITY:
  case VM_TRACE_SET_MASK:
    result = vmtrace_control(command, value);
    break;
  default:
    result = -1;
    break;
  }
  release(&p->vm.lock);
  return result;
}

void
vmstate_snapshot(struct proc *p, struct vmstats *out)
{
  acquire(&p->vm.lock);
  *out = p->vm.stats;
  out->version = VMSTATS_VERSION;
  out->resident_limit = p->vm.resident_limit;
  out->resident_count = p->vm.resident_count;
  out->policy = p->vm.policy;
  out->prefetch_enabled = p->vm.prefetch_enabled;
  out->prefetch_async = p->vm.prefetch_async;
  out->prefetch_automatic = p->vm.prefetch_automatic;
  out->generation = p->vm.generation;
  out->queued_prefetch = p->vm.queued_prefetch;
  out->inflight_io = p->vm.inflight_io;
  release(&p->vm.lock);
  out->free_swap_slots = swap_free_slots();
}
