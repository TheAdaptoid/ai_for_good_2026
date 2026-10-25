# Data Model: Review and Annotation Data Model

Everything lives in `backend/db/schema.sql`. Existing tables are unchanged. New tables are additive
([research.md R1](research.md)).

## Existing tables (unchanged)

| Table | Role in this feature |
|---|---|
| `Video` | Has `fps` and `duration_seconds`, used for derived seconds and span bounds. |
| `Frame` | Unchanged. |
| `Person` | Anonymous participant (`Person_0001`, …). Referenced by annotations and clips. |
| `FaceDetection` | Unchanged. |
| `Activity` | **Machine signal**: one per-detection activity prediction (32-frame window). Not reviewed. |
| `Engagement` | **Machine signal**: per-detection positive/neutral/negative scores. Not reviewed. |

## New tables

### Label

| Field | Type | Rules |
|---|---|---|
| `label_id` | INTEGER PK | Seeds use fixed IDs 1–18. All new indexes and triggers use `IF NOT EXISTS` |
| `name` | TEXT NOT NULL | Non-blank; `UNIQUE(category, name COLLATE NOCASE)` |
| `category` | TEXT NOT NULL | `CHECK IN ('activity','observation')` |
| `description` | TEXT | Definition shown to staff |
| `is_active` | INTEGER NOT NULL DEFAULT 1 | `CHECK IN (0,1)` |

Trigger `label_no_delete` blocks DELETE (FR-008).

**Starter seeds.** Activities, IDs 1–9: Singing, Dancing, Acting, Spoken Performance,
Instrumental Performance, Rehearsal, Group Performance, Solo Performance, Presenting Creative Work.
Observations, IDs 10–18: Sustained Participation, Projecting Voice, Collaboration, Leadership,
Increased Participation, Decreased Participation, Visible Positive Affect, Visible Neutral Affect,
Visible Negative Affect.

### ReviewClip

| Field | Type | Rules |
|---|---|---|
| `clip_id` | INTEGER PK | |
| `video_id` | INTEGER NOT NULL → Video | |
| `start_frame`, `end_frame` | INTEGER NOT NULL | `0 ≤ start ≤ end`. Upper bound checked in Python |
| `priority_score` | REAL NULL | `CHECK (priority_score IS NULL OR priority_score >= 0)`. No upper bound (FR-031) |
| `priority_method` | TEXT NULL | Name and version, e.g. `positive-weighted@1`. Required when the score is set |
| `import_key` | TEXT UNIQUE NULL | Deterministic pipeline identity (R3) |
| `created_at` | TEXT NOT NULL | ISO-8601 UTC |

### ReviewClipParticipant

| Field | Type | Rules |
|---|---|---|
| `clip_id` | INTEGER → ReviewClip, `ON DELETE CASCADE` | PK (clip_id, person_id) |
| `person_id` | TEXT → Person | |

An empty set is allowed (empty-stage clip).

### Annotation (current state, single source of truth)

| Field | Type | Rules |
|---|---|---|
| `annotation_id` | INTEGER PK | |
| `video_id` | INTEGER NOT NULL → Video | |
| `clip_id` | INTEGER NULL → ReviewClip | Optional (FR-030) |
| `person_id` | TEXT NULL → Person | NULL means group- or scene-level (FR-003) |
| `label_id` | INTEGER NOT NULL → Label | Exactly one label (FR-001, FR-002) |
| `start_frame`, `end_frame` | INTEGER NOT NULL | `0 ≤ start ≤ end` |
| `confidence` | REAL NULL | `CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)`. Model certainty only (FR-021) |
| `source` | TEXT NOT NULL | `CHECK IN ('AI','HUMAN')` |
| `review_status` | TEXT NOT NULL | `CHECK IN ('UNREVIEWED','ACCEPTED','EDITED','REJECTED','DEFERRED')` |
| `import_key` | TEXT UNIQUE NULL | Set for machine output, NULL for human-created (R3) |
| `created_at`, `updated_at` | TEXT NOT NULL | ISO-8601 UTC |

Cross-field rules, enforced in Python ([research.md R13](research.md)):

- Any annotation with `clip_id` set MUST reference a clip in the same video (import, Create).
- An annotation with `clip_id` set and `person_id` NULL is clip-level. At import and Create, its
  span MUST equal the clip's span.
- A later Edit MAY move the span or participant away from the clip. The clip is never modified
  by an edit.

Indexes: `(video_id, start_frame)`, `(person_id)`, `(label_id)`, `(review_status)`, `(clip_id)`.
Clips: `(video_id, start_frame)`, `(priority_score DESC)`. Clip participants: `(person_id)`.

### ReviewEvent (append-only history)

| Field | Type | Rules |
|---|---|---|
| `event_id` | INTEGER PK | Insertion order is chronological order |
| `annotation_id` | INTEGER NOT NULL → Annotation | No cascade |
| `video_id` | INTEGER NOT NULL → Video | Denormalized for audit queries |
| `action` | TEXT NOT NULL | `CHECK IN ('CREATED','ACCEPTED','EDITED','REJECTED','DEFERRED')` |
| `prev_label_id`, `new_label_id` | INTEGER NULL → Label | prev is NULL for CREATED |
| `prev_start_frame`, `prev_end_frame`, `new_start_frame`, `new_end_frame` | INTEGER NULL | |
| `prev_person_id`, `new_person_id` | TEXT NULL | |
| `prev_confidence`, `new_confidence` | REAL NULL | Keeps the original AI confidence recoverable (R6) |
| `prev_source`, `new_source` | TEXT NULL / NOT NULL | |
| `prev_status`, `new_status` | TEXT NULL / NOT NULL | |
| `reviewer_id` | TEXT NOT NULL | `CHECK (length(trim(reviewer_id)) > 0)`. Opaque (FR-036) |
| `note` | TEXT NULL | |
| `created_at` | TEXT NOT NULL | ISO-8601 UTC |

Triggers `review_event_no_update` and `review_event_no_delete` raise ABORT (FR-017).

## State transitions (FR-013, FR-014)

| Action | Allowed from | Value change | source | review_status | Confidence |
|---|---|---|---|---|---|
| Create | (new) | Sets all fields | HUMAN | ACCEPTED | NULL |
| Accept | any | none | unchanged | ACCEPTED | unchanged |
| Edit (changes something) | any | label (same category, must be active if changed), span, and/or person. A span- or person-only edit keeps an existing deactivated label | HUMAN | EDITED | NULL |
| Edit (changes nothing) | any | none | unchanged | ACCEPTED (recorded as ACCEPTED) | unchanged |
| Reject | any | none | unchanged | REJECTED | unchanged |
| Defer | any | none | unchanged | DEFERRED | unchanged |
| Machine re-import | `AI` and `UNREVIEWED` only | label, span, person, confidence, clip | AI | UNREVIEWED | new value |

No action returns an annotation to UNREVIEWED. A reachable starting state is one of:

- AI/UNREVIEWED
- AI/ACCEPTED, AI/REJECTED, or AI/DEFERRED
- HUMAN/ACCEPTED, HUMAN/EDITED, HUMAN/REJECTED, or HUMAN/DEFERRED

Every review action writes exactly one `ReviewEvent` in the same transaction. Machine imports write
none, because history records human actions. Imports never delete clips or annotations, and
unreviewed rows missing from a later import are kept.

## Validation summary

- Spans: `0 ≤ start_frame ≤ end_frame < frame_count`. The last check applies when the video has
  fps and duration, where `frame_count = round(duration × fps)` (FR-026).
- A clip-linked annotation must be in the clip's video. A clip-level annotation's span equals the
  clip span at import and Create.
- Newly applied labels must be active (Create, import, and an Edit that changes the label).
  Existing annotations, including span- or person-only edits, keep deactivated labels.
- Edit keeps the label category.
- `reviewer_id` must be non-empty.
- `priority_method` is required when `priority_score` is set.

## Default visibility (FR-020)

Annotation queries and exports exclude `review_status = 'REJECTED'` unless
`include_rejected=True`.
