// ABOUTME: Top-level routes — public auth pages + the protected customer/sales/admin SPA.
// ABOUTME: Phase 4 Sprint 1 wires the admin shell (operations + reports stub).
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AccountPage } from "./pages/Account";
import { AccountNotificationsPage } from "./pages/AccountNotifications";
import { AdminConfigPage } from "./pages/AdminConfig";
import { AdminCustomerEditPage } from "./pages/AdminCustomerEdit";
import { AdminCustomersPage } from "./pages/AdminCustomers";
import { AdminNotificationTemplatesPage } from "./pages/AdminNotificationTemplates";
import { AdminOperationsPage } from "./pages/AdminOperations";
import { AdminReportsPage } from "./pages/AdminReports";
import { AdminRoutingPage } from "./pages/AdminRouting";
import { DashboardPage } from "./pages/Dashboard";
import { EquipmentDetailPage } from "./pages/EquipmentDetail";
import { IntakeFormPage } from "./pages/IntakeForm";
import { LoginPage } from "./pages/Login";
import { NotFoundPage } from "./pages/NotFound";
import { RegisterPage } from "./pages/Register";
import { SalesCalendarPage } from "./pages/SalesCalendar";
import { SalesDashboardPage } from "./pages/SalesDashboard";
import { SalesEquipmentDetailPage } from "./pages/SalesEquipmentDetail";
import { VerifyEmailPage } from "./pages/VerifyEmail";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/portal" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/auth/verify-email" element={<VerifyEmailPage />} />

      <Route
        path="/portal"
        element={
          <ProtectedRoute>
            <Layout>
              <DashboardPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/portal/submit"
        element={
          <ProtectedRoute>
            <Layout>
              <IntakeFormPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/portal/equipment/:id"
        element={
          <ProtectedRoute>
            <Layout>
              <EquipmentDetailPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/portal/account"
        element={
          <ProtectedRoute>
            <Layout>
              <AccountPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/account/notifications"
        element={
          <ProtectedRoute>
            <Layout>
              <AccountNotificationsPage />
            </Layout>
          </ProtectedRoute>
        }
      />

      <Route
        path="/sales"
        element={
          <ProtectedRoute>
            <Layout>
              <SalesDashboardPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/sales/calendar"
        element={
          <ProtectedRoute>
            <Layout>
              <SalesCalendarPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/sales/equipment/:id"
        element={
          <ProtectedRoute>
            <Layout>
              <SalesEquipmentDetailPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/operations"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminOperationsPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/customers"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminCustomersPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/customers/:id"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminCustomerEditPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/config"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminConfigPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/routing"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminRoutingPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/notification-templates"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminNotificationTemplatesPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/reports"
        element={
          <ProtectedRoute>
            <Layout>
              <AdminReportsPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route path="/admin" element={<Navigate to="/admin/operations" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
