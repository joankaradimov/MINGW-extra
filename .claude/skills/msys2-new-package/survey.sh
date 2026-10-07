#!/usr/bin/env bash
# Survey an unpacked upstream source tree before writing its PKGBUILD.
#
# Usage:
#   survey.sh SOURCE-DIR
#
# SOURCE-DIR is the extracted release tarball (or src/<name>-<ver> after a
# first makepkg run). The report answers what a build will not tell you,
# because the build succeeds anyway:
#
#   bundled    third-party code copied into the tree, and whether MSYS2
#              packages each piece -- every FOUND line is a dependency to
#              take from its package and delete in prepare()
#   submodules git submodules, which a GitHub tarball leaves empty
#   downloads  build steps that fetch code at configure time
#   tests      how upstream's tests are switched on, for check()
#   install    install rules and options, for package()
#   options    every build option and its default
#   license    license files and the declared license
#
# Nothing is built. Run it from any directory; it only reads SOURCE-DIR.

set -uo pipefail

[ $# -eq 1 ] && [ -d "$1" ] || { echo "usage: survey.sh SOURCE-DIR" >&2; exit 2; }
cd "$1" || exit 2
_prefix=${MINGW_PACKAGE_PREFIX:-mingw-w64-ucrt-x86_64}

# Build files, without descending into bundled trees' own tests or docs.
mapfile -t _build_files < <(find . \( -name .git -o -name node_modules \) -prune -o \
  -type f \( -name CMakeLists.txt -o -name '*.cmake' -o -name meson.build \
  -o -name meson_options.txt -o -name meson.options -o -name configure.ac \
  -o -name Makefile.am -o -name setup.py -o -name pyproject.toml \) -print | sort)

grep_build() { [ ${#_build_files[@]} -gt 0 ] && grep -nE "$@" "${_build_files[@]}" 2>/dev/null; }

# Every package name in the sync databases, read once.
_known=$(pacman -Slq 2>/dev/null | grep "^${_prefix}-" | sort -u)

# Look a name up: exact package name, with and without a lib prefix. Prints
# the first hit.
lookup() {
  local n=${1,,} c
  n=${n%%-[0-9]*}; n=${n%%[._]v[0-9]*}
  for c in "$n" "lib$n" "${n#lib}" "${n//_/-}"; do
    if grep -qxF "${_prefix}-$c" <<<"$_known"; then
      echo "${_prefix}-$c"; return 0
    fi
  done
  return 1
}

echo "## bundled third-party code"
_found_any=0
for _d in lib libs third_party thirdparty third-party 3rdparty external externals \
          extern vendor vendored deps dependencies contrib submodules subprojects; do
  for _top in $(find . -maxdepth 3 -type d -name "$_d" -not -path './.git/*' 2>/dev/null); do
    for _sub in "$_top"/*/; do
      [ -d "$_sub" ] || continue
      _name=$(basename "$_sub")
      _found_any=1
      if [ -z "$(ls -A "$_sub")" ]; then
        printf '  %-40s EMPTY (a submodule? see below)\n' "${_sub#./}"
      elif _pkg=$(lookup "$_name"); then
        printf '  %-40s FOUND %s\n' "${_sub#./}" "$_pkg"
      else
        printf '  %-40s not packaged under that name -- check pacman -Ss before deciding\n' "${_sub#./}"
      fi
    done
  done
done
[ "$_found_any" -eq 1 ] || echo "  none found in the usual places"
echo "  -> FOUND: build against the package and delete the copy in prepare() (msys2-dependencies)."
echo "  -> a fork that only this project uses is part of the source; say so in a PKGBUILD comment."

echo
echo "## git submodules"
if [ -f .gitmodules ]; then
  git config -f .gitmodules --get-regexp '^submodule\..*\.(path|url)$' | sed 's/^/  /'
  echo "  -> a GitHub tarball has these directories EMPTY: each needs its own source=() entry"
  echo "     pinned to the commit the release uses, or (better) a package of its own."
else
  echo "  none"
fi

echo
echo "## code downloaded at configure time"
grep_build -i 'FetchContent_Declare|ExternalProject_Add|file\(DOWNLOAD|CPMAddPackage|git clone' | sed 's/^/  /' | head -20 || true
ls subprojects/*.wrap 2>/dev/null | sed 's/^/  meson wrap: /'
echo "  -> each one is a dependency to take from a package (meson: --wrap-mode=nodownload)."

echo
echo "## tests"
grep_build -E 'option\s*\(\s*[A-Za-z0-9_]*TEST[A-Za-z0-9_]*' | sed 's/^/  /' || true
grep_build -E "option\s*\(\s*'[a-z_]*test[a-z_]*'" | sed 's/^/  /' || true
grep_build -E 'enable_testing\(|include\s*\(\s*CTest|add_test\s*\(|^\s*test\s*\(|^TESTS\s*=|check_PROGRAMS' |
  sed 's/^/  /' | head -15 || true
for _t in test tests testing t spec unittest unittests; do
  [ -d "$_t" ] && echo "  directory: $_t/"
done
echo "  -> check() needs these switched on in build(), e.g. -DBUILD_TESTS=ON, then ctest."
echo "     Tests that need data you cannot ship may skip themselves; read how they decide."

echo
echo "## install rules"
grep_build -w DESTINATION | sed "s/^/  /" | head -25 || true
grep_build -E 'option\s*\(\s*[A-Za-z0-9_]*INSTALL[A-Za-z0-9_]*' | sed 's/^/  /' || true
echo "  -> an install option that defaults OFF must be turned on; a DESTINATION of \".\""
echo "     or a bare path is a patch to GNUInstallDirs, never a hand copy in package()."

echo
echo "## build options"
grep_build -E '^\s*(option|cmake_dependent_option)\s*\(' | sed 's/^/  /' | head -60 || true
for _m in meson_options.txt meson.options; do
  [ -f "$_m" ] && grep -nE '^\s*option\(' "$_m" | sed "s|^|  $_m:|"
done

echo
echo "## license"
find . -maxdepth 2 -type f \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'LICENCE*' \) \
  -not -path './.git/*' | sed 's/^/  file: /'
grep -rhoE 'SPDX-License-Identifier:\s*[^ */]+' --include='*.[ch]' --include='*.cpp' \
  --include='*.hpp' --include='*.py' --include='*.rs' . 2>/dev/null | sort | uniq -c | sort -rn | head -5 | sed 's/^/  /'
_later=$(grep -rlE 'or \(at your option\) any later version|-or-later' \
  --include='*.[ch]' --include='*.cpp' --include='*.md' --include='*.txt' . 2>/dev/null |
  grep -viE '(^|/)(LICENSE|COPYING|LICENCE)' | head -3)
if [ -n "$_later" ]; then
  echo "  'or later' appears outside the license text, e.g.: $(tr '\n' ' ' <<<"$_later")"
else
  echo "  no 'or later' grant outside the license text: a bare GPL text means -only"
fi
echo "  -> the GPL text itself always says 'any later version'; that is not a grant (msys2-licensing)."
