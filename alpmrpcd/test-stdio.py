"""Drives the server through its --stdio dispatch loop, with no pipe and no
client: libalpm's version, two version comparisons, and pacman's entry in the
local database, which must agree with what `pacman -Q pacman` says."""
import json
import subprocess
import sys

server = subprocess.Popen([sys.argv[1], "--stdio"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True)
request_id = 0


def call(method, **params):
    global request_id
    request_id += 1
    server.stdin.write(json.dumps({"id": request_id, "method": method,
                                   "params": params}) + "\n")
    server.stdin.flush()
    reply = json.loads(server.stdout.readline())
    if reply.get("id") != request_id or "result" not in reply:
        sys.exit(f"{method}: unexpected reply {reply}")
    return reply["result"]["@ret"]


def expect(what, got, wanted):
    if got != wanted:
        sys.exit(f"{what}: got {got!r}, wanted {wanted!r}")
    print(f"ok  {what}: {got}")


libalpm = subprocess.run(["pacman", "--version"], capture_output=True,
                         text=True, check=True).stdout
version = call("alpm_version")
expect("alpm_version() appears in pacman --version", f"libalpm v{version}" in libalpm, True)
expect("alpm_pkg_vercmp('1.0-1', '1.0-2')", call("alpm_pkg_vercmp", a="1.0-1", b="1.0-2"), -1)
expect("alpm_pkg_vercmp('2.0', '1.9')", call("alpm_pkg_vercmp", a="2.0", b="1.9"), 1)

handle = call("alpm_initialize", root="/", dbpath="/var/lib/pacman/")
db = call("alpm_get_localdb", handle=handle)
pkg = call("alpm_db_get_pkg", db=db, name="pacman")
installed = subprocess.run(["pacman", "-Q", "pacman"], capture_output=True,
                           text=True, check=True).stdout.split()[1]
expect("pacman's version in the local database", call("alpm_pkg_get_version", pkg=pkg), installed)
expect("alpm_release()", call("alpm_release", handle=handle), 0)

server.stdin.close()
sys.exit(server.wait())
