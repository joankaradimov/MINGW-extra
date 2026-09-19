#!/usr/bin/env bash
# Install built MSYS2 packages into a throwaway pacman root and run a command
# against them, without touching the real MSYS2 installation.
#
# Usage:
#   isolated-test.sh [--keep] [--nodeps] [--build CMD] PKG... [-- COMMAND...]
#
# Every locally built package the set depends on must be passed together: a
# sibling package from this repo is in no remote repository, so pacman can only
# see it if you hand it over. That is the point -- if the set is incomplete,
# resolution fails here instead of silently passing on a polluted machine.
#
# With no COMMAND, the root is populated and its contents reported.
# --nodeps installs without dependency resolution, to confirm a test can fail.
#
# --build CMD runs CMD on the HOST, with the normal environment and $ISOLATED_PREFIX
# set, before the isolated run. Compiling a test consumer belongs here: a toolchain
# is a makedepends concern and must come from the host, while the runtime libraries
# under test come from the throwaway root. Compiling inside the isolated run cannot
# work -- gcc's subprocesses (cc1.exe, collect2.exe) load their DLLs from the real
# prefix's bin/, and putting that on PATH would defeat the isolation entirely.

set -uo pipefail

_keep=0
_nodeps=()
_build=""
_pkgs=()
_cmd=()
while [ $# -gt 0 ]; do
  case "$1" in
    --keep)   _keep=1; shift ;;
    --nodeps) _nodeps=(--nodeps --nodeps); shift ;;
    --build)  _build="${2-}"; shift 2 ;;
    --)       shift; _cmd=("$@"); break ;;
    *)        _pkgs+=("$1"); shift ;;
  esac
done

[ ${#_pkgs[@]} -gt 0 ] || { echo "error: no packages given" >&2; exit 2; }

for p in "${_pkgs[@]}"; do
  [ -f "$p" ] || { echo "error: no such package file: $p" >&2; exit 2; }
done

# Derive the environment from the package name so PATH can point at the right
# prefix. mingw-w64-ucrt-x86_64-foo -> ucrt64.
case "$(basename "${_pkgs[0]}")" in
  mingw-w64-ucrt-x86_64-*)   _prefix=ucrt64;     _cc=gcc   ;;
  mingw-w64-clang-x86_64-*)  _prefix=clang64;    _cc=clang ;;
  mingw-w64-clang-aarch64-*) _prefix=clangarm64; _cc=clang ;;
  mingw-w64-x86_64-*)        _prefix=mingw64;    _cc=gcc   ;;
  mingw-w64-i686-*)          _prefix=mingw32;    _cc=gcc   ;;
  *)                         _prefix=usr;        _cc=gcc   ;;
esac

# The host's real prefix for this environment. The toolchain for a build step must
# come from here: a bare `gcc` in an MSYS shell is /usr/bin/gcc, which is the Cygwin
# compiler and produces binaries linked against msys-2.0.dll rather than the MinGW
# runtime the package is built for.
_host_prefix="/$_prefix"
_host_cc="$_host_prefix/bin/$_cc"

_root=$(mktemp -d)/root
mkdir -p "$_root/var/lib/pacman"
if [ "$_keep" -eq 0 ]; then
  trap 'rm -rf "$(dirname "$_root")"' EXIT
fi

_pacq=(pacman -r "$_root" --dbpath "$_root/var/lib/pacman")
_pac=("${_pacq[@]}" --cachedir /var/cache/pacman/pkg --noconfirm)

echo "==> throwaway root: $_root  (prefix: $_prefix, host cc: $_host_cc)"

# Sync only the databases; --dbonly keeps this from unpacking a base system.
"${_pac[@]}" -Sy --dbonly >/dev/null 2>&1 \
  || { echo "error: could not sync databases into the throwaway root" >&2; exit 1; }

echo "==> installing ${#_pkgs[@]} package(s) and their dependency closure"
if ! "${_pac[@]}" "${_nodeps[@]}" -U "${_pkgs[@]}"; then
  echo "FAIL: pacman could not install the package set into a clean root" >&2
  echo "      an unresolvable dependency here is a real defect in depends=()" >&2
  exit 1
fi

# pacman answers an unresolvable dependency by *skipping* that package and
# still exiting 0 ("there is nothing to do"). Confirm every package asked for
# actually landed, or the run below would test a root that silently lacks it.
_missing=0
for p in "${_pkgs[@]}"; do
  _name=$(pacman -Qp "$p" 2>/dev/null | awk '{print $1}')
  if ! "${_pacq[@]}" -Q "$_name" >/dev/null 2>&1; then
    echo "FAIL: $_name was skipped -- its dependencies are not satisfiable" >&2
    echo "      from the repos plus the packages given on the command line." >&2
    echo "      Either depends=() names something that does not exist, or a" >&2
    echo "      sibling package built in this repo was not passed alongside." >&2
    _missing=1
  fi
done
[ "$_missing" -eq 0 ] || exit 1

echo "==> closure installed:"
"${_pacq[@]}" -Q 2>/dev/null | sed 's/^/      /'
echo "==> closure size: $(du -sh "$_root/$_prefix" 2>/dev/null | cut -f1)"

# Host-side build phase: full environment, plus the isolated prefix to compile
# against. The toolchain comes from the host on purpose; only the libraries under
# test come from the throwaway root.
if [ -n "$_build" ]; then
  echo "==> host build: $_build"
  if ! ISOLATED_ROOT="$_root" ISOLATED_PREFIX="$_root/$_prefix"        ISOLATED_CC="$_host_cc" ISOLATED_HOST_PREFIX="$_host_prefix"        PATH="$_host_prefix/bin:$PATH"        /usr/bin/bash -c "$_build"; then
    echo "==> FAIL (host build step failed)" >&2
    exit 1
  fi
fi

[ ${#_cmd[@]} -gt 0 ] || exit 0

# Run the command with PATH pointing at the throwaway prefix, so nothing can
# fall back to the real one. /usr/bin/bash is spelled out because `env -i bash`
# finds WSL's bash on a machine with WSL installed, not MSYS2's.
echo "==> running: ${_cmd[*]}"
/usr/bin/env -i \
  SYSTEMROOT="C:\Windows" \
  TMP=/tmp TEMP=/tmp \
  ISOLATED_ROOT="$_root" \
  ISOLATED_PREFIX="$_root/$_prefix" \
  PATH="$_root/$_prefix/bin:/usr/bin:/c/Windows/System32:/c/Windows" \
  /usr/bin/bash --noprofile --norc -c "${_cmd[*]}"
_rc=$?

if [ $_rc -eq 0 ]; then echo "==> PASS"; else echo "==> FAIL (exit $_rc)"; fi
exit $_rc
