// ABOUTME: URLSession + async/await + Codable client for the TempleHE backend.
// ABOUTME: Sets X-Client: ios on every request; serializes 401-refresh so parallel
// ABOUTME: requests don't double-refresh and rotate the refresh token twice.

import Foundation

/// Single global protocol so tests can substitute a mock. Not actually
/// used as a parameter today (the production code holds a concrete
/// `TempleHEClient`), but the protocol is the seam for unit tests.
protocol TempleHEClientProtocol {
    func request<Body: Encodable, Response: Decodable>(
        _ method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws -> Response

    func request<Body: Encodable>(
        _ method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws

    func setTokens(access: String, refresh: String?) throws
    func clearTokens() throws
    func currentAccessToken() -> String?
}

extension TempleHEClientProtocol {
    /// Convenience for unauthenticated GETs.
    func get<Response: Decodable>(_ path: String) async throws -> Response {
        try await request("GET", path: path, body: Optional<EmptyBody>.none, authenticated: true)
    }
}

struct EmptyBody: Encodable {}

enum APIError: Error, Equatable {
    case http(status: Int, body: String)
    case unauthorized
    case decoding(String)
    case transport(String)
    case noResponse
}

actor TempleHEClient: TempleHEClientProtocol {
    // The actor-isolated state is tiny on purpose: Keychain access + a
    // single in-flight refresh task. All HTTP actually happens via
    // URLSession which runs off-actor — the actor just gates the
    // serialization of refresh attempts.

    private let baseURL: URL
    private let session: URLSession
    private let keychain: KeychainStore
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    private var refreshInFlight: Task<String, Error>?

    init(
        baseURL: URL,
        session: URLSession = .shared,
        keychain: KeychainStore = KeychainStore()
    ) {
        self.baseURL = baseURL
        self.session = session
        self.keychain = keychain
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - Token storage

    nonisolated func setTokens(access: String, refresh: String?) throws {
        try keychain.set(access, for: .accessToken)
        try keychain.set(refresh, for: .refreshToken)
    }

    nonisolated func clearTokens() throws {
        try keychain.clearAll()
    }

    nonisolated func currentAccessToken() -> String? {
        keychain.get(.accessToken)
    }

    nonisolated func currentRefreshToken() -> String? {
        keychain.get(.refreshToken)
    }

    // MARK: - Request

    func request<Body: Encodable, Response: Decodable>(
        _ method: String,
        path: String,
        body: Body? = nil,
        authenticated: Bool = true
    ) async throws -> Response {
        let data = try await rawRequest(
            method: method, path: path, body: body, authenticated: authenticated
        )
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIError.decoding("\(error)")
        }
    }

    func request<Body: Encodable>(
        _ method: String,
        path: String,
        body: Body? = nil,
        authenticated: Bool = true
    ) async throws {
        _ = try await rawRequest(
            method: method, path: path, body: body, authenticated: authenticated
        )
    }

    // MARK: - Internals

    private func rawRequest<Body: Encodable>(
        method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws -> Data {
        let url = baseURL.appendingPathComponent(path)
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // X-Client opt-in flips the backend to body-mode refresh tokens.
        req.setValue("ios", forHTTPHeaderField: "X-Client")
        if authenticated, let access = currentAccessToken() {
            req.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization")
        }
        if let body = body {
            req.httpBody = try encoder.encode(body)
        }

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.noResponse
        }

        // 401 on an authenticated request triggers a single refresh
        // attempt, then a single retry. If the refresh itself 401s
        // we bubble up and the caller pushes the user back to login.
        if http.statusCode == 401 && authenticated {
            do {
                _ = try await ensureFreshAccessToken()
            } catch {
                throw APIError.unauthorized
            }
            // Retry once with the new token.
            var retry = req
            if let access = currentAccessToken() {
                retry.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization")
            }
            let (retryData, retryResp) = try await session.data(for: retry)
            guard let retryHttp = retryResp as? HTTPURLResponse else {
                throw APIError.noResponse
            }
            if retryHttp.statusCode == 401 {
                throw APIError.unauthorized
            }
            if !(200...299).contains(retryHttp.statusCode) {
                throw APIError.http(
                    status: retryHttp.statusCode,
                    body: String(data: retryData, encoding: .utf8) ?? ""
                )
            }
            return retryData
        }

        if !(200...299).contains(http.statusCode) {
            throw APIError.http(
                status: http.statusCode,
                body: String(data: data, encoding: .utf8) ?? ""
            )
        }
        return data
    }

    /// Serialize concurrent 401-refresh attempts. If two requests land
    /// 401 at the same time, only one refresh actually fires; the other
    /// awaits the same Task and gets the same rotated token.
    private func ensureFreshAccessToken() async throws -> String {
        if let existing = refreshInFlight {
            return try await existing.value
        }
        let task = Task<String, Error> { [weak self] in
            try await self?.performRefresh() ?? ""
        }
        refreshInFlight = task
        defer { refreshInFlight = nil }
        return try await task.value
    }

    private func performRefresh() async throws -> String {
        guard let refresh = currentRefreshToken() else {
            throw APIError.unauthorized
        }
        let url = baseURL.appendingPathComponent(Endpoint.authRefresh)
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("ios", forHTTPHeaderField: "X-Client")
        req.httpBody = try encoder.encode(RefreshRequest(refresh_token: refresh))

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw APIError.unauthorized
        }
        let token = try decoder.decode(TokenResponse.self, from: data)
        try keychain.set(token.access_token, for: .accessToken)
        if let new = token.refresh_token {
            try keychain.set(new, for: .refreshToken)
        }
        return token.access_token
    }
}
