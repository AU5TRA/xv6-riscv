#include "kernel/types.h"
#include "user/user.h"

int
main(int argc, char **argv)
{
  char *name = argc > 1 ? argv[1] : "harness";

  if(strcmp(name, "harness") != 0){
    printf("prefetchtest: unknown test %s\n", name);
    printf("prefetchtest: %s: FAIL\n", name);
    exit(1);
  }
  printf("prefetchtest: %s: PASS\n", name);
  exit(0);
}
