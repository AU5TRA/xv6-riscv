#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmstats.h"

static void
clear_stats(struct vmstate *vm)
{
  uint64 generation = vm->generation;
  memset(&vm->stats, 0, sizeof(vm->stats));
  vm->stats.version = VMSTATS_VERSION;
  vm->stats.generation = generation;
}

void
vmstate_init(struct proc *p)
{
  initlock(&p->vm.lock, "vmstate");
  p->vm.generation = 0;
  vmstate_reset(p);
}

void
vmstate_reset(struct proc *p)
{
  acquire(&p->vm.lock);
  p->vm.resident_limit = VM_LIMIT_UNLIMITED;
  p->vm.resident_count = 0;
  p->vm.policy = VM_POLICY_FIFO;
  p->vm.prefetch_enabled = 0;
  p->vm.prefetch_async = 0;
  p->vm.prefetch_automatic = 0;
  p->vm.exiting = 0;
  p->vm.queued_prefetch = 0;
  p->vm.inflight_io = 0;
  p->vm.clock_hand = 0;
  p->vm.prefetch_head = 0;
  p->vm.prefetch_count = 0;
  p->vm.next_prefetch_id = 1;
#ifdef VM_DEBUG
  p->vm.invalid_policy_once = 0;
#endif
  p->vm.generation++;
  clear_stats(&p->vm);
  release(&p->vm.lock);
}

void
vmstate_inherit(struct proc *child, struct proc *parent)
{
  acquire(&parent->vm.lock);
  acquire(&child->vm.lock);
  child->vm.resident_limit = parent->vm.resident_limit;
  child->vm.policy = parent->vm.policy;
  child->vm.prefetch_enabled = parent->vm.prefetch_enabled;
  child->vm.prefetch_async = parent->vm.prefetch_async;
  child->vm.prefetch_automatic = parent->vm.prefetch_automatic;
  child->vm.clock_hand = 0;
  child->vm.prefetch_head = 0;
  child->vm.prefetch_count = 0;
  child->vm.next_prefetch_id = 1;
  clear_stats(&child->vm);
  release(&child->vm.lock);
  release(&parent->vm.lock);
}

void
vmstate_exec_reset(struct proc *p)
{
  acquire(&p->vm.lock);
  p->vm.prefetch_head = 0;
  p->vm.prefetch_count = 0;
  p->vm.queued_prefetch = 0;
  p->vm.inflight_io = 0;
  clear_stats(&p->vm);
  release(&p->vm.lock);
}

int
vmstate_ctl(struct proc *p, int command, uint64 value)
{
  int result = 0;

  acquire(&p->vm.lock);
  switch(command){
  case VM_SET_LIMIT:
    if(value > VM_MAX_RESIDENT_LIMIT ||
       (value != VM_LIMIT_UNLIMITED && value < p->vm.resident_count))
      result = -1;
    else
      p->vm.resident_limit = value;
    break;
  case VM_SET_POLICY:
    if(value >= VM_POLICY_COUNT)
      result = -1;
    else
      p->vm.policy = value;
    break;
  case VM_PREFETCH_ENABLE:
    if(value > 1)
      result = -1;
    else
      p->vm.prefetch_enabled = value;
    break;
  case VM_RESET_STATS:
    if(value != 0)
      result = -1;
    else
      clear_stats(&p->vm);
    break;
  case VM_PREFETCH_MODE:
    if(value > 1 || p->vm.inflight_io != 0 || p->vm.prefetch_count != 0)
      result = -1;
    else
      p->vm.prefetch_async = value;
    break;
  case VM_PREFETCH_AUTOMATIC:
    if(value > 1)
      result = -1;
    else
      p->vm.prefetch_automatic = value;
    break;
  case VM_TRACE_ENABLE:
  case VM_TRACE_RESET:
  case VM_TRACE_SET_CAPACITY:
    result = vmtrace_control(command, value);
    break;
  default:
    result = -1;
    break;
  }
  release(&p->vm.lock);
  return result;
}

void
vmstate_snapshot(struct proc *p, struct vmstats *out)
{
  acquire(&p->vm.lock);
  *out = p->vm.stats;
  out->version = VMSTATS_VERSION;
  out->resident_limit = p->vm.resident_limit;
  out->resident_count = p->vm.resident_count;
  out->policy = p->vm.policy;
  out->prefetch_enabled = p->vm.prefetch_enabled;
  out->prefetch_async = p->vm.prefetch_async;
  out->prefetch_automatic = p->vm.prefetch_automatic;
  out->generation = p->vm.generation;
  out->queued_prefetch = p->vm.queued_prefetch;
  out->inflight_io = p->vm.inflight_io;
  release(&p->vm.lock);
  out->free_swap_slots = swap_free_slots();
}
