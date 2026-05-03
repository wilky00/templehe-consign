// ABOUTME: Manager approval detail — full submission review with approve/reject forms and record locking.
// ABOUTME: Title-review warning blocks approval until the manager explicitly confirms the hold.
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { RecordLockIndicator } from "../components/RecordLockIndicator";
import { useRecordLock } from "../hooks/useRecordLock";
import { getApprovalDetail, approveSubmission, rejectSubmission } from "../api/approvals";
import type { SubmissionDetail } from "../api/approvals";
import { useMe } from "../hooks/useMe";

const MANAGER_ROLES = new Set(["sales_manager", "admin"]);

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="py-2 sm:grid sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm font-medium text-gray-500">{label}</dt>
      <dd className="mt-1 text-sm text-gray-900 sm:col-span-2 sm:mt-0">{value ?? "—"}</dd>
    </div>
  );
}

function ScoreBar({ score }: { score: number | null }) {
  if (score === null) return null;
  const pct = Math.min(100, (score / 5) * 100);
  const color =
    score >= 4.5
      ? "bg-green-500"
      : score >= 3.75
        ? "bg-blue-500"
        : score >= 3.0
          ? "bg-yellow-500"
          : "bg-red-500";
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 overflow-hidden rounded-full bg-gray-200" style={{ height: 8 }}>
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-semibold text-gray-900">{score.toFixed(2)} / 5.00</span>
    </div>
  );
}

function SubmissionReadOnly({ sub }: { sub: SubmissionDetail }) {
  return (
    <dl className="divide-y divide-gray-100">
      <DetailRow label="Status" value={sub.status} />
      <DetailRow
        label="Equipment"
        value={[sub.make, sub.model, sub.year].filter(Boolean).join(" ") || "—"}
      />
      <DetailRow label="Serial number" value={sub.serial_number} />
      <DetailRow label="Running status" value={sub.running_status} />
      <DetailRow label="Hours condition" value={sub.hours_condition} />
      <DetailRow label="Title status" value={sub.title_status} />
      <DetailRow label="Marketability rating" value={sub.marketability_rating} />
      <DetailRow label="Transport notes" value={sub.transport_notes} />
      <DetailRow label="Listing notes" value={sub.listing_notes} />
      {sub.review_notes && <DetailRow label="Review notes" value={sub.review_notes} />}
      {sub.component_scores.length > 0 && (
        <div className="py-3">
          <dt className="mb-2 text-sm font-medium text-gray-500">Component scores</dt>
          <dd>
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                  <th className="pb-1 pr-4">Component</th>
                  <th className="pb-1 pr-4">Score</th>
                  <th className="pb-1">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {sub.component_scores.map((cs) => (
                  <tr key={cs.id}>
                    <td className="py-1 pr-4 text-gray-700">{cs.component_name}</td>
                    <td className="py-1 pr-4 font-medium text-gray-900">
                      {cs.raw_score.toFixed(1)}
                    </td>
                    <td className="py-1 text-gray-500">{cs.notes ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </dd>
        </div>
      )}
    </dl>
  );
}

function ApproveForm({
  submissionId,
  holdForTitle,
  onSuccess,
}: {
  submissionId: string;
  holdForTitle: boolean;
  onSuccess: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [purchaseOffer, setPurchaseOffer] = useState("");
  const [consignmentPrice, setConsignmentPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [titleConfirmed, setTitleConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      approveSubmission(submissionId, {
        purchase_offer: parseFloat(purchaseOffer),
        consignment_price: parseFloat(consignmentPrice),
        notes: notes || undefined,
        title_review_confirmed: titleConfirmed,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["manager-approval-queue"] });
      qc.invalidateQueries({ queryKey: ["manager-approval-detail", submissionId] });
      onSuccess();
      navigate("/manager/approvals");
    },
    onError: (err: Error) => setError(err.message),
  });

  const canSubmit =
    purchaseOffer !== "" &&
    consignmentPrice !== "" &&
    !isNaN(parseFloat(purchaseOffer)) &&
    !isNaN(parseFloat(consignmentPrice)) &&
    (!holdForTitle || titleConfirmed);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        mutation.mutate();
      }}
      className="space-y-4"
      aria-label="Approve appraisal"
    >
      {holdForTitle && (
        <div
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800"
          role="alert"
        >
          <strong>Title review required.</strong> This submission has a title hold. Confirm you have
          reviewed the title status before approving.
          <label className="mt-2 flex items-center gap-2 font-medium">
            <input
              type="checkbox"
              checked={titleConfirmed}
              onChange={(e) => setTitleConfirmed(e.target.checked)}
              aria-label="Title review confirmed"
            />
            Title review confirmed
          </label>
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700" htmlFor="purchase-offer">
          Purchase offer ($)
        </label>
        <input
          id="purchase-offer"
          type="number"
          min="0"
          step="0.01"
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={purchaseOffer}
          onChange={(e) => setPurchaseOffer(e.target.value)}
          required
          aria-required="true"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700" htmlFor="consignment-price">
          Consignment price ($)
        </label>
        <input
          id="consignment-price"
          type="number"
          min="0"
          step="0.01"
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={consignmentPrice}
          onChange={(e) => setConsignmentPrice(e.target.value)}
          required
          aria-required="true"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700" htmlFor="approval-notes">
          Notes (optional)
        </label>
        <textarea
          id="approval-notes"
          rows={3}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
      {error && (
        <Alert tone="error" title="Approval failed">
          {error}
        </Alert>
      )}
      <Button
        type="submit"
        disabled={!canSubmit || mutation.isPending}
        aria-label="Submit approval"
      >
        {mutation.isPending ? "Approving…" : "Approve"}
      </Button>
    </form>
  );
}

function RejectForm({
  submissionId,
  onSuccess,
}: {
  submissionId: string;
  onSuccess: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [rejectionNotes, setRejectionNotes] = useState("");
  const [sendBack, setSendBack] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      rejectSubmission(submissionId, {
        rejection_notes: rejectionNotes,
        send_back: sendBack,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["manager-approval-queue"] });
      qc.invalidateQueries({ queryKey: ["manager-approval-detail", submissionId] });
      onSuccess();
      navigate("/manager/approvals");
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        mutation.mutate();
      }}
      className="space-y-4"
      aria-label="Reject appraisal"
    >
      <div>
        <label className="block text-sm font-medium text-gray-700" htmlFor="rejection-notes">
          Rejection notes
        </label>
        <textarea
          id="rejection-notes"
          rows={4}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={rejectionNotes}
          onChange={(e) => setRejectionNotes(e.target.value)}
          required
          aria-required="true"
          placeholder="Explain why you are rejecting this appraisal…"
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={sendBack}
          onChange={(e) => setSendBack(e.target.checked)}
          aria-label="Send back for re-appraisal"
        />
        Send back for re-appraisal (instead of permanent rejection)
      </label>
      {error && (
        <Alert tone="error" title="Rejection failed">
          {error}
        </Alert>
      )}
      <Button
        type="submit"
        disabled={!rejectionNotes.trim() || mutation.isPending}
        variant="danger"
        aria-label="Submit rejection"
      >
        {mutation.isPending ? "Rejecting…" : sendBack ? "Send back for re-appraisal" : "Reject permanently"}
      </Button>
    </form>
  );
}

export function ManagerApprovalDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const isManager = me ? MANAGER_ROLES.has(me.role) : false;

  const { lock, override } = useRecordLock(id);

  const query = useQuery<SubmissionDetail>({
    queryKey: ["manager-approval-detail", id],
    queryFn: () => getApprovalDetail(id!),
    enabled: !!id,
  });

  const [actionDone, setActionDone] = useState(false);

  if (!id) return <Alert tone="error" title="Missing submission ID" />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Approval review</h1>
          {query.data && (
            <p className="mt-1 text-sm text-gray-600">
              {[query.data.make, query.data.model, query.data.year].filter(Boolean).join(" ")} ·{" "}
              {query.data.score_band ?? ""}
            </p>
          )}
        </div>
        <RecordLockIndicator
          state={lock}
          canOverride={isManager}
          onOverride={override}
        />
      </div>

      {query.isLoading && <Spinner />}
      {query.isError && (
        <Alert tone="error" title="Could not load submission">
          {(query.error as Error).message}
        </Alert>
      )}

      {query.data && (
        <>
          {/* Score overview */}
          <Card>
            <h2 className="mb-3 text-base font-semibold text-gray-900">Overall score</h2>
            <ScoreBar score={query.data.overall_score} />
            {query.data.score_band && (
              <p className="mt-2 text-sm text-gray-600">{query.data.score_band}</p>
            )}
          </Card>

          {/* Red flags */}
          {(query.data.management_review_required || query.data.hold_for_title_review) && (
            <div className="space-y-2">
              {query.data.management_review_required && (
                <Alert tone="error" title="Management review required">
                  This submission has been flagged for management review.
                  {query.data.review_notes && ` Notes: ${query.data.review_notes}`}
                </Alert>
              )}
              {query.data.hold_for_title_review && (
                <Alert tone="warning" title="Title review hold">
                  The serial plate or title status requires review before this appraisal can be approved.
                </Alert>
              )}
            </div>
          )}

          {/* Submission details */}
          <Card>
            <h2 className="mb-3 text-base font-semibold text-gray-900">Submission details</h2>
            <SubmissionReadOnly sub={query.data} />
          </Card>

          {/* Approve / reject — only show if submission is still pending */}
          {query.data.status === "submitted" && !actionDone && (
            <div className="grid gap-6 sm:grid-cols-2">
              <Card>
                <h2 className="mb-4 text-base font-semibold text-gray-900">Approve</h2>
                <ApproveForm
                  submissionId={id}
                  holdForTitle={query.data.hold_for_title_review}
                  onSuccess={() => setActionDone(true)}
                />
              </Card>
              <Card>
                <h2 className="mb-4 text-base font-semibold text-gray-900">Reject</h2>
                <RejectForm submissionId={id} onSuccess={() => setActionDone(true)} />
              </Card>
            </div>
          )}

          {query.data.status !== "submitted" && (
            <Alert tone="info" title={`Appraisal ${query.data.status}`}>
              This appraisal has already been {query.data.status}.
            </Alert>
          )}
        </>
      )}
    </div>
  );
}
