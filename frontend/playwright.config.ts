import { defineConfig, devices } from '@playwright/test'

// End-to-end: real browser → Vite dev server → FastAPI on a fresh copy of data/analysis.sqlite.
// "current" runs against the data as it exists today (no clips or annotations); "imported" adds a
// clearly synthetic pipeline file to its own disposable copy to prove the future-data path.
const SYNTHETIC = '../frontend/e2e/fixtures/synthetic-import.json'

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1, // tests within a project share one database
  reporter: [['list']],
  // No traces or videos: they would capture participant footage from the player.
  use: { trace: 'off', video: 'off', screenshot: 'off' },
  projects: [
    { name: 'current', testMatch: 'workflow.spec.ts',
      use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:5174' } },
    { name: 'imported', testMatch: 'imported.spec.ts',
      use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:5175' } },
  ],
  webServer: [
    { command: './e2e/start-backend.sh 8001', url: 'http://127.0.0.1:8001/api/health', timeout: 120_000, reuseExistingServer: false },
    { command: `./e2e/start-backend.sh 8002 ${SYNTHETIC}`, url: 'http://127.0.0.1:8002/api/health', timeout: 120_000, reuseExistingServer: false },
    { command: 'npx vite --port 5174 --strictPort', url: 'http://127.0.0.1:5174', env: { TPA_API: 'http://127.0.0.1:8001' }, reuseExistingServer: false },
    { command: 'npx vite --port 5175 --strictPort', url: 'http://127.0.0.1:5175', env: { TPA_API: 'http://127.0.0.1:8002' }, reuseExistingServer: false },
  ],
})
