#include "types.h"
#include "riscv.h"
#include "defs.h"
#include "param.h"
#include "spinlock.h"
#include "proc.h"
#include "fs.h"
#include "sleeplock.h"
#include "file.h"

#define PIPESIZE 512

struct pipe {
  struct spinlock lock;
  char data[PIPESIZE];
  uint nread;    // number of bytes read
  uint nwrite;   // number of bytes written
  int readopen;  // read fd is still open
  int writeopen; // write fd is still open
};

int
pipealloc(struct file **f0, struct file **f1)
{
  struct pipe *pi;

  pi = 0;
  *f0 = *f1 = 0;
  if ((*f0 = filealloc()) == 0 || (*f1 = filealloc()) == 0)
    goto bad;
  if ((pi = (struct pipe *)kalloc()) == 0)
    goto bad;
  pi->readopen = 1;
  pi->writeopen = 1;
  pi->nwrite = 0;
  pi->nread = 0;
  initlock(&pi->lock, "pipe");
  (*f0)->type = FD_PIPE;
  (*f0)->readable = 1;
  (*f0)->writable = 0;
  (*f0)->pipe = pi;
  (*f1)->type = FD_PIPE;
  (*f1)->readable = 0;
  (*f1)->writable = 1;
  (*f1)->pipe = pi;
  return 0;

bad:
  if (pi)
    kfree((char *)pi);
  if (*f0)
    fileclose(*f0);
  if (*f1)
    fileclose(*f1);
  return -1;
}

void
pipeclose(struct pipe *pi, int writable)
{
  acquire(&pi->lock);
  if (writable) {
    pi->writeopen = 0;
    wakeup(&pi->nread);
  } else {
    pi->readopen = 0;
    wakeup(&pi->nwrite);
  }
  if (pi->readopen == 0 && pi->writeopen == 0) {
    release(&pi->lock);
    kfree((char *)pi);
  } else
    release(&pi->lock);
}

int
pipewrite(struct pipe *pi, uint64 addr, int n)
{
  int i = 0;
  struct proc *pr = myproc();
  char staging[PIPESIZE];

  while (i < n) {
    int count = n - i;
    if(count > PIPESIZE)
      count = PIPESIZE;

    // User pages can fault and perform swap I/O.  Stage them without the
    // pipe spinlock held, then preserve the usual pipe synchronization while
    // committing the bytes.
    if(copyin(pr->pagetable, pr->sz, staging, addr + i, count) < 0)
      return i == 0 ? -1 : i;

    acquire(&pi->lock);
    for(int j = 0; j < count;){
      if (pi->readopen == 0 || killed(pr)) {
        release(&pi->lock);
        return -1;
      }
      if (pi->nwrite == pi->nread + PIPESIZE) { //DOC: pipewrite-full
        wakeup(&pi->nread);
        sleep_prepare(&pi->nwrite);
        release(&pi->lock);
        sleep();
        acquire(&pi->lock);
      } else {
        pi->data[pi->nwrite++ % PIPESIZE] = staging[j++];
        i++;
      }
    }
    wakeup(&pi->nread);
    release(&pi->lock);
  }

  return i;
}

int
piperead(struct pipe *pi, uint64 addr, int n)
{
  int i;
  struct proc *pr = myproc();
  char staging[PIPESIZE];

  acquire(&pi->lock);
  while (pi->nread == pi->nwrite && pi->writeopen) { //DOC: pipe-empty
    if (killed(pr)) {
      release(&pi->lock);
      return -1;
    }
    sleep_prepare(&pi->nread); //DOC: piperead-sleep
    release(&pi->lock);
    sleep();
    acquire(&pi->lock);
  }
  for (i = 0; i < n && i < PIPESIZE; i++) { //DOC: piperead-copy
    if (pi->nread == pi->nwrite)
      break;
    staging[i] = pi->data[pi->nread++ % PIPESIZE];
  }
  wakeup(&pi->nwrite); //DOC: piperead-wakeup
  release(&pi->lock);

  // As with pipewrite, swapped user pages must be faulted without holding a
  // spinlock.  The bytes have already been removed from the pipe at this
  // point, matching an ordinary read once the copy succeeds.
  if(i != 0 && copyout(pr->pagetable, pr->sz, addr, staging, i) < 0)
    return -1;
  return i;
}
