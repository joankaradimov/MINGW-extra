"""Tests for the parts of the autobuilder that do not need MSYS2.

Run from the repository root:

    PYTHONPATH=ci python -m unittest discover -s ci -v

Everything here is pure logic -- parsing, version comparison, build ordering --
which is exactly where a mistake would be quiet. A bad topological sort does
not crash, it just builds sord before serd and fails hours later on a runner.
"""

from __future__ import annotations

import contextlib
import gzip
import http.server
import io
import os
import tarfile
import threading
import unittest

from autobuild import plan, repodb, srcinfo
from autobuild.srcinfo import SrcInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SPLIT_SRCINFO = """
pkgbase = mingw-w64-bitcoin
\tpkgver = 0.21.0
\tpkgrel = 1
\tepoch = 2
\turl = https://www.bitcoin.org/
\tmakedepends = mingw-w64-i686-boost>=1.70
\tmakedepends = mingw-w64-i686-qt5
\tvalidpgpkeys = ABCDEF0123456789

pkgname = mingw-w64-i686-bitcoin-cli
\tdepends = mingw-w64-i686-libevent

pkgname = mingw-w64-i686-bitcoin-qt
\tdepends = mingw-w64-i686-qt5
\tprovides = bitcoin-gui
"""


class SrcInfoParsing(unittest.TestCase):

    def setUp(self):
        self.info = srcinfo.parse(SPLIT_SRCINFO, "bitcoin", "mingw32")

    def test_split_packages_are_all_collected(self):
        self.assertEqual(
            self.info.pkgnames,
            ["mingw-w64-i686-bitcoin-cli", "mingw-w64-i686-bitcoin-qt"])

    def test_epoch_uses_pacman_spelling(self):
        self.assertEqual(self.info.version, "2:0.21.0-1")

    def test_version_without_epoch(self):
        info = srcinfo.parse(
            "pkgbase = a\n\tpkgver = 1.0\n\tpkgrel = 2\n\npkgname = a\n", "a", "ucrt64")
        self.assertEqual(info.version, "1.0-2")

    def test_dependencies_span_base_and_split_packages(self):
        self.assertIn("mingw-w64-i686-libevent", self.info.depends)
        self.assertIn("mingw-w64-i686-qt5", self.info.depends)

    def test_version_constraints_are_stripped(self):
        self.assertIn("mingw-w64-i686-boost", self.info.depends)
        self.assertNotIn("mingw-w64-i686-boost>=1.70", self.info.depends)

    def test_provides_and_keys_are_kept(self):
        self.assertEqual(self.info.provides, ["bitcoin-gui"])
        self.assertEqual(self.info.validpgpkeys, ["ABCDEF0123456789"])

    def test_incomplete_srcinfo_is_rejected(self):
        with self.assertRaises(ValueError):
            srcinfo.parse("pkgbase = a\n\tpkgver = 1.0\n", "a", "ucrt64")


def make_db(entries: list[tuple[str, str]]) -> bytes:
    """Build a pacman database the way repo-add would."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, version in entries:
            desc = f"%FILENAME%\n{name}-{version}-any.pkg.tar.zst\n\n" \
                   f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n"
            payload = desc.encode()
            member = tarfile.TarInfo(f"{name}-{version}/desc")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return gzip.compress(raw.getvalue())


class DatabaseParsing(unittest.TestCase):

    def test_reads_names_and_versions(self):
        database = repodb.parse(make_db([
            ("mingw-w64-ucrt-x86_64-serd", "0.30.10-1"),
            ("mingw-w64-ucrt-x86_64-sord", "0.16.6-1"),
        ]))
        self.assertEqual(len(database), 2)
        self.assertTrue(database.has("mingw-w64-ucrt-x86_64-serd", "0.30.10-1"))

    def test_a_different_version_is_not_published(self):
        database = repodb.parse(make_db([("serd", "0.30.10-1")]))
        self.assertFalse(database.has("serd", "0.30.10-2"))
        self.assertFalse(database.has("serd", "0.30.11-1"))
        self.assertFalse(database.has("nothing", "0.30.10-1"))

    def test_empty_database(self):
        self.assertEqual(len(repodb.Database()), 0)
        self.assertFalse(repodb.Database().has("serd", "1-1"))


class VersionNormalisation(unittest.TestCase):
    """MSYS2 spells the epoch separator '~' because ':' cannot be in a filename."""

    def test_epoch_separators_are_equivalent(self):
        database = repodb.parse(make_db([("qux", "2~1.0-1")]))
        self.assertTrue(database.has("qux", "2:1.0-1"))
        self.assertTrue(database.has("qux", "2~1.0-1"))

    def test_a_tilde_that_is_not_an_epoch_is_left_alone(self):
        # 1.0~rc1 sorts *before* 1.0 and has nothing to do with epochs.
        self.assertEqual(repodb.normalize_version("1.0~rc1-1"), "1.0~rc1-1")
        database = repodb.parse(make_db([("qux", "1.0~rc1-1")]))
        self.assertTrue(database.has("qux", "1.0~rc1-1"))
        self.assertFalse(database.has("qux", "1.0:rc1-1"))


class DatabaseFetching(unittest.TestCase):
    """What the planner makes of whatever the web server hands back."""

    @classmethod
    def setUpClass(cls):
        database = make_db([("serd", "0.30.10-1")])
        cls.requests = []
        cls.agents = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append(self.path)
                cls.agents.append(self.headers.get("User-Agent", ""))
                if self.path == "/real.db":
                    self.reply(200, "application/octet-stream", database)
                elif self.path == "/page.db":
                    # A catch-all rule answering for a file that is not there.
                    self.reply(200, "text/html", b"<!DOCTYPE html><html>Not here</html>")
                else:
                    self.reply(404, "text/html", b"not found")

            def reply(self, status, content_type, body):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.requests.clear()
        self.agents.clear()

    def test_a_published_database_is_read(self):
        database = repodb.fetch(f"{self.base}/real.db")
        self.assertTrue(database.has("serd", "0.30.10-1"))

    def test_requests_do_not_identify_as_python(self):
        # SiteGround answers Python-urllib with a 403 on anything its proxy
        # passes upstream, which includes every .db file.
        repodb.fetch(f"{self.base}/real.db")
        self.assertEqual(self.agents, [repodb.USER_AGENT])
        self.assertNotIn("python", repodb.USER_AGENT.lower())

    def test_a_missing_database_is_an_empty_repository(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(repodb.fetch(f"{self.base}/missing.db")), 0)

    def test_a_page_instead_of_a_database_says_what_arrived(self):
        with self.assertRaises(RuntimeError) as caught:
            repodb.fetch(f"{self.base}/page.db")
        message = str(caught.exception)
        self.assertIn("HTTP 200", message)
        self.assertIn("text/html", message)
        self.assertIn("<!DOCTYPE html>", message)
        # Asking again would only fetch the same page; transport errors alone
        # are worth a retry.
        self.assertEqual(self.requests, ["/page.db"])


def fake(directory: str, pkgnames: list[str], depends: list[str],
         provides: list[str] | None = None) -> SrcInfo:
    return SrcInfo(directory=directory, environment="ucrt64", pkgbase=directory,
                   pkgver="1", pkgrel="1", pkgnames=pkgnames, depends=depends,
                   provides=provides or [])


class BuildOrder(unittest.TestCase):

    def test_dependencies_come_first(self):
        queue = [
            fake("sratom", ["p-sratom"], ["p-serd", "p-sord", "p-lv2"]),
            fake("sord", ["p-sord"], ["p-serd"]),
            fake("serd", ["p-serd"], []),
            fake("lv2", ["p-lv2"], []),
        ]
        order = [info.directory for info in plan.order(queue)]
        self.assertLess(order.index("serd"), order.index("sord"))
        self.assertLess(order.index("sord"), order.index("sratom"))
        self.assertLess(order.index("lv2"), order.index("sratom"))

    def test_dependencies_outside_the_queue_are_not_constraints(self):
        # An already-published dependency is installed from the repository, so
        # it must not appear as an ordering edge (or hold the build hostage).
        queue = [fake("qjackctl", ["p-qjackctl"], ["p-jack2", "p-qt5"])]
        self.assertEqual([i.directory for i in plan.order(queue)], ["qjackctl"])

    def test_provides_resolves_to_the_providing_package(self):
        queue = [
            fake("consumer", ["p-consumer"], ["virtual-thing"]),
            fake("producer", ["p-producer"], [], provides=["virtual-thing"]),
        ]
        order = [info.directory for info in plan.order(queue)]
        self.assertEqual(order, ["producer", "consumer"])

    def test_self_dependency_is_not_a_cycle(self):
        queue = [fake("solo", ["p-a", "p-b"], ["p-a"])]
        self.assertEqual([i.directory for i in plan.order(queue)], ["solo"])

    def test_cycles_are_reported(self):
        queue = [
            fake("a", ["p-a"], ["p-b"]),
            fake("b", ["p-b"], ["p-a"]),
        ]
        with self.assertRaisesRegex(ValueError, "cycle"):
            plan.order(queue)

    def test_order_is_deterministic(self):
        queue = [fake(name, [f"p-{name}"], []) for name in ("c", "a", "b")]
        self.assertEqual([i.directory for i in plan.order(queue)], ["a", "b", "c"])


class RepositoryLayout(unittest.TestCase):
    """Checks against the actual PKGBUILDs in this repository."""

    def test_every_package_directory_is_found(self):
        found = srcinfo.find_package_dirs(ROOT)
        self.assertIn("serd", found)
        self.assertNotIn("ci", found)
        self.assertNotIn(".github", found)

    def test_every_pkgbuild_can_be_read(self):
        # read_environments raises if bash cannot source the PKGBUILD, or if it
        # names an environment that does not exist. An empty result is legal:
        # mingw_arch=() means verified nowhere.
        for directory in srcinfo.find_package_dirs(ROOT):
            with self.subTest(package=directory):
                srcinfo.read_environments(ROOT, directory)

    def test_the_default_is_rung_zero(self):
        self.assertEqual(srcinfo.read_environments(ROOT, "serd"), ["ucrt64"])

    def test_an_empty_array_opts_out_entirely(self):
        self.assertEqual(srcinfo.read_environments(ROOT, "bitcoin"), [])


if __name__ == "__main__":
    unittest.main()


class BrokenPkgbuild(unittest.TestCase):
    """A PKGBUILD bash cannot read must fail loudly, never fall back."""

    def test_unreadable_pkgbuild_is_an_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            package = os.path.join(root, "broken")
            os.makedirs(package)
            with open(os.path.join(package, "PKGBUILD"), "w", encoding="utf-8") as handle:
                handle.write("pkgname=broken\nif [ ; then\n")  # syntax error
            with self.assertRaisesRegex(ValueError, "could not read"):
                srcinfo.read_environments(root, "broken")

    def test_declared_environments_are_deduplicated(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            package = os.path.join(root, "dup")
            os.makedirs(package)
            with open(os.path.join(package, "PKGBUILD"), "w", encoding="utf-8") as handle:
                handle.write("mingw_arch=('ucrt64' 'clang64' 'ucrt64')\n")
            self.assertEqual(
                srcinfo.read_environments(root, "dup"), ["ucrt64", "clang64"])

    def test_an_absent_array_is_not_an_empty_one(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            for name, body in [("absent", "pkgver=1\n"), ("empty", "mingw_arch=()\n")]:
                os.makedirs(os.path.join(root, name))
                with open(os.path.join(root, name, "PKGBUILD"), "w", encoding="utf-8") as h:
                    h.write(body)
            self.assertEqual(srcinfo.read_environments(root, "absent"), ["ucrt64"])
            self.assertEqual(srcinfo.read_environments(root, "empty"), [])

    def test_unknown_environment_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            package = os.path.join(root, "typo")
            os.makedirs(package)
            with open(os.path.join(package, "PKGBUILD"), "w", encoding="utf-8") as handle:
                handle.write("mingw_arch=('ucrt65')\n")
            with self.assertRaisesRegex(ValueError, "unknown mingw_arch"):
                srcinfo.read_environments(root, "typo")
