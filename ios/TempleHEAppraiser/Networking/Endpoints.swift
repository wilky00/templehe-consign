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
}
