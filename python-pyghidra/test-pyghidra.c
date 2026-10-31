#include <stdio.h>

__declspec(dllexport) __attribute__((noinline)) unsigned pyghidra_checksum(const char *s)
{
  unsigned h = 5381;
  while (*s)
    h = h * 33 + (unsigned char)*s++;
  return h;
}

int main(int argc, char **argv)
{
  printf("%u\n", pyghidra_checksum(argc > 1 ? argv[1] : "pyghidra"));
  return 0;
}
