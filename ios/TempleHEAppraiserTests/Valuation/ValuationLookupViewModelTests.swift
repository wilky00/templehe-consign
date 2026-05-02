// ABOUTME: Unit tests for PinnedComps — pin/unpin semantics, max-5 enforcement.
// ABOUTME: Search state is covered by the integration tests; this file focuses on pinning logic.

import XCTest
@testable import TempleHEAppraiser

@MainActor
final class PinnedCompsTests: XCTestCase {

    private func makeSale(id: String = UUID().uuidString, make: String = "CAT") -> ComparableSaleOut {
        ComparableSaleOut(
            id: id,
            make: make,
            model: "320",
            year: 2020,
            hours: 3000,
            sale_price: 185000.0,
            sale_date: "2024-06-01T00:00:00Z",
            source: "internal",
            source_url: nil,
            notes: nil,
            category_id: nil
        )
    }

    func testPinAddsToList() {
        let pinned = PinnedComps()
        let sale = makeSale()
        pinned.pin(sale)
        XCTAssertEqual(pinned.pinned.count, 1)
        XCTAssertTrue(pinned.isPinned(sale))
    }

    func testUnpinRemovesFromList() {
        let pinned = PinnedComps()
        let sale = makeSale()
        pinned.pin(sale)
        pinned.unpin(sale)
        XCTAssertEqual(pinned.pinned.count, 0)
        XCTAssertFalse(pinned.isPinned(sale))
    }

    func testPinIsDeduplicated() {
        let pinned = PinnedComps()
        let sale = makeSale(id: "same-id")
        pinned.pin(sale)
        pinned.pin(sale)  // second pin is a no-op
        XCTAssertEqual(pinned.pinned.count, 1)
    }

    func testMaxFivePinsEnforced() {
        let pinned = PinnedComps()
        for i in 1...6 {
            pinned.pin(makeSale(id: "sale-\(i)"))
        }
        XCTAssertEqual(pinned.pinned.count, PinnedComps.maxPins)
        XCTAssertTrue(pinned.isFull)
    }

    func testIsFullFalseWhenBelowMax() {
        let pinned = PinnedComps()
        for i in 1...4 {
            pinned.pin(makeSale(id: "sale-\(i)"))
        }
        XCTAssertFalse(pinned.isFull)
    }

    func testIsFullTrueAtMax() {
        let pinned = PinnedComps()
        for i in 1...PinnedComps.maxPins {
            pinned.pin(makeSale(id: "sale-\(i)"))
        }
        XCTAssertTrue(pinned.isFull)
    }

    func testUnpinWhenFullAllowsFurtherPins() {
        let pinned = PinnedComps()
        let ids = (1...5).map { "sale-\($0)" }
        ids.forEach { pinned.pin(makeSale(id: $0)) }
        XCTAssertTrue(pinned.isFull)

        pinned.unpin(makeSale(id: ids[0]))
        XCTAssertFalse(pinned.isFull)

        pinned.pin(makeSale(id: "sale-6"))
        XCTAssertEqual(pinned.pinned.count, PinnedComps.maxPins)
    }

    func testIsPinnedFalseForUnknownSale() {
        let pinned = PinnedComps()
        XCTAssertFalse(pinned.isPinned(makeSale()))
    }
}
