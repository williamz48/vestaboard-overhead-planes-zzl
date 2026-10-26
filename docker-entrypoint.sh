#!/bin/sh
# Hosted volumes (Railway, Docker bind mounts) are often owned by root. Start as
# root, make the data directory writable, then drop to the unprivileged user.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R planes:planes "$DATA_DIR"
  exec setpriv --reuid=planes --regid=planes --init-groups "$@"
fi
exec "$@"
