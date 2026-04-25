// ABOUTME: Modal for bulk-assigning a sales rep + appraiser across a customer's new_request rows.
// ABOUTME: Kept unadorned — keyboard-accessible close, no backdrop portal trickery; Phase 6 polish can iterate.
import { useState } from "react";
import { Button } from "./ui/Button";
import { TextInput } from "./ui/Input";
import { Alert } from "./ui/Alert";
import { cascadeAssignments } from "../api/sales";
import { ApiError } from "../api/client";
import type { CascadeResult, CustomerGroup } from "../api/types";

interface Props {
  customer: CustomerGroup;
  open: boolean;
  onClose: () => void;
  onApplied: (result: CascadeResult) => void;
}

export function CascadeAssignModal({ customer, open, onClose, onApplied }: Props) {
  const [salesRepId, setSalesRepId] = useState("");
  const [appraiserId, setAppraiserId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CascadeResult | null>(null);

  if (!open) return null;

  const onApply = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const patch = {
        ...(salesRepId ? { assigned_sales_rep_id: salesRepId } : {}),
        ...(appraiserId ? { assigned_appraiser_id: appraiserId } : {}),
      };
      const res = await cascadeAssignments(customer.customer_id, patch);
      setResult(res);
      onApplied(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : (err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cascade-title"
      className="fixed inset-0 z-40 flex items-center justify-center bg-gray-900/40 p-4"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h2 id="cascade-title" className="text-lg font-semibold text-gray-900">
          Cascade assignments
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Apply to every <strong>new request</strong> for{" "}
          <strong>{customer.business_name ?? customer.submitter_name}</strong>.
          Records past new request are skipped.
        </p>

        <div className="mt-4 space-y-3">
          <TextInput
            id="cascade-sales-rep"
            label="Sales Rep user ID"
            value={salesRepId}
            onChange={(e) => setSalesRepId(e.target.value)}
            hint="Leave blank to skip reassigning the sales rep."
          />
          <TextInput
            id="cascade-appraiser"
            label="Appraiser user ID"
            value={appraiserId}
            onChange={(e) => setAppraiserId(e.target.value)}
            hint="Leave blank to skip reassigning the appraiser. Admin panel in Phase 4 will add dropdowns."
          />
          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              Apply these assignments to all {customer.total_items}{" "}
              equipment items for {customer.business_name ?? customer.submitter_name}
            </span>
          </label>
        </div>

        {error && (
          <div className="mt-3">
            <Alert tone="error" title="Cascade failed">
              {error}
            </Alert>
          </div>
        )}
        {result && (
          <div className="mt-3">
            <Alert tone="success" title="Cascade applied">
              Updated {result.updated_record_ids.length}; skipped{" "}
              {result.skipped_record_ids.length}
              {result.skipped_reason ? ` — ${result.skipped_reason}` : "."}
            </Alert>
          </div>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button
            onClick={onApply}
            disabled={
              submitting ||
              !confirmed ||
              (!salesRepId && !appraiserId)
            }
          >
            {submitting ? "Applying…" : "Apply"}
          </Button>
        </div>
      </div>
    </div>
  );
}
