// ABOUTME: Client-side analytics — fire-and-forget page_view events to /analytics/event.
// ABOUTME: usePageView() tracks route changes; useFormAnalytics() instruments multi-step forms.
import { useCallback, useEffect, useRef } from "react";
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

// Fires form_step_start on mount, form_step_complete on onComplete(), and
// form_abandon on unmount if onComplete() was never called.
export function useFormAnalytics(formName: string): { onComplete: () => void } {
  const formNameRef = useRef(formName);
  const completedRef = useRef(false);

  useEffect(() => {
    const page = window.location.pathname;
    const form = formNameRef.current;
    void trackEvent("form_step_start", page, { form });
    return () => {
      if (!completedRef.current) {
        void trackEvent("form_abandon", page, { form });
      }
    };
  }, []); // intentional: fires once on mount only

  const onComplete = useCallback(() => {
    completedRef.current = true;
    void trackEvent("form_step_complete", window.location.pathname, {
      form: formNameRef.current,
    });
  }, []);

  return { onComplete };
}
