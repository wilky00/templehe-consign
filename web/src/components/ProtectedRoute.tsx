// ABOUTME: Route guard — redirects to /login when there is no access token or /auth/me fails.
// ABOUTME: Wrap customer portal routes in this; public routes (login, register) do not need it.
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "../state/auth";
import { useMe } from "../hooks/useMe";
import { Spinner } from "./ui/Spinner";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.accessToken);
  const location = useLocation();
  const { data: user, isLoading, isError } = useMe();

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <Spinner />
      </div>
    );
  }
  if (isError || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}
