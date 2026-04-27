// ABOUTME: App shell for authenticated pages — sticky header with nav + logout, content area.
// ABOUTME: Renders children in a max-width container; shows the ToS re-accept interstitial on top.
import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { logout } from "../api/auth";
import { useAuthStore } from "../state/auth";
import { useMe } from "../hooks/useMe";
import { ToSInterstitial } from "./ToSInterstitial";

const navLinkClasses = (isActive: boolean) =>
  isActive
    ? "rounded-md bg-gray-100 px-3 py-2 text-sm font-medium text-gray-900"
    : "rounded-md px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900";

const SALES_ROLES = new Set(["sales", "sales_manager"]);
const ADMIN_ROLES = new Set(["admin"]);
const REPORTING_ROLES = new Set(["reporting"]);

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: user } = useMe();
  // Phase 4: a user can hold multiple roles. The admin shell takes
  // precedence over sales (since admin can do everything sales can do
  // plus the admin surface). The reporting role gets a stripped-down
  // shell with only the /admin/reports tab. Older payloads without
  // `roles` fall back to the primary `role` string.
  const heldRoles = user ? user.roles ?? [user.role] : [];
  const isAdminSide = heldRoles.some((r) => ADMIN_ROLES.has(r));
  const isSalesSide = !isAdminSide && heldRoles.some((r) => SALES_ROLES.has(r));
  const isReportingOnly =
    !isAdminSide &&
    !isSalesSide &&
    heldRoles.some((r) => REPORTING_ROLES.has(r));
  const homePath = isAdminSide
    ? "/admin/operations"
    : isReportingOnly
      ? "/admin/reports"
      : isSalesSide
        ? "/sales"
        : "/portal";

  const onLogout = async () => {
    try {
      await logout();
    } catch {
      // Even if the server call fails, clear local state and redirect.
    }
    useAuthStore.getState().clear();
    qc.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3 sm:px-6">
          <Link to={homePath} className="flex items-center gap-2">
            <span className="font-semibold text-gray-900">Temple Heavy Equipment</span>
          </Link>
          <nav className="flex items-center gap-1" aria-label="Main">
            {isAdminSide ? (
              <>
                <NavLink
                  to="/admin/operations"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Operations
                </NavLink>
                <NavLink
                  to="/admin/customers"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Customers
                </NavLink>
                <NavLink
                  to="/admin/config"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Config
                </NavLink>
                <NavLink
                  to="/admin/routing"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Routing
                </NavLink>
                <NavLink
                  to="/admin/notification-templates"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Templates
                </NavLink>
                <NavLink
                  to="/admin/categories"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Categories
                </NavLink>
                <NavLink
                  to="/admin/reports"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Reports
                </NavLink>
                <NavLink
                  to="/account/notifications"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Notifications
                </NavLink>
                <NavLink
                  to="/portal/account"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Account
                </NavLink>
              </>
            ) : isReportingOnly ? (
              <>
                <NavLink
                  to="/admin/reports"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Reports
                </NavLink>
                <NavLink
                  to="/portal/account"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Account
                </NavLink>
              </>
            ) : isSalesSide ? (
              <>
                <NavLink
                  to="/sales"
                  end
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Sales Dashboard
                </NavLink>
                <NavLink
                  to="/sales/calendar"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Calendar
                </NavLink>
                <NavLink
                  to="/account/notifications"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Notifications
                </NavLink>
                <NavLink
                  to="/portal/account"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Account
                </NavLink>
              </>
            ) : (
              <>
                <NavLink to="/portal" end className={({ isActive }) => navLinkClasses(isActive)}>
                  Dashboard
                </NavLink>
                <NavLink
                  to="/portal/submit"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Submit Equipment
                </NavLink>
                <NavLink
                  to="/account/notifications"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Notifications
                </NavLink>
                <NavLink
                  to="/portal/account"
                  className={({ isActive }) => navLinkClasses(isActive)}
                >
                  Account
                </NavLink>
              </>
            )}
          </nav>
          <div className="flex items-center gap-3 text-sm text-gray-600">
            {user && <span aria-label="Current user">{user.email}</span>}
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">{children}</main>
      <ToSInterstitial />
    </div>
  );
}
