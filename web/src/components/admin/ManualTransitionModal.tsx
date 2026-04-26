// ABOUTME: Phase 4 admin modal — pick a destination status, give a reason, choose to notify.
// ABOUTME: Forbidden transitions and unknown statuses are guarded server-side and surfaced inline.
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { manualTransition } from "../../api/admin";
import { ApiError } from "../../api/client";
import type { AdminOperationsRow } from "../../api/types";

// Mirror of api/services/equipment_status_machine.Status. Kept in sync
// manually; Sprint 3 will swap this for a fetch from the AppConfig-backed
// metadata endpoint so admin doesn't recompile when statuses change.
const STATUS_VALUES: { value: string; label: string }[] = [
  { value: "new_request", label: "A new request has been submitted" },
  { value: "appraiser_assigned", label: "An appraiser has been assigned" },
  { value: "appraisal_scheduled", label: "An appraisal has been scheduled" },
  { value: "appraisal_complete", label: "Appraisal complete" },
  { value: "offer_ready", label: "Offer ready" },
  { value: "approved_pending_esign", label: "Manager approved — pending eSign" },
  { value: "esigned_pending_publish", label: "Customer eSigned — pending publish" },
  { value: "listed", label: "Listed publicly" },
  { value: "sold", label: "Sold" },
  { value: "declined", label: "Declined by manager" },
  { value: "withdrawn", label: "Withdrawn by customer" },
];

interface Props {
  row: AdminOperationsRow;
  onClose: () => void;
}

export function ManualTransitionModal({ row, onClose }: Props) {
  const qc = useQueryClient();
  const [toStatus, setToStatus] = useState<string>("");
  const [reason, setReason] = useState<string>("");
  const [sendNotifications, setSendNotifications] = useState<boolean>(true);

  const mutation = useMutation({
    mutationFn: () =>
      manualTransition(row.id, {
        to_status: toStatus,
        reason: reason.trim(),
        send_notifications: sendNotifications,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-operations"] });
      onClose();
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!toStatus || !reason.trim()) return;
    mutation.mutate();
  };

  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-transition-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 id="manual-transition-title" className="text-lg font-semibold text-gray-900">
          Manually transition record
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          {row.reference_number ?? row.id.slice(0, 8)} —{" "}
          <span className="font-medium">{row.status_display}</span>
        </p>

        <form onSubmit={onSubmit} className="mt-4 space-y-4">
          <div>
            <label
              htmlFor="manual-transition-to-status"
              className="block text-sm font-medium text-gray-700"
            >
              Destination status
            </label>
            <select
              id="manual-transition-to-status"
              required
              value={toStatus}
              onChange={(e) => setToStatus(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="" disabled>
                Pick a status…
              </option>
              {STATUS_VALUES.filter((s) => s.value !== row.status).map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="manual-transition-reason"
              className="block text-sm font-medium text-gray-700"
            >
              Reason (recorded in audit log)
            </label>
            <textarea
              id="manual-transition-reason"
              required
              minLength={1}
              maxLength={2000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              rows={3}
              placeholder="Why is this manual transition necessary?"
            />
          </div>

          <div className="flex items-start gap-2">
            <input
              id="manual-transition-notify"
              type="checkbox"
              checked={sendNotifications}
              onChange={(e) => setSendNotifications(e.target.checked)}
              className="mt-1"
            />
            <label
              htmlFor="manual-transition-notify"
              className="text-sm text-gray-700"
            >
              Send notifications (customer email + sales-rep alert)
              <p className="text-xs text-gray-500">
                Uncheck for back-fill or data correction work where the
                customer was already notified another way.
              </p>
            </label>
          </div>

          {errorDetail && (
            <Alert tone="error" title="Could not transition the record">
              {errorDetail}
            </Alert>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={mutation.isPending || !toStatus || !reason.trim()}
            >
              {mutation.isPending ? "Saving…" : "Apply transition"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
