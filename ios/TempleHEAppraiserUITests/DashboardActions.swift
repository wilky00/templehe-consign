// ABOUTME: XCUITest — Dashboard card interactions: call, navigate, copy address.
// ABOUTME: Phase 5 Sprint 2 gate; exercises AssignmentCard action buttons.

import XCTest

final class DashboardActions: XCTestCase {

    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["XCTEST_RUNNING"] = "1"
        app.launch()
    }

    override func tearDownWithError() throws {
        app = nil
    }

    func testDashboardRendersCards() throws {
        _waitForDashboard()

        let cards = app.otherElements.matching(identifier: "assignment-card")
        XCTAssertTrue(cards.firstMatch.waitForExistence(timeout: 10))
    }

    func testTapCardOpenDetail() throws {
        _waitForDashboard()

        let firstCard = app.otherElements.matching(identifier: "assignment-card").firstMatch
        XCTAssertTrue(firstCard.waitForExistence(timeout: 10))
        firstCard.tap()

        let formSection = app.otherElements["form-section-site-asset"]
        XCTAssertTrue(formSection.waitForExistence(timeout: 10))
    }

    func testNavigateButtonPresent() throws {
        _waitForDashboard()

        let firstCard = app.otherElements.matching(identifier: "assignment-card").firstMatch
        XCTAssertTrue(firstCard.waitForExistence(timeout: 10))
        firstCard.tap()

        let navButton = app.buttons["navigate-button"]
        XCTAssertTrue(navButton.waitForExistence(timeout: 5))
    }

    func testCopyAddressButtonPresent() throws {
        _waitForDashboard()

        let firstCard = app.otherElements.matching(identifier: "assignment-card").firstMatch
        XCTAssertTrue(firstCard.waitForExistence(timeout: 10))
        firstCard.tap()

        let copyButton = app.buttons["copy-address-button"]
        XCTAssertTrue(copyButton.waitForExistence(timeout: 5))
    }

    func testCallRepButtonPresent() throws {
        _waitForDashboard()

        let firstCard = app.otherElements.matching(identifier: "assignment-card").firstMatch
        XCTAssertTrue(firstCard.waitForExistence(timeout: 10))
        firstCard.tap()

        let callRepButton = app.buttons["call-rep-button"]
        XCTAssertTrue(callRepButton.waitForExistence(timeout: 5))
    }

    // MARK: - Private

    private func _waitForDashboard() {
        let dashboard = app.otherElements["dashboard-container"]
        _ = dashboard.waitForExistence(timeout: 15)
    }
}
