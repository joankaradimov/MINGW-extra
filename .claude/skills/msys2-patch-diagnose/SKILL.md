---
name: msys2-patch-diagnose
description: Classify a failing MSYS2 / MinGW-w64 build into a known failure class before writing a patch — link errors, DLL export problems, missing POSIX APIs, path and prefix mangling, libtool and CMake Windows assumptions, and the compiler/CRT/ISA-specific failures of CLANG64, MINGW32 and CLANGARM64. Use when a makepkg-mingw build fails and the cause is not obvious.
---

# Diagnosing a MinGW build failure

Patching MSYS2 packages is mostly pattern recognition. The same two dozen upstream mistakes
recur across thousands of packages. Identify the class first; the fix follows from it.

## Step 1 — is it actually a code problem?

Rule these out before reading any source:

- **Stale checksum** → `==> ERROR: One or more files did not pass the validity check`. Run
  `updpkgsums`.
- **Missing dependency** → `target not found`. Package the dependency first.
- **Wrong environment** → you are in an MSYS shell, or `MINGW_ARCH` is unset. See
  `msys2-makepkg`.
- **Parallel-build noise** → rebuild with `MAKEFLAGS=-j1` to get a readable error.
- **Network fetch during build** → Meson wraps, CMake `FetchContent`, cargo/pip downloads. The
  build must be offline. Add `--wrap-mode=nodownload`, or package the dependency.

## Step 2 — which axis?

Which rungs of the ladder fail tells you where to look:

| Fails on | Axis | Look at |
|---|---|---|
| UCRT64 (so, everywhere) | Windows/MinGW portability | classes A–E below |
| UCRT64 ok, CLANG64 fails | compiler + libc++ | class F |
| UCRT64 + CLANG64 ok, MINGW32 fails | i686 and/or msvcrt | class G |
| only CLANGARM64 fails | aarch64 ISA | class H |

## Class A — shared library / link failures

**Symptom:** `undefined reference to ...` when linking a `.dll`, or libtool silently producing
a static library only, or no `.dll` in the output at all.

**Cause:** Windows DLLs cannot have undefined symbols at link time; ELF shared objects can.
libtool refuses to build a shared library unless told the library is self-contained.

**Fix:** add `-no-undefined` to the library's `LDFLAGS` in `Makefile.am`/`configure.ac`:
```
libfoo_la_LDFLAGS = -no-undefined -version-info 1:0:0
```
This is the single most common MSYS2 patch class — the upstream repo has a whole family of
patches literally named `*no-undefined*`.

If instead the link fails on genuinely missing Windows libraries, the fix is adding them:
`-lws2_32` (sockets), `-lbcrypt`/`-ladvapi32` (crypto/random), `-lole32 -loleaut32 -luuid`
(COM), `-lshlwapi`, `-lpsapi`, `-lwinmm`, `-liphlpapi`, `-ldbghelp`.

## Class B — symbol visibility and exports

**Symptom:** the DLL builds but consumers get unresolved symbols; or the import library
`.dll.a` is empty/absent.

**Cause:** Windows requires explicit export. GCC/Clang on ELF export everything by default.

**Fix, in order of preference:**
1. Proper `__declspec(dllexport)`/`dllimport` macro plumbing, `#if defined(_WIN32)`.
2. CMake: `set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)` or the `WINDOWS_EXPORT_ALL_SYMBOLS`
   target property.
3. Last resort: `-Wl,--export-all-symbols`. It works, but exports internals and breaks ABI
   discipline; note that in the patch header if you use it.

## Class C — missing POSIX APIs

**Symptom:** `implicit declaration of function 'X'`, `'X' undeclared`, or missing headers.

Common absences and their Windows replacements:

| Missing | Replacement |
|---|---|
| `<dlfcn.h>`, `dlopen`/`dlsym` | `LoadLibraryW`/`GetProcAddress`, or the `dlfcn-win32` package |
| `<sys/mman.h>`, `mmap` | `CreateFileMapping`/`MapViewOfFile` |
| `fork()` | no equivalent; restructure to `CreateProcess`/threads |
| `getpagesize()` | `GetNativeSystemInfo(&si); si.dwPageSize` — absent under clang in particular |
| `<pwd.h>`, `getuid`, `chown`, `symlink` | usually the feature must be `#ifdef`-ed out |
| `<sys/socket.h>`, `<netinet/*>` | `<winsock2.h>`, `<ws2tcpip.h>`, plus `WSAStartup` |
| `realpath` | `_fullpath` or `GetFullPathNameW` |
| `strcasecmp`, `strndup` | present in mingw-w64, but may need `_GNU_SOURCE`-ish guards |

Guard with `#ifdef _WIN32` (or `__MINGW32__` when the fix is mingw-specific), never by
deleting the POSIX branch.

## Class D — path, prefix and filesystem assumptions

**Symptom:** generated `.pc` or `*Config.cmake` containing `C:/msys64/...`; hardcoded `/usr`;
tests failing on path comparison; `\` vs `/`.

**Causes and fixes:**
- **MSYS2 argument conversion.** `--prefix=/ucrt64` was rewritten to a Windows path. Fix in the
  PKGBUILD with `MSYS2_ARG_CONV_EXCL`, not with a patch. See `msys2-pkgbuild`.
- **Drive letters and colons.** Code splitting `PATH`-like strings on `:` breaks on `C:/`.
- **Symlinks.** Build systems that create symlinks (versioned library aliases, docs) fail or
  silently copy. Usually the symlink step must be dropped on Windows.
- **`/` vs `\`.** Prefer fixing comparisons to accept both rather than normalising everywhere.
- **Case-insensitive filesystem.** A build generating both `Foo.h` and `foo.h` collides.

## Class E — install layout

**Symptom:** `.dll` installed into `${MINGW_PREFIX}/lib/`, or a versioned name like
`libfoo.so.1`-style output, or executables without `.exe`.

**Correct Windows layout:** runtime `.dll` in `bin/`, import library `libfoo.dll.a` and static
`libfoo.a` in `lib/`, headers in `include/`, `.pc` in `lib/pkgconfig/`.

**Fix in the build system** — CMake `RUNTIME DESTINATION bin`, autotools `bindir` for DLLs
(libtool does this correctly when `-no-undefined` is set), Meson handles it natively.

**Do not** `mv` DLLs in `package()`. That is a patch that was never written; it hides the real
defect and breaks silently on the next version.

## Class F — CLANG64 (compiler + libc++)

- Missing transitive includes libstdc++ happened to provide (`<cstdint>`, `<cstring>`,
  `<algorithm>` are the usual suspects).
- `CMAKE_COMPILER_IS_GNUCC` unset → project falls into an MSVC branch. Fix:
  ```cmake
  if("${CMAKE_C_COMPILER_ID}" MATCHES "Clang")
    set(CMAKE_COMPILER_IS_GNUCC 1)
  endif()
  ```
- **libtool drops `libclang_rt`** → undefined references to compiler-runtime symbols. Patch
  `libtool.m4`'s link-parser case to accept `*/libclang_rt.*.a` alongside `-L*|-R*|-l*`.
- Stricter diagnostics promoted to errors. Prefer a real fix; otherwise scope
  `-Wno-error=<specific>` in `build()` under `[[ ${MSYSTEM} == CLANG* ]]`.
- `getpagesize()` and other GNU-isms absent.
- `realloc` defined as a macro, breaking `std::realloc`.
- OpenMP and Fortran commonly unavailable — gate the feature off rather than fighting it.

## Class G — MINGW32 (i686 + msvcrt)

**msvcrt side:**
- `%lld`, `%zu`, `%a` and friends misformat. Fix with `-D__USE_MINGW_ANSI_STDIO=1` in
  `CPPFLAGS`, or `#define __USE_MINGW_ANSI_STDIO 1` before `<stdio.h>`.
- UCRT-only functions missing; weaker locale and `<math.h>`.

**i686 side:**
- `sizeof(long) == 4`, `sizeof(void*) == 4`; code assuming 64-bit pointers or `long`.
- No `__int128`.
- Hand-written asm with wrong calling convention or stack alignment.
- The 32-bit linker running out of address space on large C++ builds — presents as an
  allocation failure, not a code error. Reduce parallelism or split translation units.

## Class H — CLANGARM64 (aarch64)

- **x86 intrinsics**: `<emmintrin.h>`/`<xmmintrin.h>`, `_mm_*`, `__builtin_ia32_*`, `cpuid`,
  `rdtsc`. Needs a NEON path or a portable C fallback, selected by `#if defined(__aarch64__)`.
- **`config.sub`/`config.guess` too old** to accept `aarch64-*-mingw*` → `Invalid
  configuration` / `cannot guess build type`. One-line patch adding `aarch64-*` to the CPU
  case, or refresh both files wholesale.
- **x86-only compiler flags** (`-msse2`, `-mfpu=`, `-march=` values) passed unconditionally.
- **CPU feature detection** keyed to x86.
- **Image-base / large-address linker assumptions.**

Remember you cannot reproduce any of this on an x86_64 machine. If you have no ARM64 Windows
host, do not add `clangarm64` to `mingw_arch`.

## Step 3 — before writing the patch

- **Check upstream first.** The fix may already exist in a newer release or an open PR. A
  version bump beats a patch.
- **Check `msys2/MINGW-packages`.** If upstream MSYS2 packages this project, read their patches
  before writing your own.
- **Check Arch/AUR and Cygwin.** Cygwin patches in particular often address the same POSIX gaps.

Then go to `msys2-patch-author`.
