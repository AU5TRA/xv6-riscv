#ifndef XV6_VMTRACE_H
#define XV6_VMTRACE_H

// Version 2 packed the per-record fields and moved the version/record-size
// preamble into a one-time header (vmtrace_info), so a capture is a bare
// stream of fixed-size records rather than a stream that re-states its own
// schema 65536 times.
#define VMTRACE_VERSION 3

// Ring capacity in records. The ring buys a fixed BACKLOG, not a rate: a
// capture is lossless as long as the drainer never falls more than this many
// records behind, and vmdrain keeps draining after the workload exits, so a
// bounded experiment only has to fit its peak backlog.
//
// 65536 was not enough. A measured 100k-operation paging soak emitted
// 302,243 events against a drainer sustaining ~1,050 records/s over 152 s,
// giving a peak backlog of about 143,000 records -- more than twice the old
// capacity, and 47% of the capture was lost. 262144 covers that with 1.8x
// margin. At 64 bytes per record it costs 16 MiB of kernel BSS, which is
// never pageable, and it reduces the free frame pool accordingly (the boot
// banner prints the resulting configuration).
#define VMTRACE_CAPACITY 262144

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

// Event-type mask: bit N enables enum vmtrace_type value N.
//
// A masked-out event is discarded before it is assigned a sequence number,
// which is the whole point -- masking can never be mistaken for loss, because
// the surviving stream stays contiguous and the decoder's gap check still
// means exactly what it meant before.
#define VMTRACE_BIT(type) ((uint64)1 << (type))
#define VMTRACE_MASK_ALL ((uint64)-1)

// The subset a page-replacement dataset needs, and nothing else.
//
// What this drops is the *_BEGIN/*_END span markers. Their fields duplicate
// their partner's; their only unique contribution is a timestamp, i.e. I/O
// latency. Six of the ~8 records a swap fault produces are span markers, so
// this halves the event rate.
//
// What it deliberately keeps is everything a replacement decision is made
// of. Note that "was the victim dirty" survives even without the write pair:
// VICTIM_SELECTED carries the victim's existing backing slot and EVICT_END
// the slot it ended up in, and those differ exactly when a write-back was
// needed. VMTRACE_DROP is kept because masking away the loss markers would
// defeat the drop discipline; vmtrace_control() forces it on regardless.
#define VMTRACE_MASK_DATASET (               \
  VMTRACE_BIT(VMTRACE_ZERO_FAULT) |          \
  VMTRACE_BIT(VMTRACE_SWAP_FAULT) |          \
  VMTRACE_BIT(VMTRACE_PROTECTION_FAULT) |    \
  VMTRACE_BIT(VMTRACE_MAP) |                 \
  VMTRACE_BIT(VMTRACE_UNMAP) |               \
  VMTRACE_BIT(VMTRACE_VICTIM_SELECTED) |     \
  VMTRACE_BIT(VMTRACE_EVICT_END) |           \
  VMTRACE_BIT(VMTRACE_POLICY_FALLBACK) |     \
  VMTRACE_BIT(VMTRACE_PREFETCH_USE) |        \
  VMTRACE_BIT(VMTRACE_PREFETCH_WASTE) |      \
  VMTRACE_BIT(VMTRACE_DROP))

// Returned once by vmtrace_info(). Written at the head of a drained capture
// so the decoder can validate the schema and, crucially, refuse a capture
// that lost records.
// 128 bytes, not 72. The header sits at the front of a capture and every
// record follows it, so its size has to stay a multiple of the record size
// or every record in the file lands off a 64-byte boundary and straddles
// block boundaries. Two record slots leaves room to add fields later
// without moving the records again.
struct vmtrace_header {
  uint64 version;     // VMTRACE_VERSION
  uint64 record_size; // sizeof(struct vmtrace_event)
  uint64 capacity;    // ring capacity currently in effect, in records
  uint64 read_max;    // VMTRACE_READ_MAX
  uint64 sequence;    // sequence of the most recently emitted event
  uint64 dropped;     // events lost to ring overrun since the last reset
  uint64 buffered;    // events waiting to be read right now
  uint64 enabled;     // 1 while emission is on
  uint64 event_mask;  // which event types this capture was recording
  uint64 reserved[7]; // zero
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
