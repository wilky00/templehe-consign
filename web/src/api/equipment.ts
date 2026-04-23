// ABOUTME: Typed wrappers for /api/v1/me/equipment and related change-request + photo endpoints.
// ABOUTME: Photo upload is a 3-step flow: upload-url → PUT direct to R2 → POST photos finalize.
import { request } from "./client";
import type {
  ChangeRequestCreate,
  ChangeRequestOut,
  EquipmentRecord,
  FinalizePhotoRequest,
  IntakePhotoOut,
  IntakeSubmission,
  UploadUrlRequest,
  UploadUrlResponse,
  UUID,
} from "./types";

export interface EquipmentCategoryOption {
  id: UUID;
  name: string;
  slug: string;
}

export function listCategories(): Promise<EquipmentCategoryOption[]> {
  return request<EquipmentCategoryOption[]>("/me/equipment/categories");
}

export function submitIntake(body: IntakeSubmission): Promise<EquipmentRecord> {
  return request<EquipmentRecord>("/me/equipment", {
    method: "POST",
    body,
  });
}

export function listEquipment(): Promise<EquipmentRecord[]> {
  return request<EquipmentRecord[]>("/me/equipment");
}

export function getEquipment(id: UUID): Promise<EquipmentRecord> {
  return request<EquipmentRecord>(`/me/equipment/${id}`);
}

export function requestUploadUrl(
  recordId: UUID,
  body: UploadUrlRequest,
): Promise<UploadUrlResponse> {
  return request<UploadUrlResponse>(
    `/me/equipment/${recordId}/photos/upload-url`,
    { method: "POST", body },
  );
}

export function finalizePhoto(
  recordId: UUID,
  body: FinalizePhotoRequest,
): Promise<IntakePhotoOut> {
  return request<IntakePhotoOut>(`/me/equipment/${recordId}/photos`, {
    method: "POST",
    body,
  });
}

export function submitChangeRequest(
  recordId: UUID,
  body: ChangeRequestCreate,
): Promise<ChangeRequestOut> {
  return request<ChangeRequestOut>(
    `/me/equipment/${recordId}/change-requests`,
    { method: "POST", body },
  );
}

export function listChangeRequests(
  recordId: UUID,
): Promise<ChangeRequestOut[]> {
  return request<ChangeRequestOut[]>(
    `/me/equipment/${recordId}/change-requests`,
  );
}
