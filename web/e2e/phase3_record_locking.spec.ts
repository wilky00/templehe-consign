// ABOUTME: Phase 3 Sprint 6 — record-lock lifecycle: acquire, conflict for second viewer, manager override + email.
// ABOUTME: Notification worker must be running to drain the override email into Mailpit (set up by CI).
import { expect, test } from "@playwright/test";
import { seedPhase3, uiLoginAsStaff } from "./helpers/api";
import { clearInbox, waitForEmailBody } from "./helpers/mailpit";

interface LockingFixture {
  password: string;
  sales_user_id: string;
  sales_email: string;
  manager_user_id: string;
  manager_email: string;
  customer_id: string;
  equipment_record_id: string;
  reference_number: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

test("lock lifecycle: rep acquires; manager sees conflict + overrides + email lands", async ({
  browser,
}) => {
  // Drop prior runs' emails so the subject-based wait below can't match a
  // stale lock-override email for an earlier reference number.
  await clearInbox();
  const fixture = seedPhase3<LockingFixture>("locking");

  // Two isolated browser contexts so each user keeps their own session.
  const repCtx = await browser.newContext();
  const managerCtx = await browser.newContext();
  const repPage = await repCtx.newPage();
  const managerPage = await managerCtx.newPage();

  try {
    // ── Rep: opens the record, lock acquires. ────────────────────────────
    await uiLoginAsStaff(repPage, {
      email: fixture.sales_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/sales/equipment/${fixture.equipment_record_id}`,
    });
    await expect(repPage.getByText(/you are editing this record/i)).toBeVisible();

    // ── Manager: opens the same record, sees the conflict banner. ────────
    await uiLoginAsStaff(managerPage, {
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/sales/equipment/${fixture.equipment_record_id}`,
    });
    await expect(
      managerPage.getByText(/locked by another user/i),
    ).toBeVisible();

    // Manager has the override affordance; rep would not.
    const overrideBtn = managerPage.getByRole("button", {
      name: /break lock \(manager override\)/i,
    });
    await expect(overrideBtn).toBeVisible();

    // Click the override. The current UI clears the conflict banner but
    // doesn't auto-acquire a new lock for the manager — that's a known UX
    // gap (tracked separately). Assert what the user actually sees today:
    // the conflict alert disappears and the page leaves the locked state.
    await overrideBtn.click();
    await expect(
      managerPage.getByText(/locked by another user/i),
    ).toBeHidden();

    // ── Email: rep gets the broken-lock notification via Mailpit. ────────
    // Subject template embeds THE-XXXXXXXX so we match on the ref number
    // directly — that ties this assertion to the just-overridden record.
    const body = await waitForEmailBody(
      fixture.sales_email,
      fixture.reference_number,
    );
    expect(body).toContain(fixture.reference_number);
  } finally {
    await repCtx.close();
    await managerCtx.close();
  }
});
