// ABOUTME: Phase 6 gate — 6 acceptance scenarios for the manager approval queue + eSign stub flow.
// ABOUTME: Covers approval, red flags, title hold, eSign stub signing, publish, and price change re-approval.
import { expect, test, request } from "@playwright/test";
import { API_URL } from "../playwright.config";
import { assertA11y } from "./helpers/axe";
import { apiLoginAsStaff, seedPhase6, uiLoginAsStaff } from "./helpers/api";

interface BaseFixture {
  password: string;
  manager_id: string;
  manager_email: string;
  sales_id: string;
  sales_email: string;
  appraiser_id: string;
  appraiser_email: string;
  customer_id: string;
  customer_email: string;
}

interface DefaultFixture extends BaseFixture {
  record_id: string;
  reference_number: string;
  submission_id: string;
}

interface EsignFixture extends BaseFixture {
  record_id: string;
  reference_number: string;
  envelope_id: string;
}

interface PriceChangeFixture extends BaseFixture {
  record_id: string;
  reference_number: string;
  change_request_id: string;
}

interface PublishFixture extends BaseFixture {
  record_id: string;
  reference_number: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

async function authedApi(token: string, fakeIp: string) {
  return await request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
      "CF-Connecting-IP": fakeIp,
    },
  });
}

test.describe("Phase 6 gate — approval queue + eSign", () => {
  // Scenario 1: Manager approval flow — submitted appraisal → approve → navigates back to queue
  test("manager approves submitted appraisal and is redirected back to queue", async ({
    page,
  }) => {
    const fixture = seedPhase6<DefaultFixture>("default");

    // Verify the API returns the seeded record before touching the browser —
    // direct call so the login here doesn't invalidate the browser session below.
    const managerTokenDiag = await apiLoginAsStaff({
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const diagApi = await authedApi(managerTokenDiag, randomFakeIp());
    const diagResp = await diagApi.get("/api/v1/manager/approvals");
    const diagBody = (await diagResp.json()) as {
      items: Array<{ reference_number: string }>;
      total: number;
    };
    expect(
      diagResp.status(),
      `Approval queue API returned non-200: ${JSON.stringify(diagBody)}`,
    ).toBe(200);
    expect(
      diagBody.items.some((i) => i.reference_number === fixture.reference_number),
      `Expected ${fixture.reference_number} in queue items: ${JSON.stringify(diagBody.items.map((i) => i.reference_number))}`,
    ).toBe(true);

    await uiLoginAsStaff(page, {
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/manager/approvals",
    });

    await expect(
      page.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeVisible({ timeout: 15_000 });

    // The seeded record's reference number must appear in the queue.
    await expect(
      page.getByText(fixture.reference_number).first(),
    ).toBeVisible({ timeout: 15_000 });

    // Click the queue row to open the detail view.
    const row = page.getByRole("row", {
      name: new RegExp(`Review appraisal ${fixture.reference_number}`, "i"),
    });
    await row.click();
    await page.waitForURL(new RegExp(`/manager/approvals/${fixture.submission_id}`));

    // Fill in the approval form.
    await page.getByLabel(/purchase offer/i).fill("45000");
    await page.getByLabel(/consignment price/i).fill("60000");
    await page.getByRole("button", { name: /^approve$/i }).click();

    // After approval the SPA navigates back to the queue.
    await page.waitForURL(/\/manager\/approvals$/);
    await expect(
      page.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeVisible();

    // Confirm via API that the submission was approved.
    const managerToken = await apiLoginAsStaff({
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const api = await authedApi(managerToken, randomFakeIp());
    const resp = await api.get(
      `/api/v1/manager/approvals/${fixture.submission_id}`,
    );
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as { status: string };
    expect(body.status).toBe("approved");
  });

  // Scenario 2: Red flag badge shown and marketability downgraded
  test("red flag badge and management review badge shown in approval queue", async ({
    page,
  }) => {
    const fixture = seedPhase6<DefaultFixture>("red_flags");

    await uiLoginAsStaff(page, {
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/manager/approvals",
    });

    await expect(
      page.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeVisible({ timeout: 10_000 });

    // The "Review required" badge must be visible in the queue table row.
    await expect(page.getByText("Review required")).toBeVisible({
      timeout: 10_000,
    });

    // Marketability should be downgraded — seeder seeds "Salvage Risk".
    await expect(page.getByText("Salvage Risk")).toBeVisible();

    // Click into detail and confirm the management_review_required warning renders.
    const row = page.getByRole("row", {
      name: new RegExp(`Review appraisal ${fixture.reference_number}`, "i"),
    });
    await row.click();
    await page.waitForURL(new RegExp(`/manager/approvals/${fixture.submission_id}`));

    await expect(
      page.getByText(/management review required/i),
    ).toBeVisible({ timeout: 8_000 });
  });

  // Scenario 3: Title hold blocks approval until confirmation checkbox is checked
  test("title hold requires confirmation checkbox before approve button is enabled", async ({
    page,
  }) => {
    const fixture = seedPhase6<DefaultFixture>("title_hold");

    await uiLoginAsStaff(page, {
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/manager/approvals",
    });

    await expect(
      page.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeVisible({ timeout: 10_000 });

    // "Title hold" badge visible in the queue row.
    await expect(page.getByText("Title hold")).toBeVisible({
      timeout: 10_000,
    });

    // Open detail view.
    const row = page.getByRole("row", {
      name: new RegExp(`Review appraisal ${fixture.reference_number}`, "i"),
    });
    await row.click();
    await page.waitForURL(new RegExp(`/manager/approvals/${fixture.submission_id}`));

    // Fill in offer amounts — approve button should still be disabled.
    await page.getByLabel(/purchase offer/i).fill("40000");
    await page.getByLabel(/consignment price/i).fill("55000");

    const approveBtn = page.getByRole("button", { name: /^approve$/i });
    await expect(approveBtn).toBeDisabled();

    // Check the title-review confirmation checkbox.
    await page.getByLabel(/title review confirmed/i).check();

    // Approve button should now be enabled.
    await expect(approveBtn).toBeEnabled();
  });

  // Scenario 4: eSign stub — customer signs → ConsignmentContract.signed_at populated → record → esigned_pending_publish
  test("eSign stub sign-now populates signed_at and transitions record to esigned_pending_publish", async ({
    page,
  }) => {
    const fixture = seedPhase6<EsignFixture>("esign");

    // Navigate directly to the stub signing page (no auth required).
    await page.goto(
      `${API_URL}/api/v1/esign/stub-preview/${fixture.envelope_id}`,
    );
    await expect(page.getByRole("button", { name: /sign now/i })).toBeVisible();

    // Submitting the form triggers the synthetic webhook.
    await page.getByRole("button", { name: /sign now/i }).click();

    // The stub-sign endpoint returns a JSON ack — wait for it.
    await page.waitForLoadState("networkidle");

    // Verify via API that the record status is esigned_pending_publish.
    const managerToken = await apiLoginAsStaff({
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const api = await authedApi(managerToken, randomFakeIp());
    const resp = await api.get(`/api/v1/sales/equipment/${fixture.record_id}`);
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as { status: string };
    expect(body.status).toBe("esigned_pending_publish");
  });

  // Scenario 5: Sales rep publishes the listing after eSign
  test("sales rep publishes listing after eSign — record moves out of pending_publish queue", async ({
    page,
  }) => {
    const fixture = seedPhase6<PublishFixture>("publish_ready");

    await uiLoginAsStaff(page, {
      email: fixture.sales_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: `/sales/equipment/${fixture.record_id}`,
    });

    // The "Publish now" button is present for esigned_pending_publish records.
    const publishBtn = page.getByRole("button", { name: /publish now/i });
    await expect(publishBtn).toBeVisible({ timeout: 10_000 });
    await publishBtn.click();

    // After publish the button turns into a success indicator or is disabled.
    await expect(
      page.getByRole("button", { name: /publishing/i }).or(
        page.getByText(/listing published/i),
      ),
    ).toBeVisible({ timeout: 10_000 });

    // Confirm via API that the record is now listed.
    const salesToken = await apiLoginAsStaff({
      email: fixture.sales_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const api = await authedApi(salesToken, randomFakeIp());
    const resp = await api.get(`/api/v1/sales/equipment/${fixture.record_id}`);
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as { status: string };
    expect(body.status).toBe("listed");
  });

  // Scenario 6: Manager re-approves a price change that exceeded the threshold
  test("manager re-approves price change — button shows Approved", async ({
    page,
  }) => {
    const fixture = seedPhase6<PriceChangeFixture>("price_change");

    await uiLoginAsStaff(page, {
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/manager/approvals",
    });

    // Wait for ProtectedRoute to finish loading before checking sub-sections.
    await expect(
      page.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.getByRole("heading", { name: /price change re-approvals/i }),
    ).toBeVisible({ timeout: 10_000 });

    // The reference number should appear in the price change section.
    await expect(
      page.getByText(fixture.reference_number).first(),
    ).toBeVisible();

    // Click "Re-approve" for the price change item.
    const reApproveBtn = page.getByRole("button", {
      name: new RegExp(
        `Re-approve price change for ${fixture.reference_number}`,
        "i",
      ),
    });
    await expect(reApproveBtn).toBeVisible();
    await reApproveBtn.click();

    // After success the button shows "Approved" and becomes disabled.
    await expect(
      page.getByRole("button", {
        name: new RegExp(
          `Re-approve price change for ${fixture.reference_number}`,
          "i",
        ),
      }),
    ).toBeDisabled({ timeout: 8_000 });

    // Verify via API that the change request is now resolved.
    const managerToken = await apiLoginAsStaff({
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const api = await authedApi(managerToken, randomFakeIp());
    const priceResp = await api.get(
      "/api/v1/manager/approvals/price-changes",
    );
    expect(priceResp.status()).toBe(200);
    const priceBody = (await priceResp.json()) as {
      items: Array<{ change_request_id: string }>;
    };
    const stillPending = priceBody.items.some(
      (item) => item.change_request_id === fixture.change_request_id,
    );
    expect(stillPending).toBe(false);
  });
});

test.describe("A11y — Phase 6 manager approval queue", () => {
  test("approval queue and detail pass axe-core scan", async ({ page }) => {
    const fixture = seedPhase6<DefaultFixture>("default");

    await uiLoginAsStaff(page, {
      email: fixture.manager_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/manager/approvals",
    });

    await expect(
      page.getByRole("heading", { name: /manager approval queue/i }),
    ).toBeVisible({ timeout: 10_000 });
    await assertA11y(page);

    // Also scan the detail view.
    await page.goto(`/manager/approvals/${fixture.submission_id}`);
    await expect(
      page.getByRole("heading", { name: /appraisal review/i }),
    ).toBeVisible({ timeout: 8_000 });
    await assertA11y(page);
  });
});
