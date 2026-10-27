import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  expect: { timeout: 12000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5175',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    channel: process.env.CI ? undefined : 'chrome',
  },
  webServer: [
    {
      command:
        process.platform === 'win32'
          ? '..\\.venv\\py312\\Scripts\\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8011 --app-dir ..'
          : 'python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8011 --app-dir ..',
      url: 'http://127.0.0.1:8011/api/health',
      reuseExistingServer: false,
      timeout: 120000,
      env: {
        AGENT_MODE: 'off',
        STREAM_TRANSPORT: 'local',
        FRONTEND_ORIGIN: 'http://localhost:5175',
        BUDGET_FILE: path.resolve('../.venv/owner-d-browser-budget.json'),
      },
    },
    {
      command: 'npm run dev -- --port 5175',
      url: 'http://localhost:5175',
      reuseExistingServer: false,
      env: { EVERYFAN_LOCAL_API: 'http://127.0.0.1:8011', VITE_API_BASE_URL: '' },
    },
  ],
});
