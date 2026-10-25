# Live Ingestion Progress Implementation Plan

> **For agentic workers:** Use executing-plans and test-driven-development inline.

**Goal:** Show real laptop activity inference progress on Data Ingestion every three seconds.

**Architecture:** The existing authenticated `/api/processing` endpoint reads the same canonical SQLite database as the optimized inference worker. The existing page polls serially every three seconds after each request completes, retains the last successful counts on errors, and shows the last successful refresh time.

**Tech Stack:** Existing React/TypeScript/Vite, FastAPI, Python, SQLite. No new dependencies.

## Constraints

- Preserve existing staff accounts, sessions, reviews, clip membership and all completed inference.
- Preserve GPU FP32, batch size 2, 32 samples over 15 seconds, 65% rule, top-10 priority and 1,000-instance reporting chunks.
- Source of truth: `/mnt/storage/Projects/ai_for_good_2026/data/analysis.sqlite`.
- No SQLite commit or push. Respect current unrelated local frontend edits.
- No video/frame screenshots or participant media inspection.
- Keep existing visual layout, tokens and terminology.

## Tasks

- [x] Add tests to `frontend/src/test/ingestion.test.tsx`: after three seconds a successful response updates the activity bar and refresh timestamp; a rejected refresh retains counts and displays retry status; a pending request prevents overlapping polls; unmount clears timers.
- [x] Run `npm test -- src/test/ingestion.test.tsx` and observe failures for the new behavior.
- [x] Modify `frontend/src/pages/Ingestion.tsx` to use a scoped polling effect, a post-request timeout of 3,000 ms, successful timestamp state, error recovery and cleanup. Keep initial Loading/ErrorState and current data visible during refreshes.
- [x] Run focused/full frontend tests, type check, lint/build and the bounded UI detector.
- [x] Reuse `analysis_db.activity_handoff.merge_activity_results` from the inference worktree to import completed Activity rows into the canonical database. Verify staff/session/review fingerprints and SQLite integrity before/after.
- [x] Verify the running backend's database configuration and frontend proxy; use the main application code with the canonical database.
- [x] Launch `run_fast_activity.py --db /mnt/storage/Projects/ai_for_good_2026/data/analysis.sqlite --priority-top-people 10 --chunk-size 1000` from the inference worktree. Keep persistent shared indexes/model caches.
- [x] Verify authenticated `/api/processing` totals increase across committed batches and provide the live URL and log path.

## Completion evidence

- Imported 3,358 result updates; all staff/session/review/clip fingerprints matched.
- 65 frontend tests pass; type checking, lint and production build pass.
- Updated an existing dashboard test to accept the user's local Data View capitalization.
- UI detector: zero findings for the changed ingestion page.
- DOM-only browser checks on desktop/mobile verified the visible page and changing
  successful refresh timestamp. Used installed headless Chromium explicitly because
  the Playwright version's default browser binary was unavailable. No images,
  screenshots, videos or traces were captured.
- Authenticated real API counts increased from 13,791 to 13,801 while engagement
  and clip completion stayed at their actual values (50,514 and 12).
- Existing backend/frontend processes continue serving; inference PID 13526 writes
  the shared database. A temporary verification session was removed after checking.
- Setup/resume documentation: `docs/LIVE_DEMO.md`.
