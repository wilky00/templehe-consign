// ABOUTME: Sales rep dashboard — records grouped by customer with cascade action and scope toggle.
// ABOUTME: Default scope is "mine" for every role; managers/admins can flip to "all".
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { StatusBadge } from "../components/ui/StatusBadge";
import { PhoneLink } from "../components/PhoneLink";
import { CascadeAssignModal } from "../components/CascadeAssignModal";
import { getDashboard } from "../api/sales";
import { useMe } from "../hooks/useMe";
import type { CustomerGroup } from "../api/types";

const MANAGER_ROLES = new Set(["sales_manager", "admin"]);

export function SalesDashboardPage() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const isManager = me ? MANAGER_ROLES.has(me.role) : false;
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [cascadeTarget, setCascadeTarget] = useState<CustomerGroup | null>(null);

  const query = useQuery({
    queryKey: ["sales-dashboard", scope],
    queryFn: () => getDashboard({ scope }),
  });

  const onCascadeApplied = () => {
    qc.invalidateQueries({ queryKey: ["sales-dashboard"] });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Sales dashboard</h1>
          <p className="mt-1 text-sm text-gray-600">
            {scope === "mine"
              ? "Records assigned to you, grouped by customer."
              : "All records across the team, grouped by customer."}
          </p>
        </div>
        {isManager && (
          <div className="flex items-center gap-1 rounded-md border border-gray-200 bg-white p-1 text-sm">
            <button
              type="button"
              onClick={() => setScope("mine")}
              className={
                scope === "mine"
                  ? "rounded px-3 py-1.5 bg-gray-100 font-medium text-gray-900"
                  : "rounded px-3 py-1.5 text-gray-600 hover:text-gray-900"
              }
              aria-pressed={scope === "mine"}
            >
              Mine
            </button>
            <button
              type="button"
              onClick={() => setScope("all")}
              className={
                scope === "all"
                  ? "rounded px-3 py-1.5 bg-gray-100 font-medium text-gray-900"
                  : "rounded px-3 py-1.5 text-gray-600 hover:text-gray-900"
              }
              aria-pressed={scope === "all"}
            >
              All records
            </button>
          </div>
        )}
      </div>

      {query.isLoading && <Spinner />}
      {query.isError && (
        <Alert tone="error" title="Could not load the dashboard">
          {(query.error as Error).message}
        </Alert>
      )}

      {query.data && query.data.customers.length === 0 && (
        <Card>
          <p className="text-sm text-gray-600">
            No records match the current scope.
            {scope === "mine" && isManager
              ? " Flip to 'All records' to see the rest of the team's work."
              : ""}
          </p>
        </Card>
      )}

      {query.data?.customers.map((group) => (
        <Card key={group.customer_id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-gray-900">
                {group.business_name ?? group.submitter_name}
              </h2>
              <p className="text-sm text-gray-600">
                {group.submitter_name}
                {group.state ? ` — ${group.state}` : ""}
              </p>
              <p className="text-sm text-gray-600">
                Cell: <PhoneLink number={group.cell_phone} />{" "}
                {group.business_phone && (
                  <>
                    · Office:{" "}
                    <PhoneLink
                      number={group.business_phone}
                      ext={group.business_phone_ext}
                    />
                  </>
                )}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {group.total_items} item(s){" "}
                {group.first_submission_at &&
                  `· first submitted ${new Date(group.first_submission_at).toLocaleDateString()}`}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setCascadeTarget(group)}
            >
              Cascade assign
            </Button>
          </div>

          <ul className="mt-4 divide-y divide-gray-100">
            {group.records.map((rec) => (
              <li
                key={rec.id}
                className="flex items-center justify-between gap-3 py-2 text-sm"
              >
                <div className="flex-1">
                  <Link
                    to={`/sales/equipment/${rec.id}`}
                    className="font-medium text-gray-900 underline decoration-dotted underline-offset-2"
                  >
                    {rec.reference_number ?? rec.id.slice(0, 8)}
                  </Link>
                  <span className="ml-2 text-gray-600">
                    {[rec.make, rec.model].filter(Boolean).join(" ") || "—"}
                    {rec.year ? ` (${rec.year})` : ""}
                  </span>
                  {rec.serial_number && (
                    <span className="ml-2 text-xs text-gray-500">
                      SN {rec.serial_number}
                    </span>
                  )}
                </div>
                <StatusBadge status={rec.status} />
              </li>
            ))}
          </ul>
        </Card>
      ))}

      {cascadeTarget && (
        <CascadeAssignModal
          open
          customer={cascadeTarget}
          onClose={() => setCascadeTarget(null)}
          onApplied={() => {
            onCascadeApplied();
            setCascadeTarget(null);
          }}
        />
      )}
    </div>
  );
}
