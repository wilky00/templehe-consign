// ABOUTME: Phase 3 Sprint 4 — shared calendar at /sales/calendar; month/week/day via react-big-calendar.
// ABOUTME: Click an event → record detail; appraiser-color legend; appraiser multi-select filter.
import { useMemo, useState } from "react";
import { Calendar, dateFnsLocalizer, Views, type View } from "react-big-calendar";
import { format } from "date-fns/format";
import { parse } from "date-fns/parse";
import { startOfWeek } from "date-fns/startOfWeek";
import { getDay } from "date-fns/getDay";
import { enUS } from "date-fns/locale";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import "react-big-calendar/lib/css/react-big-calendar.css";

import { listCalendarEvents } from "../api/calendar";
import type { CalendarEvent } from "../api/types";

const locales = { "en-US": enUS };
const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: (date: Date) => startOfWeek(date, { locale: enUS }),
  getDay,
  locales,
});

interface CalendarEventEntry {
  id: string;
  title: string;
  start: Date;
  end: Date;
  resource: CalendarEvent;
}

// Eight tones distinguishable for color-blind users; cycles for >8 appraisers.
const APPRAISER_PALETTE: ReadonlyArray<{ bg: string; text: string }> = [
  { bg: "#1e3a8a", text: "#ffffff" }, // indigo-900
  { bg: "#0f766e", text: "#ffffff" }, // teal-700
  { bg: "#9d174d", text: "#ffffff" }, // pink-800
  { bg: "#ca8a04", text: "#1f2937" }, // amber-600 on slate-800
  { bg: "#4d7c0f", text: "#ffffff" }, // lime-700
  { bg: "#7c2d12", text: "#ffffff" }, // orange-900
  { bg: "#3f3f46", text: "#ffffff" }, // zinc-700
  { bg: "#1d4ed8", text: "#ffffff" }, // blue-700
];

function colorForAppraiser(
  appraiserId: string,
  knownIds: ReadonlyArray<string>,
): { bg: string; text: string } {
  const idx = Math.max(0, knownIds.indexOf(appraiserId));
  return APPRAISER_PALETTE[idx % APPRAISER_PALETTE.length];
}

function buildTitle(event: CalendarEvent): string {
  const ref = event.equipment?.reference_number ?? "";
  const make = event.equipment?.make ?? "";
  const model = event.equipment?.model ?? "";
  const customer = event.customer?.name ?? event.customer?.business_name ?? "";
  const equipBits = [make, model].filter(Boolean).join(" ");
  const lead = customer || equipBits || ref || "Appraisal";
  return ref ? `${lead} — ${ref}` : lead;
}

export function SalesCalendarPage() {
  const navigate = useNavigate();
  const [view, setView] = useState<View>(Views.WEEK);
  const [date, setDate] = useState<Date>(new Date());
  const [selectedAppraisers, setSelectedAppraisers] = useState<Set<string>>(
    new Set(),
  );

  const range = useMemo(() => computeRange(date, view), [date, view]);
  const eventsQuery = useQuery({
    queryKey: ["calendar-events", range.start.toISOString(), range.end.toISOString()],
    queryFn: () =>
      listCalendarEvents({
        start: range.start.toISOString(),
        end: range.end.toISOString(),
      }),
  });

  const allEvents = useMemo(
    () => eventsQuery.data?.events ?? [],
    [eventsQuery.data],
  );
  const appraiserIds = useMemo(() => {
    const ids: string[] = [];
    for (const e of allEvents) {
      if (!ids.includes(e.appraiser_id)) ids.push(e.appraiser_id);
    }
    return ids;
  }, [allEvents]);

  const visibleEvents: CalendarEventEntry[] = useMemo(() => {
    const filterActive = selectedAppraisers.size > 0;
    return allEvents
      .filter((e) => !filterActive || selectedAppraisers.has(e.appraiser_id))
      .map((e) => ({
        id: e.id,
        title: buildTitle(e),
        start: new Date(e.scheduled_at),
        end: new Date(
          new Date(e.scheduled_at).getTime() + e.duration_minutes * 60_000,
        ),
        resource: e,
      }));
  }, [allEvents, selectedAppraisers]);

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Shared calendar</h1>
        <p className="text-sm text-gray-500">
          {visibleEvents.length} event{visibleEvents.length === 1 ? "" : "s"} in view
        </p>
      </header>

      <div className="rounded-md border border-gray-200 bg-white p-3">
        <h2 className="text-sm font-medium text-gray-700">Filter by appraiser</h2>
        {appraiserIds.length === 0 ? (
          <p className="mt-2 text-xs text-gray-500">
            No appointments in this window.
          </p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-2">
            {appraiserIds.map((id) => {
              const color = colorForAppraiser(id, appraiserIds);
              const active = selectedAppraisers.has(id);
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedAppraisers((prev) => {
                        const next = new Set(prev);
                        if (next.has(id)) next.delete(id);
                        else next.add(id);
                        return next;
                      });
                    }}
                    aria-pressed={active}
                    className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition ${
                      active
                        ? "border-gray-900 bg-gray-900 text-white"
                        : "border-gray-200 bg-white text-gray-700 hover:border-gray-400"
                    }`}
                  >
                    <span
                      aria-hidden
                      className="inline-block h-3 w-3 rounded-full"
                      style={{ backgroundColor: color.bg }}
                    />
                    Appraiser {id.slice(0, 8)}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="rounded-md border border-gray-200 bg-white p-3">
        {eventsQuery.isError ? (
          <p className="text-sm text-red-600">
            Could not load events. Refresh to try again.
          </p>
        ) : (
          <Calendar
            localizer={localizer}
            events={visibleEvents}
            startAccessor="start"
            endAccessor="end"
            view={view}
            onView={(v) => setView(v)}
            date={date}
            onNavigate={(d) => setDate(d)}
            views={[Views.MONTH, Views.WEEK, Views.DAY]}
            style={{ minHeight: 600 }}
            onSelectEvent={(entry) => {
              const e = (entry as CalendarEventEntry).resource;
              navigate(`/sales/equipment/${e.equipment_record_id}`);
            }}
            eventPropGetter={(entry) => {
              const e = (entry as CalendarEventEntry).resource;
              const color = colorForAppraiser(e.appraiser_id, appraiserIds);
              return {
                style: {
                  backgroundColor: color.bg,
                  color: color.text,
                  border: "none",
                  borderRadius: "4px",
                  paddingLeft: "6px",
                },
              };
            }}
          />
        )}
      </div>
    </div>
  );
}

function computeRange(date: Date, view: View): { start: Date; end: Date } {
  const start = new Date(date);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  if (view === Views.MONTH) {
    start.setDate(1);
    start.setDate(start.getDate() - 7); // include trailing days from prior month
    end.setMonth(end.getMonth() + 1, 1);
    end.setDate(end.getDate() + 7);
  } else if (view === Views.WEEK) {
    const day = start.getDay();
    start.setDate(start.getDate() - day);
    end.setTime(start.getTime());
    end.setDate(end.getDate() + 7);
  } else {
    end.setDate(end.getDate() + 1);
  }
  return { start, end };
}
