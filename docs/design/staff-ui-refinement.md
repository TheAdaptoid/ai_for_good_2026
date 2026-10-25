# Staff UI refinement — 2026-10-25

## Reconstructed starting state

- Branch: `005-local-analysis-generation`, HEAD `d547b22`.
- Most recent UI change: `6004efa`, softening the dashboard notice border; preceding staff app
  implementation: `158758d`.
- Existing unstaged/untracked work includes Spec 005 generation code, Spec Kit tooling changes,
  PRODUCT.md, and Impeccable direction sketches/notes. The design pass uses a separate branch,
  `style/staff-ui-refinement`, and leaves generation/tooling work untouched and uncommitted.
- The shipping frontend had no pending edits. The Theater Program direction was described in
  a local surface brief but not implemented. This refinement preserves the incumbent app.

## Shipping changes

Shared spacing and typography improve login, dashboard cards/table, participants, queues,
forms, panels, and messages. Controls and timeline rows are larger. Reject is separated from
routine review actions. Presence markers are native keyboard buttons; skip navigation and
focusable table/timeline scroll regions support keyboard use. Long content wraps and narrow
layouts retain usable data widths. Observation text, reviewed bars in dark mode, and focus
colors have theme-appropriate contrast. No backend/API/review semantics change.

Rendered create-form inspection also exposed an existing navigation bug: opening Add annotation
from a review panel issued two search-parameter updates from the same snapshot, leaving the
annotation selected and showing two panels. Clearing both selections in one update fixes the
cause; each responsive browser variant verifies that the old panel and query selections close.

## Impeccable triage

The installed Impeccable 4.7.1 launcher is at
`~/.claude/plugins/cache/impeccable/impeccable/4.7.1/skills/impeccable/scripts/impeccable`.
Claude's hooks are configured in its plugin, but automatic hooks are not active in this Codex
session; the detector was invoked explicitly.

`impeccable detect --json frontend/src` reports no findings. Scanning the shipping source and
the three decision sketches together exits 0 after these supported `hooks ignore-value`
exceptions, all persisted with reasons in `.impeccable/config.json`:

| Sketch | Non-shipping findings excepted |
| --- | --- |
| `assigned.html` | low-contrast, cramped-padding, tiny-text |
| `model-pick.html` | cramped-padding, cream-palette |
| `canon.html` | low-contrast, cramped-padding, overused-font (`inter` only) |

Each exception applies to one rule in one exact sketch file. No shipping path, entire file, or
global rule is suppressed. The sketches are absent from frontend imports/build inputs and were
not edited. A non-blocking `repeating-stripes-gradient` advisory remains in `model-pick.html`;
it is sanctioned as a throwaway decision sketch, not production decoration.

The context tool also reports an unset `buildPath` preference for future Persuade/Experience
surfaces. It does not affect these code-first app screens and was left unchanged. A future
landing/showcase task can choose code-first or comp-first independently.

## Validation

- `npm test`: 25 Vitest tests pass; Vitest retained.
- `npm run typecheck`, `npm run lint`, `npm run build`: pass.
- `npm run test:e2e`: 15 Playwright tests pass: five synthetic design variants and ten existing
  current/imported-data workflow tests, using disposable database copies.
- Design variants: 320, 390, 768, 1280px light; 1280px dark. Each covers login, populated and
  empty dashboard, error message, participants, review/clip panels, edit/create forms,
  no document overflow, skip navigation, keyboard presence seeking, visible focus, and sampled
  review text/control contrast of at least 4.5:1.
- Rendered captures inspected for desktop, tablet, mobile, dark mode, forms, review, and states.
  Captures are masked or fully synthetic with media requests aborted, and remain git-ignored.
- Impeccable source/sketch scan: exit 0, only the documented non-shipping advisory remains.
- `git diff --check`: pass. Only frontend, design documentation, and narrow detector policy
  files belong in this commit. No databases, media, screenshots, cache, or speculative sketches.

This is a Chromium design/workflow pass, not a full accessibility certification. Safari,
Firefox, screen-reader testing, and backend/ML test suites are outside this frontend change.
Spec 005 remains unfinished and was not resumed.
