// ABOUTME: SwiftUI app entry point — wires AppDelegate, API client, AuthState, AppRouter.
// ABOUTME: Sprint 1 puts auth + push registration behind a single environment-injected client.

import SwiftUI

@main
struct TempleHEAppraiserApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    /// One TempleHEClient + AuthState for the whole app, plumbed into
    /// the SwiftUI environment. Tests construct their own pair against
    /// a mock URLSession.
    @StateObject private var auth: AuthState = {
        let baseURL = URL(string: Self.apiBaseURL)!
        let client = TempleHEClient(baseURL: baseURL)
        return AuthState(client: client)
    }()

    var body: some Scene {
        WindowGroup {
            AppRouter()
                .environmentObject(auth)
        }
    }

    /// Resolved at compile-time; staging URL by default. Production
    /// builds override via Xcode build settings (Sprint 7 sets up the
    /// release scheme). Hardcoded for Sprint 1.
    private static var apiBaseURL: String {
        #if DEBUG
        return "https://api.templehe-staging.fly.dev"
        #else
        return "https://api.templehe.com"
        #endif
    }
}
