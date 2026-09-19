---
name: msys2-dependencies
description: Resolve a package's dependencies before and during a build — runtime, build and check dependencies alike — enumerating depends/makedepends/checkdepends, classifying each as installed, available in a repo, or not packaged at all, and recursively packaging the missing ones depth-first, leaves before roots. Covers searching the pacman file databases (pacman -F/-Fl/-Fx) to find which package ships a given header, library or .pc file. Use when starting a new package, when makepkg reports "target not found", when a configure/CMake/meson step fails on a missing header or library, when you need to know which package provides a file, or when a build tool, code generator or other makedepends entry is not packaged.
---

# Dependency resolution and recursive packaging

This covers **every** dependency class, not just runtime ones. A missing `makedepends` entry —
a build system, a code generator, a compiler for a language the project embeds — is exactly as
much a package-it-first job as a missing library, and it blocks the build earlier. `checkdepends`
counts too whenever `check()` actually runs. Treat the four lists as one problem with one
procedure.

A dependency is in exactly one of three states, and each demands a different action:

| State | Test | Action |
|---|---|---|
| **Installed** | `pacman -Qi <pkg>` succeeds | nothing |
| **In a repo, not installed** | `pacman -Si <pkg>` succeeds | nothing — `makepkg --syncdeps` installs it |
| **Not packaged for this environment** | both fail, and no `provides` match | **recurse: package it first** |

Only the third state is work. The point of this skill is to tell the three apart *before* a
build burns twenty minutes and dies at 90%, and to keep the recursion orderly when state three
turns out to be several packages deep.

## Step 1 — get the dependency list

Before there is a PKGBUILD to read, the list comes from, in descending order of reliability:

1. **The upstream MSYS2 or Arch recipe**, if one exists — `msys2-new-package` Phase 0a/0b
   fetches these. Arch's JSON carries `depends` and `makedepends` directly.
2. **An already-packaged version's metadata**, for a dependency-of-a-dependency:
   ```bash
   pacman -Si ${MINGW_PACKAGE_PREFIX}-aubio | sed -n '/^Depends On/,/^Optional/p'
   ```
3. **The build system itself** — the authoritative source, since it is what will actually
   fail:
   ```bash
   grep -rn 'find_package\|pkg_check_modules' CMakeLists.txt cmake/     # CMake
   grep -rn 'dependency(' meson.build                                   # Meson
   grep -rn 'PKG_CHECK_MODULES\|AC_CHECK_LIB' configure.ac              # autotools
   ```
4. **A failed configure run.** Not elegant, but it enumerates what is genuinely required for
   *this* configuration rather than what upstream lists for all of them.

Sort what you find into `depends` (needed at runtime — anything the DLL links against),
`makedepends` (build only: build systems, code generators, header-only libraries),
`checkdepends` (only if `check()` runs them) and `optdepends`. Getting this split wrong is
invisible on your own machine, where everything is installed, and breaks for everyone else.

## Step 2 — classify each one

Work in a **UCRT64** shell, so `${MINGW_PACKAGE_PREFIX}` is set. In a plain MSYS shell it is
empty and every check below silently tests the wrong name — confirm with `echo $MSYSTEM`
first.

```bash
# what is not yet installed (exit 0 = all satisfied, 127 = some missing; prints the missing)
pacman -T ${MINGW_PACKAGE_PREFIX}-fftw ${MINGW_PACKAGE_PREFIX}-libsndfile

# for each of those: does it exist in a repo at all?
for d in fftw libsndfile jack; do
  if pacman -Si "${MINGW_PACKAGE_PREFIX}-$d" >/dev/null 2>&1; then
    echo "OK      $d"
  else
    echo "MISSING $d"
  fi
done
```

`pacman -T` answers *installed?*; `pacman -Si` answers *packaged?*. Confusing the two is the
usual way to end up "packaging" something that was one `pacman -S` away.

### Before believing a MISSING verdict

A name that fails `pacman -Si` is very often packaged under a different one. Always run the
substring search before concluding anything:

```bash
pacman -Ss "${MINGW_PACKAGE_PREFIX}-<partial>"
```

Real example: `pacman -Si ${MINGW_PACKAGE_PREFIX}-jack` fails, because MSYS2 ships the
implementation as `jack2`. An Arch PKGBUILD saying `depends=('jack')` translates to
`${MINGW_PACKAGE_PREFIX}-jack2`, and a naive check would have sent you off building JACK from
source for no reason at all.

Other recurring cases: Arch's soname-only deps (`libavcodec.so=63-64` really means `ffmpeg`),
`lib` prefixes MSYS2 drops or adds, `python-*` vs `python3-*`, and dependencies MSYS2 merges
into a larger package. Search before you build.

Some dependencies are also simply **not needed on Windows** and should be dropped rather than
packaged: `glibc`, `systemd`, `udev`, `alsa-lib`, `libx11`/`wayland` and the rest of the X
stack, and often `dbus`. If an Arch dep exists only to satisfy Linux plumbing, drop it — and
if the build insists on it, disable that feature with a configure flag instead of packaging a
port of it.

### Search by file, not just by name

`pacman -Ss` matches package **names and descriptions**. A build failure almost never gives
you either — it gives you a *file*: `fatal error: CLI/CLI.hpp: No such file`, `cannot find
-lfoo`, `No package 'bar' found` from pkg-config. Guessing which package name might contain
that file is the slow way. Ask directly:

```bash
pacman -Fy                       # ONCE per machine: the file databases are not synced by default
pacman -F CLI.hpp                # which package ships this file?
pacman -Fl <pkg>                 # what does a package ship? — works WITHOUT installing it
pacman -Fx 'bin/libfoo.*\.dll$'  # regex, when you only know the shape of the name
```

This is the strongest form of the MISSING check. `pacman -Si <guessed-name>` failing proves
nothing; `pacman -F <the-file-the-build-wants>` coming back empty is real evidence that
nothing packages it.

`pacman -Fl` deserves particular attention: unlike `pacman -Ql` it does **not** require the
package to be installed, so you can inspect exactly what a candidate dependency provides
before deciding to depend on it — and without polluting the machine
(`msys2-test-isolated`).

Three traps, each of which returns silence rather than an error:

| Trap | Symptom | Fix |
|---|---|---|
| databases never synced | `warning: database file for 'ucrt64' does not exist` | `pacman -Fy` once |
| **partial path** | `pacman -F include/CLI/CLI.hpp` → nothing, though the file exists | use the bare basename (`CLI.hpp`) or the full path from the root (`ucrt64/include/CLI/CLI.hpp`) — a middle fragment matches nothing |
| results span all environments | `pacman -F zlib1.dll` returns 17 hits across ucrt64, clang64, mingw64, clangarm64… | filter: `pacman -F zlib1.dll \| grep '^ucrt64/'` |

The partial-path trap is the dangerous one: an empty result reads exactly like "not
packaged", and that is how a package that already exists gets built a second time.

The same databases answer questions about **convention**, over the whole repository rather
than over whatever happens to be installed locally — which is a biased sample:

```bash
# every DLL any ucrt64 package ships, to settle "does MSYS2 use the lib prefix?"
tar -xOf /var/lib/pacman/sync/ucrt64.files --wildcards '*/files' \
  | grep -E '^ucrt64/bin/.*\.dll$' | sed 's|.*/||'
```

The databases are **zstd**, not gzip: `tar -xOzf` fails *silently* and yields nothing, which
looks like a real answer of zero. Use `tar -xOf` and let tar detect the format. (Answer, for
the record: 3332 of 4106 ucrt64 DLLs carry the `lib` prefix — 81%.)

### Build dependencies have their own trap

Before packaging a missing `makedepends` entry, check whether it is a **base MSYS tool rather
than a MinGW package**. Build tools that run on the host, are not linked into anything, and
have no MinGW variant live unprefixed in the `msys` repo, and belong in `makedepends` without
`${MINGW_PACKAGE_PREFIX}`:

```bash
pacman -Si make patch git pkgconf     # all msys/, all unprefixed
```

So a MISSING verdict on `${MINGW_PACKAGE_PREFIX}-make` means the prefix is wrong, not that
`make` needs packaging. Check both spellings before recursing:

```bash
pacman -Si "${MINGW_PACKAGE_PREFIX}-$d" >/dev/null 2>&1 || pacman -Si "$d" >/dev/null 2>&1
```

The rule of thumb: anything the package *links against or ships* is `${MINGW_PACKAGE_PREFIX}-`
prefixed; a tool that merely runs during `build()` may be either. `cmake`, `ninja`, `meson`
and `pkgconf` all exist in both forms, and the prefixed one is correct for those — it knows
about `${MINGW_PREFIX}` search paths. `make`, `patch` and `git` are msys-only.

Some MSYS2 build tools are also renamed rather than absent — autotools is the usual surprise:
there is no plain `autoconf` package, the MSYS side is split into `autoconf-wrapper` and
versioned `autoconf2.71`/`autoconf2.72`, and MinGW packages should use the
`${MINGW_PACKAGE_PREFIX}-autotools` meta-package (see `msys2-pkgbuild`).

A genuinely missing build tool — a code generator, a language toolchain the project embeds, a
documentation generator it insists on — is a full packaging job like any other, and it comes
first because the build cannot even start without it.

## Step 3 — recurse, depth-first

Everything still MISSING is its own packaging job, and it must be **finished** — built,
installed, verified — before the parent's build is attempted again.

```
zrythm                                     ← what was asked for
├── libpanel     MISSING  depends          ← package this
│   └── libadwaita   MISSING  depends      ← no: package THIS first
├── libcyaml     MISSING  depends          ← then this
└── gtk-doc      MISSING  makedepends      ← and this: build() dies without it
```

Build and runtime dependencies sit in the same tree and are resolved by the same recursion.
The only difference is when they bite: a missing `makedepends` stops the build in `build()`,
before a single object file is produced, so it is if anything the more urgent branch.

Build order is the reverse of discovery: `libadwaita`, `libpanel`, `libcyaml`, `gtk-doc`, then
`zrythm`. Leaves before roots, always.

For each missing dependency, run the **full** `msys2-new-package` workflow — including the
Phase 0a upstream check, which frequently ends the whole branch by finding the recipe already
exists in `msys2/MINGW-packages`. A dependency is not a second-class package: it gets its own
directory, its own verification, and its own commit.

After each one builds, install it **into the real root** — the parent has to compile and link
against it, and a package sitting in your working tree is invisible to pacman:

```bash
pacman -U mingw-w64-ucrt-x86_64-<dep>-<ver>-<rel>-any.pkg.tar.zst
```

This is the one case where `pacman -U` on the development machine is correct, and it does not
contradict `msys2-test-isolated`. The two are different acts: installing a **dependency** is a
build prerequisite, unavoidable because `makepkg` resolves against the real root; installing
the **package under test** is a verification shortcut, and forbidden, because everything it
forgot to declare is already sitting on this machine. Smoke-test each dependency in a
throwaway root *before* installing it here.

Then re-run Step 2 for the parent. The MISSING list should have shrunk by exactly one.

### Guards on the recursion

**Announce the tree before building it.** As soon as the missing set is more than one package,
or deeper than one level, stop and tell the user the full build order and roughly what it
commits them to. A request to package one thing is not standing authorisation to package nine.
Let them decide whether to continue, drop a feature to cut the branch, or stop.

**Detect cycles.** Keep the chain you are currently descending and refuse to enter a package
already in it. Real build-time cycles exist — a library whose test suite needs a tool that
links that library. The fix is to break the cycle with a build option, not to recurse forever.

**Cut branches with configure flags.** Before packaging a dependency, check whether it is
optional. `-DWITH_FOO=OFF`, `-Dfoo=disabled`, `--without-foo` is often the right call for a
heavy optional dep on the first pass. Record the disabled feature in the PKGBUILD with a
comment saying why, so it can be revisited deliberately.

**Depth is a signal.** A tree more than two or three levels deep usually means the project is
not really ported to Windows yet. Say so rather than grinding through it.

## What not to do

- **Never `--nodeps`.** It converts a clear dependency error into an obscure link or runtime
  error much later.
- **Never vendor a dependency into the parent package** — no bundled copies, no
  `FetchContent`, no building git submodules. Every library gets its own package so it can be
  updated and shared. Meson's `--wrap-mode=nodownload` exists to enforce exactly this; keep
  it.
- **Never put a name in `depends` that you have not confirmed with `pacman -Si`.** An
  unresolvable name makes the package uninstallable for everyone but you.
- **Never leave a locally built dependency uncommitted** while committing the parent. The
  parent is unbuildable without it.

## Commit order

One commit per package, in build order, leaves first:

```
libadwaita: Add a new package
libpanel: Add a new package
libcyaml: Add a new package
zrythm: Add a new package
```

Never squash a dependency chain into a single commit. Each package is independently useful and
independently revertable.

## Verifying the result

`msys2-verify-package` covers the full pass, but two checks are specifically about
dependencies:

```bash
ntldd -R ${MINGW_PREFIX}/bin/<binary>.exe      # everything it actually links against
pacman -Qi ${MINGW_PACKAGE_PREFIX}-<name> | sed -n '/^Depends On/p'
```

Anything in the `ntldd` output that lives under `${MINGW_PREFIX}` and is not covered by
`depends` is a missing runtime dependency — it works on your machine only because you built it
there. That is the single most common defect in a package whose dependencies were resolved by
hand.

## Sources

<https://www.msys2.org/dev/package-guidelines/>, <https://www.msys2.org/dev/new-package/>,
`pacman(8)` (`-T`, `-Si`, `-Ss`, `-Qi`, and the file-database options `-Fy`, `-F`, `-Fl`,
`-Fx`). The pacman exit codes, the `jack` → `jack2` case, the three `pacman -F` traps and the
81% figure above were all confirmed against this machine's package databases.
