// ABOUTME: Top-level tab bar — Dashboard | New Appraisal | Calendar | Profile.
// ABOUTME: Sprint 0 stubs render a placeholder per tab; real screens land in later sprints.

import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            PlaceholderTab(title: "Dashboard", systemImage: "house")
            PlaceholderTab(title: "New Appraisal", systemImage: "plus.square")
            PlaceholderTab(title: "Calendar", systemImage: "calendar")
            PlaceholderTab(title: "Profile", systemImage: "person.crop.circle")
        }
    }
}

private struct PlaceholderTab: View {
    let title: String
    let systemImage: String

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                Image(systemName: systemImage)
                    .font(.system(size: 48))
                    .foregroundStyle(.secondary)
                Text(title)
                    .font(.title2)
                    .accessibilityIdentifier("placeholder-title-\(title)")
                Text("Sprint 0 scaffold — coming online in upcoming sprints.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding()
            .navigationTitle(title)
        }
        .tabItem {
            Label(title, systemImage: systemImage)
        }
        .accessibilityIdentifier("tab-\(title)")
    }
}

#Preview {
    RootView()
}
