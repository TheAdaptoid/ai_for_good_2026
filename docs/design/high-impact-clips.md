# High-impact clip filter

Approved by the user on 2026-10-25 for the staff video view. This is a read-only ranking of
existing person-presence clips, not a generation or schema-migration feature.

## Score and data source

`impact_score = ln(1 + duration_seconds / 3) × 1.5^N × mean_positive_score` (D031; earlier 1.1^N, 1.3^N by D028, and duration weighting by D029)

- N counts distinct members in ClipPerson for that clip, including members without scores.
- The mean uses available Engagement.positive_score observations for clip members, in the
  same video, within the half-open interval `[start_time_seconds, end_time_seconds)`.
- Each observation has equal weight. Repeated detections do not increase N. Missing values
  do not become zero. A clip without observations is unscored; a measured zero is valid.
- The clip detail's visible-affect mean and the ranking use the same observations. Current
  corrected Engagement values are authoritative, so scores are recalculated on each read.
- Scores are unbounded ranking suggestions for staff attention, separate from model confidence
  and human judgments about program impact. No score or participant association is persisted.

## Video filter behavior

The default all-clips view remains available. The "See top 10 clips" button selects up to ten scored
clips from the current video, ordered by descending full-precision score, then earlier start
time and clip ID for deterministic ties. Display rounding does not affect selection.
The filtered timeline shows those clips; presence and staff annotations retain their context.
A ranked list shows scores and participant counts. Selecting an entry seeks the player and
opens that stored clip's details. Clips without observations have an explicit empty state.
Keyboard access and responsive layouts remain supported. No model or pipeline work is run.

## Dashboard labels

The Review clips summary card has been removed. Human Annotations counts human-sourced
Annotation rows plus distinct Activity and Engagement records with correction audit entries.
Repeated corrections count each record once. Accepting or deferring unchanged values does
not increase that total. Imported review suggestions remain available on the Review page.

## Acceptance and verification

- The existing database is read directly; no SQLite file enters the code commit.
- Synthetic API tests cover formula inputs, unequal observation counts, repeated detections,
  membership and interval boundaries, live corrections, missing/zero scores, and source counts.
- UI tests cover top-ten selection, ties, seeking, returning to All clips, and empty states.
- Privacy-safe browser variants cover the filter, score display, focus, contrast, and layout
  from 320 to 2400px, with traces/recordings off and synthetic or masked captures only.
- Spec 005, table cleanup, model generation, and a ranked CSV export are outside this change.
