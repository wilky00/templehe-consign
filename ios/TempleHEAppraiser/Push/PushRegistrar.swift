// ABOUTME: APNs registration — request authorization, register for remote notifications,
// ABOUTME: forward the device token to /me/device-token. Best-effort: a denied permission
// ABOUTME: is not a login blocker.

import Foundation
import UIKit
import UserNotifications

@MainActor
final class PushRegistrar {
    private let client: TempleHEClient

    init(client: TempleHEClient) {
        self.client = client
    }

    /// Kick off the full APNs registration flow:
    ///   1. Ask the user for notification permission.
    ///   2. If granted, register with APNs (the OS calls AppDelegate
    ///      callbacks asynchronously).
    ///   3. AppDelegate posts a Notification with the hex token; we
    ///      observe it and POST to /me/device-token.
    /// Permission denied or registration failure → log + skip; the
    /// app stays usable, just without push.
    func register() async {
        let center = UNUserNotificationCenter.current()
        let granted = (try? await center.requestAuthorization(
            options: [.alert, .badge, .sound]
        )) ?? false
        guard granted else {
            return
        }

        // Subscribe to the AppDelegate's posted token before kicking
        // off registration. The race is fine: if APNs answers before
        // we subscribe (unlikely on a real device), the next call to
        // register() will pick up.
        Task { await observeAndForwardToken() }

        await UIApplication.shared.registerForRemoteNotifications()
    }

    private func observeAndForwardToken() async {
        let stream = NotificationCenter.default.notifications(
            named: AppDelegate.didReceiveDeviceTokenNotification
        )
        for await notification in stream {
            guard let token = notification.userInfo?["token"] as? String else { continue }
            await forwardTokenToBackend(token)
            return  // single registration per call
        }
    }

    private func forwardTokenToBackend(_ token: String) async {
        let environment = currentEnvironment()
        do {
            try await client.request(
                "POST",
                path: Endpoint.meDeviceToken,
                body: DeviceTokenRegisterRequest(
                    platform: "ios",
                    token: token,
                    environment: environment
                ),
                authenticated: true
            )
        } catch {
            // Silent — push being absent is not a login blocker. A
            // future enhancement could surface a banner; for Sprint 1
            // we just keep the app usable.
        }
    }

    /// Distinguishes APNs sandbox (debug builds, dev provisioning) from
    /// production. The backend dispatches to the matching APNs endpoint
    /// based on this column.
    private func currentEnvironment() -> String {
        #if DEBUG
        return "development"
        #else
        return "production"
        #endif
    }
}
