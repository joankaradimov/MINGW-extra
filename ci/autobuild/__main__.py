"""Command line entry point: ``PYTHONPATH=ci python -m autobuild ...``

The subcommands are meant to be usable by hand from an MSYS2 shell, not only
from CI.  Reproducing what a failed job did should not require pushing a
commit:

    PYTHONPATH=ci python -m autobuild plan
    PYTHONPATH=ci python -m autobuild build --environment ucrt64 stormlib mpqcli
    PYTHONPATH=ci python -m autobuild build --environment msys alpmrpcd

With a copy of the server made by ``ci/fetch-published.sh``, ``--published``
makes both see exactly what CI sees.  ``registry-pull`` makes the copy pull
requests use, from the mirror on ghcr.io, and needs no key:

    PYTHONPATH=ci python -m autobuild registry-pull \
        --image ghcr.io/joankaradimov/mingw-extra --dest published
"""

from __future__ import annotations

import argparse
import os
import sys

from . import build, plan, registry, repodb
from .config import ENVIRONMENTS


def list_files(args) -> int:
    for name in repodb.published(args.published, args.environment).files():
        print(name)
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root", default=os.getcwd(),
        help="Repository root holding the package directories (default: cwd)")

    top = argparse.ArgumentParser(
        prog="autobuild", description="Build the MINGW-extra packages")
    subcommands = top.add_subparsers(dest="command", required=True)

    planner = subcommands.add_parser(
        "plan", parents=[common],
        help="Work out what needs building and print the workflow's outputs")
    planner.add_argument(
        "--changed-since", metavar="REF",
        help="Plan the packages touched since REF, and what they need from this "
             "repository, instead of comparing against the published repository. "
             "With --published, what they need is installed when it is published "
             "at its PKGBUILD's version, and built otherwise. Used for pull requests.")
    planner.add_argument(
        "-p", "--package", action="append", metavar="DIR",
        help="Restrict planning to this package directory (repeatable)")
    planner.add_argument(
        "--published", metavar="DIR",
        help="Copy of the published databases made by 'ci/fetch-published.sh "
             "databases'. Without it nothing counts as published.")
    planner.set_defaults(func=plan.main)

    builder = subcommands.add_parser(
        "build", parents=[common],
        help="Build packages for one environment, in the order given")
    builder.add_argument(
        "--environment", required=True, choices=sorted(ENVIRONMENTS),
        help="MSYS2 environment to build for")
    builder.add_argument(
        "--build-root", default=os.environ.get("BUILD_ROOT", "/tmp/mingw-extra"),
        help="Short scratch path to build under; Windows path limits are real")
    builder.add_argument(
        "--output", default="artifacts",
        help="Directory to collect built packages in, one subdirectory per environment")
    builder.add_argument(
        "--published", action="append", metavar="DIR",
        help="Copy of the published repository, databases and packages, made by "
             "ci/fetch-published.sh; already-published dependencies are "
             "installed from it (repeatable: this environment's and msys's)")
    builder.add_argument(
        "--prebuilt", action="append", metavar="DIR",
        help="Packages an earlier job of the same run built, as "
             "DIR/<environment>/*.pkg.tar.zst, to install from ahead of the "
             "published ones (repeatable). The MinGW builds get the msys job's "
             "output this way.")
    builder.add_argument("packages", nargs="+", metavar="DIR")
    builder.set_defaults(func=build.main)

    lister = subcommands.add_parser(
        "files", help="List the package files a published database references")
    lister.add_argument(
        "--published", required=True, metavar="DIR",
        help="Copy of the published databases made by 'ci/fetch-published.sh databases'")
    lister.add_argument(
        "--environment", required=True, choices=sorted(ENVIRONMENTS),
        help="MSYS2 environment whose database to read")
    lister.set_defaults(func=list_files)

    image = argparse.ArgumentParser(add_help=False)
    image.add_argument(
        "--image", required=True, metavar="REGISTRY/NAME",
        help="The mirror's image, e.g. ghcr.io/joankaradimov/mingw-extra")

    missing = subcommands.add_parser(
        "registry-missing", parents=[image],
        help="List the package files of an environment that the mirror lacks. "
             "Reads REGISTRY_USER and REGISTRY_TOKEN; anonymous without them")
    missing.add_argument(
        "--published", required=True, metavar="DIR",
        help="Copy of the published databases made by 'ci/fetch-published.sh databases'")
    missing.add_argument(
        "--environment", required=True, choices=sorted(ENVIRONMENTS))
    missing.set_defaults(func=registry.main_missing)

    pusher = subcommands.add_parser(
        "registry-push", parents=[image],
        help="Mirror an environment of the published repository to the registry. "
             "Reads REGISTRY_USER and REGISTRY_TOKEN")
    pusher.add_argument(
        "--published", required=True, metavar="DIR",
        help="Copy of the published repository holding the database and every "
             "package file registry-missing listed")
    pusher.add_argument(
        "--environment", required=True, choices=sorted(ENVIRONMENTS))
    pusher.add_argument(
        "--source", required=True, metavar="URL",
        help="The repository the image belongs to; ghcr.io links the package to it")
    pusher.set_defaults(func=registry.main_push)

    puller = subcommands.add_parser(
        "registry-pull", parents=[image],
        help="Copy the published repository from the mirror, anonymously. Leaves "
             "no copy, and says so, when the image cannot be read")
    puller.add_argument(
        "--dest", required=True, metavar="DIR",
        help="Where to put the copy, laid out as ci/fetch-published.sh would")
    puller.add_argument(
        "--environment", action="append", choices=sorted(ENVIRONMENTS),
        help="Environment to copy (repeatable; default: every one)")
    puller.add_argument(
        "--databases-only", action="store_true",
        help="Copy the databases alone, as for planning")
    puller.set_defaults(func=registry.main_pull)

    return top


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
