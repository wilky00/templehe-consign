// ABOUTME: Phase 3 Sprint 4 calendar smoke — sales nav, schedule happy path, 409 conflict banner.
// ABOUTME: Full UI gate (axe + Lighthouse + click-to-detail + cancel) is deferred to Sprint 6.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { uiLoginAsStaff } from "./helpers/api";

const HERE = path.dirname(fileURLToPath(import.meta.url));

interface SeedPayload {
  password: string;
  sales_email: string;
  appraiser_user_id: string;
  customer_user_id: string;
  equipment_record_id: string;
  reference_number: string;
}

function seedPhase3Fixture(): SeedPayload {
  const repoRoot = path.resolve(HERE, "..", "..");
  const out = execFileSync(
    "uv",
    ["run", "python", path.join(repoRoot, "scripts", "seed_e2e_phase3.py")],
    {
      cwd: path.join(repoRoot, "api"),
      env: {
        ...process.env,
        DATABASE_URL:
          process.env.E2E_DATABASE_URL ??
          "postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe",
      },
      encoding: "utf8",
    },
  );
  return JSON.parse(out.trim()) as SeedPayload;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

function todayPlusMinutes(minutesAhead: number): { date: string; time: string } {
  // Schedule into the same calendar day as today so the default week view
  // on /sales/calendar is guaranteed to render the event.
  const d = new Date();
  d.setMinutes(d.getMinutes() + minutesAhead);
  d.setSeconds(0, 0);
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return { date, time };
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

test("calendar smoke: nav + schedule + conflict", async ({ page }) => {
  // Two records — first for the happy path, second for the conflict path.
  // The seeder reuses the deterministic sales/appraiser/customer users.
  const first = seedPhase3Fixture();
  const second = seedPhase3Fixture();
  expect(second.appraiser_user_id).toBe(first.appraiser_user_id);

  await uiLoginAsStaff(page, {
    email: first.sales_email,
    password: first.password,
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
    appraiserId: first.appraiser_user_id,
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
  await expect(page.getByText(new RegExp(first.reference_number))).toBeVisible();

  // ── Conflict path: overlap second record 60 min from now (within
  // first event's 60-minute duration block) on the same appraiser. ─────
  const conflictAttempt = todayPlusMinutes(60);
  await page.goto(`/sales/equipment/${second.equipment_record_id}`);
  await page.getByRole("button", { name: /schedule appraisal/i }).click();
  await fillSchedule(page, {
    appraiserId: second.appraiser_user_id,
    date: conflictAttempt.date,
    time: conflictAttempt.time,
  });

  const dialog = page.getByRole("dialog", { name: /schedule appraisal/i });
  const alert = dialog.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/next available/i);
  await expect(dialog).toBeVisible();
});
