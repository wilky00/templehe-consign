// ABOUTME: TempleHEClient tests against a mocked URLSession.
// ABOUTME: Covers happy path, X-Client header, 401-refresh-and-retry, parallel-401 serialization.

import XCTest
@testable import TempleHEAppraiser

final class TempleHEClientTests: XCTestCase {
    private var session: URLSession!
    private var keychain: KeychainStore!
    private var client: TempleHEClient!

    override func setUpWithError() throws {
        // Per-test config so MockURLProtocol's static handlers reset.
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        session = URLSession(configuration: config)

        keychain = KeychainStore(service: "tests-\(UUID().uuidString)")
        try keychain.clearAll()

        client = TempleHEClient(
            baseURL: URL(string: "https://api.example.com")!,
            session: session,
            keychain: keychain
        )
        MockURLProtocol.handlers = []
    }

    override func tearDownWithError() throws {
        try? keychain.clearAll()
        MockURLProtocol.handlers = []
    }

    // MARK: - X-Client header

    func testEveryRequestSendsXClientIosHeader() async throws {
        var capturedHeaders: [String: String] = [:]
        MockURLProtocol.handlers.append { req in
            capturedHeaders = req.allHTTPHeaderFields ?? [:]
            return MockURLProtocol.Response(
                status: 200,
                body: try! JSONSerialization.data(withJSONObject: ["status": "ok"])
            )
        }
        struct Out: Decodable { let status: String }
        let _: Out = try await client.request(
            "GET",
            path: "/api/v1/health",
            body: Optional<EmptyBody>.none,
            authenticated: false
        )
        XCTAssertEqual(capturedHeaders["X-Client"], "ios")
    }

    // MARK: - Auth header threading

    func testAuthenticatedRequestThreadsBearer() async throws {
        try keychain.set("access-1", for: .accessToken)
        var capturedAuth: String?
        MockURLProtocol.handlers.append { req in
            capturedAuth = req.value(forHTTPHeaderField: "Authorization")
            return MockURLProtocol.Response(status: 200, body: Data("{}".utf8))
        }
        struct Out: Decodable {}
        let _: Out = try await client.request(
            "GET",
            path: "/api/v1/me",
            body: Optional<EmptyBody>.none,
            authenticated: true
        )
        XCTAssertEqual(capturedAuth, "Bearer access-1")
    }

    // MARK: - 401 refresh + retry

    func testHttp401TriggersRefreshAndRetry() async throws {
        try keychain.set("expired", for: .accessToken)
        try keychain.set("good-refresh", for: .refreshToken)

        // Sequence: 1) GET /me → 401. 2) POST /auth/refresh → 200 + new tokens. 3) retry GET /me → 200.
        MockURLProtocol.handlers = [
            { _ in MockURLProtocol.Response(status: 401, body: Data("{}".utf8)) },
            { _ in
                let body = try! JSONEncoder().encode(
                    ["access_token": "fresh", "refresh_token": "rotated"]
                )
                return MockURLProtocol.Response(status: 200, body: body)
            },
            { req in
                XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer fresh")
                return MockURLProtocol.Response(
                    status: 200,
                    body: try! JSONSerialization.data(withJSONObject: ["ok": true])
                )
            },
        ]

        struct Out: Decodable { let ok: Bool }
        let result: Out = try await client.request(
            "GET",
            path: "/api/v1/me",
            body: Optional<EmptyBody>.none,
            authenticated: true
        )
        XCTAssertTrue(result.ok)
        XCTAssertEqual(client.currentAccessToken(), "fresh")
    }

    func testRefreshFailureBubblesAsUnauthorized() async throws {
        try keychain.set("expired", for: .accessToken)
        try keychain.set("bad-refresh", for: .refreshToken)

        MockURLProtocol.handlers = [
            { _ in MockURLProtocol.Response(status: 401, body: Data("{}".utf8)) },
            { _ in MockURLProtocol.Response(status: 401, body: Data("{}".utf8)) },
        ]

        do {
            struct Out: Decodable {}
            let _: Out = try await client.request(
                "GET",
                path: "/api/v1/me",
                body: Optional<EmptyBody>.none,
                authenticated: true
            )
            XCTFail("expected unauthorized")
        } catch APIError.unauthorized {
            // expected
        }
    }
}

// MARK: - MockURLProtocol

/// Stack-of-handlers protocol — each test sets up `handlers` in the
/// order requests should fire, and the protocol pops one off per
/// request. Lets us script multi-step flows like 401 → refresh → retry.
final class MockURLProtocol: URLProtocol {
    struct Response {
        let status: Int
        let body: Data
        var headers: [String: String] = ["Content-Type": "application/json"]
    }

    static var handlers: [(URLRequest) -> Response] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard !MockURLProtocol.handlers.isEmpty else {
            client?.urlProtocol(
                self,
                didFailWithError: NSError(domain: "MockURLProtocol", code: -1)
            )
            return
        }
        let handler = MockURLProtocol.handlers.removeFirst()
        let resp = handler(request)
        let httpResp = HTTPURLResponse(
            url: request.url!,
            statusCode: resp.status,
            httpVersion: "HTTP/1.1",
            headerFields: resp.headers
        )!
        client?.urlProtocol(self, didReceive: httpResp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: resp.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
