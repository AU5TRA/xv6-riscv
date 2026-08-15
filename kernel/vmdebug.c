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
  if(type < VM_FAIL_NONE || type > VM_FAIL_DELAY_TICKS || value < 0)
    return -1;
  fail_type = type;
  fail_value = value;
  return 0;
}
#endif
