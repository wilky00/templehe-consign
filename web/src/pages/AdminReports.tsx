// ABOUTME: Phase 4 admin reporting tab — scaffold with the four sub-tabs.
// ABOUTME: Real charts ship in Phase 8; the placeholder gates the `reporting` role today.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert } from "../components/ui/Alert";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { getAdminReportsIndex } from "../api/admin";

export function AdminReportsPage() {
  const query = useQuery({
    queryKey: ["admin-reports-index"],
    queryFn: getAdminReportsIndex,
  });
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  if (query.isLoading) return <Spinner />;
  if (query.isError) {
    return (
      <Alert tone="error" title="Could not load reports">
        {(query.error as Error).message}
      </Alert>
    );
  }
  const tabs = query.data?.tabs ?? [];
  const active = tabs.find((t) => t.slug === activeSlug) ?? tabs[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Admin reports</h1>
        <p className="mt-1 text-sm text-gray-600">
          Read-only views available to admins and the reporting role.
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Admin reports"
        className="flex flex-wrap gap-2 border-b border-gray-200"
      >
        {tabs.map((tab) => {
          const isActive = active?.slug === tab.slug;
          return (
            <button
              key={tab.slug}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveSlug(tab.slug)}
              className={
                isActive
                  ? "border-b-2 border-gray-900 px-3 py-2 text-sm font-medium text-gray-900"
                  : "border-b-2 border-transparent px-3 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
              }
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <Card>
        <h2 className="text-base font-semibold text-gray-900">
          {active?.label ?? "Reports"}
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          Phase 8 will populate this view with the underlying charts and
          export controls. The role gate is wired today so the reporting
          user can land on this page even before the data is ready.
        </p>
      </Card>
    </div>
  );
}
