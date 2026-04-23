// ABOUTME: Typed wrappers for /api/v1/me/profile, /me/email-prefs, and /me/account/*.
// ABOUTME: Covers the customer profile, deletion flow, and data-export endpoints.
import { request } from "./client";
import type {
  CustomerProfile,
  DataExportOut,
  DeletionRequestResponse,
  EmailPrefs,
} from "./types";

export function getProfile(): Promise<CustomerProfile> {
  return request<CustomerProfile>("/me/profile");
}

export function updateProfile(
  patch: Partial<Omit<CustomerProfile, "id" | "user_id" | "email_prefs">>,
): Promise<CustomerProfile> {
  return request<CustomerProfile>("/me/profile", {
    method: "PATCH",
    body: patch,
  });
}

export function getEmailPrefs(): Promise<EmailPrefs> {
  return request<EmailPrefs>("/me/email-prefs");
}

export function updateEmailPrefs(body: EmailPrefs): Promise<EmailPrefs> {
  return request<EmailPrefs>("/me/email-prefs", { method: "PATCH", body });
}

export function requestDataExport(): Promise<DataExportOut> {
  return request<DataExportOut>("/me/account/data-export", { method: "POST" });
}

export function listDataExports(): Promise<DataExportOut[]> {
  return request<DataExportOut[]>("/me/account/data-exports");
}

export function requestAccountDeletion(): Promise<DeletionRequestResponse> {
  return request<DeletionRequestResponse>("/me/account/delete", {
    method: "POST",
  });
}

export function cancelAccountDeletion(): Promise<DeletionRequestResponse> {
  return request<DeletionRequestResponse>("/me/account/delete/cancel", {
    method: "POST",
  });
}
