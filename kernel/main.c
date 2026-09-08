#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "defs.h"
#include "swap.h"
#include "vmstats.h"
#include "vmtrace.h"

volatile static int started = 0;


// Phase 2 acceptance criterion 15 requires the configuration of every
// experiment to be printed, not reconstructed afterwards from a commit
// hash and a memory of which build was used. Everything below is a
// compile-time constant, so this line is the build identifying itself:
// a transcript that does not carry it was produced by a different kernel
// than the one the numbers are attributed to.
static void
vm_print_config(void)
{
  printk("xv6 vm config: frames=%d resident_limit_max=%d policies=%d "
         "swapslots=%d swap_kb=%d\n",
         (int)((PHYSTOP - KERNBASE) / PGSIZE), VM_MAX_RESIDENT_LIMIT,
         VM_POLICY_COUNT, NSWAPSLOTS, (int)(NSWAPSLOTS * (PGSIZE / 1024)));
  printk("xv6 vm config: fssize=%d nbuf=%d userstack=%d "
         "trace_version=%d trace_capacity=%d trace_record=%d debug=%d\n",
         FSSIZE, NBUF, USERSTACK, VMTRACE_VERSION, VMTRACE_CAPACITY,
         (int)sizeof(struct vmtrace_event),
#ifdef VM_DEBUG
         1
#else
         0
#endif
         );
}

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
    vm_print_config();  // provenance banner for every experiment
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
