# TPA Project Decisions

This document records durable decisions that future feature work should reuse.

It is not a replacement for the constitution or feature specifications.

If a decision is superseded, record the new decision and note which earlier decision it replaces.

---

## D001 — Application Stack

Frontend:

- React
- TypeScript
- Vite

Backend:

- FastAPI
- Python

Persistence:

- SQLite
- local filesystem

Architecture:

- modular monolith
- local-first

---

## D002 — Anonymous Identity

Participants retain anonymous identifiers such as:

`Person_0001`

The system may associate the same anonymous participant across multiple videos.

The system must not attempt to discover their real-world identity.

No:

- reverse-image search
- web identity lookup
- external facial-recognition lookup
- legal-name discovery
- home-address discovery

---

## D003 — Participant-Derived Data

Participant-derived analytical data may be stored and used when authorized for this project.

Examples:

- anonymous IDs
- bounding boxes
- timestamps
- activity labels
- visible-affect scores
- model confidence
- annotations

This does not authorize external re-identification.

---

## D004 — Annotation Current State

There is one authoritative current annotation state.

Normal:

- video views
- participant views
- review screens
- search
- analytics
- exports

read current annotation records.

Review history is not a competing current-state store.

---

## D005 — Annotation Source

Initial imported/model-created annotation values:

`source = AI`

Human-created annotations:

`source = HUMAN`

If a human changes the actual annotation value:

`source = HUMAN`

Merely reviewing an annotation does not necessarily make the value HUMAN.

---

## D006 — Review Status

Source and review status are independent.

Supported human actions:

- CREATE
- ACCEPT
- EDIT
- REJECT
- DEFER

CREATE:

- HUMAN
- ACCEPTED
- no model confidence

Accepting an unchanged AI annotation:

- source remains AI
- status becomes ACCEPTED

Actual human edit:

- source becomes HUMAN
- status becomes EDITED
- current model confidence is cleared

Reject and Defer do not independently alter source.

---

## D007 — Review History

Every human review action appends one history event.

History is append-only.

Human review action and current-state modification occur atomically.

Prior AI values/confidence are preserved as required for auditability.

---

## D008 — Protected Data

Automated processing may update only eligible machine-owned current state.

Reviewed work must not be silently overwritten.

Protected imports are skipped and counted appropriately.

Re-imports must be deterministic and idempotent.

---

## D009 — Multi-Label Model

One annotation contains one label.

A moment with multiple labels is represented using multiple annotations.

Activity and observation labels are distinct categories.

---

## D010 — Visible Affect

Use reviewable terms such as:

- Visible Positive Affect
- Visible Neutral Affect
- Visible Negative Affect

These are observable/model-derived signals for staff review.

They are not definitive statements about internal emotional state.

---

## D011 — Confidence vs Priority

Model confidence and review priority are different concepts.

Model confidence belongs to an annotation prediction.

Review priority ranks candidate clips for staff attention.

A review-priority score must not be displayed as model confidence or as a probability of human truth.

---

## D012 — Labels

Labels are deactivated rather than deleted.

Existing annotations may continue referencing a deactivated label.

A deactivated label cannot be newly assigned.

---

## D013 — Identity Stability

Once annotations/review clips rely on participant IDs, identity reclustering must not silently replace those IDs and invalidate reviewed data.

---

## D014 — Feature Delivery

Every feature follows:

specify
→ clarify if needed
→ plan
→ checklist
→ tasks
→ analyze
→ implement
→ test
→ converge
→ repeat until CONVERGED
→ commit

Converged features are committed automatically to their feature branches.

Feature branches are not automatically merged to `main`.

---

## D015 — Spec Timing

Detailed future feature specs are created immediately before their implementation cycle.

Do not fully specify all future roadmap features in advance.

Completed dependency features inform the next specification.

---

## D016 — Imports Never Delete Missing Records

Automated imports are additive/update-oriented.

If an annotation or review clip from an earlier import is absent from a later import, it is retained.

Imports must not automatically delete stale:

- annotations
- review clips
- participant associations belonging to retained records

Deletion or retirement of stale generated records requires an explicit policy defined by the responsible pipeline feature and must comply with Constitution Principle IX.

Protected or human-reviewed data must never be removed automatically.

---

## D017 — Review Clip Segmentation Baseline

The initial review-clip design for Spec 002 uses participant presence as a primary segmentation boundary.

A new review clip begins when the set of anonymous participants visible on screen changes.

A clip's representative activity is determined from the activity evidence within that clip, using the most common activity label as the baseline aggregation rule.

Spec 002 may introduce additional segmentation boundaries when needed to keep clips practical for human review, but must preserve this design unless the specification explicitly supersedes it.

Review priority remains separate from annotation confidence.

The proposed priority heuristic involving participant count and positive-affect evidence is intentionally left for Spec 002 to finalize.

---

## D018 — Application Before Clip Pipeline

Decided by the human on 2026-10-24.

The clip and annotation generation pipeline (roadmap 002) is deferred. The service, staff sign-in,
and the React dashboard/video/participant/review screens are built first, against existing data:
videos, participants, face detections, and the Spec 001 review tables, which stay empty until the
pipeline runs.

Screens must treat empty clip and annotation lists as a normal state, not an error.

Until clips exist, participant presence derived from face detections (computed on read, never
stored) is the timeline content for the video and participant views.

---

## D019 — Working Database

The running application uses `data/analysis.local.sqlite` (git-ignored), not the tracked
`data/analysis.sqlite`. It can be overridden with `TPA_DB` or `--db`.

Staff accounts, sessions, annotations, and review history therefore never enter the repository. The
tracked file remains the seed of machine signals.

---

## D020 — Staff Authentication

Local accounts only, managed with the `backend/scripts/staff.py` CLI. There is no self-registration
and no cloud identity provider.

- passwords: Argon2id (argon2-cffi)
- sessions: random token in an HttpOnly, SameSite=Strict cookie (`tpa_session`); only its SHA-256
  is stored; 12-hour lifetime; sign-out, disabling, and password reset end sessions
- every endpoint except sign-in and health requires a session
- `reviewer_id` in review history is the signed-in username; clients cannot supply it
- no roles yet: all active staff have the same permissions

---

## D021 — macOS Torch Build

`torch` stays pinned at `2.8.0`. The CUDA 12.8 index applies only when `sys_platform != 'darwin'`,
so macOS installs the standard CPU/MPS wheel and `uv sync --locked` works on team Macs (Constitution
"code MUST run on CPU"). CUDA validation still requires Linux.

---

## D022 — Frontend Testing

The human asked for Playwright for frontend testing.

- `npm run test:e2e`: Playwright (Chromium) drives the real app against the real FastAPI service.
  The service runs on a fresh copy of the tracked `data/analysis.sqlite`, built by
  `frontend/e2e/start-backend.sh` (ports 8001 and 5174), so the working database is never touched.
- `npm test`: Vitest + Testing Library component and workflow tests with a mocked `fetch`. These
  cover states the real data cannot produce yet (AI suggestions, review clips).
- Linting uses oxlint, as shipped by the Vite template.

---

## D023 — No Participant Footage in Test Artifacts or AI Context

Playwright traces, videos, and failure screenshots are disabled. Deliberate screenshots mask the
`<video>` element.

AI coding assistants must not open screenshots, traces, or frames that show participant footage
(Constitution I). This was violated once on 2026-10-24, when an unmasked e2e screenshot was
viewed. The artifact was deleted and the masking was added.

---

## D024 — Clip Pipeline Split: Infrastructure Now, Generation Later

Decided by the human on 2026-10-25.

The `Activity` table holds no predictions: X-CLIP has never been run over the footage. Spec 004
therefore builds only the infrastructure:

- import format and validation
- protected importer
- ImportRun audit
- stage Protocols, signal loader, and deterministic builder
- service and app support for clips and review priority

It runs no model, generates no clips or annotations from real signals, and never populates the
real database. Tests use synthetic fixtures only. End-to-end tests import a synthetic file into a
disposable database copy.

The later generation feature implements the stages:

- clip segmentation (D017 baseline)
- activity inference (X-CLIP, local)
- visible-affect aggregation
- review priority (the `1.1^N × positive-affect` hypothesis and its per-participant vs
  per-detection averaging choice remain open for that feature)

---

## D025 — Pipeline Import Contract

- File format `tpa-review-import/1` (`specs/004-clip-annotation-pipeline/contracts/import-format.md`).
  Videos are referenced by filename, labels by `(name, category)`, and positions in frames.
- One file is one all-or-nothing import, across all of its videos.
- Imported annotations are always `source = AI`, `review_status = UNREVIEWED`. Spec 001
  protection and no-delete rules apply unchanged.
- Builder keys are `"{pipeline}:{kind}:{sha256(content)[:20]}"`. The content is video, span,
  members, label, and person. The pipeline version is excluded, so newer versions update
  unreviewed rows in place, and a changed clip boundary yields a new record while the old one is
  retained.
- A span-less clip-level annotation takes its clip's span, or the stored span when the clip is
  protected.
- Each successful import appends an `ImportRun` audit row. ImportRun is append-only, enforced by
  triggers.

---

## D026 — High-Impact Clip Ranking in the Staff Video View

Decided by the human on 2026-10-25. Existing stored clips are ranked using
`1.1^N × mean positive score`, with N equal to the distinct clip membership count and the mean
equal to the visible-affect observation mean already displayed in clip details. Use current
Engagement values for members within the same video's half-open clip interval. A missing mean
leaves a clip unscored; a zero mean remains a valid score.

The video filter shows the top ten scored clips per video, with ties ordered by start time
and ID. Scores suggest staff review attention and are separate from confidence or conclusions
about internal emotional states. This resolves the UI ranking choice left open in D024;
generation work remains deferred. See [feature specification](design/high-impact-clips.md).

---

## D027 — The Application Uses `data/analysis.sqlite`; No Demo Databases

Decided by the human on 2026-10-25. Supersedes D019.

The running application, migrations, and data fixes use `data/analysis.sqlite`
(`scripts/serve.py` defaults to it). Demo or alternate working databases such as
`data/demo.local.sqlite` must not be created or used. Disposable copies made by automated tests
(for example the Playwright e2e databases) are not application databases and remain allowed.

Because staff accounts, sessions, and review history are now written to the tracked file, check
for them before committing `data/analysis.sqlite`.

---

## D028 — Impact Score Multiplier Is 1.3

Decided by the human on 2026-10-25. Amends D026.

The stored-clip impact score is `1.3^N × mean positive score` (previously `1.1^N`). N, the mean,
the top-ten selection, and tie ordering are unchanged from D026. The score remains a ranking
suggestion for review, not model confidence. The generation pipeline's review-priority heuristic
(`backend/pipeline/local_analysis.py`, roadmap 002 part 2) is a separate value and still uses 1.1.

---

## D029 — Impact Score Weights Clip Duration

Decided by the human on 2026-10-25. Amends D028.

The stored-clip impact score is `(duration_seconds / 3) × 1.3^N × mean positive score`, where
`duration_seconds` is the clip's end minus start time. N, the mean, the top-ten selection, and
tie ordering are unchanged from D026. Longer clips therefore rank higher at equal membership and
affect. The score remains a ranking suggestion for review, not model confidence.

---

## D030 — Impact Score Multiplier Is 1.5

Decided by the human on 2026-10-25. Amends D029.

The stored-clip impact score is `(duration_seconds / 3) × 1.5^N × mean positive score`. Duration,
N, the mean, the top-ten selection, and tie ordering are otherwise unchanged from D029.

---

## D031 — Impact Score Uses a Logarithmic Duration Weight

Decided by the human on 2026-10-25. Amends D030.

The stored-clip impact score is `ln(1 + duration_seconds / 3) × 1.5^N × mean positive score`.
The human chose `ln(1 + s/3)` over `ln(s/3)` and `log10(s)/3` because it is never negative:
clips under 3 seconds, which are common, keep a small positive weight rather than ranking below
clips with zero positive affect. Longer clips still rank higher, with diminishing returns.
