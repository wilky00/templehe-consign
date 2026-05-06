// ABOUTME: Public listing catalog API client — list, detail, and inquiry endpoints.
// ABOUTME: No auth required; the request helper sends a token only if the user is logged in.
import { request } from "./client";
import type { UUID, ISODateTime } from "./types";

export interface ListingCard {
  id: UUID;
  listing_title: string;
  asking_price: number | null;
  status: string;
  published_at: ISODateTime | null;
  make: string | null;
  model: string | null;
  year: number | null;
  category_name: string | null;
  hours_condition: string | null;
  marketability_rating: string | null;
  state: string | null;
  primary_photo_url: string | null;
}

export interface ListingDetail extends ListingCard {
  serial_number: string | null;
  running_status: string | null;
  transport_notes: string | null;
  listing_notes: string | null;
  assigned_rep_name: string | null;
  contact_phone: string | null;
}

export interface ListingListResponse {
  items: ListingCard[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ListingFilters {
  page?: number;
  page_size?: number;
  sort?: "newest" | "price_asc" | "price_desc";
  min_price?: number | null;
  max_price?: number | null;
  condition?: string | null;
}

export interface InquiryRequest {
  first_name: string;
  last_name: string;
  email: string;
  phone?: string | null;
  message?: string | null;
  web_address?: string;
}

export interface InquiryResponse {
  id: UUID;
  message: string;
}

export interface ListingPatchRequest {
  asking_price?: number | null;
  status?: "active" | "sold" | "withdrawn" | null;
}

export interface ListingPatchResponse {
  equipment_record_id: UUID;
  listing_id: UUID;
  status: string;
  asking_price: number | null;
}

export async function getListings(filters: ListingFilters = {}): Promise<ListingListResponse> {
  const params = new URLSearchParams();
  if (filters.page != null) params.set("page", String(filters.page));
  if (filters.page_size != null) params.set("page_size", String(filters.page_size));
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.min_price != null) params.set("min_price", String(filters.min_price));
  if (filters.max_price != null) params.set("max_price", String(filters.max_price));
  if (filters.condition) params.set("condition", filters.condition);
  const qs = params.toString();
  return request<ListingListResponse>(`/public/listings${qs ? `?${qs}` : ""}`);
}

export async function getListingDetail(id: UUID): Promise<ListingDetail> {
  return request<ListingDetail>(`/public/listings/${id}`);
}

export async function submitInquiry(
  listingId: UUID,
  body: InquiryRequest,
): Promise<InquiryResponse> {
  return request<InquiryResponse>(`/public/listings/${listingId}/inquiries`, {
    method: "POST",
    body,
    skipAuth: true,
  });
}

export async function patchListing(
  recordId: UUID,
  body: ListingPatchRequest,
): Promise<ListingPatchResponse> {
  return request<ListingPatchResponse>(`/sales/equipment/${recordId}/listing`, {
    method: "PATCH",
    body,
  });
}
