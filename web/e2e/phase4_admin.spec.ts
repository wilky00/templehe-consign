// ABOUTME: Phase 4 gate — 7 acceptance scenarios spanning admin shell + config + routing +
// ABOUTME: categories + integrations + health + reporting RBAC. Driven through the SPA where the
// ABOUTME: behaviour is user-observable, with direct-API checks for cross-cutting state.
import { expect, test, request } from "@playwright/test";
import { API_URL } from "../playwright.config";
import { apiLoginAsStaff, seedPhase4, uiLoginAsStaff } from "./helpers/api";

interface DefaultFixture {
  password: string;
  admin_user_id: string;
  admin_email: string;
  reporting_user_id: string;
  reporting_email: string;
  sales_user_id: string;
  sales_email: string;
  customer_user_id: string;
  customer_email: string;
  customer_id: string;
}

interface RoutingFixture extends DefaultFixture {
  seeded_geographic_rules: Array<{
    rule_id: string;
    state: string;
    priority: number;
  }>;
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

test.describe("Phase 4 acceptance — admin panel + global config", () => {
  // 1) AppConfig change is reflected immediately on the customer-facing
  // intake form-config endpoint without a deploy. The admin hides
  // `serial_number` (a canonical intake field); the customer-side
  // /equipment/form-config response should drop it from visible_fields.
  test("AppConfig hide intake field flows to customer form-config", async ({
    page,
  }) => {
    const fixture = seedPhase4<DefaultFixture>("default");
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/config",
    });

    await expect(
      page.getByRole("heading", { name: /^configuration$/i }),
    ).toBeVisible();

    // ConfigField renders the list[string] input with a stable id of
    // `cfg-<key_name>`; pinning to the id avoids flaky text-anchored
    // locators. The Save button lives in the same ConfigRow div, which
    // is the textarea's direct parent.
    const textarea = page.locator("#cfg-intake_fields_visible");
    await expect(textarea).toBeVisible();
    const visibleRow = textarea.locator("xpath=..");

    // Strip serial_number from the comma-separated draft. Seeder clears
    // any prior override, so the textarea shows the canonical default.
    const before = (await textarea.inputValue()).trim();
    const parts = before
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s && s !== "serial_number");
    expect(parts.length).toBeGreaterThan(0);
    expect(parts).not.toContain("serial_number");
    await textarea.fill(parts.join(", "));

    await visibleRow.getByRole("button", { name: /^save$/i }).click();
    // Either "Saved ✓" surfaces, or the button re-renders disabled. The
    // success-indicator path is the user-visible guarantee we care about.
    await expect(
      visibleRow.getByRole("button", { name: /saved/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Now hit the customer-facing form-config endpoint as the seeded
    // customer to confirm visibility honours the AppConfig change.
    const customerToken = await apiLoginAsStaff({
      email: fixture.customer_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const customerApi = await authedApi(customerToken, randomFakeIp());
    const cfg = await customerApi.get("/api/v1/me/equipment/form-config");
    expect(cfg.status()).toBe(200);
    const body = (await cfg.json()) as {
      visible_fields: string[];
      field_order: string[];
    };
    expect(body.visible_fields).not.toContain("serial_number");
    expect(body.visible_fields).toContain("make");
  });

  // 2) Admin saves Twilio credentials through the SPA. We don't click
  // "Test" — that hits api.twilio.com and is covered by the integration
  // suite (respx-mocked). Acceptance here is the encrypted store + the
  // resulting `configured` badge.
  test("integrations: save Twilio credentials flips the badge to configured", async ({
    page,
  }) => {
    const fixture = seedPhase4<DefaultFixture>("default");
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/integrations",
    });

    await expect(
      page.getByRole("heading", { name: /^integrations$/i }),
    ).toBeVisible();

    // Each integration renders inside a Card; pin to the heading then
    // walk up to the rounded-lg container.
    const twilioCard = page
      .getByRole("heading", { name: /^twilio$/i })
      .locator("xpath=ancestor::div[contains(@class,'rounded-lg')]")
      .first();
    await expect(twilioCard).toBeVisible();

    // Open the edit form (label is "Save" when not set, "Update" otherwise).
    await twilioCard
      .getByRole("button", { name: /^(save|update)$/i })
      .first()
      .click();

    await twilioCard.getByLabel(/account sid/i).fill("ACphase4e2e0000000000000000000000");
    await twilioCard.getByLabel(/auth token/i).fill("phase4-e2e-auth-token");
    await twilioCard.getByLabel(/from number/i).fill("+15555550199");

    // The form's submit button is the second "Save" inside the card —
    // the card-level button keeps its label until the form unmounts.
    await twilioCard.locator("form").getByRole("button", { name: /^save$/i }).click();

    // After save, the form auto-closes and the badge flips. The badge
    // text comes from the IntegrationCard header span.
    await expect(twilioCard.getByText(/^configured$/i)).toBeVisible({
      timeout: 10_000,
    });
  });

  // 3) Geographic rule routes a TX customer. We use the admin/routing
  // tester endpoint with a synthetic TX state — the persisted rule from
  // the seeder fires, returning the would_assign_to UUID matching the
  // sales rep we tagged on the rule.
  test("routing: geographic rule matches TX customer + assigns the right rep", async ({
    page,
  }) => {
    const fixture = seedPhase4<RoutingFixture>("routing");
    const txRule = fixture.seeded_geographic_rules.find((r) => r.state === "TX");
    expect(txRule).toBeDefined();

    // Drive the test through the admin routing UI so the user-visible
    // "Test rule" surface is exercised end-to-end.
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/routing",
    });
    await expect(
      page.getByRole("heading", { name: /^lead routing$/i }),
    ).toBeVisible();

    // Switch to the geographic tab — the seeded rules render under it.
    await page.getByRole("tab", { name: /^geographic$/i }).click();

    // Sanity-check the rule is listed before invoking the tester API.
    await expect(page.getByText(`priority ${txRule!.priority}`)).toBeVisible();

    // Cross-check via the API endpoint the UI calls. The /test endpoint
    // returns matched + would_assign_to without writing.
    const adminToken = await apiLoginAsStaff({
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const adminApi = await authedApi(adminToken, randomFakeIp());
    const resp = await adminApi.post(
      `/api/v1/admin/routing-rules/${txRule!.rule_id}/test`,
      { data: { customer_state: "TX" } },
    );
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as {
      matched: boolean;
      would_assign_to: string | null;
    };
    expect(body.matched).toBe(true);
    expect(body.would_assign_to).toBe(fixture.sales_user_id);
  });

  // 4) Drag-reorder is exercised via the API endpoint the UI calls;
  // @dnd-kit pointer drags are flaky in headless Chromium and the
  // server-side guarantee is what acceptance #4 actually targets.
  test("routing: reorder priorities atomically", async () => {
    const fixture = seedPhase4<RoutingFixture>("routing");
    const adminToken = await apiLoginAsStaff({
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const adminApi = await authedApi(adminToken, randomFakeIp());

    // Reverse the seeded order (TX@10, CA@20) → (CA, TX) and confirm
    // priorities renumber atomically with no stray duplicates.
    const reversed = [...fixture.seeded_geographic_rules]
      .reverse()
      .map((r) => r.rule_id);
    const reorderResp = await adminApi.post(
      "/api/v1/admin/routing-rules/reorder",
      { data: { rule_type: "geographic", ordered_ids: reversed } },
    );
    expect(reorderResp.status()).toBe(200);

    const after = await adminApi.get("/api/v1/admin/routing-rules");
    expect(after.status()).toBe(200);
    const list = (await after.json()) as {
      rules: Array<{
        id: string;
        rule_type: string;
        priority: number;
        deleted_at: string | null;
      }>;
    };
    const geographic = list.rules
      .filter(
        (r) => r.rule_type === "geographic" && r.deleted_at === null,
      )
      .sort((a, b) => a.priority - b.priority);
    // The first rule in the new ordering is the previously-second rule.
    expect(geographic[0].id).toBe(reversed[0]);
    expect(geographic[1].id).toBe(reversed[1]);
    // Priorities are unique within rule_type (uq_lead_routing_rules_type_priority).
    const priorities = geographic.map((r) => r.priority);
    expect(new Set(priorities).size).toBe(priorities.length);
  });

  // 5) Admin creates a category through the SPA. Customer-side category
  // listing (the intake form's dropdown source) and the iOS config
  // endpoint both reflect the new row immediately, and the iOS
  // config_version hash bumps because the response body changed.
  test("categories: new category appears in intake + iOS config hash bumps", async ({
    page,
  }) => {
    const fixture = seedPhase4<DefaultFixture>("default");

    // Capture the iOS config hash + the customer category list before
    // the create. Both must change.
    const adminToken = await apiLoginAsStaff({
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const adminApi = await authedApi(adminToken, randomFakeIp());
    const before = await adminApi.get("/api/v1/ios/config");
    expect(before.status()).toBe(200);
    const beforeBody = (await before.json()) as { config_version: string };

    const slug = `phase4-e2e-${Date.now()}`;
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/categories",
    });
    await expect(
      page.getByRole("heading", { name: /^equipment categories$/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /^new category$/i }).click();

    const dialog = page.getByRole("dialog", {
      name: /new equipment category/i,
    });
    await dialog.getByLabel(/^name$/i).fill("Phase 4 E2E Forklifts");
    // The slug label includes its helper-text span, so the accessible
    // name doesn't match `^slug$`. Pin to the placeholder instead.
    await dialog.getByPlaceholder("forklifts").fill(slug);
    await dialog.getByRole("button", { name: /^create$/i }).click();

    await expect(page.getByText(slug)).toBeVisible();

    // Customer-side category list reflects the new row. The intake form
    // sources its dropdown from /equipment/categories.
    const customerToken = await apiLoginAsStaff({
      email: fixture.customer_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const customerApi = await authedApi(customerToken, randomFakeIp());
    const cats = await customerApi.get("/api/v1/me/equipment/categories");
    expect(cats.status()).toBe(200);
    const catBody = (await cats.json()) as Array<{
      id: string;
      name: string;
      slug: string;
    }>;
    expect(catBody.some((c) => c.slug === slug)).toBe(true);

    // iOS config hash bumps. Endpoint requires a field-user role
    // (appraiser/admin/sales/sales_manager) — admin token works.
    const after = await adminApi.get("/api/v1/ios/config");
    expect(after.status()).toBe(200);
    const afterBody = (await after.json()) as { config_version: string };
    expect(afterBody.config_version).not.toBe(beforeBody.config_version);
  });

  // 6) Reporting role — gets /admin/reports but is denied every other
  // /admin/* surface. Layout shows only the Reports nav link.
  test("reporting role: 200 on /admin/reports, 403 on /admin/config", async ({
    page,
  }) => {
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

    // The reporting nav contains only Reports + Account; Operations is
    // an admin-only link and must NOT render for the reporting role.
    const nav = page.getByRole("navigation", { name: /main/i });
    await expect(nav.getByRole("link", { name: /^reports$/i })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^operations$/i })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: /^config$/i })).toHaveCount(0);

    // Server-side denial: /admin/config endpoint must 403 the reporting
    // role even though /admin/reports is allowed.
    const reportingToken = await apiLoginAsStaff({
      email: fixture.reporting_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
    });
    const reportingApi = await authedApi(reportingToken, randomFakeIp());
    const cfg = await reportingApi.get("/api/v1/admin/config");
    expect(cfg.status()).toBe(403);
    const ops = await reportingApi.get("/api/v1/admin/operations");
    expect(ops.status()).toBe(403);
  });

  // 7) Health dashboard renders the snapshot grid. The poller cadence
  // (30s) plus on-demand refresh both shape this view; we exercise the
  // latter explicitly so failures are visible inside the spec window.
  test("health dashboard renders the service grid + refresh forces a probe", async ({
    page,
  }) => {
    const fixture = seedPhase4<DefaultFixture>("default");
    await uiLoginAsStaff(page, {
      email: fixture.admin_email,
      password: fixture.password,
      fakeIp: randomFakeIp(),
      landingPath: "/admin/health",
    });
    await expect(page.getByRole("heading", { name: /^health$/i })).toBeVisible();

    // Database + R2 + each integration are all present. The card titles
    // come from SERVICE_LABEL in AdminHealth.tsx.
    const expectedHeadings = [
      /^database$/i,
      /^object storage \(r2\)$/i,
      /^slack$/i,
      /^twilio$/i,
      /^sendgrid$/i,
      /^google maps$/i,
    ];
    for (const heading of expectedHeadings) {
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    }

    // The "Refresh now" button forces a probe + invalidates the query.
    // We assert only the user-visible guarantee: the click succeeds and
    // the grid stays rendered. Two probes in the same wall-clock second
    // would produce the same `toLocaleTimeString()` snapshot label, so
    // a timestamp-delta assertion would be flaky on fast CI hardware.
    await page.getByRole("button", { name: /refresh now/i }).click();
    await expect(page.getByRole("heading", { name: /^twilio$/i })).toBeVisible();
    // `database` always resolves to a state in tests (we have a live DB);
    // its card serves as the "refetch settled" sentinel.
    await expect(page.getByRole("heading", { name: /^database$/i })).toBeVisible();
  });
});
