// ABOUTME: Parses APNs notification payloads and routes tapped notifications to the correct screen.
// ABOUTME: Sprint 2 handles 'assignment' type; later sprints add 'sync_confirmation' etc.

import Foundation
import UserNotifications

/// The deep-link destination decoded from an APNs notification payload.
enum DeepLinkDestination: Equatable {
    /// Tap on an assignment push — navigate to the dashboard record with this ID.
    case assignmentDetail(recordID: String)
    /// Unknown or unsupported type — navigate to the dashboard root.
    case dashboardRoot
}

enum NotificationDeepLink {
    /// Parse a tapped notification's userInfo into a ``DeepLinkDestination``.
    ///
    /// Expected payload shape from the APNs job (set by `equipment_service.py`):
    /// ```json
    /// { "type": "assignment", "record_id": "<uuid>", "reference_number": "THE-XXXX" }
    /// ```
    static func destination(from response: UNNotificationResponse) -> DeepLinkDestination {
        let userInfo = response.notification.request.content.userInfo
        guard let type = userInfo["type"] as? String else {
            return .dashboardRoot
        }
        switch type {
        case "assignment":
            if let recordID = userInfo["record_id"] as? String {
                return .assignmentDetail(recordID: recordID)
            }
            return .dashboardRoot
        default:
            return .dashboardRoot
        }
    }
}
