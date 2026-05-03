// ABOUTME: Vite build configuration for the React frontend.
// ABOUTME: Proxies /api requests to the FastAPI server on port 8000 during local dev.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        // 127.0.0.1 not localhost — on macOS the resolver tries ::1 first
        // and Node's proxy blocks ~35s falling back to IPv4 when the API
        // listens on 0.0.0.0. Same trap as SMTP to Mailpit.
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  define:
    mode === "test"
      ? {
          // MSW Node server needs an absolute URL to intercept fetch calls.
          // Relative URLs (/api/v1/...) throw in Node.js native fetch.
          "import.meta.env.VITE_API_BASE_URL": JSON.stringify(
            "http://localhost/api/v1",
          ),
        }
      : {},
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: [
      "**/node_modules/**",
      "**/e2e/**", // Playwright specs — excluded from Vitest
      "**/dist/**",
    ],
    // forks pool: each test file gets its own child process so that
    // heavy DOM environments (happy-dom + React 18) don't share V8 heap
    // with sibling workers; avoids OOM on Node 25.x.
    pool: "forks",
    poolOptions: {
      forks: { maxForks: 4, minForks: 1 },
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/test/**",
        "src/main.tsx",
        "src/App.tsx",
        "**/*.d.ts",
      ],
    },
  },
}));
