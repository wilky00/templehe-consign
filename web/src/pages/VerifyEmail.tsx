// ABOUTME: Email verification landing page — reads token from query string and calls /auth/verify-email.
// ABOUTME: Renders success/failure and a link back to login; idempotent on refresh (same token, same result).
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { verifyEmail } from "../api/auth";
import { ApiError } from "../api/client";
import { Alert } from "../components/ui/Alert";
import { Spinner } from "../components/ui/Spinner";
import { AuthShell } from "./Register";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

  const mutation = useMutation({ mutationFn: verifyEmail });

  useEffect(() => {
    if (token) {
      mutation.mutate(token);
    }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

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
      {mutation.isPending && (
        <div className="flex items-center justify-center py-6">
          <Spinner />
        </div>
      )}
      {mutation.isSuccess && (
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
      {mutation.isError && (
        <>
          <Alert tone="error" title="Verification failed">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
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
