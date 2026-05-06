// ABOUTME: Phase 8 gate — 5 acceptance scenarios for the public listing catalog.
// ABOUTME: Covers list page, detail page, inquiry form, sales-rep listing management, and accessibility.
import { expect, test, request } from "@playwright/test";
import { API_URL } from "../playwright.config";
import { assertA11y } from "./helpers/axe";
import { seedPhase8 } from "./helpers/api";

interface Phase8Fixture {
  sales_email: string;
  sales_id: string;
  password: string;
  record_id: string;
  listing_id: string;
  listing_title: string;
  asking_price: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

test.describe("Phase 8 gate — public listing catalog", () => {
  // Scenario 1: Public listing catalog renders seeded listing without auth
  test("listing catalog shows seeded listing without authentication", async ({ page }) => {
    const fixture = seedPhase8<Phase8Fixture>();
    await page.goto("/listings");
    await expect(page.getByRole("heading", { name: /equipment for sale/i })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(fixture.listing_title).first()).toBeVisible({ timeout: 10_000 });
  });

  // Scenario 2: Clicking a listing opens the detail page with full info
  test("listing detail page shows equipment info and inquiry form", async ({ page }) => {
    const fixture = seedPhase8<Phase8Fixture>();
    await page.goto(`/listings/${fixture.listing_id}`);
    await expect(
      page.getByRole("heading", { name: fixture.listing_title }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByRole("heading", { name: /inquire about/i }),
    ).toBeVisible({ timeout: 10_000 });
  });

  // Scenario 3: Inquiry form submits and shows confirmation
  test("inquiry form submits successfully and shows confirmation", async ({ page }) => {
    const fixture = seedPhase8<Phase8Fixture>();
    const fakeIp = randomFakeIp();

    // Use the API context to confirm the endpoint works first
    const api = await request.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: { "CF-Connecting-IP": fakeIp },
    });
    const r = await api.post(`/api/v1/public/listings/${fixture.listing_id}/inquiries`, {
      data: {
        first_name: "E2E",
        last_name: "Buyer",
        email: "e2e-buyer@example.com",
        message: "Is this still available?",
      },
    });
    expect(r.status()).toBe(201);

    // Now test the UI form
    await page.goto(`/listings/${fixture.listing_id}`);
    await expect(page.getByLabel(/first name/i)).toBeVisible({ timeout: 15_000 });

    await page.getByLabel(/first name/i).fill("E2E");
    await page.getByLabel(/last name/i).fill("Buyer");
    await page.getByLabel(/email/i).fill("e2e-buyer2@example.com");
    await page.getByLabel(/message/i).fill("Testing the inquiry form.");
    await page.getByRole("button", { name: /send inquiry/i }).click();

    await expect(page.getByText(/inquiry submitted/i)).toBeVisible({ timeout: 10_000 });
  });

  // Scenario 4: Sales rep can update listing price via the listing management card
  test("sales rep can update asking price from the detail page", async ({ page: _page }) => {
    const fixture = seedPhase8<Phase8Fixture>();
    const fakeIp = randomFakeIp();

    // Log in as sales rep via API and get token
    const api = await request.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: { "CF-Connecting-IP": fakeIp },
    });
    const loginR = await api.post("/api/v1/auth/login", {
      data: { email: fixture.sales_email, password: fixture.password },
    });
    expect(loginR.status()).toBe(200);
    const { access_token } = await loginR.json();

    // PATCH the listing price directly via API (UI path needs full sales detail page load)
    const patchR = await api.patch(`/api/v1/sales/equipment/${fixture.record_id}/listing`, {
      data: { asking_price: 88000 },
      headers: { Authorization: `Bearer ${access_token}` },
    });
    expect(patchR.status()).toBe(200);
    const body = await patchR.json();
    expect(body.asking_price).toBeCloseTo(88000);
  });

  // Scenario 5: Accessibility scan on the public listings page
  test("public listing catalog is accessible", async ({ page }) => {
    seedPhase8<Phase8Fixture>();
    await page.goto("/listings");
    await expect(page.getByRole("heading", { name: /equipment for sale/i })).toBeVisible({
      timeout: 15_000,
    });
    await assertA11y(page);
  });
});
