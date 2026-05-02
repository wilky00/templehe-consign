// ABOUTME: Phase 5 Sprint 4 — live overall score display, recalculated on every component change.
// ABOUTME: Shows score value, band label, and a warning when weights are not normalized to 100.

import SwiftUI

struct ScoringDisplay: View {
    let score: Double
    let band: String
    let weightNormalized: Bool

    var body: some View {
        Section {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Overall Score")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text(band.capitalized)
                        .font(.headline)
                        .foregroundStyle(bandColor)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Overall score: \(String(format: "%.2f", score)) — \(band)")

                Spacer()

                Text(String(format: "%.2f / 5.00", score))
                    .font(.title2.bold())
                    .foregroundStyle(bandColor)
                    .accessibilityHidden(true)
            }

            if weightNormalized {
                Label(
                    "Component weights don't sum to 100%; score has been normalized.",
                    systemImage: "exclamationmark.triangle"
                )
                .font(.caption)
                .foregroundStyle(.orange)
                .accessibilityLabel("Warning: component weights are not balanced; score normalized")
            }
        } header: {
            Text("Score")
        }
    }

    private var bandColor: Color {
        switch band {
        case "excellent": return .green
        case "good": return .blue
        case "fair": return .yellow
        case "poor": return .orange
        default: return .red
        }
    }
}
