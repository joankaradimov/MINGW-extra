---
name: msys2-environments
description: MSYS2 environment matrix and the UCRT64-first expansion ladder. Use when deciding which environments a package targets, setting mingw_arch or MINGW_ARCH, resolving prefix/package-name questions, or when a package builds in one environment but fails in another (CLANG64, MINGW32, CLANGARM64).
---

# MSYS2 environments and the expansion ladder

## The matrix

| MSYSTEM | Prefix | Toolchain | Arch | CRT | C++ stdlib | `MINGW_PACKAGE_PREFIX` | Status |
|---|---|---|---|---|---|---|---|
| `UCRT64` | `/ucrt64` | gcc | x86_64 | ucrt | libstdc++ | `mingw-w64-ucrt-x86_64` | **recommended default** |
| `CLANG64` | `/clang64` | llvm | x86_64 | ucrt | libc++ | `mingw-w64-clang-x86_64` | active |
| `CLANGARM64` | `/clangarm64` | llvm | aarch64 | ucrt | libc++ | `mingw-w64-clang-aarch64` | active |
| `MINGW64` | `/mingw64` | gcc | x86_64 | msvcrt | libstdc++ | `mingw-w64-x86_64` | **deprecated 2026-03-15** |
| `MINGW32` | `/mingw32` | gcc | i686 | msvcrt | libstdc++ | `mingw-w64-i686` | phase-out began 2023-12-13 |
| `CLANG32` | — | — | — | — | — | — | **removed 2024-12-18** |
| `MSYS` | `/usr` | gcc | x86_64 | cygwin | libstdc++ | (no prefix) | POSIX layer, not a MinGW target |

Never mix msvcrt and UCRT binaries. Their internal structures and data types differ; a
package built against one and loaded by the other fails in ways that look like memory
corruption rather than a link error.

## `mingw_arch` vs `MINGW_ARCH` — do not confuse these

`mingw_arch=()` inside the PKGBUILD is **metadata**. `makepkg-mingw` never reads it. It exists
for MSYS2's CI (`msys2-autobuild`) and, in this repo, as a record of which environments the
package has actually been verified in.

`MINGW_ARCH` is the **environment variable** that controls what gets built:

```bash
MINGW_ARCH=ucrt64 makepkg-mingw --cleanbuild --syncdeps --force --noconfirm
MINGW_ARCH="ucrt64 clang64" makepkg-mingw -sLf     # space-separated: builds both, in order
```

From `makepkg-mingw` itself:

- `MINGW_ARCH` is a space-separated list of environments to build for.
- If unset, it defaults to the *currently active* `MSYSTEM`.
- If unset and not run from a MINGW shell, it warns and falls back to `mingw64`. Do not rely
  on this; always set it explicitly.
- Valid values are the basenames of `/etc/makepkg_mingw.d/*.conf`. Run
  `ls /etc/makepkg_mingw.d/` to see what this installation actually supports.
- `MINGW_INSTALLS` is the deprecated old name. Do not use it.
- Each environment is built by re-invoking `makepkg` with `MSYSTEM` set and the config
  `/etc/makepkg_mingw.conf`.

So `mingw_arch` and `MINGW_ARCH` must be kept in sync **by hand**. Only add an environment to
`mingw_arch` after a build for it has actually succeeded.

## The ladder

Start at rung 0. Do not skip. Do not batch.

### Rung 0 — UCRT64
```bash
mingw_arch=('ucrt64')
```
Baseline. Everything else is measured against this. Get it building, installing and
smoke-testing cleanly, and commit that before touching anything else.

### Rung 1 — CLANG64: new compiler, new C++ standard library
Same arch, same CRT. Anything that breaks here is a *toolchain* problem.

Recurring causes:
- **libc++ vs libstdc++.** Missing transitive includes (libstdc++ pulls in headers libc++
  does not), `std::` symbols that were only reachable via GNU extensions.
- **CMake compiler identity.** Projects test `CMAKE_COMPILER_IS_GNUCC` or
  `CMAKE_CXX_COMPILER_ID STREQUAL "GNU"` and take an MSVC path when it fails. The standard
  fix is to pretend clang is gcc:
  ```cmake
  if("${CMAKE_C_COMPILER_ID}" MATCHES "Clang")
    set(CMAKE_COMPILER_IS_GNUCC 1)
  endif()
  ```
- **libtool does not understand `libclang_rt`.** Its link-command parser drops the compiler
  runtime, producing undefined references. Patch `libtool.m4` to accept `*/libclang_rt.*.a`
  alongside `-L*|-R*|-l*`.
- **Stricter diagnostics.** clang errors on what gcc warns about. Prefer a real fix; where the
  warning is genuinely spurious, scope it narrowly in `build()`:
  ```bash
  if [[ ${MSYSTEM} == CLANG* ]]; then
    CFLAGS+=" -Wno-error=used-but-marked-unused"
  fi
  ```
- **Missing GNU builtins.** e.g. `getpagesize()` is absent; guard with
  `#if defined(__MINGW32__) && defined(__clang__)` and implement via `GetNativeSystemInfo`.
- **`realloc` as a macro** under some clang configurations, breaking `std::realloc`.
- **Fortran and OpenMP** are frequently unavailable or differently linked; gate those features
  off for `CLANG*`.

Use `${MSYSTEM} == CLANG*` when the fix applies to both CLANG64 and CLANGARM64, and
`== CLANG64` when it is genuinely x86-specific.

### Rung 2 — MINGW32: new architecture *and* new CRT
Two axes at once. When it fails, determine which before patching.

msvcrt-side causes:
- **printf/scanf format specifiers.** msvcrt's are not C99. `%lld`, `%zu`, `%a` misbehave.
  Fix by defining `__USE_MINGW_ANSI_STDIO=1` before including `<stdio.h>`, or by adding
  `-D__USE_MINGW_ANSI_STDIO=1` to `CPPFLAGS`.
- **Missing UCRT-only functions** and weaker `<math.h>`/locale support.

i686-side causes:
- **32-bit `size_t`/`long`.** Code assuming `sizeof(long) == 8` or `sizeof(void*) == 8`.
- **No `__int128`.**
- **Stack alignment and calling conventions** in hand-written asm.
- **Address space limits** in the build itself — large C++ translation units can exhaust the
  32-bit linker; this presents as an out-of-memory or "file too big" error, not a code bug.

Reality check before spending time here: MINGW32 has been in phase-out since 2023-12-13, and
only 219 of 3364 upstream packages still list it. Add it only if something downstream actually
needs 32-bit.

### Rung 3 — CLANGARM64: new ISA
**You cannot build this natively on an x86_64 machine.** It needs ARM64 Windows hardware or
CI. If neither is available, stop at rung 2 and leave `clangarm64` out of `mingw_arch` — an
unverified entry is worse than an absent one.

Recurring causes:
- **x86 intrinsics and inline asm.** SSE/MMX/AVX headers, `__builtin_ia32_*`, `_mm_*`,
  `cpuid`, `rdtsc`. Needs either an ARM NEON path or a portable C fallback.
- **`config.sub` / `config.guess` too old** to recognise `aarch64-*-mingw*`. Classic one-line
  patch adding `aarch64-*` to the accepted-CPU case. Alternatively refresh both files.
- **CPU/feature detection** in configure or CMake keyed to x86 (`CMAKE_SYSTEM_PROCESSOR MATCHES
  "^arm"` handling, `-mfpu=`/`-msse` flags that are invalid on aarch64).
- **Image base / large-address assumptions** in linker flags.

## Package name and function naming

The environment determines the binary package name via `${MINGW_PACKAGE_PREFIX}`. You never
write those names out. In particular, for split packages, do **not** define
`package_mingw-w64-i686-foo()` — that hardcodes one environment and is why such a PKGBUILD
cannot build for UCRT64 at all. Use the wrapper loop documented in `msys2-pkgbuild`.

## Sources

<https://www.msys2.org/docs/environments/>, `pacman/makepkg-mingw` in `msys2/MSYS2-packages`,
and conditional idioms surveyed across 3364 PKGBUILDs in `msys2/MINGW-packages`.
