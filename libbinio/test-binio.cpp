// Round-trips integers, floats and strings through libbinio's memory and
// file streams, in both byte orders.
#include <binstr.h>
#include <binfile.h>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>

static int failures = 0;

#define CHECK(cond)                                                  \
  do {                                                               \
    if (!(cond)) {                                                   \
      std::fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__,     \
                   __LINE__, #cond);                                 \
      ++failures;                                                    \
    }                                                                \
  } while (0)

static void write_all(binostream &out, bool big_endian)
{
  out.setFlag(binio::BigEndian, big_endian);
  out.writeInt(0x12, 1);
  out.writeInt(0x1234, 2);
  out.writeInt(0x12345678, 4);
  out.writeFloat(1.5, binio::Single);
  out.writeFloat(-2.25, binio::Double);
  out.writeString(std::string("libbinio"));
  out.writeInt(0, 1);
}

static void read_all(binistream &in, bool big_endian)
{
  in.setFlag(binio::BigEndian, big_endian);
  CHECK(in.readInt(1) == 0x12);
  CHECK(in.readInt(2) == 0x1234);
  CHECK(in.readInt(4) == 0x12345678);
  CHECK(std::fabs(in.readFloat(binio::Single) - 1.5) < 1e-9);
  CHECK(std::fabs(in.readFloat(binio::Double) + 2.25) < 1e-12);
  CHECK(in.readString('\0') == "libbinio");
  CHECK(in.error() == binio::NoError);
}

int main(int argc, char **argv)
{
  for (int big = 0; big < 2; ++big) {
    unsigned char buf[64];
    std::memset(buf, 0xAA, sizeof buf);

    binosstream out(buf, sizeof buf);
    write_all(out, big);
    CHECK(out.error() == binio::NoError);

    // The 16-bit value's bytes show which order was written.
    CHECK(buf[1] == (big ? 0x12 : 0x34));
    CHECK(buf[2] == (big ? 0x34 : 0x12));

    binisstream in(buf, sizeof buf);
    read_all(in, big);
  }

  const char *path = argc > 1 ? argv[1] : "test-binio.bin";
  {
    binofstream out(path);
    CHECK(out.error() == binio::NoError);
    write_all(out, true);
  }
  {
    binifstream in(path);
    CHECK(in.error() == binio::NoError);
    read_all(in, true);
    in.readInt(1);
    CHECK(in.eof());
  }
  std::remove(path);

  if (failures == 0)
    std::puts("libbinio: all checks passed");
  return failures == 0 ? 0 : 1;
}
