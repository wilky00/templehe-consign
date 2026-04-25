// ABOUTME: /account/notifications — choose preferred channel for workflow notifications.
// ABOUTME: Customers see a read-only state; hidden roles get a "not available" placeholder.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getNotificationPreferences,
  updateNotificationPreferences,
} from "../api/notifications";
import { ApiError } from "../api/client";
import type {
  NotificationChannel,
  NotificationPreference,
  NotificationPreferenceUpdateRequest,
} from "../api/types";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { TextInput } from "../components/ui/Input";
import { Spinner } from "../components/ui/Spinner";

interface DraftState {
  channel: NotificationChannel;
  phone_number: string;
  slack_user_id: string;
}

function toDraft(pref: NotificationPreference): DraftState {
  return {
    channel: pref.channel,
    phone_number: pref.phone_number ?? "",
    slack_user_id: pref.slack_user_id ?? "",
  };
}

function toRequest(d: DraftState): NotificationPreferenceUpdateRequest {
  return {
    channel: d.channel,
    phone_number: d.phone_number.trim() || null,
    slack_user_id: d.slack_user_id.trim() || null,
  };
}

const CHANNEL_OPTIONS: ReadonlyArray<{
  value: NotificationChannel;
  label: string;
  description: string;
}> = [
  {
    value: "email",
    label: "Email",
    description: "Workflow notifications go to your account email.",
  },
  {
    value: "sms",
    label: "SMS",
    description: "Text messages to a phone number you provide.",
  },
  {
    value: "slack",
    label: "Slack",
    description:
      "Slack DMs (currently delivered as email until the Slack integration ships).",
  },
];

export function AccountNotificationsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Notifications</h1>
        <p className="mt-1 text-sm text-gray-600">
          Pick how you want to be notified about workflow events — manager
          approvals, eSign completions, lock overrides.
        </p>
      </div>
      <PreferencesCard />
    </div>
  );
}

function PreferencesCard() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: getNotificationPreferences,
  });

  const [draft, setDraft] = useState<DraftState | null>(null);

  useEffect(() => {
    if (query.data && !("hidden" in query.data)) {
      setDraft(toDraft(query.data));
    }
  }, [query.data]);

  const mutation = useMutation({
    mutationFn: (body: NotificationPreferenceUpdateRequest) =>
      updateNotificationPreferences(body),
    onSuccess: (data) => {
      qc.setQueryData(["notification-preferences"], data);
    },
  });

  if (query.isLoading || !query.data) {
    return (
      <Card>
        <div className="py-4">
          <Spinner />
        </div>
      </Card>
    );
  }

  if ("hidden" in query.data) {
    return (
      <Card>
        <h2 className="text-base font-medium text-gray-900">
          Notifications unavailable
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Notification preferences are not available for your account.
        </p>
      </Card>
    );
  }

  const pref = query.data;
  const readOnly = pref.read_only;
  const current = draft ?? toDraft(pref);

  const setChannel = (channel: NotificationChannel) =>
    setDraft({ ...current, channel });

  const setField = (key: "phone_number" | "slack_user_id", value: string) =>
    setDraft({ ...current, [key]: value });

  const canSubmit =
    !readOnly &&
    !mutation.isPending &&
    (current.channel !== "sms" || current.phone_number.trim().length > 0) &&
    (current.channel !== "slack" || current.slack_user_id.trim().length > 0);

  return (
    <Card>
      <h2 className="text-base font-medium text-gray-900">Preferred channel</h2>
      {readOnly && (
        <p className="mt-1 text-sm text-gray-600">
          Your account uses email for all notifications. Contact support if you
          need to update these settings.
        </p>
      )}

      <fieldset
        className="mt-4 space-y-3"
        disabled={readOnly}
        aria-label="Preferred notification channel"
      >
        <legend className="sr-only">Preferred notification channel</legend>
        {CHANNEL_OPTIONS.map((opt) => {
          const checked = current.channel === opt.value;
          return (
            <label
              key={opt.value}
              htmlFor={`channel-${opt.value}`}
              className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 ${
                checked
                  ? "border-gray-900 bg-gray-50"
                  : "border-gray-200 hover:border-gray-300"
              } ${readOnly ? "cursor-not-allowed opacity-75" : ""}`}
            >
              <input
                id={`channel-${opt.value}`}
                type="radio"
                name="notification-channel"
                value={opt.value}
                checked={checked}
                onChange={() => setChannel(opt.value)}
                className="mt-1 h-4 w-4 border-gray-300 text-gray-900 focus:ring-gray-900"
              />
              <div>
                <div className="text-sm font-medium text-gray-900">
                  {opt.label}
                </div>
                <div className="text-sm text-gray-600">{opt.description}</div>
              </div>
            </label>
          );
        })}
      </fieldset>

      {current.channel === "sms" && (
        <div className="mt-4">
          <TextInput
            id="pref-phone"
            label="Phone number"
            type="tel"
            placeholder="+15555550123"
            value={current.phone_number}
            onChange={(e) => setField("phone_number", e.target.value)}
            disabled={readOnly}
            required
          />
        </div>
      )}

      {current.channel === "slack" && (
        <div className="mt-4">
          <TextInput
            id="pref-slack"
            label="Slack user ID"
            placeholder="U01234567"
            value={current.slack_user_id}
            onChange={(e) => setField("slack_user_id", e.target.value)}
            disabled={readOnly}
            required
          />
        </div>
      )}

      {mutation.isError && (
        <div className="mt-4">
          <Alert tone="error" title="Could not save preferences">
            {mutation.error instanceof ApiError
              ? mutation.error.detail
              : (mutation.error as Error).message}
          </Alert>
        </div>
      )}
      {mutation.isSuccess && !mutation.isPending && (
        <div className="mt-4">
          <Alert tone="success" title="Preferences saved" />
        </div>
      )}

      {!readOnly && (
        <div className="mt-4">
          <Button
            onClick={() => mutation.mutate(toRequest(current))}
            disabled={!canSubmit}
          >
            {mutation.isPending ? "Saving…" : "Save preferences"}
          </Button>
        </div>
      )}
    </Card>
  );
}
