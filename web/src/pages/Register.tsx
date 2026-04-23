// ABOUTME: Customer sign-up page. Fetches current ToS/Privacy versions and echoes them on register.
// ABOUTME: Success directs the user to a "check your inbox" confirmation — they must verify email to log in.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { register as registerApi } from "../api/auth";
import { getPrivacy, getToS } from "../api/legal";
import { ApiError } from "../api/client";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Checkbox, TextInput } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [accepted, setAccepted] = useState(false);

  const tosQuery = useQuery({ queryKey: ["legal", "tos"], queryFn: getToS });
  const privacyQuery = useQuery({
    queryKey: ["legal", "privacy"],
    queryFn: getPrivacy,
  });

  const mutation = useMutation({
    mutationFn: registerApi,
  });

  const canSubmit =
    accepted && tosQuery.data && privacyQuery.data && !mutation.isPending;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!tosQuery.data || !privacyQuery.data) return;
    mutation.mutate({
      email,
      password,
      first_name: firstName,
      last_name: lastName,
      tos_version: tosQuery.data.version,
      privacy_version: privacyQuery.data.version,
    });
  };

  if (mutation.isSuccess) {
    return (
      <AuthShell title="Check your email">
        <Alert tone="success" title="Registration received">
          We sent a verification link to <strong>{email}</strong>. Click the link to
          activate your account, then log in.
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
    <AuthShell title="Create your account">
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <TextInput
          id="first_name"
          label="First name"
          autoComplete="given-name"
          required
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
        />
        <TextInput
          id="last_name"
          label="Last name"
          autoComplete="family-name"
          required
          value={lastName}
          onChange={(e) => setLastName(e.target.value)}
        />
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
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint="Minimum 12 characters, including an uppercase letter, a number, and a symbol."
        />

        {(tosQuery.isLoading || privacyQuery.isLoading) && (
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <Spinner size="sm" /> Loading current terms…
          </div>
        )}

        {tosQuery.data && privacyQuery.data && (
          <Checkbox
            id="accept"
            label={`I agree to the Terms of Service (v${tosQuery.data.version}) and Privacy Policy (v${privacyQuery.data.version})`}
            description="Links to both documents are available on our public site."
            required
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
          />
        )}

        {mutation.isError && (
          <Alert tone="error" title="Registration failed">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
          </Alert>
        )}

        <Button type="submit" size="lg" className="w-full" disabled={!canSubmit}>
          {mutation.isPending ? "Creating account…" : "Create account"}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-gray-600">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-gray-900 underline">
          Log in
        </Link>
      </p>
    </AuthShell>
  );
}

export function AuthShell({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-gray-50 px-4 py-10 sm:px-6">
      <div className="mx-auto max-w-md">
        <h1 className="text-center text-2xl font-semibold text-gray-900">
          Temple Heavy Equipment
        </h1>
        <p className="mt-1 text-center text-sm text-gray-600">{title}</p>
        <div className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          {children}
        </div>
      </div>
    </div>
  );
}
