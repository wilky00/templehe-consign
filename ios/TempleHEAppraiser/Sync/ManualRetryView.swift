// ABOUTME: Sheet shown when the appraiser taps a sync-failed appraisal card.
// ABOUTME: Displays the error detail and offers a manual retry button.

import SwiftUI

struct ManualRetryView: View {
    let referenceNumber: String
    let errorDetail: String
    let onRetry: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(.red)
                    .accessibilityHidden(true)

                VStack(spacing: 8) {
                    Text("Upload Failed")
                        .font(.title2.bold())
                    Text(referenceNumber)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                GroupBox {
                    Text(errorDetail)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                Spacer()

                Button {
                    onRetry()
                } label: {
                    Label("Retry Upload", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("retry-upload-button")
            }
            .padding()
            .navigationTitle("Sync Failed")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Dismiss", action: onDismiss)
                        .accessibilityIdentifier("retry-dismiss-button")
                }
            }
        }
    }
}
