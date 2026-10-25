# Local live-ingestion demo

Open **http://127.0.0.1:5173/ingestion** and sign in with your existing staff account.
The page reads committed database counts every three seconds, shows the last
successful refresh time, and retains the last received counts if a refresh fails.
Requests are serialized so a slow response cannot accumulate overlapping polls.

## One shared database

The API and inference worker both use:

```text
/mnt/storage/Projects/ai_for_good_2026/data/analysis.sqlite
```

Saved inference progress has been merged into this database without replacing
staff accounts, sessions, annotations, review history, clips, or memberships.
The database is local demo data; do not commit or push it.

## Start or resume

Backend, from the project root:

```bash
backend/.venv/bin/python backend/scripts/serve.py --db data/analysis.sqlite
```

Frontend, from `frontend/`:

```bash
npm run dev -- --host 127.0.0.1
```

Inference, from `.worktrees/inference-speed/backend/`:

```bash
.venv/bin/python -u scripts/run_fast_activity.py \
  --db /mnt/storage/Projects/ai_for_good_2026/data/analysis.sqlite \
  --priority-top-people 10 --chunk-size 1000 --device cuda \
  --report-dir /mnt/storage/Projects/ai_for_good_2026/.worktrees/inference-speed/backend/results/live-demo
```

Run one worker only. Already completed matching predictions are skipped. Each
two-instance GPU batch is saved atomically; reports are emitted per 1,000 new
instances. GPU FP32, the 32-frame/15-second input, and the exclusive 65% activity
decision rule remain unchanged.

The current background run logs to:

```text
.worktrees/inference-speed/backend/results/live-demo/inference.log
```

Startup may include model loading, cached-index validation, and forward decoding
to the next pending window. Counters start advancing once results are committed.
Only the Activity stage is currently running; completed Engagement and Clip
stages retain their actual database counts.

The timestamp shows when the browser last successfully read the API, not when a
new inference result was created. A partially processed video remains marked
"In progress" even while the external worker is paused; this page reports stored
completion, not a worker heartbeat.
