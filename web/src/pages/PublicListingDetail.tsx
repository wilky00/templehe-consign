// ABOUTME: Public listing detail page — /listings/:id with full equipment info + inquiry form.
// ABOUTME: No auth required. SEO meta via react-helmet-async. Inquiry sends POST to backend.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Helmet } from "react-helmet-async";
import { getListingDetail, submitInquiry } from "../api/listings";
import type { InquiryRequest } from "../api/listings";
import { ApiError } from "../api/client";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { TextInput, Textarea } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";
import { usePageView } from "../services/analytics";

function formatPrice(price: number | null): string {
  if (price == null) return "Price on request";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(price);
}

function FieldRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">{value}</span>
    </div>
  );
}

interface InquiryFormState {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  message: string;
}

const EMPTY_FORM: InquiryFormState = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  message: "",
};

function InquiryForm({ listingId, listingTitle }: { listingId: string; listingTitle: string }) {
  const [form, setForm] = useState<InquiryFormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof InquiryFormState, string>>>({});

  const mutation = useMutation({
    mutationFn: (body: InquiryRequest) => submitInquiry(listingId, body),
  });

  function validate(): boolean {
    const next: typeof errors = {};
    if (!form.first_name.trim()) next.first_name = "First name is required.";
    if (!form.last_name.trim()) next.last_name = "Last name is required.";
    if (!form.email.trim()) {
      next.email = "Email is required.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      next.email = "Enter a valid email address.";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    mutation.mutate({
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      email: form.email.trim(),
      phone: form.phone.trim() || null,
      message: form.message.trim() || null,
    });
  }

  function set(field: keyof InquiryFormState) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
      if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }));
    };
  }

  if (mutation.isSuccess) {
    return (
      <Alert tone="success" title="Inquiry submitted">
        {mutation.data.message}
      </Alert>
    );
  }

  return (
    <Card>
      <h2 className="text-base font-semibold text-gray-900">Inquire about this unit</h2>
      <p className="mt-1 text-sm text-gray-500">
        A sales representative will contact you within 1 business day.
      </p>

      {mutation.isError && (
        <div className="mt-3">
          <Alert tone="error" title="Could not submit inquiry">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : "Please try again."}
          </Alert>
        </div>
      )}

      <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-4" aria-label={`Inquiry form for ${listingTitle}`}>
        {/* honeypot — hidden from humans, filled by bots */}
        <input
          type="text"
          name="web_address"
          tabIndex={-1}
          autoComplete="off"
          className="sr-only"
          aria-hidden="true"
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextInput
            id="inquiry-first-name"
            label="First name"
            required
            value={form.first_name}
            onChange={set("first_name")}
            error={errors.first_name}
            disabled={mutation.isPending}
          />
          <TextInput
            id="inquiry-last-name"
            label="Last name"
            required
            value={form.last_name}
            onChange={set("last_name")}
            error={errors.last_name}
            disabled={mutation.isPending}
          />
        </div>

        <TextInput
          id="inquiry-email"
          label="Email"
          type="email"
          required
          value={form.email}
          onChange={set("email")}
          error={errors.email}
          disabled={mutation.isPending}
          autoComplete="email"
        />

        <TextInput
          id="inquiry-phone"
          label="Phone (optional)"
          type="tel"
          value={form.phone}
          onChange={set("phone")}
          disabled={mutation.isPending}
          autoComplete="tel"
        />

        <Textarea
          id="inquiry-message"
          label="Message (optional)"
          rows={4}
          value={form.message}
          onChange={set("message")}
          disabled={mutation.isPending}
          placeholder="Questions about condition, availability, transport…"
        />

        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Sending…" : "Send inquiry"}
        </Button>
      </form>
    </Card>
  );
}

export function PublicListingDetailPage() {
  usePageView();
  const { id } = useParams<{ id: string }>();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["public-listing", id],
    queryFn: () => getListingDetail(id!),
    enabled: Boolean(id),
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <Spinner />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="min-h-screen bg-gray-50 px-4 py-12">
        <div className="mx-auto max-w-lg">
          <Alert tone="error" title="Listing not found">
            This listing may have been sold or removed.{" "}
            <Link to="/listings" className="underline">
              Browse all listings
            </Link>
            .
          </Alert>
        </div>
      </div>
    );
  }

  const pageTitle = `${data.listing_title} — Temple Heavy Equipment`;
  const description = [
    [data.year, data.make, data.model].filter(Boolean).join(" "),
    data.hours_condition ? `Condition: ${data.hours_condition}` : null,
    data.asking_price ? formatPrice(data.asking_price) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <Helmet>
        <title>{pageTitle}</title>
        <meta name="description" content={description} />
        <meta property="og:title" content={pageTitle} />
        <meta property="og:description" content={description} />
        {data.primary_photo_url && (
          <meta property="og:image" content={data.primary_photo_url} />
        )}
      </Helmet>

      <div className="min-h-screen bg-gray-50">
        <header className="border-b border-gray-200 bg-white px-6 py-4">
          <div className="mx-auto max-w-5xl">
            <Link to="/listings" className="text-sm text-gray-600 underline">
              &larr; All listings
            </Link>
            <h1 className="mt-2 text-2xl font-bold text-gray-900">{data.listing_title}</h1>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-4 py-8">
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
            {/* Left column — photo + specs */}
            <div className="lg:col-span-2 space-y-6">
              <div className="aspect-[4/3] w-full overflow-hidden rounded-lg bg-gray-100">
                {data.primary_photo_url ? (
                  <img
                    src={data.primary_photo_url}
                    alt={data.listing_title}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-gray-400" aria-hidden="true">
                    <svg className="h-16 w-16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                  </div>
                )}
              </div>

              <Card>
                <h2 className="text-base font-semibold text-gray-900">Equipment details</h2>
                <dl className="mt-3 divide-y divide-gray-100">
                  <FieldRow label="Make" value={data.make} />
                  <FieldRow label="Model" value={data.model} />
                  <FieldRow label="Year" value={data.year} />
                  <FieldRow label="Serial number" value={data.serial_number} />
                  <FieldRow label="Category" value={data.category_name} />
                  <FieldRow label="Condition" value={data.hours_condition} />
                  <FieldRow label="Running status" value={data.running_status} />
                  <FieldRow label="Marketability" value={data.marketability_rating} />
                  <FieldRow label="Location" value={data.state} />
                </dl>
              </Card>

              {(data.listing_notes || data.transport_notes) && (
                <Card>
                  <h2 className="text-base font-semibold text-gray-900">Notes</h2>
                  {data.listing_notes && (
                    <p className="mt-3 whitespace-pre-wrap text-sm text-gray-700">{data.listing_notes}</p>
                  )}
                  {data.transport_notes && (
                    <div className={data.listing_notes ? "mt-4 border-t border-gray-100 pt-4" : "mt-3"}>
                      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Transport</p>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-gray-700">{data.transport_notes}</p>
                    </div>
                  )}
                </Card>
              )}
            </div>

            {/* Right column — price + inquiry */}
            <div className="space-y-4">
              <Card>
                <p className="text-2xl font-bold text-gray-900">{formatPrice(data.asking_price)}</p>
                {data.assigned_rep_name && (
                  <p className="mt-1 text-sm text-gray-500">Contact: {data.assigned_rep_name}</p>
                )}
                {data.contact_phone && (
                  <p className="mt-0.5 text-sm text-gray-500">{data.contact_phone}</p>
                )}
              </Card>

              <InquiryForm listingId={id!} listingTitle={data.listing_title} />
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
