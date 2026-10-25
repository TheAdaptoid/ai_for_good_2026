import { defineConfig, devices } from '@playwright/test'

// End-to-end: real browser → Vite dev server → FastAPI on a fresh copy of data/analysis.sqlite.
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1, // tests share one database
  reporter: [['list']],
  // No traces or videos: they would capture participant footage from the player.
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'off', video: 'off', screenshot: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: './e2e/start-backend.sh', url: 'http://127.0.0.1:8001/api/health', timeout: 120_000, reuseExistingServer: false },
    { command: 'npx vite --port 5174 --strictPort', url: 'http://127.0.0.1:5174', env: { TPA_API: 'http://127.0.0.1:8001' }, reuseExistingServer: false },
  ],
})
