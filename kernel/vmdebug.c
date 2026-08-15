#include "types.h"
#include "vmstats.h"

#ifdef VM_DEBUG
// Debug-only paging checks and fault injection are added alongside the VM
// metadata. Keeping this translation unit in the first harness gate verifies
// that VM_DEBUG builds select their own instrumentation cleanly.
void
vmdebug_init(void)
{
}

static int fail_type;
static int fail_value;

int
vmdebug_failinject(int type, int value)
{
  if(type < VM_FAIL_NONE || type > VM_FAIL_FRAME_ALLOC || value < 0)
    return -1;
  fail_type = type;
  fail_value = value;
  return 0;
}

int
vmdebug_should_fail(int type)
{
  if(fail_type != type || fail_value == 0)
    return 0;
  fail_value--;
  if(fail_value == 0){
    fail_type = VM_FAIL_NONE;
    return 1;
  }
  return 0;
}

int
vmdebug_take_delay(void)
{
  if(fail_type != VM_FAIL_DELAY_TICKS || fail_value == 0)
    return 0;
  int delay = fail_value;
  fail_type = VM_FAIL_NONE;
  fail_value = 0;
  return delay;
}
#endif
