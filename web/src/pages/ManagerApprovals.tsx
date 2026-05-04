// ABOUTME: Manager approval queue — lists submitted appraisals awaiting review, oldest-first.
// ABOUTME: Shows score, score band, red flag badges; clicking a row navigates to the detail view.
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { approvePriceChange, getApprovalQueue, getPriceChangeQueue } from "../api/approvals";
import type { ApprovalQueueItem, PriceChangeQueueItem } from "../api/approvals";
import { ApiError } from "../api/client";

function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function ScoreBadge({ score, band }: { score: number | null; band: string | null }) {
  // Pydantic serializes Decimal as a JSON string; coerce to number defensively.
  const n = score == null ? null : Number(score);
  if (n == null || Number.isNaN(n)) return <span className="text-gray-400">—</span>;
  const color =
    n >= 4.5
      ? "bg-green-100 text-green-800"
      : n >= 3.75
        ? "bg-blue-100 text-blue-800"
        : n >= 3.0
          ? "bg-yellow-100 text-yellow-800"
          : "bg-red-100 text-red-800";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {n.toFixed(2)}
      {band ? ` · ${band}` : ""}
    </span>
  );
}

function FlagBadges({ item }: { item: ApprovalQueueItem }) {
  return (
    <span className="flex flex-wrap gap-1">
      {item.management_review_required && (
        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
          Review required
        </span>
      )}
      {item.hold_for_title_review && (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
          Title hold
        </span>
      )}
    </span>
  );
}

function AppraisalQueueTable({ items }: { items: ApprovalQueueItem[] }) {
  const navigate = useNavigate();
  if (items.length === 0) {
    return <p className="text-sm text-gray-500">No appraisals awaiting review.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead>
          <tr className="text-left text-xs font-medium uppercase tracking-wider text-gray-500">
            <th className="py-3 pr-4">Reference</th>
            <th className="py-3 pr-4">Equipment</th>
            <th className="py-3 pr-4">Score</th>
            <th className="py-3 pr-4">Marketability</th>
            <th className="py-3 pr-4">Appraiser</th>
            <th className="py-3 pr-4">Submitted</th>
            <th className="py-3">Flags</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {items.map((item) => (
            <tr
              key={item.submission_id}
              className="cursor-pointer hover:bg-gray-50"
              onClick={() => navigate(`/manager/approvals/${item.submission_id}`)}
              aria-label={`Review appraisal ${item.reference_number ?? item.submission_id}`}
            >
              <td className="py-3 pr-4 font-mono text-xs text-gray-700">
                {item.reference_number ?? "—"}
              </td>
              <td className="py-3 pr-4 text-gray-900">
                {[item.make, item.model, item.year].filter(Boolean).join(" ") || "—"}
              </td>
              <td className="py-3 pr-4">
                <ScoreBadge score={item.overall_score} band={item.score_band} />
              </td>
              <td className="py-3 pr-4 text-gray-700">{item.marketability_rating ?? "—"}</td>
              <td className="py-3 pr-4 text-gray-700">{item.appraiser_name ?? "—"}</td>
              <td className="py-3 pr-4 text-gray-500">{formatDate(item.submitted_at)}</td>
              <td className="py-3">
                <FlagBadges item={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PriceChangeRow({ item }: { item: PriceChangeQueueItem }) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => approvePriceChange(item.change_request_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["manager-price-change-queue"] });
    },
  });

  const changePct =
    item.approved_price && item.proposed_price
      ? (
          ((item.proposed_price - item.approved_price) / item.approved_price) *
          100
        ).toFixed(1)
      : null;

  return (
    <tr key={item.change_request_id}>
      <td className="py-3 pr-4 font-mono text-xs text-gray-700">
        {item.reference_number ?? "—"}
      </td>
      <td className="py-3 pr-4 text-gray-900">{item.make_model ?? "—"}</td>
      <td className="py-3 pr-4 text-gray-700">
        {item.approved_price != null ? `$${item.approved_price.toLocaleString()}` : "—"}
      </td>
      <td className="py-3 pr-4 text-gray-700">
        {item.proposed_price != null ? `$${item.proposed_price.toLocaleString()}` : "—"}
      </td>
      <td className="py-3 pr-4">
        {changePct !== null ? (
          <span
            className={
              parseFloat(changePct) < 0
                ? "text-red-600 font-medium"
                : "text-green-600 font-medium"
            }
          >
            {parseFloat(changePct) > 0 ? "+" : ""}
            {changePct}%
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="py-3 pr-4 text-gray-500">{item.customer_email ?? "—"}</td>
      <td className="py-3 text-gray-500">{formatDate(item.submitted_at)}</td>
      <td className="py-3">
        {mutation.isError && (
          <p className="mb-1 text-xs text-red-600" role="alert">
            {apiErrorMessage(mutation.error)}
          </p>
        )}
        <Button
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || mutation.isSuccess}
          aria-label={`Re-approve price change for ${item.reference_number ?? item.change_request_id}`}
        >
          {mutation.isPending ? "Approving…" : mutation.isSuccess ? "Approved" : "Re-approve"}
        </Button>
      </td>
    </tr>
  );
}

function PriceChangeTable({ items }: { items: PriceChangeQueueItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-500">No price changes awaiting re-approval.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead>
          <tr className="text-left text-xs font-medium uppercase tracking-wider text-gray-500">
            <th className="py-3 pr-4">Reference</th>
            <th className="py-3 pr-4">Equipment</th>
            <th className="py-3 pr-4">Approved price</th>
            <th className="py-3 pr-4">Proposed price</th>
            <th className="py-3 pr-4">Change</th>
            <th className="py-3 pr-4">Customer</th>
            <th className="py-3 pr-4">Submitted</th>
            <th className="py-3">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {items.map((item) => (
            <PriceChangeRow key={item.change_request_id} item={item} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ManagerApprovalsPage() {
  const queueQuery = useQuery({
    queryKey: ["manager-approval-queue"],
    queryFn: getApprovalQueue,
  });

  const priceQuery = useQuery({
    queryKey: ["manager-price-change-queue"],
    queryFn: getPriceChangeQueue,
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Manager approval queue</h1>
        <p className="mt-1 text-sm text-gray-600">
          Appraisals awaiting your review, oldest first.
        </p>
      </div>

      <Card>
        <h2 className="mb-4 text-base font-semibold text-gray-900">Submitted appraisals</h2>
        {queueQuery.isLoading && <Spinner />}
        {queueQuery.isError && (
          <Alert tone="error" title="Could not load the approval queue">
            {(queueQuery.error as Error).message}
          </Alert>
        )}
        {queueQuery.data && (
          <AppraisalQueueTable items={queueQuery.data.items} />
        )}
      </Card>

      <Card>
        <h2 className="mb-4 text-base font-semibold text-gray-900">Price change re-approvals</h2>
        {priceQuery.isLoading && <Spinner />}
        {priceQuery.isError && (
          <Alert tone="error" title="Could not load price change requests">
            {(priceQuery.error as Error).message}
          </Alert>
        )}
        {priceQuery.data && <PriceChangeTable items={priceQuery.data.items} />}
      </Card>
    </div>
  );
}
