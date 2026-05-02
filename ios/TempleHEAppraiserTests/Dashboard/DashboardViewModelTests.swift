// ABOUTME: DashboardViewModel unit tests — appointment grouping into Today/Upcoming sections.
// ABOUTME: Uses MockTempleHEClient to avoid real network calls.

import XCTest
@testable import TempleHEAppraiser

final class DashboardViewModelTests: XCTestCase {

    // MARK: - Helpers

    private func makeAppointment(
        id: String = UUID().uuidString,
        offsetSeconds: TimeInterval,
        status: String = "scheduled",
        make: String? = "CAT",
        model: String? = "320",
        year: Int? = 2021
    ) -> AppointmentDetail {
        let date = Date().addingTimeInterval(offsetSeconds)
        let formatter = ISO8601DateFormatter()
        return AppointmentDetail(
            calendar_event_id: id,
            equipment_record_id: UUID().uuidString,
            reference_number: "THE-\(id.prefix(6).uppercased())",
            scheduled_at: formatter.string(from: date),
            duration_minutes: 90,
            site_address: "123 Test St",
            record_status: status,
            customer_make: make,
            customer_model: model,
            customer_year: year,
            customer_name: "Test Customer",
            customer_phone: "555-000-1111",
            sales_rep_name: "Rep Name",
            sales_rep_phone: nil,
            sales_rep_email: "rep@example.com"
        )
    }

    private func makeViewModel(appointments: [AppointmentDetail]) -> DashboardViewModel {
        let client = MockDashboardClient(appointments: appointments)
        return DashboardViewModel(client: client)
    }

    // MARK: - Section grouping

    @MainActor
    func testTodaySection_containsEventsWithin24Hours() async {
        let near = makeAppointment(offsetSeconds: 3_600)    // 1 h from now
        let far  = makeAppointment(offsetSeconds: 90_000)   // 25 h from now
        let vm   = makeViewModel(appointments: [near, far])
        await vm.load()

        XCTAssertEqual(vm.today.count, 1)
        XCTAssertEqual(vm.today.first?.calendar_event_id, near.calendar_event_id)
    }

    @MainActor
    func testUpcomingSection_excludesEventsWithin24Hours() async {
        let near = makeAppointment(offsetSeconds: 3_600)
        let far  = makeAppointment(offsetSeconds: 90_000)
        let vm   = makeViewModel(appointments: [near, far])
        await vm.load()

        XCTAssertEqual(vm.upcoming.count, 1)
        XCTAssertEqual(vm.upcoming.first?.calendar_event_id, far.calendar_event_id)
    }

    @MainActor
    func testDraftsPlaceholderIsEmpty() async {
        let vm = makeViewModel(appointments: [makeAppointment(offsetSeconds: 3_600)])
        await vm.load()
        XCTAssertTrue(vm.drafts.isEmpty)
    }

    @MainActor
    func testRecentPlaceholderIsEmpty() async {
        let vm = makeViewModel(appointments: [])
        await vm.load()
        XCTAssertTrue(vm.recent.isEmpty)
    }

    @MainActor
    func testLoadSetsErrorOnFailure() async {
        let client = FailingDashboardClient()
        let vm = DashboardViewModel(client: client)
        await vm.load()
        XCTAssertNotNil(vm.errorMessage)
        XCTAssertFalse(vm.isLoading)
    }

    @MainActor
    func testMakeModelYearConcatenation() {
        let appt = makeAppointment(offsetSeconds: 3_600, make: "Komatsu", model: "PC360", year: 2022)
        XCTAssertEqual(appt.makeModelYear, "Komatsu PC360 2022")
    }

    @MainActor
    func testMakeModelYearWithNilsIsGraceful() {
        let appt = makeAppointment(offsetSeconds: 3_600, make: nil, model: nil, year: nil)
        XCTAssertEqual(appt.makeModelYear, "")
    }
}

// MARK: - Mock clients

private final class MockDashboardClient: TempleHEClientProtocol {
    private let appointments: [AppointmentDetail]

    init(appointments: [AppointmentDetail]) {
        self.appointments = appointments
    }

    func request<Body: Encodable, Response: Decodable>(
        _ method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws -> Response {
        let resp = AppointmentListResponse(appointments: appointments, days_ahead: 30)
        let data = try JSONEncoder().encode(resp)
        return try JSONDecoder().decode(Response.self, from: data)
    }

    func request<Body: Encodable>(
        _ method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws {}

    func setTokens(access: String, refresh: String?) throws {}
    func clearTokens() throws {}
    func currentAccessToken() -> String? { "fake-token" }
}

private final class FailingDashboardClient: TempleHEClientProtocol {
    func request<Body: Encodable, Response: Decodable>(
        _ method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws -> Response {
        throw URLError(.notConnectedToInternet)
    }

    func request<Body: Encodable>(
        _ method: String,
        path: String,
        body: Body?,
        authenticated: Bool
    ) async throws {}

    func setTokens(access: String, refresh: String?) throws {}
    func clearTokens() throws {}
    func currentAccessToken() -> String? { nil }
}
