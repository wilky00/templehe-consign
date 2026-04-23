// ABOUTME: React Query hook for /auth/me. Used by ProtectedRoute and ToSInterstitial.
// ABOUTME: Fails silently if there's no access token — the route guard handles redirects.
import { useQuery } from "@tanstack/react-query";
import { me } from "../api/auth";
import { useAuthStore } from "../state/auth";

export function useMe() {
  const token = useAuthStore((s) => s.accessToken);
  return useQuery({
    queryKey: ["me", token],
    queryFn: me,
    enabled: Boolean(token),
    staleTime: 30_000,
  });
}
