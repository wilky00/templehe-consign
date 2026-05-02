// ABOUTME: Phase 5 Sprint 4 — always-shown intake section for site and asset identification fields.
// ABOUTME: Renders category picker, make/model/year/serial, and condition selects.

import SwiftUI

struct SiteAndAssetSection: View {
    @ObservedObject var draft: DraftSubmission
    let config: IOSConfig

    var body: some View {
        Section("Site & Asset") {
            Picker("Category", selection: $draft.categoryId) {
                Text("Select category").tag(String?.none)
                ForEach(config.categories) { cat in
                    Text(cat.name).tag(Optional(cat.id))
                }
            }
            .accessibilityLabel("Equipment category")

            TextField("Make", text: $draft.make)
                .textInputAutocapitalization(.words)
                .accessibilityLabel("Equipment make")
                .onChange(of: draft.make) { _ in draft.isDirty = true }

            TextField("Model", text: $draft.model)
                .textInputAutocapitalization(.words)
                .accessibilityLabel("Equipment model")
                .onChange(of: draft.model) { _ in draft.isDirty = true }

            TextField("Year", text: $draft.yearText)
                .keyboardType(.numberPad)
                .accessibilityLabel("Model year")
                .onChange(of: draft.yearText) { _ in draft.isDirty = true }

            TextField("Serial Number", text: $draft.serialNumber)
                .textInputAutocapitalization(.characters)
                .accessibilityLabel("Serial number")
                .onChange(of: draft.serialNumber) { _ in draft.isDirty = true }

            Picker("Running Status", selection: $draft.runningStatus) {
                Text("Unknown").tag(String?.none)
                Text("Runs & drives").tag(Optional("runs_drives"))
                Text("Runs, won't drive").tag(Optional("runs_no_drive"))
                Text("Will not start").tag(Optional("no_start"))
            }
            .accessibilityLabel("Running status")
            .onChange(of: draft.runningStatus) { _ in draft.isDirty = true }

            Picker("Title Status", selection: $draft.titleStatus) {
                Text("Unknown").tag(String?.none)
                Text("Clear").tag(Optional("clear"))
                Text("Lien").tag(Optional("lien"))
                Text("No title").tag(Optional("no_title"))
                Text("Bonded").tag(Optional("bonded"))
            }
            .accessibilityLabel("Title status")
            .onChange(of: draft.titleStatus) { _ in draft.isDirty = true }

            Picker("Hours Condition", selection: $draft.hoursCondition) {
                Text("Unknown").tag(String?.none)
                Text("Verified").tag(Optional("verified"))
                Text("Estimated").tag(Optional("estimated"))
                Text("Tampered").tag(Optional("tampered"))
            }
            .accessibilityLabel("Hours verification status")
            .onChange(of: draft.hoursCondition) { _ in draft.isDirty = true }
        }
        .onChange(of: draft.categoryId) { _ in draft.isDirty = true }
    }
}
