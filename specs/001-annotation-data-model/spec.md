# Feature Specification: Review and Annotation Data Model

**Feature Branch**: `001-annotation-data-model`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "Review and annotation data model for the TPA video review platform.
Define the single current-state annotation model that video timelines, anonymous participant
timelines, the human-review workflow, search, and JSON/CSV exports will all read. [...] Must
include migrating the existing Activity and Engagement tables and the existing analysis records
into the new model without losing them. Out of scope: API endpoints, UI views, authentication
implementation, running new models, review-priority scoring."

## Overview

TPA staff need one trustworthy record of what happens in their program footage. Each record says
who appears (an anonymous participant ID), when (a time span in a video), what is happening (an
activity or an observation), and how far a human has reviewed it. Machine-generated suggestions
seed these records. Staff review then confirms, corrects, rejects, or defers them. A permanent
history shows how every record got to its current state. Every later screen and export reads
these same records.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One record serves every view (Priority: P1)

A staff member looks at participant P007 singing a solo in VID003 from 12:14 to 12:48. The
moment carries three labels: Singing, Solo Performance, and Sustained Participation. The same
records answer "what happens in VID003 at 12:30?", "where does P007 appear and what are they
doing?", and "what still needs review?". No record exists in more than one place.

**Why this priority**: Every other feature (timelines, participant view, review, export) is built
on this. Without it, nothing else can be demonstrated.

**Independent Test**: Load a sample set of annotations. Query them by video and time range, by
participant, by label, and by review status. Confirm each query returns the same underlying
records, with all labels for a multi-label moment.

**Acceptance Scenarios**:

1. **Given** a segment with one participant and three labels, **When** records are queried by
   video, **Then** all three labels are returned for that time span.
2. **Given** the same data, **When** records are queried by participant, **Then** the same three
   records are returned (same identifiers), not copies.
3. **Given** a segment with two participants performing together, **When** records are queried by
   either participant, **Then** each participant's records are returned and the shared time span
   is visible for both.
4. **Given** an annotation that applies to the whole group rather than a specific person, **When**
   records are queried by video, **Then** it is returned with no participant attached.
5. **Given** activity labels and observation labels on the same segment, **When** records are
   filtered by category, **Then** activities and observations are returned separately.

---

### User Story 2 - Reviewer confirms or corrects a suggestion (Priority: P1)

A reviewer looks at a machine suggestion: "Singing", source AI, unreviewed. They can accept it,
edit it (for example change it to "Spoken Performance", or adjust its time span), reject it, or
defer it with a note. The record immediately shows the new current state, and an entry is added
to the review history.

**Why this priority**: Human review is the core of the product. Staff judgment is authoritative,
and corrections must stick.

**Independent Test**: Apply each of the four review actions to sample annotations. Check the
resulting current value, source, and review status. Check that exactly one history entry is
appended per action.

**Acceptance Scenarios**:

1. **Given** an AI annotation "Singing" (UNREVIEWED), **When** a reviewer accepts it, **Then** the
   label stays "Singing", source stays AI, status becomes ACCEPTED, and one history entry
   records the acceptance.
2. **Given** an AI annotation "Singing", **When** a reviewer changes the label to "Spoken
   Performance", **Then** the current label is "Spoken Performance", source becomes HUMAN, status
   becomes EDITED, and the history entry records both the previous and resulting values.
3. **Given** an AI annotation, **When** a reviewer rejects it, **Then** source is unchanged,
   status becomes REJECTED, and it no longer appears in default views or exports.
4. **Given** an AI annotation, **When** a reviewer defers it with a note, **Then** the value and
   source are unchanged, status becomes DEFERRED, and the note is kept in history.
5. **Given** an annotation that was edited earlier (source HUMAN), **When** a reviewer later
   accepts it, **Then** source stays HUMAN and status becomes ACCEPTED.
6. **Given** a review action that fails partway (for example, an invalid label), **When** the
   action is attempted, **Then** neither the current record nor the history changes.

---

### User Story 3 - Audit how a record reached its current state (Priority: P2)

A staff lead wants to know why P007's clip says "Spoken Performance". They open its history and
see the original AI value "Singing" with its confidence, then each review action in order, with
reviewer, time, and notes.

**Why this priority**: Provides accountability and lets the team measure model quality later.
The product still works without it in the short term, but the history must be recorded from the
first review onward or it is lost.

**Independent Test**: Run a series of review actions on one annotation, then reconstruct its full
timeline from history alone, including the original machine value.

**Acceptance Scenarios**:

1. **Given** an annotation reviewed three times, **When** its history is read, **Then** three
   entries appear in chronological order and the earliest previous value equals the original AI
   value.
2. **Given** existing history entries, **When** any later review happens, **Then** earlier entries
   are unchanged.
3. **Given** a request to modify or delete a history entry through normal operations, **When** it
   is attempted, **Then** it is refused.

---

### User Story 4 - Existing analysis is carried over (Priority: P1)

The team already has 12 videos, 100 anonymous participants, and 50,514 face detections, each with
positive/neutral/negative expression scores. After the migration, all of that is still present
and traceable. The per-detection scores are kept as machine signals, which the future
review-clip pipeline will turn into review clips and annotations.

**Why this priority**: The demo depends on real footage analysis. Losing or garbling it would
mean re-running the identity and expression pipelines.

**Independent Test**: Run the migration on a copy of the current database. Compare counts and
spot-check values against the original. Confirm that running it twice produces no duplicates.

**Acceptance Scenarios**:

1. **Given** the current database, **When** the migration runs, **Then** every video,
   participant, frame, and detection remains with its original identifiers, and every original
   expression score is still retrievable.
2. **Given** the current expression scores and any existing per-detection activity predictions,
   **When** the migration runs, **Then** each one is kept as a machine signal tied to its
   detection, with its original values. The migration creates no annotations or clips from
   them.
3. **Given** the migration has already run, **When** it runs again, **Then** no duplicates are
   created and no annotation or clip is altered.
4. **Given** the migration fails midway, **When** it stops, **Then** the database is left exactly
   as it was before the migration started.

---

### User Story 5 - Staff manage their own labels (Priority: P2)

A staff member adds a new observation label "Shares original song", with a definition, and
deactivates an activity label the team no longer uses. Existing annotations that use the
deactivated label keep it. The label is no longer offered for new annotations or edits.

**Why this priority**: TPA defines what matters, not the developers. A starter set of labels is
enough for the first demo.

**Independent Test**: Create, rename, describe, and deactivate labels. Confirm annotations keep
referring to the same label identity and that deactivated labels cannot be newly applied.

**Acceptance Scenarios**:

1. **Given** a new label with a name, category, and description, **When** it is saved, **Then**
   it receives a stable identifier and can be applied to annotations.
2. **Given** a label used by existing annotations, **When** it is renamed, **Then** those
   annotations show the new name, because they reference the label, not the text.
3. **Given** a label used by existing annotations, **When** it is deactivated, **Then** existing
   annotations still show it, and it cannot be chosen for new annotations or edits.
4. **Given** any label, **When** deletion is attempted through normal operations, **Then** it is
   refused, and deactivation is the supported path.

---

### User Story 6 - Reviewer adds a moment the machine missed (Priority: P3)

While reviewing VID003, a reviewer notices P012 presenting an original poem from 20:05 to 21:10.
The pipeline produced nothing for that moment. The reviewer creates an annotation with the
"Presenting Creative Work" label. It immediately appears in the video and participant views like
any other record.

**Why this priority**: The model will miss moments, and staff need a way to record them. It also
shows the team where the model falls short. The rest of the review workflow is useful without it.

**Independent Test**: Create an annotation by hand. Confirm its source, status, and history entry,
and confirm it is returned by video and participant queries.

**Acceptance Scenarios**:

1. **Given** a video with no annotation at a moment, **When** a reviewer creates one with an
   active label, a time span, and an optional participant, **Then** it is stored with source
   HUMAN and status ACCEPTED, with no model confidence.
2. **Given** a reviewer-created annotation, **When** its history is read, **Then** the first entry
   is a CREATED action with no previous values and the reviewer, time, and note recorded.
3. **Given** an attempt to create an annotation with a deactivated label or an invalid time span,
   **When** it is submitted, **Then** it is refused and nothing is stored.
4. **Given** a reviewer-created annotation, **When** it is later edited, rejected, or deferred,
   **Then** the same rules apply as for any other annotation.

---

### User Story 7 - Pipeline output never overwrites human work (Priority: P2)

In the future, processing may be re-run on a video that staff have already partly reviewed. New
machine output may be added. Any annotation a human has acted on stays exactly as the human left
it.

**Why this priority**: Models are not re-run today, so this protects future work. It is cheap to
guarantee now and costly to retrofit.

**Independent Test**: Simulate a second import of machine output over a partly reviewed video and
confirm that no reviewed annotation changes.

**Acceptance Scenarios**:

1. **Given** an annotation with status other than UNREVIEWED, **When** machine output for the same
   video is imported again, **Then** that annotation's value, source, status, and history are
   unchanged.
2. **Given** an annotation with source AI and status UNREVIEWED, **When** a re-import produces a
   newer value for the same annotation identity, **Then** the annotation is updated in place and
   stays source AI, status UNREVIEWED.
3. **Given** the same machine output imported twice, **When** the second import runs, **Then** no
   duplicate annotations are created.

---

### User Story 8 - Reviewers work through review clips, most promising first (Priority: P2)

A future pipeline will divide each video into review clips: spans in which the same set of
people is on screen. Each clip carries a clip-level activity annotation and a review-priority
score meant to surface the most positive moments. A reviewer opens a list of clips across all
videos, sorted by priority, and reviews each clip's annotations. A participant view can list every
clip a participant appears in.

This feature only stores clips and their scores. How clips are cut and how labels and priority
scores are computed belongs to the separate review-clip pipeline spec.

**Why this priority**: Clip-based review is how staff will actually work through hours of footage.
The data model has to hold clips now, so the pipeline can fill it later without a redesign.

**Independent Test**: Load sample clips with participants, clip-level annotations, and priority
scores. Query clips by video in time order, across all videos by priority, and by participant.
Confirm that clip annotations follow the same review rules as any other annotation.

**Acceptance Scenarios**:

1. **Given** a clip with a time span, three participants, and a priority score, **When** it is
   stored, **Then** the span, the participant set, the score, and the name and version of the
   scoring method are all retrievable.
2. **Given** clips across several videos, **When** clips are listed by priority, **Then** they
   come back highest score first, and clips without a score come last.
3. **Given** a clip-level activity annotation (no participant, linked to the clip), **When** a
   reviewer edits its label, **Then** the normal review rules and history apply, and the clip's
   priority score is unchanged.
4. **Given** a participant, **When** their clips are queried, **Then** every clip whose participant
   set includes them is returned.
5. **Given** a clip with a priority score of 2.07, **When** it is reported, **Then** it is labeled
   as a review priority, separate from any label confidence, and never as a percentage.
6. **Given** clips in a video where at least one clip annotation has been reviewed, **When** the
   pipeline re-imports clips for that video, **Then** clips holding reviewed annotations, and those
   annotations, are left unchanged, and no clip or annotation is deleted.

### Edge Cases

- An annotation's time span extends beyond the video's length, or ends before it starts: rejected
  at creation or edit.
- A zero-length (single-frame) annotation: allowed. It covers exactly one frame.
- Two annotations with the same label, participant, and overlapping time spans: allowed. Overlap
  is common in multi-label footage and is not treated as a conflict.
- A reviewer edits a REJECTED annotation: allowed. It becomes EDITED, source becomes HUMAN, and it
  returns to default views.
- An edit that changes nothing (same label, span, and participant): recorded as an acceptance, not
  an edit, so source does not change.
- A participant has no remaining active annotations after rejections: the participant still
  exists. Their detections and history remain.
- A detection with expression scores but no participant link cannot exist, because every existing
  detection belongs to a participant.
- Applying a label whose category does not fit the annotation's role (for example an observation
  label in an activity slot): not applicable, because a label's category defines the annotation's
  kind. Editing may change the label only to another label of the same category.
- Two reviewers act on the same annotation at nearly the same time: actions are applied one after
  another. The second action's "previous value" is the first action's result, so no action is
  lost from history.
- A clip with no detected people (an empty stage): allowed, with an empty participant set.
- A clip whose priority score is missing (not yet computed): allowed. It sorts after scored clips.
- Overlapping clips in one video: not prevented by the data model. Whether clips may overlap is
  up to the pipeline spec.
- A reviewer-created annotation inside a clip's span: MAY be linked to that clip, or left
  unlinked.
- An Edit that moves a clip-linked annotation's span or participant outside the clip: allowed.
  The clip is the review context that originally surfaced the annotation, and after a human edit
  the annotation's current state is authoritative. The clip itself is never changed because an
  annotation was edited.
- Review of an annotation whose label was deactivated after creation: accept, reject, and defer
  are allowed. A span-only or participant-only edit keeps the same deactivated label. Edit can
  never switch to, or newly assign, a deactivated label.
- An unreviewed AI annotation that is missing from a later import: kept unchanged. Spec 001 never
  deletes annotations or clips during import.

## Requirements *(mandatory)*

### Functional Requirements

**Annotation records**

- **FR-001**: The system MUST store each annotation as one record with: stable identifier, video,
  start and end position in the video (frame-accurate, with derived time in seconds), optional
  anonymous participant, exactly one label, optional model confidence (0–1), source, review
  status, and created/updated timestamps.
- **FR-002**: Multiple labels on the same moment MUST be represented as multiple annotation records
  sharing the same video and time span. Any number of participants and labels per time span MUST
  be supported.
- **FR-003**: An annotation with no participant MUST represent a group-level or scene-level
  observation.
- **FR-004**: All views, searches, analytics, and exports MUST read annotation records directly.
  No feature may keep its own copy of annotation values.
- **FR-005**: Records MUST be queryable by video and time range, participant, label, label
  category, source, and review status.

**Labels**

- **FR-006**: Labels MUST be stored as data with a stable identifier, name, category (activity or
  observation), description or definition, and an active flag.
- **FR-007**: Annotations MUST reference labels by identifier, so renaming a label does not change
  which label an annotation carries.
- **FR-008**: Labels MUST NOT be deletable through normal operations. Deactivated labels MUST stay
  visible on existing annotations and MUST NOT be applicable to new annotations or edits.
- **FR-009**: The system MUST provide a starter label set covering the activities and observations
  named in the project brief (see Assumptions). Staff MAY add more.
- **FR-010**: Affect and engagement labels MUST be named as observable signals ("Visible positive
  affect", "Visible neutral affect", "Visible negative affect"), never as internal states. These
  per-person observation labels let staff review and change each participant's
  engagement/sentiment. They are separate from the review-clip priority score.

**Provenance and review**

- **FR-011**: Source MUST be one of AI or HUMAN. Review status MUST be one of UNREVIEWED, ACCEPTED,
  EDITED, REJECTED, or DEFERRED. The two MUST be stored and reported separately.
- **FR-012**: Machine-created annotations MUST start as source AI and status UNREVIEWED.
- **FR-013**: Supported review actions are Create, Accept, Edit, Reject, and Defer, each optionally
  with a note.
  - Create: a reviewer adds a new annotation for a moment the pipeline missed, with an active label
    of either category, a valid time span, and an optional participant. It starts as source HUMAN
    and status ACCEPTED, with no model confidence. Its history entry (action CREATED) has no
    previous values.
  - Accept: status ACCEPTED. Value and source unchanged.
  - Edit: changes the label (within the same category), time span, and/or participant. Source
    becomes HUMAN and status becomes EDITED. An edit that changes nothing is treated as Accept.
  - Reject: status REJECTED. Value and source unchanged.
  - Defer: status DEFERRED. Value and source unchanged.
- **FR-014**: An annotation in any status MAY move to any status that a supported review action
  produces (ACCEPTED, EDITED, REJECTED, DEFERRED). No action returns an annotation to
  UNREVIEWED. Each transition is recorded.
- **FR-015**: Each review action MUST update the current record and append exactly one history
  entry as a single all-or-nothing operation.
- **FR-016**: A history entry MUST record: entry identifier, annotation, video, participant (if
  any), action, previous and resulting label, previous and resulting time span, previous and
  resulting participant, previous and resulting source and status, `reviewer_id`, timestamp,
  and optional note.
- **FR-036**: Every human review action (including Create) MUST require a non-empty `reviewer_id`.
  It is an opaque identifier, not a display name, and is never parsed or interpreted. Until
  authentication exists, the caller supplies it. A future authentication feature will fill the
  same field from the logged-in staff account.
- **FR-017**: History entries MUST NOT be modified or deleted through normal operations. The
  original machine value and confidence of every AI annotation MUST be recoverable from the
  record plus its history. "Original" means the AI value present when the first human review
  occurs. Automated re-imports before any review update the record in place and write no review
  history, so earlier AI versions are not kept.
- **FR-018**: Provenance MUST be determined only from source and history, never inferred from an
  annotation's content.
- **FR-019**: Imports of machine output MUST follow these rules:
  - An annotation with source AI and status UNREVIEWED MAY be updated or replaced by newer
    machine output. It stays source AI, status UNREVIEWED.
  - Once any human review action has occurred, automated processing MUST NOT overwrite the
    annotation. ACCEPTED, EDITED, REJECTED, and DEFERRED annotations, and all source HUMAN
    annotations, are protected.
  - Imports MUST match annotations by a deterministic identity, so re-importing the same output
    updates existing records (upsert) and never creates duplicates. The plan defines the identity.
  - Imports only insert or update. Unreviewed annotations or clips missing from a later import
    are NOT deleted in Spec 001. Removal belongs to the later clip pipeline spec.
- **FR-020**: REJECTED annotations MUST be excluded from default queries and exports, and MUST be
  available when explicitly requested (for example, for audit or review screens).
- **FR-021**: Model confidence MUST be stored only as the model's certainty in its prediction. The
  record MUST NOT hold review priority or human-judgment values in the confidence field.

**Migration of existing data**

- **FR-022**: The migration MUST keep existing per-detection expression scores
  (positive/neutral/negative) as machine signals tied to their detections, with values unchanged.
  It MUST NOT create annotations or clips from them. Turning per-frame expression scores into
  reviewable Visible Affect annotations was discussed for this migration. That work has moved to
  the later clip and annotation generation pipeline spec. This feature only preserves the raw
  per-frame scores.
- **FR-023**: The migration MUST preserve every existing video, participant, frame, and detection
  with its original identifiers and values.
- **FR-024**: The migration MUST keep any existing per-detection activity predictions as machine
  signals (label, 32-frame window, score) with values unchanged, and MUST NOT create annotations
  from them.
- **FR-025**: The migration MUST be all-or-nothing and safe to run more than once.
- **FR-026**: Data validation MUST reject annotations whose time span is reversed, negative, or
  beyond the video's length, and labels missing a name or category.

**Exports**

- **FR-027**: Current annotation records (excluding REJECTED by default) MUST be exportable as JSON
  and CSV. Each row MUST include annotation ID, video ID, participant ID, label ID and name,
  label category, start and end (frames and seconds), confidence, source, and review status.
- **FR-028**: Review history MUST be exportable as JSON and CSV.

**Review clips**

- **FR-029**: The system MUST store review clips. Each clip has a stable identifier, video, start
  and end position (frames, with derived seconds), the set of participants present (possibly
  empty), an optional review-priority score, the name and version of the method that produced
  the score, and created timestamps.
- **FR-030**: An annotation MAY reference one review clip, which MUST belong to the same video.
  Clip-level annotations (for example the clip's activity) MUST have no participant, and their
  span MUST equal the clip's span when imported or created. Per-participant annotations within a
  clip MAY carry that participant. A later Edit MAY move the span or participant away from the
  clip, and the clip is never changed by it.
- **FR-031**: The review-priority score MUST be a non-negative number with no upper bound. It MUST
  be stored and reported separately from label confidence, and MUST NOT be presented as a
  probability or percentage.
- **FR-032**: Clips MUST be queryable by video in time order, across all videos by priority
  (highest first, unscored last), and by participant.
- **FR-033**: Review actions apply to a clip's annotations under the same rules as all other
  annotations. Reviewing an annotation MUST NOT change its clip's priority score.
- **FR-034**: Re-importing a video's clips (for example on a pipeline re-run) MUST NOT alter a clip
  that holds any annotation whose status is not UNREVIEWED, or that annotation. Spec 001 imports
  never delete clips. Clip replacement and removal belong to the later clip pipeline spec.
- **FR-035**: This feature MUST NOT define how clips are segmented or how activity labels or
  priority scores are computed. It only stores the results.

### Key Entities

- **Video**: A processed recording (existing). Has duration, frame rate, and frame count.
- **Participant**: An anonymous person identifier (existing, e.g. `Person_0001`). Links
  appearances across videos. Never holds real-world identity.
- **Detection**: A face observation of a participant in one frame (existing). Keeps its bounding
  box and detection score.
- **Machine Signal**: A raw per-detection model output: expression scores, or an activity
  prediction over a 32-frame window. Read-only input for the pipeline. Not reviewed.
- **Review Clip**: A span of one video with the set of participants present and an optional
  review-priority score (plus the method that produced it). Groups annotations for review.
  Produced by the future review-clip pipeline.
- **Label**: A staff-managed vocabulary term. Category is activity or observation. Has name,
  definition, and active flag. Never deleted.
- **Annotation**: The current-state record. A label applied to a video time span, optionally for
  one participant, with confidence, source, and review status. This is the single source of truth
  for all views.
- **Review History Entry**: An immutable record of one review action on one annotation, with
  before and after values, reviewer, time, and note.
- **Reviewer**: The staff member performing a review action, identified by a stable staff
  identity. Accounts themselves are delivered by the authentication feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After migration, 100% of existing videos (12), participants (100), and detections
  (50,514) are present with unchanged identifiers. 100% of original expression scores can be
  retrieved, verified by an automated count and value comparison.
- **SC-002**: For any annotation, the full sequence of changes, including the original machine
  value, can be reconstructed from stored data alone in 100% of sampled cases.
- **SC-003**: In automated checks covering every review action and starting status, 100% of
  outcomes match the source and status rules in FR-013, and each action adds exactly one history
  entry.
- **SC-004**: A simulated re-import over partly reviewed data leaves 0 reviewed annotations
  changed.
- **SC-005**: A video-and-time query and a participant query on the migrated dataset each return
  results fast enough for interactive use (under 1 second on a typical team laptop).
- **SC-006**: Running the migration twice yields identical record counts to running it once.
- **SC-007**: An export opens in a standard spreadsheet tool and contains every non-rejected
  annotation exactly once.
- **SC-008**: With sample clips loaded for all 12 videos, listing clips by priority and listing a
  participant's clips each return results fast enough for interactive use (under 1 second on a
  typical team laptop).

## Assumptions

- Participant IDs keep their existing anonymous form (`Person_0001`, …). This satisfies the
  constitution's anonymous-ID rule ("P001" was an example). Renumbering would break traceability
  to the identity pipeline outputs.
- One label per annotation record. "Multi-label" means many records per moment. This keeps every
  review decision about exactly one claim.
- An Edit may change the label (within its category), time span, or participant. Changing the
  category (activity ↔ observation) means rejecting one annotation and creating another.
- Positions are stored in frames and also reported in seconds, matching the frame-accurate
  existing data.
- `reviewer_id` is required and opaque (FR-036). Checking that it belongs to a logged-in user is the
  authentication feature's job.
- The starter label set includes: activities — Singing, Dancing, Acting, Spoken Performance,
  Instrumental Performance, Rehearsal, Group Performance, Solo Performance, Presenting Creative
  Work; observations — Sustained Participation, Projecting Voice, Collaboration, Leadership,
  Increased Participation, Decreased Participation, Visible Positive Affect, Visible Neutral
  Affect, Visible Negative Affect.
- The existing Activity table currently holds no rows. The activity migration rule exists for
  completeness and for any rows loaded before this feature ships.
- Detections and their expression scores are kept as machine signals, not annotations. They are
  inputs that annotations are derived from, and they are not edited by review.
- Whether `data/analysis.sqlite` may stay in the public repository is governed by the
  constitution (Principle I) and is outside this feature.
- The intended clip design, recorded for the future review-clip pipeline spec and not built here,
  is as follows. A new clip starts whenever the set of people on screen changes. The clip's
  activity is the mode of its scored windows. The priority score is a weighted average of
  positive expression scores, for example 1.1^N × the average positive score, where N is the
  number of people in the clip. That spec will settle how clips are cut, how the average is taken
  (per person or per detection), and how the group weighting behaves.
- Out of scope: API endpoints, UI, authentication, running or re-running models, cutting clips,
  and computing clip labels or review-priority scores.
