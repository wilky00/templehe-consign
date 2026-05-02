// ABOUTME: Phase 5 Sprint 4 — read-only summary sheet with Edit and Submit actions.
// ABOUTME: Shows all scored components, inspection answers, and summary fields before final submit.

import SwiftUI

struct PreviewSubmissionView: View {
    let client: TempleHEClient
    @ObservedObject var draft: DraftSubmission
    @Environment(\.dismiss) private var dismiss

    @State private var isSubmitting = false
    @State private var submitError: String?
    @State private var didSubmit = false

    var body: some View {
        NavigationStack {
            List {
                assetSection
                scoreSection
                summarySection

                if let err = submitError {
                    Section {
                        Text(err)
                            .foregroundStyle(.red)
                            .font(.caption)
                            .accessibilityLabel("Submission error: \(err)")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Review & Submit")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Edit") { dismiss() }
                        .accessibilityLabel("Go back to edit form")
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSubmitting {
                        ProgressView()
                    } else {
                        Button("Submit", action: performSubmit)
                            .bold()
                            .disabled(didSubmit)
                            .accessibilityLabel("Submit appraisal")
                    }
                }
            }
        }
    }

    // MARK: - Sections

    private var assetSection: some View {
        Section("Asset") {
            LabeledRow(label: "Make", value: draft.make)
            LabeledRow(label: "Model", value: draft.model)
            LabeledRow(label: "Year", value: draft.yearText)
            LabeledRow(label: "Serial", value: draft.serialNumber)
            if let v = draft.runningStatus { LabeledRow(label: "Running", value: v) }
            if let v = draft.titleStatus { LabeledRow(label: "Title", value: v) }
        }
    }

    private var scoreSection: some View {
        Section("Score") {
            HStack {
                Text("Overall")
                Spacer()
                Text(String(format: "%.2f / 5.00", draft.overallScore))
                    .bold()
                    .accessibilityLabel("Overall score \(String(format: "%.2f", draft.overallScore))")
            }
            if !draft.scoreBand.isEmpty {
                HStack {
                    Text("Band")
                    Spacer()
                    Text(draft.scoreBand.capitalized)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var summarySection: some View {
        Section("Summary") {
            if let m = draft.marketabilityRating {
                LabeledRow(label: "Marketability", value: m)
            }
            if !draft.transportNotes.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Transport Notes").font(.caption).foregroundStyle(.secondary)
                    Text(draft.transportNotes).font(.body)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Transport notes: \(draft.transportNotes)")
            }
            if !draft.listingNotes.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Listing Notes").font(.caption).foregroundStyle(.secondary)
                    Text(draft.listingNotes).font(.body)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Listing notes: \(draft.listingNotes)")
            }
        }
    }

    // MARK: - Submit

    private func performSubmit() {
        guard let submissionId = draft.submissionId else {
            submitError = "No submission ID — save the form first."
            return
        }
        isSubmitting = true
        submitError = nil
        Task {
            defer { isSubmitting = false }
            do {
                let _: SubmissionOut = try await client.request(
                    "POST",
                    path: Endpoint.submitSubmission(submissionId),
                    body: EmptyBody(),
                    authenticated: true
                )
                draft.status = "submitted"
                didSubmit = true
                dismiss()
            } catch {
                submitError = "Submission failed. Please try again."
            }
        }
    }
}

// MARK: - Helpers

private struct LabeledRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value.isEmpty ? "—" : value)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label): \(value.isEmpty ? "not set" : value)")
    }
}

private struct EmptyBody: Encodable {}
