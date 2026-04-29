// ABOUTME: UIApplicationDelegate for APNs registration callbacks (SwiftUI bridge).
// ABOUTME: Receives the device token + permission failures; PushRegistrar handles dispatch.

import UIKit

/// SwiftUI's `App` lifecycle doesn't expose the APNs callbacks
/// directly, so we keep a thin UIApplicationDelegate and bridge it via
/// `@UIApplicationDelegateAdaptor` in `App.swift`. The delegate is
/// intentionally close to empty — actual logic (POST to /me/device-token)
/// lives in `PushRegistrar` so it's testable in isolation.
final class AppDelegate: NSObject, UIApplicationDelegate {

    /// Notified asynchronously by `PushRegistrar` so it can wait on the
    /// raw token without polling.
    static let didReceiveDeviceTokenNotification = Notification.Name(
        "templehe.didReceiveDeviceToken"
    )

    /// Notified when the OS rejects the registration (e.g. user denied
    /// push permission, or running on a sim without push capability).
    static let didFailToRegisterNotification = Notification.Name(
        "templehe.didFailToRegisterPush"
    )

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        // APNs hands us raw bytes; the standard practice is to format
        // as a lowercase hex string. The backend stores this verbatim.
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        NotificationCenter.default.post(
            name: AppDelegate.didReceiveDeviceTokenNotification,
            object: nil,
            userInfo: ["token": token]
        )
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        NotificationCenter.default.post(
            name: AppDelegate.didFailToRegisterNotification,
            object: nil,
            userInfo: ["error": error.localizedDescription]
        )
    }
}
