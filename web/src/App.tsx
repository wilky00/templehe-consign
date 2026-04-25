// ABOUTME: Top-level routes — public auth pages + the protected customer portal.
// ABOUTME: Sales CRM (Phase 3) and Admin Panel (Phase 4) remain placeholders until those phases land.
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AccountPage } from "./pages/Account";
import { AccountNotificationsPage } from "./pages/AccountNotifications";
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

function PhasePlaceholder({ title }: { title: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
        <p className="mt-2 text-gray-500">Coming in a future phase.</p>
      </div>
    </div>
  );
}

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
      <Route path="/admin/*" element={<PhasePlaceholder title="Admin Panel" />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
