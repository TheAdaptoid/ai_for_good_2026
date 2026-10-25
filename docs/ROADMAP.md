# TPA Video Intelligence Platform — Development Roadmap

## Development Rule

Each feature follows:

Specify
→ Clarify if necessary
→ Plan
→ Checklist
→ Tasks
→ Analyze
→ Implement
→ Test
→ Converge
→ repeat implementation/convergence until Converged
→ Commit
→ Next Feature

Later features are specified using the actual completed implementation of their dependencies. Detailed future specifications are intentionally not written far in advance.

---

## 001 — Review and Annotation Data Model

Status: IN PROGRESS / NEAR CONVERGENCE

Provides:

- current annotation state
- multi-label records
- label management domain
- AI/HUMAN source
- review status
- append-only review history
- review clips as stored structures
- protected imports
- JSON/CSV export
- identity safeguard

Completion condition:

- T057 complete
- tests run
- convergence reports CONVERGED
- feature committed

---

## 002 — Clip and Annotation Generation Pipeline

Depends on: 001

Purpose:

Turn existing local video-analysis/model signals into reviewable clips and annotations.

Expected scope:

- clip segmentation
- clip boundaries
- participant membership
- activity annotation generation
- Visible Positive Affect
- Visible Neutral Affect
- Visible Negative Affect
- annotation confidence
- review-priority heuristic
- deterministic import keys
- idempotent reruns
- protected import using 001
- no overwriting reviewed work

Design hypothesis to evaluate during Spec 002:
priority ≈ 1.1^N × average positive-affect score

Open decision:
whether positive-affect aggregation should average per detection
or first aggregate per participant so participants with more detections
do not receive disproportionate weight.

Outputs are consumed by FastAPI and React features.

---

## 003 — FastAPI Application Service

Depends on: 001, 002

Purpose:

Expose application/domain functionality through a local FastAPI service.

Expected resources:

- videos
- participants
- annotations
- review clips
- reviews
- labels
- exports
- processing status
- local video access/streaming as needed

Business rules remain in domain modules rather than endpoints.

---

## 004 — Staff Authentication and Authorization

Depends on: 003

Purpose:

Provide authenticated local staff access and reviewer identity.

Expected scope:

- login
- password hashing
- sessions/tokens as selected in plan
- backend authorization
- reviewer ID from authenticated staff
- role enforcement where required

No cloud identity provider unless explicitly approved.

---

## 005 — React Application Shell and Dashboard

Depends on: 003, 004

Purpose:

Create the React/TypeScript/Vite staff application foundation.

Expected scope:

- app shell
- navigation
- authenticated layout
- dashboard
- video list
- participant entry points
- review summaries
- processing status

---

## 006 — Video Timeline View

Depends on: 002, 003, 005

Purpose:

Primary video-centered review experience.

Expected scope:

- local video playback
- timeline
- review clips
- per-participant timeline rows
- activity labels
- engagement/visible-affect labels
- review-priority moments
- seek to clip/moment
- filtering

---

## 007 — Participant View

Depends on: 002, 003, 005

Purpose:

Allow staff to select an anonymous participant and see their activity across videos.

Expected scope:

- participant selector/search
- all videos containing participant
- clips involving participant
- activity annotations
- engagement/visible-affect annotations
- chronological history

Uses the same underlying annotations as the video view.

---

## 008 — Human Review Interface

Depends on: 001, 003, 004, 005

Purpose:

Expose the review workflow to staff.

Expected actions:

- CREATE
- ACCEPT
- EDIT
- REJECT
- DEFER

Editable properties include where allowed:

- activity/observation label
- engagement/visible affect
- time span
- participant

Current state and append-only history rules come from Spec 001.

---

## 009 — Label Management

Depends on: 001, 003, 004, 005

Purpose:

Allow authorized staff to manage application labels.

Expected scope:

- create label
- edit supported metadata
- deactivate label
- distinguish activity and observation categories
- prevent destructive deletion of referenced labels

---

## 010 — Video Upload and Processing

Depends on: 002, 003, 004, 005

Purpose:

Allow authorized staff to add new footage locally and process it.

Expected processing states:

- queued
- processing
- completed
- completed with warnings
- failed

Failures must remain visible.

---

## 011 — End-to-End Integration and Demo Hardening

Depends on: 001–010

Purpose:

Validate and polish the complete staff workflow.

Target flow:

Login
→ choose/upload video
→ process
→ generate clips/annotations
→ inspect video timeline
→ inspect participant timeline
→ human review
→ current-state update
→ history
→ export

Add integration testing and fix cross-feature issues.

---

## 012 — Hackathon Deliverables and Release Readiness

Depends on: completed application

Expected deliverables:

- runnable code/environment
- architecture/workflow diagram
- structured JSON/CSV output
- review/annotation interface
- model/system card
- model list
- known limitations
- uncertainty handling
- bias risks
- data-governance note
- privacy/access explanation
- end-to-end demo instructions

Do not fabricate performance or evaluation claims.

---

# Definition of Project Complete

The project is complete when:

- features 001–012 are committed
- all features have converged
- available automated tests pass except explicitly documented external/environment limitations
- Linux/CUDA-only validation has been completed where required
- the end-to-end staff workflow works
- challenge deliverables are present
- no known CRITICAL or HIGH defects remain
- no prohibited raw/biometric artifacts or secrets are committed
