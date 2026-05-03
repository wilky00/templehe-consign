// ABOUTME: Phase 7 gate — PDF report download UI acceptance scenarios.
// ABOUTME: Covers report card visibility, generating state, non-eligible status, and accessibility.
import { expect, test } from "@playwright/test";
import { assertA11y } from "./helpers/axe";
import { seedPhase7, uiLoginAsStaff } from "./helpers/api";

interface Phase7Fixture {
  customer_email: string;
  customer_id: string;
  sales_email: string;
  sales_id: string;
  password: string;
  record_id: string;
  reference_number: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

test.describe("Phase 7 gate — PDF report download UI", () => {
  // Scenario 1: Customer portal shows "generating" message for approved record
  test("customer portal shows report card with generating message for approved record", async ({
    page,
  }) => {
    const fixture = seedPhase7<Phase7Fixture>("approved");

    await uiLoginAsStaff(page, {
      email: fixture.customer_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/portal/equipment/${fixture.record_id}`,
    });

    await expect(
      page.getByRole("heading", { name: /appraisal report/i }),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.getByText(/your report is being prepared/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  // Scenario 2: Report section is NOT shown for non-eligible statuses
  test("report card is hidden when record is in new_request status", async ({
    page,
  }) => {
    const fixture = seedPhase7<Phase7Fixture>("new_request");

    await uiLoginAsStaff(page, {
      email: fixture.customer_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/portal/equipment/${fixture.record_id}`,
    });

    // Wait for the page to finish loading (reference number is present)
    await expect(
      page.getByText(fixture.reference_number),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.getByRole("heading", { name: /appraisal report/i }),
    ).not.toBeVisible();
  });

  // Scenario 3: Sales rep detail view shows report card for approved record
  test("sales rep detail view shows report card for approved record", async ({
    page,
  }) => {
    const fixture = seedPhase7<Phase7Fixture>("approved");

    await uiLoginAsStaff(page, {
      email: fixture.sales_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/sales/equipment/${fixture.record_id}`,
    });

    await expect(
      page.getByRole("heading", { name: /appraisal report/i }),
    ).toBeVisible({ timeout: 10_000 });
  });

  // Scenario 4: Accessibility scan on the customer portal with an approved record
  test("customer portal report card is accessible", async ({ page }) => {
    const fixture = seedPhase7<Phase7Fixture>("approved");

    await uiLoginAsStaff(page, {
      email: fixture.customer_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/portal/equipment/${fixture.record_id}`,
    });

    await expect(
      page.getByRole("heading", { name: /appraisal report/i }),
    ).toBeVisible({ timeout: 10_000 });

    await assertA11y(page);
  });

  // Scenario 5: API-level RBAC — wrong customer gets 403
  test("customer cannot fetch report for another customer's record via API", async ({
    request,
  }) => {
    const approved = seedPhase7<Phase7Fixture>("approved");
    const otherFixture = seedPhase7<Phase7Fixture>("new_request");

    // Log in as the new_request customer (different from approved record's customer)
    const loginResp = await request.post("/api/v1/auth/login", {
      data: { email: otherFixture.customer_email, password: otherFixture.password },
    });
    const { access_token } = (await loginResp.json()) as { access_token: string };

    const reportResp = await request.get(
      `/api/v1/equipment-records/${approved.record_id}/report/pdf`,
      {
        headers: { Authorization: `Bearer ${access_token}` },
      },
    );
    expect(reportResp.status()).toBe(403);
  });
});
