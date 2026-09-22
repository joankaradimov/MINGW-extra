---
name: msys2-pkgbuild
description: PKGBUILD anatomy and syntax for MSYS2 / MinGW-w64 packages — required variables, MSYS2-only variables and helpers (MINGW_PREFIX, MINGW_CHOST, MSYSTEM, MSYS2_ARG_CONV_EXCL, check_option), split-package wrappers, and per-build-system templates for CMake, Meson, autotools, Python and waf. Use when writing or editing any PKGBUILD in this repo.
---

# MSYS2 PKGBUILD anatomy

An MSYS2 MinGW PKGBUILD is an Arch PKGBUILD plus an environment indirection layer. Everything
that would be an absolute path or a compiler name in Arch becomes a variable here, because the
same file is evaluated once per environment.

## Substitution variables

| Variable | Example value (UCRT64) | Use |
|---|---|---|
| `MSYSTEM` | `UCRT64` | environment name; use for conditionals and build-dir names |
| `MINGW_PREFIX` | `/ucrt64` | install prefix |
| `MINGW_PACKAGE_PREFIX` | `mingw-w64-ucrt-x86_64` | binary package name prefix |
| `MINGW_CHOST` | `x86_64-w64-mingw32` | autotools `--build`/`--host`/`--target` |

Never write `/ucrt64`, `mingw-w64-ucrt-x86_64` or `x86_64-w64-mingw32` literally.

## Header block

```bash
# Maintainer: Joan Karadimov <joan.karadimov@gmail.com>

_realname=somepackage
pkgbase=mingw-w64-${_realname}
pkgname=("${MINGW_PACKAGE_PREFIX}-${_realname}")
pkgver=1.0
pkgrel=1
pkgdesc="Some package (mingw-w64)"
arch=('any')
mingw_arch=('ucrt64')
url='https://www.somepackage.org/'
license=('spdx:MIT')
makedepends=("${MINGW_PACKAGE_PREFIX}-cc")
depends=()
options=()
source=("https://www.somepackage.org/${_realname}-${pkgver}.tar.gz")
sha256sums=('SKIP')
```

Rules:
- `arch=('any')` always. The real architecture comes from the environment, not from `arch`.
- `mingw_arch` starts as `('ucrt64')` and grows only as builds are verified. See
  `msys2-environments`.
- `pkgbase=mingw-w64-${_realname}` even for a single-package PKGBUILD.
- `pkgdesc` conventionally ends with `(mingw-w64)`.
- `_realname` is the upstream name; use it for source paths, the extracted directory, and
  the license install path.

### Dependencies — compiler-agnostic or CLANG64 breaks

```bash
makedepends=("${MINGW_PACKAGE_PREFIX}-cc")          # NOT -gcc
depends=("${MINGW_PACKAGE_PREFIX}-cc-libs")         # NOT -gcc-libs
```

`-cc` and `-cc-libs` are meta-packages resolving to gcc or clang per environment. Upstream
uses `-cc` in 2080 packages and `-gcc` in 3; `-cc-libs` in 816 and `-gcc-libs` in 3.

Build-system makedepends by ecosystem:

```bash
# CMake
makedepends=("${MINGW_PACKAGE_PREFIX}-cmake" "${MINGW_PACKAGE_PREFIX}-ninja" "${MINGW_PACKAGE_PREFIX}-cc")
# Meson
makedepends=("${MINGW_PACKAGE_PREFIX}-meson" "${MINGW_PACKAGE_PREFIX}-ninja" "${MINGW_PACKAGE_PREFIX}-pkg-config" "${MINGW_PACKAGE_PREFIX}-cc")
# autotools
makedepends=("${MINGW_PACKAGE_PREFIX}-autotools" "${MINGW_PACKAGE_PREFIX}-cc")
# Python
makedepends=("${MINGW_PACKAGE_PREFIX}-python-build" "${MINGW_PACKAGE_PREFIX}-python-installer")
```

### Optional MSYS2 metadata

Widely used upstream and worth setting; all are inert at build time.

```bash
msys2_repository_url='https://github.com/someproject/somepackage'   # 2965/3364 upstream
msys2_references=(
  'archlinux: somepackage'
  'anitya: 1234'
)                                                                    # 2378/3364
msys2_changelog_url='https://.../NEWS'
msys2_issue_tracker_url='https://.../issues'
msys2_documentation_url='https://.../docs'
```

`msys2_references` keys: `anitya`, `archlinux`, `aur`, `cygwin`, `cygwin-mingw64`, `gentoo`,
`internal`, `purl`, `cpe`. Mapping syntax is `("key: value" "key2: value2")`.

### `options`

Most used upstream: `!strip` (475), `!emptydirs` (77). Set `!strip` for Python packages and
anything shipping non-ELF/PE payloads that `strip` would corrupt.

## `MSYS2_ARG_CONV_EXCL` — the path-mangling escape hatch

MSYS2 rewrites Unix-looking command-line arguments into Windows paths before handing them to
native `.exe` tools. `--prefix=/ucrt64` silently becomes `--prefix=C:/msys64/ucrt64`, which
gets baked into generated `.pc` files, CMake config files and RPATH-equivalents, destroying
relocatability. Suppress the conversion for the prefix argument:

```bash
MSYS2_ARG_CONV_EXCL="--prefix=" meson setup --prefix="${MINGW_PREFIX}" ...
MSYS2_ARG_CONV_EXCL="-DCMAKE_INSTALL_PREFIX=" cmake -DCMAKE_INSTALL_PREFIX="${MINGW_PREFIX}" ...
```

`/ucrt64` is valid as both a Unix path and (via the MSYS2 root) a Windows one, so leaving it
unconverted is what you want. 2315 of 3364 upstream PKGBUILDs use this. If a generated `.pc`
or `*Config.cmake` contains `C:/msys64/...`, a missing `MSYS2_ARG_CONV_EXCL` is the first
suspect.

## `check_option` — debug/release

```bash
build() {
  declare -a extra_config
  if check_option "debug" "n"; then
    extra_config+=("-DCMAKE_BUILD_TYPE=Release")
  else
    extra_config+=("-DCMAKE_BUILD_TYPE=Debug")
  fi
  ...
}
```

## Out-of-tree builds keyed by environment

Always build into `build-${MSYSTEM}`. It keeps rungs of the ladder from colliding in a shared
`src/` when you build several environments in one `makepkg-mingw` invocation.

## Split packages — use the wrapper loop

Do **not** hand-write `package_mingw-w64-i686-foo()` / `package_mingw-w64-x86_64-foo()`. Those
hardcode two environments and make the package unbuildable everywhere else. Zero of 3364
upstream PKGBUILDs do it. Define environment-neutral `package_<name>()` functions and generate
the real ones:

```bash
pkgbase=mingw-w64-${_realname}
pkgname=("${MINGW_PACKAGE_PREFIX}-${_realname}"
         "${MINGW_PACKAGE_PREFIX}-${_realname}-cli")

package_somepackage() {
  ...
}

package_somepackage-cli() {
  ...
}

# generate wrappers
for _name in "${pkgname[@]}"; do
  _short="package_${_name#${MINGW_PACKAGE_PREFIX}-}"
  _func="$(declare -f "${_short}")"
  eval "${_func/#${_short}/package_${_name}}"
done
```

This loop is `mingw-w64-splitpkg-wrappers-1.0.template` from upstream, used by 235 packages.
Place it at the end of the PKGBUILD, after all `package_*` definitions.

Also: avoid splitting unless justified. MSYS2 guidance is that splits add maintenance cost and
are warranted only for large optional dependencies, large packages where most users need a
subset, or dev files unneeded at runtime.

## Build-system skeletons

### CMake
```bash
build() {
  declare -a extra_config
  if check_option "debug" "n"; then
    extra_config+=("-DCMAKE_BUILD_TYPE=Release")
  else
    extra_config+=("-DCMAKE_BUILD_TYPE=Debug")
  fi

  MSYS2_ARG_CONV_EXCL="-DCMAKE_INSTALL_PREFIX=" \
    cmake \
      -GNinja \
      -DCMAKE_INSTALL_PREFIX="${MINGW_PREFIX}" \
      "${extra_config[@]}" \
      -DBUILD_{SHARED,STATIC}_LIBS=ON \
      -S "${_realname}-${pkgver}" \
      -B "build-${MSYSTEM}"

  cmake --build "build-${MSYSTEM}"
}

check() { cmake --build "build-${MSYSTEM}" --target test; }

package() {
  DESTDIR="${pkgdir}" cmake --install "build-${MSYSTEM}"
  install -Dm644 "${_realname}-${pkgver}/LICENSE" \
    "${pkgdir}${MINGW_PREFIX}/share/licenses/${_realname}/LICENSE"
}
```

### Meson
```bash
build() {
  MSYS2_ARG_CONV_EXCL="--prefix=" \
    meson setup \
      --prefix="${MINGW_PREFIX}" \
      --wrap-mode=nodownload \
      --auto-features=enabled \
      --buildtype=plain \
      "build-${MSYSTEM}" \
      "${_realname}-${pkgver}"

  meson compile -C "build-${MSYSTEM}"
}

check() { meson test -C "build-${MSYSTEM}"; }

package() {
  meson install -C "build-${MSYSTEM}" --destdir "${pkgdir}"
  install -Dm644 "${_realname}-${pkgver}/COPYING" \
    "${pkgdir}${MINGW_PREFIX}/share/licenses/${_realname}/COPYING"
}
```

`--wrap-mode=nodownload` is mandatory: the build must not fetch dependencies. If it fails
without it, the missing dependency needs to be packaged first.

### autotools
```bash
build() {
  mkdir -p "build-${MSYSTEM}" && cd "build-${MSYSTEM}"

  ../"${_realname}-${pkgver}"/configure \
    --prefix="${MINGW_PREFIX}" \
    --build="${MINGW_CHOST}" \
    --host="${MINGW_CHOST}" \
    --target="${MINGW_CHOST}" \
    --enable-static \
    --enable-shared

  make
}

check() { cd "build-${MSYSTEM}"; make check; }

package() {
  cd "build-${MSYSTEM}"
  make install DESTDIR="${pkgdir}"
  install -Dm644 "../${_realname}-${pkgver}/LICENSE" \
    "${pkgdir}${MINGW_PREFIX}/share/licenses/${_realname}/LICENSE"
}
```

### Python
```bash
options=('!strip')

build() {
  cp -r "${_realname}-${pkgver}" "python-build-${MSYSTEM}" && cd "python-build-${MSYSTEM}"
  python -m build --wheel --skip-dependency-check --no-isolation
}

package() {
  cd "python-build-${MSYSTEM}"
  MSYS2_ARG_CONV_EXCL="--prefix=" \
    python -m installer --prefix="${MINGW_PREFIX}" --destdir="${pkgdir}" dist/*.whl
  install -Dm644 LICENSE \
    "${pkgdir}${MINGW_PREFIX}/share/licenses/python-${_realname}/LICENSE"
}
```

MSYS2 guidance: ship `.pyc` and `.opt-1.pyc` for every `.py`, compiled with Unix-style paths
(`/ucrt64/lib/python3.x/site-packages/foo.py`) so they stay relocatable. Use `python -m
compileall` when the build does not produce them.

### Node.js applications
No short skeleton fits: `npm ci` against upstream's lockfile, node-gyp for native addons, a
staged install tree and `cmd-shim` launchers. See `msys2-nodejs`, and `claude-code-router/`
for a complete PKGBUILD.

### waf (used by several packages in this repo)
waf has no MSYS2 template upstream. The working pattern:

```bash
build() {
  cd "${srcdir}/${_realname}-${pkgver}"
  /usr/bin/python ./waf configure --prefix="${MINGW_PREFIX}"
  /usr/bin/python ./waf build -v
}

package() {
  cd "${srcdir}/${_realname}-${pkgver}"
  /usr/bin/python ./waf --destdir="${pkgdir}" install
}
```

Note `/usr/bin/python` — the MSYS (not MinGW) Python. waf builds in-tree, so `build-${MSYSTEM}`
separation is unavailable; build one environment at a time, or `--cleanbuild`.

### Git sources
```bash
_commit='ff9ee68d7e31784c6fea3c864a235ad1f32ff026'
source=("${_realname}"::"git+https://github.com/someproject/somepackage.git#commit=${_commit}")
sha256sums=('SKIP')

pkgver() {
  cd "${_realname}"
  git describe --long "${_commit}" | sed 's/\([^-]*-g\)/r\1/;s/-/./g;s/^v//g'
}
```

`SKIP` is legitimate **only** for VCS sources. Never `SKIP` a tarball or a local patch file.

## Sources

`mingw-w64-PKGBUILD-templates` in `msys2/MINGW-packages`;
<https://www.msys2.org/dev/pkgbuild/>; <https://www.msys2.org/dev/package-guidelines/>.
