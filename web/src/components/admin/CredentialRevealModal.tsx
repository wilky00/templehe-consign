// ABOUTME: Phase 4 Sprint 7 — step-up modal for revealing an integration credential.
// ABOUTME: Asks for password + TOTP, displays plaintext for 30s with countdown auto-mask.
import { useEffect, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { revealAdminIntegration } from "../../api/admin";
import { ApiError } from "../../api/client";
import type {
  IntegrationName,
  IntegrationRevealResponse,
} from "../../api/types";

interface Props {
  name: IntegrationName;
  onClose: () => void;
}

const REVEAL_DURATION_SECONDS = 30;

export function CredentialRevealModal({ name, onClose }: Props) {
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [revealed, setRevealed] = useState<IntegrationRevealResponse | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(REVEAL_DURATION_SECONDS);

  const mutation = useMutation({
    mutationFn: () =>
      revealAdminIntegration(name, { password, totp_code: totpCode }),
    onSuccess: (data) => {
      setRevealed(data);
      setPassword("");
      setTotpCode("");
      setSecondsLeft(REVEAL_DURATION_SECONDS);
    },
  });

  // Countdown auto-mask once revealed.
  useEffect(() => {
    if (!revealed) return;
    if (secondsLeft <= 0) {
      setRevealed(null);
      return;
    }
    const t = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [revealed, secondsLeft]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reveal-title"
    >
      <Card className="w-full max-w-md">
        <h2 id="reveal-title" className="text-lg font-semibold text-gray-900">
          Reveal {name} credential
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Verify your identity. Plaintext stays visible for{" "}
          {REVEAL_DURATION_SECONDS} seconds, then auto-masks.
        </p>

        {revealed ? (
          <div className="mt-4 space-y-3">
            <div
              className="break-all rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 font-mono text-sm text-gray-900"
              data-testid="revealed-plaintext"
            >
              {revealed.plaintext}
            </div>
            <div className="text-xs text-gray-600">
              Auto-masking in {secondsLeft}s.
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-4 space-y-4">
            <label className="block text-sm">
              <span className="font-medium text-gray-700">Password</span>
              <input
                required
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-gray-700">
                Authenticator code
              </span>
              <input
                required
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="one-time-code"
                minLength={4}
                maxLength={10}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.trim())}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono"
              />
            </label>
            {errorDetail && (
              <Alert tone="error" title="Step-up failed">
                {errorDetail}
              </Alert>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={mutation.isPending}>
                {mutation.isPending ? "Verifying…" : "Reveal"}
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}
