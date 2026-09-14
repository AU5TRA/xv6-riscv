// tracereplay: replays a slice of a REAL SQLite/Redis memory-access
// trace (collected on Linux, see tools/collect_linux_trace.sh /
// tools/trace_reduce.py) as real memory touches inside xv6, so the
// actual kernel paging code (not tools/sim.py's host-side simulator)
// faults/evicts on real-application access patterns.
//
// SCOPE, stated plainly (HANDOFF_PROMPT.md's own "be honest here"
// requirement): this is a feasibility investigation, not a general
// -purpose trace replayer. The full real-Redis trace is 12.3M
// references / 70MB; xv6's per-file cap is MAXFILE = NDIRECT(12) +
// NINDIRECT(BSIZE/sizeof(uint)=256) = 268 blocks = 268KB (kernel/fs.h)
// -- far tighter than the ~6.3MB of aggregate free filesystem space
// (FSSIZE=8000 blocks, kernel/param.h), and the actual binding
// constraint. This program replays the first 825,000 references
// (about 6.7% of the full trace) of traces/real/redis_real.trace,
// pre-split on the host into 16 files (redisreplay0 .. redisreplay15,
// see tools/gen_tracereplay_chunks.py) each safely under the 268KB cap.
// Every chunk line is a bare "T <vpn>" line, same convention as the
// project's usual trace format, just without the TRACEHDR (metadata is
// hardcoded below instead, since this is a fixed, purpose-built slice).
//
// KNOWN LIMITATION, also stated plainly: tools/trace_reduce.py collapses
// Valgrind Lackey's L (load) and S (store) lines into one undifferentiated
// "T <vpn>" reference, so the read/write distinction from the original
// real trace is already lost upstream of this program -- it cannot be
// recovered here. Every replayed reference uses touch_w() rather than
// touch_r(), the more conservative choice: it exercises both PTE_A and
// PTE_D (and therefore the write-back path), whereas replaying
// everything read-only would never exercise dirty-page write-back at
// all. This means eviction/write-back counts here are an upper bound on
// what real SQLite/Redis's own read/write mix would produce, not an
// exact reproduction of it.
//
// ARENA_PAGES=835 (not the real trace's own arena_pages=1416) because
// the max VPN actually referenced within this 825,000-reference PREFIX
// is 834 -- later pages in the full trace are simply never reached by
// this slice, so sizing the arena to the full trace's range would only
// allocate unused address space.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define ARENA_PAGES 835
#define NUM_CHUNKS 16
#define READ_BUF_SIZE 4096 // one page -- see the note below on why this
                            // must stay small, not a whole-chunk buffer

static const char *CHUNK_FILES[NUM_CHUNKS] = {
  "redisreplay0",  "redisreplay1",  "redisreplay2",  "redisreplay3",
  "redisreplay4",  "redisreplay5",  "redisreplay6",  "redisreplay7",
  "redisreplay8",  "redisreplay9",  "redisreplay10", "redisreplay11",
  "redisreplay12", "redisreplay13", "redisreplay14", "redisreplay15",
};

// A real bug found while building this: an earlier version of this
// program used one big static 256KB buffer to slurp a whole chunk file
// at once. exec() (kernel/exec.c -> uvmalloc()) EAGERLY maps every page
// of a program's .bss at process start (a real physical frame per page,
// unlike vmbench_arena()'s sbrklazy()-backed lazy holes) -- so that
// buffer alone made 64 pages resident before main() even ran, more than
// vmbench_burn()'s fixed 64-scratch-touch budget could evict through,
// and vmbench_burn() failed outright. Streaming through a single 4KB
// page-sized buffer instead avoids inflating the startup footprint, and
// is a more honest test of "many small sequential reads" throughput
// besides.
static char g_buf[READ_BUF_SIZE];

// Streams "T <digits>\n" lines from an open fd, calling touch_w(arena,
// vpn) for each one. Digit runs may span read() boundaries (a chunk is
// ~260000 bytes read in 4096-byte pieces); vpn/in_number persist across
// the read loop to handle that. Chunk files always end on a line
// boundary (built that way on the host, see the module comment above),
// so no state needs to carry across files.
static long
replay_stream(char *arena, int fd)
{
  long replayed = 0;
  long vpn = 0;
  int in_number = 0;
  int n;
  while((n = read(fd, g_buf, READ_BUF_SIZE)) > 0){
    for(int i = 0; i < n; i++){
      char ch = g_buf[i];
      if(ch >= '0' && ch <= '9'){
        vpn = vpn * 10 + (ch - '0');
        in_number = 1;
        continue;
      }
      if(!in_number)
        continue; // 'T', ' ', or between lines -- skip
      // digit run just ended (on '\n')
      if(vpn >= 0 && vpn < ARENA_PAGES){
        touch_w(arena, (uint64)vpn, (uchar)vpn);
        replayed++;
      } else {
        printf("tracereplay: vpn %ld out of range [0,%d), skipping\n",
               vpn, ARENA_PAGES);
      }
      vpn = 0;
      in_number = 0;
    }
  }
  return replayed;
}

int
main(int argc, char *argv[])
{
  if(argc < 2 || argc > 3){
    printf("usage: tracereplay <resident_margin> [trace:0|1]\n");
    exit(1);
  }
  int resident_margin = atoi(argv[1]);
  int trace = argc > 2 ? atoi(argv[2]) : 0;

  vmbench_banner("tracereplay", "setup");
  char *arena = vmbench_arena(ARENA_PAGES);
  if(arena == 0){
    printf("tracereplay: vmbench_arena(%d) failed\n", ARENA_PAGES);
    exit(1);
  }

  // Touch one arena page before burning -- vmbench_burn proves itself
  // by watching for a victim selected from inside the arena's VPN
  // range, which requires the arena to already have at least one
  // resident page (see user/vmbench.h's vmbench_burn() docstring; this
  // exact ordering bug bit an earlier workload, see HANDOFF_TO_CLAUDE.md
  // SS3 item 1).
  touch_w(arena, 0, 0);

  uint64 settled = 0;
  int proven = vmbench_burn(arena, ARENA_PAGES, &settled);
  if(proven < 0){
    printf("tracereplay: vmbench_burn failed\n");
    exit(1);
  }
  if(!proven)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("tracereplay: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("tracereplay", "replay");
  if(trace)
    vmbench_trace_start("tracereplay",
                         "redis_real prefix, 825000 refs, 16 chunks",
                         0, arena, ARENA_PAGES, 0);

  uint64 read_start = uptime();
  long total_refs = 0;
  for(int c = 0; c < NUM_CHUNKS; c++){
    int fd = open(CHUNK_FILES[c], 0);
    if(fd < 0){
      printf("tracereplay: could not open %s\n", CHUNK_FILES[c]);
      exit(1);
    }
    total_refs += replay_stream(arena, fd);
    close(fd);
  }
  uint64 replay_end = uptime();

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("tracereplay", &d);

  vmbench_result("arena_pages", ARENA_PAGES);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("num_chunks", NUM_CHUNKS);
  vmbench_result("total_refs_replayed", total_refs);
  vmbench_result("read_and_replay_ticks", (long)(replay_end - read_start));
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
