# frontend

React + TypeScript (strict) + Vite staff app for TPA video review. It talks only to the local
FastAPI service (`backend/`), which the Vite dev server reaches through a same-origin `/api` proxy.

## Run

Start the service first (see `backend/README.md`, "Application service"), then:

```bash
npm ci
npm run dev        # http://127.0.0.1:5173 (proxies /api to http://127.0.0.1:8000)
```

Sign in with an account created by `backend/scripts/staff.py create <username>`.

Use the vertical navigation to open Dashboard, Review (`/review`), or Participants. The Review
page holds the review queue, ordered by priority. Export on the dashboard downloads current
annotations or review history as CSV/JSON.

## Data source

The staff screens fetch `/api` through FastAPI, which queries the SQLite file selected by the
backend's `--db` option (or `TPA_DB`). The default is `data/analysis.local.sqlite`; an explicit
`--db ../data/demo.local.sqlite` uses that database instead. Frontend test fixtures are used
only by Vitest/Playwright; they are not loaded as application data or used as API fallbacks.

## Agentation feedback

The development app includes the Agentation toolbar, connected to the local MCP server at
`http://localhost:4747`. Open the feedback button at the bottom right, select a UI element,
and add a note. The connected agent can read and acknowledge those notes. Feedback is separate
from participant annotations and never writes to the application's SQLite database.

Keep the MCP server running while annotating. If needed, start the already configured server
with `npx agentation-mcp server`. Use the browser toolbar on desktop; its documentation is at
https://www.agentation.com/mcp. The toolbar starts light and is excluded from production builds.
It sends text/DOM context to localhost, not screenshots or participant footage. Do not put
participant media into notes or configure external webhooks.

Agentation 3.1.2 is a development-only dependency under PolyForm Shield 1.0.0 (source-available,
with restrictions on competing products); its license is included in the installed package.
It is not part of the shipping application bundle.

## Checks

```bash
npm run typecheck  # tsc -b (strict)
npm run lint       # oxlint
npm test           # Vitest + Testing Library component/workflow tests (fetch mocked)
npm run test:e2e   # Playwright: real Chromium → Vite → FastAPI on a fresh copy of data/analysis.sqlite
npm run build
```

- `npm run test:e2e` needs `uv` and the backend environment, the tracked `data/analysis.sqlite`,
  and the local videos in `data/videos/` for playback checks. First run
  `npx playwright install chromium`. The suite builds its own database under `e2e/.tmp/` and
  uses ports 8001 (service) and 5174 (Vite), so your working database is never touched.
- Playwright traces, videos, and failure screenshots are off, and the e2e screenshots mask the
  player, so no participant footage lands in test artifacts (Constitution I).
- The `design` Playwright project checks synthetic staff screens at 320, 390, 768, 1280, and 2400px,
  plus a desktop dark device preference to verify the app always stays light. It checks reflow,
  keyboard presence seeking, skip navigation, and
  review-panel text contrast; covers login, dashboard, participants, clip/review/create/edit,
  empty, and error states; and aborts all media requests. Its masked captures stay in ignored
  `test-results/design/`. Run it with `npm run test:e2e -- --project=design`.

## API types

`src/api/schema.d.ts` is generated from the service's OpenAPI schema and committed. After
changing the API, run `npm run gen:api`, which uses `backend/scripts/openapi.py`.
