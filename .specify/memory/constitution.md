<!--
Sync Impact Report
- Version change: 2.0.0 → 2.0.1 (PATCH: Principle I clarifies that internal use of derived
  records is permitted and public release requires documented authorization)
- Prior: 1.1.0 → 2.0.0 (MAJOR: principles redefined and consolidated around TPA
  video-review platform; provenance, review-history, and privacy model introduced)
- Modified principles:
  I. Privacy & Local-First Processing → I. Local-Only Processing of Sensitive Media
  II. Data Integrity & Single Source of Truth → V. Current State, Source, and Append-Only History
  III. Reproducible Environments → XI. Reproducible and Open
  IV. Tested Contracts → X. Tested Workflows
  V. Simplicity & Explicit Scope → XII. Simple, Typed, and Usable
- Added principles: II. Anonymous Identity, No Re-identification; III. Data Minimization and
  Ethical Review Gate; IV. Humans Decide, Machines Suggest; VI. One Multi-Label Annotation Model;
  VII. Modular Monolith with Clear Boundaries; VIII. Secure by Default; IX. Visible Failure and
  Safe Data Operations
- Added sections: none (Technology Stack, Development Workflow, Governance rewritten)
- Removed sections: none
- Known conflicts with current code (to resolve via feature specs, not exceptions):
  * backend/db/schema.sql Activity table is single-label per detection (violates VI)
  * Activity/Engagement tables lack source and review_status; no review-history table (V)
  * Identity notebooks persist FaceCrops/ and RepresentativeFaces/ (III)
- Follow-up TODOs: document TPA/data-governance authorization for publicly committed
  data/analysis.sqlite, or remove it from the public repository (Principle I)
-->

# TPA Video Review Platform Constitution

An open-source, privacy-conscious video intelligence and human-review platform that turns long
Performance Academy (TPA) program footage into searchable, reviewable timelines of activities,
participation, and observations. It assists staff judgment; it never replaces it.

## Core Principles

### I. Local-Only Processing of Sensitive Media

- Source video, extracted frames, face images and crops, participant audio, and transcripts MUST
  be processed only on local or explicitly TPA-controlled machines.
- Raw participant media and biometric artifacts (source video, frames, face images and crops,
  face embeddings, participant audio, and equivalent artifacts) MUST NOT be sent to any third-party
  cloud AI, inference, transcription, or facial-recognition service. This includes AI coding
  assistants and cloud agents.
- All analysis and review features MUST work without cloud inference. The network MAY be used only
  for explicit, separately invoked dependency and model downloads.
- Raw participant media and biometric artifacts MUST NOT be committed to the repository.
  `.gitignore` MUST cover each new kind of such artifact before it is first generated.
- Derived non-image records (anonymous IDs, detections, bounding boxes, timestamps, video
  associations, labels, engagement/sentiment values, scores) MAY be stored and used by the system.
  Being participant-derived does not, on its own, rule them out of the repository.
- Internal use and public release are separate decisions. Derived records MAY be committed to the
  public repository only where TPA or project data-governance rules authorize that release, and
  that authorization SHOULD be documented in the repository. Do not assume authorization that has
  not been documented.

Rationale: participants are mostly young people who appear in footage they did not consent to
distribute beyond TPA.

### II. Anonymous Identity, No Re-identification

- Participants MUST be represented only by anonymous IDs (`P001`, `P002`, …).
- The system MAY link the same anonymous person across videos ("P007 appears in A, C, F").
- The system MUST NOT attempt to learn or enrich a participant's real-world identity. That means
  no web or reverse-image search, no external database or identity-enrichment lookups, no
  facial-recognition services, no inferring names or addresses, and no joining anonymous IDs to
  externally discovered personal information.
- Any feature that uses personally identifying information provided by TPA MUST pass the ethical
  review gate (Principle III) and a constitution amendment before implementation.

Rationale: the privacy model is anonymous cross-video association without real-world identity
discovery.

### III. Data Minimization and Ethical Review Gate

- The system MUST NOT infer demographic or protected characteristics (age, gender, race, disability,
  etc.) from appearance.
- Temporary face crops SHOULD be deleted once embeddings or identity associations are produced.
  Retention requires a documented reason in the feature spec.
- Store only what a specified feature uses. No speculative biometric profiles.
- Features involving demographics, new biometric analysis, emotional or psychological
  interpretation, or automated scoring of individuals MUST record an explicit ethics and privacy
  review in their spec before planning.

### IV. Humans Decide, Machines Suggest

- Machine output MUST be presented as a suggestion, never as ground truth. The UI MUST visibly
  distinguish unreviewed suggestions from human-reviewed values.
- Model confidence, review priority, and human decisions are three separate concepts. They MUST be
  stored and displayed separately, and confidence MUST NOT be described as the probability that a
  moment matters or that an interpretation is true.
- Affect and engagement outputs MUST be worded as observable signals ("visible positive affect",
  "sustained participation"), never as internal-state claims ("happy", "disengaged").
- Ranked moments MUST be labeled as suggestions for review. Any review-priority score MUST have its
  inputs and formula documented in its feature spec.

### V. Current State, Source, and Append-Only History

- Annotation records hold the single current state. Every view, export, and analysis MUST read it.
  There MUST be no parallel "AI" and "human" annotation datasets.
- Each annotation carries `source` (`AI` | `HUMAN`) and `review_status` (`UNREVIEWED` | `ACCEPTED` |
  `EDITED` | `REJECTED` | `DEFERRED`). They answer different questions and MUST NOT be conflated:
  - Pipeline output is created as `source = AI`, `review_status = UNREVIEWED`.
  - A review action that changes a current value (label or engagement/sentiment) MUST set
    `source = HUMAN`. An action that changes no value (Accept, Reject, Defer) MUST NOT change
    `source`.
  - Provenance MUST come from the review workflow, never be inferred from the value's content.
- Every review action MUST, in the same transaction, update the current record and append a history
  event with the annotation ID, action, previous and resulting values, reviewer, timestamp, and an
  optional note.
- History records MUST NOT be updated or deleted by application code. The original AI value MUST
  remain recoverable from history.
- Automated processing MUST NOT overwrite an annotation whose `review_status` is not `UNREVIEWED`.
  Any future re-run MUST skip such records or require explicit conflict resolution.
- Rejected annotations MUST NOT appear as active observations in default views or exports.
- `backend/db/schema.sql` is the only schema definition. Bulk imports MUST be all-or-nothing per
  input file.

### VI. One Multi-Label Annotation Model

- Video timelines, participant timelines, review screens, search, analytics, and exports MUST be
  driven by the same annotation records. No per-screen copies.
- The model MUST support many people, many activity labels, and many observations per segment.
  Single-label-per-segment schemas or APIs are prohibited.
- Activity labels (singing, acting, group performance, …) and observations (sustained
  participation, projecting voice, visible affect, …) MUST be distinct label categories.
- Labels MUST be data, not code: each has a stable ID, name, category, description, and active flag.
  Neither the frontend nor the pipeline may hard-code the label set.
- Annotations MUST be exportable as JSON and CSV with stable IDs and explicit timestamps.

### VII. Modular Monolith with Clear Boundaries

- One FastAPI backend, one React frontend, one SQLite database, and the local filesystem. No
  microservices, message brokers, distributed or cloud databases, Kubernetes, or orchestration
  systems without a constitution amendment.
- The frontend handles presentation and interaction only. It MUST talk to the backend solely
  through the FastAPI API and MUST NOT touch SQLite, model files, ML artifacts, or `data/`.
- Business logic, validation, authorization, persistence, review logic, exports, and ML integration
  live in Python packages under `backend/`. FastAPI routes are a thin layer over them.
- Each pipeline stage (detection, tracking, identity association, activity classification, audio,
  observations, review priority) MUST sit behind its own typed interface. Swapping one model MUST
  NOT require changes outside that stage.

### VIII. Secure by Default

- All application access MUST require authenticated staff accounts. Passwords MUST be hashed with
  Argon2 or bcrypt and never stored or logged in plaintext.
- Authorization MUST be enforced in the backend for every endpoint. Hiding UI elements is not
  access control.
- All user-controlled input MUST be validated server-side with Pydantic models. File paths from
  requests MUST be resolved and confined to their allowed directories.
- The API MUST bind to `127.0.0.1` by default. Wider exposure is an explicit opt-in.
- Secrets MUST come from environment or local config files that are ignored by git.

### IX. Visible Failure and Safe Data Operations

- Processing jobs MUST expose an explicit state (queued, processing, completed, completed with
  warnings, failed). A failed stage MUST be visible to staff and MUST NOT produce empty results that
  look like success.
- Outputs from successful stages SHOULD be kept when another stage fails.
- Deleting videos, annotations, labels, or participant associations MUST require an explicit,
  confirmed user action. Labels SHOULD be deactivated rather than deleted.
- Expensive inference results SHOULD be cached and reused rather than recomputed. Performance work
  MUST NOT compromise privacy, provenance, or reviewed values.

### X. Tested Workflows

- Each backend change MUST ship with pytest coverage of the behavior it adds or changes. Priority
  areas: authentication and authorization, review actions and their `source`/`review_status`
  transitions, history appends, protection of reviewed values, multi-label associations, exports,
  and privacy cleanup.
- Every endpoint MUST have a `TestClient` test. The generated OpenAPI schema is the API contract.
- Frontend tests MUST cover core staff workflows (navigating video and participant views,
  performing review actions) rather than implementation details.
- Tests needing GPUs, real video, model weights, or ffmpeg MUST skip cleanly when those resources
  are absent.
- Model-quality evaluation is separate from unit testing and MUST NOT gate CI.

### XI. Reproducible and Open

- Python projects use `uv` with committed `uv.lock`. The frontend commits its lockfile and installs
  from it.
- Models MUST be pinned to exact revisions, and numerics-relevant frameworks pinned exactly.
- READMEs MUST let a new developer or judge go from clone to running app: setup, model download,
  where videos go, how to run processing, and how to start the backend and frontend.
- All dependencies and models MUST have licenses compatible with an open-source release, recorded
  in the repository. A proprietary service MUST NOT be added when a local open-source option meets
  the need.

### XII. Simple, Typed, and Usable

- Build the end-to-end path first: process video → annotations → video timeline → participant view
  → review → updated current state → history → export. Defer anything not on that path.
- No speculative abstractions, options, or infrastructure (YAGNI).
- Frontend code MUST be TypeScript with `strict` enabled. Python public interfaces and domain
  models MUST be type-hinted and use explicit models (dataclasses or Pydantic), not loose dicts.
- The UI is a staff review tool. Interactive controls MUST be keyboard-reachable with visible focus.
  Loading, empty, and error states MUST be explicit. Review state MUST be readable at a glance.

## Technology Stack

- Frontend: React + TypeScript + Vite, in `frontend/`.
- Backend: Python 3.13 + FastAPI, in `backend/` (capped `<3.14` for pinned torch).
- Storage: SQLite (`data/analysis.sqlite`) for structured records. Local filesystem (`data/`) for
  videos and generated artifacts. Persisted paths are relative to the repository root.
- ML: local, open-source models via PyTorch and Hugging Face Transformers. Code MUST run on CPU,
  with CUDA optional.
- Exploration: `notebooks/`. Logic that the application depends on MUST be promoted into
  `backend/` packages with tests.

Changing any item in this section requires a constitution amendment.

## Development Workflow

- Features follow Spec Kit: `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
  `/speckit-implement`. Each plan's Constitution Check MUST list every principle it touches, and
  every justified deviation goes in Complexity Tracking.
- Work happens on feature branches and merges to `main` through PRs. PRs MUST pass `uv run pytest`
  in each affected Python project and the frontend's type check, lint, and test scripts.
- A PR that changes the OpenAPI schema MUST update the frontend code that consumes it.
- A PR that changes commands or setup MUST update the relevant README.

## Governance

This constitution overrides all other project docs, specs, and plans. When a proposal conflicts
with it, identify the conflict and either redesign to comply or amend the constitution first. Never
bypass a principle silently.

- **MUST**: non-negotiable. Covers privacy, security, human authority, data integrity, history
  preservation, and architectural boundaries.
- **SHOULD**: a strong default. Deviations require a written justification in the plan.
- **MAY**: permitted, optional.

Amendments are PRs to `.specify/memory/constitution.md` with an updated Sync Impact Report and the
agreement of at least one other team member. Versioning: MAJOR when a principle is removed or
redefined, MINOR when a principle or section is added or materially expanded, PATCH for wording.

**Version**: 2.0.1 | **Ratified**: 2026-10-24 | **Last Amended**: 2026-10-24
