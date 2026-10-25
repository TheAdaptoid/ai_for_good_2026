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
