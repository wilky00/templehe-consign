// ABOUTME: Phase 3 Sprint 6 — /account/notifications: sales upsert, customer read-only, hidden-role placeholder.
// ABOUTME: hidden-roles toggle is driven via the seeder so the test exercises the AppConfig branch end-to-end.
import { expect, test } from "@playwright/test";
import {
  createActiveUser,
  seedPhase3,
  uiLogin,
  uiLoginAsStaff,
} from "./helpers/api";

interface DefaultFixture {
  password: string;
  sales_email: string;
  customer_email: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

test.describe("notifications page", () => {
  // Always start each test with the role unhidden so prior runs don't leak.
  // The hidden-role test re-toggles inside its own body.
  test.beforeEach(async () => {
    seedPhase3<{ hidden_roles: string[] }>("hide-roles", { roles: [] });
  });

  test("sales: switch to SMS, save, reload reflects the choice", async ({ page }) => {
    const fixture = seedPhase3<DefaultFixture>("default");

    await uiLoginAsStaff(page, {
      email: fixture.sales_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/account/notifications",
    });

    await expect(
      page.getByRole("heading", { name: /preferred channel/i }),
    ).toBeVisible();
    // Radios target by id since the accessible name picks up both the label
    // text and its description blurb (e.g. "Email Workflow notifications go…").
    const emailRadio = page.locator("#channel-email");
    const smsRadio = page.locator("#channel-sms");
    await expect(emailRadio).toBeChecked();

    await smsRadio.check();
    // The "phone number" label substring also appears in the SMS radio's
    // description, so target the input by id to keep the locator unambiguous.
    const phoneInput = page.locator("#pref-phone");
    await phoneInput.fill("+15555550199");
    await page.getByRole("button", { name: /save preferences/i }).click();
    await expect(page.getByText(/preferences saved/i)).toBeVisible();

    // Reload — the choice survives.
    await page.reload();
    await expect(page.locator("#channel-sms")).toBeChecked();
    await expect(page.locator("#pref-phone")).toHaveValue("+15555550199");
  });

  test("customer: page renders read-only with contact-support copy", async ({
    page,
  }) => {
    const customer = await createActiveUser("notif-ro");
    await uiLogin(page, customer);
    await page.goto("/account/notifications");

    await expect(
      page.getByRole("heading", { name: /preferred channel/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/your account uses email for all notifications/i),
    ).toBeVisible();
    // No save button when read-only.
    await expect(
      page.getByRole("button", { name: /save preferences/i }),
    ).toBeHidden();
  });

  test("hidden role: page shows the unavailable placeholder", async ({ page }) => {
    // Hide the page from the customer role for this test only.
    seedPhase3<{ hidden_roles: string[] }>("hide-roles", { roles: ["customer"] });
    try {
      const customer = await createActiveUser("notif-hidden");
      await uiLogin(page, customer);
      await page.goto("/account/notifications");

      await expect(
        page.getByRole("heading", { name: /notifications unavailable/i }),
      ).toBeVisible();
      // The preferences card itself doesn't render.
      await expect(
        page.getByRole("heading", { name: /preferred channel/i }),
      ).toBeHidden();
    } finally {
      // Restore so later tests run against the default config.
      seedPhase3<{ hidden_roles: string[] }>("hide-roles", { roles: [] });
    }
  });
});
