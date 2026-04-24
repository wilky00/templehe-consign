// ABOUTME: Sales API client wrappers — dashboard, record detail/assignment, cascade, publish, change-request resolve.
// ABOUTME: Record-lock lifecycle helpers live here too so the sales detail page can acquire/heartbeat/release in one place.
import { request } from "./client";
import type {
  AssignmentPatch,
  CascadeResult,
  ChangeRequestResolveRequest,
  ChangeRequestResolveResponse,
  LockInfo,
  PublishResponse,
  SalesDashboardResponse,
  SalesEquipmentDetail,
  UUID,
} from "./types";

export interface DashboardQuery {
  scope?: "mine" | "all";
  status?: string;
  assignedRepId?: UUID;
}

export async function getDashboard(
  q: DashboardQuery = {},
): Promise<SalesDashboardResponse> {
  const params = new URLSearchParams();
  if (q.scope) params.set("scope", q.scope);
  if (q.status) params.set("status", q.status);
  if (q.assignedRepId) params.set("assigned_rep_id", q.assignedRepId);
  const qs = params.toString();
  return request<SalesDashboardResponse>(
    `/sales/dashboard${qs ? `?${qs}` : ""}`,
  );
}

export async function getEquipmentDetail(
  id: UUID,
): Promise<SalesEquipmentDetail> {
  return request<SalesEquipmentDetail>(`/sales/equipment/${id}`);
}

export async function patchAssignment(
  id: UUID,
  patch: AssignmentPatch,
): Promise<SalesEquipmentDetail> {
  return request<SalesEquipmentDetail>(`/sales/equipment/${id}`, {
    method: "PATCH",
    body: patch,
  });
}

export async function cascadeAssignments(
  customerId: UUID,
  patch: AssignmentPatch,
): Promise<CascadeResult> {
  return request<CascadeResult>(
    `/sales/customers/${customerId}/cascade-assignments`,
    { method: "PATCH", body: patch },
  );
}

export async function publishListing(id: UUID): Promise<PublishResponse> {
  return request<PublishResponse>(`/sales/equipment/${id}/publish`, {
    method: "POST",
  });
}

export async function resolveChangeRequest(
  id: UUID,
  body: ChangeRequestResolveRequest,
): Promise<ChangeRequestResolveResponse> {
  return request<ChangeRequestResolveResponse>(`/sales/change-requests/${id}`, {
    method: "PATCH",
    body,
  });
}

// ---------------------------------------------------------------------------
// Record lock
// ---------------------------------------------------------------------------

export async function acquireLock(recordId: UUID): Promise<LockInfo> {
  return request<LockInfo>(`/record-locks`, {
    method: "POST",
    body: { record_id: recordId, record_type: "equipment_record" },
  });
}

export async function heartbeatLock(recordId: UUID): Promise<LockInfo> {
  return request<LockInfo>(`/record-locks/${recordId}/heartbeat`, {
    method: "PUT",
  });
}

export async function releaseLock(recordId: UUID): Promise<void> {
  return request<void>(`/record-locks/${recordId}`, { method: "DELETE" });
}

export async function overrideLock(recordId: UUID): Promise<void> {
  return request<void>(`/record-locks/${recordId}/override`, {
    method: "DELETE",
  });
}
