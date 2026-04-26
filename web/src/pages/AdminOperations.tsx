// ABOUTME: Phase 4 admin operations dashboard — all records, filters, sort, CSV, manual transition.
// ABOUTME: Days-in-status + overdue flag come from the server; UI just renders + lets admin act.
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ManualTransitionModal } from "../components/admin/ManualTransitionModal";
import { downloadOperationsCsv, listAdminOperations } from "../api/admin";
import type {
  AdminOperationsRow,
  AdminOperationsSortDirection,
  AdminOperationsSortField,
} from "../api/types";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "new_request", label: "New request" },
  { value: "appraiser_assigned", label: "Appraiser assigned" },
  { value: "appraisal_scheduled", label: "Appraisal scheduled" },
  { value: "appraisal_complete", label: "Appraisal complete" },
  { value: "offer_ready", label: "Offer ready" },
  { value: "approved_pending_esign", label: "Approved — pending eSign" },
  { value: "esigned_pending_publish", label: "eSigned — pending publish" },
  { value: "listed", label: "Listed" },
  { value: "sold", label: "Sold" },
  { value: "declined", label: "Declined" },
  { value: "withdrawn", label: "Withdrawn" },
];

const SORT_OPTIONS: { value: AdminOperationsSortField; label: string }[] = [
  { value: "updated_at", label: "Last updated" },
  { value: "submitted_at", label: "Submitted" },
  { value: "days_in_status", label: "Days in status" },
  { value: "customer_name", label: "Customer" },
  { value: "status", label: "Status" },
];

export function AdminOperationsPage() {
  const [status, setStatus] = useState<string>("");
  const [overdueOnly, setOverdueOnly] = useState<boolean>(false);
  const [sort, setSort] = useState<AdminOperationsSortField>("updated_at");
  const [direction, setDirection] = useState<AdminOperationsSortDirection>("desc");
  const [page, setPage] = useState<number>(1);
  const perPage = 50;
  const [transitionTarget, setTransitionTarget] =
    useState<AdminOperationsRow | null>(null);

  const filters = useMemo(
    () => ({
      status: status || undefined,
      overdue_only: overdueOnly,
      sort,
      direction,
      page,
      per_page: perPage,
    }),
    [status, overdueOnly, sort, direction, page],
  );

  const query = useQuery({
    queryKey: ["admin-operations", filters],
    queryFn: () => listAdminOperations(filters),
    refetchInterval: 120_000, // 2-minute auto-refresh per spec.
  });

  const onCsvClick = async () => {
    try {
      await downloadOperationsCsv({
        status: status || undefined,
        overdue_only: overdueOnly,
        sort,
        direction,
      });
    } catch (err) {
      // Surface as a transient toast — the existing alert area is enough.
      console.error(err);
      alert((err as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Operations</h1>
          <p className="mt-1 text-sm text-gray-600">
            Every active equipment record across the platform. Auto-refreshes
            every 2 minutes.
          </p>
        </div>
        <Button variant="secondary" onClick={onCsvClick}>
          Export CSV
        </Button>
      </div>

      <Card>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <label className="text-sm">
            <span className="block font-medium text-gray-700">Status</span>
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm">
            <span className="block font-medium text-gray-700">Sort by</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as AdminOperationsSortField)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm">
            <span className="block font-medium text-gray-700">Direction</span>
            <select
              value={direction}
              onChange={(e) =>
                setDirection(e.target.value as AdminOperationsSortDirection)
              }
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            >
              <option value="desc">Newest first</option>
              <option value="asc">Oldest first</option>
            </select>
          </label>

          <label className="flex items-end gap-2 text-sm">
            <input
              type="checkbox"
              checked={overdueOnly}
              onChange={(e) => {
                setOverdueOnly(e.target.checked);
                setPage(1);
              }}
            />
            <span className="font-medium text-gray-700">
              Overdue only (≥ 7 days in current status)
            </span>
          </label>
        </div>
      </Card>

      {query.isLoading && <Spinner />}
      {query.isError && (
        <Alert tone="error" title="Could not load the operations dashboard">
          {(query.error as Error).message}
        </Alert>
      )}

      {query.data && (
        <Card>
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-600">
              {query.data.total} record{query.data.total === 1 ? "" : "s"} matching
              filters · page {query.data.page}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={query.data.rows.length < perPage}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                <tr>
                  <th scope="col" className="px-3 py-2">Reference</th>
                  <th scope="col" className="px-3 py-2">Customer</th>
                  <th scope="col" className="px-3 py-2">Equipment</th>
                  <th scope="col" className="px-3 py-2">Status</th>
                  <th scope="col" className="px-3 py-2">Days</th>
                  <th scope="col" className="px-3 py-2">Sales rep</th>
                  <th scope="col" className="px-3 py-2">Appraiser</th>
                  <th scope="col" className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {query.data.rows.map((r) => (
                  <tr
                    key={r.id}
                    className={r.is_overdue ? "bg-red-50" : ""}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">
                      {r.reference_number ?? r.id.slice(0, 8)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900">
                        {r.business_name ?? r.customer_name}
                      </div>
                      {r.business_name && (
                        <div className="text-xs text-gray-500">{r.customer_name}</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {[r.make, r.model].filter(Boolean).join(" ") || "—"}
                      {r.year ? ` (${r.year})` : ""}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-3 py-2">
                      <span className={r.is_overdue ? "font-semibold text-red-700" : ""}>
                        {r.days_in_status}d
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {r.assigned_sales_rep_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {r.assigned_appraiser_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setTransitionTarget(r)}
                      >
                        Transition
                      </Button>
                    </td>
                  </tr>
                ))}
                {query.data.rows.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-sm text-gray-500">
                      No records match these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {transitionTarget && (
        <ManualTransitionModal
          row={transitionTarget}
          onClose={() => setTransitionTarget(null)}
        />
      )}
    </div>
  );
}
