#!/bin/sh
set -eu

DATA_DIR="/data"
DB_FILE="${DATA_DIR}/network_stats.db"

echo "Preparing persistent data directory..."
if [ ! -d "$DATA_DIR" ]; then
    echo "ERROR: Persistent data directory $DATA_DIR does not exist." >&2
    exit 1
fi

chown app:app "$DATA_DIR"
for file in "${DB_FILE}"*; do
    [ -e "$file" ] || continue
    chown app:app "$file"
done

echo "Applying database migrations..."
gosu app alembic upgrade head

echo "Starting Network Stats..."
exec gosu app "$@"
