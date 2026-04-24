// ABOUTME: Full-screen modal that forces re-acceptance when ToS or Privacy versions bump.
// ABOUTME: Driven by /auth/me.requires_terms_reaccept; posts to /legal/accept on confirm.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { acceptTerms, getConsentStatus, getPrivacy, getToS } from "../api/legal";
import { useMe } from "../hooks/useMe";
import { Alert } from "./ui/Alert";
import { Button } from "./ui/Button";
import { Spinner } from "./ui/Spinner";

export function ToSInterstitial() {
  const { data: user } = useMe();
  const qc = useQueryClient();
  const needsReaccept = Boolean(user?.requires_terms_reaccept);

  const { data: status } = useQuery({
    queryKey: ["legal", "consent-status"],
    queryFn: getConsentStatus,
    enabled: needsReaccept,
  });
  const { data: tos } = useQuery({
    queryKey: ["legal", "tos"],
    queryFn: getToS,
    enabled: needsReaccept,
  });
  const { data: privacy } = useQuery({
    queryKey: ["legal", "privacy"],
    queryFn: getPrivacy,
    enabled: needsReaccept,
  });

  const mutation = useMutation({
    mutationFn: () =>
      acceptTerms(status!.tos_current_version, status!.privacy_current_version),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["legal", "consent-status"] });
    },
  });

  if (!needsReaccept) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tos-interstitial-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <h2 id="tos-interstitial-title" className="text-lg font-semibold text-gray-900">
          Updated Terms of Service &amp; Privacy Policy
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          We've updated our Terms of Service and Privacy Policy. Please review and
          accept the current versions to continue.
        </p>

        {!tos || !privacy ? (
          <div className="mt-6 flex items-center justify-center py-10">
            <Spinner />
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <details className="rounded border border-gray-200 p-3" open>
              <summary className="cursor-pointer font-medium text-gray-900">
                Terms of Service (v{tos.version})
              </summary>
              <pre className="mt-3 whitespace-pre-wrap font-sans text-sm text-gray-700">
                {tos.body_markdown}
              </pre>
            </details>
            <details className="rounded border border-gray-200 p-3">
              <summary className="cursor-pointer font-medium text-gray-900">
                Privacy Policy (v{privacy.version})
              </summary>
              <pre className="mt-3 whitespace-pre-wrap font-sans text-sm text-gray-700">
                {privacy.body_markdown}
              </pre>
            </details>
          </div>
        )}

        {mutation.isError && (
          <div className="mt-4">
            <Alert tone="error" title="Could not record acceptance">
              {(mutation.error as Error).message}
            </Alert>
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <Button
            type="button"
            variant="primary"
            disabled={!status || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Recording…" : "I accept"}
          </Button>
        </div>
      </div>
    </div>
  );
}
