# Data Model: Review Data Import Pipeline

## ImportRun (new, additive in `backend/db/schema.sql`)

| Column | Type | Rules |
|---|---|---|
| run_id | INTEGER PK | |
| pipeline_name | TEXT NOT NULL | non-empty |
| pipeline_version | TEXT NOT NULL | non-empty |
| models_json | TEXT NOT NULL | JSON array of `{name, revision}` as declared |
| generated_at | TEXT | as declared by the file |
| imported_at | TEXT NOT NULL | UTC ISO-8601 |
| source_name | TEXT NOT NULL | input file name (no directory) |
| input_sha256 | TEXT NOT NULL | hash of the file bytes |
| counts_json | TEXT NOT NULL | the `ImportResult` counters |

Written in the same transaction as the import. Never updated or deleted by application code
(triggers enforce this, matching ReviewEvent).

## In-memory types

- `ImportFile`, `PipelineInfo`, `VideoEntry`, `ClipEntry`, `AnnotationEntry`, `LabelRef`,
  `PriorityEntry`: Pydantic, `extra="forbid"` (contracts/import-format.md).
- `VideoSignals(video_id, filename, fps, frame_count, detections)`.
- `DetectionSignal(detection_id, person_id, frame_number, seconds, expression, activity)`. Here
  `expression` is `ExpressionScores(positive, neutral, negative) | None` and `activity` is
  `ActivitySignal(label, start_frame, end_frame, confidence) | None`.
- `ClipProposal(start_frame, end_frame, person_ids)`.
- `AnnotationProposal(label_name, label_category, start_frame, end_frame, person_id, clip_index,
  confidence)`. `clip_index` points into the segmenter's list.
- `ImportRun` dataclass mirroring the table, with models and counts decoded.
