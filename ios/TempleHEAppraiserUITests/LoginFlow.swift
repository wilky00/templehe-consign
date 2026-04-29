// ABOUTME: XCUITest — start at LoginView, verify form is interactive + accessibility ids match.
// ABOUTME: A real login round-trip needs a live backend; Sprint 1 ships the screen smoke only.

import XCTest

final class LoginFlow: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testLaunchShowsLoginScreen() throws {
        let app = XCUIApplication()
        app.launch()

        let loginScreen = app.otherElements["screen-login"]
        XCTAssertTrue(loginScreen.waitForExistence(timeout: 5))
    }

    func testLoginFormHasExpectedFields() throws {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.textFields["login-email"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.secureTextFields["login-password"].exists)
        XCTAssertTrue(app.buttons["login-submit"].exists)
    }

    func testSubmitDisabledWhenFieldsEmpty() throws {
        let app = XCUIApplication()
        app.launch()

        let submit = app.buttons["login-submit"]
        XCTAssertTrue(submit.waitForExistence(timeout: 5))
        XCTAssertFalse(submit.isEnabled)
    }
}
