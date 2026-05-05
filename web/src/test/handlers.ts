// ABOUTME: Default MSW request handlers for Vitest tests — cover the endpoints hit on every render.
// ABOUTME: Tests that need different responses call server.use() to override per-test.
import { http, HttpResponse } from "msw";
import type { ApprovalQueueItem, PriceChangeQueueItem, SubmissionDetail } from "../api/approvals";

export const TEST_QUEUE_ITEM: ApprovalQueueItem = {
  submission_id: "00000000-0000-0000-0000-000000000010",
  equipment_record_id: "00000000-0000-0000-0000-000000000020",
  reference_number: "THE-00001",
  make: "Caterpillar",
  model: "320",
  year: 2019,
  overall_score: 3.75,
  score_band: "Strong resale candidate",
  marketability_rating: "Fast Sell",
  appraiser_name: "Jane Appraiser",
  submitted_at: "2026-05-01T10:00:00Z",
  management_review_required: false,
  hold_for_title_review: false,
  red_flags: null,
};

export const TEST_SUBMISSION: SubmissionDetail = {
  id: "00000000-0000-0000-0000-000000000010",
  equipment_record_id: "00000000-0000-0000-0000-000000000020",
  appraiser_id: "00000000-0000-0000-0000-000000000030",
  status: "submitted",
  category_id: "00000000-0000-0000-0000-000000000040",
  make: "Caterpillar",
  model: "320",
  year: 2019,
  hours_condition: null,
  running_status: null,
  serial_number: "CAT320-123456",
  title_status: null,
  overall_score: 3.75,
  score_band: "Strong resale candidate",
  management_review_required: false,
  hold_for_title_review: false,
  review_notes: null,
  marketability_rating: "Fast Sell",
  transport_notes: null,
  listing_notes: null,
  approved_purchase_offer: null,
  suggested_consignment_price: null,
  rejection_notes: null,
  approved_by_id: null,
  approved_at: null,
  red_flags: null,
  comparable_sales_data: null,
  component_scores: [],
  submitted_at: "2026-05-01T10:00:00Z",
  created_at: "2026-05-01T09:00:00Z",
  updated_at: "2026-05-01T10:00:00Z",
};

export const TEST_PRICE_CHANGE_ITEM: PriceChangeQueueItem = {
  change_request_id: "00000000-0000-0000-0000-000000000050",
  equipment_record_id: "00000000-0000-0000-0000-000000000020",
  reference_number: "THE-00001",
  make_model: "Caterpillar 320",
  approved_price: 65000,
  proposed_price: 50000,
  submitted_at: "2026-05-02T08:00:00Z",
  customer_email: "customer@example.com",
};

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

  http.get("http://localhost/api/v1/manager/approvals", () =>
    HttpResponse.json({ items: [TEST_QUEUE_ITEM], total: 1 }),
  ),

  http.get("http://localhost/api/v1/manager/approvals/price-changes", () =>
    HttpResponse.json({ items: [TEST_PRICE_CHANGE_ITEM], total: 1 }),
  ),

  http.get("http://localhost/api/v1/manager/approvals/:id", () =>
    HttpResponse.json(TEST_SUBMISSION),
  ),

  http.post("http://localhost/api/v1/manager/approvals/:id/approve", () =>
    HttpResponse.json({ ...TEST_SUBMISSION, status: "approved" }),
  ),

  http.post("http://localhost/api/v1/manager/approvals/:id/reject", () =>
    HttpResponse.json({ ...TEST_SUBMISSION, status: "rejected" }),
  ),

  http.post("http://localhost/api/v1/record-locks", () =>
    HttpResponse.json({
      record_id: "00000000-0000-0000-0000-000000000010",
      record_type: "equipment_record",
      locked_by: "00000000-0000-0000-0000-000000000001",
      locked_at: "2026-05-03T00:00:00Z",
      expires_at: "2026-05-03T00:05:00Z",
    }),
  ),

  http.delete("http://localhost/api/v1/record-locks/:id", () =>
    new HttpResponse(null, { status: 204 }),
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
    "http://localhost/api/v1/manager/approvals/price-changes/:id/approve",
    () =>
      HttpResponse.json({
        change_request_id: "00000000-0000-0000-0000-000000000050",
        status: "resolved",
        resolved_at: "2026-05-03T00:00:00Z",
        new_consignment_price: 50000,
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

  http.get("http://localhost/api/v1/equipment-records/:id/report/pdf", () =>
    HttpResponse.json(
      { status: "generating", message: "Your report is being prepared. Please check back in a few minutes." },
      { status: 202 },
    ),
  ),

  // Analytics — fire-and-forget; always succeed silently
  http.post("http://localhost/api/v1/analytics/event", () =>
    HttpResponse.json({ recorded: true }),
  ),

  // Admin reports index (static tab list from admin router)
  http.get("http://localhost/api/v1/admin/reports", () =>
    HttpResponse.json({
      tabs: [
        { slug: "sales_by_period", label: "Sales by Period", status: "phase8" },
        { slug: "sales_by_type_location", label: "Sales by Type/Location", status: "phase8" },
        { slug: "user_traffic", label: "User Traffic", status: "phase8" },
        { slug: "export_center", label: "Export Center", status: "phase8" },
      ],
    }),
  ),

  http.get("http://localhost/api/v1/admin/reports/sales-by-period", () =>
    HttpResponse.json({
      period_type: "month",
      rows: [
        {
          period_label: "2026-04",
          record_count: 2,
          approved_count: 2,
          direct_purchase_count: 1,
          consignment_count: 1,
          total_approved_offer: 120000,
          total_consignment_price: 85000,
          avg_days_to_publish: 12.5,
        },
        {
          period_label: "2026-05",
          record_count: 3,
          approved_count: 3,
          direct_purchase_count: 2,
          consignment_count: 1,
          total_approved_offer: 200000,
          total_consignment_price: 90000,
          avg_days_to_publish: 9.0,
        },
      ],
    }),
  ),

  http.get("http://localhost/api/v1/admin/reports/sales-by-type", () =>
    HttpResponse.json({
      rows: [
        {
          category_name: "Dozers",
          record_count: 5,
          approved_count: 4,
          avg_overall_score: 3.75,
          avg_approved_offer: 75000,
          avg_consignment_price: null,
        },
        {
          category_name: "Backhoe Loaders",
          record_count: 3,
          approved_count: 2,
          avg_overall_score: 3.25,
          avg_approved_offer: 45000,
          avg_consignment_price: 50000,
        },
      ],
    }),
  ),

  http.get("http://localhost/api/v1/admin/reports/sales-by-state", () =>
    HttpResponse.json({
      rows: [
        { state: "TX", record_count: 4, approved_count: 3, avg_approved_offer: 80000 },
        { state: "CA", record_count: 2, approved_count: 1, avg_approved_offer: 55000 },
      ],
    }),
  ),

  http.get("http://localhost/api/v1/admin/reports/portal-traffic", () =>
    HttpResponse.json({
      total_sessions: 42,
      unique_users: 15,
      total_page_views: 120,
      top_pages: [
        { page: "/listings", view_count: 50 },
        { page: "/portal/submit", view_count: 30 },
      ],
      form_abandon_rate: 35.0,
      pdf_download_count: 8,
    }),
  ),

  http.get("http://localhost/api/v1/admin/reports/export", () =>
    new HttpResponse("period_label,record_count\n2026-05,3\n", {
      status: 200,
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": 'attachment; filename="sales-by-period.csv"',
      },
    }),
  ),
];
