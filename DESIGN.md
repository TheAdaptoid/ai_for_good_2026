# Staff application design

The shipping React application is a staff review tool. Preserve its neutral light/dark palette,
system typography, top navigation, and player/timeline/panel workflow. The direction-decision
HTML sketches under `.impeccable/mocks/decision/` are exploratory references, not shipping screens
or a mandate to replace the application's visual identity during a refinement pass.

Use the shared tokens and controls in `frontend/src/styles.css`. Body text is 16px with 1.5 line
height; headings establish hierarchy without decorative labels. White or dark neutral surfaces
use fine borders, no shadows. Blue indicates actions/activity; teal indicates observations;
purple indicates clips. Source and review status remain separate, explicit text badges. Dashed
annotation bars indicate unreviewed AI suggestions; solid bars indicate reviewed values.

Ordinary buttons are at least 40px tall. Focus has a visible, theme-specific outline. Keep Reject
separate from Accept, Edit, and Defer. Forms share label spacing, paired time fields, and error
messages. Empty states are normal workflow states. Preserve the subtle full-border/background
dashboard notice introduced in `6004efa`.

Below 900px, player/panel and participant/detail layouts stack; the participant list scrolls
within a bounded area. Below 600px, navigation reflows and the header stops sticking. Wide tables
and timelines scroll within keyboard-focusable regions; do not squeeze their content into
unreadable rows. Long titles, notes, usernames, and method names must wrap.

No external fonts, decorative assets, imagery, animation, or new dependencies are needed for
this pass. Participant media must never enter AI context: disable traces, videos, and automatic
screenshots; mask every video element in deliberate captures. See D023.

Validation and narrow Impeccable exceptions are recorded in
`docs/design/staff-ui-refinement.md`.
