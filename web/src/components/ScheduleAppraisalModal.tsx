// ABOUTME: Phase 3 Sprint 4 — modal to schedule an appraisal on a new_request equipment record.
// ABOUTME: Captures appraiser UUID, datetime, duration, and site address; surfaces 409 conflict with next-available hint.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { createCalendarEvent } from "../api/calendar";
import type { UUID } from "../api/types";

interface Props {
  open: boolean;
  recordId: UUID;
  defaultSiteAddress: string | null;
  onClose: () => void;
  onScheduled: () => void;
}

interface FormState {
  appraiserId: string;
  date: string;
  time: string;
  durationMinutes: number;
  siteAddress: string;
}

export function ScheduleAppraisalModal({
  open,
  recordId,
  defaultSiteAddress,
  onClose,
  onScheduled,
}: Props) {
  const [form, setForm] = useState<FormState>({
    appraiserId: "",
    date: "",
    time: "",
    durationMinutes: 60,
    siteAddress: defaultSiteAddress ?? "",
  });
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  const [nextAvailableLocal, setNextAvailableLocal] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const scheduledAt = new Date(`${form.date}T${form.time}`).toISOString();
      return createCalendarEvent({
        equipment_record_id: recordId,
        appraiser_id: form.appraiserId,
        scheduled_at: scheduledAt,
        duration_minutes: form.durationMinutes,
        site_address: form.siteAddress.trim() || null,
      });
    },
    onSuccess: (result) => {
      if (result.ok) {
        onScheduled();
        onClose();
      } else {
        setConflictMessage(result.conflict.detail);
        if (result.conflict.next_available_at) {
          const local = new Date(result.conflict.next_available_at);
          setNextAvailableLocal(local.toLocaleString());
        }
      }
    },
  });

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="schedule-appraisal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="schedule-appraisal-title" className="text-lg font-semibold text-gray-900">
          Schedule appraisal
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Book this record on an appraiser's calendar. Drive time from the prior
          stop is checked automatically.
        </p>

        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            setConflictMessage(null);
            setNextAvailableLocal(null);
            mutation.mutate();
          }}
        >
          <Field
            label="Appraiser ID"
            id="sa-appraiser"
            type="text"
            value={form.appraiserId}
            onChange={(v) => setForm({ ...form, appraiserId: v })}
            required
            placeholder="UUID — searchable picker arrives in Phase 4"
          />
          <div className="grid grid-cols-2 gap-2">
            <Field
              label="Date"
              id="sa-date"
              type="date"
              value={form.date}
              onChange={(v) => setForm({ ...form, date: v })}
              required
            />
            <Field
              label="Start time"
              id="sa-time"
              type="time"
              value={form.time}
              onChange={(v) => setForm({ ...form, time: v })}
              required
            />
          </div>
          <Field
            label="Duration (minutes)"
            id="sa-duration"
            type="number"
            value={String(form.durationMinutes)}
            onChange={(v) =>
              setForm({ ...form, durationMinutes: Number.parseInt(v || "60", 10) })
            }
            min={15}
            max={480}
            required
          />
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Site address</span>
            <textarea
              rows={2}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
              value={form.siteAddress}
              onChange={(e) => setForm({ ...form, siteAddress: e.target.value })}
            />
          </label>

          {conflictMessage && (
            <div
              role="alert"
              className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
            >
              <p>{conflictMessage}</p>
              {nextAvailableLocal && (
                <p className="mt-1 text-xs">
                  Next available: <strong>{nextAvailableLocal}</strong>
                </p>
              )}
            </div>
          )}
          {mutation.isError && !conflictMessage && (
            <p role="alert" className="text-sm text-red-600">
              Could not schedule. Check the inputs and try again.
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
            >
              {mutation.isPending ? "Scheduling…" : "Schedule"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface FieldProps {
  label: string;
  id: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  placeholder?: string;
  min?: number;
  max?: number;
}

function Field(props: FieldProps) {
  return (
    <label htmlFor={props.id} className="block">
      <span className="text-sm font-medium text-gray-700">{props.label}</span>
      <input
        id={props.id}
        type={props.type}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        required={props.required}
        placeholder={props.placeholder}
        min={props.min}
        max={props.max}
        className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
      />
    </label>
  );
}
