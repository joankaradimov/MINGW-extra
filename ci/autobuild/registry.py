"""The published repository, mirrored to GitHub's container registry.

Pull requests cannot read the published repository on the host: its bot
protection answers cloud addresses with a CAPTCHA, and the deploy key that gets
around it must not reach a job a pull request can change.  So after
publishing, a job holding the key copies every environment's database and
package files to ghcr.io, as an OCI artifact tagged with the environment's
name, and pull requests download them from there anonymously -- into the
layout ``ci/fetch-published.sh`` produces, so everything downstream reads them
the same way.

An artifact is a manifest listing content-addressed blobs: the database, then
the package files, each carrying its filename in the
``org.opencontainers.image.title`` annotation.  A blob the registry already
holds is not uploaded again, and the database gives every package file's
digest (%SHA256SUM%), so finding out what a publish has to upload fetches
nothing from the host.  The manifest has no timestamps: an unchanged
environment produces the same manifest, and is not pushed again.

The package has to be public for anonymous pulls.  Until it is, a pull says so
and leaves no copy, and pull requests build their dependencies from source.

Only the standard library is used, so this runs on an ubuntu runner and in an
MSYS2 shell alike.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import repodb
from .config import ENVIRONMENTS, PUBLISHED_MARKER, db_name, db_path

MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
CONFIG_TYPE = "application/vnd.mingw-extra.repository.config.v1+json"
DATABASE_TYPE = "application/vnd.mingw-extra.pacman.database"
PACKAGE_TYPE = "application/vnd.mingw-extra.pacman.package"
TITLE = "org.opencontainers.image.title"
SOURCE = "org.opencontainers.image.source"
DESCRIPTION = "org.opencontainers.image.description"

TIMEOUT = 600
CHUNK = 1 << 20


class Unavailable(Exception):
    """The registry will not let us read the image: not public, or not there."""


@dataclass(frozen=True)
class Blob:
    filename: str
    digest: str
    """``sha256:<hex>``"""
    size: int
    media_type: str


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def blobs(copy: str, environment: str) -> list[Blob]:
    """What `environment`'s artifact holds: its database, then every package file
    the database references, sorted by filename."""
    path = db_path(copy, environment)
    with open(path, "rb") as handle:
        data = handle.read()
    result = [Blob(os.path.basename(path), sha256_digest(data), len(data), DATABASE_TYPE)]
    for entry in repodb.parse(data).package_files():
        if not entry.sha256 or entry.size is None:
            raise RuntimeError(f"{path} gives no checksum or size for {entry.filename}")
        result.append(Blob(entry.filename, f"sha256:{entry.sha256}", entry.size, PACKAGE_TYPE))
    return result


def config(environment: str) -> bytes:
    return json.dumps({"environment": environment}, sort_keys=True).encode()


def manifest(environment: str, contents: list[Blob], source: str) -> bytes:
    """The artifact's manifest: deterministic, so an unchanged environment
    gives byte for byte the same one."""
    configuration = config(environment)
    document = {
        "schemaVersion": 2,
        "mediaType": MANIFEST_TYPE,
        "config": {
            "mediaType": CONFIG_TYPE,
            "digest": sha256_digest(configuration),
            "size": len(configuration),
        },
        "layers": [
            {
                "mediaType": blob.media_type,
                "digest": blob.digest,
                "size": blob.size,
                "annotations": {TITLE: blob.filename},
            }
            for blob in contents
        ],
        "annotations": {
            SOURCE: source,
            DESCRIPTION: f"The {db_name(environment)} pacman repository",
        },
    }
    return json.dumps(document, indent=2, sort_keys=True).encode()


class _KeepMethod(urllib.request.HTTPRedirectHandler):
    """Follow a HEAD's redirect with a HEAD, not the GET urllib turns it into."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and req.get_method() == "HEAD":
            new.method = "HEAD"
        return new


_opener = urllib.request.build_opener(_KeepMethod)


class Registry:
    """The parts of the OCI distribution API this needs, for one image.

    The bearer token goes in an unredirected header: ghcr.io answers a blob
    download with a redirect to storage elsewhere, and that host must not get
    our token -- signed storage URLs reject a request that carries one.
    """

    def __init__(self, image: str, token: str | None = None) -> None:
        host, _, name = image.partition("/")
        if not host or not name:
            raise ValueError(f"not a registry image: {image}")
        self.base = f"https://{host}"
        self.name = name.lower()
        self.token = token

    @classmethod
    def login(cls, image: str, push: bool = False,
              user: str | None = None, password: str | None = None) -> "Registry":
        """A client with a bearer token; anonymous without `password`."""
        registry = cls(image)
        actions = "pull,push" if push else "pull"
        registry.token = registry._bearer(f"repository:{registry.name}:{actions}", user, password)
        return registry

    def _bearer(self, scope: str, user: str | None, password: str | None) -> str:
        # The registry names its token service in the challenge to an
        # unauthenticated request.
        try:
            with _opener.open(urllib.request.Request(f"{self.base}/v2/"), timeout=TIMEOUT):
                pass
            raise RuntimeError(f"{self.base} asked for no authentication")
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
            challenge = error.headers.get("WWW-Authenticate", "")
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        if "realm" not in fields:
            raise RuntimeError(f"unexpected authentication challenge: {challenge!r}")
        query = {"scope": scope}
        if "service" in fields:
            query["service"] = fields["service"]
        request = urllib.request.Request(f"{fields['realm']}?{urllib.parse.urlencode(query)}")
        if password:
            credentials = base64.b64encode(f"{user or 'token'}:{password}".encode()).decode()
            request.add_unredirected_header("Authorization", f"Basic {credentials}")
        try:
            with _opener.open(request, timeout=TIMEOUT) as response:
                return json.load(response)["token"]
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise Unavailable(f"{self.base}/{self.name}: {error.code} {error.reason}") from None
            raise

    def _request(self, method: str, path: str, data=None,
                 headers: dict[str, str] | None = None):
        url = path if path.startswith("https://") else f"{self.base}{path}"
        request = urllib.request.Request(url, data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if self.token:
            request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        return _opener.open(request, timeout=TIMEOUT)

    def _status(self, method: str, path: str, headers: dict[str, str] | None = None):
        """The response's headers, or None for a 404; 401 and 403 are Unavailable."""
        try:
            with self._request(method, path, headers=headers) as response:
                return response.headers
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (401, 403):
                raise Unavailable(f"{self.base}/{self.name}: {error.code} {error.reason}") from None
            raise

    def has_blob(self, digest: str) -> bool:
        return self._status("HEAD", f"/v2/{self.name}/blobs/{digest}") is not None

    def put_blob(self, digest: str, size: int, data) -> None:
        """Upload in one request; `data` is bytes or a binary file."""
        with self._request("POST", f"/v2/{self.name}/blobs/uploads/", data=b"") as response:
            location = response.headers["Location"]
        url = urllib.parse.urljoin(f"{self.base}/", location)
        separator = "&" if "?" in url else "?"
        headers = {"Content-Type": "application/octet-stream", "Content-Length": str(size)}
        with self._request("PUT", f"{url}{separator}digest={urllib.parse.quote(digest)}",
                           data=data, headers=headers):
            pass

    def manifest_digest(self, tag: str) -> str | None:
        found = self._status("HEAD", f"/v2/{self.name}/manifests/{tag}",
                             {"Accept": MANIFEST_TYPE})
        return None if found is None else found.get("Docker-Content-Digest")

    def get_manifest(self, tag: str) -> dict | None:
        try:
            with self._request("GET", f"/v2/{self.name}/manifests/{tag}",
                               headers={"Accept": MANIFEST_TYPE}) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (401, 403):
                raise Unavailable(f"{self.base}/{self.name}: {error.code} {error.reason}") from None
            raise

    def put_manifest(self, tag: str, data: bytes) -> None:
        with self._request("PUT", f"/v2/{self.name}/manifests/{tag}", data=data,
                           headers={"Content-Type": MANIFEST_TYPE}):
            pass

    def get_blob(self, digest: str, path: str) -> None:
        """Download a blob to `path`, checking it against its digest."""
        algorithm, _, expected = digest.partition(":")
        if algorithm != "sha256":
            raise RuntimeError(f"unsupported digest {digest}")
        check = hashlib.sha256()
        partial = f"{path}.part"
        with self._request("GET", f"/v2/{self.name}/blobs/{digest}") as response, \
                open(partial, "wb") as handle:
            while chunk := response.read(CHUNK):
                check.update(chunk)
                handle.write(chunk)
        if check.hexdigest() != expected:
            os.remove(partial)
            raise RuntimeError(f"{os.path.basename(path)} does not match {digest}")
        os.replace(partial, path)


def missing(registry: Registry, copy: str, environment: str) -> list[str]:
    """The package files of `environment` whose blobs the registry lacks."""
    return [blob.filename for blob in blobs(copy, environment)[1:]
            if not registry.has_blob(blob.digest)]


def push(registry: Registry, copy: str, environment: str, source: str) -> bool:
    """Mirror `environment` from `copy`: upload what the registry lacks, then tag
    the manifest.  Package files to upload must be in the copy, next to the
    database (``missing`` says which).  Returns whether the tag moved."""
    contents = blobs(copy, environment)
    directory = os.path.dirname(db_path(copy, environment))
    for blob in contents:
        if registry.has_blob(blob.digest):
            continue
        path = os.path.join(directory, blob.filename)
        print(f"uploading {blob.filename} ({blob.size} bytes)")
        with open(path, "rb") as handle:
            registry.put_blob(blob.digest, blob.size, handle)
    configuration = config(environment)
    digest = sha256_digest(configuration)
    if not registry.has_blob(digest):
        registry.put_blob(digest, len(configuration), configuration)
    document = manifest(environment, contents, source)
    if registry.manifest_digest(environment) == sha256_digest(document):
        print(f"{environment}: unchanged")
        return False
    registry.put_manifest(environment, document)
    print(f"{environment}: tagged {sha256_digest(document)}")
    return True


def _safe_filename(name: str) -> str:
    if not name or name in (".", "..") or os.path.basename(name) != name or "\\" in name:
        raise RuntimeError(f"refusing a file named {name!r}")
    return name


def pull(registry: Registry, environments: list[str], dest: str,
         packages: bool = True) -> list[str]:
    """Copy `environments` from the registry into `dest`, in the layout
    ci/fetch-published.sh produces, and mark the copy complete.  Without
    `packages`, only the databases.  Returns the environments found; one never
    published has no tag, and is left out, as the SSH copy would leave it."""
    found = []
    marker = os.path.join(dest, PUBLISHED_MARKER)
    if os.path.exists(marker):
        os.remove(marker)
    for environment in environments:
        document = registry.get_manifest(environment)
        if document is None:
            continue
        directory = os.path.dirname(db_path(dest, environment))
        os.makedirs(directory, exist_ok=True)
        for layer in document.get("layers", []):
            if layer.get("mediaType") == PACKAGE_TYPE and not packages:
                continue
            filename = _safe_filename(layer.get("annotations", {}).get(TITLE, ""))
            path = os.path.join(directory, filename)
            if os.path.isfile(path) and _matches(path, layer["digest"]):
                continue
            registry.get_blob(layer["digest"], path)
        if not os.path.isfile(db_path(dest, environment)):
            raise RuntimeError(f"the {environment} artifact has no {db_name(environment)}.db")
        found.append(environment)
    with open(marker, "w", encoding="utf-8"):
        pass
    return found


def _matches(path: str, digest: str) -> bool:
    check = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            check.update(chunk)
    return digest == f"sha256:{check.hexdigest()}"


def _credentials() -> tuple[str | None, str | None]:
    return os.environ.get("REGISTRY_USER"), os.environ.get("REGISTRY_TOKEN")


def main_missing(args) -> int:
    user, password = _credentials()
    # With credentials, the scope registry-push will use: before the first push
    # there is no package, and only that scope may look into it.
    registry = Registry.login(args.image, push=bool(password), user=user, password=password)
    for name in missing(registry, args.published, args.environment):
        print(name)
    return 0


def main_push(args) -> int:
    user, password = _credentials()
    if not password:
        raise SystemExit("registry-push needs REGISTRY_TOKEN (and REGISTRY_USER)")
    registry = Registry.login(args.image, push=True, user=user, password=password)
    push(registry, args.published, args.environment, args.source)
    return 0


def main_pull(args) -> int:
    environments = args.environment or sorted(ENVIRONMENTS)
    try:
        registry = Registry.login(args.image)
        found = pull(registry, environments, args.dest, packages=not args.databases_only)
    except Unavailable as error:
        # Not public yet, or never pushed: the caller builds without a copy.
        print(f"::notice::{args.image} cannot be read anonymously ({error}); "
              f"continuing without a copy of the published repository")
        return 0
    print(f"copied {', '.join(found) if found else 'nothing'} from {args.image}")
    return 0
