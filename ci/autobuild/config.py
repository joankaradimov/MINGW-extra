"""Static configuration for the MINGW-extra autobuilder.

Everything that is specific to this repository -- which MSYS2 environments we
target, what the published pacman repository is called, and how a copy of it is
laid out -- is collected here so the rest of the code stays generic.  Where the
repository lives is not: that is in the deploy secrets, and only the jobs that
talk to the host know it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

REPO_NAME = "mingw-extra"
"""pacman repository name.

Each environment gets its own database, so the pacman.conf section for e.g.
ucrt64 is ``[mingw-extra-ucrt64]`` and its database is
``<repository>/ucrt64/mingw-extra-ucrt64.db``.
"""

PUBLISHED_MARKER = "COMPLETE"
"""File ``ci/fetch-published.sh`` writes into its copy once rsync has succeeded.

Must match ``marker`` in that script.  ``repodb.published`` explains why a copy
without it is refused.
"""


@dataclass(frozen=True)
class Environment:
    name: str
    """The MSYS2 environment name, as used by MINGW_ARCH and in repo paths."""

    msystem: str
    """Value for the MSYSTEM environment variable."""

    prefix: str
    """Value MINGW_PACKAGE_PREFIX expands to, i.e. the binary package prefix."""

    runner: str
    """GitHub Actions runner label able to build this environment."""


ENVIRONMENTS: dict[str, Environment] = {
    e.name: e
    for e in [
        Environment("ucrt64", "UCRT64", "mingw-w64-ucrt-x86_64", "windows-2022"),
        Environment("clang64", "CLANG64", "mingw-w64-clang-x86_64", "windows-2022"),
        Environment("mingw32", "MINGW32", "mingw-w64-i686", "windows-2022"),
        # Not a rung of the ladder, but MSYS2 still ships it, and a package that
        # verified itself there (the DJGPP cross-toolchain) must not break the plan.
        Environment("mingw64", "MINGW64", "mingw-w64-x86_64", "windows-2022"),
        Environment("clangarm64", "CLANGARM64", "mingw-w64-clang-aarch64", "windows-11-arm"),
    ]
}

DEFAULT_ENVIRONMENTS = ["ucrt64"]
"""Environments a PKGBUILD is built for when it declares no ``mingw_arch``.

Rung 0 of the ladder in .claude/skills/msys2-environments, and only rung 0. That skill
is explicit that ``mingw_arch`` records the environments a package has actually
been verified in, and that "an unverified entry is worse than an absent one" --
so CI must not infer environments a package never claimed. A package climbs the
ladder by adding a rung to its ``mingw_arch`` in a pull request, which is
exactly what the PR workflow then builds and proves.

An explicitly empty ``mingw_arch=()`` means the opposite of absent: verified
nowhere, build nowhere.
"""


def db_name(env: str) -> str:
    """Name of the pacman database (and of the pacman.conf section) for `env`."""
    return f"{REPO_NAME}-{env}"


def db_path(directory: str, env: str) -> str:
    """Where a copy of the published repository keeps the database for `env`."""
    return os.path.join(directory, env, f"{db_name(env)}.db")
