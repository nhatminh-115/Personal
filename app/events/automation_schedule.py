"""Wall-clock schedules for user automations, evaluated in their saved timezone."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator


class AutomationSchedule(BaseModel):
    mode: Literal["interval", "daily", "weekly"] = "interval"
    local_time: str | None = None
    weekdays: list[StrictInt] = Field(default_factory=list)
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A valid IANA timezone is required.")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Timezone must be a valid IANA timezone.") from exc
        return value

    @field_validator("local_time")
    @classmethod
    def validate_local_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Local time must use HH:MM format.") from exc
        if parsed.second or parsed.microsecond or len(value) != 5:
            raise ValueError("Local time must use HH:MM format.")
        return value

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if any(isinstance(day, bool) or day < 0 or day > 6 for day in value):
            raise ValueError("Weekdays must be integers from 0 (Monday) through 6 (Sunday).")
        if len(set(value)) != len(value):
            raise ValueError("Weekdays cannot contain duplicates.")
        return sorted(value)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "AutomationSchedule":
        if self.mode in {"daily", "weekly"} and self.local_time is None:
            raise ValueError("Daily and weekly schedules require a local time.")
        if self.mode == "weekly" and not self.weekdays:
            raise ValueError("Weekly schedules require at least one weekday.")
        if self.mode != "weekly" and self.weekdays:
            raise ValueError("Weekdays are only valid for weekly schedules.")
        return self


def next_automation_run(
    schedule: AutomationSchedule | dict,
    after: datetime,
    interval_seconds: int,
) -> datetime:
    """Return the next UTC due time strictly after ``after``.

    A nonexistent local wall time during a spring-forward transition is moved
    forward by the transition gap. For an ambiguous fall-back time, the first
    occurrence is selected so a schedule never fires twice in one local day.
    """
    config = schedule if isinstance(schedule, AutomationSchedule) else AutomationSchedule.model_validate(schedule)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    after_utc = after.astimezone(timezone.utc)
    if config.mode == "interval":
        return after_utc + timedelta(seconds=interval_seconds)

    zone = ZoneInfo(config.timezone)
    wall_time = time.fromisoformat(config.local_time or "00:00")
    local_after = after_utc.astimezone(zone)
    for day_offset in range(0, 9):
        local_date = local_after.date() + timedelta(days=day_offset)
        if config.mode == "weekly" and local_date.weekday() not in config.weekdays:
            continue
        candidate = datetime.combine(local_date, wall_time.replace(tzinfo=zone, fold=0))
        # ZoneInfo permits construction of nonexistent times; normalize through
        # UTC so 02:30 in a skipped hour becomes the first valid later wall time.
        candidate = candidate.astimezone(timezone.utc).astimezone(zone)
        if candidate.astimezone(timezone.utc) > after_utc:
            return candidate.astimezone(timezone.utc)
    raise ValueError("Could not find the next automation occurrence.")
