#ifndef XV6_VMTRACE_H
#define XV6_VMTRACE_H

// Version 2 packed the per-record fields and moved the version/record-size
// preamble into a one-time header (vmtrace_info), so a capture is a bare
// stream of fixed-size records rather than a stream that re-states its own
// schema 65536 times.
#define VMTRACE_VERSION 2

// Ring capacity in records. Training needs 10^5-10^7 events, so the ring has
// to hold enough between drains that a reader running at process scheduling
// granularity never loses one. At 64 bytes per record this costs 4 MiB of
// kernel BSS, which is never pageable.
#define VMTRACE_CAPACITY 65536

// Records per vmtrace_read() call. 256 * 64 B = 16 KiB per syscall, which is
// what keeps a drain loop's syscall overhead off the measurement.
#define VMTRACE_READ_MAX 256

// "No value" sentinels. The emit interface takes uint64/int arguments, so
// callers keep using VMTRACE_NONE; the narrowed record fields saturate to the
// all-ones value of their own width.
#define VMTRACE_NONE ((uint64)-1)
#define VMTRACE_NONE32 ((uint32)-1)
#define VMTRACE_NONE16 ((uint16)-1)
#define VMTRACE_NONE8 ((uint8)-1)

enum vmtrace_type {
  VMTRACE_ZERO_FAULT = 1,
  VMTRACE_SWAP_FAULT,
  VMTRACE_PROTECTION_FAULT,
  VMTRACE_MAP,
  VMTRACE_UNMAP,
  VMTRACE_VICTIM_SELECTED,
  VMTRACE_EVICT_BEGIN,
  VMTRACE_EVICT_END,
  VMTRACE_SWAP_READ_BEGIN,
  VMTRACE_SWAP_READ_END,
  VMTRACE_SWAP_WRITE_BEGIN,
  VMTRACE_SWAP_WRITE_END,
  VMTRACE_PREFETCH_HINT,
  VMTRACE_PREFETCH_QUEUE,
  VMTRACE_PREFETCH_BEGIN,
  VMTRACE_PREFETCH_END,
  VMTRACE_PREFETCH_USE,
  VMTRACE_PREFETCH_WASTE,
  VMTRACE_PREFETCH_CANCEL,
  VMTRACE_POLICY_FALLBACK,
  VMTRACE_DROP,
  VMTRACE_TYPE_COUNT,
};

// Returned once by vmtrace_info(). Written at the head of a drained capture
// so the decoder can validate the schema and, crucially, refuse a capture
// that lost records.
struct vmtrace_header {
  uint64 version;     // VMTRACE_VERSION
  uint64 record_size; // sizeof(struct vmtrace_event)
  uint64 capacity;    // ring capacity currently in effect, in records
  uint64 read_max;    // VMTRACE_READ_MAX
  uint64 sequence;    // sequence of the most recently emitted event
  uint64 dropped;     // events lost to ring overrun since the last reset
  uint64 buffered;    // events waiting to be read right now
  uint64 enabled;     // 1 while emission is on
};

// One trace record, fixed at 64 bytes.
//
// Widths are chosen to be lossless for what the kernel can actually produce:
// `ticks` is already a 32-bit counter, `pte_flags` only ever holds the ten
// PTE_FLAGS bits, and vpn/frame/slot/pid/generation cannot reach 2^32 on this
// machine. A field that does not apply to an event carries the all-ones
// sentinel for its width.
//
// `status` is logically signed (-1 marks a failed operation) -- decode it as
// int32, not uint32.
//
// 64 rather than the plan's 48 bytes: the plan's own field list adds up to
// 5*8 + 7*4 + 5*1 = 73 bytes, so 48 is only reachable by dropping fields.
// 64 keeps every field, wastes no padding, and divides BSIZE exactly, so a
// record never straddles a block in a drained capture.
struct vmtrace_event {
  uint64 sequence;       // 0  monotonic, gaps mean records were lost
  uint64 cycle;          // 8  r_time() at emission
  uint32 ticks;          // 16 scheduler tick counter
  uint32 generation;     // 20 owning process's address-space generation
  uint32 pid;            // 24
  uint32 vpn;            // 28 faulting/affected virtual page number
  uint32 victim_vpn;     // 32 eviction victim, or the new page on selection
  uint32 frame_index;    // 36 physical frame index
  uint32 swap_slot;      // 40
  uint32 resident_count; // 44 owner's resident pages at emission
  uint32 queue_id;       // 48 prefetch request id
  uint32 status;         // 52 signed: 0 ok, -1 failed, or a count
  uint16 pte_flags;      // 56 PTE_FLAGS() bits
  uint8 type;            // 58 enum vmtrace_type
  uint8 access;          // 59 VM_ACCESS_*
  uint8 page_state;      // 60 enum vm_page_state
  uint8 policy;          // 61 VM_POLICY_*
  uint8 reserved[2];     // 62 zero; keeps sizeof at 64
};

#endif
