// ABOUTME: Catch-all 404 page. Offers a link back to the portal root.
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
      <div className="text-center">
        <h1 className="text-3xl font-semibold text-gray-900">404</h1>
        <p className="mt-2 text-sm text-gray-600">
          That page doesn't exist.
        </p>
        <Link
          to="/portal"
          className="mt-4 inline-block font-medium text-gray-900 underline"
        >
          Back to the dashboard
        </Link>
      </div>
    </div>
  );
}
