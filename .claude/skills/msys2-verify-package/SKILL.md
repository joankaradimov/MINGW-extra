---
name: msys2-verify-package
description: Post-build quality checks for an MSYS2 / MinGW-w64 package — DLL and import-library placement, absolute-path leakage into .pc and CMake config files, runtime dependency and CRT linkage checks with ntldd/objdump, license paths, and smoke tests. Use after a package builds, before committing it or adding another environment to mingw_arch.
---

# Verifying a built package

A build that succeeds is not a package that works. Run these before committing, and again
after each new rung of the environment ladder.

## 1 — Inspect without installing

```bash
pacman -Qlp mingw-w64-ucrt-x86_64-<name>-<ver>-<rel>-any.pkg.tar.zst   # file list
pacman -Qip mingw-w64-ucrt-x86_64-<name>-<ver>-<rel>-any.pkg.tar.zst   # metadata
```

Read the whole file list. Most defects are visible here.

## 2 — Layout

Correct Windows layout under `${MINGW_PREFIX}`:

| Artefact | Location |
|---|---|
| runtime DLL (`libfoo-1.dll`, `foo.dll`) | `bin/` |
| import library (`libfoo.dll.a`) | `lib/` |
| static library (`libfoo.a`) | `lib/` |
| executables (`.exe`) | `bin/` |
| headers | `include/` |
| pkg-config | `lib/pkgconfig/` |
| CMake config | `lib/cmake/<name>/` |
| license | `share/licenses/<realname>/` |

```bash
# a DLL under lib/ is a bug
pacman -Qlp <pkg>.pkg.tar.zst | grep -E '/lib/.*\.dll$'
# an .exe outside bin/ is usually a bug
pacman -Qlp <pkg>.pkg.tar.zst | grep -E '\.exe$' | grep -v '/bin/'
```

If a DLL is in the wrong place, **fix the build system with a patch**. Do not `mv` it in
`package()`. A `package()` that moves build output is a patch that was never written, and it
will break the next time upstream changes the install rules.

## 3 — Absolute path leakage

The most common silently-broken package. Generated files must not contain the build machine's
paths or a converted Windows prefix.

```bash
cd <package>
grep -rIn -e "$(pwd)" -e '/pkg/' -e 'C:/msys64' -e 'C:\\\\msys64' pkg/ | head -50
grep -rIn 'C:/' pkg/*/*/lib/pkgconfig/*.pc 2>/dev/null
grep -rIn 'C:/' pkg/*/*/lib/cmake/ 2>/dev/null
```

Expected in a `.pc`: `prefix=/ucrt64`. A `prefix=C:/msys64/ucrt64` means a missing
`MSYS2_ARG_CONV_EXCL` in `build()` — see `msys2-pkgbuild`. A path containing `/pkg/` means
`DESTDIR` leaked into a generated file, which needs a patch.

Also verify pkg-config actually works after install:

```bash
pkg-config --cflags --libs <name>
```

## 4 — Runtime dependencies and CRT linkage

```bash
ntldd -R "${MINGW_PREFIX}/bin/libfoo-1.dll" | less
# or, without installing:
objdump -p pkg/*/ucrt64/bin/libfoo-1.dll | grep 'DLL Name'
```

Check for:

- **Wrong CRT.** A UCRT64 or CLANG64 build must reference `ucrtbase.dll`, never `msvcrt.dll`.
  A MINGW32/MINGW64 build is the reverse. Mixing them is the failure mode MSYS2 warns about:
  the structures differ, so it fails at runtime, not at link time.
- **Cross-environment leakage.** A UCRT64 binary must not pull DLLs from `/mingw64` or
  `/clang64`. This happens when a build finds a library by absolute path or via a stale
  `PKG_CONFIG_PATH`.
- **Undeclared dependencies.** Every non-system DLL it loads should correspond to something in
  `depends`. `pactree -d1 mingw-w64-ucrt-x86_64-<name>` shows what you declared.
- **Over-declared dependencies.** Entries in `depends` that nothing links against belong in
  `optdepends` or nowhere.
- **libstdc++ / libc++.** A CLANG64 build linking `libstdc++-6.dll` means part of the build
  used gcc. Investigate before shipping.

## 5 — License

```bash
pacman -Qlp <pkg>.pkg.tar.zst | grep share/licenses
```

Must be `${MINGW_PREFIX}/share/licenses/<realname>/<file>`, where `<realname>` has no
environment prefix — `/ucrt64/share/licenses/aubio/COPYING`, not `.../mingw-w64-ucrt-x86_64-aubio/`.
See `msys2-licensing`.

## 6 — Smoke test

Actually use it. This is the step people skip and then regret.

Do **not** `pacman -U` it onto the development machine. That pollutes the installation, and it
also defeats the test: a dependency that `depends=()` forgot to declare is already installed
here, so the package runs fine and ships broken. Install into a throwaway root instead, where
the package meets exactly its declared closure and nothing else — see `msys2-test-isolated`.

```bash
.claude/skills/msys2-test-isolated/isolated-test.sh <pkg>.pkg.tar.zst [more pkgs...] -- '<command>'
```

- **Application:** run it against real input and check the output, not just `--version`. On
  Windows a missing DLL surfaces only at load time, and produces a dialog rather than a
  console error.
- **Library:** compile and link a trivial consumer against `$ISOLATED_PREFIX`.
  ```bash
  echo '#include <foo.h>
  int main(void){ return 0; }' > /tmp/t.c
  ./.claude/skills/msys2-test-isolated/isolated-test.sh <pkg>.pkg.tar.zst \
    -- 'gcc /tmp/t.c -I$ISOLATED_PREFIX/include -L$ISOLATED_PREFIX/lib -lfoo -o /tmp/t.exe && /tmp/t.exe && echo OK'
  ```
- **Python module:** `python -c "import foo; print(foo.__file__)"`.
- **Reverse dependencies:** if something else in this repo depends on it, rebuild that too —
  and pass both packages to the isolated test together.

## 7 — Repo hygiene

```bash
git status --short          # src/, pkg/ and *.pkg.tar.zst must be ignored, not staged
```

The repo `.gitignore` already covers archives, `*/src/`, `*/pkg/` and `*.log`. If `git status`
shows build output, the `.gitignore` needs extending — do not `git add -f` around it.

## Verification checklist

- [ ] file list read in full; no surprises
- [ ] no `.dll` under `lib/`; no `.exe` outside `bin/`
- [ ] no `C:/msys64`, no `/pkg/`, no build-directory paths in `.pc` or CMake config files
- [ ] `pkg-config --cflags --libs <name>` returns sane values
- [ ] correct CRT (`ucrtbase.dll` for UCRT64/CLANG64) and no cross-environment DLLs
- [ ] `depends` matches actual linkage — nothing missing, nothing spurious
- [ ] license installed at `share/licenses/<realname>/`
- [ ] smoke test passes **in a throwaway root**, not on the development machine
- [ ] `pacman -Q` afterwards confirms nothing was installed into the real MSYS2
- [ ] `mingw_arch` lists only environments verified this way
- [ ] working tree clean apart from the PKGBUILD and patches
