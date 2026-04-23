// ABOUTME: Colored badge for equipment record statuses — shown on the dashboard + detail page.
// ABOUTME: Map a status string to a tone; unknown statuses fall back to gray.
type Tone = "gray" | "blue" | "amber" | "green" | "red" | "purple";

const toneClasses: Record<Tone, string> = {
  gray: "bg-gray-100 text-gray-700",
  blue: "bg-blue-100 text-blue-800",
  amber: "bg-amber-100 text-amber-800",
  green: "bg-green-100 text-green-800",
  red: "bg-red-100 text-red-800",
  purple: "bg-purple-100 text-purple-800",
};

const statusToTone: Record<string, Tone> = {
  new_request: "blue",
  appraiser_assigned: "blue",
  appraisal_scheduled: "amber",
  appraisal_complete: "purple",
  offer_ready: "purple",
  listed: "green",
  sold: "green",
  declined: "red",
  pending_deletion: "red",
};

const statusLabels: Record<string, string> = {
  new_request: "New request",
  appraiser_assigned: "Appraiser assigned",
  appraisal_scheduled: "Appraisal scheduled",
  appraisal_complete: "Appraisal complete",
  offer_ready: "Offer ready",
  listed: "Listed",
  sold: "Sold",
  declined: "Declined",
};

interface Props {
  status: string;
}

export function StatusBadge({ status }: Props) {
  const tone = statusToTone[status] ?? "gray";
  const label = statusLabels[status] ?? status;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${toneClasses[tone]}`}
    >
      {label}
    </span>
  );
}
