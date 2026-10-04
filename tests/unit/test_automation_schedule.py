from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.db.models import JobType, ScheduledJobModel
from app.events.bus import EventBus
from app.events.automation_schedule import AutomationSchedule, next_automation_run
from app.events.scheduler import PersistentScheduler


def test_interval_schedule_keeps_elapsed_interval_semantics():
    after = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    assert next_automation_run(AutomationSchedule(), after, 3600) == datetime(2026, 10, 4, 13, 0, tzinfo=timezone.utc)


def test_daily_schedule_uses_saved_timezone_wall_clock():
    schedule = AutomationSchedule(mode="daily", local_time="09:00", timezone="Asia/Saigon")
    after = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
    assert next_automation_run(schedule, after, 86400) == datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)


def test_weekly_schedule_selects_the_next_configured_local_weekday():
    schedule = AutomationSchedule(mode="weekly", local_time="09:00", weekdays=[0, 2], timezone="Asia/Saigon")
    after = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)  # Sunday
    assert next_automation_run(schedule, after, 86400) == datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)


def test_nonexistent_spring_forward_time_moves_forward_by_the_gap():
    schedule = AutomationSchedule(mode="daily", local_time="02:30", timezone="America/New_York")
    after = datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc)
    assert next_automation_run(schedule, after, 86400) == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)


def test_ambiguous_fall_back_time_fires_once_at_the_first_occurrence():
    schedule = AutomationSchedule(mode="daily", local_time="01:30", timezone="America/New_York")
    after = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    assert next_automation_run(schedule, after, 86400) == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_scheduler_advances_an_automation_to_its_next_local_occurrence(test_db_session, monkeypatch):
    now = datetime(2026, 10, 4, 0, 1, tzinfo=timezone.utc)
    job = ScheduledJobModel(
        name="Daily wall-clock automation",
        job_type=JobType.RECURRING.value,
        schedule_expression="86400",
        payload_json={"message": "Run daily."},
        is_active=True,
        next_run_at=now - timedelta(minutes=1),
        metadata_json={
            "kind": "automation",
            "schedule": {"mode": "daily", "local_time": "09:00", "weekdays": [], "timezone": "Asia/Saigon"},
        },
    )
    test_db_session.add(job)
    await test_db_session.commit()
    monkeypatch.setattr("app.events.scheduler.utc_now", lambda: now)

    emitted = await PersistentScheduler(EventBus()).tick(test_db_session, worker_id="wall-clock-test")

    assert len(emitted) == 1
    await test_db_session.refresh(job)
    scheduled_at = job.next_run_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    assert scheduled_at == datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("data", [
    {"mode": "daily", "local_time": "25:00", "timezone": "UTC"},
    {"mode": "daily", "local_time": "08:00", "timezone": "Mars/Olympus"},
    {"mode": "weekly", "local_time": "08:00", "weekdays": [], "timezone": "UTC"},
    {"mode": "weekly", "local_time": "08:00", "weekdays": [0, 0], "timezone": "UTC"},
    {"mode": "weekly", "local_time": "08:00", "weekdays": [True], "timezone": "UTC"},
])
def test_invalid_wall_clock_schedules_are_rejected(data):
    with pytest.raises(ValidationError):
        AutomationSchedule.model_validate(data)
