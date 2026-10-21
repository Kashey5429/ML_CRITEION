#!/usr/bin/env bash
set -euo pipefail
export PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"
export PGDATABASE="$POSTGRES_DB" PGHOST=localhost PGPORT=5432
# The official postgres image's initialization server only listens on a Unix socket.
export PGHOST=/var/run/postgresql
/usr/local/madlib/bin/madpack -s madlib -p postgres install
psql -v ON_ERROR_STOP=1 -f /opt/checks/smoke.sql
psql -v ON_ERROR_STOP=1 -f /opt/checks/closest_columns.sql
psql -v ON_ERROR_STOP=1 -f /opt/checks/resources.sql
