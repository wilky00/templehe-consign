// ABOUTME: Appraiser dashboard — Today, Upcoming, Drafts (placeholder), Recent (placeholder).
// ABOUTME: Fetches appointments from GET /api/v1/me/appointments; pull-to-refresh supported.

import SwiftUI

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published private(set) var appointments: [AppointmentDetail] = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    private let client: TempleHEClientProtocol

    init(client: TempleHEClientProtocol) {
        self.client = client
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let resp: AppointmentListResponse = try await client.request(
                "GET",
                path: "\(Endpoint.meAppointments)?days=30",
                body: Optional<String>.none,
                authenticated: true
            )
            appointments = resp.appointments
        } catch {
            errorMessage = "Could not load appointments. Pull to refresh."
        }
    }

    // Today = scheduled within the next 24 hours.
    var today: [AppointmentDetail] {
        let cutoff = Date().addingTimeInterval(86_400)
        return appointments.filter { parseDate($0.scheduled_at) <= cutoff }
    }

    var upcoming: [AppointmentDetail] {
        let cutoff = Date().addingTimeInterval(86_400)
        return appointments.filter { parseDate($0.scheduled_at) > cutoff }
    }

    // Placeholders until Core Data lands in Sprint 4.
    var drafts: [AppointmentDetail] { [] }
    var recent: [AppointmentDetail] { [] }

    private func parseDate(_ raw: String) -> Date {
        ISO8601DateFormatter().date(from: raw) ?? .distantFuture
    }
}

// MARK: - View

struct DashboardView: View {
    @StateObject private var viewModel: DashboardViewModel
    @EnvironmentObject private var auth: AuthState

    init(client: TempleHEClientProtocol) {
        _viewModel = StateObject(wrappedValue: DashboardViewModel(client: client))
    }

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.isLoading && viewModel.appointments.isEmpty {
                    ProgressView("Loading…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    appointmentsList
                }
            }
            .navigationTitle("Dashboard")
        }
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
        .accessibilityIdentifier("dashboard-view")
    }

    private var appointmentsList: some View {
        List {
            if let msg = viewModel.errorMessage {
                Section {
                    Text(msg)
                        .foregroundStyle(.secondary)
                        .accessibilityLabel("Error: \(msg)")
                }
            }

            dashboardSection("Today", items: viewModel.today)
            dashboardSection("Upcoming", items: viewModel.upcoming)
            dashboardSection("Drafts", items: viewModel.drafts, emptyPlaceholder: "No drafts.")
            dashboardSection("Recent", items: viewModel.recent, emptyPlaceholder: "No recent appraisals.")
        }
        .listStyle(.insetGrouped)
    }

    private func dashboardSection(
        _ title: String,
        items: [AppointmentDetail],
        emptyPlaceholder: String? = nil
    ) -> some View {
        Section(title) {
            if items.isEmpty {
                if let placeholder = emptyPlaceholder {
                    Text(placeholder)
                        .foregroundStyle(.tertiary)
                        .font(.subheadline)
                } else {
                    EmptyView()
                }
            } else {
                ForEach(items) { appt in
                    AssignmentCard(appointment: appt)
                        .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                        .listRowSeparator(.hidden)
                        .accessibilityIdentifier("assignment-card-\(appt.calendar_event_id)")
                }
            }
        }
        .accessibilityIdentifier("section-\(title.lowercased())")
    }
}
