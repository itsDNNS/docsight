#!/bin/sh
# Fix volume permissions (may be root-owned from previous versions)
chown -R appuser:appuser /data 2>/dev/null || true
[ -d /backup ] && chown -R appuser:appuser /backup 2>/dev/null || true
exec gosu appuser "$@"
