#!/bin/bash
# Upload the repository's home page, ci/site/, to the top of DEPLOY_PATH, and
# an empty repository for every environment that has nothing published yet.
#
# It only adds and replaces files. There is no --delete, because DEPLOY_PATH
# also holds every environment's repository, and dotfiles are left out so that
# nothing here can replace the site's own .htaccess.
#
# The page and the README list a pacman.conf section for every environment in
# ci/autobuild/config.py, and pacman fails a whole -Sy over one database it
# cannot download. So an environment nothing is built for yet gets the empty
# database repo-remove leaves behind once the last package is out. Only an
# environment with no database at all: one that has a database is publish.sh's,
# and --ignore-existing keeps it that way.
#
# Usage: ci/publish-site.sh
#
# Environment:
#   DEPLOY_HOST  ssh destination, e.g. deploy@packages.example.com
#   DEPLOY_PATH  directory on that host holding the per-environment subdirs
#   RSYNC_RSH    optional; how rsync reaches DEPLOY_HOST (CI passes the key,
#                known_hosts and port here)

set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST is not set}"
: "${DEPLOY_PATH:?DEPLOY_PATH is not set}"

# Must match REPO_NAME in ci/autobuild/config.py.
repo_name=mingw-extra

here=$(dirname "${BASH_SOURCE[0]}")
site="$here/site"
htaccess="$here/pacman-repo.htaccess"
for file in "$site/index.html" "$htaccess"; do
    if [[ ! -f "$file" ]]; then
        echo "error: $file is missing" >&2
        exit 1
    fi
done

rsync -rtv --exclude='.*' "$site/" "$DEPLOY_HOST:$DEPLOY_PATH/"

environments=$(PYTHONPATH="$here" python3 -c \
    'from autobuild.config import ENVIRONMENTS; print(*ENVIRONMENTS, sep="\n")')

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
bash "$here/fetch-published.sh" databases "$work/live"

for environment in $environments; do
    db="${repo_name}-${environment}"
    if [[ -f "$work/live/$environment/$db.db" ]]; then
        continue
    fi
    echo "==> $environment: nothing is published, uploading an empty $db"
    empty="$work/empty/$environment"
    mkdir -p "$empty"
    tar -czf "$empty/$db.db.tar.gz" -T /dev/null
    for name in "$db.db" "$db.files.tar.gz" "$db.files"; do
        cp "$empty/$db.db.tar.gz" "$empty/$name"
    done
    # The .htaccess first, as publish.sh does, so no database is ever served
    # before the header that keeps it out of the host's cache.
    cp "$htaccess" "$empty/.htaccess"
    rsync -av --mkpath --ignore-existing "$empty/.htaccess" "$DEPLOY_HOST:$DEPLOY_PATH/$environment/"
    rsync -av --ignore-existing "$empty/$db".{db,db.tar.gz,files,files.tar.gz} \
        "$DEPLOY_HOST:$DEPLOY_PATH/$environment/"
done
