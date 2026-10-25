# Implementation Plan: Local Analysis Generation

**Branch**: `005-local-analysis-generation` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

## Summary

`backend/pipeline/local_analysis.py` holds `GenerationConfig` and four stages implementing the
Spec 004 Protocols:

- `PresenceSegmenter`
- `ExpressionAffectAnnotator`
- `ParticipantPositivePriority`
- `ZeroShotActivityAnnotator` (with a pluggable classifier)

`backend/pipeline/frames.py` holds a seek-based, in-memory window decoder.
`scripts/generate_pipeline_output.py` wires the stages to `build_import_file`. The import format
gains optional `pipeline.parameters`.

## Research (measured on the real DB, read-only; timestamps and IDs only)

- **R1 Segmentation defaults.** The sampled-frame cadence median is 0.209 s (5 frames). For
  same-person detection gaps, the median is 0.209 s, p90 1.63 s, p95 7.92 s, and 90.8% are ≤ 2.0 s.
  Gap tolerance **2.0 s** sits at the natural break. Simulated over all 12 videos:
  - set changes only, with tolerance 2 s: 5,319 clips, median 0.7 s (over-segmented);
  - plus a minimum presence run of 1.0 s: 3,004 clips, median 1.5 s;
  - plus a minimum clip of 5 s (merge into the touching previous clip) and a maximum of 60 s:
    **1,173 clips, median 5.0 s, p90 19 s**.
  The defaults are these last values. They are configurable and recorded in the output.
- **R2 Model.** X-CLIP base/16 zero-shot (MIT, 747 MB, 32 frames at 224 px), pinned and already
  integrated. On synthetic frames, one window takes 0.94 s on CPU and 0.23 s on MPS, with identical
  scores. Device auto order is cuda → mps → cpu. Model load takes about 4 s.
- **R3 Decoding.** `VideoRetriever` decodes from frame 0 for every request, which is unusable for
  a 110-minute video. The new decoder seeks to the keyframe before each window, decodes forward,
  rescales to a 224 px short side during decode, and keeps frames only in memory.
- **R4 Sampling.** Windows per clip are `clamp(ceil(duration / 15 s), 1, 4)`, centred evenly. Each
  window spans 4 s around its centre, with 32 frame indices spaced evenly across it and clamped to
  the video. This is deterministic.
- **R5 Activity aggregation.** Per window, the softmax over the K active activity labels
  (uniform = 1/K, about 0.11 for 9). The representative label is the most common top-1 (ties: higher
  mean, then label order), emitted if its mean is ≥ **0.20**. Any other label with mean ≥ **0.30**
  is also emitted. Confidence is the label's mean. These are uncalibrated starting values and are
  recorded.
- **R6 Prompts.** `backend/pipeline/activity_prompts.json` maps the starter labels to
  descriptive prompts (data, not code). Labels without an entry fall back to the existing template
  "A video of people {label}.". The prompt file's SHA-256 is recorded.
- **R7 Config provenance.** `pipeline.parameters` is optional in the import format and validated
  as flat scalars. Storage is unchanged: `ImportRun.input_sha256` identifies the exact file that
  carries them. No schema change.

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I. Local-only | ✅ | Local model and decoding. Frames stay in memory. No uploads. The agent never views frames, and validation is numerical |
| II. Anonymous identity | ✅ | Existing IDs only. No identity work |
| III. Minimization / ethics | ✅ | Affect is labeled "visible … affect" as an observation, and its confidence is the raw mean score. Priority is a ranking heuristic with a documented formula (Constitution IV requires formula documentation, done here and in D026) |
| IV. Humans decide | ✅ | Everything imports as AI/UNREVIEWED. Confidence and priority are separate |
| V. Protection | ✅ | Generation writes no review table. The Spec 004 importer enforces protection |
| VI. Labels as data | ✅ | Activity candidates come from active DB labels. Prompts come from a data file |
| VII. Stage interfaces | ✅ | Each stage implements its Protocol, and the classifier is injected |
| IX. Visible failure | ✅ | Missing video file or disabled activity is recorded in parameters and reported by the CLI. A failed run writes no file |
| X. Tests | ✅ | Synthetic stage tests without the model. A decoder test on a synthetic video. A real-model smoke test skips without the cache |
| XI. Reproducible | ✅ | Pinned model revision. Config recorded |

## Files

```text
backend/analysis_db/pipeline_import.py     + PipelineInfo.parameters (optional)
backend/pipeline/contracts.py              + PipelineMetadata.parameters
backend/pipeline/builder.py                passes parameters
backend/pipeline/frames.py                 new: window decoder
backend/pipeline/local_analysis.py         new: config + four stages
backend/pipeline/activity_prompts.json     new
backend/scripts/generate_pipeline_output.py  new
backend/tests/test_local_analysis.py       new
frontend/e2e/generated.spec.ts + config project (real-data generated file, disposable DB)
```
