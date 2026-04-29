// ABOUTME: Six-digit TOTP entry + recovery-code fallback. Used after 2FA-enabled login.
// ABOUTME: AuthState handles the actual /2fa/verify and /2fa/recovery calls.

import SwiftUI

struct TwoFactorView: View {
    @EnvironmentObject var auth: AuthState
    @State private var code: String = ""
    @State private var recoveryCode: String = ""
    @State private var showingRecovery: Bool = false
    @State private var isSubmitting: Bool = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Enter the 6-digit code from your authenticator app.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }

                if showingRecovery {
                    Section("Recovery code") {
                        TextField("XXXXXXXX", text: $recoveryCode)
                            .textContentType(.oneTimeCode)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .accessibilityIdentifier("2fa-recovery")
                    }
                } else {
                    Section("Authentication code") {
                        TextField("123456", text: $code)
                            .textContentType(.oneTimeCode)
                            .keyboardType(.numberPad)
                            .accessibilityIdentifier("2fa-code")
                    }
                }

                if let error = auth.lastError {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.callout)
                            .accessibilityIdentifier("2fa-error")
                    }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        if isSubmitting {
                            ProgressView()
                        } else {
                            Text(showingRecovery ? "Use Recovery Code" : "Verify")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .disabled(isSubmitting || !canSubmit)
                    .accessibilityIdentifier("2fa-submit")

                    Button(showingRecovery ? "Use authenticator code" : "Use a recovery code") {
                        showingRecovery.toggle()
                        auth.lastError = nil
                    }
                    .accessibilityIdentifier("2fa-toggle-recovery")
                }
            }
            .navigationTitle("Two-Factor Auth")
        }
    }

    private var canSubmit: Bool {
        if showingRecovery {
            return !recoveryCode.trimmingCharacters(in: .whitespaces).isEmpty
        }
        return code.count == 6 && code.allSatisfy(\.isNumber)
    }

    private func submit() async {
        isSubmitting = true
        defer { isSubmitting = false }
        if showingRecovery {
            await auth.recover2FA(recoveryCode: recoveryCode)
        } else {
            await auth.verify2FA(code: code)
        }
    }
}
