// ABOUTME: Opens a destination address in Apple Maps or falls back to Google Maps.
// ABOUTME: Prefers Apple Maps URL scheme; Google Maps universal URL is the fallback.

import Foundation
import UIKit

enum MapsLauncher {
    /// Open turn-by-turn navigation to ``address`` using Apple Maps if available,
    /// Google Maps universal URL otherwise. Call from the main actor (UIApplication
    /// must be touched on the main thread).
    @MainActor
    static func navigate(to address: String) {
        guard !address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let encoded = address.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? address

        // Apple Maps — direct URL scheme, opens the built-in Maps app.
        if let appleURL = URL(string: "maps://?daddr=\(encoded)"),
           UIApplication.shared.canOpenURL(appleURL) {
            UIApplication.shared.open(appleURL)
            return
        }

        // Google Maps universal URL — works even when the Google Maps app is not
        // installed (opens in Safari → redirects appropriately).
        if let googleURL = URL(string: "https://www.google.com/maps/dir/?api=1&destination=\(encoded)") {
            UIApplication.shared.open(googleURL)
        }
    }
}
