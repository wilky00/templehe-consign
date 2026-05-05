// ABOUTME: Tests for AdminReportsPage — tab rendering, filter controls, data display, export buttons.
// ABOUTME: Phase 8 Sprint 4; MSW provides canned responses for all four report endpoints.
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { AdminReportsPage } from "./AdminReports";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";

describe("AdminReportsPage", () => {
  it("renders the page title and all four tab labels", async () => {
    renderWithProviders(<AdminReportsPage />);
    expect(await screen.findByRole("heading", { name: /admin reports/i })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: /sales by period/i })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: /type\/location/i })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: /user traffic/i })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: /export center/i })).toBeInTheDocument();
  });

  it("shows Sales by Period table and charts by default", async () => {
    renderWithProviders(<AdminReportsPage />);
    // Summary table header
    expect(await screen.findByText("2026-04")).toBeInTheDocument();
    expect(await screen.findByText("2026-05")).toBeInTheDocument();
    // Formatted dollar value
    expect(await screen.findByText("$120,000")).toBeInTheDocument();
  });

  it("Sales by Period tab shows period selector and Export CSV button", async () => {
    renderWithProviders(<AdminReportsPage />);
    await screen.findByText("2026-05");
    expect(screen.getByRole("combobox")).toBeInTheDocument(); // period type select
    expect(screen.getByRole("button", { name: /export csv/i })).toBeInTheDocument();
  });

  it("switching to User Traffic tab renders metric cards", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />);
    const trafficTab = await screen.findByRole("tab", { name: /user traffic/i });
    await user.click(trafficTab);
    expect(await screen.findByText("Sessions")).toBeInTheDocument();
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(await screen.findByText("35.0%")).toBeInTheDocument();
    expect(await screen.findByText("8")).toBeInTheDocument();
  });

  it("User Traffic tab shows top pages table", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />);
    const trafficTab = await screen.findByRole("tab", { name: /user traffic/i });
    await user.click(trafficTab);
    expect(await screen.findByText("/listings")).toBeInTheDocument();
    expect(await screen.findByText("50")).toBeInTheDocument();
  });

  it("switching to Sales by Type/Location renders equipment type table", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />);
    const typeTab = await screen.findByRole("tab", { name: /type\/location/i });
    await user.click(typeTab);
    expect(await screen.findByText("Dozers")).toBeInTheDocument();
    expect(await screen.findByText("Backhoe Loaders")).toBeInTheDocument();
  });

  it("Type/Location tab sub-view switcher renders By state table on click", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />);
    const typeTab = await screen.findByRole("tab", { name: /type\/location/i });
    await user.click(typeTab);
    await screen.findByText("Dozers");
    const stateBtn = screen.getByRole("tab", { name: /by state/i });
    await user.click(stateBtn);
    expect(await screen.findByText("TX")).toBeInTheDocument();
    expect(await screen.findByText("CA")).toBeInTheDocument();
  });

  it("Export Center tab shows a download button for each report type", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />);
    const exportTab = await screen.findByRole("tab", { name: /export center/i });
    await user.click(exportTab);
    expect(await screen.findByRole("button", { name: /download sales by period csv/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download sales by equipment type csv/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download sales by state csv/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download portal traffic csv/i })).toBeInTheDocument();
  });

  it("shows error alert when sales-by-period endpoint fails", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/reports/sales-by-period", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    renderWithProviders(<AdminReportsPage />);
    await screen.findByRole("tab", { name: /sales by period/i });
    expect(await screen.findByText(/could not load report/i)).toBeInTheDocument();
  });

  it("shows empty state message when period report returns no rows", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/reports/sales-by-period", () =>
        HttpResponse.json({ period_type: "month", rows: [] }),
      ),
    );
    renderWithProviders(<AdminReportsPage />);
    await screen.findByRole("tab", { name: /sales by period/i });
    expect(
      await screen.findByText(/no approved records match/i),
    ).toBeInTheDocument();
  });

  it("changing period type triggers refetch with correct param", async () => {
    const user = userEvent.setup();
    let capturedUrl = "";
    server.use(
      http.get("http://localhost/api/v1/admin/reports/sales-by-period", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ period_type: "quarter", rows: [] });
      }),
    );
    renderWithProviders(<AdminReportsPage />);
    await screen.findByRole("tab", { name: /sales by period/i });
    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "quarter");
    await waitFor(() => expect(capturedUrl).toContain("period_type=quarter"));
  });

  it("avg days shows em-dash when value is null", async () => {
    server.use(
      http.get("http://localhost/api/v1/admin/reports/sales-by-period", () =>
        HttpResponse.json({
          period_type: "month",
          rows: [
            {
              period_label: "2026-05",
              record_count: 1,
              approved_count: 1,
              direct_purchase_count: 1,
              consignment_count: 0,
              total_approved_offer: 50000,
              total_consignment_price: 0,
              avg_days_to_publish: null,
            },
          ],
        }),
      ),
    );
    renderWithProviders(<AdminReportsPage />);
    expect(await screen.findByText("2026-05")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
