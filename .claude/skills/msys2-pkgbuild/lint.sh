#!/usr/bin/env bash
# Check a PKGBUILD against the mechanical rules of the msys2-* skills.
#
# Usage:
#   lint.sh [PKGBUILD | package-dir]...
#
# Every finding is one line:
#   ERROR <rule>: what is wrong -- fix: what to do  [skill]
#   WARN  <rule>: ...
# An ERROR is a rule with no exceptions in this repo: fix it. A WARN usually
# means a fix too, but can be a deliberate choice; then the PKGBUILD carries a
# comment saying why, and the WARN stays. Exit status is 1 when any ERROR was
# printed, 0 otherwise.
#
# The PKGBUILD is sourced, as makepkg does, with the UCRT64 values of the
# MSYS2 variables. Nothing is built or downloaded.

set -uo pipefail

_lint_one() {
  local _dir _file
  _dir=$(cd "$(dirname "$1")" && pwd)
  _file="$_dir/$(basename "$1")"
  local _errors=0

  err()  { echo "ERROR $1: $2  [$3]"; _errors=$((_errors + 1)); }
  warn() { echo "WARN  $1: $2  [$3]"; }

  # An MSYS-environment package (alpmrpcd) follows other rules.
  local _msys=0
  if ! grep -q 'MINGW_PACKAGE_PREFIX' "$_file"; then
    echo "note: no \${MINGW_PACKAGE_PREFIX} -- treating it as an MSYS package; MinGW rules skipped"
    _msys=1
  fi

  # Source in a subshell and print what we need, so nothing leaks between runs.
  local _dump
  _dump=$(
    MSYSTEM=UCRT64 MINGW_PREFIX=/ucrt64 MINGW_PACKAGE_PREFIX=mingw-w64-ucrt-x86_64 \
    MINGW_CHOST=x86_64-w64-mingw32 CARCH=x86_64 srcdir=/src pkgdir=/pkg
    check_option() { return 1; }
    cd "$_dir" || exit 1
    # shellcheck disable=SC1090
    source "$_file" >/dev/null 2>&1 || { echo "SOURCE_FAILED="; exit 0; }
    _decl=$(declare -p pkgname 2>/dev/null); echo "PKGNAME_DECL=${_decl:0:10}"
    echo "PKGBASE=${pkgbase-}"
    echo "REALNAME=${_realname-}"
    echo "PKGDESC=${pkgdesc-}"
    echo "ARCH=${arch[*]-}"
    declare -p mingw_arch >/dev/null 2>&1 && echo "MINGW_ARCH_SET=1"
    echo "MINGW_ARCH=${mingw_arch[*]-}"
    echo "REPO_URL=${msys2_repository_url-}"
    declare -p msys2_references >/dev/null 2>&1 && echo "REFS_SET=1"
    for l in "${license[@]-}"; do echo "LICENSE=$l"; done
    for d in "${depends[@]-}"; do echo "DEPENDS=$d"; done
    for d in "${makedepends[@]-}"; do echo "MAKEDEPENDS=$d"; done
    for s in "${source[@]-}"; do echo "SOURCE=$s"; done
    for s in "${sha256sums[@]-}"; do echo "SUM=$s"; done
    for f in prepare build check package $(declare -F | awk '{print $3}' | grep '^package_'); do
      declare -F "$f" >/dev/null || continue
      echo "FUNC_${f%%_*}<<<"; declare -f "$f"; echo ">>>"
    done
  )

  # One pass over the dump: scalars into V, lists into L, function bodies into F.
  local -A V=() L=() F=()
  local _cur="" _line _k
  while IFS= read -r _line; do
    if [ -n "$_cur" ]; then
      if [ "$_line" = ">>>" ]; then _cur=""; else F[$_cur]+="$_line"$'\n'; fi
      continue
    fi
    case "$_line" in
      FUNC_*"<<<") _cur=${_line#FUNC_}; _cur=${_cur%<<<} ;;
      *=*)
        _k=${_line%%=*}
        case "$_k" in
          LICENSE|DEPENDS|MAKEDEPENDS|SOURCE|SUM) L[$_k]+="${_line#*=}"$'\n' ;;
          *) V[$_k]=${_line#*=} ;;
        esac ;;
    esac
  done <<<"$_dump"

  if [ -n "${V[SOURCE_FAILED]+x}" ]; then
    err source-fails "sourcing the PKGBUILD failed -- fix: run 'bash -n PKGBUILD' and 'makepkg-mingw --printsrcinfo'" msys2-pkgbuild
    return 1
  fi

  local _prepare=${F[prepare]-} _build=${F[build]-} _check=${F[check]-} _package=${F[package]-}
  local _pfx=mingw-w64-ucrt-x86_64

  # --- header -------------------------------------------------------------
  if [ "$_msys" -eq 0 ]; then
    case "${V[PKGBASE]-}" in
      mingw-w64-?*) ;;
      *) err pkgbase "pkgbase is '${V[PKGBASE]-}' -- fix: pkgbase=mingw-w64-\${_realname}" msys2-pkgbuild ;;
    esac
    [ "${V[PKGNAME_DECL]-}" = "declare -a" ] ||
      warn pkgname-array "pkgname is not an array -- fix: pkgname=(\"\${MINGW_PACKAGE_PREFIX}-\${_realname}\")" msys2-pkgbuild
    [ -n "${V[MINGW_ARCH_SET]-}" ] ||
      err mingw_arch "mingw_arch is not set -- fix: mingw_arch=('ucrt64'), then add each environment once it builds and passes check()" msys2-environments
    case " ${V[MINGW_ARCH]-} " in
      *" clangarm64 "*) warn mingw_arch "clangarm64 cannot be built on x86_64; list it only if it was built on ARM64" msys2-environments ;;
    esac
    case "${V[PKGDESC]-}" in
      *"(mingw-w64)") ;;
      *) warn pkgdesc "pkgdesc does not end with '(mingw-w64)'" msys2-pkgbuild ;;
    esac
    [ -n "${V[REPO_URL]-}" ] ||
      warn msys2_repository_url "not set -- fix: the web view of upstream's repository, even if it equals url" msys2-pkgbuild
    [ -n "${V[REFS_SET]-}" ] ||
      warn msys2_references "not set -- fix: add 'archlinux: <name>' or 'aur: <name>' if either carries it; leave it out only if nobody else packages it" msys2-pkgbuild
    [ "${V[ARCH]-}" = any ] ||
      err arch "arch is '${V[ARCH]-}' -- fix: arch=('any')" msys2-pkgbuild
  fi
  local _rn=${V[REALNAME]-}
  if [ -n "$_rn" ]; then
    case "${V[PKGDESC],,}" in
      "${_rn,,} is "*) warn pkgdesc "pkgdesc reads '<name> is ...' -- describe what it is: 'Reimplementation of ...'" msys2-pkgbuild ;;
    esac
  fi

  # --- license ------------------------------------------------------------
  local _l
  [ -n "${L[LICENSE]-}" ] || err license "license is empty" msys2-licensing
  while IFS= read -r _l; do
    case "$_l" in
      ""|spdx:*) ;;
      *) err license "license '$_l' is not SPDX -- fix: license=('spdx:<id>'); GPL3 means GPL-3.0-only unless upstream grants 'or later'" msys2-licensing ;;
    esac
  done <<<"${L[LICENSE]-}"
  [[ $_package == *share/licenses* ]] ||
    warn license-file "package() installs no license file -- fix: install -Dm644 <LICENSE> \"\${pkgdir}\${MINGW_PREFIX}/share/licenses/\${_realname}/LICENSE\"; with none upstream, say so in a comment" msys2-licensing

  # --- dependencies -------------------------------------------------------
  if [ "$_msys" -eq 0 ]; then
    local _d
    while IFS= read -r _d; do
      case "$_d" in
        "$_pfx-gcc-libs"*) err cc-libs "'$_d' in depends -- fix: \${MINGW_PACKAGE_PREFIX}-cc-libs, and only if ntldd shows libgcc/libstdc++/libwinpthread" msys2-pkgbuild ;;
      esac
    done <<<"${L[DEPENDS]-}"
    local _has_cc=0
    while IFS= read -r _d; do
      case "$_d" in
        "$_pfx-gcc"|"$_pfx-gcc"[\<\>=]*)
          _has_cc=1
          err cc "'$_d' in makedepends -- fix: \${MINGW_PACKAGE_PREFIX}-cc (gcc breaks CLANG64)" msys2-pkgbuild ;;
        "$_pfx-cc"|"$_pfx-cc"[\<\>=]*|"$_pfx-toolchain"|"$_pfx-clang") _has_cc=1 ;;
      esac
    done <<<"${L[MAKEDEPENDS]-}"
    if [ "$_has_cc" -eq 0 ] && grep -qE 'cmake|meson|configure|make|ninja|gcc|clang|node-gyp' <<<"$_build"; then
      warn cc "build() compiles but makedepends has no \${MINGW_PACKAGE_PREFIX}-cc" msys2-pkgbuild
    fi
    # Literal environment values mean the recipe only works in one environment.
    local _lit
    _lit=$(grep -nE '/ucrt64|/clang64|/mingw64|/mingw32|mingw-w64-(ucrt|clang)-|mingw-w64-(x86_64|i686)-|x86_64-w64-mingw32' "$_file" |
           grep -v '^[0-9]*:[[:space:]]*#' | head -n3 | tr '\n' ' ')
    [ -z "$_lit" ] ||
      err literal-env "hardcoded environment path or prefix -- fix: \${MINGW_PREFIX}, \${MINGW_PACKAGE_PREFIX}, \${MINGW_CHOST}: $_lit" msys2-pkgbuild
  fi

  # --- sources and checksums ----------------------------------------------
  local -a _src=() _sum=()
  [ -n "${L[SOURCE]-}" ] && mapfile -t _src <<<"${L[SOURCE]%$'\n'}"
  [ -n "${L[SUM]-}" ] && mapfile -t _sum <<<"${L[SUM]%$'\n'}"
  if [ "${#_src[@]}" -ne "${#_sum[@]}" ]; then
    err checksums "${#_src[@]} sources but ${#_sum[@]} sha256sums -- fix: run updpkgsums" msys2-new-package
  else
    local i
    for i in "${!_src[@]}"; do
      [ "${_sum[$i]}" = SKIP ] || continue
      case "${_src[$i]}" in
        *git+*|*svn+*|*hg+*|*.sig|*.asc) ;;
        *) err checksums "SKIP for non-VCS source '${_src[$i]##*/}' -- fix: run updpkgsums" msys2-new-package ;;
      esac
    done
  fi
  # A loop over *.patch or source[@] applies every listed patch.
  local _loop=0
  grep -qE '\*\.patch|\*\.diff|00\*|source\[@\]' <<<"$_prepare" && _loop=1
  local _s _name
  for _s in "${_src[@]}"; do
    _name=${_s%%::*}; _name=${_name##*/}
    case "$_name" in
      *.patch|*.diff)
        [ "$_loop" -eq 1 ] || [[ $_prepare == *"$_name"* ]] ||
          err patch-unapplied "$_name is in source=() but prepare() never applies it" msys2-patch-author
        if [ -f "$_dir/$_name" ] && ! grep -qE '^Upstream(-Status)?:' "$_dir/$_name"; then
          warn patch-header "$_name has no 'Upstream:' provenance line" msys2-patch-author
        fi ;;
    esac
  done
  local _p
  for _p in "$_dir"/*.patch "$_dir"/*.diff; do
    [ -e "$_p" ] || continue
    [[ ${L[SOURCE]-} == *"${_p##*/}"* ]] ||
      warn patch-unlisted "${_p##*/} is in the directory but not in source=()" msys2-patch-author
  done

  # --- build ----------------------------------------------------------------
  if [[ $_build == *CMAKE_BUILD_TYPE=* && $_build != *check_option* ]]; then
    err build-type "CMAKE_BUILD_TYPE is hardcoded -- fix: choose Release/Debug with 'check_option \"debug\" \"n\"' (CMake skeleton)" msys2-pkgbuild
  fi
  if [[ $_build == *-DCMAKE_INSTALL_PREFIX* && $_build != *MSYS2_ARG_CONV_EXCL* ]]; then
    warn arg-conv "-DCMAKE_INSTALL_PREFIX without MSYS2_ARG_CONV_EXCL -- the MSYS runtime may rewrite the path" msys2-pkgbuild
  fi
  if grep -qE 'meson(\.exe)? setup' <<<"$_build" && [[ $_build != *--wrap-mode=nodownload* ]]; then
    err meson-wrap "meson setup without --wrap-mode=nodownload -- the build may download and bundle dependencies" msys2-dependencies
  fi
  [[ $_build == *FETCHCONTENT* || $_build == *FetchContent* ]] &&
    warn fetchcontent "build() configures FetchContent -- dependencies come from packages; a bundled copy needs a comment saying why" msys2-dependencies

  # --- check() --------------------------------------------------------------
  if [ -z "$_check" ]; then
    err check "no check() -- fix: run upstream's tests (find them with msys2-new-package/survey.sh); with none, write a test of your own" msys2-pkgbuild
  else
    local _cbody
    _cbody=$(sed '1,2d;$d' <<<"$_check" | grep -vE '^\s*(true|:);?\s*$' | grep -c .)
    [ "$_cbody" -gt 0 ] || err check "check() does nothing" msys2-pkgbuild
  fi
  if grep -qE -- '--target test(\s|"|$)' <<<"$_check" && [[ $_build == *cmake* ]] &&
     ! grep -qiE -- '-D[A-Z_]*TEST[A-Z_]*=(ON|1|TRUE)' <<<"$_build"; then
    warn check "check() runs the CMake test target, but build() enables no *TEST* option -- many projects build no tests by default; make sure ctest finds some" msys2-pkgbuild
  fi

  # --- package() ------------------------------------------------------------
  if [ -z "$_package" ]; then
    err package "no package() function" msys2-pkgbuild
  else
    grep -qE '(^|[;&|[:space:]])(mv|rm|rename)[[:space:]]' <<<"$_package" &&
      warn package-fixup "package() moves or deletes files -- if that fixes build output, patch the build system instead" msys2-packaging
    if grep -qE 'cmake|meson|ninja' <<<"$_build" &&
       ! grep -qE -- '--install|meson(\.exe)? install|ninja.* install|make.* install' <<<"$_package" &&
       grep -qE 'install .*(build|\$\{?_?builddir)' <<<"$_package"; then
      warn package-by-hand "package() copies build output by hand -- use the build system's install target, patching it if it installs to the wrong place" msys2-packaging
    fi
  fi

  return $(( _errors > 0 ))
}

[ $# -gt 0 ] || set -- PKGBUILD
_status=0
_many=0; [ $# -gt 1 ] && _many=1
for _arg in "$@"; do
  [ -d "$_arg" ] && _arg="$_arg/PKGBUILD"
  [ -f "$_arg" ] || { echo "error: no such PKGBUILD: $_arg" >&2; _status=2; continue; }
  [ "$_many" -eq 1 ] && echo "== $_arg"
  _lint_one "$_arg" || _status=1
done
exit "$_status"
