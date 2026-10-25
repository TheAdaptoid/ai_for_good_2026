# Audit and clip schema extension

`schema.sql` defines the six core ingestion tables. `audit_clips.sql` adds the
following structures. `initialize_database(path)` and `scripts/init_db.py --db
<path>` apply both scripts without deleting existing data. The extension is one
immediate transaction, using `CREATE ... IF NOT EXISTS`. Existing core counting
and ingestion contracts still cover only the original six tables.

## ActivityAudit

| Column | Type | Rule |
| --- | --- | --- |
| audit_id | INTEGER | Primary key |
| activity_id | INTEGER | Required FK to Activity |
| old_label, new_label | TEXT | Required previous/current labels |
| changed_at | TEXT | Required UTC ISO 8601 timestamp |
| changed_by | TEXT | Optional actor |

## EngagementAudit

| Column | Type | Rule |
| --- | --- | --- |
| audit_id | INTEGER | Primary key |
| engagement_id | INTEGER | Required FK to Engagement |
| old_positive_score, new_positive_score | REAL | Required previous/current values |
| old_neutral_score, new_neutral_score | REAL | Required previous/current values |
| old_negative_score, new_negative_score | REAL | Required previous/current values |
| changed_at | TEXT | Required UTC ISO 8601 timestamp |
| changed_by | TEXT | Optional actor |

Audit update, delete, and replacement of an existing audit ID are blocked by
triggers. Foreign keys prevent removal of audited parent records. Audit indexes
support ordered per-record history queries:

```sql
SELECT * FROM ActivityAudit WHERE activity_id = ? ORDER BY audit_id;
SELECT * FROM EngagementAudit WHERE engagement_id = ? ORDER BY audit_id;
```

Only `analysis_db.corrections.correct_activity` and `correct_engagement` insert
audits as part of their atomic correction operations. Inference writers and
engagement CSV imports do not use these functions. A later automated run can
replace current predictions while preserving IDs and all prior audit entries.

## Clip and ClipPerson

| Clip column | Type | Rule |
| --- | --- | --- |
| clip_id | INTEGER | Primary key |
| video_id | INTEGER | Required FK to Video |
| start_time_seconds | REAL | Required, nonnegative |
| end_time_seconds | REAL | Required, greater than start, within video duration |
| created_at | TEXT | Required UTC ISO 8601 timestamp |

`ClipPerson(clip_id INTEGER NOT NULL, person_id TEXT NOT NULL)` has a composite
primary key and foreign keys to Clip and Person. Indexed video intervals cannot
overlap. Adjacent clips may share an endpoint. Activity changes never create
boundaries. SQL triggers reject boundary/parent changes and clip deletion.

## ClipGeneration (internal lifecycle marker)

`ClipGeneration(video_id INTEGER PRIMARY KEY REFERENCES Video,
persistence_frames INTEGER NOT NULL, created_at TEXT NOT NULL)` records completed
generation, even when no people were confirmed and no clips were inserted.
The positive integer threshold is recorded for provenance; configuration remains
a service/CLI argument and needs no schema change.

The generation service inserts clips and membership first, then seals the video
with this marker in the same transaction. SQL triggers block subsequent clips,
membership additions/updates/deletes, and changes to the marker. Membership
updates/deletes are always blocked. Video duration changes that would invalidate
existing clip boundaries are also blocked. There is no regeneration API.
Replacing a protected Video row is rejected before SQLite's implicit replacement
delete can cascade into its frames, including videos finalized without clips.
An index on `Frame(video_id, source_time_seconds)` supports engagement interval
queries without scanning every analyzed frame of the source video.

## Backend interfaces

- `analysis_db.corrections.correct_activity(connection, activity_id, new_label,
  *, changed_by=None) -> bool`
- `analysis_db.corrections.correct_engagement(connection, engagement_id,
  positive_score, neutral_score, negative_score, *, changed_by=None) -> bool`
- `analysis_db.clips.generate_clips(connection, video_id,
  *, persistence_frames=5) -> tuple[int, ...]`
- `analysis_db.clips.populate_clips(connection,
  *, persistence_frames=5) -> dict[int, tuple[int, ...]]`
- `analysis_db.clip_analytics.get_clip_info(connection, clip_id) -> ClipInfo`
- `analysis_db.clip_analytics.get_clip_summary(connection, clip_id,
  *, include_details=False) -> dict`

Writes require idle connections with foreign keys enabled. Summaries establish a
consistent read snapshot when the caller has no active transaction; otherwise
they use and preserve the caller's transaction. Summaries are not stored in Clip.
See the backend README for aggregation policies and video retrieval examples.
