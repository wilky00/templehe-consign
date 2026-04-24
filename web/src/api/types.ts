// ABOUTME: TypeScript shapes that mirror the backend schemas used by the web client.
// ABOUTME: Keep in sync with api/schemas/* — a mismatch here surfaces as a runtime error, not a type error.

export type UUID = string;
export type ISODateTime = string;

export interface CurrentUser {
  id: UUID;
  email: string;
  role: string;
  status: string;
  first_name: string;
  last_name: string;
  totp_enabled: boolean;
  requires_terms_reaccept: boolean;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  tos_version: string;
  privacy_version: string;
}

export interface RegisterResponse {
  id: UUID;
  email: string;
  message: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface LegalDocument {
  document_type: "tos" | "privacy";
  version: string;
  body_markdown: string;
}

export interface ConsentStatus {
  tos_current_version: string;
  privacy_current_version: string;
  tos_accepted_version: string | null;
  privacy_accepted_version: string | null;
  requires_reaccept: boolean;
}

export interface EmailPrefs {
  intake_confirmations: boolean;
  status_updates: boolean;
  marketing: boolean;
  sms_opt_in: boolean;
}

export interface CustomerProfile {
  id: UUID;
  user_id: UUID;
  business_name: string | null;
  submitter_name: string;
  title: string | null;
  address_street: string | null;
  address_city: string | null;
  address_state: string | null;
  address_zip: string | null;
  business_phone: string | null;
  business_phone_ext: string | null;
  cell_phone: string | null;
  email_prefs: EmailPrefs;
}

export type RunningStatus = "running" | "partially_running" | "not_running";
export type OwnershipType = "owned" | "financed" | "leased" | "unknown";

export interface IntakePhotoIn {
  storage_key: string;
  caption?: string | null;
  display_order?: number;
}

export interface IntakeSubmission {
  category_id: UUID | null;
  make: string | null;
  model: string | null;
  year: number | null;
  serial_number: string | null;
  hours: number | null;
  running_status: RunningStatus | null;
  ownership_type: OwnershipType | null;
  location_text: string | null;
  description: string | null;
  photos: IntakePhotoIn[];
}

export interface IntakePhotoOut {
  id: UUID;
  storage_key: string;
  caption: string | null;
  display_order: number;
  uploaded_at: ISODateTime;
  scan_status: string;
  content_type: string | null;
}

export interface StatusEventOut {
  id: UUID;
  from_status: string | null;
  to_status: string;
  note: string | null;
  created_at: ISODateTime;
}

export interface EquipmentRecord {
  id: UUID;
  reference_number: string;
  status: string;
  category_id: UUID | null;
  make: string | null;
  model: string | null;
  year: number | null;
  serial_number: string | null;
  hours: number | null;
  running_status: string | null;
  ownership_type: string | null;
  location_text: string | null;
  description: string | null;
  submitted_at: ISODateTime | null;
  created_at: ISODateTime;
  photos: IntakePhotoOut[];
  status_events: StatusEventOut[];
}

export interface UploadUrlRequest {
  filename: string;
  content_type: string;
}

export interface UploadUrlResponse {
  upload_url: string;
  storage_key: string;
  expires_in: number;
}

export interface FinalizePhotoRequest {
  storage_key: string;
  content_type: string;
  caption?: string | null;
  display_order?: number;
  sha256?: string | null;
}

export interface ChangeRequestCreate {
  request_type: string;
  customer_notes?: string | null;
}

export interface ChangeRequestOut {
  id: UUID;
  equipment_record_id: UUID;
  request_type: string;
  customer_notes: string | null;
  status: string;
  submitted_at: ISODateTime;
  resolved_at: ISODateTime | null;
}

export interface DataExportOut {
  id: UUID;
  status: string;
  requested_at: ISODateTime;
  completed_at: ISODateTime | null;
  download_url: string | null;
  url_expires_at: ISODateTime | null;
  error: string | null;
}

export interface DeletionRequestResponse {
  status: string;
  deletion_grace_until: ISODateTime | null;
  message: string;
}

export interface ApiError {
  detail: string;
}
