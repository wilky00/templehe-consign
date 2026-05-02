// ABOUTME: Phase 5 Sprint 4 — 10-second debounced auto-save for appraisal drafts.
// ABOUTME: PATCHes to backend when online (NWPathMonitor); writes to Core Data when offline.

import Combine
import Foundation
import Network

/// Observes a ``DraftSubmission`` and persists changes automatically.
///
/// Online: debounces PATCH calls to the backend (10-second delay prevents
/// a network round-trip on every keystroke).
/// Offline: writes the draft state to Core Data for later sync by ``SyncService``.
///
/// Usage: create one ``AutoSave`` per form session; cancel it when the form
/// is dismissed to stop the timer.
@MainActor
final class AutoSave {
    private var cancellables = Set<AnyCancellable>()
    private let monitor = NWPathMonitor()
    private var isOnline = true
    private let client: TempleHEClient

    init(draft: DraftSubmission, client: TempleHEClient) {
        self.client = client

        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isOnline = path.status == .satisfied
            }
        }
        monitor.start(queue: DispatchQueue(label: "autosave.monitor"))

        // Debounce 10 seconds; skip the initial value so we don't immediately PATCH on load
        draft.$isDirty
            .dropFirst()
            .filter { $0 }
            .debounce(for: .seconds(10), scheduler: RunLoop.main)
            .sink { [weak self, weak draft] _ in
                guard let self, let draft else { return }
                Task { await self.flush(draft: draft) }
            }
            .store(in: &cancellables)
    }

    func cancel() {
        cancellables.removeAll()
        monitor.cancel()
    }

    // MARK: - Flush

    func flush(draft: DraftSubmission) async {
        guard draft.isDirty, let submissionId = draft.submissionId else { return }

        let body = draft.toUpdateRequest()

        if isOnline {
            await patchToServer(submissionId: submissionId, body: body, draft: draft)
        } else {
            saveToCoreData(draft: draft)
        }
    }

    // MARK: - Private

    private func patchToServer(
        submissionId: String,
        body: SubmissionUpdateRequest,
        draft: DraftSubmission
    ) async {
        do {
            let _: SubmissionOut = try await client.request(
                "PATCH",
                path: Endpoint.appraisalSubmission(submissionId),
                body: body,
                authenticated: true
            )
            draft.isDirty = false
        } catch {
            // Server PATCH failed — fall through to Core Data so the draft isn't lost
            saveToCoreData(draft: draft)
        }
    }

    private func saveToCoreData(draft: DraftSubmission) {
        let stack = CoreDataStack.shared
        let context = stack.newBackgroundContext()
        context.perform {
            let request = NSFetchRequest<CDAppraisalSubmission>(
                entityName: "CDAppraisalSubmission"
            )
            let submissionId = draft.submissionId ?? ""
            request.predicate = NSPredicate(format: "submissionId == %@", submissionId)

            let entity: CDAppraisalSubmission
            if let existing = (try? context.fetch(request))?.first {
                entity = existing
            } else {
                entity = CDAppraisalSubmission(context: context)
                entity.submissionId = submissionId
                entity.equipmentRecordId = draft.equipmentRecordId
            }

            entity.status = draft.status
            entity.categoryId = draft.categoryId
            entity.make = draft.make.isEmpty ? nil : draft.make
            entity.model = draft.model.isEmpty ? nil : draft.model
            entity.year = draft.yearText.flatMap { Int32($0) } ?? 0
            entity.hoursCondition = draft.hoursCondition
            entity.runningStatus = draft.runningStatus
            entity.serialNumber = draft.serialNumber.isEmpty ? nil : draft.serialNumber
            entity.titleStatus = draft.titleStatus
            entity.marketabilityRating = draft.marketabilityRating
            entity.transportNotes = draft.transportNotes.isEmpty ? nil : draft.transportNotes
            entity.listingNotes = draft.listingNotes.isEmpty ? nil : draft.listingNotes
            entity.overallScore = draft.overallScore
            entity.scoreBand = draft.scoreBand
            entity.updatedAt = Date()
            entity.pendingSync = true

            if let data = try? JSONEncoder().encode(draft.inspectionAnswers) {
                entity.fieldValuesJSON = data
            }
            if let data = try? JSONEncoder().encode(draft.componentScores) {
                entity.componentScoresJSON = data
            }

            try? context.save()
        }
    }
}
