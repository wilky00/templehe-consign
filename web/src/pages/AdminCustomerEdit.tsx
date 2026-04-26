// ABOUTME: Phase 4 admin customer detail page — edit form, soft-delete, send invite, equipment summary.
// ABOUTME: Patches go through /admin/customers/{id}; cascade soft-delete on the DELETE endpoint.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { StatusBadge } from "../components/ui/StatusBadge";
import {
  getAdminCustomer,
  sendWalkinInvite,
  softDeleteAdminCustomer,
  updateAdminCustomer,
} from "../api/admin";
import { ApiError } from "../api/client";
import type { AdminCustomerPatch, UUID } from "../api/types";

const EDITABLE_FIELDS: Array<{ key: keyof AdminCustomerPatch; label: string }> = [
  { key: "submitter_name", label: "Submitter name" },
  { key: "business_name", label: "Business name" },
  { key: "title", label: "Title" },
  { key: "address_street", label: "Street" },
  { key: "address_city", label: "City" },
  { key: "address_state", label: "State (2-letter)" },
  { key: "address_zip", label: "ZIP" },
  { key: "cell_phone", label: "Cell phone" },
  { key: "business_phone", label: "Business phone" },
  { key: "business_phone_ext", label: "Business phone ext" },
  { key: "invite_email", label: "Invite email (walk-in only)" },
];

export function AdminCustomerEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const customerId = id as UUID;

  const query = useQuery({
    queryKey: ["admin-customer", customerId],
    queryFn: () => getAdminCustomer(customerId),
    enabled: Boolean(customerId),
  });

  const [form, setForm] = useState<AdminCustomerPatch>({});
  const [confirmDelete, setConfirmDelete] = useState<boolean>(false);

  useEffect(() => {
    if (query.data) {
      setForm({
        submitter_name: query.data.submitter_name,
        business_name: query.data.business_name,
        title: query.data.title,
        address_street: query.data.address_street,
        address_city: query.data.address_city,
        address_state: query.data.address_state,
        address_zip: query.data.address_zip,
        cell_phone: query.data.cell_phone,
        business_phone: query.data.business_phone,
        business_phone_ext: query.data.business_phone_ext,
        invite_email: query.data.invite_email,
      });
    }
  }, [query.data]);

  const updateMutation = useMutation({
    mutationFn: () => updateAdminCustomer(customerId, _diff(form, query.data ?? null)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-customer", customerId] });
      qc.invalidateQueries({ queryKey: ["admin-customers"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => softDeleteAdminCustomer(customerId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-customer", customerId] });
      qc.invalidateQueries({ queryKey: ["admin-customers"] });
      navigate("/admin/customers");
    },
  });

  const inviteMutation = useMutation({
    mutationFn: () => sendWalkinInvite(customerId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-customer", customerId] });
    },
  });

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load the customer">
        {(query.error as Error).message}
      </Alert>
    );
  }
  const customer = query.data;
  if (!customer) return null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    updateMutation.mutate();
  };

  const setField = (key: keyof AdminCustomerPatch, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value === "" ? null : value }));

  const updateError =
    updateMutation.error instanceof ApiError
      ? updateMutation.error.detail
      : updateMutation.error
        ? (updateMutation.error as Error).message
        : null;

  const inviteError =
    inviteMutation.error instanceof ApiError
      ? inviteMutation.error.detail
      : inviteMutation.error
        ? (inviteMutation.error as Error).message
        : null;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/admin/customers" className="text-sm text-gray-500 underline">
          ← Customers
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-gray-900">
          {customer.business_name ?? customer.submitter_name}
        </h1>
        <p className="mt-1 text-sm text-gray-600">
          {customer.is_walkin ? (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
              Walk-in (no portal account)
            </span>
          ) : (
            <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
              Registered — {customer.user_email}
            </span>
          )}
          {customer.is_deleted && (
            <span className="ml-2 rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
              Deleted {customer.deleted_at}
            </span>
          )}
        </p>
      </div>

      {customer.is_walkin && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-gray-900">
                Portal invite
              </h2>
              <p className="text-sm text-gray-600">
                Sends a registration link to{" "}
                <strong>{customer.invite_email}</strong>. They keep this email
                when they register.
              </p>
            </div>
            <Button
              variant="primary"
              onClick={() => inviteMutation.mutate()}
              disabled={inviteMutation.isPending || !customer.invite_email}
            >
              {inviteMutation.isPending
                ? "Sending…"
                : inviteMutation.isSuccess
                  ? "Invite sent ✓"
                  : "Send portal invite"}
            </Button>
          </div>
          {inviteError && (
            <Alert tone="error" title="Invite failed">
              {inviteError}
            </Alert>
          )}
        </Card>
      )}

      <Card>
        <h2 className="text-base font-semibold text-gray-900">Profile</h2>
        <form onSubmit={onSubmit} className="mt-3 space-y-3">
          {EDITABLE_FIELDS.map((field) => {
            const isInviteField = field.key === "invite_email";
            // Only show invite_email for walk-ins (registered customers' email
            // lives on the User row + is non-editable here).
            if (isInviteField && !customer.is_walkin) return null;
            return (
              <label key={field.key} className="block text-sm">
                <span className="block font-medium text-gray-700">{field.label}</span>
                <input
                  value={(form[field.key] as string | null | undefined) ?? ""}
                  onChange={(e) => setField(field.key, e.target.value)}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2"
                  disabled={customer.is_deleted}
                />
              </label>
            );
          })}

          {updateError && (
            <Alert tone="error" title="Could not save changes">
              {updateError}
            </Alert>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="submit"
              variant="primary"
              disabled={
                customer.is_deleted ||
                updateMutation.isPending ||
                Object.keys(_diff(form, customer)).length === 0
              }
            >
              {updateMutation.isPending ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="text-base font-semibold text-gray-900">Equipment records</h2>
        {customer.equipment_records.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No records yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-100">
            {customer.equipment_records.map((rec) => (
              <li key={rec.id} className="flex items-center justify-between py-2 text-sm">
                <div>
                  <span className="font-medium">
                    {rec.reference_number ?? rec.id.slice(0, 8)}
                  </span>{" "}
                  <span className="text-gray-600">
                    {[rec.make, rec.model].filter(Boolean).join(" ") || "—"}
                    {rec.year ? ` (${rec.year})` : ""}
                  </span>
                  {rec.deleted_at && (
                    <span className="ml-2 text-xs text-gray-500">(deleted)</span>
                  )}
                </div>
                <StatusBadge status={rec.status} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      {!customer.is_deleted && (
        <Card className="border-red-200 bg-red-50">
          <h2 className="text-base font-semibold text-red-900">Danger zone</h2>
          <p className="mt-1 text-sm text-red-800">
            Soft-deletes this customer and cascades the deletion to every
            related equipment record. Audit log retains the trail.
          </p>
          {!confirmDelete ? (
            <Button
              variant="danger"
              onClick={() => setConfirmDelete(true)}
              className="mt-2"
            >
              Soft-delete customer
            </Button>
          ) : (
            <div className="mt-2 flex gap-2">
              <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? "Deleting…" : "Confirm soft-delete"}
              </Button>
            </div>
          )}
          {deleteMutation.isError && (
            <Alert tone="error" title="Delete failed">
              {(deleteMutation.error as Error).message}
            </Alert>
          )}
        </Card>
      )}
    </div>
  );
}

function _diff(
  form: AdminCustomerPatch,
  current: { [k in keyof AdminCustomerPatch]?: string | null } | null,
): AdminCustomerPatch {
  if (!current) return form;
  const out: AdminCustomerPatch = {};
  (Object.keys(form) as Array<keyof AdminCustomerPatch>).forEach((k) => {
    const next = form[k] ?? null;
    const prev = current[k] ?? null;
    if (next !== prev) {
      (out as Record<string, unknown>)[k] = next;
    }
  });
  return out;
}
