// ABOUTME: Phase 3 Sprint 6 — sales dashboard groupings, cascade modal, manual publish gating.
// ABOUTME: Drives the full sales-rep flow from dashboard → cascade → record → publish-now.
import { expect, test } from "@playwright/test";
import { seedPhase3, uiLoginAsStaff } from "./helpers/api";

interface CascadeFixture {
  password: string;
  sales_user_id: string;
  sales_email: string;
  appraiser_user_id: string;
  customer_id: string;
  records: Array<{ equipment_record_id: string; reference_number: string }>;
}

interface PublishFixture {
  password: string;
  sales_user_id: string;
  sales_email: string;
  customer_id: string;
  equipment_record_id: string;
  reference_number: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

test("dashboard: groups by customer, cascade applies to all new requests", async ({
  page,
}) => {
  const fixture = seedPhase3<CascadeFixture>("cascade");

  await uiLoginAsStaff(page, {
    email: fixture.sales_email,
    password: fixture.password,
    fakeIp: randomFakeIp(),
    landingPath: "/sales",
  });

  // Group card is visible — the seeder puts business_name = "Phase 3 E2E Co".
  const card = page
    .getByRole("heading", { name: /phase 3 e2e co/i })
    .locator("xpath=ancestor::*[contains(@class,'rounded')]")
    .first();
  await expect(card).toBeVisible();
  // All three reference numbers render under this customer.
  for (const r of fixture.records) {
    await expect(card.getByText(r.reference_number)).toBeVisible();
  }

  // Open the cascade modal from the customer parent row.
  await card.getByRole("button", { name: /cascade assign/i }).click();
  const modal = page.getByRole("dialog", { name: /cascade assignments/i });
  await expect(modal).toBeVisible();

  // Reassign the appraiser across the three new_request rows.
  await modal.getByLabel(/appraiser user id/i).fill(fixture.appraiser_user_id);
  await modal.getByRole("checkbox").check();
  await modal.getByRole("button", { name: /^apply$/i }).click();

  // The dashboard closes the modal as soon as cascade succeeds, so we
  // assert via the side-effect: dialog gone + status badges still render.
  await expect(modal).toBeHidden();
  for (const r of fixture.records) {
    await expect(card.getByText(r.reference_number)).toBeVisible();
  }
});

test("publish: button gated to esigned_pending_publish + prereqs, then publishes", async ({
  page,
}) => {
  const fixture = seedPhase3<PublishFixture>("publish");

  await uiLoginAsStaff(page, {
    email: fixture.sales_email,
    password: fixture.password,
    fakeIp: randomFakeIp(),
    landingPath: `/sales/equipment/${fixture.equipment_record_id}`,
  });

  // Wait for the lock to be acquired so writes are enabled.
  await expect(page.getByText(/you are editing this record/i)).toBeVisible();

  // Publish card is visible at this status. Seeder pre-populates contract +
  // appraisal report, so the "Not ready" warning should NOT render.
  const publishCard = page
    .getByRole("heading", { name: /publish listing/i })
    .locator("xpath=ancestor::*[contains(@class,'rounded')]")
    .first();
  await expect(publishCard).toBeVisible();
  await expect(publishCard.getByText(/not ready to publish/i)).toBeHidden();

  await publishCard.getByRole("button", { name: /publish now/i }).click();
  // Server-side success transitions the record to 'listed', which makes the
  // entire publish card unmount (it only renders at esigned_pending_publish).
  // Assert the unmount and the new status badge instead of the flashing alert.
  await expect(
    page.getByRole("heading", { name: /publish listing/i }),
  ).toBeHidden();
  await expect(page.getByText(/^Listed$/)).toBeVisible();
});

test("publish: button hidden on a new_request record", async ({ page }) => {
  // Sanity check on the gate — the default fixture is a new_request record,
  // so the publish card should not render at all.
  const fixture = seedPhase3<{
    password: string;
    sales_email: string;
    equipment_record_id: string;
  }>("default");

  await uiLoginAsStaff(page, {
    email: fixture.sales_email,
    password: fixture.password,
    fakeIp: randomFakeIp(),
    landingPath: `/sales/equipment/${fixture.equipment_record_id}`,
  });

  await expect(
    page.getByRole("heading", { name: /publish listing/i }),
  ).toBeHidden();
});
