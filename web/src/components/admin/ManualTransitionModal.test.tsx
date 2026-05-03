// ABOUTME: Tests for ManualTransitionModal — form validation, submit, cancel, error display.
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ManualTransitionModal } from "./ManualTransitionModal";
import { renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import type { AdminOperationsRow } from "../../api/types";

const ROW: AdminOperationsRow = {
  id: "00000000-0000-0000-0000-000000000001",
  reference_number: "THE-000001",
  status: "new_request",
  status_display: "New request",
  days_in_status: 3,
  customer_id: "00000000-0000-0000-0000-000000000002",
  customer_name: "Alice Smith",
  business_name: null,
  state: "TX",
  make: "Caterpillar",
  model: "320",
  year: 2018,
  assigned_sales_rep_id: null,
  assigned_sales_rep_name: null,
  assigned_appraiser_id: null,
  assigned_appraiser_name: null,
  is_overdue: false,
  submitted_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:00:00Z",
};

describe("ManualTransitionModal", () => {
  it("renders the modal dialog", () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Manually transition record")).toBeInTheDocument();
  });

  it("shows the record reference number", () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    expect(screen.getByText(/THE-000001/)).toBeInTheDocument();
  });

  it("disables submit when no status is selected", () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    expect(
      screen.getByRole("button", { name: /apply transition/i }),
    ).toBeDisabled();
  });

  it("disables submit when status selected but reason is empty", async () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/destination status/i),
      "appraiser_assigned",
    );
    expect(
      screen.getByRole("button", { name: /apply transition/i }),
    ).toBeDisabled();
  });

  it("enables submit when both status and reason are filled", async () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/destination status/i),
      "appraiser_assigned",
    );
    await userEvent.type(screen.getByLabelText(/reason/i), "Testing transition");
    expect(
      screen.getByRole("button", { name: /apply transition/i }),
    ).toBeEnabled();
  });

  it("calls onClose when cancel is clicked", async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={onClose} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose after a successful transition", async () => {
    const onClose = vi.fn();
    server.use(
      http.post(
        "http://localhost/api/v1/admin/equipment/:id/transition",
        () => HttpResponse.json({ detail: "ok" }),
      ),
    );
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={onClose} />,
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/destination status/i),
      "appraiser_assigned",
    );
    await userEvent.type(screen.getByLabelText(/reason/i), "Test reason");
    await userEvent.click(
      screen.getByRole("button", { name: /apply transition/i }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it("shows error alert when the server returns an error", async () => {
    server.use(
      http.post(
        "http://localhost/api/v1/admin/equipment/:id/transition",
        () =>
          HttpResponse.json(
            { detail: "Forbidden transition" },
            { status: 422 },
          ),
      ),
    );
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/destination status/i),
      "appraiser_assigned",
    );
    await userEvent.type(screen.getByLabelText(/reason/i), "Test reason");
    await userEvent.click(
      screen.getByRole("button", { name: /apply transition/i }),
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/Forbidden transition/i)).toBeInTheDocument();
    });
  });

  it("excludes the current status from destination options", () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    const options = screen.getAllByRole("option");
    const optionValues = options.map((o) => (o as HTMLOptionElement).value);
    expect(optionValues).not.toContain("new_request");
  });

  it("notifications checkbox is checked by default", () => {
    renderWithProviders(
      <ManualTransitionModal row={ROW} onClose={vi.fn()} />,
    );
    expect(screen.getByRole("checkbox")).toBeChecked();
  });
});
