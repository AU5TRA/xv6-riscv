#include "types.h"
#include "riscv.h"
#include "defs.h"
#include "param.h"
#include "memlayout.h"
#include "spinlock.h"
#include "proc.h"
#include "vm.h"
#include "vmstats.h"
#include "vmpage.h"

uint64
sys_exit(void)
{
  int n;
  argint(0, &n);
  kexit(n);
  return 0; // not reached
}

uint64
sys_getpid(void)
{
  return myproc()->pid;
}

uint64
sys_fork(void)
{
  return kfork();
}

uint64
sys_wait(void)
{
  uint64 p;
  argaddr(0, &p);
  return kwait(p);
}

uint64
sys_sbrk(void)
{
  uint64 addr;
  int t;
  int n;

  argint(0, &n);
  argint(1, &t);
  addr = myproc()->sz;

  if (t == SBRK_EAGER || n < 0) {
    if (growproc(n) < 0) {
      return -1;
    }
  } else {
    // Lazily allocate memory for this process: increase its memory
    // size but don't allocate memory. If the processes uses the
    // memory, vmfault() will allocate it.
    if (addr + n < addr)
      return -1;
    if (addr + n > TRAPFRAME)
      return -1;
    myproc()->sz += n;
  }
  return addr;
}

uint64
sys_pause(void)
{
  int n;
  uint ticks0;

  argint(0, &n);
  if (n < 0)
    n = 0;
  acquire(&tickslock);
  ticks0 = ticks;
  while (ticks - ticks0 < n) {
    if (killed(myproc())) {
      release(&tickslock);
      return -1;
    }
    sleep_prepare(&ticks);
    release(&tickslock);
    sleep();
    acquire(&tickslock);
  }
  release(&tickslock);
  return 0;
}

uint64
sys_kill(void)
{
  int pid;

  argint(0, &pid);
  return kkill(pid);
}

// return how many clock tick interrupts have occurred
// since start.
uint64
sys_uptime(void)
{
  uint xticks;

  acquire(&tickslock);
  xticks = ticks;
  release(&tickslock);
  return xticks;
}

uint64
sys_vmctl(void)
{
  int command;
  uint64 value;

  argint(0, &command);
  argaddr(1, &value);
  return vmstate_ctl(myproc(), command, value);
}

uint64
sys_vmstats(void)
{
  uint64 address;
  struct vmstats stats;
  struct proc *p = myproc();

  argaddr(0, &address);
  vmstate_snapshot(p, &stats);
  return copyout(p->pagetable, p->sz, address, (char *)&stats,
                 sizeof(stats));
}

uint64
sys_vmcheck(void)
{
#ifdef VM_DEBUG
  return vmpage_check_proc(myproc());
#else
  // Keep release test and benchmark code source-compatible. The expensive
  // ownership walk is intentionally absent from a non-debug kernel.
  return 0;
#endif
}

uint64
sys_vmfailinject(void)
{
  int type;
  int value;

  argint(0, &type);
  argint(1, &value);
#ifdef VM_DEBUG
  return vmdebug_failinject(type, value);
#else
  return -1;
#endif
}

uint64
sys_vmtestop(void)
{
  int operation;
  int argument;

  argint(0, &operation);
  argint(1, &argument);
#ifdef VM_DEBUG
  if(operation >= VM_TEST_FRAME_PIN)
    return vmpage_debug_test(operation);
  return swap_debug_test(operation, argument);
#else
  return -1;
#endif
}

uint64
sys_vmprefetch(void)
{
  uint64 va;
  int service;
  argaddr(0, &va);
  argint(1, &service);
  if(service < 0 || service > VM_PREFETCH_SERVICE_ALL)
    return -1;
  struct proc *p = myproc();
  int hint_result = 0;
  if(va != VM_PREFETCH_NO_HINT)
    hint_result = vm_prefetch_hint(p, va, 0);
  int completed = service ? vm_prefetch_service(p, service) : 0;
  if(hint_result < 0 && completed == 0)
    return -1;
  return completed;
}

uint64
sys_vmtrace_read(void)
{
  uint64 destination;
  int maximum;
  argaddr(0, &destination);
  argint(1, &maximum);
  return vmtrace_read(myproc(), destination, maximum);
}

uint64
sys_vmtrace_info(void)
{
  uint64 destination;
  argaddr(0, &destination);
  return vmtrace_info(myproc(), destination);
}
