/* Prints the peak level of a 16-bit PCM or 32-bit float WAV file and
 * exits 0 when the file is not silent. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static uint32_t le32(const unsigned char *p)
{
  return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint16_t le16(const unsigned char *p)
{
  return p[0] | p[1] << 8;
}

int main(int argc, char **argv)
{
  if (argc != 2) {
    fprintf(stderr, "usage: %s file.wav\n", argv[0]);
    return 2;
  }
  FILE *f = fopen(argv[1], "rb");
  if (!f) {
    perror(argv[1]);
    return 2;
  }

  unsigned char hdr[12];
  if (fread(hdr, 1, 12, f) != 12 || memcmp(hdr, "RIFF", 4) || memcmp(hdr + 8, "WAVE", 4)) {
    fprintf(stderr, "%s: not a WAV file\n", argv[1]);
    return 2;
  }

  int format = 0, bits = 0;
  unsigned char ck[8];
  while (fread(ck, 1, 8, f) == 8) {
    uint32_t size = le32(ck + 4);
    if (!memcmp(ck, "fmt ", 4)) {
      unsigned char fmt[16];
      if (size < 16 || fread(fmt, 1, 16, f) != 16) return 2;
      format = le16(fmt);
      bits = le16(fmt + 14);
      fseek(f, size - 16 + (size & 1), SEEK_CUR);
    } else if (!memcmp(ck, "data", 4)) {
      double peak = 0;
      unsigned long frames = 0;
      if (format == 1 && bits == 16) {
        unsigned char s[2];
        for (uint32_t i = 0; i < size / 2 && fread(s, 1, 2, f) == 2; ++i, ++frames) {
          double v = fabs((int16_t)le16(s) / 32768.0);
          if (v > peak) peak = v;
        }
      } else if (format == 3 && bits == 32) {
        float s;
        for (uint32_t i = 0; i < size / 4 && fread(&s, 4, 1, f) == 1; ++i, ++frames) {
          double v = fabs(s);
          if (v > peak) peak = v;
        }
      } else {
        fprintf(stderr, "%s: format %d, %d bits not supported\n", argv[1], format, bits);
        return 2;
      }
      printf("%s: %lu samples, peak %.4f\n", argv[1], frames, peak);
      return peak > 0.01 ? 0 : 1;
    } else {
      fseek(f, size + (size & 1), SEEK_CUR);
    }
  }
  fprintf(stderr, "%s: no data chunk\n", argv[1]);
  return 2;
}
