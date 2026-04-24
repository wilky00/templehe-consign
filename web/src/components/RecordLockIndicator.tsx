// ABOUTME: Visual banner for record lock status on the sales detail page.
// ABOUTME: Shows "You are editing" vs "Locked by another user" — the latter exposes override for managers.
import { Alert } from "./ui/Alert";
import { Button } from "./ui/Button";
import type { LockState } from "../hooks/useRecordLock";

interface Props {
  state: LockState;
  canOverride: boolean;
  onOverride: () => void;
}

export function RecordLockIndicator({ state, canOverride, onOverride }: Props) {
  if (state.status === "idle" || state.status === "acquiring") {
    return (
      <div className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
        Acquiring edit lock…
      </div>
    );
  }
  if (state.status === "held") {
    return (
      <div
        className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800"
        role="status"
      >
        You are editing this record.
      </div>
    );
  }
  if (state.status === "expired") {
    return (
      <Alert tone="warning" title="Your editing session timed out">
        Your changes may not have been saved. Refresh the page to resume
        editing.
      </Alert>
    );
  }
  if (state.status === "conflict") {
    return (
      <Alert tone="warning" title="Locked by another user">
        <p>
          Someone else is currently editing this record. Their session expires{" "}
          at {state.conflict.expires_at || "—"}.
        </p>
        {canOverride && (
          <div className="mt-3">
            <Button variant="danger" size="sm" onClick={onOverride}>
              Break lock (manager override)
            </Button>
          </div>
        )}
      </Alert>
    );
  }
  return (
    <Alert tone="error" title="Lock error">
      {state.detail}
    </Alert>
  );
}
