// ABOUTME: Zustand store for the access token — refresh lives in an HttpOnly cookie, not here.
// ABOUTME: Token is persisted to sessionStorage so reloads survive; cleared on logout or 401.
import { create } from "zustand";

const STORAGE_KEY = "templehe.access_token";

interface AuthState {
  accessToken: string | null;
  setAccessToken: (token: string) => void;
  clear: () => void;
}

function loadToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistToken(token: string | null): void {
  try {
    if (token === null) {
      sessionStorage.removeItem(STORAGE_KEY);
    } else {
      sessionStorage.setItem(STORAGE_KEY, token);
    }
  } catch {
    // Storage unavailable (private mode on some browsers) — fall through.
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: loadToken(),
  setAccessToken: (token) => {
    persistToken(token);
    set({ accessToken: token });
  },
  clear: () => {
    persistToken(null);
    set({ accessToken: null });
  },
}));
