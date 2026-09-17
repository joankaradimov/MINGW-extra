"""Decide what to build, and in what order.

The output is a GitHub Actions matrix with one entry per environment, each
carrying an ordered list of package directories.  Ordering *inside* a job
rather than fanning out one job per package is not a compromise: a matrix
cannot express dependencies between its own entries, and packages in this
repository do depend on each other (sord needs serd, qjackctl needs jack2).
A job that walks its queue in topological order can hand each build the
packages the previous ones just produced, with no artifact plumbing at all.

The one dependency that does cross environments is a MinGW package needing an
MSYS one (alpmrpc needs alpmrpcd), and that is why msys is not in the matrix:
it gets a job of its own, which runs first, and the MinGW builds install what
it produced.
"""

from __future__ import annotations

import json
import os
import subprocess

from . import repodb, srcinfo
from .config import ENVIRONMENTS, MSYS
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


def unpublished(infos: list[SrcInfo], published: str | None) -> list[SrcInfo]:
    """Filter to the builds whose exact version is not on the server yet.

    `published` is the copy of the server's databases the ``databases`` job
    made; None treats nothing as published.

    A split PKGBUILD counts as published only when *every* binary package it
    produces is there.  Half an upload is not a build we can skip.
    """
    queue = []
    for environment in sorted({info.environment for info in infos}):
        database = repodb.published(published, environment)
        for info in infos:
            if info.environment != environment:
                continue
            missing = [n for n in info.pkgnames if not database.has(n, info.version)]
            if missing:
                queue.append(info)
    return queue


def with_dependencies(selected: list[SrcInfo], candidates: list[SrcInfo]) -> list[SrcInfo]:
    """`selected`, plus every package in `candidates` they need, transitively.

    Pull requests use this.  Their builds cannot install from the published
    repository -- only a job holding the deploy key can read it, and nothing a
    pull request can change may hold that key -- so whatever a changed package
    needs from this repository is built from source in the same run, ahead of
    it.  A dependency resolves in the package's own environment first, then in
    msys, whose packages any environment may depend on; anything no candidate
    provides is left to MSYS2's own repositories.
    """
    providers: dict[tuple[str, str], SrcInfo] = {}
    for info in candidates:
        for name in info.pkgnames + info.provides:
            providers.setdefault((info.environment, name), info)

    chosen = {(info.directory, info.environment): info for info in selected}
    pending = list(selected)
    while pending:
        info = pending.pop()
        for dependency in info.depends:
            provider = (providers.get((info.environment, dependency))
                        or providers.get((MSYS, dependency)))
            if provider is None:
                continue
            key = (provider.directory, provider.environment)
            if key not in chosen:
                chosen[key] = provider
                pending.append(provider)
    return list(chosen.values())


def order(infos: list[SrcInfo]) -> list[SrcInfo]:
    """Topologically sort one environment's queue, dependencies first.

    Only edges *within the queue* matter.  A dependency that is already
    published is not a build-order constraint, because the build job adds its
    copy of the published repository to pacman.conf and simply installs it.
    Neither is one on an msys package: that job has finished before this queue
    starts.
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
         only: list[str] | None = None,
         published: str | None = None) -> list[dict[str, str]]:
    """Every environment's queue, msys included, in build order."""
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

        everything = srcinfo.load_all(root)
        changed = [info for info in everything if info.directory in directories]
        # A pull request builds what it touched whether or not that version is
        # already published -- the point is to see the PKGBUILD compile, and a
        # fix that does not bump pkgrel would otherwise be silently skipped.
        queue = with_dependencies(changed, everything)
        added = sorted({info.directory for info in queue} - set(directories))
        if added:
            print(f"and what they need from this repository: {', '.join(added)}")
    else:
        infos = srcinfo.load_all(root, directories)
        queue = unpublished(infos, published)

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


def outputs(matrix: list[dict[str, str]]) -> dict[str, str]:
    """What the workflows need from a plan, as step outputs.

    * ``matrix``: the MinGW environments' entries, as JSON.
    * ``msys``: the msys queue, space-separated, or empty.  It is built by a
      job of its own before the matrix starts.
    * ``mirror``: the environments to copy published packages for, as JSON --
      every MinGW environment in the matrix, plus msys whenever anything at all
      is built, since any build may need an already-published msys package.
    """
    mingw = [entry for entry in matrix if entry["environment"] != MSYS]
    msys = next((entry["packages"] for entry in matrix if entry["environment"] == MSYS), "")
    mirror = [{"environment": entry["environment"]} for entry in mingw]
    if matrix:
        mirror.append({"environment": MSYS})
    return {
        "matrix": json.dumps(mingw, separators=(",", ":")),
        "msys": msys,
        "mirror": json.dumps(mirror, separators=(",", ":")),
    }


def report(matrix: list[dict[str, str]]) -> str:
    if not matrix:
        return "Nothing to build; every package is published at its current version."
    lines = ["| environment | packages (in build order) |", "| --- | --- |"]
    for entry in matrix:
        lines.append(f"| `{entry['environment']}` | {entry['packages']} |")
    return "\n".join(lines)


def main(args) -> int:
    root = os.path.abspath(args.root)
    matrix = plan(root, changed_since=args.changed_since,
                  only=args.package or None, published=args.published)

    print(report(matrix))
    values = outputs(matrix)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report(matrix) + "\n")
    if not output:
        for key, value in values.items():
            print(f"{key}={value}")
    return 0
