// ABOUTME: Observable auth state machine — LoggedOut / TwoFactorPending / LoggedIn.
// ABOUTME: Single source of truth for "is the user signed in", injected via @EnvironmentObject.

import Combine
import Foundation

/// Coarse-grained auth phase that the UI branches on. Finer-grained
/// states (e.g. "loading", per-screen errors) live inside the views;
/// this is the contract for "what's the next screen the router shows."
enum AuthPhase: Equatable {
    case loggedOut
    case twoFactorPending(partialToken: String)
    case loggedIn
}

@MainActor
final class AuthState: ObservableObject {
    @Published private(set) var phase: AuthPhase
    @Published var lastError: String?

    private let client: TempleHEClient

    init(client: TempleHEClient) {
        self.client = client
        // If a previous session left tokens in Keychain, we boot
        // straight to LoggedIn. The first authenticated request will
        // either succeed or flip to LoggedOut via the 401 path.
        let hasToken = client.currentAccessToken() != nil
        self.phase = hasToken ? .loggedIn : .loggedOut
    }

    // MARK: - Login

    func login(email: String, password: String) async {
        lastError = nil
        do {
            let resp: LoginResponse = try await client.request(
                "POST",
                path: Endpoint.authLogin,
                body: LoginRequest(email: email, password: password),
                authenticated: false
            )
            if resp.requires_2fa == true, let partial = resp.partial_token {
                phase = .twoFactorPending(partialToken: partial)
                return
            }
            guard let access = resp.access_token, let refresh = resp.refresh_token else {
                lastError = "Server returned an incomplete login response."
                return
            }
            try client.setTokens(access: access, refresh: refresh)
            phase = .loggedIn
        } catch APIError.http(let status, _) where status == 401 {
            lastError = "Incorrect email or password."
        } catch APIError.http(let status, _) where status == 423 {
            lastError = "This account is temporarily locked. Try again in 30 minutes."
        } catch {
            lastError = "Something went wrong. Please try again."
        }
    }

    // MARK: - 2FA

    func verify2FA(code: String) async {
        guard case .twoFactorPending(let partial) = phase else { return }
        lastError = nil
        do {
            let token: TokenResponse = try await client.request(
                "POST",
                path: Endpoint.auth2FAVerify,
                body: TwoFAVerifyRequest(partial_token: partial, totp_code: code),
                authenticated: false
            )
            try client.setTokens(access: token.access_token, refresh: token.refresh_token)
            phase = .loggedIn
        } catch APIError.http(let status, _) where status == 400 {
            lastError = "Invalid verification code."
        } catch {
            lastError = "Something went wrong. Please try again."
        }
    }

    func recover2FA(recoveryCode: String) async {
        guard case .twoFactorPending(let partial) = phase else { return }
        lastError = nil
        do {
            let token: TokenResponse = try await client.request(
                "POST",
                path: Endpoint.auth2FARecovery,
                body: TwoFARecoveryRequest(
                    partial_token: partial, recovery_code: recoveryCode
                ),
                authenticated: false
            )
            try client.setTokens(access: token.access_token, refresh: token.refresh_token)
            phase = .loggedIn
        } catch APIError.http(let status, _) where status == 400 {
            lastError = "Invalid or already-used recovery code."
        } catch {
            lastError = "Something went wrong. Please try again."
        }
    }

    // MARK: - Logout

    func logout() async {
        // Best-effort server-side logout; even if the call fails (e.g.
        // offline) we still clear local state so the UI returns to the
        // login screen.
        if let refresh = (try? KeychainStore().get(.refreshToken)) ?? nil {
            try? await client.request(
                "POST",
                path: Endpoint.authLogout,
                body: LogoutRequest(refresh_token: refresh),
                authenticated: true
            )
        }
        try? client.clearTokens()
        phase = .loggedOut
    }

    /// Force the state back to `.loggedOut`, e.g. after a refresh
    /// attempt 401s. UI surfaces this so the user re-authenticates.
    func forceLogout() {
        try? client.clearTokens()
        phase = .loggedOut
    }
}
