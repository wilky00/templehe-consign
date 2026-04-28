// ABOUTME: AuthState transitions — login → 2FA-pending → loggedIn; recovery flow.
// ABOUTME: Mocked URLSession + per-test Keychain so state stays isolated.

import XCTest
@testable import TempleHEAppraiser

@MainActor
final class AuthFlowTests: XCTestCase {
    private var session: URLSession!
    private var keychain: KeychainStore!
    private var client: TempleHEClient!
    private var auth: AuthState!

    override func setUpWithError() throws {
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
        auth = AuthState(client: client)
        MockURLProtocol.handlers = []
    }

    override func tearDownWithError() throws {
        try? keychain.clearAll()
        MockURLProtocol.handlers = []
    }

    func testInitialPhaseIsLoggedOut() {
        XCTAssertEqual(auth.phase, .loggedOut)
    }

    func testInitialPhaseIsLoggedInWhenTokenExists() throws {
        try keychain.set("preloaded", for: .accessToken)
        let fresh = AuthState(client: client)
        XCTAssertEqual(fresh.phase, .loggedIn)
    }

    func testHappyPathLoginFlipsToLoggedIn() async throws {
        MockURLProtocol.handlers.append { _ in
            let body = try! JSONEncoder().encode(
                ["access_token": "a", "refresh_token": "r"]
            )
            return MockURLProtocol.Response(status: 200, body: body)
        }
        await auth.login(email: "user@example.com", password: "pw")
        XCTAssertEqual(auth.phase, .loggedIn)
        XCTAssertNil(auth.lastError)
        XCTAssertEqual(client.currentAccessToken(), "a")
    }

    func test2FAPendingTransitionsThenVerifies() async throws {
        // Step 1: login → requires_2fa
        MockURLProtocol.handlers.append { _ in
            let body = try! JSONSerialization.data(withJSONObject: [
                "requires_2fa": true,
                "partial_token": "PARTIAL",
            ])
            return MockURLProtocol.Response(status: 200, body: body)
        }
        await auth.login(email: "user@example.com", password: "pw")
        XCTAssertEqual(auth.phase, .twoFactorPending(partialToken: "PARTIAL"))

        // Step 2: verify TOTP → loggedIn with rotated tokens
        MockURLProtocol.handlers.append { _ in
            let body = try! JSONEncoder().encode(
                ["access_token": "post-2fa", "refresh_token": "rfr"]
            )
            return MockURLProtocol.Response(status: 200, body: body)
        }
        await auth.verify2FA(code: "123456")
        XCTAssertEqual(auth.phase, .loggedIn)
        XCTAssertEqual(client.currentAccessToken(), "post-2fa")
    }

    func test2FARecoveryPathTransitionsToLoggedIn() async throws {
        MockURLProtocol.handlers.append { _ in
            let body = try! JSONSerialization.data(withJSONObject: [
                "requires_2fa": true,
                "partial_token": "PARTIAL",
            ])
            return MockURLProtocol.Response(status: 200, body: body)
        }
        await auth.login(email: "user@example.com", password: "pw")

        MockURLProtocol.handlers.append { _ in
            let body = try! JSONEncoder().encode(
                ["access_token": "rec", "refresh_token": "rec-r"]
            )
            return MockURLProtocol.Response(status: 200, body: body)
        }
        await auth.recover2FA(recoveryCode: "ABCD1234")
        XCTAssertEqual(auth.phase, .loggedIn)
    }

    func testWrongPasswordSurfacesError() async throws {
        MockURLProtocol.handlers.append { _ in
            MockURLProtocol.Response(
                status: 401,
                body: Data("{\"detail\":\"Incorrect email or password.\"}".utf8)
            )
        }
        await auth.login(email: "user@example.com", password: "bad")
        XCTAssertEqual(auth.phase, .loggedOut)
        XCTAssertEqual(auth.lastError, "Incorrect email or password.")
    }

    func testForceLogoutClearsTokensAndPhase() async throws {
        try client.setTokens(access: "a", refresh: "r")
        auth = AuthState(client: client)
        XCTAssertEqual(auth.phase, .loggedIn)
        auth.forceLogout()
        XCTAssertEqual(auth.phase, .loggedOut)
        XCTAssertNil(client.currentAccessToken())
    }
}
