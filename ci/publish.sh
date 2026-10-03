#!/bin/bash
# Publish built packages to the pacman repository, and take out of it what no
# PKGBUILD here produces any more.
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
# Usage: ci/publish.sh <artifacts-dir> [<environment>/<package> ...]
#   <artifacts-dir>/<environment>/*.pkg.tar.zst
#   Each <environment>/<package> is a package to take out of that environment's
#   database: the planner's "remove" output (removals in ci/autobuild/plan.py).
#
# Environment:
#   DEPLOY_HOST      ssh destination, e.g. deploy@packages.example.com
#   DEPLOY_PATH      directory on that host holding the per-environment subdirs
#   RSYNC_RSH        optional; how rsync reaches DEPLOY_HOST (CI passes the key,
#                    known_hosts and port here)

set -euo pipefail

artifacts=${1:?usage: ci/publish.sh <artifacts-dir> [<environment>/<package> ...]}
shift
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

declare -A remove=()
for pair in "$@"; do
    environment=${pair%%/*}
    package=${pair#*/}
    if [[ -z $environment || -z $package || $package == "$pair" ]]; then
        echo "error: '$pair' is not <environment>/<package>" >&2
        exit 1
    fi
    remove[$environment]+=" $package"
done

# Every environment with packages to add or entries to take out.
environments=("${!remove[@]}")
for environment_dir in "$artifacts"/*/; do
    packages=("$environment_dir"*.pkg.tar.zst)
    if [[ ${#packages[@]} -gt 0 ]]; then
        environments+=("$(basename "$environment_dir")")
    fi
done
mapfile -t environments < <(printf '%s\n' "${environments[@]}" | sed '/^$/d' | sort -u)

published=0
removed=0
for environment in "${environments[@]}"; do
    packages=("$artifacts/$environment/"*.pkg.tar.zst)
    read -ra unwanted <<< "${remove[$environment]:-}"

    db="${repo_name}-${environment}"
    work=$(mktemp -d)
    if [[ ${#packages[@]} -gt 0 ]]; then
        cp "${packages[@]}" "$work/"
    fi

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

    # Only names the live database still holds: repo-remove leaves the database
    # alone and fails over a single name it cannot find, and one may have been
    # taken out by hand since the plan read the database.
    if [[ ${#unwanted[@]} -gt 0 ]]; then
        held=()
        if [[ -f "$work/${db}.db.tar.gz" ]]; then
            mapfile -t held < <(bsdtar -xOf "$work/${db}.db.tar.gz" '*/desc' |
                                awk '/^%NAME%$/ { getline; print }')
        fi
        present=()
        for package in "${unwanted[@]}"; do
            if printf '%s\n' "${held[@]}" | grep -qxF -- "$package"; then
                present+=("$package")
            else
                echo "note: $package is not in $db, so there is nothing to take out"
            fi
        done
        unwanted=("${present[@]}")
    fi
    if [[ ${#unwanted[@]} -gt 0 ]]; then
        echo "==> $environment: taking ${#unwanted[@]} package(s) out of $db: ${unwanted[*]}"
        repo-remove "$work/${db}.db.tar.gz" "${unwanted[@]}"
    fi

    if [[ ${#packages[@]} -gt 0 ]]; then
        echo "==> $environment: adding ${#packages[@]} package(s) to $db"
        repo-add "$work/${db}.db.tar.gz" "$work"/*.pkg.tar.zst
    fi

    if [[ ${#packages[@]} -eq 0 && ${#unwanted[@]} -eq 0 ]]; then
        rm -rf "$work"
        continue
    fi

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
    #
    # A package taken out keeps its file on the server, as a superseded version
    # does; the database no longer references it.
    cp "$htaccess" "$work/.htaccess"
    rsync -av --mkpath "$work/.htaccess" "$work"/*.pkg.tar.zst "$DEPLOY_HOST:$DEPLOY_PATH/$environment/"
    rsync -av "${db_files[@]}" "$DEPLOY_HOST:$DEPLOY_PATH/$environment/"

    rm -rf "$work"
    published=$((published + ${#packages[@]}))
    removed=$((removed + ${#unwanted[@]}))
done

# Without anything to take out, publish only runs when something was to be
# built, so publishing nothing means every build failed.
if [[ $published -eq 0 && $# -eq 0 ]]; then
    echo "error: no packages to publish -- every build must have failed" >&2
    exit 1
fi
echo "published $published package file(s), took $removed out"
