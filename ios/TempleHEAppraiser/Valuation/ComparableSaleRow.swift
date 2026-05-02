// ABOUTME: Row view for a single comparable sale result in the valuation lookup list.
// ABOUTME: Shows price, date, make/model/year/hours, source badge, and a Pin button.

import SwiftUI

struct ComparableSaleRow: View {
    let sale: ComparableSaleOut
    let isPinned: Bool
    let isFull: Bool
    let onPin: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(sale.makeModelYear.isEmpty ? "Unknown Equipment" : sale.makeModelYear)
                    .font(.headline)
                    .accessibilityLabel("Equipment: \(sale.makeModelYear)")

                HStack(spacing: 8) {
                    if let hours = sale.hours {
                        Label("\(hours) hrs", systemImage: "gauge")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("\(hours) hours")
                    }
                    if let date = sale.formattedDate {
                        Label(date, systemImage: "calendar")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("Sale date: \(date)")
                    }
                }

                SourceBadge(source: sale.source ?? "internal")
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 8) {
                if let price = sale.formattedPrice {
                    Text(price)
                        .font(.title3.bold())
                        .foregroundStyle(.primary)
                        .accessibilityLabel("Sale price: \(price)")
                }

                Button(action: onPin) {
                    Label(
                        isPinned ? "Pinned" : "Pin",
                        systemImage: isPinned ? "pin.fill" : "pin"
                    )
                    .font(.caption.bold())
                }
                .disabled(isPinned ? false : isFull)
                .tint(isPinned ? .orange : .accentColor)
                .accessibilityLabel(isPinned ? "Unpin comparable" : "Pin comparable")
                .accessibilityHint(
                    isPinned
                        ? "Removes this sale from your pinned comparables"
                        : isFull
                            ? "Maximum 5 comparables pinned"
                            : "Adds this sale to your pinned comparables"
                )
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Source badge

private struct SourceBadge: View {
    let source: String

    var body: some View {
        Text(source.capitalized)
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
            .accessibilityLabel("Source: \(source)")
    }

    private var color: Color {
        switch source {
        case "internal": return .blue
        case "external": return .purple
        case "scraped": return .orange
        default: return .secondary
        }
    }
}

// MARK: - Formatting helpers

private extension ComparableSaleOut {
    var formattedPrice: String? {
        guard let price = sale_price else { return nil }
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: price))
    }

    var formattedDate: String? {
        guard let raw = sale_date else { return nil }
        // API returns ISO-8601 timestamp; display as "Sep 2024".
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withFullDate, .withDashSeparatorInDate, .withTime, .withColonSeparatorInTime, .withTimeZone]
        if let date = iso.date(from: raw) {
            let fmt = DateFormatter()
            fmt.dateFormat = "MMM yyyy"
            return fmt.string(from: date)
        }
        // Fallback: return first 7 chars (YYYY-MM) if full parse fails.
        return raw.count >= 7 ? String(raw.prefix(7)) : nil
    }
}
