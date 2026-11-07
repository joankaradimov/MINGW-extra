# Runs Carla's engine headless through its own Python backend, with the
# Dummy driver: an internal plugin, a JSFX tone generator (ysfx), Carla's
# internal plugins as LV2 (lilv on serd, sord and sratom) and Carla-Rack as
# a VST2 (JUCE). The tone has to reach the plugin's output peak meter.
#
# Usage: python test-carla-engine.py <prefix> <scratch-dir>

import os
import sys
import time

prefix, scratch = sys.argv[1], sys.argv[2]
share = os.path.join(prefix, "share", "carla")
libdir = os.path.join(prefix, "lib", "carla")
sys.path.insert(0, share)

from carla_backend import (  # noqa: E402
    BINARY_NATIVE, CarlaHostDLL, ENGINE_OPTION_PATH_BINARIES,
    ENGINE_OPTION_PATH_RESOURCES, ENGINE_OPTION_PLUGIN_PATH,
    ENGINE_OPTION_PROCESS_MODE, ENGINE_PROCESS_MODE_CONTINUOUS_RACK,
    PLUGIN_INTERNAL, PLUGIN_JSFX, PLUGIN_LV2, PLUGIN_VST2)
from carla_utils import CarlaUtils  # noqa: E402


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        sys.exit(1)


lv2dir = os.path.join(prefix, "lib", "lv2")
with open(os.path.join(lv2dir, "carla.lv2", "manifest.ttl")) as f:
    declared = f.read().count("a lv2:Plugin")
utils = CarlaUtils(os.path.join(libdir, "libcarla_utils.dll"))
count = utils.get_cached_plugin_count(PLUGIN_LV2, lv2dir)
check(count == declared > 0, f"lilv finds all {declared} of Carla's LV2 plugins ({count})")

tone = os.path.join(scratch, "tone.jsfx")
with open(tone, "w") as f:
    f.write("desc:Test tone\n"
            "out_pin:left\n"
            "out_pin:right\n"
            "@init\n"
            "phase = 0;\n"
            "@sample\n"
            "spl0 = spl1 = 0.5 * sin(phase);\n"
            "phase += 2 * $pi * 440 / srate;\n"
            "phase > 2 * $pi ? phase -= 2 * $pi;\n")

host = CarlaHostDLL(os.path.join(libdir, "libcarla_standalone2.dll"), False)
host.set_engine_option(ENGINE_OPTION_PROCESS_MODE, ENGINE_PROCESS_MODE_CONTINUOUS_RACK, "")
host.set_engine_option(ENGINE_OPTION_PATH_BINARIES, 0, libdir)
host.set_engine_option(ENGINE_OPTION_PATH_RESOURCES, 0, os.path.join(share, "resources"))
host.set_engine_option(ENGINE_OPTION_PLUGIN_PATH, PLUGIN_LV2, lv2dir)
check(host.engine_init("Dummy", "carla-test"), "engine starts on the Dummy driver")

added = [
    ("internal audiogain",
     (BINARY_NATIVE, PLUGIN_INTERNAL, "", "", "audiogain", 0, None, 0)),
    ("JSFX tone",
     (BINARY_NATIVE, PLUGIN_JSFX, tone, "", "", 0, None, 0)),
    ("LV2 bigmeter",
     (BINARY_NATIVE, PLUGIN_LV2, "", "", "http://kxstudio.sf.net/carla/plugins/bigmeter", 0, None, 0)),
    ("LV2 Carla-Rack",
     (BINARY_NATIVE, PLUGIN_LV2, "", "", "http://kxstudio.sf.net/carla/plugins/carlarack", 0, None, 0)),
    ("VST2 Carla-Rack",
     (BINARY_NATIVE, PLUGIN_VST2, os.path.join(prefix, "lib", "vst", "carla.vst", "CarlaRack.dll"),
      "", "", 0, None, 0)),
]
for what, args in added:
    loaded = host.add_plugin(*args)
    check(loaded, f"loads {what}" + ("" if loaded else f": {host.get_last_error()}"))
check(host.get_current_plugin_count() == len(added), "all plugins are in the rack")

tone_id = 1
peak = 0.0
deadline = time.monotonic() + 10
while time.monotonic() < deadline and peak < 0.45:
    host.engine_idle()
    time.sleep(0.05)
    peak = max(peak, host.get_output_peak_value(tone_id, True))
check(0.45 <= peak <= 0.55, f"JSFX tone peaks at {peak:.3f}")

check(host.engine_close(), "engine closes")
