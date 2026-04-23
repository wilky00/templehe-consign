// ABOUTME: Playwright config — E2E + axe-core specs under ./e2e, targets local dev by default.
// ABOUTME: Auto-starts vite on a free port unless E2E_SKIP_WEBSERVER=1 (set by CI after starting vite itself).
import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:5173";
const API_URL = process.env.E2E_API_URL || "http://localhost:8000";
const MAILPIT_URL = process.env.E2E_MAILPIT_URL || "http://localhost:8025";

// When E2E_SKIP_WEBSERVER is set, Playwright assumes the web app is already
// running at BASE_URL (useful during local dev with `npm run dev` in another
// terminal, and in CI where the job starts vite in the background).
const skipWebServer = process.env.E2E_SKIP_WEBSERVER === "1";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: skipWebServer
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1 --port 5173",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});

export { API_URL, BASE_URL, MAILPIT_URL };
