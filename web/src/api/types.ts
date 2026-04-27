// ABOUTME: TypeScript shapes that mirror the backend schemas used by the web client.
// ABOUTME: Keep in sync with api/schemas/* — a mismatch here surfaces as a runtime error, not a type error.

export type UUID = string;
export type ISODateTime = string;

export interface CurrentUser {
  id: UUID;
  email: string;
  /**
   * Primary role — drives default landing-page routing (sales-side vs
   * customer-side). Phase 4 admin's "change primary role" updates this.
   * Capability checks should prefer `roles` (the full set).
   */
  role: string;
  /**
   * Every role slug the user holds, including the primary. Phase 4 pre-
   * work (multi-role users): use this for capability checks. Defaults
   * to `[role]` for back-compat in case the server omits it.
   */
  roles: string[];
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

// ---------------------------------------------------------------------------
// Phase 3 — Sales
// ---------------------------------------------------------------------------

export interface LockInfo {
  record_id: UUID;
  record_type: string;
  locked_by: UUID;
  locked_at: ISODateTime;
  expires_at: ISODateTime;
}

export interface LockConflict {
  detail: string;
  locked_by: UUID;
  locked_at: ISODateTime;
  expires_at: ISODateTime;
}

export interface EquipmentRow {
  id: UUID;
  reference_number: string | null;
  status: string;
  make: string | null;
  model: string | null;
  year: number | null;
  serial_number: string | null;
  submitted_at: ISODateTime | null;
  assigned_sales_rep_id: UUID | null;
  assigned_appraiser_id: UUID | null;
}

export interface CustomerGroup {
  customer_id: UUID;
  business_name: string | null;
  submitter_name: string;
  cell_phone: string | null;
  business_phone: string | null;
  business_phone_ext: string | null;
  state: string | null;
  first_submission_at: ISODateTime | null;
  total_items: number;
  assigned_sales_rep_id: UUID | null;
  records: EquipmentRow[];
}

export interface SalesDashboardResponse {
  customers: CustomerGroup[];
  total_customers: number;
  total_records: number;
}

export interface SalesStatusEvent {
  from_status: string | null;
  to_status: string;
  changed_by: UUID | null;
  note: string | null;
  created_at: ISODateTime;
}

export interface SalesChangeRequest {
  id: UUID;
  request_type: string;
  customer_notes: string | null;
  status: string;
  resolution_notes: string | null;
  resolved_by: UUID | null;
  submitted_at: ISODateTime;
  resolved_at: ISODateTime | null;
}

export interface SalesEquipmentDetail {
  id: UUID;
  reference_number: string | null;
  status: string;
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
  assigned_sales_rep_id: UUID | null;
  assigned_appraiser_id: UUID | null;
  customer_id: UUID;
  customer_business_name: string | null;
  customer_submitter_name: string;
  customer_cell_phone: string | null;
  customer_business_phone: string | null;
  customer_email: string;
  has_signed_contract: boolean;
  has_appraisal_report: boolean;
  public_listing_status: string | null;
  status_history: SalesStatusEvent[];
  change_requests: SalesChangeRequest[];
}

export interface AssignmentPatch {
  assigned_sales_rep_id?: UUID | null;
  assigned_appraiser_id?: UUID | null;
}

export interface CascadeResult {
  updated_record_ids: UUID[];
  skipped_record_ids: UUID[];
  skipped_reason: string | null;
}

export interface ChangeRequestResolveRequest {
  status: "resolved" | "rejected";
  resolution_notes?: string | null;
}

export interface ChangeRequestResolveResponse {
  id: UUID;
  status: string;
  resolution_notes: string | null;
  resolved_by: UUID | null;
  resolved_at: ISODateTime | null;
  equipment_record_id: UUID;
  equipment_record_status: string;
}

export interface PublishResponse {
  equipment_record_id: UUID;
  status: string;
  public_listing_id: UUID;
  published_at: ISODateTime;
}

// --- Phase 3 Sprint 4 — Calendar -------------------------------------------

export interface CalendarEventCustomer {
  id: UUID;
  name: string | null;
  business_name: string | null;
}

export interface CalendarEventEquipment {
  id: UUID;
  reference_number: string | null;
  make: string | null;
  model: string | null;
  location_text: string | null;
}

export interface CalendarEvent {
  id: UUID;
  equipment_record_id: UUID;
  appraiser_id: UUID;
  scheduled_at: ISODateTime;
  duration_minutes: number;
  site_address: string | null;
  cancelled_at: ISODateTime | null;
  customer: CalendarEventCustomer | null;
  equipment: CalendarEventEquipment | null;
}

export interface CalendarEventListResponse {
  events: CalendarEvent[];
  total: number;
}

export interface CalendarEventCreateRequest {
  equipment_record_id: UUID;
  appraiser_id: UUID;
  scheduled_at: ISODateTime;
  duration_minutes?: number;
  site_address?: string | null;
}

export interface CalendarEventPatchRequest {
  appraiser_id?: UUID;
  scheduled_at?: ISODateTime;
  duration_minutes?: number;
  site_address?: string | null;
}

export interface CalendarConflict {
  detail: string;
  next_available_at: ISODateTime | null;
  conflicting_event_id: UUID | null;
}

// ---------------------------------------------------------------------------
// Notification preferences (Phase 3 Sprint 5)
// ---------------------------------------------------------------------------

export type NotificationChannel = "email" | "sms" | "slack";

export interface NotificationPreference {
  channel: NotificationChannel;
  phone_number: string | null;
  slack_user_id: string | null;
  read_only: boolean;
}

export interface NotificationPreferenceUpdateRequest {
  channel: NotificationChannel;
  phone_number?: string | null;
  slack_user_id?: string | null;
}

// ---------------------------------------------------------------------------
// Phase 4 Sprint 1 — Admin operations dashboard + manual transitions
// ---------------------------------------------------------------------------

export type AdminOperationsSortField =
  | "updated_at"
  | "submitted_at"
  | "days_in_status"
  | "customer_name"
  | "status";
export type AdminOperationsSortDirection = "asc" | "desc";

export interface AdminOperationsRow {
  id: UUID;
  reference_number: string | null;
  status: string;
  status_display: string;
  days_in_status: number;
  customer_id: UUID;
  customer_name: string;
  business_name: string | null;
  state: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  assigned_sales_rep_id: UUID | null;
  assigned_sales_rep_name: string | null;
  assigned_appraiser_id: UUID | null;
  assigned_appraiser_name: string | null;
  is_overdue: boolean;
  submitted_at: ISODateTime | null;
  updated_at: ISODateTime;
}

export interface AdminOperationsResponse {
  rows: AdminOperationsRow[];
  total: number;
  page: number;
  per_page: number;
}

export interface AdminOperationsFilters {
  status?: string | null;
  assignee_id?: UUID | null;
  customer_id?: UUID | null;
  overdue_only?: boolean;
  sort?: AdminOperationsSortField;
  direction?: AdminOperationsSortDirection;
  page?: number;
  per_page?: number;
}

export interface ManualTransitionRequest {
  to_status: string;
  reason: string;
  send_notifications: boolean | null;
}

export interface ManualTransitionResponse {
  record_id: UUID;
  from_status: string;
  to_status: string;
  notifications_dispatched: boolean;
  audit_log_id: UUID;
}

export interface AdminReportTab {
  slug: string;
  label: string;
  status: string;
}

export interface AdminReportsIndexResponse {
  tabs: AdminReportTab[];
}

// ---------------------------------------------------------------------------
// Phase 4 Sprint 2 — Customer DB management + walk-in customers + deactivation
// ---------------------------------------------------------------------------

export interface AdminCustomerEquipmentSummary {
  id: UUID;
  reference_number: string | null;
  status: string;
  make: string | null;
  model: string | null;
  year: number | null;
  deleted_at: ISODateTime | null;
}

export interface AdminCustomer {
  id: UUID;
  user_id: UUID | null;
  user_email: string | null;
  invite_email: string | null;
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
  is_walkin: boolean;
  is_deleted: boolean;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  deleted_at: ISODateTime | null;
  equipment_records: AdminCustomerEquipmentSummary[];
}

export interface AdminCustomerListResponse {
  customers: AdminCustomer[];
  total: number;
  page: number;
  per_page: number;
}

export interface AdminCustomerListFilters {
  search?: string | null;
  include_deleted?: boolean;
  walkins_only?: boolean;
  page?: number;
  per_page?: number;
}

export interface AdminCustomerCreate {
  submitter_name: string;
  invite_email: string;
  business_name?: string | null;
  title?: string | null;
  address_street?: string | null;
  address_city?: string | null;
  address_state?: string | null;
  address_zip?: string | null;
  business_phone?: string | null;
  business_phone_ext?: string | null;
  cell_phone?: string | null;
}

export interface AdminCustomerPatch {
  submitter_name?: string | null;
  business_name?: string | null;
  title?: string | null;
  address_street?: string | null;
  address_city?: string | null;
  address_state?: string | null;
  address_zip?: string | null;
  business_phone?: string | null;
  business_phone_ext?: string | null;
  cell_phone?: string | null;
  invite_email?: string | null;
}

export interface SendInviteResponse {
  customer_id: UUID;
  invite_email: string;
  sent_at: ISODateTime;
}

export interface DeactivateUserRequest {
  reassign_to_id: UUID | null;
}

export interface DeactivateUserOpenWork {
  detail: string;
  open_record_count: number;
  future_event_count: number;
}

export interface DeactivateUserResponse {
  user_id: UUID;
  reassigned_records: UUID[];
  reassigned_events: UUID[];
  new_status: string;
}

// ---------------------------------------------------------------------------
// Phase 4 Sprint 3 — AppConfig admin
// ---------------------------------------------------------------------------

export type AppConfigFieldType = "string" | "int" | "uuid" | "list[string]";

export interface AppConfigItem {
  name: string;
  category: string;
  field_type: AppConfigFieldType | string;
  description: string;
  default: unknown;
  value: unknown;
}

export interface AppConfigListResponse {
  items: AppConfigItem[];
}

export interface AppConfigUpdateRequest {
  value: unknown;
}

// ---------------------------------------------------------------------------
// Phase 4 Sprint 4 — lead routing admin
// ---------------------------------------------------------------------------

export type RoutingRuleType = "ad_hoc" | "geographic" | "round_robin";

export interface RoutingRule {
  id: UUID;
  rule_type: RoutingRuleType;
  priority: number;
  conditions: Record<string, unknown> | null;
  assigned_user_id: UUID | null;
  round_robin_index: number;
  is_active: boolean;
  created_by: UUID | null;
  created_at: ISODateTime;
  deleted_at: ISODateTime | null;
}

export interface RoutingRuleListResponse {
  rules: RoutingRule[];
  total: number;
}

export interface RoutingRuleCreate {
  rule_type: RoutingRuleType;
  priority?: number;
  conditions?: Record<string, unknown> | null;
  assigned_user_id?: UUID | null;
  is_active?: boolean;
}

export interface RoutingRulePatch {
  priority?: number;
  conditions?: Record<string, unknown> | null;
  assigned_user_id?: UUID | null;
  is_active?: boolean;
}

export interface RoutingRuleReorderRequest {
  rule_type: RoutingRuleType;
  ordered_ids: UUID[];
}

export interface RoutingRuleReorderResponse {
  rules: RoutingRule[];
}

export interface RoutingRuleTestRequest {
  customer_id?: UUID | null;
  customer_email?: string | null;
  customer_state?: string | null;
  customer_zip?: string | null;
  customer_lat?: number | null;
  customer_lng?: number | null;
}

export interface RoutingRuleTestResponse {
  rule_id: UUID;
  rule_type: RoutingRuleType;
  matched: boolean;
  would_assign_to: UUID | null;
  reason: string;
}

// ---------------------------------------------------------------------------
// Phase 4 Sprint 5 — notification templates + watchers
// ---------------------------------------------------------------------------

export interface NotificationTemplate {
  name: string;
  channel: "email" | "sms";
  category: string;
  description: string;
  variables: string[];
  subject_template: string | null;
  body_template: string;
  has_override: boolean;
  override_subject: string | null;
  override_body: string | null;
}

export interface NotificationTemplateListResponse {
  templates: NotificationTemplate[];
}

export interface NotificationTemplateOverrideRequest {
  subject_md?: string | null;
  body_md?: string | null;
  delete?: boolean;
}

export interface Watcher {
  user_id: UUID;
  email: string;
  first_name: string;
  last_name: string;
  added_by: UUID | null;
  added_at: ISODateTime;
}

export interface WatcherListResponse {
  watchers: Watcher[];
}

// ---------------------------------------------------------------------------
// Phase 4 Sprint 6 — equipment categories admin
// ---------------------------------------------------------------------------

export interface CategoryComponent {
  id: UUID;
  name: string;
  weight_pct: number;
  display_order: number;
  active: boolean;
}

export interface CategoryInspectionPrompt {
  id: UUID;
  label: string;
  response_type: "yes_no_na" | "text" | "scale_1_5";
  required: boolean;
  display_order: number;
  active: boolean;
  version: number;
}

export interface CategoryAttachment {
  id: UUID;
  label: string;
  description: string | null;
  display_order: number;
  active: boolean;
}

export interface CategoryPhotoSlot {
  id: UUID;
  label: string;
  helper_text: string | null;
  required: boolean;
  display_order: number;
  active: boolean;
}

export interface CategoryRedFlagRule {
  id: UUID;
  label: string;
  condition_field: string;
  condition_operator: "equals" | "is_true" | "is_false";
  condition_value: string | null;
  actions: Record<string, unknown>;
  active: boolean;
  version: number;
}

export interface CategorySummary {
  id: UUID;
  name: string;
  slug: string;
  status: string;
  display_order: number;
  version: number;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  deleted_at: ISODateTime | null;
  replaced_at: ISODateTime | null;
}

export interface CategoryDetail extends CategorySummary {
  components: CategoryComponent[];
  inspection_prompts: CategoryInspectionPrompt[];
  attachments: CategoryAttachment[];
  photo_slots: CategoryPhotoSlot[];
  red_flag_rules: CategoryRedFlagRule[];
  weight_total: number;
  weight_warning: boolean;
}

export interface CategoryListResponse {
  categories: CategorySummary[];
}

export interface CategoryCreate {
  name: string;
  slug: string;
  display_order?: number;
}

export interface CategoryPatch {
  name?: string;
  slug?: string;
  display_order?: number;
  status?: "active" | "inactive";
}

export interface ComponentCreate {
  name: string;
  weight_pct: number;
  display_order?: number;
}

export interface ComponentPatch {
  name?: string;
  weight_pct?: number;
  display_order?: number;
  active?: boolean;
}

export interface InspectionPromptCreate {
  label: string;
  response_type: "yes_no_na" | "text" | "scale_1_5";
  required?: boolean;
  display_order?: number;
}

export interface InspectionPromptPatch {
  label?: string;
  response_type?: "yes_no_na" | "text" | "scale_1_5";
  required?: boolean;
  display_order?: number;
  active?: boolean;
}

export interface RedFlagRuleCreate {
  label: string;
  condition_field: string;
  condition_operator: "equals" | "is_true" | "is_false";
  condition_value?: string | null;
  actions?: Record<string, unknown>;
}

export interface RedFlagRulePatch {
  label?: string;
  condition_field?: string;
  condition_operator?: "equals" | "is_true" | "is_false";
  condition_value?: string | null;
  actions?: Record<string, unknown>;
  active?: boolean;
}

// --- Phase 4 Sprint 7 — integrations + health ---

export type IntegrationName =
  | "slack"
  | "twilio"
  | "sendgrid"
  | "google_maps"
  | "esign"
  | "valuation";

export type IntegrationTestStatus = "success" | "failure" | "stubbed";

export interface IntegrationOut {
  name: IntegrationName;
  is_set: boolean;
  set_by: UUID | null;
  set_at: string | null;
  last_tested_at: string | null;
  last_test_status: IntegrationTestStatus | null;
  last_test_detail: string | null;
  last_test_latency_ms: number | null;
}

export interface IntegrationListResponse {
  integrations: IntegrationOut[];
}

export interface IntegrationStoreRequest {
  plaintext: string;
}

export interface IntegrationRevealRequest {
  password: string;
  totp_code: string;
}

export interface IntegrationRevealResponse {
  name: IntegrationName;
  plaintext: string;
  revealed_at: string;
}

export interface IntegrationTestRequest {
  extra_args?: Record<string, unknown>;
}

export interface IntegrationTestResponse {
  name: IntegrationName;
  success: boolean;
  status: IntegrationTestStatus;
  detail: string;
  latency_ms: number;
}

export type HealthStatus = "green" | "yellow" | "red" | "unknown" | "stubbed";

export interface HealthStateRow {
  service_name: string;
  status: HealthStatus;
  last_checked_at: string | null;
  last_alerted_at: string | null;
  error_detail: Record<string, unknown> | null;
  latency_ms: number | null;
}

export interface HealthSnapshotResponse {
  services: HealthStateRow[];
  snapshot_at: string;
}

export interface CategoryImportResult {
  category_id: UUID;
  created: boolean;
  superseded_prompt_ids: UUID[];
  superseded_rule_ids: UUID[];
  added_component_ids: UUID[];
  added_prompt_ids: UUID[];
  added_attachment_ids: UUID[];
  added_photo_slot_ids: UUID[];
  added_rule_ids: UUID[];
}
