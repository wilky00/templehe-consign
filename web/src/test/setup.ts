// ABOUTME: Global Vitest setup — jest-dom matchers + MSW server lifecycle for every test file.
// ABOUTME: Imported via vite.config.ts setupFiles; runs before each test module.
import "@testing-library/jest-dom";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";
import { useAuthStore } from "../state/auth";

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => {
  server.resetHandlers();
  useAuthStore.setState({ accessToken: null });
});
afterAll(() => server.close());
