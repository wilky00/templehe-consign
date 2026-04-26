// ABOUTME: Phase 3 calendar E2E — nav, schedule happy path, 409 conflict, click event → record detail.
// ABOUTME: PATCH/DELETE for events have no UI in Sprint 4, so backend-only flows live in integration tests.
import { expect, test, type Page } from "@playwright/test";
import { seedPhase3, uiLoginAsStaff } from "./helpers/api";

interface SeedDual {
  password: string;
  sales_email: string;
  appraiser_user_id: string;
  customer_user_id: string;
  records: Array<{ equipment_record_id: string; reference_number: string }>;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

function todayPlusMinutes(minutesAhead: number): { date: string; time: string } {
  const d = new Date();
  d.setMinutes(d.getMinutes() + minutesAhead);
  d.setSeconds(0, 0);
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return { date, time };
}

function isInThisWeek(dateStr: string): boolean {
  const target = new Date(`${dateStr}T00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const startOfWeek = new Date(today);
  startOfWeek.setDate(today.getDate() - today.getDay());
  const startOfNextWeek = new Date(startOfWeek);
  startOfNextWeek.setDate(startOfWeek.getDate() + 7);
  return target >= startOfWeek && target < startOfNextWeek;
}

async function fillSchedule(
  page: Page,
  args: { appraiserId: string; date: string; time: string },
) {
  const dialog = page.getByRole("dialog", { name: /schedule appraisal/i });
  await dialog.getByLabel("Appraiser ID").fill(args.appraiserId);
  await dialog.getByLabel("Date").fill(args.date);
  await dialog.getByLabel("Start time").fill(args.time);
  await dialog.getByRole("button", { name: /^schedule$/i }).click();
}

test("calendar smoke: nav + schedule + conflict + click-through", async ({ page }) => {
  // Two records in a single seed call — the seeder wipes the customer's
  // prior records and all future calendar events first, so the calendar
  // is guaranteed empty at landing.
  const fixture = seedPhase3<SeedDual>("default", { records: 2 });
  const [first, second] = fixture.records;

  await uiLoginAsStaff(page, {
    email: fixture.sales_email,
    password: fixture.password,
    fakeIp: randomFakeIp(),
    landingPath: "/sales",
  });

  // ── Nav: Calendar link reaches an empty board ─────────────────────────
  await page.getByRole("link", { name: /^Calendar$/ }).click();
  await expect(page).toHaveURL(/\/sales\/calendar$/);
  await expect(
    page.getByRole("heading", { name: /shared calendar/i }),
  ).toBeVisible();
  await expect(page.getByText(/no appointments in this window/i)).toBeVisible();

  // ── Happy path: schedule first record 30 min from now ─────────────────
  const happyPath = todayPlusMinutes(30);
  await page.goto(`/sales/equipment/${first.equipment_record_id}`);
  await page.getByRole("button", { name: /schedule appraisal/i }).click();
  await fillSchedule(page, {
    appraiserId: fixture.appraiser_user_id,
    date: happyPath.date,
    time: happyPath.time,
  });
  await expect(
    page.getByRole("dialog", { name: /schedule appraisal/i }),
  ).toBeHidden();
  // Status moved off new_request, so the schedule card is gone.
  await expect(
    page.getByRole("heading", { name: /schedule appraisal/i }),
  ).toBeHidden();

  // The event lands on the calendar.
  await page.getByRole("link", { name: /^Calendar$/ }).click();
  await expect(page).toHaveURL(/\/sales\/calendar$/);
  // The default WEEK view shows today's week (Sun–Sat in the browser's
  // TZ). When the test runs near UTC midnight, ``todayPlusMinutes(30)``
  // can land on the following Sunday, putting the event one week out.
  // Advance the calendar with the toolbar's "Next" button when that
  // happens — the assertion stays meaningful either way.
  if (!isInThisWeek(happyPath.date)) {
    await page.getByRole("button", { name: /^next$/i }).click();
  }
  const eventCell = page
    .locator(".rbc-event")
    .filter({ hasText: first.reference_number })
    .first();
  await expect(eventCell).toBeVisible();

  // ── Click-through: tapping the event lands on the record detail. ──────
  await eventCell.click();
  await expect(page).toHaveURL(
    new RegExp(`/sales/equipment/${first.equipment_record_id}$`),
  );
  // Banner shows we're now editing this record.
  await expect(page.getByText(/you are editing this record/i)).toBeVisible();

  // ── Conflict path: overlap second record 60 min from now (within
  // first event's 60-minute duration block) on the same appraiser. ─────
  const conflictAttempt = todayPlusMinutes(60);
  await page.goto(`/sales/equipment/${second.equipment_record_id}`);
  await page.getByRole("button", { name: /schedule appraisal/i }).click();
  await fillSchedule(page, {
    appraiserId: fixture.appraiser_user_id,
    date: conflictAttempt.date,
    time: conflictAttempt.time,
  });

  const dialog = page.getByRole("dialog", { name: /schedule appraisal/i });
  const alert = dialog.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/next available/i);
  await expect(dialog).toBeVisible();
});
