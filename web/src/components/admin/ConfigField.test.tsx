// ABOUTME: Tests for ConfigField — type-driven rendering, onChange semantics, disabled state.
// ABOUTME: Uses fireEvent.change for controlled inputs since userEvent.type re-renders on each keystroke.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfigField } from "./ConfigField";
import type { AppConfigItem } from "../../api/types";

function makeSpec(overrides: Partial<AppConfigItem> = {}): AppConfigItem {
  return {
    name: "test_key",
    category: "general",
    field_type: "string",
    description: "A test config key",
    default: null,
    value: null,
    ...overrides,
  };
}

describe("ConfigField", () => {
  describe("string field type", () => {
    it("renders a text input", () => {
      render(
        <ConfigField spec={makeSpec()} draft={null} onChange={vi.fn()} />,
      );
      expect(screen.getByRole("textbox")).toBeInTheDocument();
    });

    it("shows the current draft value", () => {
      render(
        <ConfigField spec={makeSpec()} draft="hello" onChange={vi.fn()} />,
      );
      expect(screen.getByRole("textbox")).toHaveValue("hello");
    });

    it("calls onChange with string value on input", () => {
      const onChange = vi.fn();
      render(
        <ConfigField spec={makeSpec()} draft="" onChange={onChange} />,
      );
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "abc" } });
      expect(onChange).toHaveBeenCalledWith("abc");
    });

    it("calls onChange with null when input is cleared", () => {
      const onChange = vi.fn();
      render(
        <ConfigField spec={makeSpec()} draft="x" onChange={onChange} />,
      );
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
      expect(onChange).toHaveBeenCalledWith(null);
    });

    it("is disabled when disabled prop is true", () => {
      render(
        <ConfigField spec={makeSpec()} draft={null} onChange={vi.fn()} disabled />,
      );
      expect(screen.getByRole("textbox")).toBeDisabled();
    });
  });

  describe("int field type", () => {
    it("renders a number input", () => {
      render(
        <ConfigField
          spec={makeSpec({ field_type: "int" })}
          draft={42}
          onChange={vi.fn()}
        />,
      );
      expect(screen.getByRole("spinbutton")).toBeInTheDocument();
    });

    it("shows the current numeric draft value", () => {
      render(
        <ConfigField
          spec={makeSpec({ field_type: "int" })}
          draft={99}
          onChange={vi.fn()}
        />,
      );
      expect(screen.getByRole("spinbutton")).toHaveValue(99);
    });

    it("calls onChange with a number on input", () => {
      const onChange = vi.fn();
      render(
        <ConfigField
          spec={makeSpec({ field_type: "int" })}
          draft={null}
          onChange={onChange}
        />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5" } });
      expect(onChange).toHaveBeenCalledWith(5);
    });

    it("calls onChange with null when cleared", () => {
      const onChange = vi.fn();
      render(
        <ConfigField
          spec={makeSpec({ field_type: "int" })}
          draft={3}
          onChange={onChange}
        />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "" } });
      expect(onChange).toHaveBeenCalledWith(null);
    });
  });

  describe("list[string] field type", () => {
    it("renders a textarea", () => {
      render(
        <ConfigField
          spec={makeSpec({ field_type: "list[string]" })}
          draft={[]}
          onChange={vi.fn()}
        />,
      );
      expect(screen.getByRole("textbox")).toBeInTheDocument();
    });

    it("joins list items with ', ' for display", () => {
      render(
        <ConfigField
          spec={makeSpec({ field_type: "list[string]" })}
          draft={["alpha", "beta"]}
          onChange={vi.fn()}
        />,
      );
      expect(screen.getByRole("textbox")).toHaveValue("alpha, beta");
    });

    it("calls onChange with a string array split by comma", () => {
      const onChange = vi.fn();
      render(
        <ConfigField
          spec={makeSpec({ field_type: "list[string]" })}
          draft={[]}
          onChange={onChange}
        />,
      );
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: "x, y, z" },
      });
      expect(onChange).toHaveBeenCalledWith(["x", "y", "z"]);
    });
  });

  describe("uuid field type", () => {
    it("renders a text input (same as string)", () => {
      render(
        <ConfigField
          spec={makeSpec({ field_type: "uuid" })}
          draft={null}
          onChange={vi.fn()}
        />,
      );
      expect(screen.getByRole("textbox")).toBeInTheDocument();
    });
  });
});
