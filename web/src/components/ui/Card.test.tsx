// ABOUTME: Unit tests for the Card component — renders children, accepts className overrides.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Card } from "./Card";

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText("Card content")).toBeInTheDocument();
  });

  it("includes base border and shadow classes", () => {
    const { container } = render(<Card>Content</Card>);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("rounded-lg");
    expect(div.className).toContain("border-gray-200");
    expect(div.className).toContain("shadow-sm");
  });

  it("merges additional className", () => {
    const { container } = render(<Card className="mt-4">Content</Card>);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("mt-4");
  });

  it("renders nested children correctly", () => {
    render(
      <Card>
        <h2>Title</h2>
        <p>Paragraph</p>
      </Card>,
    );
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Paragraph")).toBeInTheDocument();
  });
});
