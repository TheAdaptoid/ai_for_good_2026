# AI For Good 2026

>Team: Random Forest
>
> Marion Forrest <br>
> MS Computer Science @ UCF <br>
> the.marion.404@gmail.com <br>
>
> RJ Clines <br>
>
> Caden Wondell <br>

## Running the staff review app locally

Everything runs on your machine. Footage and review data are never sent to a cloud service.

```bash
# 1. Service (Python 3.13 + uv), from backend/
cd backend
uv sync --locked
uv run python scripts/init_db.py --db ../data/analysis.sqlite
uv run python scripts/staff.py create <username>
uv run python scripts/serve.py            # http://127.0.0.1:8000

# 2. Web app (Node 20+), from frontend/ in a second terminal
cd frontend
npm ci
npm run dev                               # open http://127.0.0.1:5173
```

Put the original videos in `data/videos/` (git-ignored). See `backend/README.md` and
`frontend/README.md` for details and tests.

## Problem Statement

## Proposed Solution

## Development Challenges

## Next Steps