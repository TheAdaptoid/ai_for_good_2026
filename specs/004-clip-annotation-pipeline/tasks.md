# Tasks: Review Data Import Pipeline (Infrastructure Only)

## Phase 1: Foundational

- [X] T001 Add the `ImportRun` table plus no-update/no-delete triggers to `backend/db/schema.sql`, and add `IMPORT_TABLES`, the `ImportRun` dataclass, and `ImportResult.unchanged`/`clips_unchanged` to `backend/analysis_db/contracts.py`. Include ImportRun in the `init_db.py` counts and update `backend/tests/test_cli.py`. Per FR-007
- [X] T002 Split `_import_video` out of `import_machine_output` in `backend/analysis_db/annotations.py` (behavior unchanged; unchanged counts now reported). Add `clip_id` and `limit` filters to `list_clips` and add `get_clip`. Update `specs/001-annotation-data-model/contracts/python-api.md`. Existing tests must pass unchanged, and new tests cover unchanged counts and `get_clip`. Per plan D1

## Phase 2: US1 + US2 Import (P1)

- [X] T003 `backend/analysis_db/pipeline_import.py`: Pydantic file models, `parse_import_file(text)`, `import_file(connection, parsed, *, source_name, sha256) -> ImportRun` (resolution per D2, one transaction, audit row), and `list_import_runs`. Per FR-001–FR-007
- [X] T004 `backend/tests/test_pipeline_import.py` with synthetic DB and files covering: multi-clip, multi-person, multi-label import (AI/UNREVIEWED); clip span default; idempotent re-import (0 inserted/updated, unchanged counted); every review status protected on re-import; protected clip; omitted records retained; all-or-nothing across videos for each invalid case (unknown video, participant, label, out-of-range span, confidence, negative priority, priority without method, duplicate key, duplicate filename, bad format, unknown field); inactive label refused but tolerated when protected; rejected annotations stay rejected and hidden by default; confidence 0/1 and null; empty participants; unscored clip ordering; one-frame and whole-video spans; ImportRun recorded only on success; SC-001 timing at ≥ 1,000 annotations. Per US1, US2, SC-001, SC-002
- [X] T005 `backend/scripts/import_pipeline_output.py` (`--input`, `--db` default working DB, prints counts, exit 1 with the reason on failure, never a traceback) with CLI tests in `backend/tests/test_pipeline_import.py`. Per FR-003, FR-005, Constitution IX

## Phase 3: US4 Stage contracts (P2)

- [X] T006 `backend/pipeline/contracts.py`, `stages.py` (Protocols), `signals.py` (`load_video_signals`), and `builder.py` (`stable_key`, `build_import_file`). Per FR-009–FR-012, D3–D5
- [X] T007 `backend/tests/test_pipeline_builder.py`: the loader returns detections with expression/activity or None and leaves the DB byte-identical; the builder with synthetic stages validates and imports cleanly; deterministic byte-identical output and stable keys; a category mismatch from an annotator is refused; duplicate proposals are refused; a scorer returning None gives an unscored clip; clip-level proposals take the clip span. Per US4

## Phase 4: US3 + US5 Service and app (P1/P2)

- [X] T008 `backend/api/routes.py`: `GET /api/clips` with `limit`, `GET /api/clips/{clip_id}` (404 unknown), and `GET /api/imports`. Tests in `backend/tests/test_api.py`, with the auth sweep still covering all routes. Regenerate `frontend/src/api/schema.d.ts`. Per FR-008, FR-013
- [X] T009 Frontend: `client.ts` (`clip`, `imports`, clips `limit`), `components/ReviewQueue.tsx`, the latest import on `pages/Dashboard.tsx`, `components/ClipPanel.tsx` with `?clip=` in `pages/VideoView.tsx` (Timeline clip click selects), and clips per video in `pages/Participants.tsx`. Every state is explicit and nothing is fabricated. Per FR-014–FR-018
- [X] T010 Vitest: dashboard queue empty vs populated (ordering, title join, no %); latest import line; clip panel shows participants, priority and method, and annotations, and opens the review panel; participant clips; no labels rendered when there are no annotations. Per US5
- [X] T011 Playwright: a second project `imported` in `frontend/playwright.config.ts`. `frontend/e2e/start-backend.sh` accepts a port and an optional synthetic file, imported into its disposable DB copy. `frontend/e2e/fixtures/synthetic-import.json` is marked synthetic. `frontend/e2e/imported.spec.ts` covers: dashboard nonzero counts and queue; clip panel; participant clips; accept keeps AI; edit makes HUMAN with history reviewer `e2e`; re-import via CLI does not overwrite; CSV/JSON export shows current state. The existing `workflow.spec.ts` stays as the empty-state project. Per SC-003

## Phase 5: Polish

- [X] T012 Docs: `backend/README.md` (import command and format link), `docs/DECISIONS.md` (D024 infrastructure-first split, D025 import file format and key rule), and `docs/ROADMAP.md` status. Per Constitution XI
- [X] T013 Run all checks: backend `uv run --locked pytest -q`; frontend typecheck, lint, Vitest, build, and Playwright (both projects). Record SC-001 and SC-004 measurements in this file and confirm `data/analysis.sqlite` is unchanged. Per AGENTS I

## Results (T013)

- Backend `uv run --locked pytest -q`: 603 passed, 1 skipped, 7 failed. The 7 are the same
  pre-existing or environment-specific failures recorded in specs 002/003 (macOS case-insensitive FS;
  5 notebook tests because the committed notebook at HEAD carries execution counts; hard-coded
  `/tmp/opencode`). None touch code changed here.
- Frontend: typecheck ✓, lint ✓, Vitest 25/25 ✓, build ✓, Playwright 10/10 ✓ (`current` 5 + `imported` 5,
  three consecutive runs).
- SC-001: a synthetic load on a disposable copy of the real DB (12 videos, 2,400 clips, 9,528
  annotations) imported in 0.45 s, and the re-import took 0.41 s (0 inserted, 9,528 unchanged).
  The test-suite load (240 clips, ≥ 1,000 annotations) imports in 0.04 s.
- SC-004 on that load: review queue (top 10 by priority) 2.4 ms, all clips by priority 5.0 ms,
  one participant's clips 0.1 ms.
- `data/analysis.sqlite` MD5 unchanged (848b8938…). No model was run and no real data was
  generated. E2E synthetic imports go only into `frontend/e2e/.tmp/` copies.
- Defect found and fixed during implementation: when a clip is protected and a newer file changes
  its span, its unreviewed span-less clip-level annotations failed validation. They now take the
  stored clip span (test `test_reviewed_annotations_and_their_clips_are_protected`).

## Convergence

Checked FR-001–FR-019, US1–US5, SC-001–SC-004, and Constitution I–XII. No remaining gaps:
CONVERGED.
