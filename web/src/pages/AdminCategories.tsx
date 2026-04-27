// ABOUTME: Phase 4 Sprint 6 — admin list of equipment categories + create + import.
// ABOUTME: The detail/edit surface lives on AdminCategoryEdit; this page is the directory.
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import {
  createAdminCategory,
  importAdminCategory,
  listAdminCategories,
} from "../api/admin";
import { ApiError } from "../api/client";
import type { CategoryCreate } from "../api/types";

export function AdminCategoriesPage() {
  const qc = useQueryClient();
  const [includeInactive, setIncludeInactive] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const query = useQuery({
    queryKey: ["admin-categories", { includeInactive }],
    queryFn: () => listAdminCategories({ include_inactive: includeInactive }),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Equipment categories</h1>
          <p className="mt-1 text-sm text-gray-600">
            Categories drive intake forms, the iOS appraiser app, scoring
            components, and red-flag rules. Edits supersede prior versions so
            historical appraisals stay anchored.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setImportOpen(true)}>
            Import JSON
          </Button>
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            New category
          </Button>
        </div>
      </div>

      <Card>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)}
          />
          Show inactive
        </label>
      </Card>

      {query.isLoading && <Spinner />}
      {query.isError && (
        <Alert tone="error" title="Could not load categories">
          {(query.error as Error).message}
        </Alert>
      )}

      {query.data && (
        <Card>
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Slug</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Order</th>
                <th className="py-2 pr-4">Version</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {query.data.categories.map((c) => (
                <tr key={c.id} className="border-t border-gray-100">
                  <td className="py-2 pr-4 font-medium text-gray-900">{c.name}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-gray-600">{c.slug}</td>
                  <td className="py-2 pr-4 capitalize text-gray-700">{c.status}</td>
                  <td className="py-2 pr-4 text-gray-700">{c.display_order}</td>
                  <td className="py-2 pr-4 text-gray-700">v{c.version}</td>
                  <td className="py-2 text-right">
                    <Link
                      to={`/admin/categories/${c.id}`}
                      className="text-sm font-medium text-blue-600 hover:underline"
                    >
                      Edit
                    </Link>
                  </td>
                </tr>
              ))}
              {query.data.categories.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-gray-500">
                    No categories yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      )}

      {createOpen && (
        <CreateCategoryModal
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            qc.invalidateQueries({ queryKey: ["admin-categories"] });
          }}
        />
      )}

      {importOpen && (
        <ImportCategoryModal
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setImportOpen(false);
            qc.invalidateQueries({ queryKey: ["admin-categories"] });
          }}
        />
      )}
    </div>
  );
}

interface CreateProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreateCategoryModal({ onClose, onCreated }: CreateProps) {
  const [draft, setDraft] = useState<CategoryCreate>({
    name: "",
    slug: "",
    display_order: 0,
  });

  const mutation = useMutation({
    mutationFn: (body: CategoryCreate) => createAdminCategory(body),
    onSuccess: () => onCreated(),
  });

  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate(draft);
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-category-title"
    >
      <Card className="w-full max-w-md">
        <h2 id="new-category-title" className="text-lg font-semibold text-gray-900">
          New equipment category
        </h2>
        <form onSubmit={onSubmit} className="mt-4 space-y-4">
          <label className="block text-sm">
            <span className="font-medium text-gray-700">Name</span>
            <input
              required
              type="text"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="font-medium text-gray-700">Slug</span>
            <input
              required
              type="text"
              pattern="[a-z0-9][a-z0-9_-]*"
              value={draft.slug}
              onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
              placeholder="forklifts"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono"
            />
            <span className="mt-1 block text-xs text-gray-500">
              Lowercase letters, digits, dashes, underscores. Permanent identifier.
            </span>
          </label>
          <label className="block text-sm">
            <span className="font-medium text-gray-700">Display order</span>
            <input
              type="number"
              min={0}
              value={draft.display_order ?? 0}
              onChange={(e) =>
                setDraft({ ...draft, display_order: Number(e.target.value) })
              }
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          {errorDetail && (
            <Alert tone="error" title="Could not create">
              {errorDetail}
            </Alert>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={mutation.isPending}>
              {mutation.isPending ? "Creating…" : "Create"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

interface ImportProps {
  onClose: () => void;
  onImported: () => void;
}

function ImportCategoryModal({ onClose, onImported }: ImportProps) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [parsed, setParsed] = useState<Record<string, unknown> | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => importAdminCategory(payload),
    onSuccess: () => onImported(),
  });

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setParseError(null);
    setParsed(null);
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setParsed(JSON.parse(text));
    } catch (err) {
      setParseError(`Could not parse JSON: ${(err as Error).message}`);
    }
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
      aria-labelledby="import-category-title"
    >
      <Card className="w-full max-w-lg">
        <h2 id="import-category-title" className="text-lg font-semibold text-gray-900">
          Import category JSON
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Idempotent on slug. Existing prompts + rules supersede when their body
          changes; new components / prompts / rules are added.
        </p>
        <div className="mt-4 space-y-3">
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            onChange={onFileChange}
            className="block w-full text-sm"
          />
          {parseError && <Alert tone="error">{parseError}</Alert>}
          {parsed && (
            <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-700">
              <span className="font-medium">Slug:</span>{" "}
              <span className="font-mono">{(parsed as { slug?: string }).slug}</span>
            </div>
          )}
          {errorDetail && <Alert tone="error" title="Import failed">{errorDetail}</Alert>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              disabled={!parsed || mutation.isPending}
              onClick={() => parsed && mutation.mutate(parsed)}
            >
              {mutation.isPending ? "Importing…" : "Import"}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
