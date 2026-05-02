// ABOUTME: Manages up to 5 pinned comparable sales for a valuation lookup session.
// ABOUTME: In-memory for Sprint 3; Sprint 4 Core Data will persist into CDComparableSale.

import Foundation

/// Holds the set of comparables an appraiser has pinned during a valuation
/// lookup. Capped at 5 per business rule. Sprint 4 wires this into Core Data
/// so pins survive across draft saves; for now it lives in-session memory.
@MainActor
final class PinnedComps: ObservableObject {
    static let maxPins = 5

    @Published private(set) var pinned: [ComparableSaleOut] = []

    var isFull: Bool { pinned.count >= PinnedComps.maxPins }

    func isPinned(_ sale: ComparableSaleOut) -> Bool {
        pinned.contains { $0.id == sale.id }
    }

    func pin(_ sale: ComparableSaleOut) {
        guard !isPinned(sale), !isFull else { return }
        pinned.append(sale)
    }

    func unpin(_ sale: ComparableSaleOut) {
        pinned.removeAll { $0.id == sale.id }
    }
}
