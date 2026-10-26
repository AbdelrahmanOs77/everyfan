import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  expect: { timeout: 12000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    channel: process.env.CI ? undefined : 'chrome',
  },
  webServer: [
    {
      command:
        process.platform === 'win32'
          ? '..\\.venv\\py312\\Scripts\\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --app-dir ..'
          : 'python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --app-dir ..',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
      env: {
        AGENT_MODE: 'off',
        STREAM_TRANSPORT: 'local',
        FRONTEND_ORIGIN: 'http://localhost:5173',
        BUDGET_FILE: '.venv/owner-d-browser-budget.json',
      },
    },
    { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: !process.env.CI },
  ],
});
