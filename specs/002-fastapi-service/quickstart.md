# Quickstart: Local Application Service

Run from `backend/`.

```bash
uv sync --locked
cp -n ../data/analysis.sqlite ../data/analysis.local.sqlite   # working copy, git-ignored
uv run python scripts/init_db.py --db ../data/analysis.local.sqlite
uv run python scripts/staff.py create demo            # prompts for a password
uv run python scripts/serve.py                         # http://127.0.0.1:8000/api/docs
```

Check by hand:

```bash
curl -i http://127.0.0.1:8000/api/videos                       # 401
curl -c jar -H 'content-type: application/json' \
     -d '{"username":"demo","password":"<pw>"}' http://127.0.0.1:8000/api/auth/login
curl -b jar http://127.0.0.1:8000/api/videos                   # 12 videos
curl -b jar http://127.0.0.1:8000/api/participants/Person_0001 # its videos
curl -b jar -r 0-1023 -o /dev/null -w '%{http_code}\n' \
     http://127.0.0.1:8000/api/videos/12/stream                # 206
```

Automated: `uv run pytest -q tests/test_staff.py tests/test_catalog.py tests/test_api.py`.
