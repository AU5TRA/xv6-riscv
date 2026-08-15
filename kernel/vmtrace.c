#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmtrace.h"

static struct {
  struct spinlock lock;
  struct vmtrace_event events[VMTRACE_CAPACITY];
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

void
vmtrace_init(void)
{
  initlock(&trace_ring.lock, "vmtrace");
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
    else {
      trace_ring.head = 0;
      trace_ring.tail = 0;
      trace_ring.count = 0;
      trace_ring.sequence = 0;
      trace_ring.drops = 0;
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
  event.version = VMTRACE_VERSION;
  event.size = sizeof(event);
  event.sequence = ++trace_ring.sequence;
  event.cycle = trace_cycle();
  event.ticks = ticks;
  event.pid = p ? p->pid : VMTRACE_NONE;
  event.generation = p ? p->vm.generation : VMTRACE_NONE;
  event.type = type;
  event.vpn = va == VMTRACE_NONE ? VMTRACE_NONE : va / PGSIZE;
  event.access = access < 0 ? VMTRACE_NONE : (uint64)access;
  event.page_state = page_state < 0 ? VMTRACE_NONE : (uint64)page_state;
  event.pte_flags = pte_flags;
  event.frame_index = frame_index;
  event.swap_slot = slot < 0 ? VMTRACE_NONE : (uint64)slot;
  event.policy = p ? p->vm.policy : VMTRACE_NONE;
  event.victim_vpn = victim_va == VMTRACE_NONE ? VMTRACE_NONE :
    victim_va / PGSIZE;
  event.queue_id = queue_id;
  event.resident_count = p ? p->vm.resident_count : VMTRACE_NONE;
  event.status = status;

  if(trace_ring.count == VMTRACE_CAPACITY){
    trace_ring.tail = (trace_ring.tail + 1) % VMTRACE_CAPACITY;
    trace_ring.count--;
    trace_ring.drops++;
    event.type = VMTRACE_DROP;
    event.status = trace_ring.drops;
  }
  trace_ring.events[trace_ring.head] = event;
  trace_ring.head = (trace_ring.head + 1) % VMTRACE_CAPACITY;
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
    trace_ring.tail = (trace_ring.tail + 1) % VMTRACE_CAPACITY;
    trace_ring.count--;
    release(&trace_ring.lock);
    if(copyout(p->pagetable, p->sz,
               destination + copied * sizeof(event),
               (char *)&event, sizeof(event)) < 0)
      return copied ? copied : -1;
    copied++;
  }
  return copied;
}
