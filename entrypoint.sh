#!/bin/sh
# Fix data volume permissions (may be root-owned from previous versions)
chown -R appuser:appuser /data 2>/dev/null || true
exec gosu appuser "$@"
