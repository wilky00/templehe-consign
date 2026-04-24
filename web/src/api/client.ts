// ABOUTME: Fetch wrapper for the TempleHE API — Bearer header, cookie-based refresh, auto 401 retry.
// ABOUTME: Every endpoint client (auth.ts, equipment.ts, ...) imports `request` from here.
import { useAuthStore } from "../state/auth";

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  // When true, skip the access-token header (used by login/register/refresh).
  skipAuth?: boolean;
  // When true, don't attempt the 401 → refresh → retry dance.
  skipRefresh?: boolean;
}

async function parseJsonSafely(resp: Response): Promise<unknown> {
  const text = await resp.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function attemptRefresh(): Promise<string | null> {
  // The refresh cookie is HttpOnly + scoped to /api/v1/auth; the browser
  // attaches it automatically when credentials: 'include' is set.
  const resp = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!resp.ok) return null;
  const body = (await parseJsonSafely(resp)) as { access_token?: string } | null;
  return body?.access_token ?? null;
}

export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, skipAuth, skipRefresh } = opts;
  const headers: Record<string, string> = {};

  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (!skipAuth) {
    const token = useAuthStore.getState().accessToken;
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const doFetch = async (): Promise<Response> =>
    fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let resp = await doFetch();

  if (resp.status === 401 && !skipAuth && !skipRefresh) {
    const newToken = await attemptRefresh();
    if (newToken) {
      useAuthStore.getState().setAccessToken(newToken);
      headers["Authorization"] = `Bearer ${newToken}`;
      resp = await doFetch();
    } else {
      useAuthStore.getState().clear();
    }
  }

  if (!resp.ok) {
    const parsed = (await parseJsonSafely(resp)) as
      | { detail?: string }
      | string
      | null;
    const detail =
      typeof parsed === "string"
        ? parsed
        : parsed?.detail ?? `HTTP ${resp.status}`;
    throw new ApiError(resp.status, detail);
  }

  if (resp.status === 204) return undefined as T;
  return (await parseJsonSafely(resp)) as T;
}
