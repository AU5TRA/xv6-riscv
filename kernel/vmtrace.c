#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmtrace.h"

// Both sizes are hard-coded in the drain format and in
// tools/decode_trace.py, so a field change that alters them has to be a
// deliberate schema bump rather than a silent break.
typedef char vmtrace_event_is_64_bytes[sizeof(struct vmtrace_event) == 64 ? 1
                                                                          : -1];
typedef char vmtrace_header_is_64_bytes[sizeof(struct vmtrace_header) == 64 ? 1
                                                                            : -1];

static struct {
  struct spinlock lock;
  struct vmtrace_event events[VMTRACE_CAPACITY];
  uint capacity; // records in use; <= VMTRACE_CAPACITY
  uint head;
  uint tail;
  uint count;
  uint enabled;
  uint64 sequence;
  uint64 drops;
} trace_ring;

static uint64
trace_cycle(void)
{
  // xv6 enables the supervisor time counter, while rdcycle is not guaranteed
  // to be delegated by the machine firmware used for this kernel.
  return r_time();
}

// The record fields are narrower than the emit interface's arguments. A value
// that does not fit -- in practice only the VMTRACE_NONE sentinel -- saturates
// to the all-ones value of the destination width, which no real vpn, frame
// index, slot or flag word can reach.
static uint32
narrow32(uint64 value)
{
  return value >= (uint64)VMTRACE_NONE32 ? VMTRACE_NONE32 : (uint32)value;
}

static uint16
narrow16(uint64 value)
{
  return value >= (uint64)VMTRACE_NONE16 ? VMTRACE_NONE16 : (uint16)value;
}

static uint8
narrow8(int value)
{
  return value < 0 || value >= (int)VMTRACE_NONE8 ? VMTRACE_NONE8
                                                  : (uint8)value;
}

void
vmtrace_init(void)
{
  initlock(&trace_ring.lock, "vmtrace");
  trace_ring.capacity = VMTRACE_CAPACITY;
}

// Drops every buffered record and restarts sequence numbering. Callers hold
// the ring lock.
static void
trace_clear(void)
{
  trace_ring.head = 0;
  trace_ring.tail = 0;
  trace_ring.count = 0;
  trace_ring.sequence = 0;
  trace_ring.drops = 0;
}

int
vmtrace_control(int command, uint64 value)
{
  acquire(&trace_ring.lock);
  int result = 0;
  if(command == VM_TRACE_ENABLE){
    if(value > 1)
      result = -1;
    else
      trace_ring.enabled = value;
  } else if(command == VM_TRACE_RESET){
    if(value != 0)
      result = -1;
    else
      trace_clear();
  } else if(command == VM_TRACE_SET_CAPACITY){
    // Shrinking the ring is how the overflow tests stay cheap: filling
    // 65536 records for real would cost tens of thousands of swap I/Os.
    // It is also useful for studying drop behaviour deliberately.
    if(value == 0 || value > VMTRACE_CAPACITY)
      result = -1;
    else {
      trace_ring.capacity = (uint)value;
      trace_clear();
    }
  } else {
    result = -1;
  }
  release(&trace_ring.lock);
  return result;
}

void
vmtrace_emit(struct proc *p, int type, uint64 va, int access, int page_state,
             uint64 pte_flags, uint64 frame_index, int slot,
             uint64 victim_va, uint64 queue_id, int status)
{
  if(type <= 0 || type >= VMTRACE_TYPE_COUNT)
    return;
  acquire(&trace_ring.lock);
  if(!trace_ring.enabled){
    release(&trace_ring.lock);
    return;
  }

  struct vmtrace_event event;
  memset(&event, 0, sizeof(event));
  event.sequence = ++trace_ring.sequence;
  event.cycle = trace_cycle();
  event.ticks = ticks;
  event.generation = p ? narrow32(p->vm.generation) : VMTRACE_NONE32;
  event.pid = p ? narrow32((uint64)p->pid) : VMTRACE_NONE32;
  event.vpn = va == VMTRACE_NONE ? VMTRACE_NONE32 : narrow32(va / PGSIZE);
  event.victim_vpn = victim_va == VMTRACE_NONE ? VMTRACE_NONE32
                                               : narrow32(victim_va / PGSIZE);
  event.frame_index = narrow32(frame_index);
  event.swap_slot = slot < 0 ? VMTRACE_NONE32 : narrow32((uint64)slot);
  event.resident_count =
    p ? narrow32(p->vm.resident_count) : VMTRACE_NONE32;
  event.queue_id = narrow32(queue_id);
  event.status = (uint32)status;
  event.pte_flags = narrow16(pte_flags);
  event.type = (uint8)type;
  event.access = narrow8(access);
  event.page_state = narrow8(page_state);
  event.policy = p ? narrow8(p->vm.policy) : VMTRACE_NONE8;

  if(trace_ring.count == trace_ring.capacity){
    // The ring is full: the oldest record goes, and this one is replaced by
    // an in-band marker so a reader that only ever sees records still learns
    // that the stream is no longer complete. Both losses show up as a gap in
    // the sequence numbers.
    trace_ring.tail = (trace_ring.tail + 1) % trace_ring.capacity;
    trace_ring.count--;
    trace_ring.drops++;
    event.type = VMTRACE_DROP;
    event.status = (uint32)trace_ring.drops;
  }
  trace_ring.events[trace_ring.head] = event;
  trace_ring.head = (trace_ring.head + 1) % trace_ring.capacity;
  trace_ring.count++;
  release(&trace_ring.lock);
}

int
vmtrace_read(struct proc *p, uint64 destination, int maximum)
{
  if(p == 0 || maximum < 0 || maximum > VMTRACE_READ_MAX)
    return -1;
  int copied = 0;
  while(copied < maximum){
    struct vmtrace_event event;
    acquire(&trace_ring.lock);
    if(trace_ring.count == 0){
      release(&trace_ring.lock);
      break;
    }
    event = trace_ring.events[trace_ring.tail];
    trace_ring.tail = (trace_ring.tail + 1) % trace_ring.capacity;
    trace_ring.count--;
    release(&trace_ring.lock);
    // The lock is released first on purpose: the destination may be a lazily
    // allocated user page, so copyout can fault and page in under us.
    if(copyout(p->pagetable, p->sz,
               destination + copied * sizeof(event),
               (char *)&event, sizeof(event)) < 0)
      return copied ? copied : -1;
    copied++;
  }
  return copied;
}

int
vmtrace_info(struct proc *p, uint64 destination)
{
  if(p == 0)
    return -1;

  struct vmtrace_header header;
  memset(&header, 0, sizeof(header));
  header.version = VMTRACE_VERSION;
  header.record_size = sizeof(struct vmtrace_event);
  header.read_max = VMTRACE_READ_MAX;
  acquire(&trace_ring.lock);
  header.capacity = trace_ring.capacity;
  header.sequence = trace_ring.sequence;
  header.dropped = trace_ring.drops;
  header.buffered = trace_ring.count;
  header.enabled = trace_ring.enabled;
  release(&trace_ring.lock);

  if(copyout(p->pagetable, p->sz, destination, (char *)&header,
             sizeof(header)) < 0)
    return -1;
  return 0;
}
