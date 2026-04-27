// ABOUTME: Playwright test helpers that talk to the TempleHE API directly (no browser).
// ABOUTME: Per-test unique IPs sidestep the per-IP rate limiters; CF-Connecting-IP is trusted by the API.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { APIRequestContext, BrowserContext, Page, request } from "@playwright/test";
import { API_URL } from "../../playwright.config";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..");

/**
 * Run the Phase 3 seeder in one of its modes (default | publish | cascade |
 * locking | hide-roles) and return the JSON payload it prints to stdout.
 *
 * Each spec invokes the seeder for its own fixture instead of mutating
 * shared state, so re-runs against the same DB stay clean.
 */
export function seedPhase3<T>(
  mode: "default" | "publish" | "cascade" | "locking" | "hide-roles",
  opts: { roles?: string[]; records?: number } = {},
): T {
  const args = [
    "run",
    "python",
    path.join(REPO_ROOT, "scripts", "seed_e2e_phase3.py"),
    "--mode",
    mode,
  ];
  if (mode === "hide-roles") {
    args.push("--roles", (opts.roles ?? []).join(","));
  }
  if (mode === "default" && opts.records !== undefined) {
    args.push("--records", String(opts.records));
  }
  const out = execFileSync("uv", args, {
    cwd: path.join(REPO_ROOT, "api"),
    env: {
      ...process.env,
      DATABASE_URL:
        process.env.E2E_DATABASE_URL ??
        "postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe",
    },
    encoding: "utf8",
  });
  return JSON.parse(out.trim()) as T;
}

/**
 * Phase 4 fixture seeder — admin + reporting + sales + customer users.
 *
 * `default` resets rate limits + AppConfig overrides only. `routing`
 * additionally seeds two geographic rules at priorities 10/20 with a
 * `phase4_e2e_marker` JSONB key so re-runs purge cleanly.
 */
export function seedPhase4<T>(mode: "default" | "routing" = "default"): T {
  const args = [
    "run",
    "python",
    path.join(REPO_ROOT, "scripts", "seed_e2e_phase4.py"),
    "--mode",
    mode,
  ];
  const out = execFileSync("uv", args, {
    cwd: path.join(REPO_ROOT, "api"),
    env: {
      ...process.env,
      DATABASE_URL:
        process.env.E2E_DATABASE_URL ??
        "postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe",
    },
    encoding: "utf8",
  });
  return JSON.parse(out.trim()) as T;
}

const VALID_PASSWORD = "TestPassword1!";

export interface TestUser {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  /**
   * Per-user fake IP. Threaded into CF-Connecting-IP on every request this
   * user's tests make so the IP-based rate limiters see distinct counters.
   * Without this, 5 registrations per hour maxes out after the first spec.
   */
  fakeIp: string;
}

function randomFakeIp(): string {
  // TEST-NET-1 (RFC 5737) — safe to use as a reserved documentation range.
  const n = () => Math.floor(Math.random() * 254) + 1;
  return `192.0.2.${n()}`;
}

export function makeTestUser(prefix: string): TestUser {
  // Unique-per-run so repeat runs against the same DB don't collide.
  // example.com is the IANA-reserved example domain — pydantic-email's
  // deliverability check accepts it; the .test TLD is blocked.
  const slug = `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  return {
    email: `e2e+${slug}@example.com`.toLowerCase(),
    password: VALID_PASSWORD,
    firstName: "E2E",
    lastName: "Tester",
    fakeIp: randomFakeIp(),
  };
}

async function ctx(fakeIp?: string): Promise<APIRequestContext> {
  return await request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: fakeIp ? { "CF-Connecting-IP": fakeIp } : undefined,
  });
}

/**
 * Apply the user's fake IP header to every browser request. Call once per
 * test after login. Keeps the browser-originated calls in the same rate-
 * limit bucket as the direct-API setup calls, and keeps each test isolated
 * from the others' counters.
 */
export async function applyFakeIp(
  scope: BrowserContext | Page,
  user: TestUser,
): Promise<void> {
  await scope.setExtraHTTPHeaders({ "CF-Connecting-IP": user.fakeIp });
}

export async function apiRegister(user: TestUser): Promise<void> {
  const api = await ctx(user.fakeIp);
  const resp = await api.post("/api/v1/auth/register", {
    data: {
      email: user.email,
      password: user.password,
      first_name: user.firstName,
      last_name: user.lastName,
      tos_version: "1",
      privacy_version: "1",
    },
  });
  if (resp.status() !== 201) {
    throw new Error(`register failed (${resp.status()}): ${await resp.text()}`);
  }
}

export async function apiLogin(user: TestUser): Promise<string> {
  const api = await ctx(user.fakeIp);
  const resp = await api.post("/api/v1/auth/login", {
    data: { email: user.email, password: user.password },
  });
  if (resp.status() !== 200) {
    throw new Error(`login failed (${resp.status()}): ${await resp.text()}`);
  }
  const body = (await resp.json()) as { access_token: string };
  return body.access_token;
}

/**
 * Direct-API login for pre-seeded staff users (admin/reporting/sales/etc).
 * Returns the bearer token. Phase 4 specs use this to drive admin endpoints
 * outside the browser to verify server-side state (e.g. reorder
 * persistence, RBAC denial). Throws if TOTP is enabled — the caller would
 * need a different code path to handle the partial-token flow.
 */
export async function apiLoginAsStaff(args: {
  email: string;
  password: string;
  fakeIp: string;
}): Promise<string> {
  const api = await ctx(args.fakeIp);
  const resp = await api.post("/api/v1/auth/login", {
    data: { email: args.email, password: args.password },
  });
  if (resp.status() !== 200) {
    throw new Error(`login failed (${resp.status()}): ${await resp.text()}`);
  }
  const body = (await resp.json()) as { access_token?: string };
  if (!body.access_token) {
    throw new Error(
      `login did not return access_token (TOTP enabled?): ${JSON.stringify(body)}`,
    );
  }
  return body.access_token;
}

export async function apiVerifyEmail(user: TestUser, token: string): Promise<void> {
  const api = await ctx(user.fakeIp);
  const resp = await api.get(
    `/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`,
  );
  if (resp.status() !== 200) {
    throw new Error(
      `verify-email failed (${resp.status()}): ${await resp.text()}`,
    );
  }
}

/**
 * Set up an active user in one call. Used by tests that aren't testing the
 * registration flow itself. Registers, fetches the verify token from Mailpit,
 * hits the verify endpoint, then returns the user ready to log in via UI.
 */
export async function createActiveUser(prefix: string): Promise<TestUser> {
  const { fetchVerifyToken } = await import("./mailpit");
  const user = makeTestUser(prefix);
  await apiRegister(user);
  const token = await fetchVerifyToken(user.email);
  await apiVerifyEmail(user, token);
  return user;
}

/**
 * Log the browser in via the UI — used after createActiveUser in the
 * non-registration specs so the shared auth state flows through the SPA.
 * Applies the user's fake IP on the browser context first so the login
 * counter for this user stays isolated.
 */
export async function uiLogin(page: Page, user: TestUser): Promise<void> {
  await applyFakeIp(page.context(), user);
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForURL(/\/portal$/);
}

/**
 * Log the browser in as a pre-seeded staff user (sales/appraiser/etc).
 * The login page redirects every role to /portal; this helper waits for
 * that landing then jumps to the staff-side route the test wants. The
 * fakeIp is required so per-IP rate limiters don't leak between tests.
 */
export async function uiLoginAsStaff(
  page: Page,
  args: { email: string; password: string; fakeIp: string; landingPath: string },
): Promise<void> {
  await page.context().setExtraHTTPHeaders({ "CF-Connecting-IP": args.fakeIp });
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(args.email);
  await page.getByLabel(/password/i).fill(args.password);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForURL(/\/portal$/);
  await page.goto(args.landingPath);
}
