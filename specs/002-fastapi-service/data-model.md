# Data Model: Local Application Service with Staff Sign-In

Additive tables in `backend/db/schema.sql`. Spec 001 tables are unchanged.

## StaffAccount

| Column | Type | Rules |
|---|---|---|
| staff_id | INTEGER PK | |
| username | TEXT NOT NULL UNIQUE COLLATE NOCASE | `length(trim(username)) > 0`. Used as the opaque `reviewer_id` |
| password_hash | TEXT NOT NULL | Argon2 encoded hash. Never plaintext |
| is_active | INTEGER NOT NULL DEFAULT 1 | 0 or 1 |
| created_at | TEXT NOT NULL | UTC ISO-8601 |

Accounts are never deleted (no API). Disabling one also deletes its sessions.

## StaffSession

| Column | Type | Rules |
|---|---|---|
| token_hash | TEXT PK | SHA-256 hex of the cookie token |
| staff_id | INTEGER NOT NULL → StaffAccount ON DELETE CASCADE | |
| created_at | TEXT NOT NULL | |
| expires_at | TEXT NOT NULL | created + 12 h |

Expired rows are deleted lazily when they are next looked up.

## Computed read models (dataclasses in `analysis_db.contracts`, not stored)

- **VideoSummary**: video_id, title, filename, duration_seconds, fps, frame_count
  (`round(duration × fps)`), participant_count, detection_count, annotation_counts
  (UNREVIEWED/ACCEPTED/EDITED/REJECTED/DEFERRED → int, zeros included), clip_count.
- **PresenceInterval**: start_seconds, end_seconds, detection_count.
- **VideoParticipant**: person_id, first_seconds, last_seconds, detection_count, intervals.
- **ParticipantSummary**: person_id, video_count, detection_count.
- **ParticipantVideo**: video_id, title, first_seconds, last_seconds, detection_count.
- **ParticipantDetail**: person_id, videos (list of ParticipantVideo, ordered by video_id).
- **StaffAccount** (public view): staff_id, username, is_active, created_at. No hash.
