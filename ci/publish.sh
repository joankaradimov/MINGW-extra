#!/bin/bash
# Publish built packages to the pacman repository.
#
# This is the only part of the pipeline that knows where packages are hosted,
# and the only job that holds the deploy key. Keeping it away from the build
# jobs is a security boundary, not tidiness: a PKGBUILD's build() runs
# arbitrary upstream code, and that runner has no secrets to leak.
#
# Swapping rsync for S3, or for anything else, means rewriting this file and
# nothing else.
#
# Usage: ci/publish.sh <artifacts-dir>
#   <artifacts-dir>/<environment>/*.pkg.tar.zst
#
# Environment:
#   MINGW_EXTRA_URL  base URL the repository is served from (to read the current db)
#   RSYNC_RSH        optional; how rsync reaches DEPLOY_HOST (CI passes the key,
#                    known_hosts and port here)
#   DEPLOY_HOST      ssh destination, e.g. deploy@packages.example.com
#   DEPLOY_PATH      directory on that host holding the per-environment subdirs

set -euo pipefail

artifacts=${1:?usage: ci/publish.sh <artifacts-dir>}
: "${DEPLOY_HOST:?DEPLOY_HOST is not set}"
: "${DEPLOY_PATH:?DEPLOY_PATH is not set}"
# Required rather than optional: without the live database there is nothing to
# add to, and the upload would replace it with one holding only this run.
: "${MINGW_EXTRA_URL:?MINGW_EXTRA_URL is not set}"

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
    # repository rather than replacing it. A 404 is the first run, not an error;
    # anything else is not "the repository is empty". Carrying on after a 403 or
    # a 500 would upload a database holding only this run's packages and
    # silently unpublish everything that was there before.
    for suffix in db.tar.gz files.tar.gz; do
        url="${MINGW_EXTRA_URL%/}/${environment}/${db}.${suffix}"
        status=$(curl -sSL --retry 3 -o "$work/${db}.${suffix}" -w '%{http_code}' "$url") \
            || status=000
        case "$status" in
            200) ;;
            404)
                rm -f "$work/${db}.${suffix}"
                echo "note: no existing ${db}.${suffix}, starting a new repository"
                ;;
            *)
                echo "error: $url answered HTTP $status; refusing to replace the live database" >&2
                exit 1
                ;;
        esac
    done

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
