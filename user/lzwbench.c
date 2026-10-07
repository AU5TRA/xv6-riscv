// lzwbench: LZW compression over a real text corpus, shipped in fs.img.
// The seed picks the text; every one is real English prose, 35,823 bytes:
//   seed 0  corpus.txt   the GNU GPL version 3 licence (the original input)
//   seed 1  corpus1.txt  Austen, Pride and Prejudice        (Gutenberg #1342)
//   seed 2  corpus2.txt  Doyle, Adventures of Sherlock Holmes   (#1661)
//   seed 3  corpus3.txt  Darwin, On the Origin of Species       (#1228)
//   seed 4  corpus4.txt  Hamilton et al., The Federalist Papers (#1404)
//   seed 5  corpus5.txt  Carroll, Alice's Adventures in Wonderland (#11)
// Seeds 1-5 are public-domain texts from Project Gutenberg: the 35,823
// bytes from the first line of prose (past the title page and contents),
// with the Project Gutenberg header and licence removed. The size matches
// corpus.txt so every seed compresses the same number of bytes.
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

// The encoder is Unix compress(1) -- compress 4.0, the version that
// fixed the .Z format -- so the dictionary is the one a real LZW tool
// keeps, not a toy. An earlier version of this file let up to 65536
// codes into a 16384-slot linear-probing table; the table filled
// completely and every miss then scanned all 16384 slots, which was ~99%
// of its reference string. compress never lets that happen:
//   * the table (HSIZE) is a prime larger than the code space, so it
//     always keeps empty slots and a miss stops at the first one;
//   * collisions use compress's secondary probe (disp = HSIZE - i);
//   * once all 65536 codes are assigned the dictionary is frozen, and
//     every CHECK_GAP input bytes the compression ratio is checked; if it
//     has stopped improving the table is wiped and a CLEAR code emitted
//     ("block compress" mode, compress's default).
// Keys and codes live in two parallel arrays, htab and codetab, as in
// compress. htab is 32-bit here: count_int was 32 bits on the machines
// compress was written for, and a key needs only 24.
//
// Unlike compress, the whole input and the whole output stream sit in
// the arena rather than passing through small stdio buffers; both are
// traced, so the reference string holds every arena page this program
// touches.
#define BITS 16
#define HSIZE 69001 // prime, 95% occupancy at 2^BITS codes -- compress's value
#define INIT_BITS 9
#define CHECK_GAP 10000
#define CLEAR 256
#define FIRST 257
#define MAXCODE(n) ((1 << (n)) - 1)
#define MAXMAXCODE (1 << BITS)
#define HSHIFT 8 // compress: 8 - log2 of how far HSIZE falls short of 65536

static int *g_htab;        // key (c << BITS) + ent, or -1 if empty
static ushort *g_codetab;  // code assigned to the key in the same slot
static ushort *g_output;
static char *g_arena_base;
static long g_out_count;

// compress's output() bookkeeping: codes are n_bits wide, growing from 9
// to 16 as codes are assigned and dropping back to 9 after a CLEAR. Only
// the packed size is tracked (for the ratio check); each code is stored
// in the arena as a ushort.
static int g_free_ent;
static int g_n_bits;
static int g_maxcode;
static int g_clear_flg;
static long g_out_bits;
static long g_clears;

static void
lzw_trace(const void *p, char access)
{
  vmbench_trace_ref(g_arena_base,
                    (uint64)(((const char *)p - g_arena_base) /
                             VMBENCH_PGSIZE),
                    access);
}

static void
lzw_output(int code)
{
  g_output[g_out_count] = (ushort)code;
  lzw_trace(&g_output[g_out_count], VMBENCH_WRITE);
  g_out_count++;
  g_out_bits += g_n_bits;
  if(g_free_ent > g_maxcode || g_clear_flg){
    if(g_clear_flg){
      g_n_bits = INIT_BITS;
      g_maxcode = MAXCODE(g_n_bits);
      g_clear_flg = 0;
    } else {
      g_n_bits++;
      g_maxcode = g_n_bits == BITS ? MAXMAXCODE : MAXCODE(g_n_bits);
    }
  }
}

static void
lzw_cl_hash(int traced)
{
  for(long i = 0; i < HSIZE; i++){
    g_htab[i] = -1;
    if(traced)
      lzw_trace(&g_htab[i], VMBENCH_WRITE);
  }
}

// compress's cl_block(): called with the dictionary full, every
// CHECK_GAP input bytes. The ratio is input bytes per output byte with
// 8 fractional bits; a CLEAR is sent the first time it fails to improve.
static long g_ratio;
static long g_checkpoint;

static void
lzw_cl_block(long in_count)
{
  g_checkpoint = in_count + CHECK_GAP;
  long bytes_out = 3 + g_out_bits / 8; // 3-byte .Z header
  long rat;
  if(in_count > 0x007fffff){
    rat = bytes_out >> 8;
    rat = rat == 0 ? 0x7fffffff : in_count / rat;
  } else {
    rat = (in_count << 8) / bytes_out;
  }
  if(rat > g_ratio){
    g_ratio = rat;
  } else {
    g_ratio = 0;
    lzw_cl_hash(1);
    g_free_ent = FIRST;
    g_clear_flg = 1;
    lzw_output(CLEAR);
    g_clears++;
  }
}

int
main(int argc, char *argv[])
{
  if(argc < 3 || argc > 5){
    printf("usage: lzwbench <resident_margin> <repeat_count> "
           "[trace: 1=console, 9=file] [seed: 0-5]\n");
    exit(1);
  }
  int resident_margin = atoi(argv[1]);
  int repeat_count = atoi(argv[2]);
  if(repeat_count < 1)
    repeat_count = 1;
  int trace_flags = argc >= 4 ? atoi(argv[3]) : 0;
  int trace = (trace_flags & 1) != 0;
  int seed = argc == 5 ? atoi(argv[4]) : 0;
  if(seed < 0 || seed > 5){
    printf("lzwbench: seed must be 0-5\n");
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("lzwbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }

  vmbench_banner("lzwbench", "setup");
  char corpus_name[16];
  strcpy(corpus_name, "corpus.txt");
  if(seed > 0){
    strcpy(corpus_name, "corpusN.txt");
    corpus_name[6] = (char)('0' + seed);
  }
  int fd = open(corpus_name, 0);
  if(fd < 0){
    printf("lzwbench: could not open %s\n", corpus_name);
    exit(1);
  }
  struct stat st;
  if(fstat(fd, &st) < 0){
    printf("lzwbench: fstat failed\n");
    exit(1);
  }
  long corpus_size = st.size;
  printf("[info] seed %d: %s, %ld bytes of English text\n", seed,
         corpus_name, corpus_size);

  long total_in = corpus_size * repeat_count;
  // At most one code per input byte, plus the CLEARs.
  long max_codes = total_in + total_in / CHECK_GAP + 2;
  long output_off = (total_in + 7) & ~7L;
  long htab_off = (output_off + max_codes * (long)sizeof(ushort) + 7) & ~7L;
  long codetab_off = htab_off + (long)HSIZE * (long)sizeof(int);
  long need_bytes = codetab_off + (long)HSIZE * (long)sizeof(ushort);
  int footprint_pages = (int)((need_bytes + VMBENCH_PGSIZE - 1) /
                               VMBENCH_PGSIZE) +
                        4;

  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("lzwbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  uchar *input = (uchar *)arena;
  g_output = (ushort *)(arena + output_off);
  g_htab = (int *)(arena + htab_off);
  g_codetab = (ushort *)(arena + codetab_off);
  g_arena_base = arena;

  // Touch the first page so the burn phase has something in the arena's
  // own VPN range to observe. The corpus is loaded only after the burn and
  // the limit: loaded before, its resident input pages (175-263 at repeat
  // counts 20-30) were counted in the settled baseline, so the margin came
  // on top of the whole input and a "5%" run had 194-288 frames.
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

  // Load the input under the limit. This is setup: whatever it pushes out
  // goes to swap now, outside the measured window.
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

  // compress clears the table before it starts; that sweep is setup and
  // stays outside the measured window. Later CLEARs are traced.
  lzw_cl_hash(0);
  g_free_ent = FIRST;
  g_n_bits = INIT_BITS;
  g_maxcode = MAXCODE(INIT_BITS);
  g_ratio = 0;
  g_checkpoint = CHECK_GAP;

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("lzwbench", "workload");
  if(trace)
    vmbench_trace_start("lzwbench", "see RESULT lines below for full "
                        "parameters", (uint64)seed, arena, footprint_pages,
                        resident_margin);
  // compress's main loop.
  lzw_trace(&input[0], VMBENCH_READ);
  int ent = input[0];
  for(long in_count = 1; in_count < total_in; in_count++){
    lzw_trace(&input[in_count], VMBENCH_READ);
    int c = input[in_count];
    int fcode = (c << BITS) + ent;
    long i = ((long)c << HSHIFT) ^ ent;
    lzw_trace(&g_htab[i], VMBENCH_READ);
    if(g_htab[i] != fcode && g_htab[i] >= 0){
      long disp = i == 0 ? 1 : HSIZE - i;
      do {
        if((i -= disp) < 0)
          i += HSIZE;
        lzw_trace(&g_htab[i], VMBENCH_READ);
      } while(g_htab[i] != fcode && g_htab[i] >= 0);
    }
    if(g_htab[i] == fcode){
      lzw_trace(&g_codetab[i], VMBENCH_READ);
      ent = g_codetab[i];
      continue;
    }
    // Miss: i is the empty slot the probe stopped at.
    lzw_output(ent);
    ent = c;
    if(g_free_ent < MAXMAXCODE){
      g_codetab[i] = (ushort)g_free_ent++;
      lzw_trace(&g_codetab[i], VMBENCH_WRITE);
      g_htab[i] = fcode;
      lzw_trace(&g_htab[i], VMBENCH_WRITE);
    } else if(in_count + 1 >= g_checkpoint){
      lzw_cl_block(in_count + 1);
    }
  }
  lzw_output(ent);

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("lzwbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("corpus_bytes", corpus_size);
  vmbench_result("repeat_count", repeat_count);
  vmbench_result("seed", seed);
  vmbench_result("input_bytes", total_in);
  vmbench_result("hash_slots", HSIZE);
  vmbench_result("output_codes", g_out_count);
  vmbench_result("compressed_bytes", 3 + (g_out_bits + 7) / 8);
  vmbench_result("clears", g_clears);
  vmbench_result("dictionary_entries", g_free_ent - FIRST);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
