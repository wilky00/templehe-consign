// ABOUTME: Card view for a single appointment on the appraiser's dashboard.
// ABOUTME: Shows customer/equipment info with call, copy address, and navigate actions.

import SwiftUI

struct AssignmentCard: View {
    let appointment: AppointmentDetail

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerRow
            if let address = appointment.site_address, !address.isEmpty {
                addressRow(address)
            }
            contactRow
            actionRow
        }
        .padding()
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var headerRow: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text(appointment.makeModelYear.isEmpty ? "Equipment" : appointment.makeModelYear)
                    .font(.headline)
                    .accessibilityLabel("Equipment: \(appointment.makeModelYear)")
                if let ref = appointment.reference_number {
                    Text(ref)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            StatusBadge(status: appointment.record_status)
        }
    }

    private func addressRow(_ address: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "mappin.circle")
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text(address)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .accessibilityLabel("Site address: \(address)")
        }
    }

    private var contactRow: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let name = appointment.customer_name {
                Label(name, systemImage: "person")
                    .font(.subheadline)
                    .accessibilityLabel("Customer: \(name)")
            }
            if let repName = appointment.sales_rep_name {
                Label(repName, systemImage: "person.badge.shield.checkmark")
                    .font(.subheadline)
                    .accessibilityLabel("Sales rep: \(repName)")
            }
        }
    }

    private var actionRow: some View {
        HStack(spacing: 12) {
            if let phone = appointment.customer_phone {
                callButton(label: "Call Customer", phone: phone)
            }
            if let phone = appointment.sales_rep_phone {
                callButton(label: "Call Rep", phone: phone)
            }
            if let address = appointment.site_address {
                navigateButton(address: address)
                copyAddressButton(address: address)
            }
        }
    }

    private func callButton(label: String, phone: String) -> some View {
        let stripped = phone.components(separatedBy: CharacterSet.decimalDigits.inverted).joined()
        return Link(
            destination: URL(string: "tel:\(stripped)")!,
            label: {
                Label(label, systemImage: "phone")
                    .font(.caption.bold())
            }
        )
        .accessibilityLabel(label)
        .accessibilityHint("Calls \(phone)")
    }

    private func navigateButton(address: String) -> some View {
        Button {
            MapsLauncher.navigate(to: address)
        } label: {
            Label("Navigate", systemImage: "arrow.triangle.turn.up.right.circle")
                .font(.caption.bold())
        }
        .accessibilityLabel("Navigate to \(address)")
    }

    private func copyAddressButton(address: String) -> some View {
        Button {
            UIPasteboard.general.string = address
        } label: {
            Image(systemName: "doc.on.doc")
                .font(.caption)
        }
        .accessibilityLabel("Copy address")
        .accessibilityHint("Copies site address to clipboard")
    }
}

// MARK: - Status badge

private struct StatusBadge: View {
    let status: String

    var body: some View {
        Text(displayText)
            .font(.caption2.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
            .accessibilityLabel("Status: \(displayText)")
    }

    private var displayText: String {
        status.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private var color: Color {
        switch status {
        case "scheduled": return .blue
        case "in_progress": return .orange
        case "completed": return .green
        default: return .secondary
        }
    }
}
