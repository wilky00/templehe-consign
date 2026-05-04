// ABOUTME: Smoke tests for AdminOperationsPage — renders queue, empty state, filter controls, modal trigger.
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { AdminOperationsPage } from "./AdminOperations";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import type { AdminOperationsRow } from "../api/types";

const SAMPLE_ROW: AdminOperationsRow = {
  id: "00000000-0000-0000-0000-000000000099",
  reference_number: "THE-000099",
  status: "new_request",
  status_display: "New request",
  days_in_status: 2,
  customer_id: "00000000-0000-0000-0000-000000000002",
  customer_name: "Bob Jones",
  business_name: "Jones Farm Supply",
  state: "OK",
  make: "John Deere",
  model: "310SL",
  year: 2020,
  assigned_sales_rep_id: null,
  assigned_sales_rep_name: null,
  assigned_appraiser_id: null,
  assigned_appraiser_name: null,
  is_overdue: false,
  submitted_at: "2026-05-01T08:00:00Z",
  updated_at: "2026-05-01T08:00:00Z",
};

describe("AdminOperationsPage", () => {
  it("renders the page heading", () => {
    renderWithProviders(<AdminOperationsPage />);
    expect(screen.getByRole("heading", { name: /operations/i })).toBeInTheDocument();
  });

  it("shows empty state when no records match", async () => {
    renderWithProviders(<AdminOperationsPage />);
    await waitFor(() => {
      expect(
        screen.getByText("No records match these filters."),
      ).toBeInTheDocument();
    });
  });

  it("renders a row for each returned record", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/operations", () =>
        HttpResponse.json({
          rows: [SAMPLE_ROW],
          total: 1,
          page: 1,
          per_page: 50,
        }),
      ),
    );
    renderWithProviders(<AdminOperationsPage />);
    await waitFor(() => {
      expect(screen.getByText("THE-000099")).toBeInTheDocument();
    });
    expect(screen.getByText("Jones Farm Supply")).toBeInTheDocument();
  });

  it("renders a status badge for each row", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/operations", () =>
        HttpResponse.json({
          rows: [SAMPLE_ROW],
          total: 1,
          page: 1,
          per_page: 50,
        }),
      ),
    );
    renderWithProviders(<AdminOperationsPage />);
    await waitFor(() => {
      expect(screen.getByText("New request")).toBeInTheDocument();
    });
  });

  it("renders filter controls", () => {
    renderWithProviders(<AdminOperationsPage />);
    // Use exact string to avoid matching "Overdue only (≥ 7 days in current status)"
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByLabelText("Sort by")).toBeInTheDocument();
  });

  it("opens the transition modal when Transition is clicked", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/operations", () =>
        HttpResponse.json({
          rows: [SAMPLE_ROW],
          total: 1,
          page: 1,
          per_page: 50,
        }),
      ),
    );
    renderWithProviders(<AdminOperationsPage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^transition$/i })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: /^transition$/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/manually transition record/i)).toBeInTheDocument();
  });

  it("shows error alert when the API request fails", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/operations", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    renderWithProviders(<AdminOperationsPage />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });

  it("renders an Export CSV button", () => {
    renderWithProviders(<AdminOperationsPage />);
    expect(screen.getByRole("button", { name: /export csv/i })).toBeInTheDocument();
  });

  it("highlights overdue rows with a red background", async () => {
    const overdueRow: AdminOperationsRow = {
      ...SAMPLE_ROW,
      id: "00000000-0000-0000-0000-000000000098",
      is_overdue: true,
      days_in_status: 10,
    };
    server.use(
      http.get("http://localhost/api/v1/admin/operations", () =>
        HttpResponse.json({
          rows: [overdueRow],
          total: 1,
          page: 1,
          per_page: 50,
        }),
      ),
    );
    renderWithProviders(<AdminOperationsPage />);
    await waitFor(() => {
      // The row is rendered — find the <tr> via the reference number cell
      const refCell = screen.getByText("THE-000099");
      const row = refCell.closest("tr");
      expect(row?.className).toContain("bg-red-50");
    });
  });

  it("updates status filter when a new option is selected", async () => {
    renderWithProviders(<AdminOperationsPage />);
    // Use exact string "Status" to avoid matching the checkbox label text
    const select = screen.getByLabelText("Status") as HTMLSelectElement;
    await userEvent.selectOptions(select, "appraiser_assigned");
    expect(select.value).toBe("appraiser_assigned");
  });
});
