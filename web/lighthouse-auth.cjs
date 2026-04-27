// ABOUTME: Lighthouse CI puppeteer hook — direct-API login + sessionStorage injection so admin
// ABOUTME: routes audit as authenticated. Phase 4 closes the Phase-3 carry-forward gap.
//
// Lighthouse CI calls this once per URL with `(browser, context)`. We hook
// `targetcreated` so any page lhci subsequently opens has the access_token
// pre-seeded before the SPA's bootstrap script runs. The unauth pages
// (/login, /register) ignore the token; the admin pages (/admin/*) skip
// the redirect-to-login on ProtectedRoute and render the real surface.

const DEFAULT_API_URL = "http://localhost:8000";
const DEFAULT_EMAIL = "e2e-phase4-admin@example.com";
const DEFAULT_PASSWORD = "TestPassword1!";

async function loginAndGetToken() {
  const apiUrl = process.env.LH_API_URL || DEFAULT_API_URL;
  const email = process.env.LH_ADMIN_EMAIL || DEFAULT_EMAIL;
  const password = process.env.LH_ADMIN_PASSWORD || DEFAULT_PASSWORD;

  const resp = await fetch(`${apiUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(
      `lighthouse auth login failed (${resp.status}): ${body}`,
    );
  }
  const data = await resp.json();
  if (!data.access_token) {
    throw new Error(
      "lighthouse auth login did not return access_token (TOTP enabled on admin user?)",
    );
  }
  return data.access_token;
}

module.exports = async (browser /*, context */) => {
  const token = await loginAndGetToken();
  const injection = `sessionStorage.setItem('templehe.access_token', ${JSON.stringify(token)});`;

  // Inject on every page lhci opens after this hook returns.
  browser.on("targetcreated", async (target) => {
    if (target.type() !== "page") return;
    const page = await target.page();
    if (!page) return;
    try {
      await page.evaluateOnNewDocument(injection);
    } catch {
      // Page may already be closed mid-handshake; the per-existing-page
      // pass below covers the lhci default tab.
    }
  });

  // Cover the default about:blank tab lhci starts with.
  for (const page of await browser.pages()) {
    try {
      await page.evaluateOnNewDocument(injection);
    } catch {
      // Same race as above; safe to ignore.
    }
  }
};
