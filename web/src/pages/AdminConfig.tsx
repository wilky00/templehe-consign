// ABOUTME: Phase 4 Sprint 3 — admin reads + writes every AppConfig key from the SPA.
// ABOUTME: Auto-renders one input per KeySpec field_type; per-key Save with optimistic refresh.
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { ConfigField } from "../components/admin/ConfigField";
import { listAppConfig, updateAppConfig } from "../api/admin";
import { ApiError } from "../api/client";
import type { AppConfigItem } from "../api/types";

const CATEGORY_LABELS: Record<string, string> = {
  legal: "Legal",
  notifications: "Notifications",
  calendar: "Calendar",
  consignment: "Consignment",
  intake: "Intake form",
  lead_routing: "Lead routing",
  operations: "Operations",
  security: "Security",
};

export function AdminConfigPage() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-config"],
    queryFn: listAppConfig,
  });

  // Local drafts keyed by spec.name. Reset whenever the server data
  // refreshes so a save settles back to the canonical value.
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (query.data) {
      const next: Record<string, unknown> = {};
      for (const item of query.data.items) {
        next[item.name] = item.value;
      }
      setDrafts(next);
    }
  }, [query.data]);

  const grouped = useMemo(() => {
    const buckets = new Map<string, AppConfigItem[]>();
    for (const item of query.data?.items ?? []) {
      const list = buckets.get(item.category) ?? [];
      list.push(item);
      buckets.set(item.category, list);
    }
    return Array.from(buckets.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [query.data]);

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load configuration">
        {(query.error as Error).message}
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Configuration</h1>
        <p className="mt-1 text-sm text-gray-600">
          Platform-wide runtime settings. Changes apply immediately — no
          deploy needed. Per-key save; validation errors surface inline.
        </p>
      </div>

      {grouped.map(([category, items]) => (
        <Card key={category}>
          <h2 className="text-base font-semibold text-gray-900">
            {CATEGORY_LABELS[category] ?? category}
          </h2>
          <div className="mt-4 space-y-5">
            {items.map((item) => (
              <ConfigRow
                key={item.name}
                spec={item}
                draft={drafts[item.name] ?? item.value}
                onChange={(v) =>
                  setDrafts((prev) => ({ ...prev, [item.name]: v }))
                }
                onSaved={() => qc.invalidateQueries({ queryKey: ["admin-config"] })}
              />
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}

interface RowProps {
  spec: AppConfigItem;
  draft: unknown;
  onChange: (value: unknown) => void;
  onSaved: () => void;
}

function ConfigRow({ spec, draft, onChange, onSaved }: RowProps) {
  const mutation = useMutation({
    mutationFn: () => updateAppConfig(spec.name, draft),
    onSuccess: () => onSaved(),
  });

  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  const isDirty = JSON.stringify(draft) !== JSON.stringify(spec.value);

  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <label
          htmlFor={`cfg-${spec.name}`}
          className="block text-sm font-medium text-gray-900"
        >
          {spec.name}
          <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-normal text-gray-600">
            {spec.field_type}
          </span>
        </label>
        <Button
          size="sm"
          variant="primary"
          onClick={() => mutation.mutate()}
          disabled={!isDirty || mutation.isPending}
        >
          {mutation.isPending
            ? "Saving…"
            : mutation.isSuccess && !isDirty
              ? "Saved ✓"
              : "Save"}
        </Button>
      </div>
      {spec.description && (
        <p className="mt-1 text-xs text-gray-500">{spec.description}</p>
      )}
      <ConfigField
        spec={spec}
        draft={draft}
        onChange={onChange}
        disabled={mutation.isPending}
      />
      {errorDetail && (
        <div className="mt-2">
          <Alert tone="error" title="Save failed">
            {errorDetail}
          </Alert>
        </div>
      )}
    </div>
  );
}
