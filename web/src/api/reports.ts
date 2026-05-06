// ABOUTME: Reporting API client — Phase 7 PDF download + Phase 8 admin analytics endpoints.
// ABOUTME: Admin report fetchers (sales-by-period/type/state, portal-traffic, CSV export).
import { request, API_BASE_URL } from "./client";
import { useAuthStore } from "../state/auth";

export interface ReportDownloadResponse {
  download_url: string;
  expires_at: string;
}

export interface ReportGeneratingResponse {
  status: "generating";
  message: string;
}

export type ReportResponse = ReportDownloadResponse | ReportGeneratingResponse;

export function isReportReady(r: ReportResponse): r is ReportDownloadResponse {
  return "download_url" in r;
}

export function getReportDownload(recordId: string): Promise<ReportResponse> {
  return request<ReportResponse>(`/equipment-records/${recordId}/report/pdf`);
}

// ---------------------------------------------------------------------------
// Phase 8 Sprint 4 — Admin analytics report types
// ---------------------------------------------------------------------------

export interface SalesByPeriodRow {
  period_label: string;
  record_count: number;
  approved_count: number;
  direct_purchase_count: number;
  consignment_count: number;
  total_approved_offer: number;
  total_consignment_price: number;
  avg_days_to_publish: number | null;
}

export interface SalesByPeriodResponse {
  period_type: string;
  rows: SalesByPeriodRow[];
}

export interface SalesByTypeRow {
  category_name: string;
  record_count: number;
  approved_count: number;
  avg_overall_score: number | null;
  avg_approved_offer: number | null;
  avg_consignment_price: number | null;
}

export interface SalesByTypeResponse {
  rows: SalesByTypeRow[];
}

export interface SalesByStateRow {
  state: string;
  record_count: number;
  approved_count: number;
  avg_approved_offer: number | null;
}

export interface SalesByStateResponse {
  rows: SalesByStateRow[];
}

export interface PageViewMetric {
  page: string;
  view_count: number;
}

export interface PortalTrafficResponse {
  total_sessions: number;
  unique_users: number;
  total_page_views: number;
  top_pages: PageViewMetric[];
  form_abandon_rate: number | null;
  pdf_download_count: number;
}

export type PeriodType = "month" | "quarter" | "year";
export type UserSegment = "all" | "new" | "returning";
export type AdminReportType =
  | "sales-by-period"
  | "sales-by-type"
  | "sales-by-state"
  | "portal-traffic";

interface DateParams {
  start_date?: string;
  end_date?: string;
}

interface PeriodParams extends DateParams {
  period_type?: PeriodType;
}

interface TrafficParams extends DateParams {
  user_segment?: UserSegment;
}

function buildQs(params: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, v);
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export async function getSalesByPeriod(
  params: PeriodParams = {},
): Promise<SalesByPeriodResponse> {
  return request<SalesByPeriodResponse>(
    `/admin/reports/sales-by-period${buildQs({
      period_type: params.period_type,
      start_date: params.start_date,
      end_date: params.end_date,
    })}`,
  );
}

export async function getSalesByType(
  params: DateParams = {},
): Promise<SalesByTypeResponse> {
  return request<SalesByTypeResponse>(
    `/admin/reports/sales-by-type${buildQs({
      start_date: params.start_date,
      end_date: params.end_date,
    })}`,
  );
}

export async function getSalesByState(
  params: DateParams = {},
): Promise<SalesByStateResponse> {
  return request<SalesByStateResponse>(
    `/admin/reports/sales-by-state${buildQs({
      start_date: params.start_date,
      end_date: params.end_date,
    })}`,
  );
}

export async function getPortalTraffic(
  params: TrafficParams = {},
): Promise<PortalTrafficResponse> {
  return request<PortalTrafficResponse>(
    `/admin/reports/portal-traffic${buildQs({
      start_date: params.start_date,
      end_date: params.end_date,
      user_segment: params.user_segment,
    })}`,
  );
}

// CSV download — streams a blob and triggers a browser save dialog.
// Not routed through request() because we need the raw Response headers.
export async function downloadReportCsv(
  reportType: AdminReportType,
  params: PeriodParams = {},
): Promise<void> {
  const qs = new URLSearchParams({ report_type: reportType });
  if (params.period_type) qs.set("period_type", params.period_type);
  if (params.start_date) qs.set("start_date", params.start_date);
  if (params.end_date) qs.set("end_date", params.end_date);

  const token = useAuthStore.getState().accessToken;
  const resp = await fetch(`${API_BASE_URL}/admin/reports/export?${qs.toString()}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) throw new Error(`Export failed: HTTP ${resp.status}`);

  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  const cd = resp.headers.get("content-disposition") ?? "";
  const match = cd.match(/filename="([^"]+)"/);
  a.download = match ? match[1] : `${reportType}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}
