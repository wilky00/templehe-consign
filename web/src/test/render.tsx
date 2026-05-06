// ABOUTME: Custom renderWithProviders() wraps UI in QueryClientProvider + MemoryRouter.
// ABOUTME: Pass { authenticated: false } to test unauthenticated renders; default seeds a token.
import type { ReactElement } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HelmetProvider } from "react-helmet-async";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useAuthStore } from "../state/auth";

export const TEST_TOKEN = "test-access-token";

interface RenderOptions {
  authenticated?: boolean;
  initialEntries?: string[];
  /** When set, wraps ui in <Routes><Route path={path} element={ui} /> so useParams works. */
  path?: string;
}

export function renderWithProviders(
  ui: ReactElement,
  { authenticated = true, initialEntries = ["/"], path }: RenderOptions = {},
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

  const content = path ? (
    <Routes>
      <Route path={path} element={ui} />
    </Routes>
  ) : (
    ui
  );

  return render(
    <HelmetProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={initialEntries}>{content}</MemoryRouter>
      </QueryClientProvider>
    </HelmetProvider>,
  );
}
