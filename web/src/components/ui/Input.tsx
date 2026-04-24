// ABOUTME: Form input atoms — TextInput, Select, Textarea — with consistent labels and error states.
// ABOUTME: Each emits accessible markup (label+id, aria-invalid on error).
import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

const baseFieldClasses =
  "block w-full rounded-md border-gray-300 shadow-sm " +
  "focus:border-gray-900 focus:ring-gray-900 sm:text-sm " +
  "disabled:bg-gray-100 disabled:text-gray-500";

const errorFieldClasses =
  "block w-full rounded-md border-red-500 text-red-900 shadow-sm " +
  "focus:border-red-600 focus:ring-red-600 sm:text-sm";

function FieldLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-900">
      {children}
    </label>
  );
}

function FieldError({ message }: { message?: string | null }) {
  if (!message) return null;
  return <p className="mt-1 text-sm text-red-700">{message}</p>;
}

interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  error?: string | null;
  hint?: string | null;
}

export function TextInput({
  id,
  label,
  error,
  hint,
  className = "",
  ...rest
}: TextInputProps) {
  const invalid = Boolean(error);
  return (
    <div className="space-y-1">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <input
        id={id}
        aria-invalid={invalid || undefined}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={`${invalid ? errorFieldClasses : baseFieldClasses} ${className}`.trim()}
        {...rest}
      />
      {hint && !error && (
        <p id={`${id}-hint`} className="text-sm text-gray-500">
          {hint}
        </p>
      )}
      <FieldError message={error} />
    </div>
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  id: string;
  label: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  error?: string | null;
  placeholder?: string;
}

export function Select({
  id,
  label,
  options,
  error,
  placeholder,
  className = "",
  ...rest
}: SelectProps) {
  const invalid = Boolean(error);
  return (
    <div className="space-y-1">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <select
        id={id}
        aria-invalid={invalid || undefined}
        className={`${invalid ? errorFieldClasses : baseFieldClasses} ${className}`.trim()}
        {...rest}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <FieldError message={error} />
    </div>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  id: string;
  label: string;
  error?: string | null;
  hint?: string | null;
}

export function Textarea({
  id,
  label,
  error,
  hint,
  className = "",
  rows = 4,
  ...rest
}: TextareaProps) {
  const invalid = Boolean(error);
  return (
    <div className="space-y-1">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <textarea
        id={id}
        rows={rows}
        aria-invalid={invalid || undefined}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={`${invalid ? errorFieldClasses : baseFieldClasses} ${className}`.trim()}
        {...rest}
      />
      {hint && !error && (
        <p id={`${id}-hint`} className="text-sm text-gray-500">
          {hint}
        </p>
      )}
      <FieldError message={error} />
    </div>
  );
}

interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  description?: string;
}

export function Checkbox({ id, label, description, className = "", ...rest }: CheckboxProps) {
  return (
    <div className="flex items-start">
      <input
        id={id}
        type="checkbox"
        className={`mt-1 h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900 ${className}`.trim()}
        {...rest}
      />
      <div className="ml-3">
        <label htmlFor={id} className="text-sm font-medium text-gray-900">
          {label}
        </label>
        {description && <p className="text-sm text-gray-500">{description}</p>}
      </div>
    </div>
  );
}
