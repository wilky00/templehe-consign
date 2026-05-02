// ABOUTME: Typed endpoints + request/response shapes for the TempleHE backend.
// ABOUTME: Sprint 1 covers auth + device-token + ios-config; later sprints extend.

import Foundation

// MARK: - Login

struct LoginRequest: Encodable {
    let email: String
    let password: String
}

/// The login response is a sum type at the API layer:
/// - 2FA-disabled accounts get `access_token` + `refresh_token` (mobile body-mode).
/// - 2FA-enabled accounts get `requires_2fa: true` + `partial_token`.
/// We decode both shapes and let the caller branch.
struct LoginResponse: Decodable {
    let access_token: String?
    let refresh_token: String?
    let requires_2fa: Bool?
    let partial_token: String?
}

// MARK: - 2FA

struct TwoFAVerifyRequest: Encodable {
    let partial_token: String
    let totp_code: String
}

struct TwoFARecoveryRequest: Encodable {
    let partial_token: String
    let recovery_code: String
}

struct TokenResponse: Decodable {
    let access_token: String
    let refresh_token: String?  // present in mobile body-mode
}

// MARK: - Refresh / logout

struct RefreshRequest: Encodable {
    let refresh_token: String
}

struct LogoutRequest: Encodable {
    let refresh_token: String
}

// MARK: - Device token

struct DeviceTokenRegisterRequest: Encodable {
    let platform: String  // "ios" | "android"
    let token: String
    let environment: String  // "development" | "production"
}

struct DeviceTokenRevokeRequest: Encodable {
    let token: String
}

struct DeviceTokenOut: Decodable, Identifiable {
    let id: String
    let platform: String
    let environment: String
    let token_preview: String
    let registered_at: String
    let last_seen_at: String
}

struct DeviceTokenListResponse: Decodable {
    let tokens: [DeviceTokenOut]
}

// MARK: - Appointments

struct AppointmentDetail: Decodable, Identifiable {
    let calendar_event_id: String
    let equipment_record_id: String
    let reference_number: String?
    let scheduled_at: String
    let duration_minutes: Int
    let site_address: String?
    let record_status: String
    let customer_make: String?
    let customer_model: String?
    let customer_year: Int?
    let customer_name: String?
    let customer_phone: String?
    let sales_rep_name: String?
    let sales_rep_phone: String?
    let sales_rep_email: String?

    var id: String { calendar_event_id }

    var makeModelYear: String {
        [customer_make, customer_model, customer_year.map { String($0) }]
            .compactMap { $0 }
            .joined(separator: " ")
    }
}

struct AppointmentListResponse: Decodable {
    let appointments: [AppointmentDetail]
    let days_ahead: Int
}

// MARK: - Valuation

struct ComparableSaleOut: Decodable, Identifiable {
    let id: String
    let make: String?
    let model: String?
    let year: Int?
    let hours: Int?
    let sale_price: Double?
    let sale_date: String?
    let source: String?
    let source_url: String?
    let notes: String?
    let category_id: String?

    var makeModelYear: String {
        [make, model, year.map { String($0) }]
            .compactMap { $0 }
            .joined(separator: " ")
    }
}

struct ValuationSearchRequest: Encodable {
    let make: String?
    let model: String?
    let year: Int?
    let hours: Int?
    let category_id: String?
}

struct ValuationSearchResponse: Decodable {
    let results: [ComparableSaleOut]
    let used_sources: [String]
}

// MARK: - iOS Config

struct IOSConfigCategory: Decodable, Identifiable {
    let id: String
    let name: String
    let slug: String
    let display_order: Int
}

struct IOSConfigComponent: Decodable, Identifiable {
    let id: String
    let category_id: String
    let name: String
    let weight_pct: String
    let display_order: Int

    var weightDouble: Double { Double(weight_pct) ?? 0 }
}

struct IOSConfigPrompt: Decodable, Identifiable {
    let id: String
    let category_id: String
    let label: String
    let response_type: String  // yes_no_na | text | scale_1_5
    let required: Bool
    let display_order: Int
    let version: Int
}

struct IOSConfigRedFlagRule: Decodable, Identifiable {
    let id: String
    let category_id: String
    let label: String
    let condition_field: String
    let condition_operator: String
    let condition_value: String?
    let version: Int
}

struct IOSConfig: Decodable {
    let config_version: String
    let categories: [IOSConfigCategory]
    let components: [IOSConfigComponent]
    let inspection_prompts: [IOSConfigPrompt]
    let red_flag_rules: [IOSConfigRedFlagRule]

    func components(for categoryId: String) -> [IOSConfigComponent] {
        components.filter { $0.category_id == categoryId }
                  .sorted { $0.display_order < $1.display_order }
    }

    func prompts(for categoryId: String) -> [IOSConfigPrompt] {
        inspection_prompts.filter { $0.category_id == categoryId }
                          .sorted { $0.display_order < $1.display_order }
    }
}

// MARK: - Appraisal Submissions

struct SubmissionCreateRequest: Encodable {
    let equipment_record_id: String
}

struct InspectionAnswerIn: Encodable {
    let prompt_id: String
    let prompt_version: Int
    // Serialized as string; server accepts string for all response types
    let value: String?
}

struct ComponentScoreIn: Encodable {
    let component_id: String
    let score: Double
    let notes: String?
}

struct SubmissionUpdateRequest: Encodable {
    var category_id: String?
    var make: String?
    var model: String?
    var year: Int?
    var hours_condition: String?
    var running_status: String?
    var serial_number: String?
    var title_status: String?
    var field_values: [InspectionAnswerIn]?
    var component_scores: [ComponentScoreIn]?
    var marketability_rating: String?
    var transport_notes: String?
    var listing_notes: String?
}

struct ComponentScoreOut: Decodable, Identifiable {
    let id: String
    let component_id: String
    let component_name: String
    let raw_score: Double
    let weight_at_time_of_scoring: Double
    let notes: String?
}

struct SubmissionOut: Decodable, Identifiable {
    let id: String
    let equipment_record_id: String
    let appraiser_id: String?
    let status: String
    let category_id: String?
    let category_version: Int?
    let make: String?
    let model: String?
    let year: Int?
    let hours_condition: String?
    let running_status: String?
    let serial_number: String?
    let title_status: String?
    let overall_score: Double?
    let score_band: String?
    let marketability_rating: String?
    let transport_notes: String?
    let listing_notes: String?
    let component_scores: [ComponentScoreOut]
    let submitted_at: String?
    let created_at: String
    let updated_at: String
}

struct SubmissionListResponse: Decodable {
    let submissions: [SubmissionOut]
    let total: Int
}

// MARK: - Endpoint paths

enum Endpoint {
    static let authLogin = "/api/v1/auth/login"
    static let authRefresh = "/api/v1/auth/refresh"
    static let authLogout = "/api/v1/auth/logout"
    static let auth2FAVerify = "/api/v1/auth/2fa/verify"
    static let auth2FARecovery = "/api/v1/auth/2fa/recovery"
    static let authMe = "/api/v1/auth/me"
    static let meDeviceToken = "/api/v1/me/device-token"
    static let meAppointments = "/api/v1/me/appointments"
    static let iosConfig = "/api/v1/ios/config"
    static let valuationSearch = "/api/v1/valuation/search"
    static let appraisalSubmissions = "/api/v1/appraisal-submissions"
    static func appraisalSubmission(_ id: String) -> String {
        "/api/v1/appraisal-submissions/\(id)"
    }
    static func submitSubmission(_ id: String) -> String {
        "/api/v1/appraisal-submissions/\(id)/submit"
    }
}
