#!/bin/sh
# Usage: start-backend.sh PORT [SYNTHETIC_IMPORT_JSON]
# Builds a fresh copy of the tracked seed database per run, so e2e tests never touch the working
# DB or data/analysis.sqlite. An optional synthetic pipeline file is imported into the copy only.
set -eu
port="$1"
fixture="${2:-}"
cd "$(dirname "$0")/../../backend"
db="../frontend/e2e/.tmp/e2e-$port.sqlite"
mkdir -p "$(dirname "$db")"
rm -f "$db"
cp ../data/analysis.sqlite "$db"
uv run --locked python scripts/init_db.py --db "$db" > /dev/null
echo "e2e-password" | uv run --locked python scripts/staff.py create e2e --db "$db" --password-stdin > /dev/null
if [ -n "$fixture" ]; then
  uv run --locked python scripts/import_pipeline_output.py --input "$fixture" --db "$db" > /dev/null
fi
exec uv run --locked python scripts/serve.py --db "$db" --port "$port"
