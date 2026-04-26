// ABOUTME: Phase 4 admin customer list — search + filter (active/walk-ins/deleted) + create walk-in.
// ABOUTME: Soft-delete + edit live on AdminCustomerEdit.tsx; this page is the directory.
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { createWalkinCustomer, listAdminCustomers } from "../api/admin";
import { ApiError } from "../api/client";
import type { AdminCustomerCreate } from "../api/types";

type FilterMode = "active" | "walkins" | "deleted";

export function AdminCustomersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState<string>("");
  const [searchInput, setSearchInput] = useState<string>("");
  const [mode, setMode] = useState<FilterMode>("active");
  const [page, setPage] = useState<number>(1);
  const perPage = 50;
  const [createOpen, setCreateOpen] = useState<boolean>(false);

  const filters = useMemo(
    () => ({
      search: search || undefined,
      include_deleted: mode === "deleted",
      walkins_only: mode === "walkins",
      page,
      per_page: perPage,
    }),
    [search, mode, page],
  );

  const query = useQuery({
    queryKey: ["admin-customers", filters],
    queryFn: () => listAdminCustomers(filters),
  });

  const onSubmitSearch = (e: FormEvent) => {
    e.preventDefault();
    setSearch(searchInput.trim());
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Customers</h1>
          <p className="mt-1 text-sm text-gray-600">
            Search, edit, and manage every customer record across the platform.
          </p>
        </div>
        <Button variant="primary" onClick={() => setCreateOpen(true)}>
          New walk-in customer
        </Button>
      </div>

      <Card>
        <form onSubmit={onSubmitSearch} className="flex flex-wrap items-end gap-3">
          <label className="flex-1 text-sm">
            <span className="block font-medium text-gray-700">Search</span>
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Name, business, email, or phone…"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <Button type="submit" variant="secondary">
            Search
          </Button>
          <div className="flex items-center gap-1 rounded-md border border-gray-200 p-1 text-sm">
            {(["active", "walkins", "deleted"] as FilterMode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMode(m);
                  setPage(1);
                }}
                aria-pressed={mode === m}
                className={
                  mode === m
                    ? "rounded px-3 py-1.5 bg-gray-100 font-medium text-gray-900"
                    : "rounded px-3 py-1.5 text-gray-600 hover:text-gray-900"
                }
              >
                {m === "active" ? "Active" : m === "walkins" ? "Walk-ins" : "Deleted"}
              </button>
            ))}
          </div>
        </form>
      </Card>

      {query.isLoading && <Spinner />}
      {query.isError && (
        <Alert tone="error" title="Could not load customers">
          {(query.error as Error).message}
        </Alert>
      )}

      {query.data && (
        <Card>
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-600">
              {query.data.total} customer{query.data.total === 1 ? "" : "s"} matching
              filters · page {query.data.page}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={query.data.customers.length < perPage}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                <tr>
                  <th scope="col" className="px-3 py-2">Customer</th>
                  <th scope="col" className="px-3 py-2">Email</th>
                  <th scope="col" className="px-3 py-2">Phone</th>
                  <th scope="col" className="px-3 py-2">State</th>
                  <th scope="col" className="px-3 py-2">Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {query.data.customers.map((c) => (
                  <tr key={c.id} className={c.is_deleted ? "opacity-60" : ""}>
                    <td className="px-3 py-2">
                      <Link
                        to={`/admin/customers/${c.id}`}
                        className="font-medium text-gray-900 underline decoration-dotted underline-offset-2"
                      >
                        {c.business_name ?? c.submitter_name}
                      </Link>
                      {c.business_name && (
                        <div className="text-xs text-gray-500">{c.submitter_name}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {c.user_email ?? c.invite_email ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {c.cell_phone ?? c.business_phone ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-gray-700">{c.address_state ?? "—"}</td>
                    <td className="px-3 py-2">
                      {c.is_deleted ? (
                        <span className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600">
                          Deleted
                        </span>
                      ) : c.is_walkin ? (
                        <span className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">
                          Walk-in
                        </span>
                      ) : (
                        <span className="rounded bg-emerald-100 px-2 py-1 text-xs text-emerald-800">
                          Registered
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
                {query.data.customers.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-sm text-gray-500">
                      No customers match these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {createOpen && (
        <WalkinCreateModal
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            qc.invalidateQueries({ queryKey: ["admin-customers"] });
          }}
        />
      )}
    </div>
  );
}

interface WalkinModalProps {
  onClose: () => void;
  onCreated: () => void;
}

function WalkinCreateModal({ onClose, onCreated }: WalkinModalProps) {
  const [form, setForm] = useState<AdminCustomerCreate>({
    submitter_name: "",
    invite_email: "",
    business_name: "",
  });
  const mutation = useMutation({
    mutationFn: () => createWalkinCustomer(form),
    onSuccess: () => onCreated(),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.submitter_name.trim() || !form.invite_email.trim()) return;
    mutation.mutate();
  };

  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.detail
      : mutation.error
        ? (mutation.error as Error).message
        : null;

  const setField = <K extends keyof AdminCustomerCreate>(
    key: K,
    value: AdminCustomerCreate[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="walkin-create-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 id="walkin-create-title" className="text-lg font-semibold text-gray-900">
          New walk-in customer
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Type the customer's details. They won't have a portal account yet —
          click "Send portal invite" on the record when you're ready to invite
          them in.
        </p>

        <form onSubmit={onSubmit} className="mt-4 space-y-3">
          <label className="block text-sm">
            <span className="block font-medium text-gray-700">Submitter name *</span>
            <input
              required
              value={form.submitter_name}
              onChange={(e) => setField("submitter_name", e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="block font-medium text-gray-700">Invite email *</span>
            <input
              type="email"
              required
              value={form.invite_email}
              onChange={(e) => setField("invite_email", e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="block font-medium text-gray-700">Business name</span>
            <input
              value={form.business_name ?? ""}
              onChange={(e) => setField("business_name", e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="block font-medium text-gray-700">Cell phone</span>
            <input
              value={form.cell_phone ?? ""}
              onChange={(e) => setField("cell_phone", e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
            />
          </label>

          {errorDetail && (
            <Alert tone="error" title="Could not create the customer">
              {errorDetail}
            </Alert>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={
                mutation.isPending ||
                !form.submitter_name.trim() ||
                !form.invite_email.trim()
              }
            >
              {mutation.isPending ? "Creating…" : "Create"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
