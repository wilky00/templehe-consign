// ABOUTME: Unit tests for PublicListingsPage — rendering, filtering, pagination, empty state.
// ABOUTME: PublicListingDetailPage — detail view, 404 state, inquiry form submission.
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { PublicListingsPage } from "./PublicListings";
import { PublicListingDetailPage } from "./PublicListingDetail";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import type { ListingCard, ListingDetail } from "../api/listings";

const TEST_LISTING: ListingCard = {
  id: "00000000-0000-0000-0000-000000000001",
  listing_title: "2019 Caterpillar 336",
  asking_price: 85000,
  status: "active",
  published_at: "2026-05-01T00:00:00Z",
  make: "Caterpillar",
  model: "336",
  year: 2019,
  category_name: "Excavator",
  hours_condition: "Good",
  marketability_rating: "Fast Sell",
  state: "TX",
  primary_photo_url: null,
};

const TEST_DETAIL: ListingDetail = {
  ...TEST_LISTING,
  serial_number: "CAT336-001",
  running_status: "running",
  transport_notes: "Can be transported via flatbed.",
  listing_notes: "Single owner. Well maintained.",
  assigned_rep_name: "John Rep",
  contact_phone: "555-0100",
};

function mockListings(items: ListingCard[] = [TEST_LISTING], total = 1) {
  server.use(
    http.get("http://localhost/api/v1/public/listings", () =>
      HttpResponse.json({
        items,
        total,
        page: 1,
        page_size: 24,
        total_pages: 1,
      }),
    ),
  );
}

function mockDetail(detail: ListingDetail = TEST_DETAIL) {
  server.use(
    http.get("http://localhost/api/v1/public/listings/:id", () =>
      HttpResponse.json(detail),
    ),
  );
}

// ---------------------------------------------------------------------------
// PublicListingsPage
// ---------------------------------------------------------------------------

describe("PublicListingsPage", () => {
  it("renders the page heading", () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    expect(screen.getByRole("heading", { name: /equipment for sale/i })).toBeInTheDocument();
  });

  it("renders listing cards when listings are returned", async () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getAllByText("2019 Caterpillar 336").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("$85,000")).toBeInTheDocument();
  });

  it("shows the condition badge on a card", async () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getByText("Good")).toBeInTheDocument();
    });
  });

  it("shows empty state when no listings match", async () => {
    mockListings([], 0);
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getByText(/no listings match/i)).toBeInTheDocument();
    });
  });

  it("shows total listing count", async () => {
    mockListings([TEST_LISTING], 42);
    server.use(
      http.get("http://localhost/api/v1/public/listings", () =>
        HttpResponse.json({
          items: [TEST_LISTING],
          total: 42,
          page: 1,
          page_size: 24,
          total_pages: 2,
        }),
      ),
    );
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getByText(/42 listings/i)).toBeInTheDocument();
    });
  });

  it("renders condition filter options", () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    expect(screen.getByRole("radio", { name: "Excellent" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Good" })).toBeInTheDocument();
  });

  it("renders sort dropdown", () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    expect(screen.getByRole("combobox", { name: /sort/i })).toBeInTheDocument();
  });

  it("renders without authentication", async () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getAllByText("2019 Caterpillar 336").length).toBeGreaterThan(0);
    });
  });

  it("shows error state on API failure", async () => {
    server.use(
      http.get("http://localhost/api/v1/public/listings", () =>
        HttpResponse.json({ detail: "server error" }, { status: 500 }),
      ),
    );
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getByText(/could not load listings/i)).toBeInTheDocument();
    });
  });

  it("links listing cards to detail pages", async () => {
    mockListings();
    renderWithProviders(<PublicListingsPage />, { authenticated: false });
    await waitFor(() => {
      expect(screen.getAllByText("2019 Caterpillar 336").length).toBeGreaterThan(0);
    });
    const link = screen.getByRole("link", { name: /2019 caterpillar 336/i });
    expect(link).toHaveAttribute("href", `/listings/${TEST_LISTING.id}`);
  });
});

// ---------------------------------------------------------------------------
// PublicListingDetailPage
// ---------------------------------------------------------------------------

describe("PublicListingDetailPage", () => {
  it("renders the listing title", async () => {
    mockDetail();
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: [`/listings/${TEST_DETAIL.id}`],
      path: "/listings/:id",
    });
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "2019 Caterpillar 336" })).toBeInTheDocument();
    });
  });

  it("shows equipment details fields", async () => {
    mockDetail();
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: [`/listings/${TEST_DETAIL.id}`],
      path: "/listings/:id",
    });
    await waitFor(() => {
      expect(screen.getByText("Caterpillar")).toBeInTheDocument();
    });
    expect(screen.getByText("Good")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("shows the asking price", async () => {
    mockDetail();
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: [`/listings/${TEST_DETAIL.id}`],
      path: "/listings/:id",
    });
    await waitFor(() => {
      expect(screen.getByText("$85,000")).toBeInTheDocument();
    });
  });

  it("shows inquiry form", async () => {
    mockDetail();
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: [`/listings/${TEST_DETAIL.id}`],
      path: "/listings/:id",
    });
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /inquire about/i })).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  });

  it("shows 404 message on API error", async () => {
    server.use(
      http.get("http://localhost/api/v1/public/listings/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: ["/listings/00000000-0000-0000-0000-000000000099"],
      path: "/listings/:id",
    });
    await waitFor(() => {
      expect(screen.getByText(/listing not found/i)).toBeInTheDocument();
    });
  });

  it("submits inquiry form and shows success message", async () => {
    mockDetail();
    server.use(
      http.post("http://localhost/api/v1/public/listings/:id/inquiries", () =>
        HttpResponse.json(
          {
            id: "00000000-0000-0000-0000-000000000002",
            message: "Thank you for your inquiry. A sales representative will be in touch shortly.",
          },
          { status: 201 },
        ),
      ),
    );
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: [`/listings/${TEST_DETAIL.id}`],
      path: "/listings/:id",
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/first name/i), "Bob");
    await userEvent.type(screen.getByLabelText(/last name/i), "Buyer");
    await userEvent.type(screen.getByLabelText(/email/i), "bob@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send inquiry/i }));

    await waitFor(() => {
      expect(screen.getByText(/inquiry submitted/i)).toBeInTheDocument();
    });
  });

  it("validates required fields before submitting", async () => {
    mockDetail();
    renderWithProviders(<PublicListingDetailPage />, {
      authenticated: false,
      initialEntries: [`/listings/${TEST_DETAIL.id}`],
      path: "/listings/:id",
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /send inquiry/i })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: /send inquiry/i }));
    await waitFor(() => {
      expect(screen.getByText(/first name is required/i)).toBeInTheDocument();
    });
  });
});
