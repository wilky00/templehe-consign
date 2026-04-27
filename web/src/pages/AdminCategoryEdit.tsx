// ABOUTME: Phase 4 Sprint 6 — admin edit page for one equipment category + its components/prompts/rules.
// ABOUTME: Edits route through versioning where appropriate; export downloads JSON; warning shows weight drift.
import { useState, type FormEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { ComponentWeightWarning } from "../components/admin/ComponentWeightWarning";
import {
  addCategoryComponent,
  addCategoryInspectionPrompt,
  addCategoryRedFlagRule,
  deactivateAdminCategory,
  deleteAdminCategory,
  downloadAdminCategoryExport,
  getAdminCategory,
  updateAdminCategory,
  updateCategoryInspectionPrompt,
} from "../api/admin";
import { ApiError } from "../api/client";
import type {
  CategoryDetail,
  ComponentCreate,
  InspectionPromptCreate,
  RedFlagRuleCreate,
} from "../api/types";

type Tab = "components" | "prompts" | "redflags" | "photos" | "attachments";

export function AdminCategoryEditPage() {
  const params = useParams<{ id: string }>();
  const id = params.id ?? "";
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("components");

  const query = useQuery({
    queryKey: ["admin-category", id],
    queryFn: () => getAdminCategory(id),
    enabled: !!id,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-category", id] });

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load category">
        {(query.error as Error).message}
      </Alert>
    );
  }
  if (!query.data) return null;
  const cat = query.data;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/admin/categories" className="text-sm text-gray-500 hover:underline">
          ← All categories
        </Link>
        <h1 className="mt-1 text-2xl font-semibold text-gray-900">{cat.name}</h1>
        <p className="text-sm text-gray-600">
          <span className="font-mono">{cat.slug}</span> · v{cat.version} · {cat.status}
        </p>
      </div>

      <CategoryHeaderActions cat={cat} onChanged={refresh} />

      {cat.weight_warning && <ComponentWeightWarning total={cat.weight_total} />}

      <Card>
        <div className="flex flex-wrap gap-1 border-b border-gray-200" role="tablist">
          {(
            [
              ["components", `Components (${cat.components.length})`],
              ["prompts", `Inspection prompts (${cat.inspection_prompts.length})`],
              ["redflags", `Red-flag rules (${cat.red_flag_rules.length})`],
              ["photos", `Photo slots (${cat.photo_slots.length})`],
              ["attachments", `Attachments (${cat.attachments.length})`],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              type="button"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={
                tab === key
                  ? "rounded-t-md border-b-2 border-blue-500 px-3 py-2 text-sm font-medium text-blue-700"
                  : "rounded-t-md px-3 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
              }
            >
              {label}
            </button>
          ))}
        </div>

        <div className="mt-4">
          {tab === "components" && (
            <ComponentsTab cat={cat} onChanged={refresh} />
          )}
          {tab === "prompts" && <PromptsTab cat={cat} onChanged={refresh} />}
          {tab === "redflags" && <RedFlagsTab cat={cat} onChanged={refresh} />}
          {tab === "photos" && (
            <p className="text-sm text-gray-600">
              Photo slot CRUD ships in the iOS work. The list above reflects the
              current state.
            </p>
          )}
          {tab === "attachments" && (
            <p className="text-sm text-gray-600">
              Attachment CRUD ships in the iOS work. The list above reflects the
              current state.
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}

interface HeaderProps {
  cat: CategoryDetail;
  onChanged: () => void;
}

function CategoryHeaderActions({ cat, onChanged }: HeaderProps) {
  const [renameOpen, setRenameOpen] = useState(false);
  const deactivate = useMutation({
    mutationFn: () => deactivateAdminCategory(cat.id),
    onSuccess: () => onChanged(),
  });
  const remove = useMutation({
    mutationFn: () => deleteAdminCategory(cat.id),
    onSuccess: () => onChanged(),
  });

  const exportFile = async () => {
    await downloadAdminCategoryExport(cat.id, `category-${cat.slug}.json`);
  };

  const removeError =
    remove.error instanceof ApiError
      ? remove.error.detail
      : remove.error
        ? (remove.error as Error).message
        : null;

  return (
    <Card>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => setRenameOpen(true)}>
          Rename / edit
        </Button>
        <Button
          variant="secondary"
          onClick={() => deactivate.mutate()}
          disabled={cat.status === "inactive" || deactivate.isPending}
        >
          {cat.status === "inactive" ? "Inactive" : "Deactivate"}
        </Button>
        <Button variant="secondary" onClick={exportFile}>
          Export JSON
        </Button>
        <Button
          variant="danger"
          onClick={() => {
            if (confirm("Soft-delete this category? Records still referencing it will block.")) {
              remove.mutate();
            }
          }}
          disabled={remove.isPending}
        >
          Soft delete
        </Button>
      </div>
      {removeError && (
        <div className="mt-3">
          <Alert tone="error" title="Cannot delete">
            {removeError}
          </Alert>
        </div>
      )}
      {renameOpen && (
        <RenameModal cat={cat} onClose={() => setRenameOpen(false)} onChanged={onChanged} />
      )}
    </Card>
  );
}

interface RenameProps {
  cat: CategoryDetail;
  onClose: () => void;
  onChanged: () => void;
}

function RenameModal({ cat, onClose, onChanged }: RenameProps) {
  const [name, setName] = useState(cat.name);
  const [slug, setSlug] = useState(cat.slug);
  const mutation = useMutation({
    mutationFn: () => updateAdminCategory(cat.id, { name, slug }),
    onSuccess: () => {
      onChanged();
      onClose();
    },
  });
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
      aria-labelledby="rename-title"
    >
      <Card className="w-full max-w-md">
        <h2 id="rename-title" className="text-lg font-semibold text-gray-900">
          Rename / edit
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Saving creates a new version. Historical appraisals stay anchored to
          the prior version.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          className="mt-4 space-y-4"
        >
          <label className="block text-sm">
            <span className="font-medium text-gray-700">Name</span>
            <input
              required
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="font-medium text-gray-700">Slug</span>
            <input
              required
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              pattern="[a-z0-9][a-z0-9_-]*"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono"
            />
          </label>
          {errorDetail && <Alert tone="error">{errorDetail}</Alert>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving…" : "Save new version"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

interface SectionProps {
  cat: CategoryDetail;
  onChanged: () => void;
}

function ComponentsTab({ cat, onChanged }: SectionProps) {
  const [draft, setDraft] = useState<ComponentCreate>({
    name: "",
    weight_pct: 0,
    display_order: 0,
  });
  const mutation = useMutation({
    mutationFn: () => addCategoryComponent(cat.id, draft),
    onSuccess: () => {
      setDraft({ name: "", weight_pct: 0, display_order: 0 });
      onChanged();
    },
  });
  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-gray-500">
            <tr>
              <th className="py-2 pr-4">Name</th>
              <th className="py-2 pr-4">Weight</th>
              <th className="py-2 pr-4">Order</th>
              <th className="py-2">Active</th>
            </tr>
          </thead>
          <tbody>
            {cat.components.map((c) => (
              <tr key={c.id} className="border-t border-gray-100">
                <td className="py-2 pr-4 font-medium text-gray-900">{c.name}</td>
                <td className="py-2 pr-4 text-gray-700">{c.weight_pct.toFixed(2)}%</td>
                <td className="py-2 pr-4 text-gray-700">{c.display_order}</td>
                <td className="py-2 text-gray-700">{c.active ? "Yes" : "No"}</td>
              </tr>
            ))}
            {cat.components.length === 0 && (
              <tr>
                <td colSpan={4} className="py-4 text-center text-gray-500">
                  No components yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <form onSubmit={onSubmit} className="grid gap-3 border-t border-gray-100 pt-4 sm:grid-cols-4">
        <label className="text-sm sm:col-span-2">
          <span className="block font-medium text-gray-700">Name</span>
          <input
            required
            type="text"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="block font-medium text-gray-700">Weight (%)</span>
          <input
            type="number"
            min={0}
            max={99.99}
            step={0.01}
            value={draft.weight_pct}
            onChange={(e) => setDraft({ ...draft, weight_pct: Number(e.target.value) })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="block font-medium text-gray-700">Order</span>
          <input
            type="number"
            min={0}
            value={draft.display_order ?? 0}
            onChange={(e) => setDraft({ ...draft, display_order: Number(e.target.value) })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        {errorDetail && (
          <div className="sm:col-span-4">
            <Alert tone="error">{errorDetail}</Alert>
          </div>
        )}
        <div className="sm:col-span-4">
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? "Adding…" : "Add component"}
          </Button>
        </div>
      </form>
    </div>
  );
}

function PromptsTab({ cat, onChanged }: SectionProps) {
  const [draft, setDraft] = useState<InspectionPromptCreate>({
    label: "",
    response_type: "yes_no_na",
    required: true,
    display_order: 0,
  });
  const add = useMutation({
    mutationFn: () => addCategoryInspectionPrompt(cat.id, draft),
    onSuccess: () => {
      setDraft({ label: "", response_type: "yes_no_na", required: true, display_order: 0 });
      onChanged();
    },
  });
  const errorDetail =
    add.error instanceof ApiError
      ? add.error.detail
      : add.error
        ? (add.error as Error).message
        : null;

  return (
    <div className="space-y-4">
      <ul className="space-y-2">
        {cat.inspection_prompts.map((p) => (
          <PromptRow key={p.id} catId={cat.id} prompt={p} onChanged={onChanged} />
        ))}
        {cat.inspection_prompts.length === 0 && (
          <li className="py-4 text-center text-sm text-gray-500">No prompts yet.</li>
        )}
      </ul>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
        className="grid gap-3 border-t border-gray-100 pt-4 sm:grid-cols-4"
      >
        <label className="text-sm sm:col-span-2">
          <span className="block font-medium text-gray-700">Label</span>
          <input
            required
            type="text"
            value={draft.label}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="block font-medium text-gray-700">Response type</span>
          <select
            value={draft.response_type}
            onChange={(e) =>
              setDraft({
                ...draft,
                response_type: e.target.value as InspectionPromptCreate["response_type"],
              })
            }
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="yes_no_na">Yes / No / N/A</option>
            <option value="text">Free text</option>
            <option value="scale_1_5">Scale 1–5</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="block font-medium text-gray-700">Order</span>
          <input
            type="number"
            min={0}
            value={draft.display_order ?? 0}
            onChange={(e) => setDraft({ ...draft, display_order: Number(e.target.value) })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        {errorDetail && (
          <div className="sm:col-span-4">
            <Alert tone="error">{errorDetail}</Alert>
          </div>
        )}
        <div className="sm:col-span-4">
          <Button type="submit" variant="primary" disabled={add.isPending}>
            {add.isPending ? "Adding…" : "Add prompt"}
          </Button>
        </div>
      </form>
    </div>
  );
}

interface PromptRowProps {
  catId: string;
  prompt: CategoryDetail["inspection_prompts"][number];
  onChanged: () => void;
}

function PromptRow({ catId, prompt, onChanged }: PromptRowProps) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(prompt.label);
  const mutation = useMutation({
    mutationFn: () =>
      updateCategoryInspectionPrompt(catId, prompt.id, { label }),
    onSuccess: () => {
      setEditing(false);
      onChanged();
    },
  });

  return (
    <li className="rounded-md border border-gray-100 bg-white px-3 py-2">
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          className="flex gap-2"
        >
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
          <Button size="sm" type="submit" disabled={mutation.isPending}>
            Save
          </Button>
          <Button size="sm" type="button" variant="secondary" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-900">{prompt.label}</p>
            <p className="text-xs text-gray-500">
              {prompt.response_type} · v{prompt.version}
            </p>
          </div>
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
            Edit
          </Button>
        </div>
      )}
    </li>
  );
}

function RedFlagsTab({ cat, onChanged }: SectionProps) {
  const [draft, setDraft] = useState<RedFlagRuleCreate>({
    label: "",
    condition_field: "",
    condition_operator: "equals",
    condition_value: "",
    actions: {},
  });
  const add = useMutation({
    mutationFn: () => addCategoryRedFlagRule(cat.id, draft),
    onSuccess: () => {
      setDraft({
        label: "",
        condition_field: "",
        condition_operator: "equals",
        condition_value: "",
        actions: {},
      });
      onChanged();
    },
  });
  const errorDetail =
    add.error instanceof ApiError
      ? add.error.detail
      : add.error
        ? (add.error as Error).message
        : null;

  return (
    <div className="space-y-4">
      <ul className="space-y-2">
        {cat.red_flag_rules.map((r) => (
          <li key={r.id} className="rounded-md border border-gray-100 bg-white px-3 py-2">
            <p className="text-sm font-medium text-gray-900">{r.label}</p>
            <p className="text-xs text-gray-500">
              when <span className="font-mono">{r.condition_field}</span>{" "}
              {r.condition_operator}{" "}
              {r.condition_value && <span className="font-mono">{r.condition_value}</span>} · v
              {r.version}
            </p>
          </li>
        ))}
        {cat.red_flag_rules.length === 0 && (
          <li className="py-4 text-center text-sm text-gray-500">No rules yet.</li>
        )}
      </ul>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
        className="grid gap-3 border-t border-gray-100 pt-4 sm:grid-cols-4"
      >
        <label className="text-sm sm:col-span-2">
          <span className="block font-medium text-gray-700">Label</span>
          <input
            required
            type="text"
            value={draft.label}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="block font-medium text-gray-700">Field</span>
          <input
            required
            type="text"
            value={draft.condition_field}
            onChange={(e) => setDraft({ ...draft, condition_field: e.target.value })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono"
          />
        </label>
        <label className="text-sm">
          <span className="block font-medium text-gray-700">Operator</span>
          <select
            value={draft.condition_operator}
            onChange={(e) =>
              setDraft({
                ...draft,
                condition_operator: e.target.value as RedFlagRuleCreate["condition_operator"],
              })
            }
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="equals">equals</option>
            <option value="is_true">is true</option>
            <option value="is_false">is false</option>
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          <span className="block font-medium text-gray-700">Value (when equals)</span>
          <input
            type="text"
            value={draft.condition_value ?? ""}
            onChange={(e) => setDraft({ ...draft, condition_value: e.target.value })}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        {errorDetail && (
          <div className="sm:col-span-4">
            <Alert tone="error">{errorDetail}</Alert>
          </div>
        )}
        <div className="sm:col-span-4">
          <Button type="submit" variant="primary" disabled={add.isPending}>
            {add.isPending ? "Adding…" : "Add rule"}
          </Button>
        </div>
      </form>
    </div>
  );
}
