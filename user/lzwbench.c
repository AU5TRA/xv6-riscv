// lzwbench: LZW compression over a real text corpus (corpus.txt,
// shipped in fs.img -- the GNU GPLv3 license text, chosen simply for
// being real, freely-redistributable, moderately-sized English prose
// with natural redundancy).
//
// Justification against the "no single heuristic wins" property
// (WORK_PROMPT.md SS0): LZW's dictionary lookup (mapping a
// (prefix_code, next_byte) pair to its assigned code) is a hash table
// probed in an order determined entirely by the INPUT DATA's own
// byte sequence, not by any structural property of the algorithm --
// this is genuinely data-dependent, irregular access, unlike
// btreebench's engineered root-to-leaf shape or kvbench's engineered
// Zipf skew. Some dictionary entries (common short sequences: "the ",
// "tion", punctuation) get re-probed constantly throughout the whole
// file (frequency-favoring), while most entries are created once near
// where they first occur and never probed again (recency-favoring,
// and in the SAME run as the frequent ones) -- a real mixture that
// isn't hand-tuned to favor one policy the way a synthetic pattern
// could be.
#include "kernel/types.h"
#include "kernel/stat.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define LZW_FIRST_CODE 256
#define LZW_MAX_CODE 65536
#define LZW_TABLE_SIZE 16384 // power of 2

struct lzw_entry {
  int prefix; // -1 if empty
  int byte;
  int code;
};

static struct lzw_entry *g_table;
static int g_next_code;

static long
lzw_hash(int prefix, int byte)
{
  uint64 x = ((uint64)(uint32)prefix << 8) ^ (uint64)(uint32)byte;
  x ^= x >> 15;
  x *= 0x2545F4914F6CDD1DULL;
  x ^= x >> 13;
  return (long)(x & (LZW_TABLE_SIZE - 1));
}

// Finds the code for (prefix, byte) if present; returns -1 otherwise.
// If not present and there's room, ALSO inserts a new code for it.
static int
lzw_lookup_or_insert(int prefix, int byte)
{
  long slot = lzw_hash(prefix, byte);
  for(long tries = 0; tries < LZW_TABLE_SIZE; tries++){
    struct lzw_entry *e = &g_table[slot];
    if(e->prefix == -1){
      if(g_next_code < LZW_MAX_CODE){
        e->prefix = prefix;
        e->byte = byte;
        e->code = g_next_code++;
      }
      return -1; // not found (whether or not we just inserted)
    }
    if(e->prefix == prefix && e->byte == byte)
      return e->code;
    slot = (slot + 1) & (LZW_TABLE_SIZE - 1);
  }
  return -1; // table full and not found -- caller treats as miss
}

int
main(int argc, char *argv[])
{
  if(argc != 3){
    printf("usage: lzwbench <resident_margin> <repeat_count>\n");
    exit(1);
  }
  int resident_margin = atoi(argv[1]);
  int repeat_count = atoi(argv[2]);
  if(repeat_count < 1)
    repeat_count = 1;

  vmbench_banner("lzwbench", "setup");
  int fd = open("corpus.txt", 0);
  if(fd < 0){
    printf("lzwbench: could not open corpus.txt\n");
    exit(1);
  }
  struct stat st;
  if(fstat(fd, &st) < 0){
    printf("lzwbench: fstat failed\n");
    exit(1);
  }
  long corpus_size = st.size;
  printf("[info] real text corpus: corpus.txt, %ld bytes (GNU GPLv3 "
         "license text)\n", corpus_size);

  long total_in = corpus_size * repeat_count;
  long table_bytes = (long)LZW_TABLE_SIZE * sizeof(struct lzw_entry);
  long need_bytes = total_in           // input buffer
                    + total_in * 2     // output codes (worst case, 2 bytes/code)
                    + table_bytes;     // dictionary hash table
  int footprint_pages = (int)((need_bytes + VMBENCH_PGSIZE - 1) /
                               VMBENCH_PGSIZE) +
                        4;

  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("lzwbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  uchar *input = (uchar *)arena;
  ushort *output = (ushort *)(input + total_in);
  g_table = (struct lzw_entry *)(output + total_in);

  long got = 0;
  while(got < corpus_size){
    int n = read(fd, (char *)input + got, (int)(corpus_size - got));
    if(n <= 0)
      break;
    got += n;
  }
  close(fd);
  if(got != corpus_size){
    printf("lzwbench: short read (%ld of %ld bytes)\n", got, corpus_size);
    exit(1);
  }
  for(int r = 1; r < repeat_count; r++)
    memmove(input + (long)r * corpus_size, input, corpus_size);

  *(volatile int *)arena = 0;
  uint64 settled;
  int proven = vmbench_burn(arena, footprint_pages, &settled);
  if(proven < 0){
    printf("lzwbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("lzwbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  for(long i = 0; i < LZW_TABLE_SIZE; i++)
    g_table[i].prefix = -1;
  g_next_code = LZW_FIRST_CODE;

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("lzwbench", "workload");
  long out_count = 0;
  int prefix = input[0];
  for(long i = 1; i < total_in; i++){
    int byte = input[i];
    int code = lzw_lookup_or_insert(prefix, byte);
    if(code >= 0){
      prefix = code;
    } else {
      output[out_count++] = (ushort)prefix;
      prefix = byte;
    }
  }
  output[out_count++] = (ushort)prefix;

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("lzwbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("corpus_bytes", corpus_size);
  vmbench_result("repeat_count", repeat_count);
  vmbench_result("input_bytes", total_in);
  vmbench_result("output_codes", out_count);
  vmbench_result("dictionary_entries", g_next_code - LZW_FIRST_CODE);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
