// ABOUTME: Five-state visual badge that reflects an appraisal submission's sync status.
// ABOUTME: Used on AssignmentCard in DashboardView and in the Drafts section.

import SwiftUI

/// The five sync states that an appraisal submission can be in.
enum SyncStatus: String {
    case draft          = "draft"
    case pendingSync    = "pending_sync"
    case uploading      = "uploading"
    case uploaded       = "uploaded"
    case syncFailed     = "sync_failed"
}

/// Compact badge rendered on each appraisal card.
struct SyncStatusBadge: View {
    let status: SyncStatus

    var body: some View {
        HStack(spacing: 4) {
            icon
            Text(label)
                .font(.caption2.weight(.semibold))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.15))
        .foregroundStyle(color)
        .clipShape(Capsule())
        .accessibilityLabel(accessibilityLabel)
    }

    // MARK: - Private

    private var icon: some View {
        Group {
            switch status {
            case .draft:
                Image(systemName: "pencil.circle")
            case .pendingSync:
                Image(systemName: "wifi.slash")
            case .uploading:
                ProgressView()
                    .scaleEffect(0.6)
                    .tint(color)
            case .uploaded:
                Image(systemName: "checkmark.circle.fill")
            case .syncFailed:
                Image(systemName: "exclamationmark.circle.fill")
            }
        }
        .imageScale(.small)
    }

    private var label: String {
        switch status {
        case .draft:        return "Not yet submitted"
        case .pendingSync:  return "Waiting for connection"
        case .uploading:    return "Uploading..."
        case .uploaded:     return "Received by TempleHE"
        case .syncFailed:   return "Upload failed — tap to retry"
        }
    }

    private var color: Color {
        switch status {
        case .draft:        return .secondary
        case .pendingSync:  return .yellow
        case .uploading:    return .blue
        case .uploaded:     return .green
        case .syncFailed:   return .red
        }
    }

    private var accessibilityLabel: String {
        switch status {
        case .draft:        return "Draft — not yet submitted"
        case .pendingSync:  return "Waiting for connection to upload"
        case .uploading:    return "Uploading appraisal"
        case .uploaded:     return "Received by TempleHE"
        case .syncFailed:   return "Upload failed, tap to retry"
        }
    }
}

/// Full-width banner shown at the top of Dashboard when pending uploads exist.
struct PendingSyncBanner: View {
    let pendingCount: Int

    var body: some View {
        if pendingCount > 0 {
            HStack(spacing: 8) {
                Image(systemName: "arrow.triangle.2.circlepath")
                Text("\(pendingCount) appraisal\(pendingCount == 1 ? "" : "s") pending upload")
                    .font(.subheadline.weight(.medium))
                Spacer()
            }
            .padding()
            .background(Color.yellow.opacity(0.15))
            .foregroundStyle(.yellow)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(pendingCount) appraisal\(pendingCount == 1 ? "" : "s") pending upload")
        }
    }
}
