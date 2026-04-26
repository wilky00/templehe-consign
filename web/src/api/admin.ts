// ABOUTME: Admin panel API client — operations dashboard, CSV export, manual transitions, reports.
// ABOUTME: Phase 4 Sprint 1 surface; Sprints 2+ extend with customers, config, routing, etc.
import {
  type AdminOperationsFilters,
  type AdminOperationsResponse,
  type AdminReportsIndexResponse,
  type ManualTransitionRequest,
  type ManualTransitionResponse,
  type UUID,
} from "./types";
import { useAuthStore } from "../state/auth";
import { API_BASE_URL, request } from "./client";

function _params(filters: AdminOperationsFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (filters.status) p.set("status", filters.status);
  if (filters.assignee_id) p.set("assignee_id", filters.assignee_id);
  if (filters.customer_id) p.set("customer_id", filters.customer_id);
  if (filters.overdue_only) p.set("overdue_only", "true");
  if (filters.sort) p.set("sort", filters.sort);
  if (filters.direction) p.set("direction", filters.direction);
  if (filters.page) p.set("page", String(filters.page));
  if (filters.per_page) p.set("per_page", String(filters.per_page));
  return p;
}

export async function listAdminOperations(
  filters: AdminOperationsFilters = {},
): Promise<AdminOperationsResponse> {
  const qs = _params(filters).toString();
  const path = qs ? `/admin/operations?${qs}` : "/admin/operations";
  return request<AdminOperationsResponse>(path);
}

export function adminOperationsCsvUrl(
  filters: Omit<AdminOperationsFilters, "page" | "per_page"> = {},
): string {
  const qs = _params(filters).toString();
  return qs ? `${API_BASE_URL}/admin/operations/export.csv?${qs}` : `${API_BASE_URL}/admin/operations/export.csv`;
}

export async function downloadOperationsCsv(
  filters: Omit<AdminOperationsFilters, "page" | "per_page"> = {},
): Promise<void> {
  // Browser-driven download — Bearer header isn't sent on a plain link.
  // Pull the CSV via fetch with auth, then create a blob and click a
  // synthetic anchor.
  const url = adminOperationsCsvUrl(filters);
  const token = useAuthStore.getState().accessToken;
  const resp = await fetch(url, {
    method: "GET",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: "include",
  });
  if (!resp.ok) {
    throw new Error(`CSV export failed (HTTP ${resp.status}).`);
  }
  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = "operations.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function manualTransition(
  recordId: UUID,
  body: ManualTransitionRequest,
): Promise<ManualTransitionResponse> {
  return request<ManualTransitionResponse>(
    `/admin/equipment/${recordId}/transition`,
    { method: "POST", body },
  );
}

export async function getAdminReportsIndex(): Promise<AdminReportsIndexResponse> {
  return request<AdminReportsIndexResponse>("/admin/reports");
}
