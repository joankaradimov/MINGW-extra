---
name: msys2-patch-author
description: Create, name, apply, refresh and retire patches in MSYS2 / MinGW-w64 packages following upstream MINGW-packages conventions — NNNN-description.patch naming, patch -Np1 in prepare(), git apply for git sources, provenance headers, and refreshing patches on a version bump. Use when adding a patch to a PKGBUILD or when an existing patch stops applying.
---

# Authoring and maintaining patches

Patching is a larger part of MSYS2 packaging than it is on Linux, because upstream projects
routinely have never been built with a GNU toolchain on Windows. Treat patches as long-lived
assets with provenance, not as one-off hacks.

## Naming

`NNNN-short-description.patch`, four-digit, zero-padded, in the package directory next to the
PKGBUILD. Upstream uses a numeric prefix on 2502 of 2988 patch files; the four-digit form
(`0001-`) is the majority and matches `git format-patch` output.

```
0001-add-no-undefined-to-libtool-flags.patch
0002-use-GetNativeSystemInfo-for-getpagesize.patch
0010-clang-fix-libtool-libclang_rt-handling.patch
```

Number by intended application order. Leave gaps (0010, 0020) when a package is likely to grow
more patches. Descriptions are lowercase, hyphenated, and say *what the patch does* — not
`fix.patch`, not `mingw-fix.patch`.

## Provenance header

Every patch gets a header. Six months later this is the only thing that tells you whether the
patch can be dropped.

If the patch came from a real commit, `git format-patch` already gives you `From`/`Date`/
`Subject`; keep them and add the MSYS2-specific lines:

```
From 305a92c010e157a0ece9d652d139768460814183 Mon Sep 17 00:00:00 2001
From: Some One <some.one@example.com>
Date: Sat, 28 Aug 2021 21:01:14 +0530
Subject: [PATCH] CMake: Pretend clang is gcc

Backported from upstream. Needed for CLANG64: the project keys its GNU
code path off CMAKE_COMPILER_IS_GNUCC, which CMake does not set for clang,
so it falls through to an MSVC branch that does not build under mingw-w64.

Upstream: https://github.com/someproject/somepackage/pull/123
Applies-to: all environments
---
```

For a hand-written patch with no upstream commit, use a plain comment block before the diff —
`patch(1)` ignores everything before the first `---`/`+++` pair:

```
Add -no-undefined so libtool will build a DLL.

Windows shared libraries cannot have undefined symbols, so libtool refuses
to produce a DLL without this flag and silently builds only a static lib.

Upstream: not submitted (project is unmaintained)
Applies-to: all environments

--- a/src/Makefile.am
+++ b/src/Makefile.am
```

Always answer three questions in the header: **what** it fixes, **why** it is needed on
MinGW/MSYS2, and **whether it went upstream** (PR link, or an explicit "not submitted" and the
reason). Add `Applies-to:` when the patch is environment-specific (`CLANG64 only`,
`CLANGARM64 only`).

## Producing the diff

**From hand edits in `src/`** — the usual case. Build once so `src/` exists and is patched,
edit files under `src/<name>-<ver>/` until it works (rebuild with `--noextract` to keep your
edits), then diff against a pristine copy:

```bash
cd <package>
cp -r "src/<name>-<pkgver>" /tmp/orig-clean     # or re-extract the tarball
# ... make your edits in src/<name>-<pkgver>/ ...
diff -Naur /tmp/orig-clean "src/<name>-<pkgver>" > 0001-my-fix.patch
```

**Cleaner alternative** — turn the extracted source into a throwaway git repo:

```bash
cd "src/<name>-<pkgver>"
git init -q && git add -A && git commit -qm base
# ... edit ...
git diff > ../../0001-my-fix.patch
```

This gives you `git format-patch`-shaped output, per-hunk staging, and easy iteration. Delete
the `.git` directory afterwards, or rely on `--cleanbuild` to wipe `src/`.

**Backporting an upstream commit:**

```bash
git -C /path/to/upstream-clone format-patch -1 <sha> --stdout > 0003-backport-xyz.patch
```
Then add the MSYS2 rationale lines to the header. Keep the original `From`/`Subject` so the
commit is traceable.

## Applying — in `prepare()`

For **tarball sources** use `patch`. This is what upstream does (1329 `patch -Np1`/`-p1`
invocations plus 938 via the helper, against only 27 `git apply`):

```bash
prepare() {
  cd "${_realname}-${pkgver}"

  patch -Np1 -i "${srcdir}/0001-add-no-undefined-to-libtool-flags.patch"
  patch -Np1 -i "${srcdir}/0002-use-GetNativeSystemInfo-for-getpagesize.patch"
}
```

With more than three or four patches, use the upstream helper so failures are attributable:

```bash
prepare() {
  cd "${_realname}-${pkgver}"

  apply_patch_with_msg \
    0001-add-no-undefined-to-libtool-flags.patch \
    0002-use-GetNativeSystemInfo-for-getpagesize.patch \
    0010-clang-fix-libtool-libclang_rt-handling.patch
}
```

defined at the top of the PKGBUILD:

```bash
apply_patch_with_msg() {
  for _patch in "$@"; do
    msg2 "Applying $_patch"
    patch -Np1 -i "${srcdir}/$_patch"
  done
}
```

Used by 403 upstream packages. `-N` makes an already-applied patch a no-op rather than an
interactive prompt, which matters when iterating with `--noextract`.

For **git sources**, use `git apply` instead, and for backports `git cherry-pick --no-commit`.
Do **not** commit inside the checkout: `pkgver()` runs `git describe`, and an extra commit
changes the computed version.

```bash
prepare() {
  cd "${_realname}"
  git apply "${srcdir}/0001-my-fix.patch"
}
```

**After adding or editing any patch file, run `updpkgsums`.** A stale patch checksum surfaces
as a validity-check failure that looks like a download problem.

Finally, prove the patch works from scratch:

```bash
MINGW_ARCH=ucrt64 makepkg-mingw --cleanbuild --syncdeps --force --noconfirm
```

## Environment-specific patches

Prefer a patch that is correct everywhere over one guarded by environment. When a fix genuinely
only applies to one environment, guard it in the *source* with a preprocessor condition
(`#if defined(__clang__)`, `#if defined(__aarch64__)`) rather than conditionally applying the
patch in `prepare()` — a conditionally-applied patch will silently stop applying after an
unrelated version bump and nobody will notice.

If it must be conditional, be explicit:

```bash
if [[ ${MSYSTEM} == CLANG* ]]; then
  patch -Np1 -i "${srcdir}/0010-clang-fix-libtool.patch"
fi
```
and say so in the patch header's `Applies-to:` line.

## Refreshing on a version bump

When `Hunk #N FAILED` appears after bumping `pkgver`:

1. **Ask whether the patch is still needed at all.** Read the upstream changelog and check
   whether the fix was merged. A dropped patch is the best outcome. Test by removing it.
2. If still needed, refresh rather than rewrite:
   ```bash
   cd "src/<name>-<newver>"
   patch -Np1 --merge -i "${srcdir}/0001-my-fix.patch"   # leaves conflict markers
   # resolve, then regenerate the diff as above
   ```
   Or apply with fuzz to see how far off it is: `patch -Np1 -l -F3 --dry-run -i ...`
3. Preserve the original header, and add a line recording the refresh:
   `Refreshed for 1.2.0.`
4. Re-run `updpkgsums`.

## Retiring a patch

On every version bump, try dropping each patch and rebuilding. Patches that survive long after
upstream fixed the problem are how PKGBUILDs rot. When you drop one:

- delete the file, remove it from `source`, remove the `patch` line from `prepare()`
- run `updpkgsums`
- mention it in the commit message: `<name>: Update to 1.2.0, drop merged getpagesize patch`

## Checklist

- [ ] named `NNNN-description.patch`, description says what it does
- [ ] header states what / why-on-MinGW / upstream status
- [ ] listed in `source=()` in application order
- [ ] applied with `patch -Np1 -i "${srcdir}/..."` (or `git apply` for git sources)
- [ ] `updpkgsums` run
- [ ] full `--cleanbuild` succeeds
- [ ] guarded in-source, not in `prepare()`, if environment-specific

## Sources

<https://www.msys2.org/dev/package-guidelines/>; patch naming and application conventions
surveyed across 2988 patch files and 3364 PKGBUILDs in `msys2/MINGW-packages`.
