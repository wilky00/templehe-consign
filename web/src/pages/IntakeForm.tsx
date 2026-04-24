// ABOUTME: Customer intake form — single page. Submits record, then uploads photos via the signed-URL flow.
// ABOUTME: On success navigates to the detail page so the customer can see their THE-XXXXXXXX reference.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { listCategories, submitIntake } from "../api/equipment";
import { uploadIntakePhoto } from "../hooks/usePhotoUpload";
import type { OwnershipType, RunningStatus } from "../api/types";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Select, TextInput, Textarea } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";

const RUNNING_OPTIONS = [
  { value: "running", label: "Running" },
  { value: "partially_running", label: "Partially running" },
  { value: "not_running", label: "Not running" },
];

const OWNERSHIP_OPTIONS = [
  { value: "owned", label: "Owned" },
  { value: "financed", label: "Financed" },
  { value: "leased", label: "Leased" },
  { value: "unknown", label: "Unknown / Other" },
];

type FormState = {
  categoryId: string;
  make: string;
  model: string;
  year: string;
  serialNumber: string;
  hours: string;
  runningStatus: string;
  ownershipType: string;
  locationText: string;
  description: string;
};

const EMPTY_FORM: FormState = {
  categoryId: "",
  make: "",
  model: "",
  year: "",
  serialNumber: "",
  hours: "",
  runningStatus: "",
  ownershipType: "",
  locationText: "",
  description: "",
};

export function IntakeFormPage() {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [files, setFiles] = useState<File[]>([]);
  const [photoErrors, setPhotoErrors] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const categories = useQuery({
    queryKey: ["equipment-categories"],
    queryFn: listCategories,
  });

  const mutation = useMutation({
    mutationFn: async () => {
      const record = await submitIntake({
        category_id: form.categoryId || null,
        make: form.make || null,
        model: form.model || null,
        year: form.year ? Number(form.year) : null,
        serial_number: form.serialNumber || null,
        hours: form.hours ? Number(form.hours) : null,
        running_status: (form.runningStatus as RunningStatus) || null,
        ownership_type: (form.ownershipType as OwnershipType) || null,
        location_text: form.locationText || null,
        description: form.description || null,
        photos: [],
      });

      if (files.length > 0) {
        setUploading(true);
        const errors: string[] = [];
        for (let i = 0; i < files.length; i++) {
          try {
            await uploadIntakePhoto(record.id, files[i], i);
          } catch (err) {
            errors.push(
              `${files[i].name}: ${
                err instanceof ApiError ? err.detail : (err as Error).message
              }`,
            );
          }
        }
        setPhotoErrors(errors);
        setUploading(false);
      }
      return record;
    },
    onSuccess: (record) => {
      qc.invalidateQueries({ queryKey: ["equipment"] });
      qc.invalidateQueries({ queryKey: ["equipment", record.id] });
      navigate(`/portal/equipment/${record.id}`);
    },
  });

  const update =
    (key: keyof FormState) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((s) => ({ ...s, [key]: e.target.value }));

  const onPickFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files ? Array.from(e.target.files) : [];
    // Hard-cap matches the backend's photos list max_length=20.
    setFiles(picked.slice(0, 20));
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPhotoErrors([]);
    mutation.mutate();
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Submit equipment</h1>
        <p className="mt-1 text-sm text-gray-600">
          Tell us about the machine you'd like us to appraise. A sales
          representative will follow up within one business day.
        </p>
      </div>

      <form className="space-y-6" onSubmit={onSubmit} noValidate>
        <Card>
          <div className="space-y-4">
            <Select
              id="category"
              label="Equipment category"
              placeholder={
                categories.isLoading ? "Loading categories…" : "Select a category"
              }
              options={
                categories.data?.map((c) => ({ value: c.id, label: c.name })) ?? []
              }
              value={form.categoryId}
              onChange={update("categoryId")}
            />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <TextInput
                id="make"
                label="Make"
                autoComplete="off"
                value={form.make}
                onChange={update("make")}
              />
              <TextInput
                id="model"
                label="Model"
                autoComplete="off"
                value={form.model}
                onChange={update("model")}
              />
              <TextInput
                id="year"
                label="Year"
                type="number"
                inputMode="numeric"
                min={1900}
                max={2100}
                value={form.year}
                onChange={update("year")}
              />
              <TextInput
                id="hours"
                label="Hour meter reading"
                type="number"
                inputMode="numeric"
                min={0}
                value={form.hours}
                onChange={update("hours")}
              />
              <TextInput
                id="serial"
                label="Serial / VIN (optional)"
                autoComplete="off"
                value={form.serialNumber}
                onChange={update("serialNumber")}
              />
              <Select
                id="running_status"
                label="Running condition"
                placeholder="Select one"
                options={RUNNING_OPTIONS}
                value={form.runningStatus}
                onChange={update("runningStatus")}
              />
              <Select
                id="ownership_type"
                label="Ownership"
                placeholder="Select one"
                options={OWNERSHIP_OPTIONS}
                value={form.ownershipType}
                onChange={update("ownershipType")}
              />
            </div>
            <TextInput
              id="location"
              label="Current location"
              hint="Yard, address, or city — where should we send the appraiser?"
              value={form.locationText}
              onChange={update("locationText")}
            />
            <Textarea
              id="description"
              label="Description"
              hint="Anything relevant: recent maintenance, known issues, attachments included."
              rows={5}
              value={form.description}
              onChange={update("description")}
            />
          </div>
        </Card>

        <Card>
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-medium text-gray-900">Photos</h2>
              <p className="text-sm text-gray-600">
                Upload 5–10 photos covering the exterior, cab, hour meter, and any
                visible damage. JPG, PNG, or WebP, up to 20 photos.
              </p>
            </div>
            <label htmlFor="intake-photos" className="sr-only">
              Select intake photos
            </label>
            <input
              id="intake-photos"
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
              onChange={onPickFiles}
              className="block w-full text-sm text-gray-900 file:mr-3 file:rounded-md file:border-0 file:bg-gray-900 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-gray-800"
            />
            {files.length > 0 && (
              <p className="text-sm text-gray-600">
                Selected {files.length} {files.length === 1 ? "photo" : "photos"}.
              </p>
            )}
          </div>
        </Card>

        {mutation.isError && (
          <Alert tone="error" title="Could not submit">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
          </Alert>
        )}

        {photoErrors.length > 0 && (
          <Alert tone="warning" title="Some photos failed to upload">
            <ul className="list-disc pl-4">
              {photoErrors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
            Your submission was created. You can add the missing photos from the
            detail page.
          </Alert>
        )}

        <div className="flex items-center gap-3">
          <Button
            type="submit"
            size="lg"
            disabled={mutation.isPending || uploading}
          >
            {mutation.isPending
              ? uploading
                ? "Uploading photos…"
                : "Submitting…"
              : "Submit for appraisal"}
          </Button>
          {(mutation.isPending || uploading) && <Spinner />}
        </div>
      </form>
    </div>
  );
}
