// ABOUTME: Smoke tests for LoginPage — form fields, submit, error display, register link.
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { LoginPage } from "./Login";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";

describe("LoginPage", () => {
  it("renders email and password fields", () => {
    renderWithProviders(<LoginPage />, { authenticated: false });
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("renders the log in button", () => {
    renderWithProviders(<LoginPage />, { authenticated: false });
    expect(screen.getByRole("button", { name: /log in/i })).toBeInTheDocument();
  });

  it("renders a link to the register page", () => {
    renderWithProviders(<LoginPage />, { authenticated: false });
    expect(screen.getByRole("link", { name: /create an account/i })).toBeInTheDocument();
  });

  it("disables the button while submitting", async () => {
    server.use(
      http.post("http://localhost/api/v1/auth/login", async () => {
        await new Promise((r) => setTimeout(r, 200));
        return HttpResponse.json({ access_token: "tok", token_type: "bearer" });
      }),
    );
    renderWithProviders(<LoginPage />, { authenticated: false });
    await userEvent.type(screen.getByLabelText("Email"), "test@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "secret");
    await userEvent.click(screen.getByRole("button", { name: /log in/i }));
    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
  });

  it("shows an error alert when login fails", async () => {
    server.use(
      http.post("http://localhost/api/v1/auth/login", () =>
        HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 }),
      ),
    );
    renderWithProviders(<LoginPage />, { authenticated: false });
    await userEvent.type(screen.getByLabelText("Email"), "bad@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /log in/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/Invalid credentials/i)).toBeInTheDocument();
    });
  });

  it("shows 'Log in' label when not submitting", () => {
    renderWithProviders(<LoginPage />, { authenticated: false });
    expect(screen.getByRole("button", { name: /^log in$/i })).toBeInTheDocument();
  });
});
