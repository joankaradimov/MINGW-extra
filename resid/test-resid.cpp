// Plays a sawtooth on voice 1 and checks that the output is loud enough
// and has the pitch the frequency register asks for, on both chip models
// and with both a direct and a resampling sampling method.
#include <resid/sid.h>

#include <cmath>
#include <cstdio>
#include <vector>

static const double clock_pal = 985248.0;
static const double sample_rate = 44100.0;

static bool play(chip_model model, sampling_method method, const char *name)
{
  SID sid;
  sid.set_chip_model(model);
  if (!sid.set_sampling_parameters(clock_pal, method, sample_rate)) {
    std::printf("%s: set_sampling_parameters failed\n", name);
    return false;
  }
  sid.reset();

  const unsigned freq = 7382;  // 433.5 Hz at the PAL clock
  sid.write(0x18, 0x0f);       // volume 15, no filter
  sid.write(0x00, freq & 0xff);
  sid.write(0x01, freq >> 8);
  sid.write(0x05, 0x00);       // attack 2 ms, decay 6 ms
  sid.write(0x06, 0xf0);       // sustain 15, release 6 ms
  sid.write(0x04, 0x21);       // sawtooth, gate on

  std::vector<short> buf(int(sample_rate) + 1024);
  cycle_count left = cycle_count(clock_pal);  // one second
  int n = 0;
  while (left > 0 && n < int(buf.size()))
    n += sid.clock(left, &buf[n], int(buf.size()) - n);

  // Skip the first 100 ms (attack, and the resampler's warm-up).
  const int start = int(sample_rate / 10);
  double mean = 0;
  for (int i = start; i < n; ++i) mean += buf[i];
  mean /= n - start;

  double sq = 0;
  int rising = 0;
  int first = -1, last = -1;
  for (int i = start; i < n; ++i) {
    double v = buf[i] - mean;
    sq += v * v;
    // A sawtooth climbs slowly and drops at once; count the drops.
    if (i > start && buf[i - 1] - mean > 0 && v < 0 &&
        buf[i - 1] - buf[i] > 2000) {
      if (first < 0) first = i;
      last = i;
      ++rising;
    }
  }
  double rms = std::sqrt(sq / (n - start));
  double expected = freq * clock_pal / 16777216.0;
  double measured = rising > 1 ? (rising - 1) * sample_rate / (last - first) : 0;

  bool ok = n >= int(sample_rate) - 1 && rms > 2000 &&
            std::fabs(measured - expected) < expected * 0.01;
  std::printf("%-28s samples %d  rms %.0f  pitch %.1f Hz (want %.1f)  %s\n",
              name, n, rms, measured, expected, ok ? "ok" : "FAIL");
  return ok;
}

int main()
{
  bool ok = true;
  ok &= play(MOS6581, SAMPLE_FAST, "6581 fast");
  ok &= play(MOS8580, SAMPLE_FAST, "8580 fast");
  ok &= play(MOS6581, SAMPLE_RESAMPLE_INTERPOLATE, "6581 resample-interpolate");
  ok &= play(MOS8580, SAMPLE_RESAMPLE_INTERPOLATE, "8580 resample-interpolate");
  return ok ? 0 : 1;
}
