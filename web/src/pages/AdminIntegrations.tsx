// ABOUTME: Phase 4 Sprint 7 — admin manages integration credentials from the SPA.
// ABOUTME: One card per integration with Save/Test/Reveal. Twilio's edit form has 3 fields.
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { CredentialRevealModal } from "../components/admin/CredentialRevealModal";
import {
  listAdminIntegrations,
  storeAdminIntegration,
  testAdminIntegration,
} from "../api/admin";
import { ApiError } from "../api/client";
import type {
  IntegrationName,
  IntegrationOut,
} from "../api/types";

const FRIENDLY_NAMES: Record<IntegrationName, string> = {
  slack: "Slack",
  twilio: "Twilio",
  sendgrid: "SendGrid",
  google_maps: "Google Maps",
  esign: "eSign provider",
  valuation: "Valuation API",
};

const HELP_TEXT: Record<IntegrationName, string> = {
  slack:
    "Webhook URL (https://hooks.slack.com/services/…). Test posts a tiny message.",
  twilio:
    "Account SID, Auth Token, From Number. Stored as one JSON blob; the test validates the credentials with no SMS unless you supply a number.",
  sendgrid:
    "API Key starting with SG.. The test calls /v3/scopes — no email is sent.",
  google_maps:
    "API key authorized for the Geocoding API. The test geocodes a sample US address.",
  esign:
    "Phase 6 wiring — the test button reports 'stubbed' until a real provider lands.",
  valuation:
    "Phase 5+ wiring — the test button reports 'stubbed' until a real provider lands.",
};

export function AdminIntegrationsPage() {
  const query = useQuery({
    queryKey: ["admin-integrations"],
    queryFn: listAdminIntegrations,
  });

  const [revealName, setRevealName] = useState<IntegrationName | null>(null);

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load integrations">
        {(query.error as Error).message}
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Integrations</h1>
        <p className="mt-1 text-sm text-gray-600">
          Manage credentials for outbound integrations. Plaintext is encrypted
          at rest; reveal requires step-up auth (password + authenticator
          code) and is rate-limited.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {query.data!.integrations.map((integration) => (
          <IntegrationCard
            key={integration.name}
            integration={integration}
            onRevealClick={() => setRevealName(integration.name)}
          />
        ))}
      </div>

      {revealName && (
        <CredentialRevealModal
          name={revealName}
          onClose={() => setRevealName(null)}
        />
      )}
    </div>
  );
}

interface CardProps {
  integration: IntegrationOut;
  onRevealClick: () => void;
}

function IntegrationCard({ integration, onRevealClick }: CardProps) {
  const qc = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);

  const test = useMutation({
    mutationFn: () => testAdminIntegration(integration.name),
    onSettled: () => qc.invalidateQueries({ queryKey: ["admin-integrations"] }),
  });

  const lastTestBadge = renderLastTestBadge(integration);

  const stubbed = integration.name === "esign" || integration.name === "valuation";

  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            {FRIENDLY_NAMES[integration.name]}
          </h2>
          <p className="mt-1 text-xs text-gray-500">{HELP_TEXT[integration.name]}</p>
        </div>
        <span
          className={`shrink-0 rounded-md px-2 py-1 text-xs font-medium ${
            integration.is_set
              ? "bg-emerald-100 text-emerald-800"
              : "bg-gray-100 text-gray-600"
          }`}
        >
          {integration.is_set ? "configured" : "not set"}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 text-sm text-gray-700">
        <div>
          <span className="text-gray-500">Last set:</span>{" "}
          {integration.set_at ? new Date(integration.set_at).toLocaleString() : "—"}
        </div>
        <div>
          <span className="text-gray-500">Last tested:</span>{" "}
          {integration.last_tested_at
            ? new Date(integration.last_tested_at).toLocaleString()
            : "—"}
        </div>
      </div>

      {lastTestBadge}

      {test.isError && (
        <Alert tone="error" title="Test failed">
          {(test.error as Error).message}
        </Alert>
      )}
      {test.isSuccess && (
        <Alert tone={test.data.success ? "success" : "error"}>
          {test.data.detail}
          {typeof test.data.latency_ms === "number" && (
            <span className="ml-2 text-xs text-gray-600">
              ({test.data.latency_ms} ms)
            </span>
          )}
        </Alert>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          type="button"
          variant="primary"
          onClick={() => setEditOpen((o) => !o)}
        >
          {integration.is_set ? "Update" : "Save"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={!integration.is_set || test.isPending}
          onClick={() => test.mutate()}
        >
          {test.isPending ? "Testing…" : stubbed ? "Test (stubbed)" : "Test"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={!integration.is_set}
          onClick={onRevealClick}
        >
          Reveal
        </Button>
      </div>

      {editOpen && (
        <EditCredentialForm
          integration={integration}
          onClose={() => setEditOpen(false)}
        />
      )}
    </Card>
  );
}

function renderLastTestBadge(integration: IntegrationOut) {
  if (!integration.last_test_status) return null;
  const isOk = integration.last_test_status === "success";
  const isStub = integration.last_test_status === "stubbed";
  const cls = isOk
    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
    : isStub
      ? "border-blue-300 bg-blue-50 text-blue-900"
      : "border-red-300 bg-red-50 text-red-900";
  return (
    <div className={`mt-3 rounded-md border px-3 py-2 text-xs ${cls}`}>
      <span className="font-medium uppercase">{integration.last_test_status}</span>
      {integration.last_test_detail && (
        <span className="ml-2">{integration.last_test_detail}</span>
      )}
    </div>
  );
}

interface EditFormProps {
  integration: IntegrationOut;
  onClose: () => void;
}

function EditCredentialForm({ integration, onClose }: EditFormProps) {
  const qc = useQueryClient();

  // Twilio = multi-field. Everything else = single text input.
  const isTwilio = integration.name === "twilio";

  const [single, setSingle] = useState("");
  const [twilio, setTwilio] = useState({
    account_sid: "",
    auth_token: "",
    from_number: "",
  });

  const mutation = useMutation({
    mutationFn: () => {
      const plaintext = isTwilio ? JSON.stringify(twilio) : single;
      return storeAdminIntegration(integration.name, { plaintext });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-integrations"] });
      onClose();
    },
  });

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
    <form
      onSubmit={onSubmit}
      className="mt-4 space-y-3 rounded-md border border-gray-200 bg-gray-50 p-4"
    >
      {isTwilio ? (
        <>
          <FieldInput
            label="Account SID"
            value={twilio.account_sid}
            onChange={(v) => setTwilio({ ...twilio, account_sid: v })}
            placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            mono
          />
          <FieldInput
            label="Auth Token"
            value={twilio.auth_token}
            onChange={(v) => setTwilio({ ...twilio, auth_token: v })}
            placeholder="••••••••••••••••"
            mono
            type="password"
          />
          <FieldInput
            label="From Number (E.164)"
            value={twilio.from_number}
            onChange={(v) => setTwilio({ ...twilio, from_number: v })}
            placeholder="+15555550100"
            mono
          />
        </>
      ) : (
        <FieldInput
          label="Credential value"
          value={single}
          onChange={setSingle}
          placeholder="paste here"
          mono
          type="password"
        />
      )}
      {errorDetail && (
        <Alert tone="error" title="Save failed">
          {errorDetail}
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}

interface FieldInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  type?: string;
}

function FieldInput({
  label,
  value,
  onChange,
  placeholder,
  mono,
  type = "text",
}: FieldInputProps) {
  return (
    <label className="block text-sm">
      <span className="font-medium text-gray-700">{label}</span>
      <input
        required
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 ${
          mono ? "font-mono text-sm" : ""
        }`}
      />
    </label>
  );
}
