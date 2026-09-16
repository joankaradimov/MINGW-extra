#!/bin/bash
# Upload the repository's home page, ci/site/, to the top of DEPLOY_PATH.
#
# It only adds and replaces files. There is no --delete, because DEPLOY_PATH
# also holds every environment's repository, and dotfiles are left out so that
# nothing here can replace the site's own .htaccess.
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

site="$(dirname "${BASH_SOURCE[0]}")/site"
if [[ ! -f "$site/index.html" ]]; then
    echo "error: $site/index.html is missing" >&2
    exit 1
fi

rsync -rtv --exclude='.*' "$site/" "$DEPLOY_HOST:$DEPLOY_PATH/"
