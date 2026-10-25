# Tasks: TPA Staff Review Web Application

**Input**: `specs/003-react-app/` spec.md, plan.md

## Phase 1: Setup

- [X] T001 Scaffold `frontend/` (Vite react-ts) with exact-pinned dependencies, `package-lock.json`, strict `tsconfig`, oxlint (from the Vite template), a `vite.config.ts` that proxies `/api` to `http://127.0.0.1:8000` and holds the vitest config (jsdom, setup file), and the scripts `dev`, `build`, `typecheck`, `lint`, `test`, `gen:api`. Add a `frontend/.gitignore` for `node_modules` and `dist`. Per plan
- [X] T002 Add `backend/scripts/openapi.py`, which prints the service OpenAPI JSON using a temp initialized DB, plus a test in `backend/tests/test_api.py` that its output parses and includes `/api/videos`. Generate `frontend/src/api/schema.d.ts`. Per FR-002, plan D1

## Phase 2: Foundational

- [X] T003 `frontend/src/api/client.ts`: a typed `api.get/post`, JSON errors carrying the service `detail`, 401 → `onUnauthorized` callback, and URL helpers for stream and exports. `frontend/src/hooks.ts` `useResource`. `frontend/src/format.ts` (time formatting, seconds↔frames). Unit tests in `frontend/src/test/format.test.ts`. Per FR-001, FR-014
- [X] T004 `frontend/src/auth.tsx` (AuthProvider: me/login/logout, signed-out on 401), `frontend/src/pages/Login.tsx`, `frontend/src/components/Layout.tsx` (header with nav, username, sign-out), `frontend/src/main.tsx` routes (`/`, `/videos/:id`, `/participants`, `/participants/:personId`, `*`), and `frontend/src/styles.css` tokens with light/dark and focus styles. Test `frontend/src/test/auth.test.tsx`: unauthenticated shows login, a bad login shows a generic error, a good login shows the dashboard, sign-out returns to login. Per US1, FR-001, FR-014, FR-015

## Phase 3: US2 Dashboard

- [X] T005 `frontend/src/pages/Dashboard.tsx` with totals, a video table (title link, duration, participants, clips, review counts), the empty-pipeline note, an export menu (annotations/history × CSV/JSON), and error + retry. `frontend/src/components/States.tsx` (Loading, ErrorState, Empty). Test `frontend/src/test/dashboard.test.tsx`. Per US2, US7, FR-003, FR-013

## Phase 4: US3 Video view + US5/US6 Review

- [X] T006 `frontend/src/components/Timeline.tsx`: time axis ticks, clip row (review priority), scene row, per-participant rows (presence bars + annotation bars, AI/unreviewed styling, status marks), playhead, click-to-seek, participant links. Per FR-004–FR-008
- [X] T007 `frontend/src/components/StatusBadge.tsx` (separate source and status badges). `frontend/src/components/ReviewPanel.tsx`: details (model confidence labeled), Accept/Reject/Defer with note, Edit (label same category and active, start/end seconds, participant), error display, and history list. Per US5, FR-005, FR-010
- [X] T008 `frontend/src/components/CreateForm.tsx`: label (active, either category), start/end with "use current time", participant from video participants, note → POST, reload. Per US6, FR-011
- [X] T009 `frontend/src/pages/VideoView.tsx`: player (stream URL, missing-file message, `?t=` start), timeline, a "show rejected" toggle, the selected annotation (`?annotation=`) → ReviewPanel, the create form, and a reload after actions. Per US3, FR-012
- [X] T010 Test `frontend/src/test/video.test.tsx`: timeline rows for participants, clicking a presence bar sets the player `currentTime`, rejected hidden until toggled, review priority labeled without %, accept calls the service and re-renders the new status, an edit error message is shown, and create sends frames. Per SC-003

## Phase 5: US4 Participant view

- [X] T011 `frontend/src/pages/Participants.tsx`: a filterable list, and the detail for the chosen participant with per-video presence mini-timelines and annotations, linking to `/videos/:id?t=…&annotation=…`. Per US4, FR-009
- [X] T012 Test `frontend/src/test/participants.test.tsx`: filter, detail lists the videos, and links carry the time. Per SC-003

## Phase 6: Polish

- [X] T013 `frontend/src/pages/NotFound.tsx` and not-found handling for an unknown video or participant. README: a "Running the web app" section in the root `README.md` and `frontend/README.md`. Update `docs/ROADMAP.md` status. Per FR-014, Constitution XI
- [X] T014 Run `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`, and backend `uv run --locked pytest -q`. Then do a manual end-to-end run on a copy of the real DB (SC-004) and check the timeline render time for video 2 (SC-002). Per AGENTS I

## Phase 7: End-to-end (requested by the human: "use Playwright for testing the frontend")

- [X] T015 Add `@playwright/test`, `frontend/playwright.config.ts` (Chromium; web servers: `frontend/e2e/start-backend.sh` on 8001 with a fresh copy of `data/analysis.sqlite` and an `e2e` account, plus Vite on 5174 proxying via `TPA_API`), and `frontend/e2e/workflow.spec.ts` covering sign-in, the dashboard (12 videos, 100 participants, empty-pipeline note), the video view seek, the participant view across 6 videos with `?t=` start, and create → edit → history → participant view → CSV export → reject → show rejected. Traces off, player masked in screenshots. Per SC-003, SC-004, Constitution I
- [X] T016 Fix the defects the e2e run found. (a) Service 500s: `sqlite3.ProgrammingError` when FastAPI ran `get_db` and the route on different threads, so `connect_database(..., check_same_thread=False)` is now used for the per-request connection, with a regression test in `backend/tests/test_api.py` that fails without the fix. (b) Review history not refreshed after back-to-back actions in the same second, so the panel now reloads history after each action

## Results (T014)

- Frontend: typecheck ✓, lint ✓ (0 warnings), Vitest 22/22 ✓, build ✓, Playwright 5/5 ✓ (3 consecutive runs).
- Backend: `uv run --locked pytest -q`: 552 passed, 1 skipped, 7 failed. The 7 are the same
  pre-existing or environment-specific failures recorded in spec 002 (macOS case-insensitive FS,
  notebook execution counts at HEAD, hard-coded `/tmp/opencode`).
- SC-004: covered by the Playwright workflow test on real data. SC-002 (timeline render time) was
  not measured separately; in the e2e run the longest video was not timed, while the 152 s video
  rendered and responded instantly.
