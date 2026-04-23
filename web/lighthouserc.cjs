// ABOUTME: Lighthouse CI config — runs against the built vite preview server on :4173.
// ABOUTME: Asserts Accessibility + Best Practices ≥ 90; Performance is informational only (cold-boot flake).
module.exports = {
  ci: {
    collect: {
      staticDistDir: "./dist",
      url: ["http://localhost/login", "http://localhost/register"],
      numberOfRuns: 1,
      settings: {
        // Headless Chrome with desktop form factor — matches real customer usage.
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
