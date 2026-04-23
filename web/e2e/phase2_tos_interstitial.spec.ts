// ABOUTME: ToS version bump → /auth/me flips requires_terms_reaccept → interstitial blocks every route.
// ABOUTME: Uses Playwright's route interceptor to fake the /me response instead of reaching into Postgres.
import { expect, test } from "@playwright/test";
import { createActiveUser, uiLogin } from "./helpers/api";

test("interstitial appears when requires_terms_reaccept flips true", async ({
  page,
}) => {
  const user = await createActiveUser("tos");
  await uiLogin(page, user);

  // Intercept /auth/me responses and patch in requires_terms_reaccept = true.
  // Emulates what happens right after an admin bumps the current ToS version.
  await page.route("**/api/v1/auth/me", async (route) => {
    const resp = await route.fetch();
    const body = await resp.json();
    body.requires_terms_reaccept = true;
    await route.fulfill({
      response: resp,
      json: body,
    });
  });

  // Reload any authenticated page — the modal should take over.
  await page.goto("/portal");
  const dialog = page.getByRole("dialog", { name: /updated terms/i });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: /i accept/i })).toBeVisible();
});
