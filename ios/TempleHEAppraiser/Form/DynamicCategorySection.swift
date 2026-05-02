// ABOUTME: Phase 5 Sprint 4 — dynamic category section sourced from IOSConfig.
// ABOUTME: Renders scoring components (0–5 segmented) and inspection prompts (yes/no/N/A or text).

import SwiftUI

struct DynamicCategorySection: View {
    @ObservedObject var draft: DraftSubmission
    let config: IOSConfig
    let categoryId: String

    private var components: [IOSConfigComponent] { config.components(for: categoryId) }
    private var prompts: [IOSConfigPrompt] { config.prompts(for: categoryId) }

    var body: some View {
        if !components.isEmpty {
            Section("Component Scores") {
                ForEach(components) { component in
                    ComponentScoreRow(
                        component: component,
                        score: Binding(
                            get: { draft.componentScores[component.id] ?? 0 },
                            set: {
                                draft.componentScores[component.id] = $0
                                draft.isDirty = true
                            }
                        )
                    )
                }
            }
        }

        if !prompts.isEmpty {
            Section("Inspection Checklist") {
                ForEach(prompts) { prompt in
                    InspectionPromptRow(
                        prompt: prompt,
                        answer: Binding(
                            get: { draft.inspectionAnswers[prompt.id]?.value },
                            set: { newValue in
                                draft.inspectionAnswers[prompt.id] = InspectionAnswerEntry(
                                    promptId: prompt.id,
                                    version: prompt.version,
                                    value: newValue
                                )
                                draft.isDirty = true
                            }
                        )
                    )
                }
            }
        }
    }
}

// MARK: - Component score row

private struct ComponentScoreRow: View {
    let component: IOSConfigComponent
    @Binding var score: Double

    private let options: [Double] = [0, 1, 2, 3, 4, 5]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(component.name)
                    .font(.subheadline)
                    .accessibilityLabel("Component: \(component.name)")
                Spacer()
                Text(String(format: "%.0f / 5", score))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("Score: \(Int(score)) out of 5")
            }
            // Segmented 0–5 control
            Picker("", selection: $score) {
                ForEach(options, id: \.self) { v in
                    Text("\(Int(v))").tag(v)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("\(component.name) score")
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Inspection prompt row

private struct InspectionPromptRow: View {
    let prompt: IOSConfigPrompt
    @Binding var answer: String?

    var body: some View {
        switch prompt.response_type {
        case "yes_no_na":
            YesNoNARow(label: prompt.label, required: prompt.required, answer: $answer)
        case "text":
            TextPromptRow(label: prompt.label, required: prompt.required, answer: $answer)
        case "scale_1_5":
            ScaleRow(label: prompt.label, required: prompt.required, answer: $answer)
        default:
            TextPromptRow(label: prompt.label, required: prompt.required, answer: $answer)
        }
    }
}

private struct YesNoNARow: View {
    let label: String
    let required: Bool
    @Binding var answer: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label)
                    .font(.subheadline)
                    .accessibilityLabel(label)
                if required {
                    Text("*").foregroundStyle(.red).accessibilityHidden(true)
                }
            }
            Picker("", selection: $answer) {
                Text("—").tag(String?.none)
                Text("Yes").tag(Optional("yes"))
                Text("No").tag(Optional("no"))
                Text("N/A").tag(Optional("na"))
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("\(label) answer")
        }
        .padding(.vertical, 2)
    }
}

private struct TextPromptRow: View {
    let label: String
    let required: Bool
    @Binding var answer: String?

    private var binding: Binding<String> {
        Binding(get: { answer ?? "" }, set: { answer = $0.isEmpty ? nil : $0 })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(.subheadline)
                if required { Text("*").foregroundStyle(.red).accessibilityHidden(true) }
            }
            TextField("Enter response", text: binding)
                .font(.body)
                .accessibilityLabel(label)
        }
        .padding(.vertical, 2)
    }
}

private struct ScaleRow: View {
    let label: String
    let required: Bool
    @Binding var answer: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(.subheadline)
                if required { Text("*").foregroundStyle(.red).accessibilityHidden(true) }
            }
            Picker("", selection: $answer) {
                Text("—").tag(String?.none)
                ForEach(1...5, id: \.self) { i in
                    Text("\(i)").tag(Optional(String(i)))
                }
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("\(label) rating 1–5")
        }
        .padding(.vertical, 2)
    }
}
