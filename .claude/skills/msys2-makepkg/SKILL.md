---
name: msys2-makepkg
description: Running makepkg-mingw — flags, the srcdir/pkgdir layout, fast edit-rebuild iteration, MINGW_ARCH handling, and common makepkg errors and their meanings. Use when building a PKGBUILD, iterating on a failing build, or interpreting makepkg output.
---

# Building with makepkg-mingw

`makepkg-mingw` is a thin wrapper: it loops over the environments in `MINGW_ARCH`, and for each
one re-invokes plain `makepkg` with `MSYSTEM` set and `--config /etc/makepkg_mingw.conf`. It
does **not** read `mingw_arch` from the PKGBUILD.

## The standard invocation

```bash
MINGW_ARCH=ucrt64 makepkg-mingw --cleanbuild --syncdeps --force --noconfirm
```

| Flag | Short | Effect |
|---|---|---|
| `--cleanbuild` | | remove `src/` before building — start from pristine sources |
| `--syncdeps` | `-s` | install missing dependencies with pacman |
| `--force` | `-f` | overwrite an existing built package |
| `--noconfirm` | | no pacman prompts |
| `--install` | `-i` | install the result when done |
| `--log` | `-L` | write `*.log` files next to the PKGBUILD |
| `--nocheck` | | skip `check()` |
| `--noextract` | `-e` | **do not re-extract** `src/` — the iteration flag, see below |
| `--repackage` | `-R` | re-run only `package()` |

`-sLf` is the common shorthand: syncdeps, log, force.

`MINGW_ARCH` is space-separated for multiple environments (`MINGW_ARCH="ucrt64 clang64"`), but
during development build one at a time. If unset it defaults to the active `MSYSTEM`; if you
are not in a MINGW shell it warns and falls back to `mingw64`. Always set it explicitly.

Valid values: `ls /etc/makepkg_mingw.d/` — the basenames of the `.conf` files there are exactly
what this installation accepts.

## Directory layout during a build

```
<package>/
  PKGBUILD
  0001-something.patch
  src/                          # extracted + patched sources; wiped by --cleanbuild
    <name>-<ver>/               # $srcdir/<name>-<ver>
    build-UCRT64/               # out-of-tree build dir (by convention)
  pkg/                          # staged install tree
    mingw-w64-ucrt-x86_64-<name>/<prefix>/...    # this is $pkgdir
  *.pkg.tar.zst                 # the result
```

Inside the PKGBUILD, `${srcdir}` is `<package>/src` and `${pkgdir}` is the staging root.
`${pkgdir}${MINGW_PREFIX}/bin` is where executables and DLLs belong.

Both `src/` and `pkg/` are gitignored in this repo (`*/src/`, `*/pkg/`).

## Iterating fast

A full `--cleanbuild` re-extracts and re-patches every time. When you are debugging a compile
error deep in a large project, that is wasted minutes.

**Editing sources to find a fix** (before writing a patch):

```bash
# first build normally so src/ exists and is patched
MINGW_ARCH=ucrt64 makepkg-mingw -sLf
# now edit files under src/<name>-<ver>/ directly, then:
MINGW_ARCH=ucrt64 makepkg-mingw -sLf --noextract
```

`--noextract` skips `prepare()` too, so your hand edits survive. Once the build succeeds,
generate the patch from those edits (`msys2-patch-author`), then do one final `--cleanbuild`
run to prove the patch reproduces the fix from scratch.

**Only `package()` changed:** `makepkg-mingw -R` re-runs packaging against the existing build.

**Inspecting the staged tree without building a package:** after a run, `pkg/` is still there.
`find pkg -type f | sort` is the fastest way to check what would be installed.

## Checksums

```bash
updpkgsums          # in the package directory; rewrites sha256sums in place
```

Run it after changing `source`, after bumping `pkgver`, and after editing any local patch file.
A stale patch checksum produces a validity error that looks like a download problem.

## Reading common failures

| Message | Actual meaning |
|---|---|
| `==> ERROR: One or more files did not pass the validity check` | a checksum is stale — usually a patch you edited. Run `updpkgsums`. |
| `error: target not found: mingw-w64-ucrt-x86_64-foo` | the name is wrong, or the dependency is not packaged for this environment. Confirm with `pacman -Ss` before concluding it is missing, then see `msys2-dependencies` — it may need packaging first. |
| `MINGW_ARCH: 'xyz' unknown, possible values: ...` | typo, or that environment is not installed. |
| `MINGW_ARCH not set and not called from a MINGW environment, defaulting to mingw64` | you are in an MSYS shell. Open a UCRT64 shell or set `MINGW_ARCH`. |
| `undefined reference to ...` while linking a shared lib | almost always libtool `-no-undefined`; see `msys2-patch-diagnose`. |
| `configure: error: cannot guess build type` | `config.sub`/`config.guess` too old for this host — classic on CLANGARM64. |
| `Invalid configuration 'aarch64-w64-mingw32'` | same as above. |
| patch `Hunk #N FAILED` | the patch no longer applies to this source version; refresh it (`msys2-patch-author`). |
| `==> ERROR: A failure occurred in package()` | usually an `install`/`mv` in `package()` referencing a file the build did not produce. |

Run with `--log` and read the `*.log` file rather than scrollback; the real error is often
hundreds of lines above the last output line in a parallel build. To rule out parallelism
confusing the output, rebuild with `MAKEFLAGS=-j1`.

## Installing and removing

Reference only. To *smoke-test* a package, do not install it here — use a throwaway root
(`msys2-test-isolated`). `pacman -U` on this machine is right for a dependency the next build
needs, and wrong for the package you are trying to verify.

```bash
pacman -U mingw-w64-ucrt-x86_64-<name>-<ver>-<rel>-any.pkg.tar.zst
pacman -R mingw-w64-ucrt-x86_64-<name>
pacman -Qlp <file>.pkg.tar.zst     # list contents without installing
pacman -Qip <file>.pkg.tar.zst     # show metadata without installing
```

`-Qlp`/`-Qip` are the quickest verification of a built package; see `msys2-verify-package`.

## Sources

`pacman/makepkg-mingw` in `msys2/MSYS2-packages`; <https://www.msys2.org/dev/new-package/>;
<https://www.msys2.org/dev/update-package/>.
