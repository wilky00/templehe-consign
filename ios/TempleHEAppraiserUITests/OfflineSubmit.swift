// ABOUTME: XCUITest — offline submit → pending_sync → DebugForceSync → uploaded flow.
// ABOUTME: Uses XCTEST_SIMULATE_OFFLINE launch env + the force-sync-button debug control.

import XCTest

final class OfflineSubmit: XCTestCase {

    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["XCTEST_RUNNING"] = "1"
    }

    override func tearDownWithError() throws {
        app = nil
    }

    /// Full offline→online sync flow:
    /// 1. Launch in simulated-offline mode.
    /// 2. Open the first assignment card + tap Submit.
    /// 3. Verify card shows "Waiting for connection".
    /// 4. Re-launch online and tap DebugForceSync.
    /// 5. Verify card shows "Received by TempleHE".
    func testOfflineSubmitThenSyncUploads() throws {
        // Launch offline.
        app.launchEnvironment["XCTEST_SIMULATE_OFFLINE"] = "1"
        app.launch()

        let dashboard = app.otherElements["dashboard-container"]
        XCTAssertTrue(dashboard.waitForExistence(timeout: 15))

        let firstCard = app.otherElements.matching(identifier: "assignment-card").firstMatch
        XCTAssertTrue(firstCard.waitForExistence(timeout: 10))
        firstCard.tap()

        // Attempt to submit. If required fields or photos are missing the button
        // may be disabled — this test requires a pre-seeded draft with all
        // required slots already filled.
        let submitButton = app.buttons["submit-appraisal-button"]
        if submitButton.waitForExistence(timeout: 5), submitButton.isEnabled {
            submitButton.tap()
            let confirmButton = app.buttons["submit-confirm-button"]
            if confirmButton.waitForExistence(timeout: 5) {
                confirmButton.tap()
            }
        }

        // Return to dashboard.
        let backButton = app.navigationBars.buttons.firstMatch
        if backButton.waitForExistence(timeout: 3) {
            backButton.tap()
        }

        // Card must show "Waiting for connection" (pending_sync).
        let pendingBadge = app.staticTexts["Waiting for connection"]
        XCTAssertTrue(pendingBadge.waitForExistence(timeout: 10))

        // Re-launch online.
        app.terminate()
        app.launchEnvironment.removeValue(forKey: "XCTEST_SIMULATE_OFFLINE")
        app.launch()

        let dashboardOnline = app.otherElements["dashboard-container"]
        XCTAssertTrue(dashboardOnline.waitForExistence(timeout: 15))

        // DebugForceSync is only present in DEBUG builds.
        let forceSyncButton = app.buttons["force-sync-button"]
        guard forceSyncButton.waitForExistence(timeout: 5) else {
            throw XCTSkip("force-sync-button not present — ensure DEBUG build")
        }
        forceSyncButton.tap()

        // Card should transition to "Received by TempleHE".
        let uploadedBadge = app.staticTexts["Received by TempleHE"]
        XCTAssertTrue(uploadedBadge.waitForExistence(timeout: 30))
    }

    func testPendingSyncBannerAppearsWhileOffline() throws {
        app.launchEnvironment["XCTEST_SIMULATE_OFFLINE"] = "1"
        app.launchEnvironment["XCTEST_SEED_PENDING_SYNC"] = "1"
        app.launch()

        let dashboard = app.otherElements["dashboard-container"]
        XCTAssertTrue(dashboard.waitForExistence(timeout: 15))

        // The pending-sync banner should be visible when there are queued items.
        let banner = app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'pending upload'")).firstMatch
        XCTAssertTrue(banner.waitForExistence(timeout: 5))
    }

    func testNoSyncBannerWhenAllUploaded() throws {
        // Default launch with no offline flag — all records should be uploaded.
        app.launch()

        let dashboard = app.otherElements["dashboard-container"]
        XCTAssertTrue(dashboard.waitForExistence(timeout: 15))

        // Banner must not appear when there are no pending items.
        let banner = app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'pending upload'")).firstMatch
        XCTAssertFalse(banner.waitForExistence(timeout: 3))
    }
}
