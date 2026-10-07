#!/bin/bash
# Delete published package files that no database references any more, once
# they have been unreferenced long enough that nobody is still pointed at one.
#
# Publishing replaces a package's entry, and taking one out removes it, but
# either way the file it referenced stays on the server: a client that synced
# before the publish still has a database naming it, and `pacman -U <url>` on an
# old file is the only quick way back from a bad build. Both reasons expire,
# which is what the window is for -- a database holds one version per package,
# so an old file is never reachable through `pacman -S` anyway.
#
# The clock is not the file's own timestamp. That is when it was built, which
# for a package rebuilt after a year would delete the version it just replaced
# on the same day. So each environment keeps a .prune-state beside its
# database, recording when a file was first seen unreferenced, and a file is
# deleted a window after that. A lost state file only restarts the clock.
#
# Usage: ci/prune.sh <published-dir> [--dry-run]
#   <published-dir> is what `ci/fetch-published.sh databases` produced, read
#   after publishing so the newest files count as referenced.
#
# Environment:
#   PRUNE_DAYS   how long an unreferenced file is kept; 30 by default
#   DEPLOY_HOST  ssh destination, e.g. deploy@packages.example.com
#   DEPLOY_PATH  directory on that host holding the per-environment subdirs
#   RSYNC_RSH    optional; how rsync reaches DEPLOY_HOST (CI passes the key,
#                known_hosts and port here)

set -euo pipefail

published=${1:?usage: ci/prune.sh <published-dir> [--dry-run]}
dry_run=0
if [[ ${2:-} == --dry-run ]]; then
    dry_run=1
elif [[ -n ${2:-} ]]; then
    echo "error: unknown argument '$2'" >&2
    exit 2
fi
: "${DEPLOY_HOST:?DEPLOY_HOST is not set}"
: "${DEPLOY_PATH:?DEPLOY_PATH is not set}"

window_days=${PRUNE_DAYS:-30}
state_name=.prune-state
here=$(dirname "${BASH_SOURCE[0]}")

now=$(date +%s)
cutoff=$((now - window_days * 86400))
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/empty"

shopt -s nullglob

deleted=0
waiting=0
for directory in "$published"/*/; do
    environment=$(basename "$directory")
    # Without the database, every file would look unreferenced.
    if [[ -z $(find "$directory" -maxdepth 1 -name '*.db' -print -quit) ]]; then
        echo "note: no database copied for $environment, so nothing is pruned there"
        continue
    fi

    referenced=$(PYTHONPATH="$here" python3 -m autobuild files \
        --published "$published" --environment "$environment")

    remote="$DEPLOY_HOST:$DEPLOY_PATH/$environment/"
    rsync -q "$remote$state_name" "$work/state" 2>/dev/null || : > "$work/state"

    doomed=()
    : > "$work/next-state"
    while read -r _ name; do
        case $name in
            *.pkg.tar.zst | *.pkg.tar.zst.sig) ;;
            *) continue ;;
        esac
        # A signature belongs to its package: keep both or delete both.
        if grep -qxF -- "${name%.sig}" <<< "$referenced"; then
            continue
        fi
        since=$(awk -v name="$name" '$2 == name { print $1; exit }' "$work/state")
        if [[ -z $since ]]; then
            since=$now
        fi
        if [[ $since -le $cutoff ]]; then
            doomed+=("$name")
        else
            printf '%s %s\n' "$since" "$name" >> "$work/next-state"
            waiting=$((waiting + 1))
        fi
    done < <(rsync --list-only "$remote" |
             awk '$1 !~ /^d/ { name = $0; sub(/^([^ ]+ +){4}/, "", name); print $2, name }')

    if [[ ${#doomed[@]} -gt 0 ]]; then
        echo "==> $environment: deleting ${#doomed[@]} file(s) unreferenced for more than $window_days days"
        printf '  %s\n' "${doomed[@]}"
    else
        echo "==> $environment: nothing to delete yet"
    fi

    if [[ $dry_run -eq 1 ]]; then
        deleted=$((deleted + ${#doomed[@]}))
        continue
    fi

    # Deletion without a shell on the far side: rsync deletes what the source
    # lacks, and the source is empty, so the filters decide. Everything is
    # excluded -- rsync does not delete an excluded file -- except the names
    # listed here. An empty include list would therefore delete nothing.
    if [[ ${#doomed[@]} -gt 0 ]]; then
        filters=()
        for name in "${doomed[@]}"; do
            filters+=("--include=/$name")
        done
        rsync -r --delete "${filters[@]}" --exclude='*' "$work/empty/" "$remote"
        deleted=$((deleted + ${#doomed[@]}))
    fi

    # Written every run, so an entry for a file that came back, or that someone
    # deleted by hand, does not linger.
    cp "$work/next-state" "$work/$state_name"
    rsync -q "$work/$state_name" "$remote"
done

if [[ $dry_run -eq 1 ]]; then
    echo "would delete $deleted file(s); $waiting unreferenced file(s) are inside the window"
else
    echo "deleted $deleted file(s); $waiting unreferenced file(s) are inside the window"
fi
