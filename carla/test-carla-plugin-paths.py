#!/usr/bin/env python3
# The frontend's default plugin folders include the prefix's own
# lib/{ladspa,dssi,lv2,vst,vst3}, both for carla_shared.py in share/carla and
# for its copy in share/carla/resources, which the plugin UIs import.
#
# Usage: test-carla-plugin-paths.py <prefix>

import os
import subprocess
import sys

prefix = sys.argv[1]
folders = {"LADSPA": "ladspa", "DSSI": "dssi", "LV2": "lv2", "VST2": "vst", "VST3": "vst3"}

def norm(path):
    return os.path.abspath(path).replace("\\", "/").rstrip("/").lower()

# The *_PATH variables replace the defaults when they are set.
env = {k: v for k, v in os.environ.items() if not k.endswith("_PATH")}
code = ("import carla_shared as c\n"
        "for n in %r:\n"
        "    print(n, '|'.join(getattr(c, 'CARLA_DEFAULT_' + n + '_PATH')))\n" % list(folders))

failed = False
for frontend in ("share/carla", "share/carla/resources"):
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(prefix, frontend),
                         env=env, check=True, capture_output=True, text=True).stdout
    paths = dict(line.split(" ", 1) for line in out.splitlines() if line.split(" ", 1)[0] in folders)

    for name, sub in folders.items():
        entries = paths[name].split("|")
        want = norm(os.path.join(prefix, "lib", sub))
        if want not in [norm(p) for p in entries]:
            print("FAIL %s: %s has no %s" % (frontend, name, want))
            failed = True
        # A missing separator glues two folders into one path.
        for p in entries:
            if p.count(":") > 1:
                print("FAIL %s: %s has a glued entry %s" % (frontend, name, p))
                failed = True

    print("%s: prefix plugin folders found" % frontend)

sys.exit(1 if failed else 0)
