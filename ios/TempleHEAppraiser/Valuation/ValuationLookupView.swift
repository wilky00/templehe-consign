// ABOUTME: Phase 5 Sprint 3 — valuation comparable search UI for the iOS appraiser app.
// ABOUTME: Make/model/year/hours inputs; searches backend; results list with pin support.

import SwiftUI

/// Standalone valuation lookup screen. In Sprint 4 this will be embedded
/// in the dynamic appraisal form with inputs pre-filled from the draft.
/// For now it operates as an independent search surface.
struct ValuationLookupView: View {
    let client: TempleHEClient

    @StateObject private var pinnedComps = PinnedComps()
    @State private var make: String = ""
    @State private var model: String = ""
    @State private var yearText: String = ""
    @State private var hoursText: String = ""
    @State private var results: [ComparableSaleOut] = []
    @State private var usedSources: [String] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var hasSearched = false

    var body: some View {
        NavigationStack {
            List {
                searchSection
                if hasSearched && !isLoading {
                    resultsSection
                }
                if !pinnedComps.pinned.isEmpty {
                    pinnedSection
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Valuation Lookup")
            .overlay {
                if isLoading {
                    ProgressView("Searching...")
                        .padding()
                        .background(.regularMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }
        }
    }

    // MARK: - Sections

    private var searchSection: some View {
        Section("Search Parameters") {
            TextField("Make", text: $make)
                .textInputAutocapitalization(.words)
                .accessibilityLabel("Equipment make")
            TextField("Model", text: $model)
                .textInputAutocapitalization(.words)
                .accessibilityLabel("Equipment model")
            TextField("Year", text: $yearText)
                .keyboardType(.numberPad)
                .accessibilityLabel("Model year")
            TextField("Hours", text: $hoursText)
                .keyboardType(.numberPad)
                .accessibilityLabel("Hours of use")

            Button(action: performSearch) {
                HStack {
                    Spacer()
                    Text("Search Comparables")
                        .bold()
                    Spacer()
                }
            }
            .disabled(isLoading || (make.isEmpty && model.isEmpty && yearText.isEmpty && hoursText.isEmpty))
            .accessibilityLabel("Search for comparable sales")

            if let error = errorMessage {
                Text(error)
                    .foregroundStyle(.red)
                    .font(.caption)
                    .accessibilityLabel("Error: \(error)")
            }
        }
    }

    private var resultsSection: some View {
        Section {
            if results.isEmpty {
                Text("No comparables found. Try widening your search.")
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
                    .accessibilityLabel("No results found")
            } else {
                ForEach(results) { sale in
                    ComparableSaleRow(
                        sale: sale,
                        isPinned: pinnedComps.isPinned(sale),
                        isFull: pinnedComps.isFull
                    ) {
                        if pinnedComps.isPinned(sale) {
                            pinnedComps.unpin(sale)
                        } else {
                            pinnedComps.pin(sale)
                        }
                    }
                }
            }
        } header: {
            HStack {
                Text("Results")
                if !usedSources.isEmpty {
                    Spacer()
                    Text("Sources: \(usedSources.joined(separator: ", "))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .accessibilityLabel("Data sources: \(usedSources.joined(separator: ", "))")
                }
            }
        }
    }

    private var pinnedSection: some View {
        Section("Pinned Comparables (\(pinnedComps.pinned.count)/\(PinnedComps.maxPins))") {
            ForEach(pinnedComps.pinned) { sale in
                ComparableSaleRow(
                    sale: sale,
                    isPinned: true,
                    isFull: false
                ) {
                    pinnedComps.unpin(sale)
                }
            }
            .onDelete { offsets in
                offsets.forEach { pinnedComps.unpin(pinnedComps.pinned[$0]) }
            }
        }
    }

    // MARK: - Search

    private func performSearch() {
        isLoading = true
        errorMessage = nil

        let req = ValuationSearchRequest(
            make: make.isEmpty ? nil : make,
            model: model.isEmpty ? nil : model,
            year: Int(yearText),
            hours: Int(hoursText),
            category_id: nil
        )

        Task {
            defer { isLoading = false }
            do {
                let response: ValuationSearchResponse = try await client.request(
                    "POST",
                    path: Endpoint.valuationSearch,
                    body: req,
                    authenticated: true
                )
                results = response.results
                usedSources = response.used_sources
                hasSearched = true
            } catch {
                errorMessage = "Search failed. Please try again."
                hasSearched = true
            }
        }
    }
}
