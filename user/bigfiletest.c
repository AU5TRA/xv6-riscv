// Exercises the ceilings raised in Phase 1: the doubly-indirect block map
// (MAXFILE well past the old single-indirect limit), the deeper user stack,
// and a swap footprint larger than the old 1024-slot region.
//
// Block accounting is deliberately not checked from here -- the kernel does
// not expose a free-block count -- so run tools/fsck_xv6.py over fs.img
// afterwards to confirm nothing leaked.

#include "kernel/types.h"
#include "kernel/stat.h"
#include "kernel/param.h"
#include "kernel/fs.h"
#include "kernel/fcntl.h"
#include "kernel/vmstats.h"
#include "user/user.h"

#define PGSIZE   4096
#define BUFBYTES 8192
#define BUFWORDS (BUFBYTES / 4)

static uint buf[BUFWORDS];

// Position-dependent pattern: a wrong-but-plausible block map (a swapped
// index, an off-by-one level) shows up as a mismatch rather than as data that
// happens to look right.
static uint
mix(uint x)
{
  x ^= x >> 16;
  x *= 0x7feb352d;
  x ^= x >> 15;
  x *= 0x846ca68b;
  x ^= x >> 16;
  return x;
}

static int
fail(const char *name, const char *why)
{
  printf("FAILED -- %s: %s\n", name, why);
  return -1;
}

// Append `bytes` of pattern to an already-open fd whose current offset is
// `off`. Returns 0 on success.
static int
append_pattern(int fd, uint off, uint bytes)
{
  while (bytes > 0) {
    uint n = bytes < BUFBYTES ? bytes : BUFBYTES;
    for (uint i = 0; i < n / 4; i++)
      buf[i] = mix(off / 4 + i);
    if (write(fd, buf, (int)n) != (int)n)
      return -1;
    off += n;
    bytes -= n;
  }
  return 0;
}

static int
write_pattern(const char *path, uint bytes)
{
  int fd = open(path, O_CREATE | O_TRUNC | O_RDWR);
  if (fd < 0)
    return -1;
  int r = append_pattern(fd, 0, bytes);
  close(fd);
  return r;
}

// Reads the whole file back and checks every 32-bit word against the pattern
// and the total length against `bytes`.
static int
verify_pattern(const char *path, uint bytes)
{
  struct stat st;
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return -1;
  if (fstat(fd, &st) < 0) {
    close(fd);
    return -1;
  }
  if (st.size != bytes) {
    printf("bigfiletest: fstat size %ld expected %d\n", st.size, bytes);
    close(fd);
    return -1;
  }

  uint off = 0;
  for (;;) {
    int n = read(fd, buf, BUFBYTES);
    if (n < 0 || (n % 4) != 0) {
      printf("bigfiletest: read returned %d at offset %d\n", n, off);
      close(fd);
      return -1;
    }
    if (n == 0)
      break;
    for (int i = 0; i < n / 4; i++) {
      if (buf[i] != mix(off / 4 + i)) {
        printf("bigfiletest: content mismatch at byte %d\n", off + i * 4);
        close(fd);
        return -1;
      }
    }
    off += n;
  }
  close(fd);
  if (off != bytes) {
    printf("bigfiletest: read %d bytes, expected %d\n", off, bytes);
    return -1;
  }
  return 0;
}

// ---------------------------------------------------------------- basic ----

// 5 MiB is 5120 blocks: past NDIRECT+NINDIRECT (267), so most of it lives
// under the doubly-indirect block, spanning 19 second-level blocks.
static int
basic(void)
{
  const char *name = "basic";
  enum { SIZE = 5 * 1024 * 1024 };
  struct stat st;

  if (write_pattern("big5m", SIZE) < 0)
    return fail(name, "write failed");
  if (verify_pattern("big5m", SIZE) < 0)
    return fail(name, "read-back mismatch");
  if (stat("big5m", &st) < 0 || st.type != T_FILE || st.size != SIZE)
    return fail(name, "stat disagrees after close");
  if (unlink("big5m") < 0)
    return fail(name, "unlink failed");
  if (open("big5m", O_RDONLY) >= 0)
    return fail(name, "file still present after unlink");

  printf("bigfiletest: basic: ok (%d bytes, %d blocks)\n", SIZE, SIZE / BSIZE);
  return 0;
}

// ------------------------------------------------------------- boundary ----

// Grows a file across each level transition and re-verifies the whole file
// after every step, so a level boundary that maps the wrong block shows up
// immediately rather than only in a large file.
static int
boundary(void)
{
  const char *name = "boundary";
  // Last block reachable without the doubly-indirect block.
  uint single = (NDIRECT + NINDIRECT) * BSIZE;
  // One block into the doubly-indirect region.
  uint first_double = single + BSIZE;
  // First block under the second entry of the doubly-indirect block.
  uint second_l1 = single + (NINDIRECT + 1) * BSIZE;

  // xv6 has no lseek, so each step rewrites the file from offset zero with
  // O_TRUNC rather than appending to the previous one. That also puts itrunc
  // on a doubly-indirect file four times over.
  if (write_pattern("bfbound", (uint)(NDIRECT * BSIZE)) < 0 ||
      verify_pattern("bfbound", (uint)(NDIRECT * BSIZE)) < 0)
    return fail(name, "direct blocks only");
  if (write_pattern("bfbound", single) < 0 || verify_pattern("bfbound", single) < 0)
    return fail(name, "singly-indirect full");
  if (write_pattern("bfbound", first_double) < 0 ||
      verify_pattern("bfbound", first_double) < 0)
    return fail(name, "first doubly-indirect block");
  if (write_pattern("bfbound", second_l1) < 0 ||
      verify_pattern("bfbound", second_l1) < 0)
    return fail(name, "second doubly-indirect entry");

  if (unlink("bfbound") < 0)
    return fail(name, "unlink failed");

  printf("bigfiletest: boundary: ok (%d, %d, %d bytes)\n", single, first_double,
         second_l1);
  return 0;
}

// ---------------------------------------------------------------- trunc ----

// O_TRUNC has to run itrunc over a doubly-indirect file and leave the inode
// reusable in the same breath.
static int
trunc(void)
{
  const char *name = "trunc";
  enum { SIZE = 2 * 1024 * 1024, SMALL = 3 * BUFBYTES };
  struct stat st;

  if (write_pattern("bftrunc", SIZE) < 0)
    return fail(name, "initial write failed");

  int fd = open("bftrunc", O_TRUNC | O_RDWR);
  if (fd < 0)
    return fail(name, "O_TRUNC open failed");
  if (fstat(fd, &st) < 0 || st.size != 0) {
    close(fd);
    return fail(name, "size not zero after O_TRUNC");
  }
  if (append_pattern(fd, 0, SMALL) < 0) {
    close(fd);
    return fail(name, "rewrite after truncate failed");
  }
  close(fd);

  if (verify_pattern("bftrunc", SMALL) < 0)
    return fail(name, "rewritten content mismatch");
  if (unlink("bftrunc") < 0)
    return fail(name, "unlink failed");

  printf("bigfiletest: trunc: ok\n");
  return 0;
}

// ------------------------------------------------------------ deepstack ----

// USERSTACK pages of stack must all be usable. Each frame holds a 1 KiB array
// that is written and read back, so the compiler cannot elide it and a frame
// landing on the guard page faults instead of silently aliasing.
static int __attribute__((noinline))
descend(int depth, int seed)
{
  volatile char frame[1024];
  frame[0] = (char)seed;
  frame[sizeof(frame) - 1] = (char)(seed + depth);
  if (depth > 0) {
    int r = descend(depth - 1, seed + 1);
    if (r < 0)
      return r;
  }
  if (frame[0] != (char)seed || frame[sizeof(frame) - 1] != (char)(seed + depth))
    return -1;
  return 0;
}

static int
deepstack(void)
{
  const char *name = "deepstack";
  // Stay clear of the top of the stack so argv and the outer frames fit, and
  // leave room for the per-frame save area on top of each 1 KiB array.
  int frames = (USERSTACK * PGSIZE) / 1024 - 16;
  if (frames <= 4)
    return fail(name, "USERSTACK too small for this test");
  if (descend(frames, 1) < 0)
    return fail(name, "stack frame corrupted");

  printf("bigfiletest: deepstack: ok (%d frames, %d KiB, USERSTACK=%d)\n", frames,
         frames, USERSTACK);
  return 0;
}

// -------------------------------------------------------------- swapbig ----

// Pushes more pages through swap than the old 1024-slot (4 MiB) region could
// hold, so the raised NSWAPSLOTS is exercised rather than merely configured.
static int
swapbig(void)
{
  const char *name = "swapbig";
  enum { PAGES = 2048 }; // 8 MiB of anonymous memory
  struct vmstats before, after;

  if (vmstats(&before) < 0)
    return fail(name, "vmstats failed");
  if (before.free_swap_slots < (uint64)PAGES)
    return fail(name, "swap region too small for this test");

  if (vmctl(VM_SET_LIMIT, before.resident_count + 32) < 0)
    return fail(name, "VM_SET_LIMIT failed");

  char *memory = sbrklazy(PAGES * PGSIZE);
  if (memory == SBRK_ERROR)
    return fail(name, "sbrklazy failed");

  // First pass writes a per-page tag; the resident limit forces all but 32
  // pages out to swap.
  for (int i = 0; i < PAGES; i++)
    memory[(uint64)i * PGSIZE] = (char)mix((uint)i);
  // Second pass reads them back, so every page has to come in from swap.
  for (int i = 0; i < PAGES; i++) {
    if (memory[(uint64)i * PGSIZE] != (char)mix((uint)i)) {
      printf("bigfiletest: page %d came back wrong\n", i);
      return fail(name, "swapped page content mismatch");
    }
  }

  if (vmstats(&after) < 0)
    return fail(name, "vmstats failed after");
  if (after.resident_count > after.resident_limit)
    return fail(name, "resident count above limit");
  if (after.evictions - before.evictions < (uint64)(PAGES - 32))
    return fail(name, "fewer evictions than pages touched");
  if (after.swap_faults - before.swap_faults < (uint64)(PAGES - 32))
    return fail(name, "fewer swap-in faults than pages touched");
  if (vmcheck() != 0)
    return fail(name, "vmcheck reported an invariant failure");
  if (sbrk(-PAGES * PGSIZE) == SBRK_ERROR)
    return fail(name, "shrink failed");
  if (vmcheck() != 0)
    return fail(name, "vmcheck failed after shrink");

  printf("bigfiletest: swapbig: ok (%d pages, %ld slots free at start, "
         "evictions +%ld, swap_faults +%ld)\n",
         PAGES, before.free_swap_slots, after.evictions - before.evictions,
         after.swap_faults - before.swap_faults);
  return 0;
}

// ----------------------------------------------------------------- main ----

static int
run(const char *name)
{
  if (strcmp(name, "basic") == 0)
    return basic();
  if (strcmp(name, "boundary") == 0)
    return boundary();
  if (strcmp(name, "trunc") == 0)
    return trunc();
  if (strcmp(name, "deepstack") == 0)
    return deepstack();
  if (strcmp(name, "swapbig") == 0)
    return swapbig();
  if (strcmp(name, "all") == 0) {
    if (deepstack() < 0 || boundary() < 0 || trunc() < 0 || basic() < 0 ||
        swapbig() < 0)
      return -1;
    return 0;
  }
  printf("FAILED -- unknown test %s\n", name);
  return -1;
}

int
main(int argc, char **argv)
{
  const char *name = argc > 1 ? argv[1] : "all";

  printf("bigfiletest: %s starting (MAXFILE=%d blocks, NDIRECT=%d, "
         "NINDIRECT=%d)\n",
         name, (int)MAXFILE, NDIRECT, (int)NINDIRECT);
  if (run(name) < 0)
    exit(1);
  printf("PASS\n");
  exit(0);
}
