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
from .config import ENVIRONMENTS, MSYS, db_name

PACMAN = "/usr/bin/pacman"

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
    """A PACKAGER that points back at the run which produced the package.

    makepkg warns about anything but ``Name <...>`` -- pacman looks between the
    brackets for an address -- and accepts anything there except more
    brackets, so the run's URL goes inside them.
    """
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if repository and run_id:
        return f"MINGW-extra CI <https://github.com/{repository}/actions/runs/{run_id}>"
    return "MINGW-extra CI <local build>"


def local_repositories(environment: str, staging_root: str,
                       published: list[str]) -> list[tuple[str, str, str]]:
    """The file:// repositories a build installs from, highest priority first.

    Each entry is (pacman.conf section, directory, SigLevel).  Packages built
    earlier in this run come first -- by this job, or for msys by the job before
    it -- then what is already published; MSYS2's own repositories follow in
    the stock configuration.  That order is what lets sord find the serd this
    job built.

    msys sits next to every MinGW environment, because a MinGW package may
    depend on an MSYS one from this repository, as alpmrpc does on alpmrpcd.

    `published` lists copies made by ``ci/fetch-published.sh``; the first one
    holding an environment's database is used for it.  A repository only
    appears once its database exists: listing one that has none makes pacman
    refuse every transaction, which on a first run would take the whole queue
    down.
    """
    environments = [environment] if environment == MSYS else [environment, MSYS]
    repositories = []
    for env in environments:
        staging = os.path.join(staging_root, env)
        if os.path.isfile(os.path.join(staging, f"{db_name(env)}-staging.db.tar.gz")):
            repositories.append((f"{db_name(env)}-staging", staging, "Never"))
    for env in environments:
        for copy in published:
            if len(repodb.published(copy, env)):
                repositories.append(
                    (db_name(env), os.path.abspath(os.path.join(copy, env)), "Optional TrustAll"))
                break
    return repositories


def write_pacman_conf(path: str, repositories: list[tuple[str, str, str]],
                      stock: str = "/etc/pacman.conf") -> None:
    """Write a pacman.conf with `repositories` in front of the stock ones."""
    with open(stock, encoding="utf-8") as handle:
        stock_conf = handle.read()

    sections = [
        f"[{name}]\nServer = file://{directory}\nSigLevel = {siglevel}\n"
        for name, directory, siglevel in repositories
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(sections) + "\n" + stock_conf)


def write_pacman_wrapper(path: str, config: str) -> None:
    """makepkg has no --config, but it does respect $PACMAN."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f'#!/bin/bash\nset -e\nexec {PACMAN} --config {config} "$@"\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IRUSR)


def sync(config: str) -> bool:
    """Refresh every database `config` lists; whether pacman succeeded.

    makepkg installs dependencies through this configuration without ever
    refreshing it, so pacman has to have read a repository's database before a
    build can install from it -- a listed repository whose database it never
    fetched makes it refuse the whole transaction.

    -Syu rather than -Sy: refreshing databases without upgrading is how you get
    a partial upgrade, and MSYS2 is unusually unforgiving about those.
    """
    return subprocess.run([PACMAN, "--config", config, "-Syu", "--noconfirm"]).returncode == 0


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


def stage(staging: str, environment: str, packages: list[str]) -> None:
    """Add packages to a local staging repository.

    pacman resolves package files relative to the repository's Server URL, so
    the files have to sit next to the staging database; listing them in it from
    somewhere else yields "target not found" at install time.
    """
    os.makedirs(staging, exist_ok=True)
    staged = []
    for path in packages:
        copy = os.path.join(staging, os.path.basename(path))
        shutil.copy2(path, copy)
        staged.append(copy)

    database = os.path.join(staging, f"{db_name(environment)}-staging.db.tar.gz")
    subprocess.run(["repo-add", "--quiet", database] + staged, check=True)


def stage_prebuilt(prebuilt: list[str], environment: str, staging_root: str) -> None:
    """Stage what earlier jobs of this run built for other environments.

    Each directory holds ``<environment>/*.pkg.tar.zst``, the layout every
    build job uploads.  For a MinGW build that is the msys job's output.
    """
    for directory in prebuilt:
        for env in sorted(ENVIRONMENTS):
            if env == environment:
                continue
            packages = sorted(glob.glob(os.path.join(directory, env, "*.pkg.tar.zst")))
            if packages:
                stage(os.path.join(staging_root, env), env, packages)
                print(f"note: {len(packages)} {env} package file(s) built earlier "
                      f"in this run are available")


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

        child = srcinfo.makepkg_environment(environment, clean_environment())
        child["PACKAGER"] = packager()
        child["PACMAN"] = pacman
        child["CHERE_INVOKING"] = "1"

        makepkg = ENVIRONMENTS[environment].makepkg
        result = subprocess.run([makepkg] + MAKEPKG_FLAGS, cwd=work, env=child)
        if result.returncode != 0:
            raise BuildError(f"{makepkg} failed for {directory} ({environment})")

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
    staging_root = os.path.join(build_root, "staging")
    # Already-published dependencies are installed from local copies that the
    # mirror jobs made over SSH, never over HTTP -- repodb explains why.
    published = [os.path.abspath(copy) for copy in (args.published or [])]

    os.makedirs(build_root, exist_ok=True)
    os.makedirs(output, exist_ok=True)

    config = os.path.join(build_root, f"pacman-{environment}.conf")
    pacman = os.path.join(build_root, f"pacman-{environment}.sh")
    write_pacman_wrapper(pacman, config)

    stage_prebuilt(args.prebuilt or [], environment, staging_root)

    repositories = local_repositories(environment, staging_root, published)
    write_pacman_conf(config, repositories)
    if not any(name == db_name(environment) for name, _, _ in repositories):
        print(f"note: nothing published for {environment} yet")
    if repositories and not sync(config):
        print(f"::error title=pacman ({environment})::could not read the local "
              f"repositories: {', '.join(name for name, _, _ in repositories)}")
        return 1

    built: list[str] = []
    failed: list[str] = []
    for directory in args.packages:
        try:
            produced = build_one(root, directory, environment, build_root, output, pacman)
            built.extend(produced)
            stage(os.path.join(staging_root, environment), environment, produced)
        except BUILD_FAILURES as error:
            print(f"::error title={directory} ({environment})::{error}")
            failed.append(directory)
            continue

        # The staging section only exists once its database does, so the
        # configuration is rewritten after the first success. A failed refresh
        # is reported but not fatal: if it left the staging database stale, the
        # next build says so precisely.
        write_pacman_conf(config, local_repositories(environment, staging_root, published))
        if not sync(config):
            print("warning: pacman -Syu reported an error; continuing")

    print(f"\nbuilt {len(built)} package file(s) for {environment}")
    for path in built:
        print(f"  {os.path.basename(path)}")
    if failed:
        print(f"\nfailed: {', '.join(failed)}")
        return 1
    return 0
