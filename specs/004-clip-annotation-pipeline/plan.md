# Implementation Plan: Review Data Import Pipeline (Infrastructure Only)

**Branch**: `004-clip-annotation-pipeline` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

## Summary

- `analysis_db/pipeline_import.py`: Pydantic models for the versioned import file (format
  `tpa-review-import/1`), label/video resolution, and `import_file()`. That function stores every
  video in **one** transaction through a refactored Spec 001 import core, then appends an
  `ImportRun` audit row.
- `pipeline/`: stage Protocols, the read-only signal loader, and the deterministic builder. There
  are no concrete algorithms.
- Service: `GET /api/clips/{id}` and `GET /api/imports`. `GET /api/clips` already orders across
  videos by priority.
- App: a dashboard review queue and latest import, a video-view clip panel, and participant clips.
- CLI: `scripts/import_pipeline_output.py --input file.json [--db]`.

## Technical Context

**Language/Version**: Python 3.13, TypeScript strict

**Primary Dependencies**: Pydantic 2 (already installed via FastAPI). No new dependencies.

**Storage**: `backend/db/schema.sql` gains an `ImportRun` table, additive only

**Testing**: pytest with synthetic DBs and files. Vitest. Playwright gets a second project
("imported") that runs against a disposable DB copy with a synthetic import.

**Performance Goals**: SC-001 (≥ 1,000 annotations import < 5 s) and SC-004 (< 1 s queries)

**Constraints**: no model execution, no generation from real signals, tracked DB never written

## Design

### D1 — One transaction per file

Split `import_machine_output` in `analysis_db/annotations.py` into a private
`_import_video(connection, video_id, clips, annotations, now) -> dict[str, int]` (no
transaction handling) and the existing public wrapper, whose behavior is unchanged. `import_file`
opens `BEGIN IMMEDIATE`, calls `_import_video` per video, inserts the `ImportRun`, and commits.
Any error rolls back the whole file (FR-003).

`ImportResult` gains `unchanged` and `clips_unchanged` (default 0, appended so existing callers
are unaffected). The Spec 001 python-api contract is updated to match.

### D2 — Resolution before import

Videos are resolved by `Video.filename`. Labels are resolved by `(category, name)` (NOCASE),
**including inactive labels**: Spec 001 then refuses inactive labels only for new or
update-eligible rows and skips protected ones (T057 behavior). Unknown video, label, or
participant raises `DataError` naming the file path (`videos[i].annotations[j]`).

A clip-level annotation with no span takes its clip's span.

### D3 — Keys

Keys are stored exactly as given and must be globally unique (Spec 001 `UNIQUE`). The builder
derives them as `"{pipeline}:{kind}:{sha256(json(content))[:20]}"`. The content is video filename,
span, and members for clips, plus label category/name and person for annotations. The pipeline
version is deliberately excluded, so a newer version updates unreviewed rows in place.

### D4 — Stage contracts (`backend/pipeline/stages.py`)

```python
class ClipSegmenter(Protocol):
    def segment(self, video: VideoSignals) -> list[ClipProposal]: ...
class ClipAnnotator(Protocol):          # activity annotators and affect annotators
    def annotate(self, video: VideoSignals, clips: Sequence[ClipProposal]) -> list[AnnotationProposal]: ...
class PriorityScorer(Protocol):
    method: str                          # e.g. "positive-affect-per-participant@1"
    def score(self, video: VideoSignals, clip: ClipProposal,
              annotations: Sequence[AnnotationProposal]) -> float | None: ...
```

`build_import_file(info, videos, segmenter, activity=[...], affect=[...], scorer=None)` checks
that activity annotators return only `activity` labels and affect annotators only `observation`
labels, assigns keys, and returns the validated `ImportFile`. `ImportFile.to_json()` sorts keys
for byte-stable output.

### D5 — Signal loader (`backend/pipeline/signals.py`)

`load_video_signals(connection, video_id) -> VideoSignals` runs SELECTs only, joining
FaceDetection, Frame, Engagement, and Activity. A detection with no expression or activity row
carries `None` for it.

### D6 — App

The dashboard fetches `/api/clips?order=priority&limit=10` and `/api/imports`. The video view
adds `?clip=` selection, and `ClipPanel` loads `/api/annotations?clip_id=`. The participant view
loads `/api/clips?person_id=`.

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I. Local-only | ✅ | No media touched. Synthetic fixtures. No network. AGENTS.md now carries the agent media rule |
| II. Anonymous identity | ✅ | Importer never creates participants. IDs are preserved |
| III. Minimization | ✅ | Stores only Spec 001 fields plus import provenance |
| IV. Humans decide | ✅ | Imports are AI/UNREVIEWED. Priority and confidence stay separate and are labeled. No fabricated labels |
| V. Current state/history | ✅ | Spec 001 protected upsert. No deletes. All-or-nothing per file |
| VI. One model | ✅ | Labels are resolved by name/category from data. Multi-label |
| VII. Boundaries | ✅ | Each stage has its own Protocol. The import goes through `analysis_db`. Routes stay thin |
| VIII. Security | ✅ | New endpoints are behind the session dependency. The file is validated with Pydantic |
| IX. Visible failure | ✅ | A failed import stores nothing and the CLI exits non-zero with the reason. Successful runs are audited |
| X. Tests | ✅ | Synthetic coverage of every rule. Endpoint tests. Vitest and Playwright for both states |
| XII. YAGNI | ✅ | No algorithms, no job queue |

## Files

```text
backend/db/schema.sql                       + ImportRun
backend/analysis_db/contracts.py            + ImportRun dataclass; ImportResult.unchanged/clips_unchanged
backend/analysis_db/annotations.py          _import_video split; list_clips(clip_id=, limit=); get_clip
backend/analysis_db/pipeline_import.py      new
backend/pipeline/{__init__,contracts,stages,signals,builder}.py   new
backend/scripts/import_pipeline_output.py   new
backend/api/routes.py                       + /clips/{id}, /imports, /clips limit
backend/tests/test_pipeline_import.py, test_pipeline_builder.py, test_api.py (+)
frontend/src/api/{client.ts,schema.d.ts}
frontend/src/components/{ClipPanel,ReviewQueue}.tsx; pages Dashboard/VideoView/Participants
frontend/src/test/{dashboard,video,participants}.test.tsx (+)
frontend/e2e/{fixtures/synthetic-import.json,imported.spec.ts,start-backend.sh}, playwright.config.ts
```

## Complexity Tracking

| Item | Why | Simpler alternative rejected |
|---|---|---|
| ImportRun table | Constitution IX visibility and FR-007 provenance | Logging to stdout only leaves no record of what is in the DB |
| Second Playwright project | The future state must be proven in a real browser (SC-003) without touching real data | Mock-only tests cannot catch service/UI integration gaps |
