---
name: msys2-test-isolated
description: Smoke-test a built MSYS2 / MinGW-w64 package in a throwaway pacman root instead of installing it into the development machine — proving the declared depends() are complete and the binaries run against nothing but their own closure. Use after a package builds and before committing it, in place of `pacman -U`, and whenever a package must be tested without polluting the real MSYS2 installation.
---

# Testing a built package in isolation

`pacman -U` on the development machine is the wrong way to smoke-test a package, for a
reason that has nothing to do with tidiness: **it hides the defect you are testing for.**

Once a library is installed system-wide, a package that forgot to declare it still runs
perfectly. The dependency is satisfied by accident. The package then goes to the repo,
someone installs it on a clean machine, and it fails at load time with a missing DLL.
Testing in a polluted root cannot detect this, no matter how thorough the smoke test is.

A throwaway root fixes both problems at once. Nothing touches the real installation, and
the package is exercised against **exactly** its declared closure and nothing else.

## The method

`pacman -r <root>` installs into an alternate prefix. Point it at a temporary directory,
hand it the built packages, let it resolve the dependency closure from the real repos, then
run the binary with `PATH` restricted to that root.

The closure is small. For `mpqcli` it is 7 packages and **9.9 MB** — versus 9.8 GB for the
full UCRT64 tree on this machine. This costs seconds, not minutes, so there is no reason to
skip it.

## Usage

```bash
isolated-test.sh [--keep] [--nodeps] [--build CMD] <pkg.tar.zst>... [-- <command>]
```

Two phases, and the split matters:

| Phase | Environment | For |
|---|---|---|
| `--build CMD` | **host**, full PATH, `$ISOLATED_CC` and `$ISOLATED_PREFIX` set | compiling a test consumer — a toolchain is a `makedepends` concern |
| `-- COMMAND` | **isolated**, PATH restricted to the throwaway prefix | running it — the `depends` closure under test |

Exit code is the command's. The root is deleted on exit unless `--keep`.

```bash
# an application: exercise it for real, not just --version
./.claude/skills/msys2-test-isolated/isolated-test.sh \
  stormlib/mingw-w64-ucrt-x86_64-stormlib-9.40-1-any.pkg.tar.zst \
  mpqcli/mingw-w64-ucrt-x86_64-mpqcli-0.10.2-1-any.pkg.tar.zst \
  -- 'T=$(mktemp -d); cd $T; mkdir p; echo hi > p/a.txt;
      mpqcli.exe create ./p -o t.mpq >/dev/null && mkdir o &&
      mpqcli.exe extract t.mpq -o o >/dev/null && cmp p/a.txt o/a.txt'

# a library: compile on the host against the isolated root, then run isolated
./.claude/skills/msys2-test-isolated/isolated-test.sh \
  stormlib/mingw-w64-ucrt-x86_64-stormlib-9.40-1-any.pkg.tar.zst \
  --build '$ISOLATED_CC /tmp/t.c -I$ISOLATED_PREFIX/include -L$ISOLATED_PREFIX/lib -lStormLib -o /tmp/t.exe' \
  -- '/tmp/t.exe'
```

**Pass every locally built package in the set together.** A sibling package from this repo
exists in no remote repository, so pacman can only see it if you hand it over. That is a
feature: if you omit one, resolution fails here instead of silently passing.

## Doing it by hand

```bash
_root=$(mktemp -d)/root
mkdir -p "$_root/var/lib/pacman"
_pac=(pacman -r "$_root" --dbpath "$_root/var/lib/pacman"
      --cachedir /var/cache/pacman/pkg --noconfirm)

"${_pac[@]}" -Sy --dbonly              # sync databases only
"${_pac[@]}" -U <pkgs>...              # install closure
"${_pac[@]}" -Q                        # what landed
```

| Flag | Why it is needed |
|---|---|
| `-r <root>` | the alternate install root — the whole point |
| `--dbpath <root>/var/lib/pacman` | keeps the local package database inside the root |
| `--cachedir /var/cache/pacman/pkg` | reuses the host's cache, so dependencies are not re-downloaded |
| `-Sy --dbonly` | populates sync databases so resolution works, without unpacking a base system |

## Six traps, all of them load-bearing

Traps 5 and 6 are the dangerous ones: they do not make the test fail, they make it **pass
for the wrong reason**.

**1. `env -i ... bash` gets you WSL's bash.** On a machine with WSL installed, clearing the
environment makes `bash` resolve to `/mnt/c`-flavoured WSL bash, and every MSYS2 path on
your carefully built `PATH` becomes meaningless. Spell out `/usr/bin/bash --noprofile
--norc`.

**2. pacman skips unresolvable packages and still exits 0.** Given a package whose
dependency it cannot find, it prints `warning: cannot resolve ...`, asks to skip it, and
finishes with `there is nothing to do` — exit status 0. A harness that only checks pacman's
exit code will report a pass on a root that does not contain the package. Verify explicitly
that every requested package is present afterwards:

```bash
_name=$(pacman -Qp "$pkg" 2>/dev/null | awk '{print $1}')
"${_pacq[@]}" -Q "$_name" >/dev/null || echo "FAIL: $_name was skipped"
```

**3. `pacman -Qp` has no `--print-format`.** It is a `-S`/`-Q` query option only; on a
package *file* it errors out. Parse the plain `name version` output instead.

**4. Restrict `PATH`, or you prove nothing.** If the real prefix's `bin/` is still on
`PATH`, Windows will happily resolve the package's DLLs from there and the test passes
regardless. `PATH` must start with the throwaway prefix and must not contain the real one.

**5. A bare `gcc` in an MSYS shell is the Cygwin compiler.** `/usr/bin/gcc` is
`x86_64-pc-cygwin`, and it links test binaries against `msys-2.0.dll` rather than the MinGW
runtime the package was built for. It compiles, it links, it runs, it reports `PASS` — and
it tested a Cygwin consumer instead of a MinGW one. Use `$ISOLATED_CC`, which the script
points at the host prefix's own compiler (`/ucrt64/bin/gcc`, `/clang64/bin/clang`). Confirm
with `$ISOLATED_CC -dumpmachine` — it must be `x86_64-w64-mingw32`, never `*-cygwin` — and
check the result has no `msys-2.0.dll` in `objdump -p`.

**6. You cannot compile inside the isolated run.** `gcc` spawns `cc1.exe` and `collect2.exe`,
which load their DLLs from the real prefix's `bin/`. With `PATH` restricted, gcc exits 1
having printed nothing at all. Putting the real `bin/` on `PATH` to fix it would defeat trap
4. This is not a limitation to work around — the two phases are genuinely different
concerns, which is why `--build` runs on the host and `--` runs isolated.

Traps 5 and 6 compound: the "obvious" one-liner that compiles and runs in a single isolated
command fails trap 6, and the "obvious" fix of falling back to a bare `gcc` silently walks
into trap 5.

## What this does and does not catch

| Catches | Does not catch |
|---|---|
| a dependency missing from `depends=()` | assumptions about registry or system-wide state |
| a `depends=()` entry that no repo provides | a missing MSVC runtime on a clean Windows |
| a binary that cannot start (missing DLL) | installer / uninstaller side effects |
| a sibling package forgotten in the build set | anything needing a fresh Windows user profile |
| over-declared deps (compare closure to `depends`) | GUI behaviour and file associations |

The right-hand column needs a real ephemeral machine. Windows Sandbox
(`Containers-DisposableClientVM`) can provide one, but note it is **not** a named,
PowerShell-managed container: there are no sandbox cmdlets at all, only
`WindowsSandbox.exe` plus a `.wsb` XML file, automation goes through `<LogonCommand>` and
`<MappedFolder>`, and there is no return channel — the exit code has to come back through a
polled sentinel file in a mapped folder. It also boots blank, so MSYS2 must be staged into
it on every run. Reach for it deliberately, not by default. For a named and genuinely
scriptable VM, Hyper-V (`New-VM`, `Checkpoint-VM`, `Restore-VMCheckpoint`) is the real
answer.

## Prove the harness can fail

A test that has never failed is not known to work. `--nodeps` installs without resolving
dependencies, simulating a `depends=()` entry that was forgotten:

```bash
./.claude/skills/msys2-test-isolated/isolated-test.sh --nodeps \
  mpqcli/mingw-w64-ucrt-x86_64-mpqcli-0.10.2-1-any.pkg.tar.zst -- 'mpqcli.exe version'
# error while loading shared libraries: libStormLib.dll: cannot open shared object file
# ==> FAIL (exit 127)
```

If that comes back `PASS`, the isolation is broken — almost always trap 4.

## Checklist

- [ ] every locally built package in the set passed on one command line
- [ ] closure listing read — nothing unexpected, nothing missing
- [ ] closure contents reconcile with `depends=()`: nothing extra, nothing absent
- [ ] the smoke test does real work, not just `--version`
- [ ] test consumers compiled with `$ISOLATED_CC` via `--build`, never a bare `gcc`
- [ ] built consumer has no `msys-2.0.dll` in `objdump -p` (trap 5)
- [ ] run repeated for each environment in `mingw_arch`
- [ ] `--nodeps` negative control fails, confirming the harness can detect a defect
- [ ] `pacman -Q` on the real root afterwards shows the package was never installed there

## Sources

`pacman(8)` — `--root`, `--dbpath`, `--cachedir`, `--dbonly`, `--nodeps`. Behaviours in
"Four traps" were each reproduced on this machine rather than taken from documentation.
Windows Sandbox: <https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/>
(configuration is a `.wsb` file; no PowerShell module ships with the feature).
