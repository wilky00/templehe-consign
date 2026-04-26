// ABOUTME: Phase 4 Sprint 3 — type-driven input renderer for one AppConfig key.
// ABOUTME: Supports string / int / uuid / list[string]; comma-separated input for lists.
import type { AppConfigItem } from "../../api/types";

interface Props {
  spec: AppConfigItem;
  draft: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}

export function ConfigField({ spec, draft, onChange, disabled }: Props) {
  const inputId = `cfg-${spec.name}`;
  switch (spec.field_type) {
    case "int":
      return (
        <input
          id={inputId}
          type="number"
          value={
            draft === null || draft === undefined || draft === ""
              ? ""
              : Number(draft)
          }
          onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === "" ? null : Number(raw));
          }}
          disabled={disabled}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      );
    case "list[string]":
      return (
        <textarea
          id={inputId}
          value={
            Array.isArray(draft) ? (draft as string[]).join(", ") : ""
          }
          onChange={(e) => {
            const parts = e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            onChange(parts);
          }}
          rows={Array.isArray(draft) && (draft as string[]).length > 6 ? 4 : 2}
          disabled={disabled}
          placeholder="comma-separated list"
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      );
    case "uuid":
    case "string":
    default:
      return (
        <input
          id={inputId}
          type="text"
          value={(draft as string | null | undefined) ?? ""}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : e.target.value)
          }
          disabled={disabled}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      );
  }
}
