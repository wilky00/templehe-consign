// ABOUTME: Orchestrates the 3-step intake-photo flow: upload-url → PUT direct to R2 → finalize.
// ABOUTME: Used by the intake form + (future) change-request photo replacement flow.
import { finalizePhoto, requestUploadUrl } from "../api/equipment";
import type { IntakePhotoOut, UUID } from "../api/types";

export interface PhotoUploadProgress {
  fileName: string;
  status: "pending" | "uploading" | "finalizing" | "done" | "error";
  error?: string;
}

async function putToR2(
  uploadUrl: string,
  file: File,
  contentType: string,
): Promise<void> {
  const resp = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: file,
  });
  if (!resp.ok) {
    throw new Error(`R2 upload failed (${resp.status})`);
  }
}

export async function uploadIntakePhoto(
  recordId: UUID,
  file: File,
  displayOrder: number,
  caption?: string,
): Promise<IntakePhotoOut> {
  const contentType = file.type || "image/jpeg";
  const url = await requestUploadUrl(recordId, {
    filename: file.name,
    content_type: contentType,
  });
  await putToR2(url.upload_url, file, contentType);
  return finalizePhoto(recordId, {
    storage_key: url.storage_key,
    content_type: contentType,
    caption: caption ?? null,
    display_order: displayOrder,
  });
}
