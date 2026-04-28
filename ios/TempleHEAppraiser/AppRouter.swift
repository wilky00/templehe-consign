// ABOUTME: Top-level state-machine view — gates the tab bar behind auth state.
// ABOUTME: LoggedOut → LoginView; TwoFactorPending → TwoFactorView; LoggedIn → RootView.

import SwiftUI

struct AppRouter: View {
    @EnvironmentObject var auth: AuthState

    var body: some View {
        switch auth.phase {
        case .loggedOut:
            LoginView()
                .accessibilityIdentifier("screen-login")
        case .twoFactorPending:
            TwoFactorView()
                .accessibilityIdentifier("screen-2fa")
        case .loggedIn:
            RootView()
                .accessibilityIdentifier("screen-root")
        }
    }
}
