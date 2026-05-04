// ABOUTME: Public consignment listing catalog — /listings with filter sidebar, sort, pagination.
// ABOUTME: No auth required. URL search params carry filter state for shareable links.
import { useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Helmet } from "react-helmet-async";
import { getListings } from "../api/listings";
import type { ListingFilters } from "../api/listings";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Spinner } from "../components/ui/Spinner";
import { usePageView } from "../services/analytics";

const PAGE_SIZE = 24;

const CONDITION_OPTIONS = ["Excellent", "Good", "Fair", "Poor"];

function formatPrice(price: number | null): string {
  if (price == null) return "Price on request";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(price);
}

function ListingCardItem({ item }: { item: import("../api/listings").ListingCard }) {
  const subtitle = [item.year, item.make, item.model].filter(Boolean).join(" ");
  return (
    <Link to={`/listings/${item.id}`} className="group block rounded-lg border border-gray-200 bg-white shadow-sm transition hover:shadow-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-2">
      <div className="aspect-[4/3] w-full overflow-hidden rounded-t-lg bg-gray-100">
        {item.primary_photo_url ? (
          <img
            src={item.primary_photo_url}
            alt={item.listing_title}
            className="h-full w-full object-cover transition group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-gray-400" aria-hidden="true">
            <svg className="h-12 w-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
        )}
      </div>
      <div className="p-4">
        <h2 className="truncate text-sm font-semibold text-gray-900 group-hover:underline">
          {item.listing_title}
        </h2>
        {subtitle && (
          <p className="mt-0.5 truncate text-xs text-gray-500">{subtitle}</p>
        )}
        <div className="mt-2 flex items-center justify-between">
          <span className="text-base font-bold text-gray-900">{formatPrice(item.asking_price)}</span>
          {item.hours_condition && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
              {item.hours_condition}
            </span>
          )}
        </div>
        {item.state && (
          <p className="mt-1 text-xs text-gray-500">{item.state}</p>
        )}
      </div>
    </Link>
  );
}

function FilterSidebar({
  filters,
  onChange,
}: {
  filters: ListingFilters;
  onChange: (patch: Partial<ListingFilters>) => void;
}) {
  return (
    <aside aria-label="Filter listings" className="w-full md:w-56 flex-none">
      <Card>
        <h2 className="text-sm font-semibold text-gray-900">Filters</h2>

        <div className="mt-4 space-y-4">
          <div>
            <label htmlFor="min-price" className="block text-xs font-medium text-gray-700">
              Min price
            </label>
            <input
              id="min-price"
              type="number"
              min={0}
              className="mt-1 block w-full rounded-md border-gray-300 text-sm shadow-sm focus:border-gray-900 focus:ring-gray-900"
              value={filters.min_price ?? ""}
              onChange={(e) =>
                onChange({ min_price: e.target.value ? Number(e.target.value) : null, page: 1 })
              }
              placeholder="Any"
            />
          </div>

          <div>
            <label htmlFor="max-price" className="block text-xs font-medium text-gray-700">
              Max price
            </label>
            <input
              id="max-price"
              type="number"
              min={0}
              className="mt-1 block w-full rounded-md border-gray-300 text-sm shadow-sm focus:border-gray-900 focus:ring-gray-900"
              value={filters.max_price ?? ""}
              onChange={(e) =>
                onChange({ max_price: e.target.value ? Number(e.target.value) : null, page: 1 })
              }
              placeholder="Any"
            />
          </div>

          <div>
            <fieldset>
              <legend className="text-xs font-medium text-gray-700">Condition</legend>
              <div className="mt-1 space-y-1">
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="radio"
                    name="condition"
                    value=""
                    checked={!filters.condition}
                    onChange={() => onChange({ condition: null, page: 1 })}
                    className="text-gray-900 focus:ring-gray-900"
                  />
                  Any
                </label>
                {CONDITION_OPTIONS.map((c) => (
                  <label key={c} className="flex items-center gap-2 text-sm text-gray-700">
                    <input
                      type="radio"
                      name="condition"
                      value={c}
                      checked={filters.condition === c}
                      onChange={() => onChange({ condition: c, page: 1 })}
                      className="text-gray-900 focus:ring-gray-900"
                    />
                    {c}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => onChange({ min_price: null, max_price: null, condition: null, page: 1 })}
          >
            Clear filters
          </Button>
        </div>
      </Card>
    </aside>
  );
}

function Pagination({
  page,
  total_pages,
  onPage,
}: {
  page: number;
  total_pages: number;
  onPage: (p: number) => void;
}) {
  if (total_pages <= 1) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        aria-label="Previous page"
      >
        &larr; Prev
      </Button>
      <span className="text-sm text-gray-600">
        Page {page} of {total_pages}
      </span>
      <Button
        variant="secondary"
        size="sm"
        disabled={page >= total_pages}
        onClick={() => onPage(page + 1)}
        aria-label="Next page"
      >
        Next &rarr;
      </Button>
    </nav>
  );
}

export function PublicListingsPage() {
  usePageView();

  const [searchParams, setSearchParams] = useSearchParams();

  const filters: ListingFilters = {
    page: Number(searchParams.get("page") ?? "1"),
    page_size: PAGE_SIZE,
    sort: (searchParams.get("sort") as ListingFilters["sort"]) || "newest",
    min_price: searchParams.get("min_price") ? Number(searchParams.get("min_price")) : null,
    max_price: searchParams.get("max_price") ? Number(searchParams.get("max_price")) : null,
    condition: searchParams.get("condition") || null,
  };

  const updateFilters = useCallback(
    (patch: Partial<ListingFilters>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (patch.page != null) next.set("page", String(patch.page));
        if (patch.sort !== undefined) {
          if (patch.sort) next.set("sort", patch.sort);
          else next.delete("sort");
        }
        if ("min_price" in patch) {
          if (patch.min_price != null) next.set("min_price", String(patch.min_price));
          else next.delete("min_price");
        }
        if ("max_price" in patch) {
          if (patch.max_price != null) next.set("max_price", String(patch.max_price));
          else next.delete("max_price");
        }
        if ("condition" in patch) {
          if (patch.condition) next.set("condition", patch.condition);
          else next.delete("condition");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: ["public-listings", filters],
    queryFn: () => getListings(filters),
  });

  return (
    <>
      <Helmet>
        <title>Equipment for Sale — Temple Heavy Equipment</title>
        <meta
          name="description"
          content="Browse heavy equipment for sale at Temple Heavy Equipment. Excavators, dozers, graders, and more — all appraiser-verified."
        />
      </Helmet>

      <div className="min-h-screen bg-gray-50">
        <header className="border-b border-gray-200 bg-white px-6 py-4">
          <div className="mx-auto max-w-7xl">
            <h1 className="text-2xl font-bold text-gray-900">Equipment for Sale</h1>
            {data && (
              <p className="mt-1 text-sm text-gray-500">
                {data.total} {data.total === 1 ? "listing" : "listings"}
              </p>
            )}
          </div>
        </header>

        <main className="mx-auto max-w-7xl px-4 py-6">
          {/* Sort row */}
          <div className="mb-4 flex items-center justify-end gap-2">
            <label htmlFor="sort" className="text-sm text-gray-700">
              Sort:
            </label>
            <select
              id="sort"
              className="rounded-md border-gray-300 text-sm shadow-sm focus:border-gray-900 focus:ring-gray-900"
              value={filters.sort}
              onChange={(e) =>
                updateFilters({ sort: e.target.value as ListingFilters["sort"], page: 1 })
              }
            >
              <option value="newest">Newest</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
            </select>
          </div>

          <div className="flex flex-col gap-6 md:flex-row md:items-start">
            <FilterSidebar filters={filters} onChange={updateFilters} />

            <div className="flex-1">
              {isLoading && (
                <div className="flex justify-center py-20">
                  <Spinner />
                </div>
              )}

              {isError && (
                <Alert tone="error" title="Could not load listings">
                  Please refresh the page to try again.
                </Alert>
              )}

              {data && data.items.length === 0 && (
                <div className="py-20 text-center">
                  <p className="text-gray-500">No listings match your filters.</p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-4"
                    onClick={() =>
                      updateFilters({ min_price: null, max_price: null, condition: null, page: 1 })
                    }
                  >
                    Clear filters
                  </Button>
                </div>
              )}

              {data && data.items.length > 0 && (
                <>
                  <div
                    className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
                    aria-label="Equipment listings"
                  >
                    {data.items.map((item) => (
                      <ListingCardItem key={item.id} item={item} />
                    ))}
                  </div>

                  <div className="mt-8">
                    <Pagination
                      page={data.page}
                      total_pages={data.total_pages}
                      onPage={(p) => updateFilters({ page: p })}
                    />
                  </div>
                </>
              )}
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
