"""Turn the PKGBUILDs in this repository into machine-readable metadata.

A PKGBUILD is bash, so the only trustworthy way to read one is to let bash do
it.  ``makepkg-mingw --printsrcinfo`` sources the PKGBUILD with the
``MINGW_PACKAGE_PREFIX`` and ``MINGW_PREFIX`` of a single environment and
prints a .SRCINFO.  Because those variables differ per environment, one
PKGBUILD yields one .SRCINFO *per environment* -- which is why everything here
is keyed on (package directory, environment).

Never parse a PKGBUILD with a regular expression.  ``mingw-w64-${_realname}``
does not mean anything until bash has expanded it.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from .config import DEFAULT_ENVIRONMENTS, ENVIRONMENTS


@dataclass
class SrcInfo:
    """The parts of a .SRCINFO that the build planner cares about."""

    directory: str
    """Package directory relative to the repository root; our package identity."""

    environment: str
    pkgbase: str
    pkgver: str
    pkgrel: str
    epoch: str = ""
    pkgnames: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    """Union of depends and makedepends over pkgbase and every split package.

    makepkg lets a split package override the base's depends; taking the union
    is deliberate.  We only use this to decide build *order*, and a package
    that any subpackage needs has to exist before the build starts.
    """

    validpgpkeys: list[str] = field(default_factory=list)

    @property
    def version(self) -> str:
        """pkgver-pkgrel, with the epoch prefixed the way makepkg writes it."""
        if self.epoch:
            return f"{self.epoch}:{self.pkgver}-{self.pkgrel}"
        return f"{self.pkgver}-{self.pkgrel}"

    def __str__(self) -> str:
        return f"{self.directory} {self.version} ({self.environment})"


def find_package_dirs(root: str) -> list[str]:
    """Every directory in `root` holding a PKGBUILD, sorted by name."""
    found = []
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        if os.path.isfile(os.path.join(root, name, "PKGBUILD")):
            found.append(name)
    return found


def read_environments(root: str, directory: str) -> list[str]:
    """Environments this package opts into, via a ``mingw_arch`` array.

    Per .claude/skills/msys2-environments the array records where a package has been
    *verified*, not where someone hopes it works, so CI treats it as binding:

    * no array         -> DEFAULT_ENVIRONMENTS (rung 0, ucrt64)
    * ``mingw_arch=()``-> nothing; verified nowhere, so built nowhere
    * a list           -> exactly that list
    """
    # The sentinel is what separates "no mingw_arch" (use the default) from
    # "mingw_arch=()" (verified nowhere, build nowhere). Both otherwise print
    # nothing useful.
    script = (
        'set -e; source ./PKGBUILD >/dev/null 2>&1; '
        'if declare -p mingw_arch >/dev/null 2>&1; then '
        'printf "@declared\\n"; printf "%s\\n" "${mingw_arch[@]}"; fi'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=os.path.join(root, directory),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Falling back to the defaults here would be the worst outcome: a
        # PKGBUILD that pins itself to one environment would silently be
        # queued for three.
        raise ValueError(
            f"bash could not read {directory}/PKGBUILD (exit {result.returncode})"
        )

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if "@declared" not in lines:
        return list(DEFAULT_ENVIRONMENTS)

    # dict.fromkeys de-duplicates while keeping the declared order.
    declared = list(dict.fromkeys(line for line in lines if line != "@declared"))

    unknown = [e for e in declared if e not in ENVIRONMENTS]
    if unknown:
        raise ValueError(
            f"{directory}/PKGBUILD declares unknown mingw_arch {unknown}; "
            f"known environments are {sorted(ENVIRONMENTS)}"
        )
    return declared


def parse(text: str, directory: str, environment: str) -> SrcInfo:
    """Parse .SRCINFO text.

    The format is a ``pkgbase`` block followed by one block per ``pkgname``.
    Keys in the base block apply to every split package unless a package
    overrides them; since we only take unions here, that distinction does not
    need to be modelled.
    """
    info = SrcInfo(directory=directory, environment=environment,
                   pkgbase="", pkgver="", pkgrel="")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        key, value = key.strip(), value.strip()
        if key == "pkgbase":
            info.pkgbase = value
        elif key == "pkgname":
            info.pkgnames.append(value)
        elif key == "pkgver":
            info.pkgver = value
        elif key == "pkgrel":
            info.pkgrel = value
        elif key == "epoch":
            info.epoch = value
        elif key == "provides":
            info.provides.append(_strip_constraint(value))
        elif key in ("depends", "makedepends"):
            info.depends.append(_strip_constraint(value))
        elif key == "validpgpkeys":
            info.validpgpkeys.append(value)

    if not info.pkgbase or not info.pkgver or not info.pkgrel:
        raise ValueError(f"{directory}: incomplete .SRCINFO for {environment}")
    if not info.pkgnames:
        info.pkgnames = [info.pkgbase]
    return info


def _strip_constraint(dep: str) -> str:
    """``foo>=1.2`` -> ``foo``.  Version constraints are irrelevant to ordering."""
    for separator in (">=", "<=", "==", "=", ">", "<"):
        if separator in dep:
            return dep.split(separator, 1)[0].strip()
    return dep.strip()


def load(root: str, directory: str, environment: str) -> SrcInfo:
    """Run makepkg-mingw --printsrcinfo for one package in one environment."""
    child_env = dict(os.environ)
    child_env["MINGW_ARCH"] = environment
    result = subprocess.run(
        ["makepkg-mingw", "--printsrcinfo", "-p", "PKGBUILD"],
        cwd=os.path.join(root, directory),
        env=child_env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"--printsrcinfo failed for {directory} ({environment}):\n{result.stderr}"
        )
    return parse(result.stdout, directory, environment)


def load_all(root: str, directories: list[str] | None = None) -> list[SrcInfo]:
    """Metadata for every (package, environment) pair this repository declares."""
    if directories is None:
        directories = find_package_dirs(root)
    infos = []
    for directory in directories:
        for environment in read_environments(root, directory):
            infos.append(load(root, directory, environment))
    return infos
