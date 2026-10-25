# Audit logging and person-based clips

Approved by the user on October 25, 2026. This design implements the supplied
Audit Logging & Person-Based Video Clips specification.

## Integration

Keep the existing six-table ingestion contract. Add ActivityAudit,
EngagementAudit, Clip, and ClipPerson, plus an internal ClipGeneration table that
records finalization even when a video yields zero clips. Initialization applies
an additive SQL extension to existing databases without rebuilding source tables.
The existing explicit Activity migration remains required for legacy Activity.

Correction functions own an immediate transaction, reject invalid values, read
the current record, skip no-ops, update the original, and append a UTC ISO 8601
audit entry. Database triggers reject audit updates, deletes, and replacement of
existing audit IDs. Automated inference does not call correction functions.

Engagement CSV replacement retains IDs for retained detections using upserts.
Removing an audited record fails transactionally rather than removing history.
Identity replacement is rejected once audits or finalized clips exist.

## Segmentation and lifecycle

Expose an explicit initial-population service and CLI run after all detection
imports. Default persistence is five consecutive stored Frame records, including
frames with no detections. Never infer extra observations from missing frames.
For each person, count consecutive observations that disagree with confirmed
presence. Confirmation emits an event at the first qualifying observation.
Sort all confirmed events by source timestamp and apply simultaneous events
together. Emit positive-duration intervals with a nonempty confirmed person set.
Unconfirmed trailing changes are ignored; confirmed presence lasts to video end.

Use half-open intervals [start, end). First appearance begins at its first
qualifying frame, not automatically at zero. Require finite positive video
duration and strictly increasing, in-range frame timestamps in presentation
order. Invalid source metadata fails before persistence. Generate clips,
memberships, and the finalization marker in one immediate transaction. Repeated
calls return existing IDs regardless of the newly requested threshold.

SQLite constraints/triggers enforce positive in-range nonoverlapping intervals
and prevent boundary/parent changes, clip deletion, and membership changes after
finalization. There is no regeneration or identity-edit interface.

## Analytics

Read each summary in a consistent database snapshot. Activity membership uses
positive window overlap with the clip, restricted to the same video. Sum overlap
durations per current label and normalize by total overlap weight. Overlapping
prediction windows are independent evidence, not deduplicated timeline coverage.
Resolve dominant-label ties alphabetically. Detailed results include overlap
seconds and current activity rows. No observations yields no dominant label and
an empty distribution.

Engagement uses stored frame timestamps in [start, end), same video, and people
in ClipPerson. Average available detection observations equally. Include per-person
and group observation counts. A person without observations has null means;
the group is observation-weighted, not an unweighted mean of person means.

## Retrieval

Keep detection-based get_clip unchanged. Add person-clip metadata and segment
retrieval methods to VideoRetriever, reusing its path resolution and PyAV decoder.
Return in-memory RGB frames, source frame indices, and normalized presentation
timestamps for frames in [start, end). No padding, exports, permanent copies, or
new decoding dependency. Reject invalid/nonincreasing PTS consistently with the
existing temporal retriever. Audio/muxed HTTP streaming remains outside this
backend's existing array-based retrieval contract.

## Verification

Cover additive migration, append-only history, atomic failures, invalid/no-op
corrections, prediction imports, persistence events and overlapping transitions,
empty finalization, immutable relationships, overlap weighting, missing scores,
correction propagation, first/last video frames, variable presentation times, and
absence of exported files. Run the complete existing backend suite afterwards.
