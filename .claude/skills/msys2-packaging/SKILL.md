---
name: msys2-packaging
description: Router for MSYS2 / MinGW-w64 packaging in the MINGW-extra repo. Use when creating, building, patching, licensing, or verifying a PKGBUILD for MSYS2 (UCRT64, CLANG64, MINGW32, CLANGARM64), when a makepkg-mingw build fails, or when deciding which environments a package should support, when checking whether a package already exists in msys2/MINGW-packages, or when a dependency is missing and needs packaging first. Dispatches to the specialised msys2-* skills.
---

# MSYS2 packaging — router

This repo (`MINGW-extra`) is a personal MSYS2 package repository. One directory per
package, named after the **upstream project** (`aubio/`, `jack2/`, `lv2/`), each holding a
`PKGBUILD` and any `*.patch` files. Note this differs from upstream `msys2/MINGW-packages`,
which uses `mingw-w64-<name>/` — when copying a recipe from upstream, rename the directory.

## The four laws of this repo

**1. Check upstream first.** Before writing anything, confirm that `msys2/MINGW-packages` does
not already carry the package (`msys2-new-package`, Phase 0a). If it does, warn the user and let
them decide — do not quietly duplicate a recipe that already exists and is already maintained.
When no upstream recipe exists, Arch Linux is the reference to mine, with the AUR as backup.

**2. Leaves before roots.** A package whose dependencies are not all resolvable is not ready to
build — runtime and build dependencies alike. Enumerate and classify them first
(`msys2-dependencies`); every one still missing re-enters the
new-package workflow on its own, and is built, verified and committed before the package that
needs it. Confirm a MISSING verdict with `pacman -Ss` first — MSYS2 often uses a
different name than Arch (`jack` is `jack2` here).

**3. UCRT64 first.** Never start a package by targeting several environments. Get a clean
UCRT64 build, install it, smoke-test it, commit it. Only then climb the ladder. Building for
four environments at once turns one fixable failure into four entangled ones.

**4. Fix the build system, not the artefacts.** If DLLs land in `lib/` instead of `bin/`,
write a patch. Do not `mv` them in `package()`. A `package()` function that moves, renames or
deletes build output is a patch that was never written, and it will silently rot on the next
version bump.

## The expansion ladder

Climb one rung at a time. Each rung introduces exactly one new failure axis:

| Rung | Environment | New axis introduced |
|---|---|---|
| 0 | **UCRT64** | baseline: gcc, x86_64, UCRT, libstdc++ |
| 1 | **CLANG64** | new compiler + libc++ |
| 2 | **MINGW32** | new architecture (i686) + new CRT (msvcrt) |
| 3 | **CLANGARM64** | new ISA (aarch64); cannot be built natively on x86_64 |

When a rung fails, you know which axis caused it. That is the entire point of the ordering.

## Dispatch

| If the task is… | Read |
|---|---|
| Checking whether a package already exists upstream, or finding an Arch/AUR reference | `msys2-new-package` |
| Resolving dependencies, or packaging a missing one before the package that needs it | `msys2-dependencies` |
| Writing a PKGBUILD from scratch, or the end-to-end new-package workflow | `msys2-new-package` |
| PKGBUILD syntax, variables, split packages, build-system idioms | `msys2-pkgbuild` |
| Choosing environments, `mingw_arch`, prefixes, climbing the ladder | `msys2-environments` |
| Running the build, makepkg-mingw flags, the edit/rebuild loop | `msys2-makepkg` |
| A build failed and you need to identify the cause | `msys2-patch-diagnose` |
| Writing, naming, applying, refreshing or retiring a patch | `msys2-patch-author` |
| Checking a built package before committing | `msys2-verify-package` |
| Smoke-testing a package without installing it into the real MSYS2 | `msys2-test-isolated` |
| The `license=()` field and where license files go | `msys2-licensing` |

## Non-negotiables

- `makepkg-mingw` **ignores `mingw_arch`**. It reads the `MINGW_ARCH` environment variable.
  `mingw_arch` in the PKGBUILD is metadata only. Never tell the user that setting
  `mingw_arch` will change what gets built.
- Never hand-write `package_mingw-w64-i686-foo()` style functions. Use the split-package
  wrapper loop (see `msys2-pkgbuild`). Zero of 3364 upstream PKGBUILDs hardcode them.
- `makedepends` uses `${MINGW_PACKAGE_PREFIX}-cc`, never `-gcc`. Hardcoding gcc guarantees
  CLANG64 fails. Upstream: 2080 packages use `-cc`, 3 use `-gcc`.
- `license=()` uses `spdx:` expressions. Upstream: 3015 of 3361 packages.
- Never begin a new package without the `msys2/MINGW-packages` existence check. Eight of the
  twelve packages currently in this repo also exist upstream — that is what skipping it costs.
- Never `makepkg --nodeps`, and never vendor a dependency into the package that needs it.
  One library, one package.
- Never smoke-test with `pacman -U` on the development machine. It pollutes the installation
  and, worse, hides missing `depends=()` entries behind libraries that are already installed.
  Use a throwaway root (`msys2-test-isolated`).
- Every PKGBUILD sets `arch=('any')` and `mingw_arch=(...)`. All 3364 upstream packages set
  `mingw_arch`.

## Sources

Grounded in <https://www.msys2.org/dev/> (new-package, update-package, package-guidelines,
package-licensing, pkgbuild), <https://www.msys2.org/docs/environments/>, the
`mingw-w64-PKGBUILD-templates` in `msys2/MINGW-packages`, and `pacman/makepkg-mingw` in
`msys2/MSYS2-packages`.
