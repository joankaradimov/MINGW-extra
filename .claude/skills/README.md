# MSYS2 packaging skills

A library of Claude-compatible skills for building MinGW-w64 packages under MSYS2, written for
this repository. Modelled on [pahheb-skills](https://github.com/Pahheb/pahheb-skills), but
grounded in [msys2.org](https://www.msys2.org/dev/) rather than the AUR — Arch and the AUR are
used here only as a reference of last resort, never as the source of conventions.

## The skills

| Skill | Purpose |
|---|---|
| `msys2-packaging` | **Router.** House rules and dispatch to everything below. |
| `msys2-new-package` | End-to-end workflow for adding a package: upstream check → prior art → deps → UCRT64 → ladder. |
| `msys2-dependencies` | Classify `depends`/`makedepends`; recursively package the missing ones. |
| `msys2-pkgbuild` | PKGBUILD anatomy, MSYS2 variables, split-package wrappers, build-system skeletons. |
| `msys2-environments` | The environment matrix, `mingw_arch` vs `MINGW_ARCH`, the expansion ladder. |
| `msys2-makepkg` | `makepkg-mingw` flags, directory layout, fast iteration, error decoding. |
| `msys2-patch-diagnose` | Classify a build failure into a known MinGW failure class. |
| `msys2-patch-author` | Create, name, apply, refresh and retire patches. |
| `msys2-verify-package` | Post-build QA before committing or extending `mingw_arch`. |
| `msys2-test-isolated` | Smoke-test a built package in a throwaway pacman root, never the real MSYS2. |
| `msys2-licensing` | `license=()` SPDX rules and license file placement. |
| `msys2-nodejs` | Node.js applications: lockfile-pinned `npm ci`, bundled modules, node-gyp addons on shared MinGW libraries. |

## Four things these skills insist on

**Check `msys2/MINGW-packages` first.** A package that already has an upstream recipe should not
be re-packaged here without a stated reason. When there is no upstream recipe,
[Arch Linux](https://archlinux.org/packages/) is the reference to mine, with the
[AUR](https://aur.archlinux.org/) as backup — for dependency sets, licenses and build flags,
never for structure.

**Leaves before roots.** A missing dependency — runtime or build-time — is a package in its own
right — built, verified
and committed before the thing that needs it. Never `--nodeps`, never a vendored copy — the
npm modules of a Node.js application being the one deliberate exception (`msys2-nodejs`). And
confirm a dependency really is missing before packaging it: MSYS2 often names it differently
from Arch.

**UCRT64 first.** Build, verify and commit one environment before touching another. Each rung
of the ladder — `clang64`, then `mingw32`, then `clangarm64` — introduces exactly one new
failure axis, so when a rung breaks you already know why.

**Patch the build system, not the artefacts.** A `package()` function that moves, renames or
deletes build output is a patch that was never written.

## Where these live

The skills sit in `.claude/skills/`, so in this repository they load with no setup at all:

- **Claude Code** reads `.claude/skills/<name>/SKILL.md` for the current project.
- **OpenCode** reads the same path as one of its compatibility locations.

**AiderDesk** looks elsewhere, and to use these skills in other repositories any tool needs its
own personal-scope copy. Copy the directories in, and re-copy after a `git pull`:

```bash
cp -r .claude/skills/msys2-* ~/.claude/skills/       # Claude Code, OpenCode
cp -r .claude/skills/msys2-* ~/.aider-desk/skills/   # AiderDesk
```

AiderDesk also needs skills tools enabled on the active agent profile.

Verify by asking the agent to list its available skills.

## Sources

Derived from the MSYS2 documentation —
[new-package](https://www.msys2.org/dev/new-package/),
[update-package](https://www.msys2.org/dev/update-package/),
[package-guidelines](https://www.msys2.org/dev/package-guidelines/),
[package-licensing](https://www.msys2.org/dev/package-licensing/),
[pkgbuild](https://www.msys2.org/dev/pkgbuild/),
[environments](https://www.msys2.org/docs/environments/) — plus a survey of 3364 PKGBUILDs and
2988 patch files in [msys2/MINGW-packages](https://github.com/msys2/MINGW-packages) and the
`makepkg-mingw` wrapper in [msys2/MSYS2-packages](https://github.com/msys2/MSYS2-packages).
Conventions stated as fact in these skills are backed by counts from that survey.
