#!/bin/sh
# Uses the Open Watcom tree in $1: a C and a C++ Win32 console program must
# build, run and print what they should, and a DOS program built through the
# toolchain file $2, with the caller's CFLAGS and LDFLAGS still set, must come
# out as an MZ executable.
set -eu
rel=$(cygpath -am "$1")
toolchain=$(cygpath -am "$2")
work=$(mktemp -d "${PWD}/check-XXXXXX")
cd "${work}"

bin="${rel}/binnt64"
[ -f "${bin}/wcl386.exe" ] || bin="${rel}/binnt"
export WATCOM="${rel}"
export INCLUDE="${rel}/h;${rel}/h/nt"
export PATH="$(cygpath -u "${bin}"):$(cygpath -u "${rel}/binw"):${PATH}"

cat > hello.c <<'EOF'
#include <stdio.h>
int main(void) { printf("%s %d\n", "C", 6 * 7); return 0; }
EOF
cat > hello.cpp <<'EOF'
#include <iostream>
#include <string>
int main() { std::string s("C+"); s += '+'; std::cout << s.c_str() << ' ' << 6 * 7 << std::endl; return 0; }
EOF

wcl386 -zq -bt=nt -l=nt -fe=hello-c.exe hello.c
wcl386 -zq -xs -bt=nt -l=nt -fe=hello-cpp.exe hello.cpp
[ "$(./hello-c.exe | tr -d '\r')" = "C 42" ]
[ "$(./hello-cpp.exe | tr -d '\r')" = "C++ 42" ]
echo "Win32: the C and C++ programs ran"

mkdir dos
cat > dos/CMakeLists.txt <<'EOF'
cmake_minimum_required(VERSION 3.20)
project(hello C)
add_executable(hello ../hello.c)
EOF
cmake -S dos -B dos/build -G Ninja -DCMAKE_TOOLCHAIN_FILE="${toolchain}" \
  -DWATCOM_ROOT="${rel}" > dos/configure.log
cmake --build dos/build > dos/build.log
[ "$(head -c 2 dos/build/hello.exe)" = "MZ" ]
echo "DOS: OpenWatcomDOS.cmake built an MZ executable"
