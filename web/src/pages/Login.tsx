// ABOUTME: Login page — email+password → /auth/login → stores access token + redirects to portal.
// ABOUTME: 2FA flow is deferred to Phase 5 iOS; partial-token responses currently fall through to an error.
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { login } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuthStore } from "../state/auth";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { TextInput } from "../components/ui/Input";
import { AuthShell } from "./Register";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const navigate = useNavigate();
  const location = useLocation();
  const from =
    (location.state as { from?: { pathname: string } } | null)?.from?.pathname ??
    "/portal";

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      useAuthStore.getState().setAccessToken(data.access_token);
      navigate(from, { replace: true });
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate({ email, password });
  };

  return (
    <AuthShell title="Log in to your account">
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <TextInput
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <TextInput
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {mutation.isError && (
          <Alert tone="error" title="Login failed">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
          </Alert>
        )}

        <Button
          type="submit"
          size="lg"
          className="w-full"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Signing in…" : "Log in"}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-gray-600">
        New to Temple Heavy Equipment?{" "}
        <Link to="/register" className="font-medium text-gray-900 underline">
          Create an account
        </Link>
      </p>
    </AuthShell>
  );
}
