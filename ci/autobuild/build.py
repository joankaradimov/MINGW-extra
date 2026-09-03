"""Run makepkg for a queue of packages in one MSYS2 environment.

Three things here are less obvious than they look, and all three are borrowed
from msys2-autobuild because they are right:

* **The pacman config is a temporary copy.**  makepkg offers no ``--config``,
  but it honours ``$PACMAN``, so a two-line wrapper script that execs
  ``pacman --config <ours>`` gets a custom repository list into the build
  without touching ``/etc/pacman.conf``.  That matters most when you run this
  on your own machine.

* **CI variables are stripped before makepkg runs.**  ``build()`` executes
  arbitrary upstream code; ``GITHUB_TOKEN`` and friends have no business being
  visible to it.

* **Packages are built at a short path.**  Windows path limits are reached
  surprisingly quickly by ``$srcdir`` inside a deeply nested checkout, so each
  package is copied to ``<build root>/B`` first.

One failure does not abort the queue.  With thirteen packages, one broken
PKGBUILD blocking the other twelve would make every run useless -- so the
per-package error handling below is deliberately wide.
"""

from __future__ import annotations

import glob
import os
import shutil
import stat
import subprocess
import sys

from . import repodb, srcinfo
from .config import REMOTE_URL, db_name, db_url

MAKEPKG_FLAGS = [
    "--noconfirm",
    "--noprogressbar",
    "--nocheck",
    "--syncdeps",
    # --rmdeps costs a few reinstalls across a queue, and buys the guarantee
    # that a package cannot quietly build against something an earlier package
    # in the same job happened to pull in without declaring it.
    "--rmdeps",
    "--cleanbuild",
]

GPG_TIMEOUT = 60

# Anything a single package can throw that should fail only that package.
BUILD_FAILURES = (RuntimeError, OSError, shutil.Error, subprocess.SubprocessError)


class BuildError(RuntimeError):
    pass


def clean_environment() -> dict[str, str]:
    """A copy of the environment with every CI variable removed."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GITHUB_", "RUNNER_", "ACTIONS_"))
    }


def packager() -> str:
    """A PACKAGER string that points back at the run which produced the package."""
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if repository and run_id:
        return f"CI (https://github.com/{repository}/actions/runs/{run_id})"
    return "CI (MINGW-extra)"


def write_pacman_conf(path: str, environment: str, staging: str | None,
                      published: bool) -> None:
    """Write a pacman.conf with our repositories in front of the stock ones.

    Order is the whole point.  Packages built moments ago in this job come
    first, then whatever is already published, then MSYS2's own repositories.
    That is what lets sord find the serd this job built.

    `published` is False when the server has no database for this environment
    yet.  Listing a repository whose database 404s makes every subsequent
    ``pacman -Sy`` fail, which on a first run would take the whole queue down.
    """
    with open("/etc/pacman.conf", encoding="utf-8") as handle:
        stock = handle.read()

    sections = []
    if staging:
        sections.append(
            f"[{db_name(environment)}-staging]\n"
            f"Server = file://{staging}\n"
            "SigLevel = Never\n"
        )
    if published:
        sections.append(
            f"[{db_name(environment)}]\n"
            f"Server = {REMOTE_URL}/{environment}\n"
            "SigLevel = Optional TrustAll\n"
        )

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(sections) + "\n" + stock)


def write_pacman_wrapper(path: str, config: str) -> None:
    """makepkg has no --config, but it does respect $PACMAN."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f'#!/bin/bash\nset -e\nexec /usr/bin/pacman --config {config} "$@"\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IRUSR)


def receive_keys(info: srcinfo.SrcInfo) -> None:
    """Import any validpgpkeys so makepkg can verify signed sources.

    Never fatal: the key may already be in the keyring, and when it is genuinely
    missing makepkg reports that far more clearly than we could here.
    """
    for key in info.validpgpkeys:
        try:
            result = subprocess.run(
                ["gpg", "--keyserver", "keyserver.ubuntu.com", "--recv-keys", key],
                capture_output=True, text=True, timeout=GPG_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"warning: could not fetch {key}: {error}")
            continue
        if result.returncode != 0:
            print(f"warning: could not import {key}: {result.stderr.strip()}")


def stage(staging: str, environment: str, packages: list[str], config: str,
          published: bool) -> None:
    """Add freshly built packages to the local repository this job builds against.

    pacman resolves package files relative to the repository's Server URL, so
    the files have to sit next to the staging database; listing them in it from
    somewhere else yields "target not found" at install time.
    """
    staged = []
    for path in packages:
        copy = os.path.join(staging, os.path.basename(path))
        shutil.copy2(path, copy)
        staged.append(copy)

    database = os.path.join(staging, f"{db_name(environment)}-staging.db.tar.gz")
    subprocess.run(["repo-add", "--quiet", database] + staged, check=True)

    # The staging section can only be written once its database exists, so it
    # goes in here rather than before the build.
    write_pacman_conf(config, environment, staging, published)

    # -Syu rather than -Sy: refreshing databases without upgrading is how you
    # get a partial upgrade, and MSYS2 is unusually unforgiving about those.
    # A failure here is reported but not fatal -- if it left the staging
    # database stale, the next build says so precisely.
    result = subprocess.run(["/usr/bin/pacman", "--config", config, "-Syu", "--noconfirm"])
    if result.returncode != 0:
        print("warning: pacman -Syu reported an error; continuing")


def build_one(root: str, directory: str, environment: str, build_root: str,
              output: str, pacman: str) -> list[str]:
    """Build one package directory; return the paths of the files it produced."""
    info = srcinfo.load(root, directory, environment)
    print(f"::group::{directory} {info.version} ({environment})", flush=True)
    try:
        work = os.path.join(build_root, "B")
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(work):
            # rmtree with ignore_errors hides a locked file, and copytree would
            # then fail with something far less informative than this.
            raise BuildError(f"could not clear the build directory {work}")
        shutil.copytree(
            os.path.join(root, directory), work,
            ignore=shutil.ignore_patterns("src", "pkg", "*.pkg.tar.*", "*.src.tar.*"),
        )

        receive_keys(info)

        child = clean_environment()
        child["MINGW_ARCH"] = environment
        child["PACKAGER"] = packager()
        child["PACMAN"] = pacman
        child["CHERE_INVOKING"] = "1"

        result = subprocess.run(["makepkg-mingw"] + MAKEPKG_FLAGS, cwd=work, env=child)
        if result.returncode != 0:
            raise BuildError(f"makepkg failed for {directory} ({environment})")

        produced = sorted(glob.glob(os.path.join(work, "*.pkg.tar.zst")))
        expected = set(info.pkgnames)
        stamp = info.version.replace(":", "~")  # ':' is not legal in a filename
        got = {os.path.basename(p).rsplit(f"-{stamp}-", 1)[0] for p in produced}
        if not expected <= got:
            raise BuildError(
                f"{directory} ({environment}): expected {sorted(expected - got)} at "
                f"version {info.version}, got {sorted(os.path.basename(p) for p in produced)}"
            )

        destination = os.path.join(output, environment)
        os.makedirs(destination, exist_ok=True)
        moved = []
        for path in produced:
            target = os.path.join(destination, os.path.basename(path))
            shutil.move(path, target)
            moved.append(target)
        return moved
    finally:
        print("::endgroup::", flush=True)


def main(args) -> int:
    # makepkg writes straight to the step's stdout while Python block-buffers
    # into the same pipe; without this the ::group:: markers land nowhere near
    # the output they are supposed to fold.
    sys.stdout.reconfigure(line_buffering=True)

    root = os.path.abspath(args.root)
    environment = args.environment
    build_root = os.path.abspath(args.build_root)
    output = os.path.abspath(args.output)

    os.makedirs(build_root, exist_ok=True)
    os.makedirs(output, exist_ok=True)
    staging = os.path.join(build_root, "staging", environment)
    os.makedirs(staging, exist_ok=True)

    config = os.path.join(build_root, f"pacman-{environment}.conf")
    pacman = os.path.join(build_root, f"pacman-{environment}.sh")

    published = bool(REMOTE_URL) and len(repodb.fetch(db_url(environment))) > 0
    if REMOTE_URL and not published:
        print(f"note: nothing published for {environment} yet, "
              f"building against MSYS2's repositories alone")

    built: list[str] = []
    failed: list[str] = []
    staged = False
    for directory in args.packages:
        write_pacman_conf(config, environment, staging if staged else None, published)
        write_pacman_wrapper(pacman, config)
        try:
            produced = build_one(root, directory, environment, build_root, output, pacman)
            built.extend(produced)
            stage(staging, environment, produced, config, published)
            staged = True
        except BUILD_FAILURES as error:
            print(f"::error title={directory} ({environment})::{error}")
            failed.append(directory)
            continue

    print(f"\nbuilt {len(built)} package file(s) for {environment}")
    for path in built:
        print(f"  {os.path.basename(path)}")
    if failed:
        print(f"\nfailed: {', '.join(failed)}")
        return 1
    return 0
