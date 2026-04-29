// ABOUTME: Face ID / Touch ID gate that unlocks the cached session in Keychain.
// ABOUTME: Falls back to LoginView if biometrics fail or aren't enrolled.

import LocalAuthentication
import SwiftUI

/// Optional biometric gate — when biometrics are available the app
/// can launch into a "tap to unlock" screen rather than re-presenting
/// a full login. Sprint 1 does NOT auto-trigger this; it's available
/// for views that explicitly need to re-confirm identity (e.g., a
/// future "view recovery codes" screen). The biometric check itself
/// never sends anything to the backend — it's purely a local gate
/// that allows reading from Keychain.
struct BiometricLoginView: View {
    @EnvironmentObject var auth: AuthState
    @State private var status: Status = .idle

    enum Status {
        case idle
        case authenticating
        case failed(String)
    }

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "faceid")
                .font(.system(size: 64))
                .foregroundStyle(.secondary)
            Text("Unlock TempleHE Appraiser")
                .font(.title2)
            Button {
                Task { await authenticate() }
            } label: {
                Text("Use Face ID")
                    .frame(maxWidth: .infinity)
                    .padding()
            }
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier("biometric-unlock")

            if case .failed(let message) = status {
                Text(message)
                    .foregroundStyle(.red)
                    .font(.callout)
                    .accessibilityIdentifier("biometric-error")
            }

            Button("Sign in with password") {
                auth.forceLogout()
            }
            .accessibilityIdentifier("biometric-fallback")
        }
        .padding()
    }

    private func authenticate() async {
        status = .authenticating
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(
            .deviceOwnerAuthenticationWithBiometrics, error: &error
        ) else {
            status = .failed(error?.localizedDescription ?? "Biometrics unavailable.")
            return
        }
        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: "Unlock your TempleHE session"
            )
            if success {
                // Biometric pass means the cached session is trusted;
                // AuthState.phase already reflects that — nothing more
                // to do here than dismiss this view (caller's job).
                status = .idle
            } else {
                status = .failed("Authentication failed.")
            }
        } catch {
            status = .failed(error.localizedDescription)
        }
    }
}
