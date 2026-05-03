// ABOUTME: Default MSW request handlers for Vitest tests — cover the endpoints hit on every render.
// ABOUTME: Tests that need different responses call server.use() to override per-test.
import { http, HttpResponse } from "msw";

export const TEST_USER = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "test@example.com",
  role: "admin",
  roles: ["admin"],
  status: "active",
  first_name: "Test",
  last_name: "User",
  totp_enabled: false,
  requires_terms_reaccept: false,
};

export const handlers = [
  http.get("http://localhost/api/v1/auth/me", () =>
    HttpResponse.json(TEST_USER),
  ),

  http.get("http://localhost/api/v1/record-locks/:id", () =>
    HttpResponse.json(null, { status: 404 }),
  ),

  http.get("http://localhost/api/v1/admin/operations", () =>
    HttpResponse.json({
      rows: [],
      total: 0,
      page: 1,
      per_page: 50,
    }),
  ),

  http.post(
    "http://localhost/api/v1/admin/equipment/:id/transition",
    () =>
      HttpResponse.json({
        record_id: "00000000-0000-0000-0000-000000000001",
        from_status: "new_request",
        to_status: "appraiser_assigned",
        notifications_dispatched: true,
        audit_log_id: "00000000-0000-0000-0000-000000000099",
      }),
  ),

  http.post("http://localhost/api/v1/auth/login", () =>
    HttpResponse.json({ access_token: "fake-token", token_type: "bearer" }),
  ),
];
