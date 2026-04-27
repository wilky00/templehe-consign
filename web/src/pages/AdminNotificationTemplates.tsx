// ABOUTME: Phase 4 Sprint 5 — admin reads + edits notification template overrides.
// ABOUTME: Per-template card with subject/body editor + variable picker chips + revert.
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import {
  listNotificationTemplates,
  updateNotificationTemplate,
} from "../api/admin";
import { ApiError } from "../api/client";
import type { NotificationTemplate } from "../api/types";

const CATEGORY_LABELS: Record<string, string> = {
  equipment_status: "Equipment status",
  sales_rep: "Sales rep alerts",
  record_lock: "Record locks",
  auth: "Authentication",
};

export function AdminNotificationTemplatesPage() {
  const query = useQuery({
    queryKey: ["admin-notification-templates"],
    queryFn: listNotificationTemplates,
  });

  const grouped = useMemo(() => {
    const buckets = new Map<string, NotificationTemplate[]>();
    for (const t of query.data?.templates ?? []) {
      const list = buckets.get(t.category) ?? [];
      list.push(t);
      buckets.set(t.category, list);
    }
    return Array.from(buckets.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [query.data]);

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load templates">
        {(query.error as Error).message}
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">
          Notification templates
        </h1>
        <p className="mt-1 text-sm text-gray-600">
          Edit subject + body for any registered notification. Save creates an
          override; "Revert to default" drops it. Variables are listed below
          each template — use them in your text as{" "}
          <code className="rounded bg-gray-100 px-1">{"{{ name }}"}</code>.
          Email bodies render as HTML; SMS bodies as plain text.
        </p>
      </div>

      {grouped.map(([category, templates]) => (
        <section key={category} className="space-y-4">
          <h2 className="text-base font-semibold text-gray-900">
            {CATEGORY_LABELS[category] ?? category}
          </h2>
          {templates.map((template) => (
            <TemplateCard key={template.name} template={template} />
          ))}
        </section>
      ))}
    </div>
  );
}

interface CardProps {
  template: NotificationTemplate;
}

function TemplateCard({ template }: CardProps) {
  const qc = useQueryClient();
  const [subject, setSubject] = useState<string>(
    template.override_subject ?? template.subject_template ?? "",
  );
  const [body, setBody] = useState<string>(
    template.override_body ?? template.body_template,
  );

  useEffect(() => {
    setSubject(template.override_subject ?? template.subject_template ?? "");
    setBody(template.override_body ?? template.body_template);
  }, [template]);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateNotificationTemplate(template.name, {
        subject_md: template.channel === "email" ? subject : null,
        body_md: body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-notification-templates"] }),
  });
  const revertMutation = useMutation({
    mutationFn: () => updateNotificationTemplate(template.name, { delete: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-notification-templates"] }),
  });

  const error =
    saveMutation.error instanceof ApiError
      ? saveMutation.error.detail
      : saveMutation.error
        ? (saveMutation.error as Error).message
        : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    saveMutation.mutate();
  };

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">
            {template.name}
            <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-normal text-gray-600">
              {template.channel}
            </span>
            {template.has_override && (
              <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-normal text-amber-800">
                customized
              </span>
            )}
          </h3>
          {template.description && (
            <p className="mt-1 text-xs text-gray-500">{template.description}</p>
          )}
        </div>
        {template.has_override && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => revertMutation.mutate()}
            disabled={revertMutation.isPending}
          >
            {revertMutation.isPending ? "Reverting…" : "Revert to default"}
          </Button>
        )}
      </div>

      <form onSubmit={onSubmit} className="mt-3 space-y-3">
        {template.channel === "email" && (
          <label className="block text-sm">
            <span className="block font-medium text-gray-700">Subject</span>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs"
            />
          </label>
        )}
        <label className="block text-sm">
          <span className="block font-medium text-gray-700">
            Body ({template.channel === "email" ? "HTML" : "plain text"})
          </span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={template.channel === "email" ? 8 : 3}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs"
          />
        </label>

        <div className="flex flex-wrap gap-1">
          {template.variables.map((v) => (
            <span
              key={v}
              className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-gray-700"
            >
              {`{{ ${v} }}`}
            </span>
          ))}
        </div>

        {error && (
          <Alert tone="error" title="Save failed">
            {error}
          </Alert>
        )}

        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "Saving…" : "Save override"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
