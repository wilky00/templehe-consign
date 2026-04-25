// ABOUTME: tel: link helper — renders a clickable phone number, or an em-dash when absent.
// ABOUTME: Strips formatting from the href so dialer apps get digits only.
interface Props {
  number: string | null | undefined;
  ext?: string | null;
  className?: string;
}

function toDigits(n: string): string {
  return n.replace(/[^\d+]/g, "");
}

export function PhoneLink({ number, ext, className }: Props) {
  if (!number) return <span className={className}>—</span>;
  const digits = toDigits(number);
  const display = ext ? `${number} x${ext}` : number;
  const href = ext ? `tel:${digits},${ext}` : `tel:${digits}`;
  return (
    <a
      href={href}
      className={
        className ??
        "text-gray-900 underline decoration-dotted underline-offset-2 hover:text-gray-700"
      }
      aria-label={`Call ${display}`}
    >
      {display}
    </a>
  );
}
