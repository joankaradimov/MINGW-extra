#include <cstdio>

namespace ghidra_test {

__declspec(dllexport) __attribute__((noinline)) unsigned checksum(const char *s)
{
  unsigned h = 5381;
  while (*s)
    h = h * 33 + static_cast<unsigned char>(*s++);
  return h;
}

}

int main(int argc, char **argv)
{
  std::printf("%u\n", ghidra_test::checksum(argc > 1 ? argv[1] : "ghidra"));
  return 0;
}
