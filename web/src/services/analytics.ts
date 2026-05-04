// ABOUTME: Client-side analytics — fire-and-forget page_view events to /analytics/event.
// ABOUTME: usePageView() hook wires route changes; trackEvent() is the raw sender.
import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { request } from "../api/client";

function getSessionId(): string {
  const key = "templehe.session_id";
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

export async function trackEvent(
  event_type: string,
  page: string,
  metadata?: Record<string, unknown>,
): Promise<void> {
  try {
    await request("/analytics/event", {
      method: "POST",
      body: {
        session_id: getSessionId(),
        event_type,
        page,
        metadata: metadata ?? null,
      },
      skipAuth: true,
    });
  } catch {
    // best-effort — never surface analytics errors to the user
  }
}

export function usePageView(): void {
  const location = useLocation();
  const lastPath = useRef<string | null>(null);

  useEffect(() => {
    const path = location.pathname;
    if (path === lastPath.current) return;
    lastPath.current = path;
    void trackEvent("page_view", path);
  }, [location.pathname]);
}
