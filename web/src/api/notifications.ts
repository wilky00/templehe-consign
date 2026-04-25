// ABOUTME: Typed wrappers for /me/notification-preferences GET + PUT.
// ABOUTME: Returns ApiError on 404 (hidden) / 403 (RO) so the page can surface state.
import { ApiError, request } from "./client";
import type {
  NotificationPreference,
  NotificationPreferenceUpdateRequest,
} from "./types";

export async function getNotificationPreferences(): Promise<
  NotificationPreference | { hidden: true }
> {
  try {
    return await request<NotificationPreference>("/me/notification-preferences");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return { hidden: true };
    }
    throw e;
  }
}

export function updateNotificationPreferences(
  body: NotificationPreferenceUpdateRequest,
): Promise<NotificationPreference> {
  return request<NotificationPreference>("/me/notification-preferences", {
    method: "PUT",
    body,
  });
}
