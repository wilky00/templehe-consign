// ABOUTME: Vite build configuration for the React frontend.
// ABOUTME: Proxies /api requests to the FastAPI server on port 8000 during local dev.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
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
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [],
  },
});
