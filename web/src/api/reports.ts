// ABOUTME: Phase 7 — API client for PDF report download endpoint.
// ABOUTME: Returns a signed R2 URL (200) or a generating status (202).
import { request } from "./client";

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
