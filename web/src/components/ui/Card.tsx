// ABOUTME: Plain content container with a border + rounded corners for cards on the dashboard.
// ABOUTME: No variants — composed as needed in pages.
import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  className?: string;
}

export function Card({ children, className = "" }: Props) {
  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-5 shadow-sm ${className}`.trim()}>
      {children}
    </div>
  );
}
