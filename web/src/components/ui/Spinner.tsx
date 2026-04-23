// ABOUTME: Minimal loading spinner used inline in pages and buttons.
// ABOUTME: Purely CSS — no external icon library dependency.
interface Props {
  size?: "sm" | "md";
  label?: string;
}

export function Spinner({ size = "md", label = "Loading" }: Props) {
  const dim = size === "sm" ? "h-4 w-4" : "h-6 w-6";
  return (
    <span
      role="status"
      aria-label={label}
      className={`inline-block ${dim} animate-spin rounded-full border-2 border-gray-300 border-t-gray-900`}
    />
  );
}
