#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "defs.h"

volatile static int started = 0;

// start() jumps here in supervisor mode on all CPUs.
void
main()
{
  if (cpuid() == 0) {
    consoleinit();
    printkinit();
    printk("\n");
    printk("xv6 kernel is booting\n");
    printk("\n");
    kinit();            // physical page allocator
    vmpage_init();      // pageable frame metadata
    kvminit();          // create kernel page table
    kvminithart();      // turn on paging
    procinit();         // process table
    trapinit();         // trap vectors
    trapinithart();     // install kernel trap vector
    plicinit();         // set up interrupt controller
    plicinithart();     // ask PLIC for device interrupts
    binit();            // buffer cache
    iinit();            // inode table
    fileinit();         // file table
    virtio_disk_init(); // emulated hard disk
    swap_init();        // raw disk-backed paging slots
    vm_prefetch_init(); // asynchronous paging work queue
    vmtrace_init();      // preallocated paging event ring
    userinit();         // first user process
    vm_prefetch_worker_start();

    __atomic_store_n(&started, 1, __ATOMIC_RELEASE);
  } else {
    while (__atomic_load_n(&started, __ATOMIC_ACQUIRE) == 0)
      ;

    printk("hart %d starting\n", cpuid());
    // The paging/swap subsystem's locking discipline assumes CPUS=1: victim
    // selection, eviction, and fetch/prefetch state transitions all rely on
    // a process never running its own kernel code on two harts at once, and
    // there is no cross-hart TLB shootdown after a PTE is invalidated or
    // repointed. Reaching here means a second hart has joined, so paging
    // correctness beyond CPUS=1 is not guaranteed -- treat this as a
    // stress-test configuration only, not a correctness reference.
    printk("warning: hart %d joining with CPUS>1; paging/swap correctness "
           "is only validated at CPUS=1 (no cross-hart TLB shootdown)\n",
           cpuid());
    kvminithart();  // turn on paging
    trapinithart(); // install kernel trap vector
    plicinithart(); // ask PLIC for device interrupts
  }

  scheduler();
}
