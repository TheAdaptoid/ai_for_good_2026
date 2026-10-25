# Feature Specification: Local Analysis Generation

**Feature Branch**: `005-local-analysis-generation`

**Created**: 2026-10-25

**Status**: Draft

**Input**: Human direction (2026-10-25). Generate real review clips, activity annotations,
visible-affect annotations, and review-priority values locally, as a Spec 004 import file. This is
the generation half of the split recorded in D024.

## Overview

A local command reads the analysis database read-only, runs four stages, and writes one Spec 004
import file. Importing it remains a separate, explicit step with the existing importer. The four
stages are clip segmentation from participant presence, activity inference with a local
open-source video model, per-person visible-affect aggregation, and review-priority scoring.
Nothing leaves the machine. No review table is written by generation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a reviewable file for chosen videos (Priority: P1)

A team member runs one command against the working database for one or more videos and gets a
JSON file. The file contains review clips with participants and review priority, clip-level
activity annotations, and per-person visible-affect annotations, all with model confidences and
the pipeline's model and configuration metadata. The existing importer accepts it unchanged.

**Acceptance Scenarios**:

1. **Given** the working database and a video name, **When** generation runs, **Then** a file is
   written that passes Spec 004 validation and imports with the existing command.
2. **Given** the same database, model, and configuration, **When** generation runs twice with the
   same generation time, **Then** the two files are identical.
3. **Given** any run, **When** it finishes, **Then** the source database is byte-identical to
   before. It is opened read-only.
4. **Given** no output path, **When** the command runs, **Then** it refuses to run. Nothing is
   imported automatically.

---

### User Story 2 - Clips follow who is on screen (Priority: P1)

Clips start when the set of visible participants changes. Brief detection gaps do not split a
participant's presence. Flickers too short to be meaningful do not create clips. Very short set
changes are absorbed into the neighbouring clip. Long unchanged stretches are split.

**Acceptance Scenarios**:

1. **Given** one participant visible throughout, **Then** clips cover their presence, split only at
   the maximum clip length.
2. **Given** a participant entering or leaving for longer than the minimum clip length, **Then** a
   new clip starts at the change.
3. **Given** a gap in one participant's detections no longer than the gap tolerance, **Then** their
   presence is continuous across it.
4. **Given** a gap longer than the tolerance with nobody on screen, **Then** no clip covers the gap.
5. **Given** a video with no detections, **Then** it yields no clips.

---

### User Story 3 - Per-person visible affect (Priority: P1)

For each participant in each clip, the three per-detection expression scores are averaged over
that participant's detections in the clip. The highest average becomes the label (Visible
Positive, Neutral, or Negative Affect), and that average is the annotation's confidence. Raw scores
are never changed.

**Acceptance Scenarios**:

1. **Given** a participant whose positive average is highest, **Then** they get "Visible Positive
   Affect" with confidence equal to that average.
2. **Given** a tie, **Then** the result is deterministic. Neutral is preferred, then Positive, then
   Negative.
3. **Given** a participant with no expression scores in the clip, **Then** they get no affect
   annotation, and nothing is invented.

---

### User Story 4 - Review priority per clip (Priority: P1)

Each clip with affect evidence gets `priority = 1.1^N × mean over participants of (that
participant's mean positive score in the clip)`. N is the number of unique participants in the
clip. The method is recorded as `participant_count_positive_affect_v1`.

**Acceptance Scenarios**:

1. **Given** two participants with means 0.8 (10 detections) and 0.2 (1 detection), **Then**
   priority = 1.21 × 0.5 = 0.605, not weighted by detection count.
2. **Given** a clip with no expression scores at all, **Then** it has no priority (not computed).
3. **Given** many participants with high positive means, **Then** the priority can exceed 1, and it
   is never shown as a percentage.

---

### User Story 5 - Activity from a local video model (Priority: P1)

For each clip, a few short windows are sampled deterministically and classified zero-shot against
the active activity labels in the database. The label that wins most often across windows is the
clip's representative activity, if it has enough support. Other labels with strong average support
are also emitted. Confidence is the label's average candidate-relative score.

**Acceptance Scenarios**:

1. **Given** windows that mostly favour one label above the support threshold, **Then** exactly
   that clip-level activity annotation is emitted.
2. **Given** two labels both above the multi-label threshold, **Then** both are emitted as separate
   annotations.
3. **Given** scores spread near uniform (below the support threshold), **Then** no activity
   annotation is emitted.
4. **Given** activity inference disabled or impossible (no video file), **Then** clips and affect
   are still generated, activity is absent, and the file records why.

---

### User Story 6 - The populated app works end to end (Priority: P1)

After importing a generated file for real videos into a working copy, staff see nonzero clips, a
priority-ranked queue, generated activity and affect annotations on timelines and the participant
view. Staff can accept (source stays AI), edit (source becomes HUMAN, history records the
reviewer), and export. Regenerating and re-importing never overwrites reviewed work.

### Edge Cases

- Participant sets that change rapidly: changes shorter than the minimum clip length merge into the
  previous clip, whose members become the union.
- A participant whose qualifying presence overlaps a clip but who has no detection inside it: they
  are a member, but they get no affect annotation and do not count toward the priority mean. They
  do count in N.
- Video frame count unknown: clips are bounded by the last detection frame.
- Activity window near the start or end of a video: clamped to the video's frames.
- Tie between activity labels for most-common: higher mean score wins, then label order.

## Requirements *(mandatory)*

- **FR-001**: Generation MUST open the source database read-only and MUST write only the output
  file.
- **FR-002**: Output MUST validate against the Spec 004 format and be importable by
  `scripts/import_pipeline_output.py` without changes to the importer's rules.
- **FR-003**: Output metadata MUST record pipeline name and version, model ID and revision (when
  activity ran), the device, and every configuration value (segmentation, sampling, thresholds,
  prompts hash, scoring method).
- **FR-004**: Segmentation MUST use participant presence from detections: per-participant runs
  (gap tolerance), minimum presence run, set-change boundaries, minimum clip length (merge into
  the previous touching clip with member union), and maximum clip length (even split). Defaults
  come from measured detection cadence (plan R1).
- **FR-005**: Affect MUST be per participant per clip from that participant's own detections, with
  argmax of mean scores, a deterministic tie order, and confidence equal to the winning mean.
- **FR-006**: Priority MUST be exactly `1.1^N × mean(per-participant mean positive)`, N = unique
  participants, method `participant_count_positive_affect_v1`, and None when no participant has
  expression scores.
- **FR-007**: Activity MUST use a local open-source zero-shot video model over deterministic
  sampled windows, against the active activity labels from the database, with prompts held as data.
  It MUST emit the representative (most-common) label and any further labels meeting the
  multi-label threshold, and MUST emit nothing below the support threshold.
- **FR-008**: Each stage MUST implement its Spec 004 Protocol and be testable without the model
  (an injected classifier).
- **FR-009**: Keys MUST be the Spec 004 deterministic content keys. Generation MUST be
  deterministic for fixed inputs, model, configuration, and generation time.
- **FR-010**: The command MUST support selecting videos, the device (auto/cuda/mps/cpu), disabling
  activity, the configuration values, and a fixed generation time. It MUST refuse to run without an
  output path.
- **FR-011**: No media, frames, or crops MAY be written to disk or leave the machine. Frames live
  only in memory during inference.
- **FR-012**: The import format gains an optional `pipeline.parameters` object (flat scalar
  values) to carry FR-003 configuration. Existing files stay valid.

## Success Criteria *(mandatory)*

- **SC-001**: For at least two real videos, generation, import, and the populated app pass the
  Playwright flow in US6.
- **SC-002**: Generation time, inference time, clip and annotation counts, file size, import time,
  and API query times are measured and recorded for the real-data run.
- **SC-003**: All stage logic is covered by synthetic tests that run without the model, including
  the explicit priority formula and the detection-frequency bias case.

## Assumptions

- The model is `microsoft/xclip-base-patch16-zero-shot` at the pinned revision (MIT), already used
  by `activity_classification`. It is about 750 MB, cached in `backend/.cache/huggingface`
  (git-ignored), and downloaded once with the existing command.
- Activity confidence is the candidate-relative softmax averaged over windows. It is not a
  calibrated probability, and its thresholds are documented starting values.
- Activity annotations are clip-level (no participant), matching D017's representative clip
  activity. Per-person activity is out of scope.
- Participant membership of a merged clip is the union of members present for at least the
  minimum presence run within it.
