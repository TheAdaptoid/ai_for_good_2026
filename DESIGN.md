# Staff application design

The shipping React application is a staff review tool. Preserve its light palette, system
typography, vertical sidebar navigation, and player/timeline/panel workflow.

Visual language (2026-10-25, from staff-supplied reference dashboards): a light purple-gray canvas
(`--bg #f3f2f7`) with white cards on it, 16px card corners (`--radius-lg`) and 10px control
corners (`--radius`), a hairline border plus one soft offset shadow (`--shadow`). The sidebar is a
white rail whose links carry an authored line icon (`components/Icon.tsx`, 24px grid, 1.75 stroke)
and a solid purple pill for the active page. Dashboard stat tiles pair a tinted icon disc with a
large ink number and a muted label; they stack icon-over-value below 1600px. Table headers are small
uppercase labels on a faint well, except the Data view, which shows exact CSV column names. The direction-decision
HTML sketches under `.impeccable/mocks/decision/` are exploratory references, not shipping screens
or a mandate to replace the application's visual identity during a refinement pass.

Use the shared tokens and controls in `frontend/src/styles.css`. Body text is 16px with 1.5 line
height; headings establish hierarchy without decorative labels. White cards
use a hairline border and the shared soft shadow; do not nest a bordered card inside another. Always use light mode, including when the device prefers dark mode;
native form controls use `color-scheme: light`. Blue indicates actions/activity; teal indicates
observations;
purple indicates clips. Source and review status remain separate, explicit text badges. Dashed
annotation bars indicate unreviewed AI suggestions; solid bars indicate reviewed values.

Ordinary buttons are at least 40px tall. Focus has a visible, contrasting outline. Keep Reject
separate from Accept, Edit, and Defer. Forms share label spacing, paired time fields, and error
messages. Empty states are normal workflow states. Preserve the subtle full-border/background
dashboard notice introduced in `6004efa`.

The Review navigation item opens `/review`, the dedicated review queue page. The dashboard
contains video totals and the video table; participant browsing uses a button. Queue metadata
stays inline with clip information when space allows. Data view (`/data`) previews the exact
database-backed CSV for current annotations or review history and owns the Export menu for
CSV/JSON downloads. The preview scrolls within its own focusable region; empty datasets retain
their CSV headers. The video page has a Back button returning to Dashboard.

Below 900px, player/panel and participant/detail layouts stack; the participant list scrolls
within a bounded area. Below 600px, the vertical navigation stacks above the content and stops sticking. Wide tables
and timelines scroll within keyboard-focusable regions; do not squeeze their content into
unreadable rows. Long titles, notes, usernames, and method names must wrap.

No external fonts, decorative assets, imagery, animation, or new dependencies are needed for
this pass. Participant media must never enter AI context: disable traces, videos, and automatic
screenshots; mask every video element in deliberate captures. See D023.

Validation and narrow Impeccable exceptions are recorded in
`docs/design/staff-ui-refinement.md`.
