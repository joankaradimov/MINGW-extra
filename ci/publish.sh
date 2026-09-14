#!/bin/bash
# Publish built packages to the pacman repository.
#
# Together with ci/fetch-published.sh, this is the only part of the pipeline
# that knows where packages are hosted, and the jobs that run the two are the
# only ones holding the deploy key. Keeping the key away from the build jobs is
# a security boundary, not tidiness: a PKGBUILD's build() runs arbitrary
# upstream code, and those runners have no secrets to leak.
#
# Swapping rsync for S3, or for anything else, means rewriting these two files
# and nothing else.
#
# Usage: ci/publish.sh <artifacts-dir>
#   <artifacts-dir>/<environment>/*.pkg.tar.zst
#
# Environment:
#   DEPLOY_HOST      ssh destination, e.g. deploy@packages.example.com
#   DEPLOY_PATH      directory on that host holding the per-environment subdirs
#   RSYNC_RSH        optional; how rsync reaches DEPLOY_HOST (CI passes the key,
#                    known_hosts and port here)

set -euo pipefail

artifacts=${1:?usage: ci/publish.sh <artifacts-dir>}
: "${DEPLOY_HOST:?DEPLOY_HOST is not set}"
: "${DEPLOY_PATH:?DEPLOY_PATH is not set}"

# Must match REPO_NAME in ci/autobuild/config.py: the planner reads the database
# this script writes, and they find each other by name alone.
repo_name=mingw-extra

# Uploaded as .htaccess next to the databases; the file itself says why.
htaccess="$(dirname "${BASH_SOURCE[0]}")/pacman-repo.htaccess"
if [[ ! -f "$htaccess" ]]; then
    echo "error: $htaccess is missing" >&2
    exit 1
fi

shopt -s nullglob

published=0
for environment_dir in "$artifacts"/*/; do
    environment=$(basename "$environment_dir")
    packages=("$environment_dir"*.pkg.tar.zst)
    if [[ ${#packages[@]} -eq 0 ]]; then
        continue
    fi

    db="${repo_name}-${environment}"
    work=$(mktemp -d)
    cp "${packages[@]}" "$work/"

    # Start from the database that is live right now, so this run adds to the
    # repository rather than replacing it. It is copied over SSH, not fetched
    # over HTTP: the host's bot protection challenges the addresses CI runs on.
    #
    # Filtering from the top of DEPLOY_PATH makes an environment that was never
    # published an empty result rather than an error. Anything that does go
    # wrong -- a refused key, a dropped connection -- still stops this script
    # before it uploads a database holding only this run's packages.
    live="$work/live"
    mkdir -p "$live"
    rsync -a --prune-empty-dirs \
        --include="/$environment/" \
        --include="/$environment/${db}.db.tar.gz" \
        --include="/$environment/${db}.files.tar.gz" \
        --exclude='*' \
        "$DEPLOY_HOST:$DEPLOY_PATH/" "$live/"
    for suffix in db.tar.gz files.tar.gz; do
        if [[ -f "$live/$environment/${db}.${suffix}" ]]; then
            mv "$live/$environment/${db}.${suffix}" "$work/"
        else
            echo "note: no existing ${db}.${suffix}, starting a new repository"
        fi
    done
    rm -rf "$live"

    echo "==> $environment: adding ${#packages[@]} package(s) to $db"
    repo-add "$work/${db}.db.tar.gz" "$work"/*.pkg.tar.zst

    # repo-add leaves .db and .files as symlinks; a web server needs real files.
    for link in "$work/${db}.db" "$work/${db}.files"; do
        if [[ -L "$link" ]]; then
            cp -L "$link" "$link.real"
            mv -f "$link.real" "$link"
        fi
    done

    # Named explicitly rather than globbed: repo-add also leaves .old backups
    # behind, and a glob that matched nothing would silently degrade this into
    # an rsync that lists the remote directory and exits 0.
    db_files=("$work/${db}.db" "$work/${db}.db.tar.gz"
              "$work/${db}.files" "$work/${db}.files.tar.gz")
    for file in "${db_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            echo "error: repo-add did not produce $(basename "$file")" >&2
            exit 1
        fi
    done

    # Packages first, database last: a client that syncs mid-upload sees a
    # database that only ever references packages already on the server. The
    # .htaccess travels with the packages, so no database is ever served before
    # the header that keeps it out of the host's cache.
    #
    # --mkpath creates the environment directory, so the deploy key can stay
    # restricted to rsync (command="rrsync ..." in authorized_keys) instead of
    # needing a shell to run mkdir.
    cp "$htaccess" "$work/.htaccess"
    rsync -av --mkpath "$work/.htaccess" "$work"/*.pkg.tar.zst "$DEPLOY_HOST:$DEPLOY_PATH/$environment/"
    rsync -av "${db_files[@]}" "$DEPLOY_HOST:$DEPLOY_PATH/$environment/"

    rm -rf "$work"
    published=$((published + ${#packages[@]}))
done

if [[ $published -eq 0 ]]; then
    echo "error: no packages to publish -- every build must have failed" >&2
    exit 1
fi
echo "published $published package file(s)"
