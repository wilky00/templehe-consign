// ABOUTME: Unit tests for StatusBadge — known status labels, tone colors, unknown fallback.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders 'New request' for new_request", () => {
    render(<StatusBadge status="new_request" />);
    expect(screen.getByText("New request")).toBeInTheDocument();
  });

  it("renders 'Declined' for declined", () => {
    render(<StatusBadge status="declined" />);
    expect(screen.getByText("Declined")).toBeInTheDocument();
  });

  it("renders 'Approved — pending eSign' for approved_pending_esign", () => {
    render(<StatusBadge status="approved_pending_esign" />);
    expect(screen.getByText("Approved — pending eSign")).toBeInTheDocument();
  });

  it("renders 'Listed' for listed", () => {
    render(<StatusBadge status="listed" />);
    expect(screen.getByText("Listed")).toBeInTheDocument();
  });

  it("falls back to the raw status string for unknown statuses", () => {
    render(<StatusBadge status="some_unknown_status" />);
    expect(screen.getByText("some_unknown_status")).toBeInTheDocument();
  });

  it("applies red classes for declined", () => {
    render(<StatusBadge status="declined" />);
    expect(screen.getByText("Declined").className).toContain("bg-red-100");
  });

  it("applies green classes for sold", () => {
    render(<StatusBadge status="sold" />);
    expect(screen.getByText("Sold").className).toContain("bg-green-100");
  });

  it("applies gray classes for unknown status", () => {
    render(<StatusBadge status="mystery_status" />);
    expect(screen.getByText("mystery_status").className).toContain("bg-gray-100");
  });
});
