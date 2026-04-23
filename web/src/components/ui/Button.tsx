// ABOUTME: Reusable button atom with size + variant props. Tailwind utility classes.
// ABOUTME: Default is a solid primary button; secondary/ghost/danger variants for other uses.
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-gray-900 text-white hover:bg-gray-800 disabled:bg-gray-400 focus-visible:ring-gray-900",
  secondary:
    "bg-white text-gray-900 border border-gray-300 hover:bg-gray-50 disabled:text-gray-400 focus-visible:ring-gray-900",
  ghost:
    "bg-transparent text-gray-700 hover:bg-gray-100 disabled:text-gray-400 focus-visible:ring-gray-500",
  danger:
    "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300 focus-visible:ring-red-600",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-base",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}: Props) {
  const base =
    "inline-flex items-center justify-center rounded-md font-medium " +
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 " +
    "disabled:cursor-not-allowed transition-colors";
  const cls = `${base} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`.trim();
  return (
    <button className={cls} {...rest}>
      {children}
    </button>
  );
}
