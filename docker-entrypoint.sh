#!/bin/sh
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Starting Network Stats..."
exec "$@"
