// ABOUTME: Manager approval queue API client — fetches queue, approval detail, approve/reject actions.
// ABOUTME: Also covers the price change re-approval queue endpoint.
import { request } from "./client";
import type { UUID, ISODateTime } from "./types";

export interface ApprovalQueueItem {
  submission_id: UUID;
  equipment_record_id: UUID;
  reference_number: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  overall_score: number | null;
  score_band: string | null;
  marketability_rating: string | null;
  appraiser_name: string | null;
  submitted_at: ISODateTime | null;
  management_review_required: boolean;
  hold_for_title_review: boolean;
  red_flags: unknown[] | null;
}

export interface ApprovalQueueResponse {
  items: ApprovalQueueItem[];
  total: number;
}

export interface ComponentScoreOut {
  id: UUID;
  component_id: UUID;
  component_name: string;
  raw_score: number;
  weight_at_time_of_scoring: number | null;
  notes: string | null;
}

export interface SubmissionDetail {
  id: UUID;
  equipment_record_id: UUID;
  appraiser_id: UUID | null;
  status: string;
  category_id: UUID | null;
  make: string | null;
  model: string | null;
  year: number | null;
  hours_condition: string | null;
  running_status: string | null;
  serial_number: string | null;
  title_status: string | null;
  overall_score: number | null;
  score_band: string | null;
  management_review_required: boolean;
  hold_for_title_review: boolean;
  review_notes: string | null;
  marketability_rating: string | null;
  transport_notes: string | null;
  listing_notes: string | null;
  approved_purchase_offer: number | null;
  suggested_consignment_price: number | null;
  rejection_notes: string | null;
  approved_by_id: UUID | null;
  approved_at: ISODateTime | null;
  red_flags: unknown[] | null;
  comparable_sales_data: unknown[] | null;
  component_scores: ComponentScoreOut[];
  submitted_at: ISODateTime | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ApproveRequest {
  purchase_offer: number;
  consignment_price: number;
  notes?: string;
  title_review_confirmed?: boolean;
}

export interface RejectRequest {
  rejection_notes: string;
  send_back?: boolean;
}

export interface PriceChangeQueueItem {
  change_request_id: UUID;
  equipment_record_id: UUID;
  reference_number: string | null;
  make_model: string | null;
  approved_price: number | null;
  proposed_price: number | null;
  submitted_at: ISODateTime | null;
  customer_email: string | null;
}

export interface PriceChangeQueueResponse {
  items: PriceChangeQueueItem[];
  total: number;
}

export async function getApprovalQueue(): Promise<ApprovalQueueResponse> {
  return request<ApprovalQueueResponse>("/manager/approvals");
}

export async function getApprovalDetail(submissionId: UUID): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/manager/approvals/${submissionId}`);
}

export async function approveSubmission(
  submissionId: UUID,
  body: ApproveRequest,
): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/manager/approvals/${submissionId}/approve`, {
    method: "POST",
    body,
  });
}

export async function rejectSubmission(
  submissionId: UUID,
  body: RejectRequest,
): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/manager/approvals/${submissionId}/reject`, {
    method: "POST",
    body,
  });
}

export async function getPriceChangeQueue(): Promise<PriceChangeQueueResponse> {
  return request<PriceChangeQueueResponse>("/manager/approvals/price-changes");
}

export interface PriceChangeApprovalOut {
  change_request_id: UUID;
  status: string;
  resolved_at: ISODateTime | null;
  new_consignment_price: number | null;
}

export async function approvePriceChange(
  changeRequestId: UUID,
): Promise<PriceChangeApprovalOut> {
  return request<PriceChangeApprovalOut>(
    `/manager/approvals/price-changes/${changeRequestId}/approve`,
    { method: "POST" },
  );
}
