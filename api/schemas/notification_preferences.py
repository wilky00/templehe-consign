# ABOUTME: Pydantic shapes for /me/notification-preferences GET + PUT.
# ABOUTME: Channel enum + conditional destination validation; read_only flag mirrors role policy.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Channel = Literal["email", "sms", "slack"]


class NotificationPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: Channel
    phone_number: str | None = None
    slack_user_id: str | None = None
    # ``read_only`` is policy, not stored data — the router fills it from
    # the user's role. Surfacing it here lets the UI render an RO state
    # without a second round-trip.
    read_only: bool = False


class NotificationPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel
    phone_number: str | None = Field(default=None, max_length=20)
    slack_user_id: str | None = Field(default=None, max_length=100)

    @field_validator("phone_number")
    @classmethod
    def _strip_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None

    @field_validator("slack_user_id")
    @classmethod
    def _strip_slack(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _require_destination(self) -> NotificationPreferenceUpdate:
        if self.channel == "sms" and not self.phone_number:
            raise ValueError("phone_number is required when channel is 'sms'")
        if self.channel == "slack" and not self.slack_user_id:
            raise ValueError("slack_user_id is required when channel is 'slack'")
        return self
