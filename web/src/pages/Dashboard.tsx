// ABOUTME: Customer dashboard — list of submissions with status badges + a CTA to submit new equipment.
// ABOUTME: Clicking a row opens /portal/equipment/{id}. Empty state links to the intake form.
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listEquipment } from "../api/equipment";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { StatusBadge } from "../components/ui/StatusBadge";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function DashboardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["equipment"],
    queryFn: listEquipment,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Your submissions</h1>
          <p className="mt-1 text-sm text-gray-600">
            Track every piece of equipment you've submitted and its current status.
          </p>
        </div>
        <Link to="/portal/submit">
          <Button>Submit new equipment</Button>
        </Link>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-10">
          <Spinner />
        </div>
      )}

      {isError && (
        <Alert tone="error" title="Could not load your submissions">
          {(error as Error).message}
        </Alert>
      )}

      {data && data.length === 0 && (
        <Card>
          <p className="text-gray-700">
            You haven't submitted any equipment yet.
          </p>
          <p className="mt-2 text-sm text-gray-500">
            Use <Link to="/portal/submit" className="underline">Submit new equipment</Link>{" "}
            to start your first submission. A Temple Heavy Equipment sales
            representative will follow up within one business day.
          </p>
        </Card>
      )}

      {data && data.length > 0 && (
        <ul className="space-y-3">
          {data.map((rec) => {
            const title =
              [rec.year, rec.make, rec.model].filter(Boolean).join(" ") ||
              "Equipment submission";
            return (
              <li key={rec.id}>
                <Link
                  to={`/portal/equipment/${rec.id}`}
                  className="block rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:border-gray-300 hover:shadow"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-mono text-gray-500">
                        {rec.reference_number}
                      </p>
                      <h2 className="mt-1 text-base font-medium text-gray-900">
                        {title}
                      </h2>
                      {rec.location_text && (
                        <p className="mt-1 text-sm text-gray-600">
                          {rec.location_text}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <StatusBadge status={rec.status} />
                      <span className="text-xs text-gray-500">
                        Submitted {formatDate(rec.submitted_at)}
                      </span>
                    </div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
