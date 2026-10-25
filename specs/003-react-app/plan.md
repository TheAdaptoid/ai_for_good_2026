# Implementation Plan: TPA Staff Review Web Application

**Branch**: `003-react-app` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

## Summary

A Vite + React + TypeScript (strict) single-page app in `frontend/`. API types are generated
from the Spec 002 OpenAPI schema with `openapi-typescript`. Data access goes through one small
`fetch` wrapper that redirects to sign-in on 401. Routing uses `react-router-dom`. Styling is plain
CSS with design tokens, light and dark. There is no UI kit and no external fonts. Tests use Vitest +
Testing Library + jsdom, with `fetch` mocked at the wrapper boundary.

## Technical Context

**Language/Version**: TypeScript (strict), React 19, Node ≥ 20 for tooling

**Primary Dependencies**: react, react-dom, react-router-dom. Dev: vite, @vitejs/plugin-react,
typescript, vitest, jsdom, @testing-library/react, @testing-library/user-event,
@testing-library/jest-dom, oxlint (ships with the Vite template), openapi-typescript,
@playwright/test.
All are pinned exactly in `package.json`, and `package-lock.json` is committed.

**Storage**: none. All state comes from the service. The URL holds the selected video, time, and
annotation.

**Testing**: `npm test` (Vitest component and workflow tests), `npm run test:e2e` (Playwright, a real
browser against the real service on a fresh copy of the seed DB), `npm run typecheck` (tsc -b), and
`npm run lint` (oxlint)

**Target Platform**: desktop browsers on the local machine

**Performance Goals**: timeline for the longest video (≈2.3k presence intervals) renders in < 1 s
(SC-002). Bars are absolutely positioned divs, which is enough at this scale.

**Constraints**: no external network resources. Same-origin through the Vite proxy (`/api` →
`http://127.0.0.1:8000`).

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I. Local-only media | ✅ | Video streamed from the local service. No CDN, fonts, or analytics |
| II. Anonymous identity | ✅ | Shows only `Person_####` IDs |
| IV. Humans decide | ✅ | AI/unreviewed is styled distinctly (dashed outline). Source and status are separate badges. "Review priority" and "model confidence" are labeled separately. Priority is never a percentage |
| V. Current state | ✅ | Views re-fetch from the service after each action. There is no client copy of annotation state |
| VI. One model | ✅ | Video and participant views both read `/api/annotations`. Labels come from `/api/labels` |
| VII. Boundaries | ✅ | Frontend uses only the HTTP API |
| VIII. Security | ✅ | Cookie session handled by the browser. The frontend never stores credentials. Authorization is enforced by the service |
| IX. Visible failure | ✅ | Every fetch has explicit loading, error (retry), and empty states. Missing video file shown as such |
| X. Tests | ✅ | Vitest workflow tests per user story, plus Playwright end-to-end on real data. Artifacts never capture footage (player masked, traces off) |
| XI. Reproducible | ✅ | Exact pins plus lockfile. README run steps |
| XII. Usable | ✅ | Keyboard-reachable controls with visible focus. Review state readable at a glance |

## Project Structure

```text
frontend/
├── package.json, package-lock.json, vite.config.ts, playwright.config.ts, tsconfig*.json, index.html
├── e2e/                      # Playwright specs + start-backend.sh (fresh DB copy, port 8001)
├── scripts/                  # (none: schema dump lives in backend/scripts/openapi.py)
└── src/
    ├── main.tsx              # router + auth provider
    ├── api/schema.d.ts       # generated, committed
    ├── api/client.ts         # fetch wrapper, typed helpers, 401 → signed-out event
    ├── auth.tsx              # session context: me / login / logout
    ├── hooks.ts              # useResource(fetcher, deps) → {data, error, loading, reload}
    ├── format.ts             # seconds ↔ mm:ss, frames ↔ seconds
    ├── components/           # Layout, StatusBadge, Timeline, ReviewPanel, CreateForm, States
    ├── pages/                # Login, Dashboard, VideoView, Participants, NotFound
    ├── styles.css
    └── test/                 # setup + workflow tests
backend/scripts/openapi.py    # writes the app's OpenAPI JSON for type generation
```

## Key design decisions

- **D1 Type generation**: `backend/scripts/openapi.py` prints `create_app(...).openapi()`. It needs
  a database, so it builds a temp initialized database. `npm run gen:api` runs it and
  `openapi-typescript`. Generated `schema.d.ts` is committed, so builds do not need Python.
- **D2 Refresh after review**: the video view owns `annotations` and passes `reload` to the panel.
  The participant view fetches its own. Both read the same endpoint, so both show current state
  (FR-012).
- **D3 Timeline**: one shared time scale (`left = t / duration * 100%`). Row label column is
  sticky. Click on the track maps the x position to a time and seeks. The playhead updates on
  `timeupdate`.
- **D4 Frames ↔ seconds**: the create/edit forms take seconds, and conversion uses
  `Math.round(s * fps)`. Displays use the service's `start_seconds`/`end_seconds`.
- **D5 Auth flow**: `AuthProvider` calls `/api/auth/me` on load. Any 401 from the client clears
  the user, which renders the Login page.

## Complexity Tracking

| Item | Why | Simpler alternative rejected |
|---|---|---|
| One feature for roadmap 005–008 | Screens share the timeline, review panel, and API client. Splitting them would duplicate scaffolding cycles | Separate features would ship a dashboard with no reachable review |
| openapi-typescript (dev) | Constitution X makes the OpenAPI schema the contract. Generated types catch drift in typecheck | Hand-written types drift silently |
