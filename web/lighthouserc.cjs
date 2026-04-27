// ABOUTME: Lighthouse CI config — Phase 4 covers admin routes via auth-injection (lighthouse-auth.cjs).
// ABOUTME: Asserts Accessibility + Best Practices ≥ 90 on unauth + admin routes; Performance is informational.
module.exports = {
  ci: {
    collect: {
      // CI starts vite preview on :5173 + the API on :8000 before lhci runs.
      // We use the running preview server (not staticDistDir) so the SPA
      // can fetch from /api/v1/* during the audit; admin routes need the
      // backend present to render anything beyond a loading spinner.
      url: [
        "http://localhost:5173/login",
        "http://localhost:5173/register",
        "http://localhost:5173/admin/operations",
        "http://localhost:5173/admin/customers",
        "http://localhost:5173/admin/config",
        "http://localhost:5173/admin/categories",
      ],
      numberOfRuns: 1,
      // The puppeteer hook does a direct-API login as the seeded admin
      // user and pre-injects the access token into sessionStorage on
      // every subsequent page lhci opens. Login/register pages ignore
      // the token; admin pages skip the ProtectedRoute redirect.
      puppeteerScript: "./lighthouse-auth.cjs",
      settings: {
        // Headless Chrome with desktop form factor — matches real staff usage.
        preset: "desktop",
        onlyCategories: [
          "accessibility",
          "best-practices",
          "performance",
          "seo",
        ],
      },
    },
    assert: {
      // Gate assertions — CI fails if any of these trip.
      assertions: {
        "categories:accessibility": ["error", { minScore: 0.9 }],
        "categories:best-practices": ["error", { minScore: 0.9 }],
        "categories:seo": ["warn", { minScore: 0.85 }],
        // Performance is noisy on CI cold starts — keep it as a warning.
        "categories:performance": ["warn", { minScore: 0.7 }],
      },
    },
    upload: {
      // Default public storage; the report URL is printed in the CI log.
      target: "temporary-public-storage",
    },
  },
};
