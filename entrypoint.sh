#!/bin/sh
# Prepare volume permissions. Repair recursively only when the mount root is not
# owned by the runtime user, so normal restarts do not rescan large data trees.

repair_owner_if_needed() {
    target="$1"
    [ -d "$target" ] || return 0

    current_owner="$(stat -c '%u:%g' "$target" 2>/dev/null || true)"
    desired_owner="$(id -u appuser):$(id -g appuser)"
    if [ "$current_owner" != "$desired_owner" ]; then
        chown -R appuser:appuser "$target" 2>/dev/null || true
    fi
}

mkdir -p /data/modules 2>/dev/null || true
chown appuser:appuser /data/modules 2>/dev/null || true
repair_owner_if_needed /data
repair_owner_if_needed /modules
repair_owner_if_needed /backup
exec gosu appuser "$@"
