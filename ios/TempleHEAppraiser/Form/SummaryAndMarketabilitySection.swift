// ABOUTME: Phase 5 Sprint 4 — summary section: marketability rating, transport/listing notes.
// ABOUTME: Appears at the bottom of the form above the Preview button.

import SwiftUI

struct SummaryAndMarketabilitySection: View {
    @ObservedObject var draft: DraftSubmission

    private let marketabilityOptions = [
        ("high", "High — Ready to sell"),
        ("medium", "Medium — Minor reconditioning needed"),
        ("low", "Low — Significant issues"),
        ("parts_only", "Parts only"),
    ]

    var body: some View {
        Section("Summary & Marketability") {
            Picker("Marketability", selection: $draft.marketabilityRating) {
                Text("Not assessed").tag(String?.none)
                ForEach(marketabilityOptions, id: \.0) { value, label in
                    Text(label).tag(Optional(value))
                }
            }
            .accessibilityLabel("Marketability rating")
            .onChange(of: draft.marketabilityRating) { _ in draft.isDirty = true }

            VStack(alignment: .leading, spacing: 4) {
                Text("Transport Notes")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                TextEditor(text: $draft.transportNotes)
                    .frame(minHeight: 60)
                    .accessibilityLabel("Transport notes")
                    .onChange(of: draft.transportNotes) { _ in draft.isDirty = true }
            }
            .padding(.vertical, 2)

            VStack(alignment: .leading, spacing: 4) {
                Text("Listing Notes")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                TextEditor(text: $draft.listingNotes)
                    .frame(minHeight: 60)
                    .accessibilityLabel("Listing notes for sales team")
                    .onChange(of: draft.listingNotes) { _ in draft.isDirty = true }
            }
            .padding(.vertical, 2)
        }
    }
}
