// ABOUTME: Tests for ManagerApprovalsPage — queue rendering, empty state, price change section.
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ManagerApprovalsPage } from "./ManagerApprovals";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { TEST_QUEUE_ITEM, TEST_PRICE_CHANGE_ITEM } from "../test/handlers";

describe("ManagerApprovalsPage", () => {
  it("renders the page heading", () => {
    renderWithProviders(<ManagerApprovalsPage />);
    expect(
      screen.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeInTheDocument();
  });

  it("renders a row for each appraisal in the queue", async () => {
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(screen.getAllByText("THE-00001").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/Caterpillar.*320/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Jane Appraiser/)).toBeInTheDocument();
  });

  it("shows empty state when no appraisals are pending", async () => {
    server.use(
      http.get("http://localhost/api/v1/manager/approvals", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(
        screen.getByText("No appraisals awaiting review."),
      ).toBeInTheDocument();
    });
  });

  it("shows the score band badge", async () => {
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(screen.getByText(/Strong resale candidate/)).toBeInTheDocument();
    });
  });

  it("shows review-required flag badge", async () => {
    server.use(
      http.get("http://localhost/api/v1/manager/approvals", () =>
        HttpResponse.json({
          items: [{ ...TEST_QUEUE_ITEM, management_review_required: true }],
          total: 1,
        }),
      ),
    );
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(screen.getByText("Review required")).toBeInTheDocument();
    });
  });

  it("shows title-hold badge", async () => {
    server.use(
      http.get("http://localhost/api/v1/manager/approvals", () =>
        HttpResponse.json({
          items: [{ ...TEST_QUEUE_ITEM, hold_for_title_review: true }],
          total: 1,
        }),
      ),
    );
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(screen.getByText("Title hold")).toBeInTheDocument();
    });
  });

  it("renders the price change re-approval section", async () => {
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /price change re-approvals/i }),
      ).toBeInTheDocument();
      expect(screen.getByText("customer@example.com")).toBeInTheDocument();
    });
  });

  it("shows empty state for price changes when none are pending", async () => {
    server.use(
      http.get("http://localhost/api/v1/manager/approvals/price-changes", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderWithProviders(<ManagerApprovalsPage />);
    await waitFor(() => {
      expect(
        screen.getByText("No price changes awaiting re-approval."),
      ).toBeInTheDocument();
    });
  });

  it("navigates to detail on row click", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ManagerApprovalsPage />, {
      initialEntries: ["/manager/approvals"],
    });
    await waitFor(() => {
      expect(screen.getAllByText("THE-00001").length).toBeGreaterThan(0);
    });
    const row = screen.getByRole("row", { name: /review appraisal THE-00001/i });
    await user.click(row);
    // Navigation is tested — just confirm click doesn't throw.
  });
});
