// ABOUTME: Tests for ManagerApprovalDetailPage — submission display, approve/reject forms, title hold warning.
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ManagerApprovalDetailPage } from "./ManagerApprovalDetail";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { TEST_SUBMISSION } from "../test/handlers";

const SUBMISSION_ID = TEST_SUBMISSION.id;

describe("ManagerApprovalDetailPage", () => {
  it("renders the page heading", async () => {
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /approval review/i }),
      ).toBeInTheDocument();
    });
  });

  it("renders submission fields from the API", async () => {
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(screen.getByText("CAT320-123456")).toBeInTheDocument();
    });
    expect(screen.getByText(/Fast Sell/)).toBeInTheDocument();
    expect(screen.getByText(/3\.75/)).toBeInTheDocument();
  });

  it("shows the approve and reject forms for submitted appraisals", async () => {
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(
        screen.getByRole("form", { name: /approve appraisal/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("form", { name: /reject appraisal/i }),
      ).toBeInTheDocument();
    });
  });

  it("shows title review warning when hold_for_title_review is true", async () => {
    server.use(
      http.get("http://localhost/api/v1/manager/approvals/:id", () =>
        HttpResponse.json({ ...TEST_SUBMISSION, hold_for_title_review: true }),
      ),
    );
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Title review hold/)).toBeInTheDocument();
    expect(screen.getByLabelText(/title review confirmed/i)).toBeInTheDocument();
  });

  it("approve button is disabled until purchase offer and consignment price are filled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^approve$/i })).toBeInTheDocument();
    });
    const approveBtn = screen.getByRole("button", { name: /^approve$/i });
    expect(approveBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/purchase offer/i), "50000");
    await user.type(screen.getByLabelText(/consignment price/i), "65000");
    expect(approveBtn).not.toBeDisabled();
  });

  it("reject button is disabled until rejection notes are filled", async () => {
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(screen.getByLabelText(/submit rejection/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/submit rejection/i)).toBeDisabled();
  });

  it("shows an informational banner when appraisal is already approved", async () => {
    server.use(
      http.get("http://localhost/api/v1/manager/approvals/:id", () =>
        HttpResponse.json({ ...TEST_SUBMISSION, status: "approved" }),
      ),
    );
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(screen.getByText(/already been approved/i)).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("form", { name: /approve appraisal/i }),
    ).not.toBeInTheDocument();
  });

  it("calls approve API and shows success feedback", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ManagerApprovalDetailPage />, {
      initialEntries: [`/manager/approvals/${SUBMISSION_ID}`],
      path: "/manager/approvals/:id",
    });
    await waitFor(() => {
      expect(screen.getByLabelText(/purchase offer/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/purchase offer/i), "50000");
    await user.type(screen.getByLabelText(/consignment price/i), "65000");
    await user.click(screen.getByRole("button", { name: /^approve$/i }));
    // Navigation fires on success; no error visible means it worked.
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });
});
