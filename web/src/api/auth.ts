// ABOUTME: Typed wrappers for /api/v1/auth/* — register, login, logout, /me.
// ABOUTME: Refresh is internal to the client (see api/client.ts).
import { request } from "./client";
import type {
  CurrentUser,
  RegisterRequest,
  RegisterResponse,
  TokenResponse,
} from "./types";

export function register(body: RegisterRequest): Promise<RegisterResponse> {
  return request<RegisterResponse>("/auth/register", {
    method: "POST",
    body,
    skipAuth: true,
  });
}

export interface LoginBody {
  email: string;
  password: string;
}

export function login(body: LoginBody): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body,
    skipAuth: true,
  });
}

export function logout(): Promise<{ message: string }> {
  return request<{ message: string }>("/auth/logout", {
    method: "POST",
    skipRefresh: true,
  });
}

export function me(): Promise<CurrentUser> {
  return request<CurrentUser>("/auth/me");
}

export function verifyEmail(token: string): Promise<{ message: string }> {
  return request<{ message: string }>(
    `/auth/verify-email?token=${encodeURIComponent(token)}`,
    { skipAuth: true },
  );
}
