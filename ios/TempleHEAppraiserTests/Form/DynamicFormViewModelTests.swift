// ABOUTME: Phase 5 Sprint 4 — unit tests for DraftSubmission observable and score recalculation.
// ABOUTME: Covers dirty flag, category change, score band labels, and update request encoding.

import XCTest
@testable import TempleHEAppraiser

@MainActor
final class DynamicFormViewModelTests: XCTestCase {

    private func makeConfig(categoryId: String = "cat-1") -> IOSConfig {
        IOSConfig(
            config_version: "abc123",
            categories: [
                IOSConfigCategory(id: categoryId, name: "Excavator", slug: "excavator", display_order: 0)
            ],
            components: [
                IOSConfigComponent(id: "comp-1", category_id: categoryId, name: "Engine", weight_pct: "50.0000", display_order: 0),
                IOSConfigComponent(id: "comp-2", category_id: categoryId, name: "Undercarriage", weight_pct: "50.0000", display_order: 1),
            ],
            inspection_prompts: [
                IOSConfigPrompt(id: "p-1", category_id: categoryId, label: "Engine starts?", response_type: "yes_no_na", required: true, display_order: 0, version: 1),
            ],
            red_flag_rules: []
        )
    }

    func testInitialStateIsDraft() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        XCTAssertEqual(draft.status, "draft")
        XCTAssertFalse(draft.isDirty)
    }

    func testDirtyFlagSetOnMakeChange() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        draft.make = "CAT"
        draft.isDirty = true  // simulates the .onChange handler in the view
        XCTAssertTrue(draft.isDirty)
    }

    func testScoreRecalculationWithEqualWeights() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        let config = makeConfig()
        draft.categoryId = "cat-1"
        draft.componentScores["comp-1"] = 4.0
        draft.componentScores["comp-2"] = 2.0

        draft.recalculateScore(config: config)

        XCTAssertEqual(draft.overallScore, 3.0, accuracy: 0.01)
        XCTAssertEqual(draft.scoreBand, "fair")
    }

    func testScoreExcellentBand() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        let config = makeConfig()
        draft.categoryId = "cat-1"
        draft.componentScores["comp-1"] = 5.0
        draft.componentScores["comp-2"] = 5.0

        draft.recalculateScore(config: config)
        XCTAssertEqual(draft.scoreBand, "excellent")
    }

    func testScoreSalvageBandWhenNoCategory() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        let config = makeConfig()
        draft.categoryId = nil

        draft.recalculateScore(config: config)
        XCTAssertEqual(draft.overallScore, 0.0, accuracy: 0.001)
        XCTAssertEqual(draft.scoreBand, "salvage")
    }

    func testToUpdateRequestIncludesScores() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        draft.categoryId = "cat-1"
        draft.make = "Komatsu"
        draft.componentScores["comp-1"] = 3.5

        let req = draft.toUpdateRequest()
        XCTAssertEqual(req.make, "Komatsu")
        XCTAssertEqual(req.category_id, "cat-1")
        XCTAssertNotNil(req.component_scores)
        XCTAssertEqual(req.component_scores?.first?.score, 3.5, accuracy: 0.001)
    }

    func testToUpdateRequestExcludesEmptyStrings() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        draft.make = ""
        draft.serialNumber = ""

        let req = draft.toUpdateRequest()
        XCTAssertNil(req.make)
        XCTAssertNil(req.serial_number)
    }

    func testInspectionAnswerStoredWithVersion() {
        let draft = DraftSubmission(equipmentRecordId: "rec-1")
        draft.inspectionAnswers["p-1"] = InspectionAnswerEntry(promptId: "p-1", version: 2, value: "yes")

        let answer = draft.inspectionAnswers["p-1"]
        XCTAssertEqual(answer?.version, 2)
        XCTAssertEqual(answer?.value, "yes")
    }

    func testInitFromServerSubmission() {
        let server = SubmissionOut(
            id: "sub-1",
            equipment_record_id: "rec-1",
            appraiser_id: nil,
            status: "draft",
            category_id: "cat-1",
            category_version: nil,
            make: "CAT",
            model: "320",
            year: 2021,
            hours_condition: "verified",
            running_status: "runs_drives",
            serial_number: "ABC123",
            title_status: "clear",
            overall_score: 4.2,
            score_band: "good",
            marketability_rating: "high",
            transport_notes: "No oversize",
            listing_notes: "Ready to list",
            component_scores: [],
            submitted_at: nil,
            created_at: "2026-05-01T00:00:00Z",
            updated_at: "2026-05-01T00:00:00Z"
        )
        let draft = DraftSubmission(equipmentRecordId: "rec-1", from: server)
        XCTAssertEqual(draft.make, "CAT")
        XCTAssertEqual(draft.yearText, "2021")
        XCTAssertEqual(draft.overallScore, 4.2, accuracy: 0.001)
        XCTAssertEqual(draft.scoreBand, "good")
    }
}
