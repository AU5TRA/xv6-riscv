#include "kernel/types.h"
#include "user/user.h"
#include "kernel/vmstats.h"
#include "kernel/swap.h"

static int
harness(void)
{
  return 0;
}

static int
controls(void)
{
  struct vmstats stats;

  if(vmstats(&stats) < 0 || stats.version != VMSTATS_VERSION ||
     stats.resident_limit != VM_LIMIT_UNLIMITED ||
     stats.policy != VM_POLICY_FIFO || stats.prefetch_enabled != 0)
    return -1;
  if(vmctl(VM_SET_LIMIT, 8) < 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_CLOCK) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return -1;
  if(vmctl(VM_SET_LIMIT, VM_MAX_RESIDENT_LIMIT + 1) == 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_COUNT) == 0 ||
     vmctl(VM_PREFETCH_ENABLE, 2) == 0 || vmctl(999, 0) == 0)
    return -1;
  if(vmstats(&stats) < 0 || stats.resident_limit != 8 ||
     stats.policy != VM_POLICY_CLOCK || stats.prefetch_enabled != 1)
    return -1;
  return vmcheck();
}

static int
inherit(void)
{
  int status;
  if(vmctl(VM_SET_LIMIT, 7) < 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_AGING) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    struct vmstats stats;
    int ok = vmstats(&stats) == 0 && stats.resident_limit == 7 &&
      stats.policy == VM_POLICY_AGING && stats.prefetch_enabled == 1 &&
      vmcheck() == 0;
    exit(ok ? 0 : 1);
  }
  if(wait(&status) != pid || status != 0)
    return -1;
  return vmcheck();
}

static int
limit_basic(void)
{
  struct vmstats before, after;
  if(vmstats(&before) < 0 || before.resident_count + 8 >
     VM_MAX_RESIDENT_LIMIT)
    return -1;
  if(vmctl(VM_SET_LIMIT, before.resident_count + 8) < 0)
    return -1;
  char *base = sbrk(8 * 4096);
  if(base == SBRK_ERROR || sbrk(4096) != SBRK_ERROR)
    return -1;
  if(vmstats(&after) < 0 || after.resident_count != before.resident_count + 8 ||
     after.resident_count > after.resident_limit)
    return -1;
  if(sbrk(-8 * 4096) == SBRK_ERROR || vmstats(&after) < 0 ||
     after.resident_count != before.resident_count)
    return -1;
  return vmcheck();
}

static int
run(char *name)
{
  if(strcmp(name, "harness") == 0)
    return harness();
  if(strcmp(name, "controls") == 0)
    return controls();
  if(strcmp(name, "inherit") == 0)
    return inherit();
  if(strcmp(name, "swapio") == 0)
    return vmtestop(VM_TEST_SWAP_IO, 0);
  if(strcmp(name, "swap-reuse") == 0)
    return vmtestop(VM_TEST_SWAP_REUSE, 0);
  if(strcmp(name, "swap-bounds") == 0)
    return vmtestop(VM_TEST_SWAP_BOUNDS, 0);
  if(strcmp(name, "swap-io-error") == 0)
    return vmtestop(VM_TEST_SWAP_IO_ERROR, 0);
  if(strcmp(name, "limit-basic") == 0)
    return limit_basic();
  if(strcmp(name, "pin") == 0)
    return vmtestop(VM_TEST_FRAME_PIN, 0);
  if(strcmp(name, "metadata-reuse") == 0)
    return vmtestop(VM_TEST_FRAME_METADATA, 0);
  if(strcmp(name, "all") == 0){
    if(harness() < 0 || controls() < 0 || inherit() < 0)
      return -1;
    return 0;
  }
  printf("vmtest: unknown test %s\n", name);
  return -1;
}

int
main(int argc, char **argv)
{
  char *name = argc > 1 ? argv[1] : "harness";

  if(run(name) < 0){
    printf("vmtest: %s: FAIL\n", name);
    exit(1);
  }
  printf("vmtest: %s: PASS\n", name);
  exit(0);
}
