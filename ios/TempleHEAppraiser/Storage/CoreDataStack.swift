// ABOUTME: Phase 5 Sprint 4 — Core Data stack for offline appraisal draft storage.
// ABOUTME: Programmatic model (no .xcdatamodeld) with CDAppraisalSubmission and CDConfig entities.

import CoreData
import Foundation

/// Shared Core Data stack. Access via `CoreDataStack.shared`.
///
/// Entities:
/// - ``CDAppraisalSubmission`` — offline draft state (mirrored to server when online)
/// - ``CDConfig`` — cached iOS config response keyed by config_version hash
final class CoreDataStack {
    static let shared = CoreDataStack()

    let container: NSPersistentContainer

    var viewContext: NSManagedObjectContext { container.viewContext }

    private init() {
        let model = CoreDataStack.makeModel()
        container = NSPersistentContainer(name: "TempleHEAppraiser", managedObjectModel: model)
        container.loadPersistentStores { _, error in
            if let error {
                // Persistent store failures are unrecoverable during development.
                // In production the app falls back to server-only mode (AutoSave skips Core Data).
                fatalError("Core Data store failed to load: \(error)")
            }
        }
        container.viewContext.automaticallyMergesChangesFromParent = true
    }

    func newBackgroundContext() -> NSManagedObjectContext {
        container.newBackgroundContext()
    }

    // MARK: - Model

    private static func makeModel() -> NSManagedObjectModel {
        let model = NSManagedObjectModel()

        let submission = submissionEntity()
        let config = configEntity()

        model.entities = [submission, config]
        return model
    }

    private static func submissionEntity() -> NSEntityDescription {
        let entity = NSEntityDescription()
        entity.name = "CDAppraisalSubmission"
        entity.managedObjectClassName = NSStringFromClass(CDAppraisalSubmission.self)

        let attrs: [(String, NSAttributeType, Bool)] = [
            ("submissionId", .stringAttributeType, false),
            ("equipmentRecordId", .stringAttributeType, false),
            ("status", .stringAttributeType, false),
            ("categoryId", .stringAttributeType, true),
            ("make", .stringAttributeType, true),
            ("model", .stringAttributeType, true),
            ("year", .integer32AttributeType, true),
            ("hoursCondition", .stringAttributeType, true),
            ("runningStatus", .stringAttributeType, true),
            ("serialNumber", .stringAttributeType, true),
            ("titleStatus", .stringAttributeType, true),
            ("marketabilityRating", .stringAttributeType, true),
            ("transportNotes", .stringAttributeType, true),
            ("listingNotes", .stringAttributeType, true),
            ("overallScore", .doubleAttributeType, true),
            ("scoreBand", .stringAttributeType, true),
            // JSON blobs stored as Data
            ("fieldValuesJSON", .binaryDataAttributeType, true),
            ("componentScoresJSON", .binaryDataAttributeType, true),
            ("updatedAt", .dateAttributeType, true),
            ("pendingSync", .booleanAttributeType, false),
        ]

        entity.properties = attrs.map { name, type, optional in
            let attr = NSAttributeDescription()
            attr.name = name
            attr.attributeType = type
            attr.isOptional = optional
            if name == "status" { attr.defaultValue = "draft" }
            if name == "pendingSync" { attr.defaultValue = false }
            return attr
        }
        return entity
    }

    private static func configEntity() -> NSEntityDescription {
        let entity = NSEntityDescription()
        entity.name = "CDConfig"
        entity.managedObjectClassName = NSStringFromClass(CDConfig.self)

        let attrs: [(String, NSAttributeType, Bool)] = [
            ("configVersion", .stringAttributeType, false),
            ("payloadJSON", .binaryDataAttributeType, false),
            ("cachedAt", .dateAttributeType, false),
        ]
        entity.properties = attrs.map { name, type, optional in
            let attr = NSAttributeDescription()
            attr.name = name
            attr.attributeType = type
            attr.isOptional = optional
            return attr
        }
        return entity
    }
}

// MARK: - Managed Object subclasses

@objc(CDAppraisalSubmission)
final class CDAppraisalSubmission: NSManagedObject {
    @NSManaged var submissionId: String
    @NSManaged var equipmentRecordId: String
    @NSManaged var status: String
    @NSManaged var categoryId: String?
    @NSManaged var make: String?
    @NSManaged var model: String?
    @NSManaged var year: Int32
    @NSManaged var hoursCondition: String?
    @NSManaged var runningStatus: String?
    @NSManaged var serialNumber: String?
    @NSManaged var titleStatus: String?
    @NSManaged var marketabilityRating: String?
    @NSManaged var transportNotes: String?
    @NSManaged var listingNotes: String?
    @NSManaged var overallScore: Double
    @NSManaged var scoreBand: String?
    @NSManaged var fieldValuesJSON: Data?
    @NSManaged var componentScoresJSON: Data?
    @NSManaged var updatedAt: Date?
    @NSManaged var pendingSync: Bool
}

@objc(CDConfig)
final class CDConfig: NSManagedObject {
    @NSManaged var configVersion: String
    @NSManaged var payloadJSON: Data
    @NSManaged var cachedAt: Date

    func decoded() -> IOSConfig? {
        try? JSONDecoder().decode(IOSConfig.self, from: payloadJSON)
    }
}

// MARK: - Config cache helpers

extension CoreDataStack {
    func cachedConfig() -> IOSConfig? {
        let request = NSFetchRequest<CDConfig>(entityName: "CDConfig")
        request.sortDescriptors = [NSSortDescriptor(key: "cachedAt", ascending: false)]
        request.fetchLimit = 1
        return (try? viewContext.fetch(request))?.first?.decoded()
    }

    func saveConfig(_ config: IOSConfig, rawData: Data) {
        viewContext.perform {
            // Replace any existing cached config
            let request = NSFetchRequest<CDConfig>(entityName: "CDConfig")
            if let existing = try? self.viewContext.fetch(request) {
                existing.forEach { self.viewContext.delete($0) }
            }
            let entity = CDConfig(context: self.viewContext)
            entity.configVersion = config.config_version
            entity.payloadJSON = rawData
            entity.cachedAt = Date()
            try? self.viewContext.save()
        }
    }
}
