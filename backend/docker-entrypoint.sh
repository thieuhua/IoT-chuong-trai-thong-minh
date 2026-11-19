#!/bin/sh
# deployment/.env points DATABASE_URL at MySQL on the laptop (127.0.0.1 / localhost).
# Inside the container that address is the container itself, so use the Docker host instead.
set -eu
if [ -n "${DATABASE_URL:-}" ]; then
    DATABASE_URL=$(printf '%s' "$DATABASE_URL" | sed -E 's#@(127\.0\.0\.1|localhost)([:/])#@host.docker.internal\2#')
    export DATABASE_URL
fi
exec "$@"
