// ABOUTME: End-to-end registration flow — form submit → email → verify → login → dashboard.
// ABOUTME: Exercises real Mailpit + real API, clicking every button a human would click.
import { expect, test } from "@playwright/test";
import { applyFakeIp, makeTestUser } from "./helpers/api";
import { fetchVerifyToken } from "./helpers/mailpit";

test("register → verify email → login → dashboard", async ({ page }) => {
  const user = makeTestUser("register");
  await applyFakeIp(page.context(), user);

  // Step 1 — register via the form.
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: /create your account/i })).toBeVisible();
  await page.getByLabel(/first name/i).fill(user.firstName);
  await page.getByLabel(/last name/i).fill(user.lastName);
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  // The consent checkbox label includes "I agree to the Terms of Service…"
  await page.getByLabel(/i agree to the terms of service/i).check();
  await page.getByRole("button", { name: /create account/i }).click();

  await expect(page.getByText(/check your email/i)).toBeVisible();

  // Step 2 — fetch the verification token from Mailpit and hit the URL.
  const token = await fetchVerifyToken(user.email);
  await page.goto(`/auth/verify-email?token=${encodeURIComponent(token)}`);
  await expect(page.getByText(/email verified/i)).toBeVisible();

  // Step 3 — log in.
  await page.getByRole("link", { name: /go to login/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /log in/i }).click();

  // Step 4 — landed on the dashboard; email visible in the header.
  await expect(page).toHaveURL(/\/portal$/);
  await expect(page.getByRole("heading", { name: /your submissions/i })).toBeVisible();
  await expect(page.getByText(user.email)).toBeVisible();
});

test("login with wrong password surfaces an error", async ({ page }) => {
  // Use a random fake IP so failed-login counters from this spec don't
  // cross-contaminate the other auth tests.
  const user = makeTestUser("wrongpw");
  await applyFakeIp(page.context(), user);

  await page.goto("/login");
  await page.getByLabel(/email/i).fill("nobody@example.com");
  await page.getByLabel(/password/i).fill("TotallyWrong1!");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page.getByRole("alert").filter({ hasText: /login failed/i })).toBeVisible();
});
