# Diablo map editor (diasurgical/modding-tools): packaging research

Status (2026-09-28): research done, nothing packaged. Paused on the open decisions below.

## What it is

- <https://github.com/diasurgical/modding-tools>, directory `Tiled/`. A project kit for stock
  Tiled, not a fork. Nothing to compile.
  - `diablo.tiled-project`: `automappingRulesFile` rules.txt, `extensionsPath` extensions.
  - `extensions/diablo-dun.js`: map format `dun`, read and write, via `tiled.registerMapFormat`.
  - `tilesets/*.tsx` (9), `rules.txt` + `rules/*.tmx` (7 legacy "regions" rule maps),
    `stamps/<level>/*.stamp` (152 in 7 subdirectories), `example.tmx`, README + `docs/images`.
  - `tilesets/monsters.png` and `objects.png` are committed Blizzard sprites. The level sheets
    (`l1`…`l6`, `town` `_til.png`) are gitignored; each user makes them from their own MPQs.
  - Every reference is relative (`tilesets/`, `../tilesets/`, `../../tilesets/`), so the tree
    must stay together and the PNGs must sit next to the `.tsx` files.
- No tags. HEAD `cb5957b6b06e99654eab68ba2b4ef4641299a2ec` (2025-04-17), 87 commits, 73 by
  Anders Jenbo. No license file, ever.
- Not in MSYS2 (`pacman -Ss`, raw MINGW-packages PKGBUILD checks: 404), not in Arch or the AUR.
- MSYS2 `tiled` is 1.12.2, ucrt64 only (qbs, Qt 6, `installHeaders:true`).

## Verified: MSYS2 Tiled 1.12.2 (UCRT64) under Wine

- `diablo-dun.js` works unchanged.
  - With it in `%LOCALAPPDATA%\Tiled\extensions`,
    `tiled --export-map dun example.tmx out.dun` writes the correct 13,332 bytes.
  - Opening that DUN in the GUI (tilesets open) gives 4 layers: tiles, 3 monsters, 20 objects,
    transparency. Saved as TMX and exported again: byte-identical.
- Opening a DUN fails with "Invalid tile ID" when a referenced tileset PNG is missing, including
  `monsters.png` / `objects.png`.
- `tmxrasterizer` renders `example.tmx` correctly with a shareware-derived `l1_til.png`.

## Tiled 1.12 behaviour (source: src/tiled/scriptmanager.cpp, src/tiledapp/main.cpp)

- Extensions load only from `<AppConfigLocation>/extensions` (Windows:
  `%LOCALAPPDATA%\Tiled\extensions`) and the current project's `extensionsPath`.
- Project extensions stay off until the user clicks "Enable Extensions" (Tiled >= 1.7; setting
  `Scripting/EnabledProjects` under `HKCU\Software\mapeditor.org\Tiled`). The CLI `--project`
  flag (>= 1.11) silently skips an untrusted project's extensions.
- No system-wide or install-relative extensions directory, no environment variable. Portable
  mode (`tiled.ini` next to the exe) would take over all settings: don't.
- Opening a project writes `<name>.tiled-session` beside it; Project Properties -> OK rewrites
  the `.tiled-project`.
- The stamps folder is a per-session setting and is not searched recursively.
- `tiled.alert()` opens a modal box, which blocks unattended runs. `.js` extensions run
  non-strict; don't rename the extension to `.mjs`.
- `tiled.exe` attaches to the parent console: run it with `wine` directly, not from MSYS2 bash,
  to see its output.
- Legacy automapping "regions" rules are still honoured; a rule's tileset must be the same
  `.tsx` file the map uses.
- Needs `tiled>=1.11`.

## Tile sheets

- Extraction: `mpqcli` (this repo) or `smpq`, with the public-domain listfiles in
  diasurgical/devilutionx-mpq-tools `data/` (`diabdat-`, `hellfire-`, `spawn-listfile.txt`).
- Rendering: the Open Source AMI Go tools, `github.com/sanctuary/formats` `cmd/til_dump`,
  `cel_dump` (Unlicense).
  - The GitHub repos are gone, but proxy.golang.org still serves
    `github.com/sanctuary/formats@v0.0.0-20200419174750-c646ccdb5a40`.
  - Surviving AMI scripts: AJenbo/opensource-ami and sergi4ua/opensource-ami (Unlicense). Old
    Windows ports are in modding-tools history: `git show 2c986bb^:windows-x86-scripts/...`.
  - `til_dump -mpqdir <extracted> levels/l1data/l1.til levels/towndata/town.til`, plus
    `-special` for arches, writes per-tile PNGs. Then
    `montage <dir>/*.png -gravity south -geometry 128x+0+0 -tile 16x -background none l1_til.png`
    (`-tile 8x` for l4 and town).
  - Vanilla data only: no L5/L6, no Hellfire town, no Hellfire monsters.
- d1-graphics-tool: GUI only; Sustainable Use License (non-free) since 1.0.0; 0.5.0 and older
  are Unlicense.
- Shareware `spawn.mpq`
  (<https://github.com/diasurgical/devilutionx-assets/releases/latest/download/spawn.mpq>,
  sha256 `64427cd7c1ba904eaa2e0031c16a6b136d0ecef9abc888c5ff8344b459356e38` on 2026-09-28):
  - Cathedral and town tiles; nearly all vanilla objects; monsters 33 of AMI's 108 cells;
    nothing for l2-l6.
  - Generated `l1_til.png` is 2048x2496, exactly what `cathedral_mega.tsx` declares. The town
    comes out 1024x12384 (342 tiles) against the tsx's Hellfire-sized 376 slots (1024x13536).
- The monster and object sheets must match the index tables in `diablo-dun.js`, which the kit
  remapped in 2022-23 (AMI's layout is older). That needs a layout script; not written yet.

## Open decisions

1. License: the user said "public domain". It needs an upstream statement to cite, or upstream
   adding an Unlicense file like their other tools.
2. Don't ship Blizzard-derived PNGs. Generate them on the user's machine, from the shareware or
   the user's own MPQs.
3. A plain data package adds little. Worth it as a setup tool:
   `diablo-tiled [--mpq diabdat.mpq --mpq hellfire.mpq] [workspace]` that copies the kit into a
   writable workspace, generates the sheets, refreshes `diablo-dun.js` in
   `%LOCALAPPDATA%\Tiled\extensions`, then runs `tiled --project`.
4. Packaging the Go tools vs the repo's no-vendoring rule
   (`.claude/skills/msys2-dependencies/SKILL.md`, "Never vendor a dependency").

## Package sketch (untested)

`_realname=diablo-tiled`, `_commit=cb5957b6b06e99654eab68ba2b4ef4641299a2ec`,
`pkgver=r87.gcb5957b`, `arch=('any')`, `mingw_arch=('ucrt64')`,
`depends=("${MINGW_PACKAGE_PREFIX}-tiled>=1.11")`,
`source=("modding-tools::git+https://github.com/diasurgical/modding-tools.git#commit=${_commit}")`.
Install the `Tiled/` tree, without the PNGs, to `${MINGW_PREFIX}/share/diablo-tiled/`.

## Upstream nits

- The README says `L5_til.png` / `L6_til.png`; the tsx files use lowercase.
- `monsters.tsx` declares 1920x1760; the PNG is 1920x1920.
- The README's Project Properties step has been unnecessary since Tiled 1.5, and following it
  rewrites the project file.

## Cloud environment notes

- MSYS2 under Wine works with `ghcr.io/msys2/msys2-docker-experimental` (Wine 11.15 plus the
  msys2-hacks patches). It needs `pkg-containers.githubusercontent.com` and `repo.msys2.org`
  allowed. Ubuntu's stock Wine 9.0 hangs as soon as MSYS2 forks.
- In the container: `xvfb-run -a wine …`. A `pacman` install unpacks about 36 files a second.
