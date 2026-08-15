#include "types.h"

#ifdef VM_DEBUG
// Debug-only paging checks and fault injection are added alongside the VM
// metadata. Keeping this translation unit in the first harness gate verifies
// that VM_DEBUG builds select their own instrumentation cleanly.
void
vmdebug_init(void)
{
}
#endif
