// Drains the kernel's paging trace ring into a file.
//
// The ring holds VMTRACE_CAPACITY records; any workload that outruns a reader
// overwrites the oldest ones, and a trace with silent holes is worse than no
// trace at all because a model will happily learn from the biased remainder.
// So this writes a header at the front of the capture, records every record
// verbatim, and treats a non-zero drop count as making the whole capture
// invalid rather than as a warning.
//
// Capture format:
//   [ struct vmtrace_header ][ struct vmtrace_event ] * n
//
// The header is written before the workload runs, so its version/record_size/
// capacity/read_max fields describe the schema and its counters are only the
// pre-run snapshot. Losslessness is proved from the records themselves: every
// emitted event carries a sequence number, the ring resets sequencing to zero,
// so a capture is complete exactly when the first record is sequence 1, every
// following sequence is one greater than the last, and no record has type
// VMTRACE_DROP. tools/decode_trace.py enforces all three.
//
// Usage:
//   vmdrain <file> collect <command> [args...]   run a command, drain while it runs
//   vmdrain <file> follow <ticks>                drain for a fixed number of ticks
//   vmdrain <file> once                          drain whatever is buffered now
//
// "collect" and "follow" both reset the ring and turn emission on for the
// measured window, then turn it off again, so their captures start at
// sequence 1 and pass a --strict decode. "once" deliberately does neither:
// it copies out whatever is already buffered, which is a mid-stream window
// unless the caller reset the ring itself.
//
// "follow" is the mode for a workload that has to be started separately:
//   $ vmdrain trace.bin follow 600 &
//   $ vmtest swap-repeat

#include "kernel/types.h"
#include "kernel/stat.h"
#include "kernel/fcntl.h"
#include "kernel/vmstats.h"
#include "kernel/vmtrace.h"
#include "user/user.h"

// Consecutive quiet polls that end a "collect" run.
#define COLLECT_IDLE_TICKS 100

// One vmtrace_read() batch. Kept as a global so it lands in .bss rather than
// on the 16-page user stack.
static struct vmtrace_event batch[VMTRACE_READ_MAX];

static uint64 total_records;
static uint64 total_writes;
static uint64 sequence_gaps;
static uint64 last_sequence;
static uint64 drop_records;

static int
write_all(int fd, const void *data, int bytes)
{
  const char *p = (const char *)data;
  while (bytes > 0) {
    int n = write(fd, p, bytes);
    if (n <= 0)
      return -1;
    p += n;
    bytes -= n;
    total_writes++;
  }
  return 0;
}

// Copies whatever is buffered into the capture file. Returns the number of
// records moved, or -1 on error.
static int
drain_once(int fd)
{
  int moved = 0;
  for (;;) {
    int count = vmtrace_read(batch, VMTRACE_READ_MAX);
    if (count < 0)
      return -1;
    if (count == 0)
      break;
    for (int i = 0; i < count; i++) {
      // A gap in the sequence numbers is the in-band evidence that the ring
      // overran, independent of the header's drop counter.
      if (last_sequence != 0 && batch[i].sequence != last_sequence + 1)
        sequence_gaps++;
      last_sequence = batch[i].sequence;
      if (batch[i].type == VMTRACE_DROP)
        drop_records++;
    }
    if (write_all(fd, batch, count * (int)sizeof(batch[0])) < 0)
      return -1;
    total_records += count;
    moved += count;
    if (count < VMTRACE_READ_MAX)
      break; // ring is empty for now
  }
  return moved;
}

static int
write_header(int fd)
{
  struct vmtrace_header header;
  if (vmtrace_info(&header) < 0) {
    printf("vmdrain: vmtrace_info failed\n");
    return -1;
  }
  if (header.version != VMTRACE_VERSION ||
      header.record_size != sizeof(struct vmtrace_event)) {
    printf("vmdrain: schema mismatch: version %ld record_size %ld "
           "(expected %d and %d)\n",
           header.version, header.record_size, VMTRACE_VERSION,
           (int)sizeof(struct vmtrace_event));
    return -1;
  }
  return write_all(fd, &header, (int)sizeof(header));
}

// Prints the verdict and returns the process exit status. A capture that lost
// records is invalid, full stop -- the caller is expected to discard it.
static int
report(const char *path)
{
  struct vmtrace_header header;
  if (vmtrace_info(&header) < 0) {
    printf("vmdrain: vmtrace_info failed\n");
    return 1;
  }

  printf("vmdrain: %s: records=%ld writes=%ld last_sequence=%ld\n", path,
         total_records, total_writes, last_sequence);
  printf("vmdrain: kernel: emitted=%ld dropped=%ld buffered=%ld capacity=%ld\n",
         header.sequence, header.dropped, header.buffered, header.capacity);

  if (header.dropped != 0 || drop_records != 0 || sequence_gaps != 0) {
    printf("vmdrain: INVALID: dropped=%ld drop_records=%ld sequence_gaps=%ld\n",
           header.dropped, drop_records, sequence_gaps);
    printf("FAILED -- capture lost records; discard it\n");
    return 1;
  }
  if (header.buffered != 0) {
    printf("vmdrain: INVALID: %ld record(s) still buffered\n", header.buffered);
    printf("FAILED -- capture is incomplete\n");
    return 1;
  }
  printf("vmdrain: lossless: no drops, no sequence gaps\n");
  printf("PASS\n");
  return 0;
}

static int
open_capture(const char *path)
{
  int fd = open(path, O_CREATE | O_TRUNC | O_RDWR);
  if (fd < 0)
    printf("vmdrain: cannot create %s\n", path);
  return fd;
}

// Runs `argv` in a child and drains continuously until it exits.
static int
collect(const char *path, char **argv)
{
  int fd = open_capture(path);
  if (fd < 0)
    return 1;

  if (vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0) {
    printf("vmdrain: cannot reset the trace ring\n");
    close(fd);
    return 1;
  }
  if (write_header(fd) < 0) {
    close(fd);
    return 1;
  }

  int pid = fork();
  if (pid < 0) {
    printf("vmdrain: fork failed\n");
    close(fd);
    return 1;
  }
  if (pid == 0) {
    // Emission is a single global switch, so this turns tracing on for the
    // whole system. Records carry a pid, so the decoder filters.
    if (vmctl(VM_TRACE_ENABLE, 1) < 0)
      exit(1);
    exec(argv[0], argv);
    printf("vmdrain: exec %s failed\n", argv[0]);
    exit(1);
  }

  // xv6's wait() blocks and there is no non-blocking variant, so a drainer
  // that waits on the workload cannot drain at the same time. Instead this
  // drains until the ring has produced nothing for COLLECT_IDLE_TICKS
  // consecutive polls, which is the workload having finished (or having gone
  // quiet for over a second). Guessing early is safe rather than silent: any
  // records lost while blocked in wait() show up in report() as a non-zero
  // drop count and the capture is declared invalid.
  int idle = 0;
  for (;;) {
    int moved = drain_once(fd);
    if (moved < 0) {
      printf("vmdrain: write to %s failed\n", path);
      close(fd);
      return 1;
    }
    if (moved > 0)
      idle = 0;
    else if (++idle >= COLLECT_IDLE_TICKS)
      break;
    pause(1);
  }

  int status = -1;
  wait(&status);
  // The workload has exited; sweep up whatever it emitted last.
  if (drain_once(fd) < 0) {
    printf("vmdrain: final drain failed\n");
    close(fd);
    return 1;
  }
  vmctl(VM_TRACE_ENABLE, 0);
  close(fd);

  if (status != 0) {
    printf("vmdrain: workload exited with status %d\n", status);
    return 1;
  }
  return report(path);
}

static int
follow(const char *path, int wait_ticks)
{
  int fd = open_capture(path);
  if (fd < 0)
    return 1;
  // Reset and enable here, not in the workload: this process starts
  // first (it is meant to be backgrounded), so the window it records
  // begins at sequence 1.
  if (vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0) {
    printf("vmdrain: cannot reset the trace ring\n");
    close(fd);
    return 1;
  }
  if (write_header(fd) < 0) {
    close(fd);
    return 1;
  }
  if (vmctl(VM_TRACE_ENABLE, 1) < 0) {
    printf("vmdrain: cannot enable tracing\n");
    close(fd);
    return 1;
  }
  int start = uptime();
  for (;;) {
    if (drain_once(fd) < 0) {
      printf("vmdrain: write to %s failed\n", path);
      close(fd);
      return 1;
    }
    if (uptime() - start >= wait_ticks)
      break;
    pause(1);
  }
  vmctl(VM_TRACE_ENABLE, 0);
  // Sweep up anything emitted between the last drain and the stop.
  if (drain_once(fd) < 0) {
    printf("vmdrain: final drain failed\n");
    close(fd);
    return 1;
  }
  close(fd);
  return report(path);
}

static int
once(const char *path)
{
  int fd = open_capture(path);
  if (fd < 0)
    return 1;
  if (write_header(fd) < 0) {
    close(fd);
    return 1;
  }
  if (drain_once(fd) < 0) {
    printf("vmdrain: write to %s failed\n", path);
    close(fd);
    return 1;
  }
  close(fd);
  return report(path);
}

int
main(int argc, char **argv)
{
  if (argc < 3) {
    printf("usage: vmdrain <file> collect <command> [args...]\n");
    printf("       vmdrain <file> follow <ticks>\n");
    printf("       vmdrain <file> once\n");
    exit(1);
  }

  const char *path = argv[1];
  const char *mode = argv[2];

  if (strcmp(mode, "collect") == 0) {
    if (argc < 4) {
      printf("vmdrain: collect needs a command\n");
      exit(1);
    }
    exit(collect(path, argv + 3));
  }
  if (strcmp(mode, "follow") == 0) {
    int ticks = argc > 3 ? atoi(argv[3]) : 10;
    if (ticks <= 0) {
      printf("vmdrain: follow needs a positive tick count\n");
      exit(1);
    }
    exit(follow(path, ticks));
  }
  if (strcmp(mode, "once") == 0)
    exit(once(path));

  printf("vmdrain: unknown mode %s\n", mode);
  exit(1);
}
