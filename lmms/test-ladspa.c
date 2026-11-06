/* Loads each LADSPA library named on the command line, then instantiates
 * and runs every plugin in it for one block of noise. Fails when a
 * library does not load, exports no descriptors, or a plugin cannot be
 * instantiated. */
#include <windows.h>

#include <stdio.h>
#include <stdlib.h>

#include "ladspa.h"

#define BLOCK 256
#define MAX_PORTS 128

static LADSPA_Data default_value(const LADSPA_PortRangeHint *h)
{
  LADSPA_PortRangeHintDescriptor d = h->HintDescriptor;
  LADSPA_Data lo = h->LowerBound, hi = h->UpperBound;
  switch (d & LADSPA_HINT_DEFAULT_MASK) {
  case LADSPA_HINT_DEFAULT_MINIMUM: return lo;
  case LADSPA_HINT_DEFAULT_LOW: return lo * 0.75f + hi * 0.25f;
  case LADSPA_HINT_DEFAULT_MIDDLE: return (lo + hi) / 2;
  case LADSPA_HINT_DEFAULT_HIGH: return lo * 0.25f + hi * 0.75f;
  case LADSPA_HINT_DEFAULT_MAXIMUM: return hi;
  case LADSPA_HINT_DEFAULT_0: return 0;
  case LADSPA_HINT_DEFAULT_1: return 1;
  case LADSPA_HINT_DEFAULT_100: return 100;
  case LADSPA_HINT_DEFAULT_440: return 440;
  }
  if (LADSPA_IS_HINT_BOUNDED_BELOW(d)) return lo;
  if (LADSPA_IS_HINT_BOUNDED_ABOVE(d)) return hi < 0 ? hi : 0;
  return 0;
}

static int run_plugin(const LADSPA_Descriptor *desc)
{
  static LADSPA_Data audio[MAX_PORTS][BLOCK];
  static LADSPA_Data control[MAX_PORTS];
  if (desc->PortCount > MAX_PORTS) {
    printf("  %s: %lu ports, skipped\n", desc->Label, desc->PortCount);
    return 0;
  }
  LADSPA_Handle h = desc->instantiate(desc, 44100);
  if (!h) {
    printf("  %s: instantiate failed\n", desc->Label);
    return 1;
  }
  for (unsigned long p = 0; p < desc->PortCount; ++p) {
    LADSPA_PortDescriptor pd = desc->PortDescriptors[p];
    if (LADSPA_IS_PORT_AUDIO(pd)) {
      for (int i = 0; i < BLOCK; ++i)
        audio[p][i] = LADSPA_IS_PORT_INPUT(pd) ? (rand() / (float)RAND_MAX - 0.5f) : 0;
      desc->connect_port(h, p, audio[p]);
    } else {
      control[p] = default_value(&desc->PortRangeHints[p]);
      desc->connect_port(h, p, &control[p]);
    }
  }
  if (desc->activate) desc->activate(h);
  desc->run(h, BLOCK);
  if (desc->deactivate) desc->deactivate(h);
  desc->cleanup(h);
  return 0;
}

int main(int argc, char **argv)
{
  int failures = 0;
  for (int a = 1; a < argc; ++a) {
    HMODULE lib = LoadLibraryA(argv[a]);
    if (!lib) {
      printf("%s: LoadLibrary failed, error %lu\n", argv[a], GetLastError());
      ++failures;
      continue;
    }
    LADSPA_Descriptor_Function fn =
        (LADSPA_Descriptor_Function)(void *)GetProcAddress(lib, "ladspa_descriptor");
    if (!fn) {
      printf("%s: no ladspa_descriptor\n", argv[a]);
      ++failures;
      continue;
    }
    unsigned long n = 0;
    const LADSPA_Descriptor *desc;
    while ((desc = fn(n)) != NULL) {
      failures += run_plugin(desc);
      ++n;
    }
    printf("%s: %lu plugins\n", argv[a], n);
    if (n == 0) ++failures;
  }
  return failures ? 1 : 0;
}
