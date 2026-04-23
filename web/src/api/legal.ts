// ABOUTME: Typed wrappers for /api/v1/legal/* — public ToS/Privacy + re-accept.
// ABOUTME: Sign-up reads the current version from /tos + /privacy and echoes it back on register.
import { request } from "./client";
import type { ConsentStatus, LegalDocument } from "./types";

export function getToS(): Promise<LegalDocument> {
  return request<LegalDocument>("/legal/tos", { skipAuth: true });
}

export function getPrivacy(): Promise<LegalDocument> {
  return request<LegalDocument>("/legal/privacy", { skipAuth: true });
}

export function getConsentStatus(): Promise<ConsentStatus> {
  return request<ConsentStatus>("/legal/consent-status");
}

export function acceptTerms(tos_version: string, privacy_version: string) {
  return request<{ message: string }>("/legal/accept", {
    method: "POST",
    body: { tos_version, privacy_version },
  });
}
