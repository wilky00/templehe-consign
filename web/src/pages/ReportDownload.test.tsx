// ABOUTME: Phase 7 — Vitest tests for the PDF report download UI in EquipmentDetail.
// ABOUTME: Covers generating state, ready state (download link), and non-eligible status gating.
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { EquipmentDetailPage } from "./EquipmentDetail";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";

const RECORD_ID = "00000000-0000-0000-0000-000000000099";

function makeRecord(status: string) {
  return {
    id: RECORD_ID,
    reference_number: "THE-00099",
    status,
    make: "Caterpillar",
    model: "320",
    year: 2019,
    serial_number: null,
    hours: null,
    running_status: null,
    ownership_type: null,
    location_text: null,
    description: null,
    photos: [],
    status_events: [],
  };
}

function setupEquipmentHandler(status: string) {
  server.use(
    http.get(`http://localhost/api/v1/me/equipment/${RECORD_ID}`, () =>
      HttpResponse.json(makeRecord(status)),
    ),
    http.get(
      `http://localhost/api/v1/me/equipment/${RECORD_ID}/change-requests`,
      () => HttpResponse.json([]),
    ),
  );
}

describe("ReportCard in EquipmentDetailPage", () => {
  it("hides the report card when status is new_request", async () => {
    setupEquipmentHandler("new_request");
    renderWithProviders(<EquipmentDetailPage />, {
      initialEntries: [`/portal/equipment/${RECORD_ID}`],
      path: "/portal/equipment/:id",
    });
    await waitFor(() =>
      expect(screen.getByText("THE-00099")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("heading", { name: /appraisal report/i }),
    ).not.toBeInTheDocument();
  });

  it("shows generating message when report is not yet ready", async () => {
    setupEquipmentHandler("approved_pending_esign");
    // Default handler returns 202 generating
    renderWithProviders(<EquipmentDetailPage />, {
      initialEntries: [`/portal/equipment/${RECORD_ID}`],
      path: "/portal/equipment/:id",
    });
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /appraisal report/i }),
      ).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/your report is being prepared/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows download link when report is ready", async () => {
    setupEquipmentHandler("approved_pending_esign");
    server.use(
      http.get(
        `http://localhost/api/v1/equipment-records/${RECORD_ID}/report/pdf`,
        () =>
          HttpResponse.json({
            download_url: "https://r2.example.com/signed.pdf",
            expires_at: "2026-05-03T14:00:00Z",
          }),
      ),
    );
    renderWithProviders(<EquipmentDetailPage />, {
      initialEntries: [`/portal/equipment/${RECORD_ID}`],
      path: "/portal/equipment/:id",
    });
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /download pdf/i })).toHaveAttribute(
        "href",
        "https://r2.example.com/signed.pdf",
      ),
    );
  });
});
