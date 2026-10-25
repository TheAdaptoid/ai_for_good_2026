# Research: Local Application Service with Staff Sign-In

## R1 — Sessions: server-side token in a cookie

Decision: on sign-in, generate a `secrets.token_urlsafe(32)` token and store its SHA-256 in
`StaffSession` with a 12-hour expiry. The token goes in cookie `tpa_session`
(HttpOnly, SameSite=Strict, Path=/, Secure off by default because the service runs on plain-HTTP
localhost). Sign-out deletes the row.

Rationale: revocation is immediate (disable account, sign out), no signing secret has to be
managed, and a stolen database does not leak usable tokens. JWT was rejected because it cannot be
revoked without a server-side list anyway.

## R2 — Password hashing: argon2-cffi `PasswordHasher` defaults

Decision: use `PasswordHasher()` (Argon2id, library defaults) and rehash on sign-in when
`check_needs_rehash` reports it. Unknown usernames still run a verify against a fixed dummy hash,
so response timing does not reveal which usernames exist (FR-005).

## R3 — Global auth

Decision: every router except `/api/auth/login` and `/api/health` is mounted with
`dependencies=[Depends(current_staff)]`. A test walks `app.openapi()` and asserts 401 for every
other operation without a cookie (SC-001).

## R4 — CSRF

Decision: SameSite=Strict cookies plus JSON-only request bodies are enough for a localhost tool.
No CORS middleware is installed, so cross-origin browsers cannot read responses, and Strict cookies
are not sent on cross-site requests.

## R5 — Presence intervals

Decision: for one video, read `(person_id, source_time_seconds)` ordered by person then time.
Start a new interval whenever the gap to the previous detection of that person is more than
2.0 s. An interval spans its first to last detection time, so a single detection is a
zero-length interval. Computed in Python per request. For the longest video (about 31k
detections) this is a single indexed query plus a linear pass.

## R6 — Video streaming

Decision: Starlette 0.49 `FileResponse` handles `Range` requests and `206 Partial Content`. The
path comes from `Video.file_path`, resolved against the repository root, and must be inside
`data/videos/` (resolved). Otherwise the service returns 404 without serving the file.

## R7 — Database connection per request

Decision: a FastAPI dependency opens `connect_database(path, must_exist=True)` per request and
closes it afterwards. Spec 001 review functions start their own `BEGIN IMMEDIATE` and need an idle
connection, which a fresh connection always is. Sync route functions run in FastAPI's threadpool.

## R8 — Error mapping

Decision: `DataError` → 400, `LookupError` → 404, Pydantic validation → 422. The body is
`{"detail": "<message>"}`.

## R9 — Responses reuse domain dataclasses

Decision: routes return `analysis_db.contracts` dataclasses, and FastAPI serializes them. Request
bodies are Pydantic models with `extra="forbid"`, so a client-supplied `reviewer_id` gets 422
(FR-006).

## R10 — Working database

Decision: the default is `data/analysis.local.sqlite` (already ignored by `data/*.local.sqlite`).
The README documents creating it as a copy of `data/analysis.sqlite` and running `init_db.py`.
`TPA_DB` or `--db` overrides it. Accounts, sessions, annotations, and history therefore stay out of
the tracked file.
