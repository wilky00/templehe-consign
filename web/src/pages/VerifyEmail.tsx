// ABOUTME: Email verification landing page — reads token from query string and calls /auth/verify-email.
// ABOUTME: Renders success/failure and a link back to login; idempotent on refresh (same token, same result).
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { verifyEmail } from "../api/auth";
import { ApiError } from "../api/client";
import { Alert } from "../components/ui/Alert";
import { Spinner } from "../components/ui/Spinner";
import { AuthShell } from "./Register";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

  // useQuery rather than useMutation so React Query's built-in dedup
  // prevents the token from being consumed twice. Plain useMutation inside
  // a useEffect double-fires under StrictMode (fresh useRef per remount),
  // which would succeed-then-fail as the account flips pending→active.
  const query = useQuery({
    queryKey: ["verify-email", token],
    queryFn: () => verifyEmail(token),
    enabled: !!token,
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  if (!token) {
    return (
      <AuthShell title="Verification link missing">
        <Alert tone="error" title="No token provided">
          The verification link is incomplete. Please click the exact link sent to
          your email.
        </Alert>
        <p className="mt-6 text-center text-sm text-gray-600">
          <Link to="/login" className="font-medium text-gray-900 underline">
            Back to login
          </Link>
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Verifying your email">
      {query.isLoading && (
        <div className="flex items-center justify-center py-6">
          <Spinner />
        </div>
      )}
      {query.isSuccess && (
        <>
          <Alert tone="success" title="Email verified">
            Your account is active. You can now log in.
          </Alert>
          <p className="mt-6 text-center text-sm text-gray-600">
            <Link to="/login" className="font-medium text-gray-900 underline">
              Go to login
            </Link>
          </p>
        </>
      )}
      {query.isError && (
        <>
          <Alert tone="error" title="Verification failed">
            {query.error instanceof ApiError
              ? query.error.detail
              : (query.error as Error).message}
          </Alert>
          <p className="mt-6 text-center text-sm text-gray-600">
            <Link to="/login" className="font-medium text-gray-900 underline">
              Back to login
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  );
}
