# MINGW-extra

Extra MinGW-w64 packages for [MSYS2](https://www.msys2.org/): software the
official MSYS2 repositories don't carry, in a pacman repository of its own at
**https://msys2pkgs.karadimov.org**.

Every package is built by GitHub Actions from a PKGBUILD in this repository. The
repository only adds packages; it is meant to sit next to MSYS2's own
repositories, not to replace anything they ship.

## Using it

Append these sections to the end of `/etc/pacman.conf`, after MSYS2's own
repositories, so that MSYS2 keeps precedence. Keep the environments you use, and
`msys-extra` in any case: some packages here depend on an MSYS package
from it.

```ini
[ucrt64-extra]
SigLevel = Optional TrustAll
Server = https://msys2pkgs.karadimov.org/ucrt64

[clang64-extra]
SigLevel = Optional TrustAll
Server = https://msys2pkgs.karadimov.org/clang64

[clangarm64-extra]
SigLevel = Optional TrustAll
Server = https://msys2pkgs.karadimov.org/clangarm64

[mingw64-extra]
SigLevel = Optional TrustAll
Server = https://msys2pkgs.karadimov.org/mingw64

[mingw32-extra]
SigLevel = Optional TrustAll
Server = https://msys2pkgs.karadimov.org/mingw32

[msys-extra]
SigLevel = Optional TrustAll
Server = https://msys2pkgs.karadimov.org/msys
```

The packages are not signed yet. `SigLevel = Optional TrustAll` is what lets
pacman accept them.

Then refresh, see what is available, and install. From a UCRT64 shell:

```sh
pacman -Sy
pacman -Sl ucrt64-extra
pacman -S mingw-w64-ucrt-x86_64-stormlib
```

In any environment's shell, `${MINGW_PACKAGE_PREFIX}-stormlib` expands to the
right name. Not every package is built for every environment; `pacman -Sl` shows
what yours has.

| Environment | Repository | Package names start with |
| --- | --- | --- |
| UCRT64 | `ucrt64-extra` | `mingw-w64-ucrt-x86_64-` |
| CLANG64 | `clang64-extra` | `mingw-w64-clang-x86_64-` |
| CLANGARM64 | `clangarm64-extra` | `mingw-w64-clang-aarch64-` |
| MINGW64 | `mingw64-extra` | `mingw-w64-x86_64-` |
| MINGW32 | `mingw32-extra` | `mingw-w64-i686-` |
| MSYS | `msys-extra` | no prefix |

To stop using it, delete the sections and run `pacman -Sy`. Installed packages
stay installed; `pacman -Qm` lists the ones no remaining repository provides.

From a cloud VM or a CI runner, the host's bot protection can answer with a
challenge page instead of the database, and pacman then calls the `*-extra`
databases invalid or corrupted. Ordinary connections are not affected.

## Working on it

Each top-level directory holding a `PKGBUILD` is one package; there is nothing
else to register. [`ci/README.md`](ci/README.md) covers how CI decides what to
build, which environments a package is built for, and how the results reach the
server.

Problems and requests go to the
[issue tracker](https://github.com/joankaradimov/MINGW-extra/issues).
