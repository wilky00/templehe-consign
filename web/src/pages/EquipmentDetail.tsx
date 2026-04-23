// ABOUTME: Equipment record detail — shows customer-entered facts, timeline, photos, and the change-request flow.
// ABOUTME: The photo thumbnails reference R2 storage keys; the image src is constructed from the public bucket URL when set.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import {
  getEquipment,
  listChangeRequests,
  submitChangeRequest,
} from "../api/equipment";
import type { ChangeRequestOut, EquipmentRecord } from "../api/types";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Select, Textarea } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";
import { StatusBadge } from "../components/ui/StatusBadge";

const R2_PUBLIC_BASE: string = import.meta.env.VITE_R2_PUBLIC_URL ?? "";

const CHANGE_TYPES = [
  { value: "edit_details", label: "Edit submission details" },
  { value: "update_location", label: "Update location" },
  { value: "update_photos", label: "Update photos" },
  { value: "withdraw", label: "Withdraw submission" },
  { value: "other", label: "Other" },
];

function photoUrl(storageKey: string): string | null {
  if (!R2_PUBLIC_BASE) return null;
  return `${R2_PUBLIC_BASE.replace(/\/$/, "")}/${storageKey}`;
}

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function EquipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const recordQuery = useQuery({
    queryKey: ["equipment", id],
    queryFn: () => getEquipment(id!),
    enabled: Boolean(id),
  });

  if (!id) {
    return (
      <Alert tone="error" title="Missing record id">
        The URL is incomplete.
      </Alert>
    );
  }

  if (recordQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }
  if (recordQuery.isError || !recordQuery.data) {
    return (
      <Alert tone="error" title="Could not load submission">
        {(recordQuery.error as Error)?.message ?? "Not found."}
      </Alert>
    );
  }
  const record = recordQuery.data;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Link to="/portal" className="text-sm text-gray-600 underline">
            ← Back to dashboard
          </Link>
          <h1 className="mt-2 text-2xl font-semibold text-gray-900">
            {[record.year, record.make, record.model].filter(Boolean).join(" ") ||
              "Submission"}
          </h1>
          <p className="mt-1 font-mono text-sm text-gray-500">
            {record.reference_number}
          </p>
        </div>
        <StatusBadge status={record.status} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <DetailsCard record={record} />
        <TimelineCard record={record} />
      </div>

      <PhotosCard record={record} />
      <ChangeRequestsCard recordId={record.id} />
    </div>
  );
}

function DetailsCard({ record }: { record: EquipmentRecord }) {
  const rows: Array<[string, string | number | null]> = [
    ["Make", record.make],
    ["Model", record.model],
    ["Year", record.year],
    ["Serial / VIN", record.serial_number],
    ["Hour meter", record.hours],
    ["Running condition", record.running_status],
    ["Ownership", record.ownership_type],
    ["Current location", record.location_text],
  ];
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Submission details</h2>
      <dl className="mt-3 divide-y divide-gray-100">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between py-2 text-sm">
            <dt className="text-gray-500">{label}</dt>
            <dd className="text-gray-900">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {record.description && (
        <div className="mt-4">
          <p className="text-sm font-medium text-gray-700">Description</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-gray-700">
            {record.description}
          </p>
        </div>
      )}
    </Card>
  );
}

function TimelineCard({ record }: { record: EquipmentRecord }) {
  const events = record.status_events;
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Status timeline</h2>
      {events.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500">
          No status changes yet. Your request is in the queue.
        </p>
      ) : (
        <ol className="mt-3 space-y-3">
          {events.map((e) => (
            <li key={e.id} className="flex items-start gap-3">
              <span className="mt-1 block h-2 w-2 flex-none rounded-full bg-gray-900" />
              <div>
                <p className="text-sm text-gray-900">
                  {e.from_status ? `${e.from_status} → ` : ""}
                  <strong>{e.to_status}</strong>
                </p>
                {e.note && <p className="text-sm text-gray-600">{e.note}</p>}
                <p className="text-xs text-gray-500">{fmt(e.created_at)}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function PhotosCard({ record }: { record: EquipmentRecord }) {
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Photos</h2>
      {record.photos.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500">No photos uploaded yet.</p>
      ) : (
        <ul className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {record.photos.map((p) => {
            const src = photoUrl(p.storage_key);
            return (
              <li
                key={p.id}
                className="overflow-hidden rounded-md border border-gray-200 bg-gray-100"
              >
                {src ? (
                  <img
                    src={src}
                    alt={p.caption ?? "Intake photo"}
                    className="h-32 w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-32 w-full items-center justify-center text-xs text-gray-500">
                    {p.storage_key}
                  </div>
                )}
                <div className="flex items-center justify-between px-2 py-1 text-xs">
                  <span className="truncate text-gray-600">
                    {p.caption ?? "Photo"}
                  </span>
                  <span
                    className={
                      p.scan_status === "clean"
                        ? "text-green-700"
                        : p.scan_status === "pending"
                          ? "text-gray-500"
                          : "text-red-700"
                    }
                  >
                    {p.scan_status}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function ChangeRequestsCard({ recordId }: { recordId: string }) {
  const qc = useQueryClient();
  const [type, setType] = useState<string>("edit_details");
  const [notes, setNotes] = useState("");

  const listQuery = useQuery({
    queryKey: ["change-requests", recordId],
    queryFn: () => listChangeRequests(recordId),
  });

  const mutation = useMutation({
    mutationFn: () =>
      submitChangeRequest(recordId, {
        request_type: type,
        customer_notes: notes || null,
      }),
    onSuccess: () => {
      setNotes("");
      qc.invalidateQueries({ queryKey: ["change-requests", recordId] });
    },
  });

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Change requests</h2>
      <p className="mt-1 text-sm text-gray-600">
        Need to update something or withdraw your submission? Submit a change
        request and your sales rep will respond.
      </p>

      <form
        className="mt-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        noValidate
      >
        <Select
          id="request_type"
          label="Type"
          options={CHANGE_TYPES}
          value={type}
          onChange={(e) => setType(e.target.value)}
        />
        <Textarea
          id="notes"
          label="Notes"
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          hint="Give us enough detail to act — a sales rep reads this and responds."
        />
        {mutation.isError && (
          <Alert tone="error" title="Could not submit change request">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
          </Alert>
        )}
        {mutation.isSuccess && (
          <Alert tone="success" title="Change request submitted">
            Your sales rep has been notified.
          </Alert>
        )}
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Submitting…" : "Submit change request"}
        </Button>
      </form>

      {listQuery.data && listQuery.data.length > 0 && (
        <div className="mt-6 border-t border-gray-200 pt-4">
          <h3 className="text-sm font-medium text-gray-900">Prior requests</h3>
          <ul className="mt-2 space-y-2">
            {listQuery.data.map((c: ChangeRequestOut) => (
              <li
                key={c.id}
                className="rounded-md border border-gray-200 p-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">
                    {c.request_type}
                  </span>
                  <span className="text-xs text-gray-500">
                    {fmt(c.submitted_at)} · {c.status}
                  </span>
                </div>
                {c.customer_notes && (
                  <p className="mt-1 text-gray-700">{c.customer_notes}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
