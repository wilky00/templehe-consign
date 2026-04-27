// ABOUTME: axe-core sweep across every Phase 4 admin route + the reporting-side report stub.
// ABOUTME: Same WCAG 2.1 AA bar as Phase 2/3; admin grids inherit the dnd-kit caveat from routing.
import { expect, test } from "@playwright/test";
import { assertA11y } from "./helpers/axe";
import { seedPhase4, uiLoginAsStaff } from "./helpers/api";

interface DefaultFixture {
  password: string;
  admin_email: string;
  reporting_email: string;
}

function randomFakeIp(): string {
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

test.describe("A11y — Phase 4 admin shell", () => {
  test("operations, customers, config, routing, templates, categories, integrations, health, reports", async ({
    page,
  }) => {
    const fixture = seedPhase4<DefaultFixture>("default");
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/operations",
    });

    await expect(page.getByRole("heading", { name: /^operations$/i })).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/customers");
    await expect(page.getByRole("heading", { name: /^customers$/i })).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/config");
    await expect(page.getByRole("heading", { name: /^configuration$/i })).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/routing");
    await expect(page.getByRole("heading", { name: /^lead routing$/i })).toBeVisible();
    // SortableContext from @dnd-kit emits draggable list rows with a
    // grab-cursor button whose role is "button" not the surrounding
    // listitem. Stock axe rules still pass on AA — keep the default
    // allow-list, but drop scrollable-region-focusable since the
    // dnd grid renders as a non-scrollable list.
    await assertA11y(page);

    await page.goto("/admin/notification-templates");
    await expect(
      page.getByRole("heading", { name: /^notification templates$/i }),
    ).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/categories");
    await expect(
      page.getByRole("heading", { name: /^equipment categories$/i }),
    ).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/integrations");
    await expect(
      page.getByRole("heading", { name: /^integrations$/i }),
    ).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/health");
    await expect(page.getByRole("heading", { name: /^health$/i })).toBeVisible();
    await assertA11y(page);

    await page.goto("/admin/reports");
    await expect(page.getByRole("heading", { name: /^admin reports$/i })).toBeVisible();
    await assertA11y(page);
  });
});

test.describe("A11y — Phase 4 reporting role surface", () => {
  test("/admin/reports renders with reporting-only nav", async ({ page }) => {
    const fixture = seedPhase4<DefaultFixture>("default");
    await uiLoginAsStaff(page, {
      email: fixture.reporting_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/reports",
    });
    await expect(
      page.getByRole("heading", { name: /^admin reports$/i }),
    ).toBeVisible();
    await assertA11y(page);
  });
});
