// ABOUTME: axe-core sweep across every public + authenticated Phase 2 route.
// ABOUTME: Fails the suite on any Critical/Serious violation; non-critical violations log but don't block.
import { expect, test } from "@playwright/test";
import { assertA11y } from "./helpers/axe";
import { createActiveUser, uiLogin } from "./helpers/api";

test.describe("A11y — public routes", () => {
  test("/login", async ({ page }) => {
    await page.goto("/login");
    await assertA11y(page);
  });

  test("/register", async ({ page }) => {
    await page.goto("/register");
    // The consent checkbox only appears after the legal docs load.
    await expect(page.getByLabel(/i agree to the terms of service/i)).toBeVisible();
    await assertA11y(page);
  });

  test("/auth/verify-email with no token", async ({ page }) => {
    await page.goto("/auth/verify-email");
    await assertA11y(page);
  });
});

test.describe("A11y — authenticated routes", () => {
  test("dashboard, submit, detail, account", async ({ page }) => {
    const user = await createActiveUser("a11y");
    await uiLogin(page, user);

    await page.goto("/portal");
    await expect(
      page.getByRole("heading", { name: /your submissions/i }),
    ).toBeVisible();
    await assertA11y(page);

    await page.goto("/portal/submit");
    await expect(page.getByRole("heading", { name: /submit equipment/i })).toBeVisible();
    // Give categories a beat to load so the dropdown isn't in a pending state
    // that axe might read as missing-label.
    await expect(page.getByLabel(/equipment category/i)).toBeEnabled();
    await assertA11y(page);

    // Seed one record to exercise the detail page.
    await page.getByLabel(/^make$/i).fill("Komatsu");
    await page.getByRole("button", { name: /submit for appraisal/i }).click();
    await expect(page).toHaveURL(/\/portal\/equipment\/[0-9a-f-]{36}$/);
    await assertA11y(page);

    await page.goto("/portal/account");
    await expect(page.getByRole("heading", { name: /^account$/i })).toBeVisible();
    await assertA11y(page);
  });
});
