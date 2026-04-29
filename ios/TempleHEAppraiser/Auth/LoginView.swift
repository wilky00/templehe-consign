// ABOUTME: Email + password login screen. Sprint 1 ships this; Google sign-in is deferred (D2).
// ABOUTME: Errors surface via AuthState.lastError; loading state guards the submit button.

import SwiftUI

struct LoginView: View {
    @EnvironmentObject var auth: AuthState
    @State private var email: String = ""
    @State private var password: String = ""
    @State private var isSubmitting: Bool = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .accessibilityIdentifier("login-email")
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                        .accessibilityIdentifier("login-password")
                }

                if let error = auth.lastError {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.callout)
                            .accessibilityIdentifier("login-error")
                    }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        if isSubmitting {
                            ProgressView()
                        } else {
                            Text("Log In")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .disabled(!canSubmit || isSubmitting)
                    .accessibilityIdentifier("login-submit")
                }
            }
            .navigationTitle("TempleHE Appraiser")
        }
    }

    private var canSubmit: Bool {
        !email.trimmingCharacters(in: .whitespaces).isEmpty
            && !password.isEmpty
    }

    private func submit() async {
        isSubmitting = true
        defer { isSubmitting = false }
        await auth.login(email: email, password: password)
    }
}
