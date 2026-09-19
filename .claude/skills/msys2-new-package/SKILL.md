---
name: msys2-new-package
description: End-to-end workflow for adding a new package to the MINGW-extra repo — checking msys2/MINGW-packages for an existing recipe, mining Arch Linux and the AUR for prior art, recursively packaging missing dependencies, directory setup, PKGBUILD authoring, the UCRT64-first build loop, then climbing the environment ladder. Use when asked to package a new project for MSYS2 or to add a package to this repo.
---

# Adding a new package

## Phase 0 — feasibility, before writing anything

Answer these first. Half of failed packaging attempts die on question 2 or 4.

1. **Does upstream support Windows and non-MSVC compilers?** A project that only ever builds
   with MSVC is a porting project, not a packaging job. Say so before starting.
2. **Is it already packaged?** Run the upstream check in Phase 0a. This is not optional and
   it is not a formality — it is the single most common reason a packaging session was wasted
   effort. Also check this repo and `pacman -Ss <name>`.
3. **Do all dependencies exist?** Every entry you would put in `depends` and `makedepends`
   must already be available as `${MINGW_PACKAGE_PREFIX}-*`. Enumerate and classify them with
   `msys2-dependencies`; each one still missing is a package that has to be built first,
   depth-first, leaves before roots. Do this before Phase 1, not when the build fails.
4. **Is there prior art?** Phase 0b. A recipe someone else already debugged is worth more
   than anything you will write from a blank file.
5. **Does it build by hand?** In a UCRT64 shell, configure and build it manually once. If you
   cannot, the PKGBUILD will not help you.

## Phase 0a — does msys2/MINGW-packages already have it?

Run **both** checks. They fail in different directions: the search API only knows packages
that have been *built and published*, so it misses a freshly merged recipe; the raw-file
check only knows the `mingw-w64-<upstream-name>` naming, so it misses recipes whose directory
name differs (`mingw-w64-python-foo`, `mingw-w64-qt6-foo`, a `pkgbase` unrelated to the
project name).

```bash
_n=aubio                                   # bare upstream name

# 1. built-and-published check — also finds near-miss names
curl -s "https://packages.msys2.org/api/search?query=$_n"

# 2. recipe-in-git check
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://raw.githubusercontent.com/msys2/MINGW-packages/master/mingw-w64-$_n/PKGBUILD"
```

Reading the results:

| Signal | Meaning |
|---|---|
| `results.exact` is non-null | It exists upstream. **Stop and warn.** |
| `results.exact` null, `results.other` non-empty | Possible different naming — read the entries before concluding anything. |
| HTTP `200` from check 2 | The recipe is in git. **Stop and warn.** |
| HTTP `404` and empty search results | Genuinely absent. Continue to Phase 0b. |

**If it exists, say so before writing a single line of PKGBUILD.** Report the upstream
version, the environments it is built for, and the `source_url` from the search JSON. Then ask
the user whether to continue. Do not decide for them and do not quietly proceed.

There are legitimate reasons to package something that exists upstream — a newer version, a
patch upstream will not take, a build option they disable, an environment they do not ship.
Each of those is a reason the *user* gives, and it belongs in the commit message. "I did not
check" is not one of them. Eight of the twelve packages currently in this repo also exist
upstream; that is the situation this check is meant to stop growing.

If the answer is to use the upstream package instead, the whole job is:

```bash
pacman -S ${MINGW_PACKAGE_PREFIX}-<name>
```

## Phase 0b — prior art, in descending order of usefulness

**1. Other packages in this repo** using the same build system. Same conventions, already
verified on this machine.

**2. Arch Linux** — the primary reference for a package with no MSYS2 recipe. Arch PKGBUILDs
use the same syntax and language, are reviewed, and carry an accurate dependency set and SPDX
license.

```bash
# metadata: repo, pkgbase, pkgver, url, licenses, depends, makedepends
curl -s "https://archlinux.org/packages/search/json/?name=$_n"

# the PKGBUILD itself — use pkgbase from the JSON, which may differ from pkgname
curl -s "https://gitlab.archlinux.org/archlinux/packaging/packages/$_n/-/raw/main/PKGBUILD"
```

If `results` is empty, try `?q=$_n` instead of `?name=$_n` for a substring search — Arch
often names a library after its soname or with a `lib` prefix the project itself does not use.

**3. The AUR** — the backup, when Arch proper does not carry it.

```bash
curl -s "https://aur.archlinux.org/rpc/v5/info?arg[]=$_n"        # exact name
curl -s "https://aur.archlinux.org/rpc/v5/search/$_n"            # fuzzy, if info is empty
curl -s "https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=<PackageBase>"
```

AUR PKGBUILDs are unreviewed and frequently stale. Treat one as a hint about where the source
tarball lives and which flags the build wants — never as an authority. Verify the source URL
and recompute checksums yourself with `updpkgsums`; never copy a checksum from the AUR.

### What to take from an Arch or AUR PKGBUILD, and what to leave

| Take | Leave behind |
|---|---|
| Upstream source URL and tarball layout | `arch=('x86_64')` — this repo uses `arch=('any')` plus `mingw_arch` |
| `pkgver`, `pkgdesc`, `url` | Bare dependency names — every one needs `${MINGW_PACKAGE_PREFIX}-` |
| `license` (Arch is on SPDX too) | `--prefix=/usr`, `/etc`, `/usr/lib` — use `${MINGW_PREFIX}` |
| The dependency *set*, after name translation | `.so` versioning, `provides=('libfoo.so=5-64')` |
| Configure/CMake/meson options and their rationale | systemd, udev, desktop-file, hicolor postinstall |
| Patches for genuinely portable bugs | `-fPIC`, `-pie`, `--as-needed`, RPATH work — meaningless or harmful on Windows |
| `check()` structure, if the suite is portable | Anything hardcoding `gcc` — CLANG64 needs `cc` |

Dependency name translation is manual and every entry must be confirmed with
`pacman -Ss <name>` before it goes in the PKGBUILD:

| Arch | MSYS2 |
|---|---|
| `glibc` | drop entirely |
| `gcc-libs` | `${MINGW_PACKAGE_PREFIX}-cc-libs` |
| `gcc`, `clang` in `makedepends` | `${MINGW_PACKAGE_PREFIX}-cc` |
| `jack` | `${MINGW_PACKAGE_PREFIX}-jack2` |
| `fftw`, `libsndfile`, … | `${MINGW_PACKAGE_PREFIX}-fftw`, `-libsndfile`, … |
| `cmake`, `ninja`, `meson`, `pkgconf` | `${MINGW_PACKAGE_PREFIX}-` prefixed, in `makedepends` |

Never copy an Arch PKGBUILD's *structure*. Start from the matching template in
`msys2-pkgbuild` and move the Arch content into it — otherwise the environment indirection,
`mingw_arch`, and the split-package wrapper all go missing at once.

## Phase 0c — dependencies, and the packages hiding behind them

Do not skip to Phase 1 with an unresolved dependency list. Work through `msys2-dependencies`:
enumerate `depends`, `makedepends` and `checkdepends`, then classify each one as installed,
available in a repo, or not packaged at all.

Build dependencies are not a lesser case. A missing build tool or code generator is as much a
packaging job as a missing library, and it stops the build earlier — in `build()`, before any
object file exists. Check the unprefixed `msys` name too before concluding one is missing:
`make`, `patch` and `git` are msys-only packages and need no `${MINGW_PACKAGE_PREFIX}-`.

Confirm every MISSING verdict with `pacman -Ss` before believing it — MSYS2 frequently uses a
different name than Arch does.

Anything genuinely missing is its own packaging job, and it re-enters this workflow at Phase 0
before the current package continues. Build order is leaves before roots.

If the missing set turns out to be more than one package, or more than one level deep, stop
and show the user the full build order before starting it. Packaging one library can quietly
become packaging six, and that is their decision to make.

## Phase 1 — set up

```bash
cd /path/to/MINGW-extra
mkdir <upstream-name>          # bare upstream name, e.g. aubio — NOT mingw-w64-aubio
cd <upstream-name>
```

Start from the matching template in `msys2-pkgbuild` (CMake, Meson, autotools, Python, waf,
git). Do not start from an Arch PKGBUILD — you will forget the environment indirection.

Fill in the header. Set `mingw_arch=('ucrt64')` and nothing else. Set `license` per
`msys2-licensing`.

```bash
updpkgsums          # rewrites sha256sums from the actual downloaded sources
```

`updpkgsums` covers local patch files too. `SKIP` belongs only to VCS sources.

## Phase 2 — the UCRT64 loop

From a **UCRT64** shell:

```bash
MINGW_ARCH=ucrt64 makepkg-mingw --cleanbuild --syncdeps --force --noconfirm
```

Iterate here until it builds. When it fails, do not guess. `error: target not found` or a
configure step failing on a missing library is a dependency problem — go back to
`msys2-dependencies`. Anything else: read `msys2-patch-diagnose` to classify the failure, then
`msys2-patch-author` to write the fix. Details of the build loop,
including how to iterate without re-downloading and re-extracting each time, are in
`msys2-makepkg`.

Resist two temptations:
- Adding `|| true`, `-Wno-error` blanket flags, or `--disable-<thing>` to make an error go
  away without understanding it.
- Fixing installed files in `package()`. If the build installs a DLL to `lib/`, patch the
  build system. See `msys2-verify-package`.

## Phase 3 — confirm before extending

Actually exercise it — but **not** by installing it here. `pacman -U` onto the development
machine both pollutes the installation and defeats the test: a dependency missing from
`depends()` is already installed on this machine, so the package runs fine and ships broken.
Use a throwaway root, where it meets exactly its declared closure and nothing else
(`msys2-test-isolated`):

```bash
.claude/skills/msys2-test-isolated/isolated-test.sh \
  mingw-w64-ucrt-x86_64-<name>-<ver>-<rel>-any.pkg.tar.zst -- '<command>'
```

Then run the checks in `msys2-verify-package`: DLL placement, `.pc` sanity, dependency
linkage, license path. For a library, compile a trivial consumer against it. For an
application, launch it.

**Commit this.** One package, one commit, message `<name>: Add a new package` — matching the
existing history in this repo. A verified single-environment package in git is worth more than
four unverified ones in your working tree.

## Phase 4 — climb the ladder

One rung at a time: `clang64`, then `mingw32`, then `clangarm64`. For each:

```bash
MINGW_ARCH=clang64 makepkg-mingw --cleanbuild --syncdeps --force --noconfirm
```

If it builds and verifies, add that environment to `mingw_arch` and commit separately
(`<name>: Enable clang64`). If it fails, `msys2-environments` lists the failure modes specific
to each rung — the rung tells you which axis to suspect.

Never add an environment to `mingw_arch` you have not built. `mingw_arch` is a record of what
works, not a wish list. In particular `clangarm64` cannot be built on x86_64 hardware at all;
leave it out unless you have an ARM64 Windows machine or CI.

## Phase 5 — record what you learned

If the package needed patches, make sure each one carries a provenance header explaining what
it fixes and whether it has been sent upstream (`msys2-patch-author`). Six months from now,
during a version bump, that header is the only thing standing between you and a guess.

## Checklist before committing

- [ ] `msys2/MINGW-packages` checked (Phase 0a); if the package exists there, the reason for
      keeping a local copy is stated in the commit message
- [ ] `arch=('any')`, `mingw_arch` lists only verified environments
- [ ] `pkgbase` set, `pkgdesc` ends with `(mingw-w64)`
- [ ] `makedepends` uses `-cc`, not `-gcc`; `depends` uses `-cc-libs`, not `-gcc-libs`
- [ ] `license` uses `spdx:` and the license file is installed to
      `${MINGW_PREFIX}/share/licenses/${_realname}/`
- [ ] checksums real (`SKIP` only for VCS sources)
- [ ] no `mv`/`rm`/`rename` fixups in `package()`
- [ ] patches numbered `NNNN-description.patch` with provenance headers
- [ ] split packages use the wrapper loop, not hardcoded `package_mingw-w64-*` names
- [ ] every `depends`/`makedepends` entry resolves with `pacman -Si`; any dependency packaged
      for this one is committed too
- [ ] built, installed, and smoke-tested in at least UCRT64

## Sources

<https://www.msys2.org/dev/new-package/>, <https://www.msys2.org/dev/package-guidelines/>.

Prior-art lookups: <https://packages.msys2.org/>,
<https://github.com/msys2/MINGW-packages>, <https://archlinux.org/packages/>,
<https://gitlab.archlinux.org/archlinux/packaging/packages/>,
<https://aur.archlinux.org/>. All endpoints used above were confirmed working with plain
`curl` — no `jq`, `gh` or authentication required.
