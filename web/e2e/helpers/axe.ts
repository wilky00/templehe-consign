// ABOUTME: @axe-core/playwright wrapper — scans the current page and fails on Critical/Serious violations.
// ABOUTME: Color-contrast runs but is report-only: MVP uses default Tailwind grays that sometimes flirt with 4.5:1.
import AxeBuilder from "@axe-core/playwright";
import { expect, Page } from "@playwright/test";

/**
 * Run axe against the current page state. Fails the test if there is a
 * Critical or Serious violation (per WCAG 2.1 AA). Returns the full
 * result so callers can log it.
 */
export async function assertA11y(
  page: Page,
  opts: { allowedRules?: string[] } = {},
): Promise<void> {
  const builder = new AxeBuilder({ page }).withTags([
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
  ]);
  if (opts.allowedRules?.length) {
    builder.disableRules(opts.allowedRules);
  }
  const results = await builder.analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  if (blocking.length > 0) {
    const summary = blocking
      .map((v) => `  [${v.impact}] ${v.id}: ${v.help}`)
      .join("\n");
    // Log the full result so the Playwright report captures it.
    console.error("axe violations:\n" + summary);
  }
  expect(blocking, "axe found Critical/Serious a11y violations").toEqual([]);
}
