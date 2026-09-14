// sqlitereplay: replays a slice of a REAL SQLite memory-access trace
// (collected on Linux, see tools/collect_linux_trace.sh /
// tools/trace_reduce.py) as real memory touches inside xv6, so the
// actual kernel paging code (not tools/sim.py's host-side simulator)
// faults/evicts on a real-application access pattern.
//
// SQLite's sibling of user/tracereplay.c (the original, Redis-focused
// replay program) -- a SEPARATE program rather than a generalized one,
// chosen deliberately: this project's own precedent throughout (six
// independent workload programs: btreebench/kvbench/graphbench/
// sortbench/matmulbench/lzwbench) favors separate purpose-built
// programs over a single parameterized one, and duplicating this
// program's small (~150-line) replay logic carries zero risk to
// tracereplay.c's already-verified, already-committed Redis replay
// path -- generalizing that program in place would have meant
// re-verifying it end to end for a marginal reduction in duplication.
// See docs/workloads.md for the full reasoning.
//
// SCOPE, stated plainly, same as tracereplay.c's own requirement: this
// is a feasibility investigation, not a general-purpose trace replayer.
// The full real-SQLite trace is 8.56M references; xv6's per-file cap is
// MAXFILE = NDIRECT(12) + NINDIRECT(BSIZE/sizeof(uint)=256) = 268 blocks
// = 268KB (kernel/fs.h). This program replays the first 300,000
// references (about 3.51% of the full trace -- a SMALLER fraction than
// tracereplay.c's 6.70% Redis slice, because committing the Redis
// chunks already consumed most of the filesystem's free space; see the
// margin sweep and headroom numbers in docs/workloads.md) of
// traces/real/sqlite_real.trace, pre-split on the host into 7 files
// (sqlitereplay0 .. sqlitereplay6, see tools/gen_tracereplay_chunks.py)
// each safely under the 268KB cap.
//
// KNOWN LIMITATION, also stated plainly, identical to tracereplay.c's:
// tools/trace_reduce.py collapses Valgrind Lackey's L (load) and S
// (store) lines into one undifferentiated "T <vpn>" reference, upstream
// of both traces, before either was ever chunked -- the read/write
// distinction cannot be recovered here for SQLite any more than it
// could for Redis. Every replayed reference uses touch_w() rather than
// touch_r(), the more conservative choice: it exercises both PTE_A and
// PTE_D (and therefore the write-back path), whereas replaying
// everything read-only would never exercise dirty-page write-back at
// all. This means eviction/write-back counts here are an upper bound on
// what real SQLite's own read/write mix would produce, not an exact
// reproduction of it.
//
// ARENA_PAGES=282 (not the real trace's own arena_pages=283) because
// the max VPN actually referenced within this 300,000-reference PREFIX
// is 281 -- later pages in the full trace are simply never reached by
// this slice, so sizing the arena to the full trace's range would only
// allocate unused address space.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define ARENA_PAGES 282
#define NUM_CHUNKS 7
#define READ_BUF_SIZE 4096 // one page -- see tracereplay.c's own note on
                            // why this must stay small, not a
                            // whole-chunk buffer (exec()'s eager .bss
                            // mapping broke vmbench_burn() the first time)

static const char *CHUNK_FILES[NUM_CHUNKS] = {
  "sqlitereplay0", "sqlitereplay1", "sqlitereplay2", "sqlitereplay3",
  "sqlitereplay4", "sqlitereplay5", "sqlitereplay6",
};

static char g_buf[READ_BUF_SIZE];

// Streams "T <digits>\n" lines from an open fd, calling touch_w(arena,
// vpn) for each one. Identical logic to tracereplay.c's replay_stream()
// -- see that file for the full reasoning on why digit runs need to
// persist across read() boundaries and why chunk files never need
// cross-file carry state.
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
        printf("sqlitereplay: vpn %ld out of range [0,%d), skipping\n",
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
    printf("usage: sqlitereplay <resident_margin> [trace:0|1]\n");
    exit(1);
  }
  int resident_margin = atoi(argv[1]);
  int trace = argc > 2 ? atoi(argv[2]) : 0;

  vmbench_banner("sqlitereplay", "setup");
  char *arena = vmbench_arena(ARENA_PAGES);
  if(arena == 0){
    printf("sqlitereplay: vmbench_arena(%d) failed\n", ARENA_PAGES);
    exit(1);
  }

  // Touch one arena page before burning -- vmbench_burn proves itself
  // by watching for a victim selected from inside the arena's VPN
  // range, which requires the arena to already have at least one
  // resident page (see user/vmbench.h's vmbench_burn() docstring; this
  // exact ordering bug bit an earlier workload, see HANDOFF_TO_CLAUDE.md
  // SS3 item 1, and tracereplay.c reuses the same fix).
  touch_w(arena, 0, 0);

  uint64 settled = 0;
  int proven = vmbench_burn(arena, ARENA_PAGES, &settled);
  if(proven < 0){
    printf("sqlitereplay: vmbench_burn failed\n");
    exit(1);
  }
  if(!proven)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("sqlitereplay: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("sqlitereplay", "replay");
  if(trace)
    vmbench_trace_start("sqlitereplay",
                         "sqlite_real prefix, 300000 refs, 7 chunks",
                         0, arena, ARENA_PAGES, 0);

  uint64 read_start = uptime();
  long total_refs = 0;
  for(int c = 0; c < NUM_CHUNKS; c++){
    int fd = open(CHUNK_FILES[c], 0);
    if(fd < 0){
      printf("sqlitereplay: could not open %s\n", CHUNK_FILES[c]);
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
  vmbench_print_delta("sqlitereplay", &d);

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
