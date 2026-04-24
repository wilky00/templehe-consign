// ABOUTME: End-to-end change-request flow — customer submits a change request from the detail page.
// ABOUTME: Confirms success banner + the new row in the prior-requests list.
import { expect, test } from "@playwright/test";
import { createActiveUser, uiLogin } from "./helpers/api";

test("submit change request from equipment detail", async ({ page }) => {
  const user = await createActiveUser("changereq");
  await uiLogin(page, user);

  // Seed an equipment record via the UI so we have somewhere to file the change.
  await page.goto("/portal/submit");
  await page.getByLabel(/^make$/i).fill("JCB");
  await page.getByRole("button", { name: /submit for appraisal/i }).click();
  await expect(page).toHaveURL(/\/portal\/equipment\/[0-9a-f-]{36}$/);

  // Fill out the change request form.
  await page.getByLabel(/type/i).selectOption("update_location");
  await page
    .getByLabel(/^notes$/i)
    .fill("Relocated to the back lot at the north yard.");
  await page.getByRole("button", { name: /submit change request/i }).click();

  // Success banner + the new row appears in the prior-requests list.
  await expect(page.getByRole("status").filter({ hasText: /change request submitted/i })).toBeVisible();
  await expect(page.getByText(/update_location/i).first()).toBeVisible();
});
