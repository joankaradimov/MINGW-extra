# CMake toolchain file: 32-bit DOS binaries built with Open Watcom.
#
#   cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/OpenWatcomDOS.cmake
#
# Open Watcom's own environment has to be set up first, because its compiler
# driver locates the back ends through WATCOM and PATH. With the MSYS2
# package that is:
#
#   . $MINGW_PREFIX/lib/watcom/owsetenv.sh
#
# Failing that, pass -DWATCOM_ROOT=<dir> and make sure the host tool
# directory is on PATH.

set(CMAKE_SYSTEM_NAME DOS)
set(CMAKE_SYSTEM_PROCESSOR I386)

if(NOT WATCOM_ROOT)
  if(DEFINED ENV{WATCOM})
    file(TO_CMAKE_PATH "$ENV{WATCOM}" WATCOM_ROOT)
  else()
    message(FATAL_ERROR
      "Open Watcom not found. Source its environment script first, or pass "
      "-DWATCOM_ROOT=<dir>. See the comments at the top of this file.")
  endif()
endif()
set(WATCOM_ROOT "${WATCOM_ROOT}" CACHE PATH "Open Watcom installation root")

# Host tools. Prefer the 64-bit set; a 32-bit hosted Open Watcom builds its
# tools into binnt and leaves only DOS stub files in binnt64.
if(EXISTS "${WATCOM_ROOT}/binnt64/wcl386.exe")
  set(_watcom_bin "${WATCOM_ROOT}/binnt64")
else()
  set(_watcom_bin "${WATCOM_ROOT}/binnt")
endif()
set(WATCOM_BIN "${_watcom_bin}" CACHE PATH "Open Watcom host tool directory")

set(CMAKE_C_COMPILER   "${WATCOM_BIN}/wcl386.exe")
set(CMAKE_ASM_COMPILER "${WATCOM_BIN}/wasm.exe")
set(CMAKE_LINKER       "${WATCOM_BIN}/wlink.exe")
set(CMAKE_AR           "${WATCOM_BIN}/wlib.exe")

# wcl386 launches wcc386 and the other back ends, and wlink resolves the
# libpath entries of its system definitions, both through WATCOM. Set it for
# this CMake run if the caller has not; the build step needs it too.
if(NOT DEFINED ENV{WATCOM})
  set(ENV{WATCOM} "${WATCOM_ROOT}")
endif()

# Linking an executable needs a DOS extender stub, so probe with a library.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Open Watcom's assembler names its output with -fo= and takes include
# directories with -i=, neither of which matches CMake's generic rule.
set(CMAKE_ASM_SOURCE_FILE_EXTENSIONS asm;ASM)
set(CMAKE_INCLUDE_FLAG_ASM "-i=")
set(CMAKE_ASM_COMPILE_OBJECT
    "<CMAKE_ASM_COMPILER> -zq <DEFINES> <INCLUDES> <FLAGS> -fo=<OBJECT> <SOURCE>")
set(CMAKE_ASM_COMPILER_ID "OpenWatcom")
set(CMAKE_ASM_COMPILER_WORKS 1)
