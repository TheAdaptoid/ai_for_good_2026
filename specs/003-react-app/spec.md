# Feature Specification: TPA Staff Review Web Application

**Feature Branch**: `003-react-app`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "Make the dashboard etc. first; the data such as the clips themselves
will be a later step." This combines roadmap items 005 (shell and dashboard), 006 (video timeline),
007 (participant view), and 008 (human review interface). It is built on the Spec 002 service. It
uses the data that exists today: videos, anonymous participants, detection-based presence, labels,
and any annotations. Clip content arrives later (D018).

## Overview

Staff use a browser application on their own machine to sign in, see the footage, watch a video
with a timeline of who is on screen, look up an anonymous participant across videos, and review
or add annotations. Everything they see comes from the Spec 002 service. The application never
computes or stores review data of its own.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sign in and out (Priority: P1)

A staff member opens the application, sees a sign-in form, enters their username and password,
and lands on the dashboard. Their username is shown in the header with a sign-out button. If their
session ends, the next action returns them to sign-in.

**Independent Test**: Sign in with valid and invalid credentials, then sign out.

**Acceptance Scenarios**:

1. **Given** no session, **When** any page is opened, **Then** the sign-in form is shown.
2. **Given** wrong credentials, **When** submitted, **Then** a generic error is shown and the form
   stays.
3. **Given** a signed-in user, **When** they sign out, **Then** the sign-in form is shown and the
   protected pages are no longer reachable.
4. **Given** a session that expires while working, **When** the next request fails as
   unauthenticated, **Then** the sign-in form is shown.

---

### User Story 2 - Dashboard (Priority: P1)

After signing in, staff see every video with title, length, number of anonymous participants,
number of review clips, and a review summary (unreviewed, accepted, edited, deferred, rejected).
Totals across all videos sit at the top. Each video opens its video view, and a participants entry
point opens the participant view.

**Independent Test**: Sign in against the real data and see 12 videos with participant counts and
zero review counts.

**Acceptance Scenarios**:

1. **Given** the 12 processed videos, **When** the dashboard loads, **Then** all 12 appear with
   length and participant count.
2. **Given** no annotations or clips yet, **When** the dashboard loads, **Then** review counts show
   0, with a note that suggestions appear once the clip pipeline has run. Nothing looks like an
   error.
3. **Given** the service is unreachable, **When** the dashboard loads, **Then** a visible error
   with a retry option is shown.

---

### User Story 3 - Video view with timeline (Priority: P1)

Staff open a video and see a player and, under it, a timeline as long as the video. The timeline
has a row for review clips (with their review priority), a row for scene-level annotations, and
one row per anonymous participant. Each participant row shows when that person is on screen
(from detections) and their annotations, colored by label category and marked by review status.
Clicking anywhere on the timeline, a presence bar, or an annotation seeks the player to that
moment. A playhead follows playback.

**Independent Test**: Open the shortest video, click a participant's presence bar, and confirm
the player seeks to that time.

**Acceptance Scenarios**:

1. **Given** a video, **When** it opens, **Then** the player loads the video and the timeline lists
   every participant seen in it, ordered by first appearance.
2. **Given** a click on a presence bar or annotation, **When** it happens, **Then** the player seeks
   to its start time.
3. **Given** annotations exist, **When** shown, **Then** each shows its label, and its review
   status and source are readable at a glance. Unreviewed AI suggestions look visibly different
   from human-reviewed values.
4. **Given** rejected annotations, **When** the timeline is shown, **Then** they are hidden unless
   the reviewer turns on "show rejected".
5. **Given** review clips exist, **When** shown, **Then** each displays its review priority as a
   plain number labeled "review priority", never as a percentage or a confidence.
6. **Given** a participant ID on the timeline, **When** it is clicked, **Then** the participant view
   opens for that person.
7. **Given** a link with a time (for example from the participant view), **When** the video view
   opens, **Then** the player starts at that time.

---

### User Story 4 - Participant view (Priority: P1)

Staff choose an anonymous participant, such as `Person_0001`, from a searchable list and see
every video they appear in, in order, with first and last appearance, a small timeline of their
presence in each video, and their annotations (label, time, status). Clicking a presence bar or
an annotation opens that video at that moment.

**Independent Test**: Choose `Person_0001` and confirm the 6 videos they appear in are listed, each
opening the video at the right time.

**Acceptance Scenarios**:

1. **Given** the participant list, **When** staff type part of an ID, **Then** the list filters.
2. **Given** a participant, **When** selected, **Then** each video they appear in is shown once with
   appearance times and presence.
3. **Given** their annotations, **When** shown, **Then** they are the same records the video view
   shows, with the same status and labels.

---

### User Story 5 - Review an annotation (Priority: P1)

Selecting an annotation opens a review panel that shows its label, category, time span,
participant, model confidence (if any), source, and review status. Staff can Accept, Reject, or
Defer with an optional note, or Edit the label (same category, active labels only), the time
span, or the participant. After an action, the panel and every view show the new current state,
and the panel shows the annotation's history.

**Independent Test**: Create an annotation, edit its label, and confirm the timeline and
participant view show the new label, source HUMAN, status EDITED, and two history entries.

**Acceptance Scenarios**:

1. **Given** an AI annotation, **When** accepted, **Then** status shows ACCEPTED and source stays AI.
2. **Given** an annotation, **When** its label is changed, **Then** status shows EDITED and source
   HUMAN, and the timeline updates.
3. **Given** an invalid edit (span beyond the video), **When** saved, **Then** the service's message
   is shown and nothing changes.
4. **Given** the label picker, **When** opened, **Then** only active labels of the annotation's
   category are offered.
5. **Given** the history section, **When** shown, **Then** each entry shows action, reviewer, time,
   note, and what changed.

---

### User Story 6 - Add a missed moment (Priority: P2)

From the video view, staff create an annotation: choose an active label (activity or observation),
set start and end (or use the current player time), and optionally choose a participant from
those in the video. It appears on the timeline immediately as a human, accepted record.

**Acceptance Scenarios**:

1. **Given** the player at 12.0 s, **When** "use current time" is pressed for start, **Then** the
   start field is 12.0 s.
2. **Given** a valid form, **When** saved, **Then** the new annotation appears in its row as HUMAN /
   ACCEPTED.
3. **Given** end before start, **When** saved, **Then** an error is shown and nothing is created.

---

### User Story 7 - Export (Priority: P2)

From the dashboard, staff download current annotations (CSV or JSON) and review history (CSV or
JSON).

**Acceptance Scenarios**:

1. **Given** the export menu, **When** "Annotations CSV" is chosen, **Then** a file downloads from
   the service export.

### Edge Cases

- A video file missing on disk: the player shows "video file unavailable", and the timeline still
  works.
- A video with dozens of participants: rows scroll vertically. The header and playhead stay
  usable.
- A participant with no detections in any video: the participant view says they appear in no
  videos.
- Two staff edit the same annotation: the second sees the result after their action. The service
  orders them.
- Unknown route or unknown video/participant id: a not-found message with a link to the
  dashboard.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every page except sign-in MUST require a signed-in session. Any unauthenticated
  response MUST return the user to sign-in.
- **FR-002**: The application MUST talk only to the Spec 002 service, and its data types MUST be
  generated from the service's published API schema.
- **FR-003**: The dashboard MUST list all videos with title, duration, participant count, clip
  count, and review counts by status, plus totals, and MUST link to each video and to participants.
- **FR-004**: The video view MUST play the video with seeking, and MUST show a timeline with a clip
  row, a scene-annotation row, and one row per participant (presence plus that person's
  annotations), a playhead, and click-to-seek.
- **FR-005**: Unreviewed AI suggestions and human-reviewed records MUST be visually distinct.
  Source and review status MUST be shown as separate, labeled values.
- **FR-006**: Review priority MUST be labeled "review priority" and shown as a plain number. Model
  confidence MUST be labeled "model confidence". Neither may appear as the other, and priority
  MUST NOT be shown as a percentage.
- **FR-007**: Rejected annotations MUST be hidden by default and shown only when the reviewer asks.
- **FR-008**: Affect labels MUST be shown with their observational names exactly as stored (for
  example "Visible Positive Affect").
- **FR-009**: The participant view MUST offer a filterable participant list and, for the chosen
  participant, their videos with appearance times, presence, and annotations, each linking to
  the video at that moment.
- **FR-010**: The review panel MUST offer Accept, Reject, Defer (with optional note) and Edit
  (label within category from active labels, start/end, participant), MUST show the service's
  error message on failure, and MUST show the history after each action.
- **FR-011**: Creating an annotation MUST be possible from the video view with an active label,
  start/end (with "use current time"), optional participant, and an optional note.
- **FR-012**: After any review action, every visible view MUST reflect the service's current state
  without a manual reload.
- **FR-013**: Export links for annotations and history in CSV and JSON MUST be available.
- **FR-014**: Loading, empty, and error states MUST be explicit on every page. All controls MUST be
  keyboard-reachable with a visible focus indicator.
- **FR-015**: The application MUST load no external resources (fonts, scripts, analytics). It
  works fully offline on the local machine.

### Key Entities

Uses the Spec 002 resources unchanged: staff account, video summary, video participant (with
presence intervals), participant detail, annotation, review event, review clip, and label.

## Success Criteria *(mandatory)*

- **SC-001**: A staff member can go from sign-in to playing a video at a chosen participant's first
  appearance in under 4 clicks.
- **SC-002**: The video view for the longest video (73 participants, 2,000+ presence intervals)
  renders its timeline in under 1 second on a team laptop.
- **SC-003**: Automated frontend tests cover sign-in, the dashboard, the video view seek, the
  participant view, and a review action, and they pass. Type check and lint pass.
- **SC-004**: A full manual run on real data (sign in → video → participant → create → edit →
  history → export) completes without errors.

## Assumptions

- Development uses the Vite dev server with a proxy to the service on `127.0.0.1:8000`, so the
  session cookie is same-origin. A production build is served the same way or behind any
  same-origin setup. Serving the built files from the service is out of scope.
- Time inputs are entered in seconds and converted to frames using the video's frame rate. The
  service validates the bounds.
- A desktop browser layout is targeted. Phone layouts are out of scope for this staff tool, but
  the layout must not break at narrow widths.
- Label management screens, video upload, and processing status are out of scope (later
  features).
