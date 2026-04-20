// ABOUTME: Root application component — sets up routing for all TempleHE frontend views.
// ABOUTME: Phase 1 placeholder; full routes are built per phase (Portal=2, CRM=3, Admin=4).
import { Routes, Route } from "react-router-dom";

function Placeholder({ title }: { title: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
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
      <Route path="/" element={<Placeholder title="Temple Heavy Equipment" />} />
      <Route path="/login" element={<Placeholder title="Login" />} />
      <Route path="/portal/*" element={<Placeholder title="Customer Portal" />} />
      <Route path="/sales/*" element={<Placeholder title="Sales CRM" />} />
      <Route path="/admin/*" element={<Placeholder title="Admin Panel" />} />
      <Route path="*" element={<Placeholder title="404 — Page Not Found" />} />
    </Routes>
  );
}
