// ABOUTME: Admin panel API client — operations dashboard, CSV export, manual transitions, reports.
// ABOUTME: Phase 4 Sprint 1 surface; Sprints 2+ extend with customers, config, routing, etc.
import {
  type AdminCustomer,
  type AdminCustomerCreate,
  type AdminCustomerListFilters,
  type AdminCustomerListResponse,
  type AdminCustomerPatch,
  type AdminOperationsFilters,
  type AdminOperationsResponse,
  type AdminReportsIndexResponse,
  type AppConfigItem,
  type AppConfigListResponse,
  type DeactivateUserRequest,
  type DeactivateUserResponse,
  type ManualTransitionRequest,
  type ManualTransitionResponse,
  type RoutingRule,
  type RoutingRuleCreate,
  type RoutingRuleListResponse,
  type RoutingRulePatch,
  type RoutingRuleReorderRequest,
  type RoutingRuleReorderResponse,
  type RoutingRuleTestRequest,
  type RoutingRuleTestResponse,
  type SendInviteResponse,
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

// --- Customer admin (Sprint 2) ----------------------------------------- //

function _customerListParams(filters: AdminCustomerListFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (filters.search) p.set("search", filters.search);
  if (filters.include_deleted) p.set("include_deleted", "true");
  if (filters.walkins_only) p.set("walkins_only", "true");
  if (filters.page) p.set("page", String(filters.page));
  if (filters.per_page) p.set("per_page", String(filters.per_page));
  return p;
}

export async function listAdminCustomers(
  filters: AdminCustomerListFilters = {},
): Promise<AdminCustomerListResponse> {
  const qs = _customerListParams(filters).toString();
  const path = qs ? `/admin/customers?${qs}` : "/admin/customers";
  return request<AdminCustomerListResponse>(path);
}

export async function getAdminCustomer(customerId: UUID): Promise<AdminCustomer> {
  return request<AdminCustomer>(`/admin/customers/${customerId}`);
}

export async function createWalkinCustomer(
  body: AdminCustomerCreate,
): Promise<AdminCustomer> {
  return request<AdminCustomer>("/admin/customers", { method: "POST", body });
}

export async function updateAdminCustomer(
  customerId: UUID,
  body: AdminCustomerPatch,
): Promise<AdminCustomer> {
  return request<AdminCustomer>(`/admin/customers/${customerId}`, {
    method: "PATCH",
    body,
  });
}

export async function softDeleteAdminCustomer(customerId: UUID): Promise<AdminCustomer> {
  return request<AdminCustomer>(`/admin/customers/${customerId}`, {
    method: "DELETE",
  });
}

export async function sendWalkinInvite(customerId: UUID): Promise<SendInviteResponse> {
  return request<SendInviteResponse>(
    `/admin/customers/${customerId}/send-invite`,
    { method: "POST" },
  );
}

// --- User deactivation (Sprint 2) -------------------------------------- //

export async function deactivateUser(
  userId: UUID,
  body: DeactivateUserRequest,
): Promise<DeactivateUserResponse> {
  return request<DeactivateUserResponse>(`/admin/users/${userId}/deactivate`, {
    method: "POST",
    body,
  });
}

// --- AppConfig admin (Sprint 3) ---------------------------------------- //

export async function listAppConfig(): Promise<AppConfigListResponse> {
  return request<AppConfigListResponse>("/admin/config");
}

export async function updateAppConfig(
  key: string,
  value: unknown,
): Promise<AppConfigItem> {
  return request<AppConfigItem>(`/admin/config/${key}`, {
    method: "PATCH",
    body: { value },
  });
}

// --- Lead routing admin (Sprint 4) ------------------------------------- //

export async function listRoutingRules(
  includeDeleted = false,
): Promise<RoutingRuleListResponse> {
  const path = includeDeleted
    ? "/admin/routing-rules?include_deleted=true"
    : "/admin/routing-rules";
  return request<RoutingRuleListResponse>(path);
}

export async function createRoutingRule(body: RoutingRuleCreate): Promise<RoutingRule> {
  return request<RoutingRule>("/admin/routing-rules", { method: "POST", body });
}

export async function updateRoutingRule(
  ruleId: UUID,
  body: RoutingRulePatch,
): Promise<RoutingRule> {
  return request<RoutingRule>(`/admin/routing-rules/${ruleId}`, {
    method: "PATCH",
    body,
  });
}

export async function softDeleteRoutingRule(ruleId: UUID): Promise<RoutingRule> {
  return request<RoutingRule>(`/admin/routing-rules/${ruleId}`, { method: "DELETE" });
}

export async function reorderRoutingRules(
  body: RoutingRuleReorderRequest,
): Promise<RoutingRuleReorderResponse> {
  return request<RoutingRuleReorderResponse>("/admin/routing-rules/reorder", {
    method: "POST",
    body,
  });
}

export async function testRoutingRule(
  ruleId: UUID,
  body: RoutingRuleTestRequest,
): Promise<RoutingRuleTestResponse> {
  return request<RoutingRuleTestResponse>(`/admin/routing-rules/${ruleId}/test`, {
    method: "POST",
    body,
  });
}
