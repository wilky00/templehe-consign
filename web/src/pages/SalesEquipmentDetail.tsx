// ABOUTME: Sales detail view — acquires an edit lock, lets the rep reassign/publish/resolve change requests.
// ABOUTME: Writes require lock.status === "held"; publish is gated on esigned_pending_publish + signed contract + appraisal.
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import {
  getEquipmentDetail,
  overrideLock,
  patchAssignment,
  publishListing,
  resolveChangeRequest,
} from "../api/sales";
import { useMe } from "../hooks/useMe";
import { useRecordLock } from "../hooks/useRecordLock";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { TextInput, Textarea } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";
import { StatusBadge } from "../components/ui/StatusBadge";
import { PhoneLink } from "../components/PhoneLink";
import { RecordLockIndicator } from "../components/RecordLockIndicator";
import { ScheduleAppraisalModal } from "../components/ScheduleAppraisalModal";
import type {
  AssignmentPatch,
  SalesChangeRequest,
  SalesEquipmentDetail,
} from "../api/types";

const MANAGER_ROLES = new Set(["sales_manager", "admin"]);
const PUBLISH_STATUS = "esigned_pending_publish";

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

function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

export function SalesEquipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const canOverride = me ? MANAGER_ROLES.has(me.role) : false;

  const { lock, refresh: refreshLock } = useRecordLock(id);
  const canWrite = lock.status === "held";

  const detailQuery = useQuery({
    queryKey: ["sales-equipment", id],
    queryFn: () => getEquipmentDetail(id!),
    enabled: Boolean(id),
  });

  const onOverride = async () => {
    if (!id) return;
    try {
      await overrideLock(id);
      await refreshLock();
    } catch (err) {
      console.warn("override failed", apiErrorMessage(err));
    }
  };

  if (!id) {
    return (
      <Alert tone="error" title="Missing record id">
        The URL is incomplete.
      </Alert>
    );
  }
  if (detailQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }
  if (detailQuery.isError || !detailQuery.data) {
    return (
      <Alert tone="error" title="Could not load record">
        {apiErrorMessage(detailQuery.error)}
      </Alert>
    );
  }

  const detail = detailQuery.data;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Link to="/sales" className="text-sm text-gray-600 underline">
            ← Back to sales dashboard
          </Link>
          <h1 className="mt-2 text-2xl font-semibold text-gray-900">
            {[detail.year, detail.make, detail.model].filter(Boolean).join(" ") ||
              "Record"}
          </h1>
          <p className="mt-1 font-mono text-sm text-gray-500">
            {detail.reference_number ?? detail.id.slice(0, 8)}
          </p>
        </div>
        <StatusBadge status={detail.status} />
      </div>

      <RecordLockIndicator
        state={lock}
        canOverride={canOverride}
        onOverride={onOverride}
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <CustomerCard detail={detail} />
        <DetailsCard detail={detail} />
      </div>

      <AssignmentCard detail={detail} canWrite={canWrite} recordId={id} />

      {detail.status === "new_request" && (
        <ScheduleCard detail={detail} canWrite={canWrite} recordId={id} />
      )}

      {detail.status === PUBLISH_STATUS && (
        <PublishCard detail={detail} canWrite={canWrite} recordId={id} />
      )}

      <ChangeRequestsCard
        changeRequests={detail.change_requests}
        canWrite={canWrite}
        recordId={id}
      />

      <TimelineCard detail={detail} />
    </div>
  );
}

function CustomerCard({ detail }: { detail: SalesEquipmentDetail }) {
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Customer</h2>
      <dl className="mt-3 space-y-2 text-sm">
        <div>
          <dt className="text-xs uppercase tracking-wide text-gray-500">
            Business
          </dt>
          <dd className="text-gray-900">
            {detail.customer_business_name ?? detail.customer_submitter_name}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-gray-500">
            Submitter
          </dt>
          <dd className="text-gray-900">{detail.customer_submitter_name}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-gray-500">
            Email
          </dt>
          <dd className="text-gray-900">
            <a
              href={`mailto:${detail.customer_email}`}
              className="underline decoration-dotted underline-offset-2"
            >
              {detail.customer_email}
            </a>
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-gray-500">Cell</dt>
          <dd className="text-gray-900">
            <PhoneLink number={detail.customer_cell_phone} />
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-gray-500">
            Office
          </dt>
          <dd className="text-gray-900">
            <PhoneLink number={detail.customer_business_phone} />
          </dd>
        </div>
      </dl>
    </Card>
  );
}

function DetailsCard({ detail }: { detail: SalesEquipmentDetail }) {
  const rows: Array<[string, string | number | null]> = [
    ["Make", detail.make],
    ["Model", detail.model],
    ["Year", detail.year],
    ["Serial / VIN", detail.serial_number],
    ["Hour meter", detail.hours],
    ["Running condition", detail.running_status],
    ["Ownership", detail.ownership_type],
    ["Current location", detail.location_text],
    ["Submitted", detail.submitted_at ? fmt(detail.submitted_at) : null],
  ];
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Equipment</h2>
      <dl className="mt-3 divide-y divide-gray-100">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between py-2 text-sm">
            <dt className="text-gray-500">{label}</dt>
            <dd className="text-gray-900">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {detail.description && (
        <div className="mt-4">
          <p className="text-sm font-medium text-gray-700">Description</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-gray-700">
            {detail.description}
          </p>
        </div>
      )}
    </Card>
  );
}

function AssignmentCard({
  detail,
  canWrite,
  recordId,
}: {
  detail: SalesEquipmentDetail;
  canWrite: boolean;
  recordId: string;
}) {
  const qc = useQueryClient();
  const [salesRepId, setSalesRepId] = useState<string>(
    detail.assigned_sales_rep_id ?? "",
  );
  const [appraiserId, setAppraiserId] = useState<string>(
    detail.assigned_appraiser_id ?? "",
  );

  const initial = useMemo(
    () => ({
      salesRep: detail.assigned_sales_rep_id ?? "",
      appraiser: detail.assigned_appraiser_id ?? "",
    }),
    [detail.assigned_sales_rep_id, detail.assigned_appraiser_id],
  );
  const dirty =
    salesRepId !== initial.salesRep || appraiserId !== initial.appraiser;

  const mutation = useMutation({
    mutationFn: () => {
      const patch: AssignmentPatch = {};
      if (salesRepId !== initial.salesRep) {
        patch.assigned_sales_rep_id = salesRepId ? salesRepId : null;
      }
      if (appraiserId !== initial.appraiser) {
        patch.assigned_appraiser_id = appraiserId ? appraiserId : null;
      }
      return patchAssignment(recordId, patch);
    },
    onSuccess: (updated) => {
      qc.setQueryData(["sales-equipment", recordId], updated);
      qc.invalidateQueries({ queryKey: ["sales-dashboard"] });
    },
  });

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Assignments</h2>
      <p className="mt-1 text-sm text-gray-600">
        IDs will be replaced with user pickers in Phase 4 (Admin panel).
      </p>
      <form
        className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!canWrite || !dirty) return;
          mutation.mutate();
        }}
        noValidate
      >
        <TextInput
          id="assigned-sales-rep"
          label="Sales Rep user ID"
          value={salesRepId}
          onChange={(e) => setSalesRepId(e.target.value)}
          disabled={!canWrite}
          hint="Blank clears the assignment."
        />
        <TextInput
          id="assigned-appraiser"
          label="Appraiser user ID"
          value={appraiserId}
          onChange={(e) => setAppraiserId(e.target.value)}
          disabled={!canWrite}
          hint="Blank clears the assignment."
        />
        <div className="md:col-span-2">
          {mutation.isError && (
            <div className="mb-3">
              <Alert tone="error" title="Could not save assignments">
                {apiErrorMessage(mutation.error)}
              </Alert>
            </div>
          )}
          {mutation.isSuccess && (
            <div className="mb-3">
              <Alert tone="success" title="Assignments saved">
                The record has been updated.
              </Alert>
            </div>
          )}
          <Button
            type="submit"
            disabled={!canWrite || !dirty || mutation.isPending}
          >
            {mutation.isPending ? "Saving…" : "Save assignments"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ScheduleCard({
  detail,
  canWrite,
  recordId,
}: {
  detail: SalesEquipmentDetail;
  canWrite: boolean;
  recordId: string;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Schedule appraisal</h2>
      <p className="mt-1 text-sm text-gray-500">
        Book an on-site appraisal for this record. Conflict + drive-time
        checks run automatically against the appraiser's calendar.
      </p>
      <div className="mt-3">
        <Button
          type="button"
          disabled={!canWrite}
          onClick={() => setOpen(true)}
        >
          Schedule appraisal
        </Button>
      </div>
      <ScheduleAppraisalModal
        open={open}
        recordId={recordId}
        defaultSiteAddress={detail.location_text}
        onClose={() => setOpen(false)}
        onScheduled={() => {
          qc.invalidateQueries({ queryKey: ["sales-equipment", recordId] });
          qc.invalidateQueries({ queryKey: ["calendar-events"] });
        }}
      />
    </Card>
  );
}

function PublishCard({
  detail,
  canWrite,
  recordId,
}: {
  detail: SalesEquipmentDetail;
  canWrite: boolean;
  recordId: string;
}) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => publishListing(recordId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-equipment", recordId] });
      qc.invalidateQueries({ queryKey: ["sales-dashboard"] });
    },
  });

  const missing: string[] = [];
  if (!detail.has_signed_contract) missing.push("signed consignment contract");
  if (!detail.has_appraisal_report) missing.push("appraisal report");
  const blocked = missing.length > 0;

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Publish listing</h2>
      <p className="mt-1 text-sm text-gray-600">
        Manual publish pushes this record to the public listings page.
      </p>
      {blocked && (
        <div className="mt-3">
          <Alert tone="warning" title="Not ready to publish">
            Missing: {missing.join(", ")}.
          </Alert>
        </div>
      )}
      {mutation.isError && (
        <div className="mt-3">
          <Alert tone="error" title="Publish failed">
            {apiErrorMessage(mutation.error)}
          </Alert>
        </div>
      )}
      {mutation.isSuccess && (
        <div className="mt-3">
          <Alert tone="success" title="Listing published">
            The record is now public.
          </Alert>
        </div>
      )}
      <div className="mt-4">
        <Button
          onClick={() => mutation.mutate()}
          disabled={!canWrite || blocked || mutation.isPending}
        >
          {mutation.isPending ? "Publishing…" : "Publish now"}
        </Button>
      </div>
    </Card>
  );
}

function ChangeRequestsCard({
  changeRequests,
  canWrite,
  recordId,
}: {
  changeRequests: SalesChangeRequest[];
  canWrite: boolean;
  recordId: string;
}) {
  const pending = changeRequests.filter((c) => c.status === "pending");
  const history = changeRequests.filter((c) => c.status !== "pending");

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Change requests</h2>
      {pending.length === 0 && history.length === 0 && (
        <p className="mt-3 text-sm text-gray-500">
          The customer hasn't filed any change requests.
        </p>
      )}

      {pending.length > 0 && (
        <div className="mt-4 space-y-3">
          {pending.map((c) => (
            <PendingChangeRequest
              key={c.id}
              change={c}
              canWrite={canWrite}
              recordId={recordId}
            />
          ))}
        </div>
      )}

      {history.length > 0 && (
        <div className="mt-6 border-t border-gray-200 pt-4">
          <h3 className="text-sm font-medium text-gray-900">History</h3>
          <ul className="mt-2 space-y-2">
            {history.map((c) => (
              <li
                key={c.id}
                className="rounded-md border border-gray-200 p-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">
                    {c.request_type}
                  </span>
                  <span className="text-xs text-gray-500">
                    {fmt(c.resolved_at ?? c.submitted_at)} · {c.status}
                  </span>
                </div>
                {c.customer_notes && (
                  <p className="mt-1 text-gray-700">{c.customer_notes}</p>
                )}
                {c.resolution_notes && (
                  <p className="mt-1 text-gray-600">
                    <span className="font-medium">Resolution:</span>{" "}
                    {c.resolution_notes}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function PendingChangeRequest({
  change,
  canWrite,
  recordId,
}: {
  change: SalesChangeRequest;
  canWrite: boolean;
  recordId: string;
}) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");

  const mutation = useMutation({
    mutationFn: (status: "resolved" | "rejected") =>
      resolveChangeRequest(change.id, {
        status,
        resolution_notes: notes || null,
      }),
    onSuccess: () => {
      setNotes("");
      qc.invalidateQueries({ queryKey: ["sales-equipment", recordId] });
      qc.invalidateQueries({ queryKey: ["sales-dashboard"] });
    },
  });

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-900">{change.request_type}</span>
        <span className="text-xs text-gray-500">
          Submitted {fmt(change.submitted_at)}
        </span>
      </div>
      {change.customer_notes && (
        <p className="mt-1 text-gray-700">{change.customer_notes}</p>
      )}
      <div className="mt-3">
        <Textarea
          id={`resolution-${change.id}`}
          label="Resolution notes"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={!canWrite || mutation.isPending}
          hint={
            change.request_type === "withdraw"
              ? "'Resolve' withdraws this record from the pipeline."
              : null
          }
        />
      </div>
      {mutation.isError && (
        <div className="mt-2">
          <Alert tone="error" title="Could not update request">
            {apiErrorMessage(mutation.error)}
          </Alert>
        </div>
      )}
      <div className="mt-3 flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => mutation.mutate("resolved")}
          disabled={!canWrite || mutation.isPending}
        >
          Resolve
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => mutation.mutate("rejected")}
          disabled={!canWrite || mutation.isPending}
        >
          Reject
        </Button>
      </div>
    </div>
  );
}

function TimelineCard({ detail }: { detail: SalesEquipmentDetail }) {
  const events = detail.status_history;
  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Status timeline</h2>
      {events.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500">No status changes yet.</p>
      ) : (
        <ol className="mt-3 space-y-3">
          {events.map((e, i) => (
            <li key={`${e.created_at}-${i}`} className="flex items-start gap-3">
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
