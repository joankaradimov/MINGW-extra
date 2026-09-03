"""Decide what to build, and in what order.

The output is a GitHub Actions matrix with one entry per environment, each
carrying an ordered list of package directories.  Ordering *inside* a job
rather than fanning out one job per package is not a compromise: a matrix
cannot express dependencies between its own entries, and packages in this
repository do depend on each other (sord needs serd, qjackctl needs jack2).
A job that walks its queue in topological order can hand each build the
packages the previous ones just produced, with no artifact plumbing at all.
"""

from __future__ import annotations

import json
import os
import subprocess

from . import repodb, srcinfo
from .config import ENVIRONMENTS, db_url
from .srcinfo import SrcInfo


def changed_directories(root: str, ref: str) -> list[str]:
    """Package directories touched since `ref`."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    packages = set(srcinfo.find_package_dirs(root))
    touched = {path.split("/", 1)[0] for path in result.stdout.splitlines() if path.strip()}
    return sorted(touched & packages)


def unpublished(infos: list[SrcInfo]) -> list[SrcInfo]:
    """Filter to the builds whose exact version is not on the server yet.

    A split PKGBUILD counts as published only when *every* binary package it
    produces is there.  Half an upload is not a build we can skip.
    """
    queue = []
    for environment in sorted({info.environment for info in infos}):
        database = repodb.fetch(db_url(environment))
        for info in infos:
            if info.environment != environment:
                continue
            missing = [n for n in info.pkgnames if not database.has(n, info.version)]
            if missing:
                queue.append(info)
    return queue


def order(infos: list[SrcInfo]) -> list[SrcInfo]:
    """Topologically sort one environment's queue, dependencies first.

    Only edges *within the queue* matter.  A dependency that is already
    published is not a build-order constraint, because the build job adds the
    published repository to pacman.conf and simply installs it.
    """
    provider: dict[str, str] = {}
    for info in infos:
        for name in info.pkgnames + info.provides:
            provider[name] = info.directory

    by_directory = {info.directory: info for info in infos}
    edges = {
        info.directory: {
            provider[dep]
            for dep in info.depends
            if dep in provider and provider[dep] != info.directory
        }
        for info in infos
    }

    ordered: list[SrcInfo] = []
    done: set[str] = set()
    while len(done) < len(edges):
        ready = sorted(d for d in edges if d not in done and edges[d] <= done)
        if not ready:
            stuck = sorted(d for d in edges if d not in done)
            raise ValueError(f"dependency cycle among {stuck}")
        for directory in ready:
            ordered.append(by_directory[directory])
            done.add(directory)
    return ordered


def plan(root: str, changed_since: str | None = None,
         only: list[str] | None = None) -> list[dict[str, str]]:
    """Build a GitHub Actions matrix describing everything that needs building."""
    directories = only
    if directories:
        known = set(srcinfo.find_package_dirs(root))
        unknown = sorted(set(directories) - known)
        if unknown:
            raise ValueError(f"no such package directory: {', '.join(unknown)}")
    if changed_since is not None:
        directories = changed_directories(root, changed_since)
        if not directories:
            print("no package directories changed")
            return []
        print(f"changed since {changed_since}: {', '.join(directories)}")

    infos = srcinfo.load_all(root, directories)

    # A pull request builds what it touched whether or not that version is
    # already published -- the point is to see the PKGBUILD compile, and a fix
    # that does not bump pkgrel would otherwise be silently skipped.
    queue = infos if changed_since is not None else unpublished(infos)

    matrix = []
    for name in ENVIRONMENTS:
        for_environment = [info for info in queue if info.environment == name]
        if not for_environment:
            continue
        ordered = order(for_environment)
        matrix.append({
            "environment": name,
            "msystem": ENVIRONMENTS[name].msystem,
            "runner": ENVIRONMENTS[name].runner,
            "packages": " ".join(info.directory for info in ordered),
        })
    return matrix


def report(matrix: list[dict[str, str]]) -> str:
    if not matrix:
        return "Nothing to build; every package is published at its current version."
    lines = ["| environment | packages (in build order) |", "| --- | --- |"]
    for entry in matrix:
        lines.append(f"| `{entry['environment']}` | {entry['packages']} |")
    return "\n".join(lines)


def main(args) -> int:
    root = os.path.abspath(args.root)
    matrix = plan(root, changed_since=args.changed_since, only=args.package or None)

    print(report(matrix))
    encoded = json.dumps(matrix, separators=(",", ":"))

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"matrix={encoded}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report(matrix) + "\n")
    if not output:
        print(encoded)
    return 0
