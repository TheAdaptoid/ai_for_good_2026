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

## Follow-up: always light mode

The user requested white/light UI throughout. Removed the automatic dark palette and set
`color-scheme: light`, including native form controls. The existing dark-device-preference
browser variant now verifies that every captured screen still uses a light color scheme and
white navigation/login surfaces. The original validation above describes the initial pass;
dark mode is no longer a shipping option.

## Follow-up: database verification and Agentation

Verified the shipping path: React API client → Vite `/api` proxy → FastAPI request database
connection → SQLite catalog/current-state queries. There is no shipping mock-data fallback.
The running service explicitly selects `data/demo.local.sqlite`; read-only inspection found
12 videos, 100 anonymous participants, 123 review clips, and 329 AI/unreviewed annotations, with
an import recorded as `tpa-local-analysis` version `1.0.0`. No application database was changed.

Added Agentation 3.1.2 as a development-only dependency with a localhost:4747 MCP endpoint and
light toolbar initialization. Production bundle inspection finds no Agentation code. The
dependency's PolyForm Shield license and local text-only workflow are documented in the
frontend README. A synthetic sign-in-screen feedback note made the browser → local server →
connected MCP trip successfully and was removed after verification. No media was captured.

Validation: 25 Vitest tests, 15 privacy-safe Playwright tests (including toolbar presence/light
appearance), 38 catalog/API tests, typecheck, lint, production build, and shipping-source
Impeccable detection all pass. The backend tests report one existing Starlette/AnyIO deprecation
warning. Spec 005 implementation and the previously unfinished files remain untouched.

## Agentation feedback: navigation and review page

Implemented feedback 1, 2, 5, 6, and 7: queue metadata sits inline with clip information;
Browse participants is a button; the queue is on `/review`; navigation is a vertical sidebar
with a Review entry. On narrow screens the vertical navigation stacks above the content.
For feedback 3, Export opens CSV/JSON downloads for current annotations or review history;
the menu now explains this purpose. Video files are not exported.

Feedback 4, “Unreviewed Clips,” requires a count-semantics clarification. The existing column
counts individual annotations, not distinct clips. Its data and label remain unchanged pending
the user's choice; it must not be relabeled as clips while displaying annotation counts.

Validation: 25 Vitest tests, typecheck, lint, production build, 16 privacy-safe Playwright tests,
and the shipping-source Impeccable scan pass. Browser coverage includes the reported
2400×1092 viewport, inline queue metadata, vertically arranged navigation, the dedicated page,
participant-button navigation, export help, and narrow layouts. Captures contain synthetic data
or masked players and stay git-ignored. No database, API, or Spec 005 implementation changed.
Agentation notes remain acknowledged for human review; they were not auto-resolved.
