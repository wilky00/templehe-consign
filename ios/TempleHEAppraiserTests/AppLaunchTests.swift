// ABOUTME: Sprint 0 smoke tests — RootView renders the four placeholder tabs.
// ABOUTME: Real auth/session/networking tests land in Sprint 1.

import XCTest
@testable import TempleHEAppraiser

final class AppLaunchTests: XCTestCase {
    func testRootViewIsConstructable() {
        // The view is intentionally trivial in Sprint 0 — this test exists
        // so the test target wires up cleanly + future tests have a home.
        let view = RootView()
        _ = view.body
    }
}
