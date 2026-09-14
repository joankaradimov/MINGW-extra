"""Command line entry point: ``PYTHONPATH=ci python -m autobuild ...``

The subcommands are meant to be usable by hand from an MSYS2 shell, not only
from CI.  Reproducing what a failed job did should not require pushing a
commit:

    PYTHONPATH=ci python -m autobuild plan
    PYTHONPATH=ci python -m autobuild build --environment ucrt64 serd sord

With a copy of the server made by ``ci/fetch-published.sh``, ``--published``
makes both see exactly what CI sees.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import build, plan, repodb
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
        help="Work out what needs building and print a GitHub Actions matrix")
    planner.add_argument(
        "--changed-since", metavar="REF",
        help="Plan the packages touched since REF, and what they need from this "
             "repository, instead of comparing against the published repository. "
             "Used for pull requests.")
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
        "--published", metavar="DIR",
        help="Copy of the published repository, databases and packages, made by "
             "ci/fetch-published.sh; already-published dependencies are "
             "installed from it")
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

    return top


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
