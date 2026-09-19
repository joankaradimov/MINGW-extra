# The MINGW-extra autobuilder

Builds every PKGBUILD in this repository whose current version is not published
yet, and pushes the results to a pacman repository we host ourselves.

## Why this is not msys2-autobuild

MSYS2's own [msys2-autobuild](https://github.com/msys2/msys2-autobuild) looks
like the obvious thing to fork, and it isn't. Its `get_buildqueue()` is one
HTTP call to `https://packages.msys2.org/api/buildqueue2` — a separate hosted
service ([msys2-web](https://github.com/msys2/msys2-web)) that only knows about
`msys2/MINGW-packages` and `msys2/MSYS2-packages`, and only diffs them against
`repo.msys2.org`. There is no configuration hook to point it somewhere else, so
reusing autobuild means also running msys2-web plus the `.SRCINFO` cache
generator that feeds it — and *that* is the part which actually decides what
needs building. What remains in autobuild is largely a GitHub-Releases-as-staging
shuttle hardwired to MSYS2's own org and directory layout.

That machinery earns its keep at 3400 packages across six environments. At
thirteen it is a large dependency you cannot configure. What it *is* good for is
its hard-won details, and several are reproduced here on purpose:

- the published repository, not a git diff, decides what needs building;
- `makepkg-mingw --printsrcinfo` per environment, never a regex over a PKGBUILD;
- a temporary `pacman.conf` reached through `$PACMAN`, since makepkg has no `--config`;
- `GITHUB_*`/`ACTIONS_*`/`RUNNER_*` stripped from the environment before makepkg runs;
- `PACKAGER` pointing back at the run that produced the package;
- a short build path, because Windows path limits arrive sooner than you expect;
- a bigger pagefile on hosted runners.

## How it works

**databases** (Linux) copies each environment's published pacman database off
the server over SSH, and hands them on as an artifact.

**plan** (Windows + MSYS2) runs `makepkg-mingw --printsrcinfo` for every
PKGBUILD in every environment it declares, reads those databases, and queues
anything whose exact `pkgver-pkgrel` is not there. It topologically sorts each
queue and emits a GitHub Actions matrix with one entry per environment.

**mirror** (Linux, one job per environment with something to build) copies the
package files that environment's database references, so its build can install
already-published dependencies.

**build** (Windows + MSYS2, one job per environment) walks its queue in order,
with that copy in its pacman.conf as a `file://` repository. After each success
it `repo-add`s the result into a local staging repository and refreshes pacman,
so `sord` installs the `serd` this job built minutes earlier. A package that
fails does not stop the queue — the remaining ones still build, and the job
fails at the end with all of them listed.

**msys** (Windows + MSYS2) builds the MSYS packages -- the ones whose names
carry no `MINGW_PACKAGE_PREFIX` -- with plain `makepkg`, before any MinGW build
starts. A MinGW package may depend on one (`alpmrpc` needs `alpmrpcd`), so every
MinGW build installs what this job produced, and what is already published for
msys, next to its own environment's packages.

**publish** (Linux) collects the artifacts, rebuilds each database from the one
currently live, and rsyncs packages first and databases last, so a client
syncing mid-upload never sees a database referencing a package that is not there
yet.

**site** (Linux) uploads `ci/site/`, the home page users land on, to the top
of `DEPLOY_PATH`. It runs on every run, alongside the rest; the page is small,
and this way the one on the server never drifts from the one in the repository.

Only databases, mirror, publish and site hold the deploy key, and none of them
runs a PKGBUILD. plan and build run PKGBUILDs — `build()` is arbitrary upstream code —
and **hold no secrets**, deliberately.

Nothing in CI reads the repository over HTTP. The host's bot protection answers
requests from cloud addresses, which is where GitHub's runners are, with a
CAPTCHA page, and pacman would store that page as a database without complaint.
SSH is not challenged.

Ordering inside a job rather than one job per package is not a compromise: a
matrix cannot express dependencies between its own entries, and packages here
do depend on each other.

**Pull requests** build what they change, but cannot have the key and so cannot
see the published repository. Their planner queues every package from this
repository that a changed one depends on, and the build compiles those from
source first.

## One-time setup

Four **secrets**, and an optional fifth, used only by the databases, mirror,
publish and site jobs:

| name | what it is |
| --- | --- |
| `DEPLOY_KEY` | private half of an SSH key the server accepts, without a passphrase |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -p <port> -t ed25519 packages.example.com` |
| `DEPLOY_HOST` | `deploy@packages.example.com` |
| `DEPLOY_PORT` | the SSH port; optional, 22 when absent |
| `DEPLOY_PATH` | directory the per-environment subdirectories live in; `.` under rrsync |

`DEPLOY_KNOWN_HOSTS` has to be scanned with the same host name and port the
jobs connect to. For any port but 22 ssh looks the key up as `[host]:port`, so
an entry scanned without `-p` never matches and every SSH job fails with "Host
key verification failed".

All four jobs target a GitHub Actions **environment** named `publish`, so the
secrets can live on that environment or on the repository. Leave the
environment without required reviewers: they would ask for approval four times
per run, and hold every scheduled run at its very first jobs.

On the server, `DEPLOY_PATH` needs to be writable by the deploy user and served
to users over HTTPS. The layout builds itself:

```
<DEPLOY_PATH>/index.html                            -> https://packages.example.com/mingw-extra/
<DEPLOY_PATH>/ucrt64/mingw-extra-ucrt64.db          -> https://packages.example.com/mingw-extra/ucrt64/...
<DEPLOY_PATH>/ucrt64/mingw-extra-ucrt64.files
<DEPLOY_PATH>/ucrt64/mingw-w64-ucrt-x86_64-serd-0.30.10-1-any.pkg.tar.zst
<DEPLOY_PATH>/clang64/...
<DEPLOY_PATH>/mingw32/...
<DEPLOY_PATH>/msys/mingw-extra-msys.db              -> the MSYS packages
```

The host has to serve files ending in `.db`: that is the name pacman asks for,
and it cannot be changed. SiteGround refuses them with a 403 by default; its
support lifted that for this repository's subdomain on request. SiteGround's
bot protection still challenges visitors from cloud addresses, so a user
installing from a cloud VM or a CI job may get a CAPTCHA page instead of a
database.

Every environment directory also receives `ci/pacman-repo.htaccess` as its
`.htaccess`, marking the databases `Cache-Control: no-cache`. Without it a host
with a caching proxy in front of Apache, SiteGround included, keeps handing out
the previous database for hours after a publish.

Restrict the deploy key to that directory — `command="rrsync /srv/mingw-extra"`
in `authorized_keys`, or the equivalent forced-command wrapper — where the host
allows it. The jobs only ever run rsync (publish creates the per-environment
directories with `--mkpath`), so the key never needs a shell.

rrsync resolves every path the client sends *inside* its directory, stripping
any leading slash, so under rrsync `DEPLOY_PATH` must be `.`. An absolute
`DEPLOY_PATH` would put packages in `/srv/mingw-extra/srv/mingw-extra/ucrt64`,
which `--mkpath` creates without complaint and the web server never serves.

## The home page

`ci/site/index.html` is what a browser gets at the top of the repository: what
MINGW-extra is, and the `pacman.conf` sections to add. `ci/publish-site.sh`
uploads everything in `ci/site/` except dotfiles, and never deletes anything,
since the same directory holds the repositories.

The page names the host (`https://msys2pkgs.karadimov.org`) outright, so moving
the repository means editing it. A test checks that it lists a section for
every environment in `ci/autobuild/config.py`, so adding an environment there
without adding it to the page fails the build.

## Using the repository

Users add one section per environment to `/etc/pacman.conf`, after the MSYS2
repositories so upstream keeps precedence:

```ini
[mingw-extra-ucrt64]
SigLevel = Optional TrustAll
Server = https://packages.example.com/mingw-extra/ucrt64
```

Add `[mingw-extra-msys]` too, served from `.../msys`, whatever environment you
use: some MinGW packages here depend on an MSYS package from it.

`SigLevel = Optional TrustAll` is what unsigned packages require. See
*Adding signing* below.

## Choosing environments per package

`.claude/skills/msys2-environments` defines the ladder — UCRT64, then CLANG64, then
MINGW32, then CLANGARM64, one rung at a time — and is explicit that
`mingw_arch` records where a package has actually been *verified*, because "an
unverified entry is worse than an absent one". CI treats that as binding rather
than guessing:

| in the PKGBUILD | what CI builds |
| --- | --- |
| no `mingw_arch` | `ucrt64` — rung 0, and nothing else |
| `mingw_arch=('ucrt64' 'clang64')` | exactly those |
| `mingw_arch=()` | nothing: verified nowhere, so built nowhere |

An MSYS package -- one whose `pkgname` carries no `MINGW_PACKAGE_PREFIX`, the
same distinction MSYS2 itself draws between its two package trees -- is built
for `msys` and nothing else. `mingw_arch=()` still keeps one from being built;
any other `mingw_arch` in it is an error.

This makes climbing a rung a pull request. Add `clang64` to `mingw_arch`, open
the PR, and the PR workflow builds that environment and only that environment —
so the merge is the record that it worked, which is precisely the order the
skill asks for. `clangarm64` works the same way, which is how a rung you cannot
test on an x64 desktop still gets verified before it is claimed.

`bitcoin` currently declares `mingw_arch=()`. Its `package_*()` functions are
named for the i686 and x86_64 prefixes only, so makepkg has nothing to call in
`ucrt64`; reaching rung 0 means adding `package_mingw-w64-ucrt-x86_64-*`
wrappers first. Until then CI leaves it alone instead of failing on it nightly.

## Running it yourself

From an MSYS2 shell at the repository root, with `python` and `base-devel`
installed:

```console
$ PYTHONPATH=ci python -m autobuild plan
$ PYTHONPATH=ci python -m autobuild plan --package serd
$ PYTHONPATH=ci python -m autobuild build --environment ucrt64 serd sord
```

Without `--published`, nothing counts as published, so `plan` queues
everything — handy for a dry run. To see exactly what CI sees, copy the server
first, with `DEPLOY_HOST` and `DEPLOY_PATH` set and SSH access to the host:

```console
$ ci/fetch-published.sh databases published
$ PYTHONPATH=ci python -m autobuild plan --published published
$ ci/fetch-published.sh packages ucrt64 published
$ PYTHONPATH=ci python -m autobuild build --published published --environment ucrt64 sord
```

`--prebuilt DIR` makes packages another job built, laid out as
`DIR/<environment>/*.pkg.tar.zst`, a staging repository of their own; that is how
the MinGW builds get the msys job's output.

`build` writes packages to `artifacts/<environment>/` and scratch to
`--build-root` (`/tmp/mingw-extra` by default; CI uses `/c/_b` to keep paths
short). It never modifies `/etc/pacman.conf`.

The tests need neither Windows nor MSYS2, which is why they run on every push
and pull request in their own workflow:

```console
$ PYTHONPATH=ci python -m unittest discover -s ci -v
```

## Adding a package

Create a directory with a PKGBUILD and push. The scheduled run picks it up
within a day; a push to `master` picks it up immediately. Nothing is
registered anywhere — a directory containing a PKGBUILD *is* the registration.

A new package starts at rung 0 with no `mingw_arch` at all, which is what the
default is for. Extend it as each rung is verified.

To rebuild a package that is already published, bump `pkgrel`. That is not a
workaround for the version check, it is the correct thing to do: users whose
pacman already has the old build have no other way to learn there is a new one.

VCS packages are built with `--holdver`: the version is the `pkgver` in the
PKGBUILD, not whatever upstream's HEAD happens to be, so it only changes when a
commit here changes it.

## Adding signing

Currently packages are unsigned. To change that:

1. put the private key and passphrase in secrets;
2. import them in the publish job and pass `--sign` to `repo-add`;
3. sign each package with `gpg --detach-sign` and rsync the `.sig` files too;
4. drop `TrustAll` from the pacman.conf snippet above.

Signing in the build jobs instead would put the key next to arbitrary upstream
build scripts, which is exactly what the current split avoids.

## Deliberately not built yet

- **Source packages.** `makepkg --allsource` and a `sources/` directory, if
  anyone ever wants to rebuild from what was actually shipped.
- **Failure markers.** A package that cannot build is retried every scheduled
  run forever. At thirteen packages that is cheap and arguably useful, since
  upstream fixing a dead source URL resolves itself. msys2-autobuild uploads a
  `.failed` marker to stop retrying; worth copying if the queue grows.
- **Pruning old versions.** Nothing deletes superseded packages from the
  server, so the repository grows without bound. `paccache -r` over
  `DEPLOY_PATH` on a timer is the usual answer.
- **Mirroring only what a queue needs.** The mirror job copies every current
  package of an environment, even when the queue needs two of them. Resolving
  the queue's dependencies against the database would cut that down, once the
  repository is large enough for the copy to take noticeable time.
