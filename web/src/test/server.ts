// ABOUTME: MSW Node server instance shared across all Vitest test files.
// ABOUTME: Handlers are reset after each test; per-test overrides via server.use().
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);
