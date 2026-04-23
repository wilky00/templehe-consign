// ABOUTME: End-to-end intake flow — customer submits equipment, lands on detail with THE-XXXXXXXX.
// ABOUTME: Skips real photo upload; that path is covered in backend integration tests.
import { expect, test } from "@playwright/test";
import { createActiveUser, uiLogin } from "./helpers/api";

test("submit intake → see on dashboard → open detail", async ({ page }) => {
  const user = await createActiveUser("intake");
  await uiLogin(page, user);

  // Dashboard starts empty.
  await expect(page.getByRole("heading", { name: /your submissions/i })).toBeVisible();
  await expect(page.getByText(/haven't submitted/i)).toBeVisible();

  // Open the intake form.
  await page.getByRole("link", { name: /submit new equipment/i }).first().click();
  await expect(page).toHaveURL(/\/portal\/submit$/);

  // Fill in a minimal happy-path submission.
  await page.getByLabel(/equipment category/i).selectOption({ label: "Dozers" });
  await page.getByLabel(/^make$/i).fill("Caterpillar");
  await page.getByLabel(/^model$/i).fill("D6T");
  await page.getByLabel(/^year$/i).fill("2018");
  await page.getByLabel(/hour meter reading/i).fill("3450");
  await page.getByLabel(/running condition/i).selectOption("running");
  await page.getByLabel(/ownership/i).selectOption("owned");
  await page.getByLabel(/current location/i).fill("Yard 2, Houston TX");
  await page.getByLabel(/description/i).fill("Well-maintained; recent service.");

  await page.getByRole("button", { name: /submit for appraisal/i }).click();

  // Lands on the detail page — THE-XXXXXXXX reference shown, details card populated.
  await expect(page).toHaveURL(/\/portal\/equipment\/[0-9a-f-]{36}$/);
  await expect(page.getByText(/^THE-[0-9A-Z]{8}$/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /2018 caterpillar d6t/i })).toBeVisible();

  // Back to dashboard — the submission shows up with a status badge.
  await page.getByRole("link", { name: /back to dashboard/i }).click();
  await expect(page).toHaveURL(/\/portal$/);
  await expect(page.getByText(/2018 caterpillar d6t/i)).toBeVisible();
  await expect(page.getByText(/new request/i)).toBeVisible();
});
