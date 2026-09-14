#!/bin/bash
# Copy the published repository off the server, over SSH.
#
# CI never reads the repository over HTTP. The host's bot protection answers
# requests from cloud addresses -- which is where GitHub's runners are -- with
# a CAPTCHA page, and pacman would store that page as a database. So the jobs
# holding the deploy key copy what the planner and the builds need, and hand it
# over as an artifact. The jobs that run PKGBUILDs never see the key.
#
# Usage:
#   ci/fetch-published.sh databases <dest>
#       <dest>/<environment>/mingw-extra-<environment>.db for every environment
#       published so far, then <dest>/COMPLETE once all of it has arrived.
#   ci/fetch-published.sh packages <environment> <dest>
#       Every package file <dest>/<environment>/mingw-extra-<environment>.db
#       references, copied next to it: a local repository pacman can install
#       from. <dest> is what the databases step produced.
#
# Environment:
#   DEPLOY_HOST  ssh destination, e.g. deploy@packages.example.com
#   DEPLOY_PATH  directory on that host holding the per-environment subdirs
#   RSYNC_RSH    optional; how rsync reaches DEPLOY_HOST (CI passes the key,
#                known_hosts and port here)

set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST is not set}"
: "${DEPLOY_PATH:?DEPLOY_PATH is not set}"

# Must match REPO_NAME and PUBLISHED_MARKER in ci/autobuild/config.py.
repo_name=mingw-extra
marker=COMPLETE

here=$(dirname "${BASH_SOURCE[0]}")

case "${1:-}" in
    databases)
        dest=${2:?usage: ci/fetch-published.sh databases <dest>}
        mkdir -p "$dest"
        rm -f "$dest/$marker"
        # Filtered from the top of DEPLOY_PATH rather than named one by one, so
        # an environment that was never published is simply absent instead of
        # an error -- while a failed connection still fails the job, and leaves
        # no marker behind. Nothing deeper than one directory is walked.
        rsync -a --prune-empty-dirs \
            --include='/*/' \
            --include="/*/${repo_name}-*.db" \
            --exclude='*' \
            "$DEPLOY_HOST:$DEPLOY_PATH/" "$dest/"
        touch "$dest/$marker"
        found=$(find "$dest" -name "${repo_name}-*.db" -printf '%P\n' | sort)
        if [[ -n "$found" ]]; then
            echo "copied:"
            printf '  %s\n' $found
        else
            echo "nothing is published yet"
        fi
        ;;

    packages)
        environment=${2:?usage: ci/fetch-published.sh packages <environment> <dest>}
        dest=${3:?usage: ci/fetch-published.sh packages <environment> <dest>}
        list=$(mktemp)
        trap 'rm -f "$list"' EXIT
        PYTHONPATH="$here" python3 -m autobuild files \
            --published "$dest" --environment "$environment" > "$list"
        count=$(wc -l < "$list")
        echo "==> $environment: $count published package file(s)"
        if [[ $count -gt 0 ]]; then
            # A file the database lists but the server lacks fails the job.
            # That repository is broken, and building against it would only move
            # the failure somewhere harder to read.
            rsync -a --files-from="$list" \
                "$DEPLOY_HOST:$DEPLOY_PATH/$environment/" "$dest/$environment/"
        fi
        ;;

    *)
        echo "usage: ci/fetch-published.sh databases <dest>" >&2
        echo "       ci/fetch-published.sh packages <environment> <dest>" >&2
        exit 2
        ;;
esac
