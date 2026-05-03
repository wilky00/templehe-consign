// ABOUTME: Custom renderWithProviders() wraps UI in QueryClientProvider + MemoryRouter.
// ABOUTME: Pass { authenticated: false } to test unauthenticated renders; default seeds a token.
import type { ReactElement } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { useAuthStore } from "../state/auth";

export const TEST_TOKEN = "test-access-token";

interface RenderOptions {
  authenticated?: boolean;
  initialEntries?: string[];
}

export function renderWithProviders(
  ui: ReactElement,
  { authenticated = true, initialEntries = ["/"] }: RenderOptions = {},
): RenderResult {
  if (authenticated) {
    useAuthStore.setState({ accessToken: TEST_TOKEN });
  } else {
    useAuthStore.setState({ accessToken: null });
  }

  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
