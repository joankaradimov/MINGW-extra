"""Read the published pacman database, to tell what still needs building.

Making the published repository the source of truth is deliberate, and it is
the one idea worth taking wholesale from msys2-autobuild.  Deciding what to
build from a git diff means a build that crashed, or an upload that got lost,
is never retried and nobody finds out until a user reports a missing package.
Comparing PKGBUILD versions against what is actually on the server makes every
run idempotent and self-healing: re-running fixes things, and running twice
costs nothing.

A ``.db`` is a gzipped tar of ``<pkgname>-<version>/desc`` files, each a
sequence of ``%KEY%`` headers followed by their values.  Nothing else is
needed to answer "is this exact version published".
"""

from __future__ import annotations

import io
import tarfile
import time
import urllib.error
import urllib.request

FETCH_TIMEOUT = 30
FETCH_ATTEMPTS = 3


class Database:
    """Package name -> version, as currently published for one environment."""

    def __init__(self, versions: dict[str, str] | None = None) -> None:
        self._versions = versions or {}

    def __len__(self) -> int:
        return len(self._versions)

    def version_of(self, pkgname: str) -> str | None:
        return self._versions.get(pkgname)

    def has(self, pkgname: str, version: str) -> bool:
        """Whether exactly `version` of `pkgname` is published."""
        published = self._versions.get(pkgname)
        if published is None:
            return False
        return normalize_version(published) == normalize_version(version)


def normalize_version(version: str) -> str:
    """Make MSYS2's ``2~1.0-1`` and pacman's ``2:1.0-1`` compare equal.

    ``:`` is not legal in a Windows filename, so MSYS2 spells the epoch
    separator ``~``.  A bare ``~`` elsewhere in a version is legal and means
    something else entirely (``1.0~rc1`` sorts *before* ``1.0``), so only
    rewrite it when everything before it is digits -- which is exactly the
    shape an epoch has.
    """
    head, separator, tail = version.partition("~")
    if separator and head.isdigit():
        return f"{head}:{tail}"
    return version


def parse(data: bytes) -> Database:
    """Parse the bytes of a ``.db`` (or ``.files``) archive."""
    versions: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith("/desc"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            entry = _parse_desc(handle.read().decode("utf-8", "replace"))
            name, version = entry.get("NAME"), entry.get("VERSION")
            if name and version:
                versions[name] = version
    return Database(versions)


def _parse_desc(text: str) -> dict[str, str]:
    """Read the ``%KEY%``-then-values format, keeping only single-valued keys."""
    entry: dict[str, str] = {}
    key = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            key = None
        elif line.startswith("%") and line.endswith("%"):
            key = line.strip("%")
        elif key is not None and key not in entry:
            entry[key] = line
    return entry


def fetch(url: str | None) -> Database:
    """Download and parse a published database.

    A repository that does not exist yet is not an error -- it is the first
    run, and an empty database correctly means "build everything".
    """
    if not url:
        return Database()

    last_error: Exception | None = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
                return parse(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                print(f"note: {url} does not exist yet, treating it as empty")
                return Database()
            last_error = error
        except (urllib.error.URLError, OSError, tarfile.TarError) as error:
            last_error = error
        if attempt + 1 < FETCH_ATTEMPTS:
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"could not read {url}: {last_error}")
