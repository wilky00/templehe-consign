// ABOUTME: Account page — email preferences, data export requests, and account deletion grace management.
// ABOUTME: Shows the current deletion_grace_until when status is pending_deletion so the user knows the clock.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelAccountDeletion,
  getEmailPrefs,
  listDataExports,
  requestAccountDeletion,
  requestDataExport,
  updateEmailPrefs,
} from "../api/account";
import { ApiError } from "../api/client";
import type { EmailPrefs } from "../api/types";
import { useMe } from "../hooks/useMe";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Checkbox } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function AccountPage() {
  const { data: me } = useMe();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Account</h1>
        <p className="mt-1 text-sm text-gray-600">
          Signed in as <strong>{me?.email}</strong>.
        </p>
      </div>

      <EmailPrefsCard />
      <DataExportCard />
      <DeletionCard />
    </div>
  );
}

function EmailPrefsCard() {
  const qc = useQueryClient();
  const prefsQuery = useQuery({
    queryKey: ["email-prefs"],
    queryFn: getEmailPrefs,
  });
  const [draft, setDraft] = useState<EmailPrefs | null>(null);

  useEffect(() => {
    if (prefsQuery.data) setDraft(prefsQuery.data);
  }, [prefsQuery.data]);

  const mutation = useMutation({
    mutationFn: (body: EmailPrefs) => updateEmailPrefs(body),
    onSuccess: (data) => {
      qc.setQueryData(["email-prefs"], data);
    },
  });

  if (!draft) {
    return (
      <Card>
        <h2 className="text-base font-medium text-gray-900">Email preferences</h2>
        <div className="mt-3">
          <Spinner />
        </div>
      </Card>
    );
  }

  const set = (key: keyof EmailPrefs, value: boolean) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d));

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Email preferences</h2>
      <div className="mt-4 space-y-3">
        <Checkbox
          id="pref-intake"
          label="Intake confirmations"
          description="Receipt + reference number when you submit equipment."
          checked={draft.intake_confirmations}
          onChange={(e) => set("intake_confirmations", e.target.checked)}
        />
        <Checkbox
          id="pref-status"
          label="Status updates"
          description="Appraisal scheduled, complete, listed, sold, etc."
          checked={draft.status_updates}
          onChange={(e) => set("status_updates", e.target.checked)}
        />
        <Checkbox
          id="pref-marketing"
          label="Marketing"
          description="Occasional product updates. Off by default."
          checked={draft.marketing}
          onChange={(e) => set("marketing", e.target.checked)}
        />
        <Checkbox
          id="pref-sms"
          label="SMS opt-in"
          description="Text message updates (requires a cell number on your profile)."
          checked={draft.sms_opt_in}
          onChange={(e) => set("sms_opt_in", e.target.checked)}
        />
      </div>
      {mutation.isError && (
        <div className="mt-3">
          <Alert tone="error" title="Could not save preferences">
            {(mutation.error as Error).message}
          </Alert>
        </div>
      )}
      {mutation.isSuccess && !mutation.isPending && (
        <div className="mt-3">
          <Alert tone="success" title="Preferences saved" />
        </div>
      )}
      <div className="mt-4">
        <Button
          onClick={() => mutation.mutate(draft)}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Saving…" : "Save preferences"}
        </Button>
      </div>
    </Card>
  );
}

function DataExportCard() {
  const qc = useQueryClient();
  const listQuery = useQuery({
    queryKey: ["data-exports"],
    queryFn: listDataExports,
  });

  const mutation = useMutation({
    mutationFn: requestDataExport,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["data-exports"] });
    },
  });

  const latest = listQuery.data?.[0] ?? null;

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Download my data</h2>
      <p className="mt-1 text-sm text-gray-600">
        We'll package everything we hold about you as a single zip. The download
        link is valid for 7 days and is also emailed to you.
      </p>

      {mutation.isError && (
        <div className="mt-3">
          <Alert tone="error" title="Export failed">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
          </Alert>
        </div>
      )}

      {latest && (
        <div className="mt-4 rounded-md border border-gray-200 p-3 text-sm">
          <p className="text-gray-900">
            Latest export: <strong>{latest.status}</strong>
          </p>
          <p className="text-gray-600">Requested {fmt(latest.requested_at)}</p>
          {latest.download_url && (
            <a
              href={latest.download_url}
              className="mt-2 inline-block font-medium text-gray-900 underline"
              rel="noreferrer"
            >
              Download zip
            </a>
          )}
          {latest.url_expires_at && (
            <p className="mt-1 text-xs text-gray-500">
              Link expires {fmt(latest.url_expires_at)}
            </p>
          )}
        </div>
      )}

      <div className="mt-4">
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          {mutation.isPending ? "Generating…" : "Request new export"}
        </Button>
      </div>
    </Card>
  );
}

function DeletionCard() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [confirmed, setConfirmed] = useState(false);

  const isPending = me?.status === "pending_deletion";

  const requestMutation = useMutation({
    mutationFn: requestAccountDeletion,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: cancelAccountDeletion,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Delete my account</h2>
      <p className="mt-1 text-sm text-gray-600">
        Deletion starts a 30-day grace period. During that time your account is
        still active and you can cancel. After 30 days your personal information
        is scrubbed — equipment records remain as business history but are no
        longer linked to you.
      </p>

      {isPending && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          <p className="font-medium">
            Deletion is scheduled. You can cancel any time before the grace
            period ends.
          </p>
          {cancelMutation.isError && (
            <p className="mt-2 text-red-700">
              {(cancelMutation.error as Error).message}
            </p>
          )}
          <div className="mt-3">
            <Button
              variant="secondary"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending ? "Cancelling…" : "Cancel deletion"}
            </Button>
          </div>
        </div>
      )}

      {!isPending && (
        <>
          <div className="mt-4">
            <Checkbox
              id="confirm-delete"
              label="I understand this starts a 30-day grace period and my personal information will be scrubbed afterwards."
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
          </div>
          {requestMutation.isError && (
            <div className="mt-3">
              <Alert tone="error" title="Could not request deletion">
                {(requestMutation.error as Error).message}
              </Alert>
            </div>
          )}
          <div className="mt-4">
            <Button
              variant="danger"
              onClick={() => requestMutation.mutate()}
              disabled={!confirmed || requestMutation.isPending}
            >
              {requestMutation.isPending ? "Scheduling…" : "Delete my account"}
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}
