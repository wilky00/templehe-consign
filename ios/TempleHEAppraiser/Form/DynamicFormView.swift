// ABOUTME: Phase 5 Sprint 4 — top-level dynamic appraisal form container.
// ABOUTME: Holds DraftSubmission state; shows SiteAndAsset + category-specific sections.

import SwiftUI

/// DraftSubmission is the in-memory model for a form session.
/// AutoSave observes `isDirty` and debounces PATCH calls.
@MainActor
final class DraftSubmission: ObservableObject {
    // Server identity
    var submissionId: String?
    let equipmentRecordId: String

    // Lifecycle
    @Published var status: String = "draft"

    // Site & Asset
    @Published var categoryId: String?
    @Published var make: String = ""
    @Published var model: String = ""
    @Published var yearText: String = ""
    @Published var serialNumber: String = ""
    @Published var hoursCondition: String?
    @Published var runningStatus: String?
    @Published var titleStatus: String?

    // Inspection answers: prompt_id → (value, version)
    @Published var inspectionAnswers: [String: InspectionAnswerEntry] = [:]

    // Component scores: component_id → score (0–5)
    @Published var componentScores: [String: Double] = [:]

    // Summary
    @Published var marketabilityRating: String?
    @Published var transportNotes: String = ""
    @Published var listingNotes: String = ""

    // Computed score (updated whenever componentScores changes)
    @Published var overallScore: Double = 0
    @Published var scoreBand: String = "salvage"
    @Published var scoreWeightNormalized: Bool = false

    // Dirty flag — set to true whenever any field changes
    @Published var isDirty: Bool = false

    init(equipmentRecordId: String, from server: SubmissionOut? = nil) {
        self.equipmentRecordId = equipmentRecordId
        if let s = server {
            submissionId = s.id
            status = s.status
            categoryId = s.category_id
            make = s.make ?? ""
            model = s.model ?? ""
            yearText = s.year.map { String($0) } ?? ""
            serialNumber = s.serial_number ?? ""
            hoursCondition = s.hours_condition
            runningStatus = s.running_status
            titleStatus = s.title_status
            marketabilityRating = s.marketability_rating
            transportNotes = s.transport_notes ?? ""
            listingNotes = s.listing_notes ?? ""
            overallScore = s.overall_score ?? 0
            scoreBand = s.score_band ?? "salvage"
            for cs in s.component_scores {
                componentScores[cs.component_id] = cs.raw_score
            }
        }
    }

    func recalculateScore(config: IOSConfig) {
        guard let catId = categoryId else {
            overallScore = 0; scoreBand = "salvage"; return
        }
        let components = config.components(for: catId)
        guard !components.isEmpty else {
            overallScore = 0; scoreBand = "salvage"; return
        }
        let totalWeight = components.reduce(0.0) { $0 + $1.weightDouble }
        guard totalWeight > 0 else { return }

        let weighted = components.reduce(0.0) { sum, c in
            let score = componentScores[c.id] ?? 0
            return sum + score * c.weightDouble
        }
        let avg = weighted / totalWeight
        overallScore = (avg * 100).rounded() / 100
        scoreWeightNormalized = !(99.5...100.5).contains(totalWeight)
        scoreBand = scoreBandLabel(for: overallScore)
    }

    func toUpdateRequest() -> SubmissionUpdateRequest {
        var req = SubmissionUpdateRequest()
        req.category_id = categoryId
        req.make = make.isEmpty ? nil : make
        req.model = model.isEmpty ? nil : model
        req.year = Int(yearText)
        req.serial_number = serialNumber.isEmpty ? nil : serialNumber
        req.hours_condition = hoursCondition
        req.running_status = runningStatus
        req.title_status = titleStatus
        req.marketability_rating = marketabilityRating
        req.transport_notes = transportNotes.isEmpty ? nil : transportNotes
        req.listing_notes = listingNotes.isEmpty ? nil : listingNotes
        req.field_values = inspectionAnswers.values.map {
            InspectionAnswerIn(prompt_id: $0.promptId, prompt_version: $0.version, value: $0.value)
        }
        req.component_scores = componentScores.map {
            ComponentScoreIn(component_id: $0.key, score: $0.value, notes: nil)
        }
        return req
    }

    private func scoreBandLabel(for score: Double) -> String {
        switch score {
        case 4.5...: return "excellent"
        case 3.5...: return "good"
        case 2.5...: return "fair"
        case 1.5...: return "poor"
        default: return "salvage"
        }
    }
}

struct InspectionAnswerEntry: Codable {
    var promptId: String
    var version: Int
    var value: String?
}

// MARK: - View

/// Embeds all appraisal form sections in a NavigationStack list.
/// Lifecycle: caller creates a DraftSubmission and passes the IOSConfig;
/// the form posts to the server to create a draft on first load if needed.
struct DynamicFormView: View {
    let client: TempleHEClient
    let config: IOSConfig
    @StateObject var draft: DraftSubmission

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var showPreview = false
    private var autoSave: AutoSave?

    init(client: TempleHEClient, config: IOSConfig, draft: DraftSubmission) {
        self.client = client
        self.config = config
        _draft = StateObject(wrappedValue: draft)
    }

    var body: some View {
        NavigationStack {
            List {
                SiteAndAssetSection(draft: draft, config: config)
                if let catId = draft.categoryId {
                    DynamicCategorySection(draft: draft, config: config, categoryId: catId)
                    ScoringDisplay(
                        score: draft.overallScore,
                        band: draft.scoreBand,
                        weightNormalized: draft.scoreWeightNormalized
                    )
                }
                SummaryAndMarketabilitySection(draft: draft)
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Appraisal Form")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Preview") { showPreview = true }
                        .disabled(draft.status != "draft")
                        .accessibilityLabel("Preview and submit appraisal")
                }
            }
            .sheet(isPresented: $showPreview) {
                PreviewSubmissionView(client: client, draft: draft)
            }
            .overlay {
                if isLoading {
                    ProgressView()
                        .padding()
                        .background(.regularMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }
        }
        .onChange(of: draft.componentScores) { _ in
            draft.recalculateScore(config: config)
        }
    }
}
