// ABOUTME: Debug-only button that bypasses BGTaskScheduler to invoke SyncService directly.
// ABOUTME: Exists solely for XCUITest determinism — BGTaskScheduler doesn't fire reliably in simulator.

#if DEBUG
import SwiftUI

/// A floating button shown on the Dashboard in DEBUG builds that immediately
/// triggers SyncService rather than waiting for BGTaskScheduler.
///
/// XCUITest targets the `force-sync-button` accessibility identifier to drive
/// the offline → upload → uploaded flow deterministically without mocking
/// BGTaskScheduler.
struct DebugForceSyncButton: View {
    @State private var isSyncing = false
    @State private var lastResult: String?

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            if let result = lastResult {
                Text(result)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
            }
            Button {
                Task { await forceSyncNow() }
            } label: {
                Label(
                    isSyncing ? "Syncing..." : "Force Sync",
                    systemImage: isSyncing ? "arrow.triangle.2.circlepath" : "bolt.fill"
                )
                .font(.caption.bold())
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Color.orange)
                .foregroundStyle(.white)
                .clipShape(Capsule())
            }
            .disabled(isSyncing)
            .accessibilityIdentifier("force-sync-button")
        }
    }

    // Placeholder — real implementation calls SyncService.shared.runNow() once
    // SyncService lands in a future sprint. Kept as a stub so the button wires
    // up without the service present.
    private func forceSyncNow() async {
        isSyncing = true
        defer { isSyncing = false }
        try? await Task.sleep(for: .seconds(1))
        lastResult = "Sync triggered at \(Date().formatted(.dateTime.hour().minute().second()))"
    }
}
#endif
