// ABOUTME: KeychainStore unit tests — round-trip + deletion + clearAll.
// ABOUTME: Tests use a unique service id so they can't collide with other apps' Keychain rows.

import XCTest
@testable import TempleHEAppraiser

final class KeychainStoreTests: XCTestCase {
    /// Per-test unique service so parallel test runs and replays don't
    /// interleave through the same Keychain rows.
    private var store: KeychainStore!
    private var service: String!

    override func setUpWithError() throws {
        service = "com.templehe.appraiser.tests-\(UUID().uuidString)"
        store = KeychainStore(service: service)
        try store.clearAll()
    }

    override func tearDownWithError() throws {
        try? store.clearAll()
        store = nil
        service = nil
    }

    func testRoundTripAccessToken() throws {
        try store.set("access-abc", for: .accessToken)
        XCTAssertEqual(store.get(.accessToken), "access-abc")
    }

    func testRoundTripRefreshToken() throws {
        try store.set("refresh-xyz", for: .refreshToken)
        XCTAssertEqual(store.get(.refreshToken), "refresh-xyz")
    }

    func testOverwriteReplacesValue() throws {
        try store.set("first", for: .accessToken)
        try store.set("second", for: .accessToken)
        XCTAssertEqual(store.get(.accessToken), "second")
    }

    func testSetNilDeletes() throws {
        try store.set("present", for: .accessToken)
        try store.set(nil, for: .accessToken)
        XCTAssertNil(store.get(.accessToken))
    }

    func testClearAllRemovesEverything() throws {
        try store.set("a", for: .accessToken)
        try store.set("r", for: .refreshToken)
        try store.clearAll()
        XCTAssertNil(store.get(.accessToken))
        XCTAssertNil(store.get(.refreshToken))
    }

    func testGetMissingKeyReturnsNil() {
        XCTAssertNil(store.get(.accessToken))
    }
}
