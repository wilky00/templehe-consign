// ABOUTME: Phase 4 Sprint 7 — admin health dashboard. Reads /admin/health snapshot.
// ABOUTME: Manual refresh forces a probe; otherwise the 30s poller keeps it fresh.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { getAdminHealth } from "../api/admin";
import type { HealthStateRow, HealthStatus } from "../api/types";

const STATUS_LABEL: Record<HealthStatus, string> = {
  green: "Healthy",
  yellow: "Degraded",
  red: "Down",
  unknown: "Unconfigured",
  stubbed: "Stubbed",
};

const STATUS_CLASSES: Record<HealthStatus, string> = {
  green: "border-emerald-300 bg-emerald-50 text-emerald-900",
  yellow: "border-amber-300 bg-amber-50 text-amber-900",
  red: "border-red-300 bg-red-50 text-red-900",
  unknown: "border-gray-300 bg-gray-50 text-gray-700",
  stubbed: "border-blue-300 bg-blue-50 text-blue-900",
};

const SERVICE_LABEL: Record<string, string> = {
  database: "Database",
  r2: "Object storage (R2)",
  slack: "Slack",
  twilio: "Twilio",
  sendgrid: "SendGrid",
  google_maps: "Google Maps",
  esign: "eSign provider",
  valuation: "Valuation API",
};

export function AdminHealthPage() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-health"],
    queryFn: () => getAdminHealth(false),
    refetchInterval: 30_000,
  });

  const refresh = async () => {
    await getAdminHealth(true);
    qc.invalidateQueries({ queryKey: ["admin-health"] });
  };

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load health snapshot">
        {(query.error as Error).message}
      </Alert>
    );
  }

  const data = query.data!;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Health</h1>
          <p className="mt-1 text-sm text-gray-600">
            Snapshot of platform + integration status. The background poller
            refreshes every 30 seconds; admins receive alerts when a service
            flips red (rate-limited, max one per service per 15 min).
          </p>
        </div>
        <div className="flex gap-2">
          <span className="self-center text-xs text-gray-500">
            Snapshot at {new Date(data.snapshot_at).toLocaleTimeString()}
          </span>
          <Button type="button" variant="secondary" onClick={refresh}>
            Refresh now
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.services.map((svc) => (
          <ServiceCard key={svc.service_name} row={svc} />
        ))}
      </div>
    </div>
  );
}

function ServiceCard({ row }: { row: HealthStateRow }) {
  const status = row.status;
  const classes = STATUS_CLASSES[status];
  return (
    <Card className={`border ${classes}`}>
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-base font-semibold">
          {SERVICE_LABEL[row.service_name] ?? row.service_name}
        </h2>
        <span className="rounded-md bg-white/70 px-2 py-1 text-xs font-medium uppercase">
          {STATUS_LABEL[status]}
        </span>
      </div>
      <dl className="mt-3 space-y-1 text-xs">
        <div className="flex justify-between">
          <dt className="text-gray-600">Last check</dt>
          <dd>
            {row.last_checked_at
              ? new Date(row.last_checked_at).toLocaleTimeString()
              : "—"}
          </dd>
        </div>
        {typeof row.latency_ms === "number" && (
          <div className="flex justify-between">
            <dt className="text-gray-600">Latency</dt>
            <dd>{row.latency_ms} ms</dd>
          </div>
        )}
        {row.last_alerted_at && (
          <div className="flex justify-between">
            <dt className="text-gray-600">Last alert</dt>
            <dd>{new Date(row.last_alerted_at).toLocaleTimeString()}</dd>
          </div>
        )}
      </dl>
      {row.error_detail && Boolean(row.error_detail.detail) ? (
        <p className="mt-2 break-words text-xs">
          {String(row.error_detail.detail)}
        </p>
      ) : null}
    </Card>
  );
}
