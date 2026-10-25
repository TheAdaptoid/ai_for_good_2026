# Tasks: Local Application Service with Staff Sign-In

**Input**: Design documents from `specs/002-fastapi-service/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/http-api.md

Tests accompany the behavior they verify (Constitution X). Paths are relative to the repo root.

## Phase 1: Setup

- [X] T001 Pin `fastapi==0.120.4`, `uvicorn==0.38.0`, and `argon2-cffi==25.1.0` in `backend/pyproject.toml`, add `httpx` to the dev group, and make the CUDA torch index apply only when `sys_platform != 'darwin'`. Regenerate `backend/uv.lock` and confirm `uv sync --locked` works on macOS. Per plan: Technical Context
- [X] T002 Add `STAFF_TABLES` and the dataclasses `StaffAccount`, `VideoSummary`, `PresenceInterval`, `VideoParticipant`, `ParticipantSummary`, `ParticipantVideo`, and `ParticipantDetail` to `backend/analysis_db/contracts.py`. Per data-model.md

## Phase 2: Foundational

- [X] T003 Append the `StaffAccount` and `StaffSession` tables to `backend/db/schema.sql`, per data-model.md. Include `StaffAccount`/`StaffSession` counts in `backend/scripts/init_db.py` output via a `staff_table_counts` helper in `backend/analysis_db/storage.py`. Test in `backend/tests/test_staff.py` that init on a copy-like DB is idempotent and adds 0 rows. Per FR-002, FR-004
- [X] T004 Implement `backend/analysis_db/staff.py`: `create_account`, `set_password`, `set_active` (disabling deletes sessions), `authenticate` (dummy-hash verify for unknown users, rehash if needed), `create_session` (returns a raw token and stores its SHA-256 with a 12 h expiry), `resolve_session` (rejects expired or inactive, and deletes expired rows), and `end_session`. Tests in `backend/tests/test_staff.py`: no plaintext stored, wrong and unknown password both return None, expired and disabled sessions refused, sign-out ends the session. Per FR-002–FR-005, US1
- [X] T005 Implement `backend/scripts/staff.py` (`create`, `disable`, `enable`, `reset-password`; password via `getpass` with confirmation, or `--password-stdin`; `--db` defaults to the working DB). Add a `WORKING_DB` constant (`data/analysis.local.sqlite`) to `backend/analysis_db/paths.py`. CLI tests in `backend/tests/test_staff.py`. Per FR-003, FR-019
- [X] T006 Create `backend/api/app.py` with `create_app(db_path, video_dir)`: a startup schema check over `TABLES + REVIEW_TABLES + STAFF_TABLES` (raises on missing tables), a per-request connection dependency, `DataError`→400 and `LookupError`→404 handlers, docs at `/api/docs`, OpenAPI at `/api/openapi.json`, and `/api/health`. Per FR-016, FR-020, FR-021, R7, R8
- [X] T007 Create `backend/api/auth.py`: a `current_staff` dependency (cookie `tpa_session` → `resolve_session`, else 401) and the routes `POST /api/auth/login` (generic 401 on failure, HttpOnly SameSite=Strict cookie), `POST /api/auth/logout`, and `GET /api/auth/me`. Create `backend/api/schemas.py` with the `LoginRequest` model (`extra="forbid"`). Per FR-001, FR-004, FR-005, US1

## Phase 3: US1 + US2 + US3 + US4 — Sign-in, dashboard, video, participant (P1/P2)

- [X] T008 Implement `backend/analysis_db/catalog.py`: `list_videos`, `get_video` (summary counts with zeros for every review status), `video_participants` (presence intervals with a 2.0 s gap tolerance, per R5), `list_participants`, and `get_participant`. Tests in `backend/tests/test_catalog.py` cover gap merging, single-detection intervals, zero counts, and unknown ids raising LookupError. Per FR-008–FR-010
- [X] T009 Add the video and participant routes to `backend/api/routes.py`: `GET /api/videos`, `/api/videos/{id}`, `/api/videos/{id}/participants`, `/api/videos/{id}/stream` (FileResponse with Range; path confined to `video_dir`; missing file or out-of-directory path → 404), `/api/participants`, and `/api/participants/{person_id}`. Per FR-008–FR-010, FR-017
- [X] T010 Tests in `backend/tests/test_api.py`: login/logout/me flow; generic failure; a disabled account mid-session gets 401; an OpenAPI sweep where every operation except login and health returns 401 without a cookie; video list and detail; 404s; participants; stream returns 200 and 206 with `Content-Range`; a missing file and an out-of-directory path return 404; `create_app` on a database without the staff tables raises at startup. Per SC-001, SC-006, US1–US4, FR-020

## Phase 4: US5 + US6 — Review, labels, clips, history, export (P1/P2)

- [X] T011 Add `CreateAnnotationRequest`, `EditRequest` (person_id omitted → UNSET, explicit null → clear), and `NoteRequest` to `backend/api/schemas.py`, all with `extra="forbid"`. Add the annotation routes to `backend/api/routes.py`: list (Spec 001 filters), get, history, create (201), accept, reject, defer, and edit. Each calls `analysis_db.review` with `reviewer_id` set to the session username and returns `{annotation, event}`. Per FR-006, FR-011, FR-014–FR-016
- [X] T012 Add `GET /api/clips` (video_id, person_id, order), `GET /api/labels` (category, include_inactive), and `GET /api/exports/annotations` and `/api/exports/history` (format csv|json, a Content-Disposition filename; the annotation export takes `include_rejected`) to `backend/api/routes.py`. Per FR-012, FR-013, FR-018
- [X] T013 Tests in `backend/tests/test_api.py`: create → edit → history records the session username; `reviewer_id` in a body returns 422; a deactivated label or bad span returns 400 and no change; rejected annotations hidden by default and listed with `include_rejected`; person_id null vs omitted on edit; labels (18 active, inactive only when asked); clips ordered by priority with unscored last; CSV and JSON exports with headers and filename; history export. Per US5, US6, SC-004

## Phase 5: Polish

- [X] T014 Add `backend/scripts/serve.py` (`--host` default `127.0.0.1`, `--port` 8000, `--db` default working DB or `TPA_DB`, `--video-dir`), and a test that the parser default host is `127.0.0.1`. Per FR-007, FR-019
- [X] T015 Add an opt-in test in `backend/tests/test_api.py` that copies the real `data/analysis.sqlite` to tmp when present (skipped otherwise), runs init, creates an account, and checks 12 videos and 100 participants, that `Person_0001` appears in its videos, and that each of the list, participants-of-longest-video, and participant-list reads takes under 1 s. Per SC-002, SC-003
- [X] T016 Update `backend/README.md` with the working DB setup, the account CLI, starting the service, and the endpoint overview. Update `docs/ROADMAP.md` (feature order: service + auth now, clip pipeline deferred) and `docs/DECISIONS.md` (D018 deferral of clip pipeline, D019 working database, D020 session auth). Per Constitution XI, AGENTS M
- [X] T017 Run `uv run --locked pytest -q` in `backend/` and record results, including the known pre-existing failures. Per AGENTS I. FR-022 (no outbound network) holds by construction: no HTTP client in runtime code, and the dev-only httpx is used solely by TestClient.

## Results (T017)

`uv run --locked pytest -q` in `backend/`: 550 passed, 1 skipped, 7 failed. All 7 failures are
pre-existing or environment-specific and are not caused by this feature:

- `test_video_metadata.py::test_different_case_is_not_found`: case-insensitive macOS filesystem
  (known before Spec 001).
- 5 × `test_activity_notebook.py`: the committed `notebooks/activity_classification.ipynb` at
  HEAD carries execution counts, so the tests' clean-source check fails before execution.
- `test_activity_runtime.py::test_isolated_backend_subprocess_defaults_and_fake_classification`:
  the test hard-codes `/tmp/opencode`, which does not exist on this machine.

The live smoke run of `scripts/serve.py` on a copy of the real DB returned 401 without a
session, then a successful login, 12 videos, a 206 stream, and `Person_0001` across 6 videos.
Not run: SC-005 in-browser playback, which the React feature will verify.
