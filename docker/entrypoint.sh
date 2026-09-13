#!/bin/sh
# Apply migrations, then serve. Runs on every container start: migrations are
# idempotent, so a rebuild with a new schema revision upgrades the DB in place.
set -e
autoqa db upgrade
exec autoqa serve --host 0.0.0.0 --port 8000
