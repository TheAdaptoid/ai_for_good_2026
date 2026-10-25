# Implementation Plan: Local Application Service with Staff Sign-In

**Branch**: `002-fastapi-service` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-fastapi-service/spec.md`

## Summary

Add a FastAPI package `backend/api/` that is a thin HTTP layer over `analysis_db`. Add two domain
modules to `analysis_db`: `staff.py` (accounts and sessions with Argon2) and `catalog.py` (video
and participant summaries, plus presence intervals computed from detections). Add two tables,
`StaffAccount` and `StaffSession`, to `backend/db/schema.sql`. A local CLI manages accounts, and a
serve script starts the service on `127.0.0.1`. The working database defaults to the git-ignored
`data/analysis.local.sqlite`.

## Technical Context

**Language/Version**: Python 3.13 (`backend/`)

**Primary Dependencies**: FastAPI 0.120.4 (Starlette 0.49.3, Pydantic 2), uvicorn 0.38.0, and
argon2-cffi 25.1.0, all pinned exactly. httpx is a dev-only dependency for `TestClient`.

**Storage**: SQLite. The schema stays in `backend/db/schema.sql`. The default working DB is
`data/analysis.local.sqlite` (git-ignored), overridable with `TPA_DB` or `--db`.

**Testing**: pytest and FastAPI `TestClient`, against temp databases built by the existing
`conftest.py` fixtures. An opt-in smoke test runs against a copy of the real database when present.

**Target Platform**: Local team laptops (macOS/Linux), offline

**Project Type**: Web service inside the backend of a web application

**Performance Goals**: Video, participant, and presence reads under 1 s on the real database
(SC-002, SC-003)

**Constraints**: No outbound network access. Bind to `127.0.0.1` by default. No business logic in
routes.

**Scale/Scope**: About 30 endpoints, 12 videos, 100 participants, and 50k detections

Also in this feature: `backend/pyproject.toml` takes the CUDA torch index only on non-macOS
platforms, so `uv sync --locked` works on the team's Macs. torch stays pinned at 2.8.0. This
satisfies Constitution "code MUST run on CPU" and is needed so the service runs locally.

## Constitution Check

| Principle | Status | How this plan complies |
|---|---|---|
| I. Local-only media | ✅ | Video streamed only to the local browser. No network calls. Accounts and history go to the git-ignored working DB |
| II. Anonymous identity | ✅ | Only `person_id` is exposed. Staff usernames are not participant data |
| III. Data minimization | ✅ | Presence is computed on read, not stored. Staff account holds only username, hash, active flag, timestamp |
| IV. Humans decide | ✅ | Clip priority and annotation confidence are separate fields. No percentages |
| V. Current state/history | ✅ | Review routes call `analysis_db.review` unchanged. Reviewer comes from the session |
| VI. One annotation model | ✅ | All annotation reads use `list_annotations`. Labels come from the `Label` table |
| VII. Modular monolith | ✅ | One FastAPI app. Routes delegate to `analysis_db` |
| VIII. Secure by default | ✅ | Argon2 hashes, hashed session tokens, HttpOnly SameSite=Strict cookie, a global auth dependency, Pydantic `extra="forbid"` bodies, path confinement for video files, `127.0.0.1` default |
| IX. Visible failure | ✅ | Startup schema check. A missing video file returns 404. Domain errors return 400/404 with messages |
| X. Tested workflows | ✅ | Every endpoint has a `TestClient` test. An auth sweep walks the OpenAPI schema |
| XI. Reproducible | ✅ | Exact pins, `uv.lock` updated, README updated |
| XII. Simple, typed | ✅ | Dataclass responses are reused directly, with no parallel DTO layer except request models |

## Project Structure

### Documentation (this feature)

```text
specs/002-fastapi-service/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/http-api.md
└── checklists/requirements.md
```

### Source Code

```text
backend/
├── db/schema.sql                 # + StaffAccount, StaffSession
├── analysis_db/
│   ├── contracts.py              # + STAFF_TABLES, StaffAccount, VideoSummary, PresenceInterval, ...
│   ├── staff.py                  # new: accounts, password hashing, sessions
│   └── catalog.py                # new: video/participant summaries, presence
├── api/
│   ├── __init__.py
│   ├── app.py                    # create_app(db_path), startup check, error mapping, routers
│   ├── auth.py                   # session dependency + /api/auth routes
│   ├── schemas.py                # Pydantic request models
│   └── routes.py                 # videos, participants, annotations, clips, labels, exports
├── scripts/
│   ├── staff.py                  # create / disable / enable / reset-password
│   └── serve.py                  # uvicorn on 127.0.0.1:8000 by default
└── tests/
    ├── test_staff.py
    ├── test_catalog.py
    └── test_api.py
```

**Structure Decision**: Domain logic lives in `analysis_db` and HTTP lives in `api`, following
Constitution VII.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Combined service + auth feature | Constitution VIII forbids any unauthenticated access, so the service cannot ship without auth | A separate auth feature would mean shipping an open API first |
| pyproject torch source marker | `uv sync` fails on macOS, so the service cannot run on the team's machines | Keeping the CUDA-only source blocks every Mac developer |
