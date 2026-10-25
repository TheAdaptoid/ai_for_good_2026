# Feature Specification: Local Application Service with Staff Sign-In

**Feature Branch**: `002-fastapi-service`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "Skip creating the review clips for now. First build the dashboard and
the rest of the staff application; the clip/annotation generation pipeline becomes a later step."
This feature is the service layer that the dashboard and later screens read through. It combines
roadmap items "FastAPI Application Service" and "Staff Authentication", because the constitution
forbids any unauthenticated application access (Principle VIII).

## Overview

Staff need a local service that exposes the analysis database and the Spec 001 review model to the
web application. Every request comes from a signed-in staff account. The service shows what
already exists today (12 videos, 100 anonymous participants, and their face detections), plus the
review records (annotations, review clips, labels, history). Those review records are empty until
the later clip pipeline or staff creating annotations by hand fills them. The service adds no
business rules of its own: it delegates to the Spec 001 domain functions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Staff sign in, and nobody else gets in (Priority: P1)

A staff member opens the application and signs in with a username and password created for them
by an administrator on the local machine. They stay signed in while they work and can sign out.
Anyone without a valid session gets nothing except the sign-in endpoint.

**Why this priority**: The constitution requires authenticated access to everything, and review
actions need a trustworthy reviewer identity.

**Independent Test**: Create an account with the local command, sign in, call a protected
endpoint, sign out, and confirm the same call is refused.

**Acceptance Scenarios**:

1. **Given** an account created with the local command, **When** the staff member signs in with
   the right password, **Then** a session is established and "who am I" returns their username.
2. **Given** a wrong password or unknown username, **When** sign-in is attempted, **Then** it is
   refused with the same generic message in both cases.
3. **Given** no session, an expired session, or a signed-out session, **When** any endpoint other
   than sign-in is called, **Then** it is refused as unauthenticated.
4. **Given** a stored account, **When** the database is inspected, **Then** no plaintext password
   is present, only a slow one-way hash.
5. **Given** a disabled account, **When** it signs in or uses an existing session, **Then** it is
   refused.

---

### User Story 2 - Dashboard overview of the footage (Priority: P1)

A signed-in staff member sees every processed video with its title, length, number of anonymous
participants seen, and a review summary (annotations by review status, number of review clips). The
list is useful today, even though there are no annotations or clips yet.

**Why this priority**: The dashboard is the entry point the team wants to build next.

**Independent Test**: Against the real database, list videos and confirm 12 entries with correct
durations and participant counts, and zero annotation counts.

**Acceptance Scenarios**:

1. **Given** the existing database, **When** videos are listed, **Then** all 12 appear with title,
   duration, frame rate, participant count, detection count, and review counts.
2. **Given** a video with no annotations or clips, **When** its summary is read, **Then** the
   counts are zero, not missing, and the response does not suggest processing failed.
3. **Given** a video id that does not exist, **When** it is requested, **Then** a not-found error is
   returned.

---

### User Story 3 - Watch a video and see who is on screen (Priority: P1)

A staff member opens one video, plays it in the browser, and sees which anonymous participants
appear and roughly when. Presence comes from the existing face detections. It is a read-only view
of machine signals, not a review record.

**Why this priority**: Without clips, presence is the only timeline content available for the
video view, and playback is needed for any review.

**Independent Test**: Stream a video with byte-range requests and read the presence intervals for
one participant, then compare them with that participant's detections.

**Acceptance Scenarios**:

1. **Given** a video file present on disk, **When** it is streamed, **Then** the browser can play it
   and seek (partial content is supported).
2. **Given** a video whose file is missing, **When** it is streamed, **Then** a clear not-found
   error is returned, not an empty success.
3. **Given** a video, **When** its participants are read, **Then** each participant appears once
   with first and last appearance time, detection count, and presence intervals. Detections closer
   together than the gap tolerance are merged into one interval.

---

### User Story 4 - Look up an anonymous participant across videos (Priority: P2)

A staff member picks `Person_0001` and sees every video that person appears in, with first and last
appearance times and the number of detections, along with any annotations and clips involving them.

**Why this priority**: The participant view is a core MVP screen. It depends on the same data as
the video view.

**Independent Test**: Read a participant known to appear in 3 videos and confirm all 3 are listed.

**Acceptance Scenarios**:

1. **Given** the participant list, **When** it is read, **Then** all 100 participants appear with the
   number of videos and detections for each.
2. **Given** a participant, **When** their detail is read, **Then** each video they appear in is
   listed once, in video order, with appearance times.
3. **Given** an unknown participant id, **When** it is requested, **Then** a not-found error is
   returned.

---

### User Story 5 - Review annotations through the service (Priority: P1)

A staff member lists annotations for a video or participant, opens one, and accepts, edits,
rejects, defers, or creates one. The reviewer recorded in history is always the signed-in account,
never a value the client sends.

**Why this priority**: Human review is the core of the product. The service is how the
application reaches the Spec 001 review rules.

**Independent Test**: Create an annotation through the service, edit it, read its history, and
confirm the reviewer is the signed-in username and source/status follow Spec 001.

**Acceptance Scenarios**:

1. **Given** a signed-in reviewer, **When** they create an annotation with an active label and a
   valid span, **Then** it is stored as source HUMAN, status ACCEPTED, and history records their
   username.
2. **Given** an annotation, **When** a reviewer edits the label, **Then** the response shows the
   new current state and Spec 001 source/status rules apply.
3. **Given** a request body that includes a reviewer id, **When** a review action is made, **Then**
   the reviewer id is ignored or refused, and the signed-in username is recorded.
4. **Given** an invalid edit (a deactivated label, a span beyond the video, a category change),
   **When** it is submitted, **Then** a validation error is returned and nothing changes.
5. **Given** default listing, **When** annotations are listed, **Then** rejected ones are excluded
   unless explicitly requested.

---

### User Story 6 - Read labels, clips, history, and export (Priority: P2)

A staff member sees the active label choices for review, the review clips (once the pipeline
produces them) by video or by priority, an annotation's history, and can download current
annotations or the history as CSV or JSON.

**Why this priority**: Needed by the review and export screens, but each is a thin read.

**Independent Test**: Read labels (18 starter labels), read empty clip lists, and download a CSV
export that opens in a spreadsheet tool.

**Acceptance Scenarios**:

1. **Given** the starter labels, **When** labels are listed, **Then** active labels are returned with
   category. Inactive labels are included only when requested.
2. **Given** clips exist, **When** they are listed by priority, **Then** they come back highest first,
   with the review-priority score clearly separate from any confidence.
3. **Given** a request for an export, **When** it is downloaded, **Then** the file has the Spec 001
   export columns, excludes rejected annotations by default, and has a download filename.

### Edge Cases

- Malformed ids or query values (non-integer video id, unknown review status): refused with a
  validation error.
- A stored video path that resolves outside the videos directory: refused, never served.
- Two reviewers act on the same annotation at once: Spec 001 serializes them, and both actions are
  recorded.
- A database missing the review or staff tables: the service refuses to start with a clear message
  rather than failing per request.
- A session token that is valid but belongs to an account disabled since sign-in: refused.
- Many failed sign-in attempts: each attempt costs a slow hash check. Lockout is out of scope.
- No annotations and no clips (today's state): every list returns an empty array with success.

## Requirements *(mandatory)*

### Functional Requirements

**Access**

- **FR-001**: Every endpoint except sign-in and a liveness check MUST require a valid staff session.
  Authorization MUST be enforced in the service, not the client.
- **FR-002**: Staff accounts MUST have a unique username, a password stored only as an Argon2 hash,
  an active flag, and a created timestamp. Passwords MUST never be logged or returned.
- **FR-003**: Accounts MUST be created, disabled, and have passwords reset only through a local
  command run on the machine. There is no self-registration and no web account management.
- **FR-004**: Sign-in MUST establish a session carried in an HttpOnly, SameSite=Strict cookie.
  The session MUST expire after a fixed lifetime, and sign-out MUST end it immediately.
  Only a hash of the session token is stored.
- **FR-005**: A failed sign-in MUST return the same response whether the username or the password
  was wrong.
- **FR-006**: The reviewer identity for every review action MUST be the signed-in account's
  username. Clients MUST NOT be able to supply it.
- **FR-007**: The service MUST bind to `127.0.0.1` by default. Wider binding is an explicit option.

**Read endpoints**

- **FR-008**: Videos MUST be listable and readable individually, with title, duration, fps, frame
  count, participant count, detection count, annotation counts by review status (rejected
  included in the counts), and clip count.
- **FR-009**: A video's participants MUST be listable with first/last appearance seconds,
  detection count, and presence intervals derived from detections, using a documented gap
  tolerance. Presence is computed on read and not stored.
- **FR-010**: Participants MUST be listable with video and detection counts, and readable
  individually with the videos they appear in.
- **FR-011**: Annotations MUST be listable with the Spec 001 filters (video, frame range,
  participant, label, category, source, review status, clip, include rejected) and readable
  individually, including the label name and category, seconds, confidence, source, and status.
- **FR-012**: Review clips MUST be listable by video in time order, by participant, and across
  videos by priority. The priority score and its method MUST be reported separately from
  confidence, never as a percentage.
- **FR-013**: Labels MUST be listable, active only by default, with optional category filter and
  inactive inclusion.
- **FR-014**: An annotation's review history MUST be readable in chronological order.

**Review endpoints**

- **FR-015**: Create, Accept, Edit, Reject, and Defer MUST be available, each with an optional note,
  and MUST call the Spec 001 review functions unchanged. Each returns the resulting current
  annotation and the appended history event.
- **FR-016**: Domain validation failures MUST return a client error with the domain message and
  change nothing. A missing resource named in the URL (annotation, video, participant) MUST
  return not-found. A nonexistent label, participant, or clip referenced in a request body is a
  validation error.

**Media and export**

- **FR-017**: Video files MUST be streamable with byte-range support. Paths MUST be resolved from
  the database and confined to the videos directory.
- **FR-018**: Current annotations (rejected excluded unless requested) and review history MUST be
  downloadable as CSV and JSON using the Spec 001 export functions.

**Operation**

- **FR-019**: The service MUST use a configurable database path that defaults to a git-ignored
  working copy, so accounts, sessions, and review history never enter the tracked
  `data/analysis.sqlite`.
- **FR-020**: The service MUST verify at startup that the database has the analysis, review, and
  staff tables, and MUST refuse to start otherwise.
- **FR-021**: The API schema the service publishes MUST be the contract the frontend consumes.
- **FR-022**: The service MUST make no outbound network calls.

### Key Entities

- **Staff Account**: username (unique, used as the opaque reviewer id), password hash, active flag,
  created time.
- **Session**: hashed token, account, created and expiry time.
- **Presence Interval**: computed, not stored. One participant's continuous on-screen span in one
  video, from detections no further apart than the gap tolerance.
- All other entities (Video, Participant, Detection, Label, Annotation, Review Clip, Review Event)
  come from Spec 001 unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of endpoints other than sign-in and liveness refuse requests without a valid
  session, verified by an automated test that walks the published API schema.
- **SC-002**: On the real database, the video list returns all 12 videos and the participant list
  all 100 participants, each in under 1 second on a team laptop.
- **SC-003**: A video's participant presence returns in under 1 second for the longest video.
- **SC-004**: Every review action made through the service records the signed-in username as
  reviewer in 100% of automated checks.
- **SC-005**: A video plays and seeks in a desktop browser served by the service.
- **SC-006**: Every endpoint has an automated test.

## Assumptions

- Clips and annotations are empty until the later clip and annotation pipeline runs, or staff
  create annotations by hand. The service handles that state as normal.
- All signed-in staff have the same permissions. Roles are out of scope until a feature needs them.
- Session lifetime is 12 hours. There is no "remember me".
- The presence gap tolerance is 2 seconds. Detections are sampled about every 5 frames, so
  shorter gaps are detection flicker rather than the person leaving.
- The web application is served from the same origin as the service in production, or through
  the dev server's proxy in development, so no cross-origin access is enabled.
- Label management (create, rename, deactivate), video upload, and processing status are out of
  scope. They belong to later roadmap features.
- Out of scope: the frontend itself, the clip pipeline, model execution, and account lockout or
  rate limiting.
