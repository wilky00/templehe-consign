// ABOUTME: First-launch XCUITest — app launches and the four tabs are visible.
// ABOUTME: Phase 5 Sprint 0 sanity check; richer flows land alongside their epics.

import XCTest

final class SmokeTest: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testAppLaunchesAndShowsTabBar() throws {
        let app = XCUIApplication()
        app.launch()

        // Each tab in RootView pins an `.accessibilityIdentifier("tab-<title>")`.
        // The XCUITest queries for those identifiers so the assertion isn't
        // tied to localization or display text.
        let dashboardTab = app.otherElements["tab-Dashboard"]
        XCTAssertTrue(dashboardTab.waitForExistence(timeout: 5))
        XCTAssertTrue(app.otherElements["tab-New Appraisal"].exists)
        XCTAssertTrue(app.otherElements["tab-Calendar"].exists)
        XCTAssertTrue(app.otherElements["tab-Profile"].exists)
    }
}
