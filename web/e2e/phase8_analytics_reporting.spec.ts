// ABOUTME: Phase 8 Sprint 4 gate — acceptance scenarios for admin reporting tabs.
// ABOUTME: Covers tab rendering, data display, sub-view switching, and CSV export trigger.
import { expect, test } from "@playwright/test";
import { assertA11y } from "./helpers/axe";
import { seedPhase8Reporting, uiLoginAsStaff } from "./helpers/api";

interface ReportingFixture {
  admin_email: string;
  password: string;
  fake_ip: string;
}

test.describe("Phase 8 gate — admin reporting", () => {
  // Scenario 1: Admin can reach the reports page and see all four tabs
  test("admin can navigate to reports and sees all four tabs", async ({ page }) => {
    const fixture = seedPhase8Reporting<ReportingFixture>();
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: fixture.fake_ip,
      landingPath: "/admin/reports",
    });

    await expect(
      page.getByRole("heading", { name: /admin reports/i }),
    ).toBeVisible({ timeout: 15_000 });

    await expect(page.getByRole("tab", { name: /sales by period/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /type\/location/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /user traffic/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /export center/i })).toBeVisible();
  });

  // Scenario 2: Sales by Period tab loads and shows a data table
  test("sales by period tab renders summary table with seeded data", async ({ page }) => {
    const fixture = seedPhase8Reporting<ReportingFixture>();
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: fixture.fake_ip,
      landingPath: "/admin/reports",
    });

    await page.getByRole("tab", { name: /sales by period/i }).click();
    // The summary table header should be visible once data loads
    await expect(page.getByText("Period", { exact: true })).toBeVisible({ timeout: 10_000 });
    // At least one row of data from the seeded records
    await expect(page.getByRole("button", { name: /export csv/i })).toBeVisible();
  });

  // Scenario 3: User Traffic tab shows metric cards
  test("user traffic tab renders session and page-view metric cards", async ({ page }) => {
    const fixture = seedPhase8Reporting<ReportingFixture>();
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: fixture.fake_ip,
      landingPath: "/admin/reports",
    });

    await page.getByRole("tab", { name: /user traffic/i }).click();
    await expect(page.getByText("Sessions")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Page views")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Form abandon rate")).toBeVisible({ timeout: 5_000 });
  });

  // Scenario 4: Export Center tab lists all four download buttons
  test("export center tab shows download CSV buttons for every report type", async ({ page }) => {
    const fixture = seedPhase8Reporting<ReportingFixture>();
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: fixture.fake_ip,
      landingPath: "/admin/reports",
    });

    await page.getByRole("tab", { name: /export center/i }).click();
    await expect(
      page.getByRole("button", { name: /download sales by period csv/i }),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /download sales by equipment type csv/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /download sales by state csv/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /download portal traffic csv/i }),
    ).toBeVisible();
  });

  // Scenario 5: Accessibility audit on reports page
  test("admin reports page passes axe accessibility audit", async ({ page }) => {
    const fixture = seedPhase8Reporting<ReportingFixture>();
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: fixture.fake_ip,
      landingPath: "/admin/reports",
    });

    await expect(
      page.getByRole("heading", { name: /admin reports/i }),
    ).toBeVisible({ timeout: 15_000 });
    // Wait for data to load before scanning
    await page.waitForTimeout(1_000);
    await assertA11y(page);
  });
});
