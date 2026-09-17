#ifndef XV6_SWAP_H
#define XV6_SWAP_H

#ifndef NSWAPSLOTS
#define NSWAPSLOTS 8192
#endif

#define SWAP_START_BLOCK FSSIZE
#define SWAP_BLOCKS_PER_PAGE (PGSIZE / BSIZE)
#define SWAP_START_SECTOR (SWAP_START_BLOCK * (BSIZE / 512))
#define SWAP_SECTOR(slot) (SWAP_START_SECTOR + (slot) * (PGSIZE / 512))
#define SLOT2PTE(slot) ((uint64)(slot) << 10)
#define PTE2SLOT(pte) ((int)((uint64)(pte) >> 10))

#define VM_TEST_SWAP_IO 1
#define VM_TEST_SWAP_REUSE 2
#define VM_TEST_SWAP_BOUNDS 3
#define VM_TEST_SWAP_IO_ERROR 4
#define VM_TEST_SWAP_RESERVE 5
#define VM_TEST_SWAP_RELEASE 6

#endif
