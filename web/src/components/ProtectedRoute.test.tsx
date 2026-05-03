// ABOUTME: Tests for ProtectedRoute — redirect when unauthenticated, spinner while loading, renders children.
// ABOUTME: Navigate and useMe are mocked to prevent routing loops from state={from:location} growth.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { ProtectedRoute } from "./ProtectedRoute";
import { renderWithProviders } from "../test/render";
import type { UseQueryResult } from "@tanstack/react-query";
import type { CurrentUser } from "../api/types";

// Navigate in ProtectedRoute passes state={{ from: location }}, which grows on each re-render
// at the same URL and creates an infinite redirect loop in MemoryRouter. Mock Navigate to a
// passive element so the router state never changes.
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, Navigate: ({ to }: { to: string }) => <div data-testid="redirect" data-href={to} /> };
});

vi.mock("../hooks/useMe", () => ({
  useMe: vi.fn(),
}));

import { useMe } from "../hooks/useMe";

const mockUseMe = vi.mocked(useMe);

function fakeQuery(overrides: Partial<UseQueryResult<CurrentUser>>): UseQueryResult<CurrentUser> {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    isSuccess: false,
    isPending: false,
    isFetching: false,
    isRefetching: false,
    isLoadingError: false,
    isRefetchError: false,
    isPlaceholderData: false,
    status: "pending",
    fetchStatus: "idle",
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    errorUpdateCount: 0,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    refetch: vi.fn(),
    ...overrides,
  } as UseQueryResult<CurrentUser>;
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    mockUseMe.mockReturnValue(fakeQuery({ isLoading: true, isPending: true }));
  });

  it("redirects to /login when there is no access token", () => {
    renderWithProviders(
      <ProtectedRoute>
        <div>Protected content</div>
      </ProtectedRoute>,
      { authenticated: false, initialEntries: ["/portal"] },
    );
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.getByTestId("redirect")).toHaveAttribute("data-href", "/login");
  });

  it("renders children when authenticated and /me succeeds", () => {
    const user: CurrentUser = {
      id: "00000000-0000-0000-0000-000000000001",
      email: "test@example.com",
      role: "admin",
      roles: ["admin"],
      status: "active",
      first_name: "Test",
      last_name: "User",
      totp_enabled: false,
      requires_terms_reaccept: false,
    };
    mockUseMe.mockReturnValue(
      fakeQuery({ data: user, isLoading: false, isSuccess: true, status: "success" }),
    );
    renderWithProviders(
      <ProtectedRoute>
        <div>Protected content</div>
      </ProtectedRoute>,
      { authenticated: true },
    );
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("shows a spinner while /me is loading", () => {
    mockUseMe.mockReturnValue(fakeQuery({ isLoading: true, isPending: true }));
    renderWithProviders(
      <ProtectedRoute>
        <div>Protected content</div>
      </ProtectedRoute>,
      { authenticated: true },
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("redirects to /login when /me returns an error", () => {
    mockUseMe.mockReturnValue(
      fakeQuery({ isLoading: false, isError: true, isLoadingError: true, status: "error" }),
    );
    renderWithProviders(
      <ProtectedRoute>
        <div>Protected content</div>
      </ProtectedRoute>,
      { authenticated: true },
    );
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.getByTestId("redirect")).toHaveAttribute("data-href", "/login");
  });
});
