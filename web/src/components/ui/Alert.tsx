// ABOUTME: Inline alert atom for form errors, success, and informational messages.
// ABOUTME: role="alert" for errors so assistive tech announces them immediately.
import type { ReactNode } from "react";

export type AlertTone = "error" | "warning" | "success" | "info";

const toneClasses: Record<AlertTone, string> = {
  error: "bg-red-50 border-red-200 text-red-900",
  warning: "bg-amber-50 border-amber-200 text-amber-900",
  success: "bg-green-50 border-green-200 text-green-900",
  info: "bg-blue-50 border-blue-200 text-blue-900",
};

interface Props {
  tone?: AlertTone;
  title?: string;
  children?: ReactNode;
}

export function Alert({ tone = "info", title, children }: Props) {
  const role = tone === "error" || tone === "warning" ? "alert" : "status";
  return (
    <div role={role} className={`rounded-md border p-3 text-sm ${toneClasses[tone]}`}>
      {title && <p className="font-medium">{title}</p>}
      {children && <div className={title ? "mt-1" : undefined}>{children}</div>}
    </div>
  );
}
