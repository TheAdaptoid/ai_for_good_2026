#!/bin/sh
# Fresh copy of the tracked seed database per run, so e2e tests never touch the working DB.
set -eu
cd "$(dirname "$0")/../../backend"
db="../frontend/e2e/.tmp/e2e.sqlite"
mkdir -p "$(dirname "$db")"
rm -f "$db"
cp ../data/analysis.sqlite "$db"
uv run --locked python scripts/init_db.py --db "$db" > /dev/null
echo "e2e-password" | uv run --locked python scripts/staff.py create e2e --db "$db" --password-stdin > /dev/null
exec uv run --locked python scripts/serve.py --db "$db" --port 8001
