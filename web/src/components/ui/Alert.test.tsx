// ABOUTME: Unit tests for the Alert component — tone, title, children, ARIA roles.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Alert } from "./Alert";

describe("Alert", () => {
  it("renders children", () => {
    render(<Alert>Something went wrong</Alert>);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("renders a title", () => {
    render(<Alert title="Heads up">Details here</Alert>);
    expect(screen.getByText("Heads up")).toBeInTheDocument();
    expect(screen.getByText("Details here")).toBeInTheDocument();
  });

  it("uses role=alert for error tone", () => {
    render(<Alert tone="error">Error</Alert>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("uses role=alert for warning tone", () => {
    render(<Alert tone="warning">Warning</Alert>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("uses role=status for info tone", () => {
    render(<Alert tone="info">Info</Alert>);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("uses role=status for success tone", () => {
    render(<Alert tone="success">Done</Alert>);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("defaults to info tone (role=status)", () => {
    render(<Alert>Default</Alert>);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders without children", () => {
    render(<Alert title="Title only" />);
    expect(screen.getByText("Title only")).toBeInTheDocument();
  });
});
