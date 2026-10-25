# Feature Specification: Review Data Import Pipeline (Infrastructure Only)

**Feature Branch**: `004-clip-annotation-pipeline`

**Created**: 2026-10-25

**Status**: Draft

**Input**: Human direction (2026-10-25): "Build the full pipeline and application support so it is
ready for activity, affect, and clip data when that data becomes available, but do not generate
any of that data yet." No model runs, no clip generation from detections, no affect aggregation,
and no population of the real database. The actual generation is a later feature (D024).

## Overview

A future pipeline will produce review clips, activity annotations, per-person visible-affect
annotations, model confidences, and review-priority scores. This feature builds everything
needed to receive that output safely:

- a documented import file format and its validation;
- an importer that stores it through the Spec 001 protected-import rules;
- an audit record of each import;
- typed interfaces for the future generation stages, plus a loader for the machine signals those
  stages will read;
- service and application support for showing imported clips and review priority.

The application keeps working as it does today when no such data exists. It never fabricates
labels.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import pipeline output safely (Priority: P1)

A team member who has run a future pipeline imports its output file with one local command. The
command validates the whole file and then stores its clips and annotations. All new annotations
start as AI suggestions awaiting review. Running the same file again changes nothing. Anything a
human has already reviewed stays exactly as the human left it.

**Independent Test**: Import a synthetic output file into a database copy, re-import it, review
one annotation, import a changed version, and check counts and protected rows.

**Acceptance Scenarios**:

1. **Given** a valid file with clips (span, participants, priority) and annotations (activity and
   affect, with confidences), **When** imported, **Then** every clip and annotation is stored, and
   the annotations are source AI and status UNREVIEWED.
2. **Given** the same file imported twice, **When** the second import runs, **Then** nothing is
   inserted or changed, and it reports everything unchanged.
3. **Given** an annotation a reviewer has accepted, edited, rejected, or deferred, **When** a newer
   file changes that annotation, **Then** the reviewed annotation is untouched and counted as
   protected.
4. **Given** a clip holding a reviewed annotation, **When** a newer file changes that clip, **Then**
   the clip is untouched and counted as protected.
5. **Given** a later file that omits clips or annotations from an earlier one, **When** imported,
   **Then** nothing is deleted.
6. **Given** a file with any invalid record (unknown participant, unknown video, unknown label,
   span beyond the video, confidence outside 0–1, negative priority, duplicate key), **When**
   imported, **Then** nothing from the file is stored, and the error names the record.

---

### User Story 2 - Multi-label, multi-person output (Priority: P1)

One clip can hold several participants. Each participant can carry several annotations, for
example two activities plus one visible-affect observation. A clip can also carry clip-level
activity annotations with no participant. All of them are stored as separate records.

**Acceptance Scenarios**:

1. **Given** a clip with three participants, two clip-level activities, and per-person affect
   annotations, **When** imported, **Then** the clip lists all three participants and every
   annotation is a separate record linked to the clip.
2. **Given** a clip-level annotation without an explicit span, **When** imported, **Then** it takes
   the clip's span.
3. **Given** affect annotations, **When** imported, **Then** they use the observation labels
   "Visible Positive Affect", "Visible Neutral Affect", and "Visible Negative Affect", and their
   confidence is stored separately from the clip's review priority.

---

### User Story 3 - Know what was imported and from where (Priority: P2)

Staff and developers can see which pipeline runs have been imported: the pipeline name and
version, the models and revisions it declares, when it was generated and imported, and how many
records were inserted, updated, unchanged, or protected.

**Acceptance Scenarios**:

1. **Given** a successful import, **When** the import history is read, **Then** it shows the run
   with its metadata and counts.
2. **Given** a failed import, **When** the import history is read, **Then** it has no entry for that
   run, and the command reported the failure.
3. **Given** the dashboard, **When** no import has happened, **Then** it says so plainly.

---

### User Story 4 - Future stages plug into a fixed contract (Priority: P2)

A developer writing the later generation feature implements small typed stages: a clip segmenter,
activity annotators, affect annotators, and a priority scorer. A provided loader reads one video's
machine signals (detections with participants and frame times, expression scores, and any
activity predictions) from the database without changing it. A provided builder turns the stages'
proposals into a valid import file with deterministic keys. Swapping one stage needs no changes
elsewhere.

**Acceptance Scenarios**:

1. **Given** synthetic stages, **When** the builder runs, **Then** it produces a file that passes
   validation and imports cleanly.
2. **Given** the same signals and stages, **When** the builder runs twice, **Then** the two files
   are identical, including every key.
3. **Given** the signal loader, **When** it reads a video, **Then** the database is unchanged.

---

### User Story 5 - The application shows imported clips and priority (Priority: P1)

When clips exist, staff see a review queue on the dashboard (highest review priority first, across
videos). In the video view, clicking a clip opens a clip panel with its time span, participants,
review priority with its method, and the clip's annotations, each of which opens the review
panel. The participant view shows the clips a participant appears in. When no clips exist, each of
these places shows a clear empty state.

**Acceptance Scenarios**:

1. **Given** no clips, **When** the dashboard loads, **Then** the review queue says no clips have
   been imported yet. No labels or scores are invented.
2. **Given** imported clips, **When** the dashboard loads, **Then** the queue lists them by review
   priority, with unscored clips last, each linking to the video at the clip's start.
3. **Given** a clip in the video view, **When** it is clicked, **Then** the clip panel shows its
   participants, its review priority labeled as review priority (never a percentage), and its
   annotations. Choosing an annotation opens the review panel.
4. **Given** an imported AI annotation, **When** it is accepted, **Then** source stays AI. **When**
   edited, **Then** source becomes HUMAN. **When** the same file is imported again, **Then** the
   reviewed annotation keeps its reviewed state.

### Edge Cases

- A clip with no participants: allowed (empty stage).
- A clip with no priority score: allowed. It is listed after scored clips.
- An annotation with no confidence: allowed (null). Confidence 0 and 1 are valid.
- A clip-level annotation whose span differs from its clip: refused (Spec 001 FR-030).
- A label that exists but is deactivated: refused for new or update-eligible annotations, and
  ignored for protected ones (Spec 001 behavior).
- A video in the file not present in the database: refused, and nothing from the file is stored.
- A file that names the same key twice: refused.
- Very short spans (one frame) and spans covering the whole video: allowed.
- An unsupported file format version: refused, with the supported version named.

## Requirements *(mandatory)*

### Functional Requirements

**Import format and validation**

- **FR-001**: The system MUST define a versioned import file format (JSON) holding pipeline
  metadata (name, version, declared models with revisions, generation time) and, per video
  (identified by filename): clips (key, start/end frame, participant IDs, optional priority score
  with its method) and annotations (key, label by name and category, start/end frame or the clip's
  span, optional participant, optional clip key, optional confidence).
- **FR-002**: Validation MUST check the whole file before storing anything. Every rule from
  Spec 001 MUST apply, plus: known format version, known videos, existing participants (the
  importer never creates participants), labels resolvable by name and category, confidence in 0–1,
  priority ≥ 0 with a method when present, and keys unique within the file and non-empty.
- **FR-003**: Import MUST be all-or-nothing per file, across all videos in it.
- **FR-004**: Import MUST store records only through the Spec 001 protected-import rules. AI
  annotations start as source AI, status UNREVIEWED. Reviewed annotations and clips holding
  reviewed annotations are never changed. Re-imports upsert by key and never duplicate. Nothing
  is deleted.
- **FR-005**: Import MUST report counts of inserted, updated, unchanged, and protected clips and
  annotations.
- **FR-006**: Labels MUST be referenced by name and category, never hard-coded IDs, so the label
  set stays data.

**Provenance**

- **FR-007**: Each successful import MUST be recorded with pipeline name and version, declared
  models, generation time, import time, a hash of the input file, the source file name, and the
  counts. Failed imports record nothing.
- **FR-008**: The import history MUST be readable through the service by signed-in staff.

**Stage interfaces**

- **FR-009**: The system MUST define typed interfaces for a clip segmenter, activity annotators,
  affect annotators, and a review-priority scorer. Each consumes one video's machine signals and
  returns proposals.
- **FR-010**: A signal loader MUST read one video's detections (participant, frame, time), their
  expression scores, and their activity predictions without writing to the database.
- **FR-011**: A builder MUST combine stage proposals into a valid import file with deterministic
  keys derived from the proposal content. The same inputs MUST produce byte-identical output.
- **FR-012**: This feature MUST NOT include any concrete segmentation, activity, affect, or
  priority algorithm, and MUST NOT run any model.

**Service and application**

- **FR-013**: The service MUST expose clips across videos ordered by review priority, a single clip
  by id, and the import history.
- **FR-014**: The dashboard MUST show a review queue (top clips by review priority) and the latest
  import, with explicit empty states when there are none.
- **FR-015**: The video view MUST let staff open a clip panel (span, participants, review priority
  and method, clip annotations) from the timeline.
- **FR-016**: The participant view MUST show the clips each participant belongs to, per video.
- **FR-017**: Review priority MUST always be labeled as review priority and shown as a plain
  number, never as a percentage or as confidence. Confidence MUST be labeled model confidence.
- **FR-018**: The application MUST NOT display activity or affect labels that are not stored
  annotations.

**Data safety**

- **FR-019**: Development and automated tests MUST NOT write to the tracked
  `data/analysis.sqlite`. End-to-end tests that import synthetic files MUST use a disposable
  database copy.

### Key Entities

- **Import File**: versioned JSON from a pipeline run (see FR-001).
- **Import Run**: audit record of one successful import (FR-007).
- **Video Signals**: read-only view of one video's detections, expression scores, and activity
  predictions.
- **Clip Proposal / Annotation Proposal / Priority Score**: what stages return. The builder turns
  them into an Import File.
- Clips, annotations, labels, and participants are the Spec 001 entities, unchanged.

## Success Criteria *(mandatory)*

- **SC-001**: A synthetic file with ≥ 3 videos, ≥ 200 clips, and ≥ 1,000 annotations imports in
  under 5 seconds on a team laptop. Re-importing it reports 0 inserted and 0 updated.
- **SC-002**: In automated tests covering every review status, 0 reviewed annotations or protected
  clips change on re-import.
- **SC-003**: The real database copy shows the current empty states with no errors, and a
  disposable copy with a synthetic import shows the queue, clip panel, and review flow, verified by
  Playwright.
- **SC-004**: Listing clips by priority and a participant's clips returns in under 1 second with
  the synthetic load.

## Assumptions

- Positions in the file are frames, matching the stored data. Seconds are derived on read.
- Keys are chosen by the producer. The builder derives them from content (video, kind, span,
  participant, label), so a changed clip boundary yields a new key, and the old record is retained
  (D016). Stale-record policy is the later generation feature's job.
- The import history is an audit log for successful imports. It is not a background job system.
  Imports run synchronously from the command line.
- Synthetic fixtures may name real video filenames and real anonymous participant IDs so they can
  run against a disposable copy of the real database. They are clearly marked synthetic in their
  pipeline name, and they never reach the tracked database.
- Out of scope: concrete algorithms, model execution, generating data from real signals, label
  management screens, and video upload.
