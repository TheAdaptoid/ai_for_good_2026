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
- The `design` Playwright project checks synthetic staff screens at 320, 390, 768, and 1280px,
  plus desktop dark mode. It checks reflow, keyboard presence seeking, skip navigation, and
  review-panel text contrast; covers login, dashboard, participants, clip/review/create/edit,
  empty, and error states; and aborts all media requests. Its masked captures stay in ignored
  `test-results/design/`. Run it with `npm run test:e2e -- --project=design`.

## API types

`src/api/schema.d.ts` is generated from the service's OpenAPI schema and committed. After
changing the API, run `npm run gen:api`, which uses `backend/scripts/openapi.py`.
