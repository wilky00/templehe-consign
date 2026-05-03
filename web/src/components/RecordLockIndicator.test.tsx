// ABOUTME: Unit tests for RecordLockIndicator — all LockState variants and override button.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RecordLockIndicator } from "./RecordLockIndicator";
import type { LockState } from "../hooks/useRecordLock";

const noop = vi.fn();

describe("RecordLockIndicator", () => {
  it("shows 'Acquiring' for idle state", () => {
    const state: LockState = { status: "idle" };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.getByText(/Acquiring edit lock/i)).toBeInTheDocument();
  });

  it("shows 'Acquiring' for acquiring state", () => {
    const state: LockState = { status: "acquiring" };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.getByText(/Acquiring edit lock/i)).toBeInTheDocument();
  });

  it("shows 'You are editing' for held state", () => {
    const state: LockState = {
      status: "held",
      info: {
        record_id: "rec-1",
        record_type: "equipment",
        locked_by: "00000000-0000-0000-0000-000000000001",
        locked_at: "2026-05-01T12:00:00Z",
        expires_at: "2026-05-01T12:30:00Z",
      },
    };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.getByRole("status")).toHaveTextContent("You are editing this record.");
  });

  it("shows warning for expired state", () => {
    const state: LockState = { status: "expired" };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/editing session timed out/i)).toBeInTheDocument();
  });

  it("shows conflict warning with expiry for conflict state", () => {
    const state: LockState = {
      status: "conflict",
      conflict: {
        detail: "Record locked",
        locked_by: "user-2",
        locked_at: "2026-05-01T12:00:00Z",
        expires_at: "2026-05-01T12:05:00Z",
      },
    };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Locked by another user/i)).toBeInTheDocument();
  });

  it("does not show override button when canOverride is false", () => {
    const state: LockState = {
      status: "conflict",
      conflict: { detail: "Locked", locked_by: "x", locked_at: "z", expires_at: "z" },
    };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.queryByRole("button", { name: /break lock/i })).not.toBeInTheDocument();
  });

  it("shows override button when canOverride is true", () => {
    const state: LockState = {
      status: "conflict",
      conflict: { detail: "Locked", locked_by: "x", locked_at: "z", expires_at: "z" },
    };
    render(<RecordLockIndicator state={state} canOverride={true} onOverride={noop} />);
    expect(screen.getByRole("button", { name: /break lock/i })).toBeInTheDocument();
  });

  it("calls onOverride when override button is clicked", async () => {
    const onOverride = vi.fn();
    const state: LockState = {
      status: "conflict",
      conflict: { detail: "Locked", locked_by: "x", locked_at: "z", expires_at: "z" },
    };
    render(<RecordLockIndicator state={state} canOverride={true} onOverride={onOverride} />);
    await userEvent.click(screen.getByRole("button", { name: /break lock/i }));
    expect(onOverride).toHaveBeenCalledOnce();
  });

  it("shows error alert for error state", () => {
    const state: LockState = { status: "error", detail: "Network failure" };
    render(<RecordLockIndicator state={state} canOverride={false} onOverride={noop} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Network failure")).toBeInTheDocument();
  });
});
