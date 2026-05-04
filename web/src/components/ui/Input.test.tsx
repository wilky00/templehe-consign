// ABOUTME: Unit tests for Input atoms — TextInput, Select, Textarea, Checkbox.
// ABOUTME: Covers label association, error states, aria-invalid, and hint text.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TextInput, Select, Textarea, Checkbox } from "./Input";

// ---------------------------------------------------------------------------
// TextInput
// ---------------------------------------------------------------------------

describe("TextInput", () => {
  it("renders a labeled input", () => {
    render(<TextInput id="email" label="Email" />);
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("input is associated with its label via id", () => {
    render(<TextInput id="name" label="Full name" />);
    const input = screen.getByLabelText("Full name");
    expect(input).toHaveAttribute("id", "name");
  });

  it("shows error message when error prop is provided", () => {
    render(<TextInput id="email" label="Email" error="Invalid email" />);
    expect(screen.getByText("Invalid email")).toBeInTheDocument();
  });

  it("sets aria-invalid when error is provided", () => {
    render(<TextInput id="email" label="Email" error="Required" />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("does not set aria-invalid without error", () => {
    render(<TextInput id="email" label="Email" />);
    expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-invalid");
  });

  it("shows hint text when no error", () => {
    render(<TextInput id="url" label="URL" hint="Include https://" />);
    expect(screen.getByText("Include https://")).toBeInTheDocument();
  });

  it("hides hint when error is present (error takes precedence)", () => {
    render(<TextInput id="url" label="URL" hint="Include https://" error="Bad URL" />);
    expect(screen.queryByText("Include https://")).not.toBeInTheDocument();
    expect(screen.getByText("Bad URL")).toBeInTheDocument();
  });

  it("calls onChange on typing", async () => {
    const onChange = vi.fn();
    render(<TextInput id="name" label="Name" onChange={onChange} />);
    await userEvent.type(screen.getByLabelText("Name"), "Alice");
    expect(onChange).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Select
// ---------------------------------------------------------------------------

describe("Select", () => {
  const OPTIONS = [
    { value: "a", label: "Option A" },
    { value: "b", label: "Option B" },
  ];

  it("renders a labeled select", () => {
    render(<Select id="choice" label="Pick one" options={OPTIONS} />);
    expect(screen.getByLabelText("Pick one")).toBeInTheDocument();
  });

  it("renders all options", () => {
    render(<Select id="choice" label="Pick one" options={OPTIONS} />);
    expect(screen.getByRole("option", { name: "Option A" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Option B" })).toBeInTheDocument();
  });

  it("renders placeholder option when provided", () => {
    render(
      <Select id="choice" label="Pick" options={OPTIONS} placeholder="Select…" />,
    );
    expect(screen.getByRole("option", { name: "Select…" })).toBeInTheDocument();
  });

  it("shows error message", () => {
    render(<Select id="choice" label="Pick" options={OPTIONS} error="Required" />);
    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("sets aria-invalid on error", () => {
    render(<Select id="choice" label="Pick" options={OPTIONS} error="Bad" />);
    expect(screen.getByLabelText("Pick")).toHaveAttribute("aria-invalid", "true");
  });
});

// ---------------------------------------------------------------------------
// Textarea
// ---------------------------------------------------------------------------

describe("Textarea", () => {
  it("renders a labeled textarea", () => {
    render(<Textarea id="notes" label="Notes" />);
    expect(screen.getByLabelText("Notes")).toBeInTheDocument();
  });

  it("shows error message", () => {
    render(<Textarea id="notes" label="Notes" error="Too long" />);
    expect(screen.getByText("Too long")).toBeInTheDocument();
  });

  it("sets aria-invalid on error", () => {
    render(<Textarea id="notes" label="Notes" error="Required" />);
    expect(screen.getByLabelText("Notes")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows hint text", () => {
    render(<Textarea id="notes" label="Notes" hint="Max 500 chars" />);
    expect(screen.getByText("Max 500 chars")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Checkbox
// ---------------------------------------------------------------------------

describe("Checkbox", () => {
  it("renders a labeled checkbox", () => {
    render(<Checkbox id="agree" label="I agree" />);
    expect(screen.getByLabelText("I agree")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    render(<Checkbox id="agree" label="I agree" description="Read the terms" />);
    expect(screen.getByText("Read the terms")).toBeInTheDocument();
  });

  it("calls onChange when clicked", async () => {
    const onChange = vi.fn();
    render(<Checkbox id="agree" label="I agree" onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalled();
  });

  it("renders as checked when defaultChecked", () => {
    render(<Checkbox id="agree" label="I agree" defaultChecked />);
    expect(screen.getByRole("checkbox")).toBeChecked();
  });
});
