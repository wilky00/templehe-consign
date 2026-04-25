// ABOUTME: Calendar API client wrappers — list / create / patch / cancel events.
// ABOUTME: 409 conflict from POST/PATCH is parsed into a typed CalendarConflict so the UI can offer "next available".
import { API_BASE_URL, ApiError } from "./client";
import { useAuthStore } from "../state/auth";
import type {
  CalendarConflict,
  CalendarEvent,
  CalendarEventCreateRequest,
  CalendarEventListResponse,
  CalendarEventPatchRequest,
  ISODateTime,
  UUID,
} from "./types";

export interface ListEventsQuery {
  start: ISODateTime;
  end: ISODateTime;
  appraiserId?: UUID;
}

export type CreateOrPatchResult =
  | { ok: true; event: CalendarEvent }
  | { ok: false; conflict: CalendarConflict };

async function authedFetch(
  path: string,
  init: RequestInit,
): Promise<Response> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body) headers["Content-Type"] = "application/json";
  const token = useAuthStore.getState().accessToken;
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
}

async function parseJson(resp: Response): Promise<unknown> {
  const text = await resp.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function listCalendarEvents(
  q: ListEventsQuery,
): Promise<CalendarEventListResponse> {
  const params = new URLSearchParams({ start: q.start, end: q.end });
  if (q.appraiserId) params.set("appraiser_id", q.appraiserId);
  const resp = await authedFetch(`/calendar/events?${params.toString()}`, {
    method: "GET",
  });
  if (!resp.ok) {
    const body = (await parseJson(resp)) as { detail?: string } | null;
    throw new ApiError(resp.status, body?.detail ?? `HTTP ${resp.status}`);
  }
  return (await parseJson(resp)) as CalendarEventListResponse;
}

export async function createCalendarEvent(
  body: CalendarEventCreateRequest,
): Promise<CreateOrPatchResult> {
  const resp = await authedFetch("/calendar/events", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return _resolveCreateOrPatch(resp);
}

export async function patchCalendarEvent(
  id: UUID,
  body: CalendarEventPatchRequest,
): Promise<CreateOrPatchResult> {
  const resp = await authedFetch(`/calendar/events/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return _resolveCreateOrPatch(resp);
}

export async function cancelCalendarEvent(id: UUID): Promise<CalendarEvent> {
  const resp = await authedFetch(`/calendar/events/${id}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const body = (await parseJson(resp)) as { detail?: string } | null;
    throw new ApiError(resp.status, body?.detail ?? `HTTP ${resp.status}`);
  }
  return (await parseJson(resp)) as CalendarEvent;
}

async function _resolveCreateOrPatch(
  resp: Response,
): Promise<CreateOrPatchResult> {
  if (resp.status === 409) {
    const body = (await parseJson(resp)) as CalendarConflict;
    return { ok: false, conflict: body };
  }
  if (!resp.ok) {
    const body = (await parseJson(resp)) as { detail?: string } | null;
    throw new ApiError(resp.status, body?.detail ?? `HTTP ${resp.status}`);
  }
  const event = (await parseJson(resp)) as CalendarEvent;
  return { ok: true, event };
}
