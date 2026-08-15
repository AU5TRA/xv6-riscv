#include "kernel/types.h"
#include "user/user.h"

static int
harness(void)
{
  return 0;
}

static int
run(char *name)
{
  if(strcmp(name, "harness") == 0)
    return harness();
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
