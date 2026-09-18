# Open Watcom V2 environment for MSYS2 shells.
#
# Source this file to put the Open Watcom tools on PATH and set the
# variables the tools expect:
#
#   . ${MINGW_PREFIX}/lib/watcom/owsetenv.sh
#
# The wrapper scripts in ${MINGW_PREFIX}/bin (wcc386, wcl386, wlink, ...)
# set up the same environment on their own; sourcing this file is only
# needed to run the tools from ${WATCOM}/binnt64 directly, or to point
# INCLUDE at a different target (DOS, OS/2, Win16, Linux).

_owroot="$(cd "$(dirname "${BASH_SOURCE:-$0}")" && pwd)"

export WATCOM="$(cygpath -m "${_owroot}")"
export EDPATH="${WATCOM}/eddat"
export WIPFC="${WATCOM}/wipfc"
export WHTMLHELP="${WATCOM}/binnt/help"
export INCLUDE="${WATCOM}/h;${WATCOM}/h/nt;${WATCOM}/h/nt/directx;${WATCOM}/h/nt/ddk${INCLUDE:+;${INCLUDE}}"
# binw last: its tools are 16-bit and unrunnable here, but wlink searches
# PATH for the DOS extender stubs it binds into DOS executables.
export PATH="${_owroot}/binnt64:${_owroot}/binnt:${PATH}:${_owroot}/binw"

unset _owroot
