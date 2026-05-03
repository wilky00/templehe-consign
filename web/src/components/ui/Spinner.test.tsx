// ABOUTME: Unit tests for the Spinner — ARIA role, label, size variants.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Spinner } from "./Spinner";

describe("Spinner", () => {
  it("has role=status", () => {
    render(<Spinner />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("uses default label 'Loading'", () => {
    render(<Spinner />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading");
  });

  it("accepts a custom label", () => {
    render(<Spinner label="Saving changes" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Saving changes");
  });

  it("renders md size classes by default", () => {
    render(<Spinner />);
    expect(screen.getByRole("status").className).toContain("h-6");
    expect(screen.getByRole("status").className).toContain("w-6");
  });

  it("renders sm size classes", () => {
    render(<Spinner size="sm" />);
    expect(screen.getByRole("status").className).toContain("h-4");
    expect(screen.getByRole("status").className).toContain("w-4");
  });
});
