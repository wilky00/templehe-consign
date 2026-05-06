// ABOUTME: Admin reporting page — Sales by Period/Type/State, Portal Traffic, and CSV Export Center.
// ABOUTME: Phase 8 Sprint 4 — Recharts charts, filter controls, and CSV download wired to backend.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AdminReportTab } from "../api/types";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import {
  getSalesByPeriod,
  getSalesByType,
  getSalesByState,
  getPortalTraffic,
  downloadReportCsv,
  type AdminReportType,
  type PeriodType,
  type UserSegment,
} from "../api/reports";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CHART_PRIMARY = "#111827";
const CHART_SECONDARY = "#059669";
const PIE_COLORS = ["#111827", "#374151", "#6b7280", "#9ca3af", "#d1d5db", "#e5e7eb"];

function formatUsd(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}


// ---------------------------------------------------------------------------
// Shared filter primitives
// ---------------------------------------------------------------------------

interface DateRangeFilterProps {
  startDate: string;
  endDate: string;
  onStartChange: (v: string) => void;
  onEndChange: (v: string) => void;
}

function DateRangeFilter({
  startDate,
  endDate,
  onStartChange,
  onEndChange,
}: DateRangeFilterProps) {
  return (
    <>
      <label className="text-sm">
        <span className="block font-medium text-gray-700">From</span>
        <input
          type="date"
          value={startDate}
          onChange={(e) => onStartChange(e.target.value)}
          className="mt-1 block rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </label>
      <label className="text-sm">
        <span className="block font-medium text-gray-700">To</span>
        <input
          type="date"
          value={endDate}
          onChange={(e) => onEndChange(e.target.value)}
          className="mt-1 block rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </label>
    </>
  );
}

// ---------------------------------------------------------------------------
// Sales by Period tab
// ---------------------------------------------------------------------------

function SalesByPeriodTab() {
  const [periodType, setPeriodType] = useState<PeriodType>("month");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["reports-period", periodType, startDate, endDate],
    queryFn: () =>
      getSalesByPeriod({
        period_type: periodType,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      }),
  });

  const onExport = async () => {
    setDownloading(true);
    setExportError(null);
    try {
      await downloadReportCsv("sales-by-period", {
        period_type: periodType,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      });
    } catch (err) {
      setExportError((err as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  const rows = query.data?.rows ?? [];

  return (
    <div className="space-y-6">
      {/* Filters */}
      <Card>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <label className="text-sm">
            <span className="block font-medium text-gray-700">Period</span>
            <select
              value={periodType}
              onChange={(e) => setPeriodType(e.target.value as PeriodType)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            >
              <option value="month">Month</option>
              <option value="quarter">Quarter</option>
              <option value="year">Year</option>
            </select>
          </label>
          <DateRangeFilter
            startDate={startDate}
            endDate={endDate}
            onStartChange={setStartDate}
            onEndChange={setEndDate}
          />
          <div className="flex items-end">
            <Button
              variant="secondary"
              onClick={onExport}
              disabled={downloading || query.isLoading}
            >
              {downloading ? "Downloading…" : "Export CSV"}
            </Button>
          </div>
        </div>
        {exportError && (
          <p className="mt-2 text-sm text-red-700">{exportError}</p>
        )}
      </Card>

      {query.isLoading && <Spinner />}

      {query.isError && (
        <Alert tone="error" title="Could not load report">
          {(query.error as Error).message}
        </Alert>
      )}

      {rows.length > 0 && (
        <>
          {/* Summary table */}
          <Card>
            <h2 className="mb-3 text-base font-semibold text-gray-900">Summary</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                  <tr>
                    <th scope="col" className="px-3 py-2">Period</th>
                    <th scope="col" className="px-3 py-2 text-right">Records</th>
                    <th scope="col" className="px-3 py-2 text-right">Direct</th>
                    <th scope="col" className="px-3 py-2 text-right">Consignment</th>
                    <th scope="col" className="px-3 py-2 text-right">Total Offer</th>
                    <th scope="col" className="px-3 py-2 text-right">Total Consign.</th>
                    <th scope="col" className="px-3 py-2 text-right">Avg Days</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((row) => (
                    <tr key={row.period_label} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium text-gray-900">
                        {row.period_label}
                      </td>
                      <td className="px-3 py-2 text-right">{row.record_count}</td>
                      <td className="px-3 py-2 text-right">{row.direct_purchase_count}</td>
                      <td className="px-3 py-2 text-right">{row.consignment_count}</td>
                      <td className="px-3 py-2 text-right">{formatUsd(row.total_approved_offer)}</td>
                      <td className="px-3 py-2 text-right">{formatUsd(row.total_consignment_price)}</td>
                      <td className="px-3 py-2 text-right">
                        {row.avg_days_to_publish != null
                          ? row.avg_days_to_publish.toFixed(1)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Line chart — published count per period */}
          <Card>
            <h2 className="mb-3 text-base font-semibold text-gray-900">
              Records per {periodType}
            </h2>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={rows} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="period_label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="record_count"
                  name="Records"
                  stroke={CHART_PRIMARY}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* Bar chart — consignment vs direct */}
          <Card>
            <h2 className="mb-3 text-base font-semibold text-gray-900">
              Acquisition path per {periodType}
            </h2>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={rows} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="period_label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar dataKey="direct_purchase_count" name="Direct purchase" fill={CHART_PRIMARY} />
                <Bar dataKey="consignment_count" name="Consignment" fill={CHART_SECONDARY} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </>
      )}

      {!query.isLoading && !query.isError && rows.length === 0 && (
        <p className="text-sm text-gray-500">No approved records match the selected filters.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sales by Type / Location tab
// ---------------------------------------------------------------------------

function SalesByTypeLocationTab() {
  const [subView, setSubView] = useState<"type" | "state">("type");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const typeQuery = useQuery({
    queryKey: ["reports-type", startDate, endDate],
    queryFn: () =>
      getSalesByType({
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      }),
  });

  const stateQuery = useQuery({
    queryKey: ["reports-state", startDate, endDate],
    queryFn: () =>
      getSalesByState({
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      }),
    enabled: subView === "state",
  });

  const onExport = async () => {
    const reportType: AdminReportType =
      subView === "type" ? "sales-by-type" : "sales-by-state";
    setDownloading(true);
    setExportError(null);
    try {
      await downloadReportCsv(reportType, {
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      });
    } catch (err) {
      setExportError((err as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  const typeRows = typeQuery.data?.rows ?? [];
  const stateRows = stateQuery.data?.rows ?? [];
  const isLoading = subView === "type" ? typeQuery.isLoading : stateQuery.isLoading;
  const isError = subView === "type" ? typeQuery.isError : stateQuery.isError;
  const error = subView === "type" ? typeQuery.error : stateQuery.error;

  return (
    <div className="space-y-6">
      {/* Sub-view switcher */}
      <div
        role="tablist"
        aria-label="Sales sub-view"
        className="flex gap-1 rounded-md border border-gray-200 bg-gray-50 p-1 w-fit"
      >
        {(["type", "state"] as const).map((sv) => (
          <button
            key={sv}
            type="button"
            role="tab"
            aria-selected={subView === sv}
            onClick={() => setSubView(sv)}
            className={
              subView === sv
                ? "rounded px-4 py-1.5 text-sm font-medium bg-white shadow text-gray-900"
                : "rounded px-4 py-1.5 text-sm font-medium text-gray-500 hover:text-gray-900"
            }
          >
            {sv === "type" ? "By equipment type" : "By state"}
          </button>
        ))}
      </div>

      {/* Filters */}
      <Card>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <DateRangeFilter
            startDate={startDate}
            endDate={endDate}
            onStartChange={setStartDate}
            onEndChange={setEndDate}
          />
          <div className="flex items-end">
            <Button
              variant="secondary"
              onClick={onExport}
              disabled={downloading || isLoading}
            >
              {downloading ? "Downloading…" : "Export CSV"}
            </Button>
          </div>
        </div>
        {exportError && (
          <p className="mt-2 text-sm text-red-700">{exportError}</p>
        )}
      </Card>

      {isLoading && <Spinner />}

      {isError && (
        <Alert tone="error" title="Could not load report">
          {(error as Error).message}
        </Alert>
      )}

      {/* By equipment type */}
      {subView === "type" && typeRows.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Table */}
            <Card>
              <h2 className="mb-3 text-base font-semibold text-gray-900">By category</h2>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                    <tr>
                      <th scope="col" className="px-3 py-2">Category</th>
                      <th scope="col" className="px-3 py-2 text-right">Records</th>
                      <th scope="col" className="px-3 py-2 text-right">Approved</th>
                      <th scope="col" className="px-3 py-2 text-right">Avg Score</th>
                      <th scope="col" className="px-3 py-2 text-right">Avg Offer</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {typeRows.map((row) => (
                      <tr key={row.category_name} className="hover:bg-gray-50">
                        <td className="px-3 py-2 font-medium text-gray-900">
                          {row.category_name}
                        </td>
                        <td className="px-3 py-2 text-right">{row.record_count}</td>
                        <td className="px-3 py-2 text-right">{row.approved_count}</td>
                        <td className="px-3 py-2 text-right">
                          {row.avg_overall_score != null
                            ? row.avg_overall_score.toFixed(2)
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {row.avg_approved_offer != null
                            ? formatUsd(row.avg_approved_offer)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            {/* Pie chart */}
            <Card>
              <h2 className="mb-3 text-base font-semibold text-gray-900">
                Volume by category
              </h2>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={typeRows}
                    dataKey="record_count"
                    nameKey="category_name"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    innerRadius={40}
                  >
                    {typeRows.map((_, i) => (
                      <Cell
                        key={i}
                        fill={PIE_COLORS[i % PIE_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [value, name]}
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </Card>
          </div>
        </>
      )}

      {/* By state */}
      {subView === "state" && stateRows.length > 0 && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-gray-900">By state</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                <tr>
                  <th scope="col" className="px-3 py-2">State</th>
                  <th scope="col" className="px-3 py-2 text-right">Records</th>
                  <th scope="col" className="px-3 py-2 text-right">Approved</th>
                  <th scope="col" className="px-3 py-2 text-right">Avg Offer</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {stateRows.map((row) => (
                  <tr key={row.state} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium text-gray-900">{row.state}</td>
                    <td className="px-3 py-2 text-right">{row.record_count}</td>
                    <td className="px-3 py-2 text-right">{row.approved_count}</td>
                    <td className="px-3 py-2 text-right">
                      {row.avg_approved_offer != null
                        ? formatUsd(row.avg_approved_offer)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {!isLoading && !isError &&
        subView === "type" && typeRows.length === 0 && (
          <p className="text-sm text-gray-500">No category data for the selected range.</p>
        )}

      {!isLoading && !isError &&
        subView === "state" && stateRows.length === 0 && stateQuery.isFetched && (
          <p className="text-sm text-gray-500">No state data for the selected range.</p>
        )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portal Traffic tab
// ---------------------------------------------------------------------------

function PortalTrafficTab() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [userSegment, setUserSegment] = useState<UserSegment>("all");
  const [downloading, setDownloading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["reports-traffic", startDate, endDate, userSegment],
    queryFn: () =>
      getPortalTraffic({
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        user_segment: userSegment,
      }),
  });

  const onExport = async () => {
    setDownloading(true);
    setExportError(null);
    try {
      await downloadReportCsv("portal-traffic", {
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      });
    } catch (err) {
      setExportError((err as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  const data = query.data;

  return (
    <div className="space-y-6">
      {/* Filters */}
      <Card>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <DateRangeFilter
            startDate={startDate}
            endDate={endDate}
            onStartChange={setStartDate}
            onEndChange={setEndDate}
          />
          <label className="text-sm">
            <span className="block font-medium text-gray-700">User segment</span>
            <select
              value={userSegment}
              onChange={(e) => setUserSegment(e.target.value as UserSegment)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            >
              <option value="all">All users</option>
              <option value="new">New</option>
              <option value="returning">Returning</option>
            </select>
          </label>
          <div className="flex items-end">
            <Button
              variant="secondary"
              onClick={onExport}
              disabled={downloading || query.isLoading}
            >
              {downloading ? "Downloading…" : "Export CSV"}
            </Button>
          </div>
        </div>
        {exportError && (
          <p className="mt-2 text-sm text-red-700">{exportError}</p>
        )}
      </Card>

      {query.isLoading && <Spinner />}

      {query.isError && (
        <Alert tone="error" title="Could not load portal traffic">
          {(query.error as Error).message}
        </Alert>
      )}

      {data && (
        <>
          {/* Metric cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {[
              { label: "Sessions", value: data.total_sessions.toLocaleString() },
              { label: "Unique users", value: data.unique_users.toLocaleString() },
              { label: "Page views", value: data.total_page_views.toLocaleString() },
              {
                label: "Form abandon rate",
                value: `${data.form_abandon_rate.toFixed(1)}%`,
              },
              { label: "PDF downloads", value: data.pdf_download_count.toLocaleString() },
            ].map(({ label, value }) => (
              <Card key={label}>
                <p className="text-xs font-medium text-gray-500">{label}</p>
                <p className="mt-1 text-2xl font-semibold text-gray-900">{value}</p>
              </Card>
            ))}
          </div>

          {/* Top pages table */}
          {data.top_pages.length > 0 && (
            <Card>
              <h2 className="mb-3 text-base font-semibold text-gray-900">Top pages</h2>
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                  <tr>
                    <th scope="col" className="px-3 py-2">Page</th>
                    <th scope="col" className="px-3 py-2 text-right">Views</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.top_pages.map((p) => (
                    <tr key={p.page} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono text-xs text-gray-700">{p.page}</td>
                      <td className="px-3 py-2 text-right">{p.view_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export Center tab
// ---------------------------------------------------------------------------

const EXPORT_REPORTS: Array<{
  type: AdminReportType;
  label: string;
  description: string;
}> = [
  {
    type: "sales-by-period",
    label: "Sales by Period",
    description: "Approved records grouped by month, quarter, or year with offer totals.",
  },
  {
    type: "sales-by-type",
    label: "Sales by Equipment Type",
    description: "Records broken out by equipment category with average scores and offers.",
  },
  {
    type: "sales-by-state",
    label: "Sales by State",
    description: "Records grouped by customer state with approval counts.",
  },
  {
    type: "portal-traffic",
    label: "Portal Traffic",
    description: "Session counts, page views, form abandon rate, and PDF download activity.",
  },
];

function ExportCenterTab() {
  const [downloading, setDownloading] = useState<AdminReportType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onDownload = async (reportType: AdminReportType) => {
    setDownloading(reportType);
    setError(null);
    try {
      await downloadReportCsv(reportType);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <Alert tone="error" title="Export failed">
          {error}
        </Alert>
      )}
      {EXPORT_REPORTS.map(({ type, label, description }) => (
        <Card key={type}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">{label}</h2>
              <p className="mt-0.5 text-sm text-gray-500">{description}</p>
            </div>
            <Button
              variant="secondary"
              onClick={() => onDownload(type)}
              disabled={downloading !== null}
              aria-label={`Download ${label} CSV`}
            >
              {downloading === type ? "Downloading…" : "Download CSV"}
            </Button>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TAB_COMPONENTS: Record<string, React.ComponentType> = {
  sales_by_period: SalesByPeriodTab,
  sales_by_type_location: SalesByTypeLocationTab,
  user_traffic: PortalTrafficTab,
  export_center: ExportCenterTab,
};

const TABS: AdminReportTab[] = [
  { slug: "sales_by_period", label: "Sales by Period", status: "active" },
  { slug: "sales_by_type_location", label: "Type/Location", status: "active" },
  { slug: "user_traffic", label: "User Traffic", status: "active" },
  { slug: "export_center", label: "Export Center", status: "active" },
];

export function AdminReportsPage() {
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  const tabs = TABS;
  const active = tabs.find((t) => t.slug === activeSlug) ?? tabs[0];
  const TabContent = active ? TAB_COMPONENTS[active.slug] : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Admin reports</h1>
        <p className="mt-1 text-sm text-gray-600">
          Read-only views available to admins and the reporting role.
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Admin reports"
        className="flex flex-wrap gap-2 border-b border-gray-200"
      >
        {tabs.map((tab) => {
          const isActive = active?.slug === tab.slug;
          return (
            <button
              key={tab.slug}
              type="button"
              role="tab"
              id={`tab-${tab.slug}`}
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.slug}`}
              onClick={() => setActiveSlug(tab.slug)}
              className={
                isActive
                  ? "border-b-2 border-gray-900 px-3 py-2 text-sm font-medium text-gray-900"
                  : "border-b-2 border-transparent px-3 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
              }
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={active ? `tabpanel-${active.slug}` : undefined}
        aria-labelledby={active ? `tab-${active.slug}` : undefined}
      >
        {TabContent ? <TabContent /> : null}
      </div>
    </div>
  );
}
