from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from celery.schedules import crontab
from django.conf import settings
from django.utils import timezone

from apps.analytics.tasks import compute_previous_day_analytics_snapshot_task


SCHEDULE_NAME = "analytics-compute-previous-day-snapshot"
TASK_PATH = "apps.analytics.tasks.compute_previous_day_analytics_snapshot_task"


def test_analytics_daily_snapshot_beat_schedule_is_registered():
    assert SCHEDULE_NAME in settings.CELERY_BEAT_SCHEDULE

    schedule_entry = settings.CELERY_BEAT_SCHEDULE[SCHEDULE_NAME]

    assert schedule_entry["task"] == TASK_PATH


def test_analytics_daily_snapshot_beat_schedule_uses_crontab():
    schedule_entry = settings.CELERY_BEAT_SCHEDULE[SCHEDULE_NAME]

    assert isinstance(schedule_entry["schedule"], crontab)


def test_analytics_daily_snapshot_schedule_time_settings_are_valid():
    assert isinstance(settings.ANALYTICS_DAILY_SNAPSHOT_HOUR, int)
    assert isinstance(settings.ANALYTICS_DAILY_SNAPSHOT_MINUTE, int)

    assert 0 <= settings.ANALYTICS_DAILY_SNAPSHOT_HOUR <= 23
    assert 0 <= settings.ANALYTICS_DAILY_SNAPSHOT_MINUTE <= 59


def test_analytics_daily_snapshot_schedule_has_no_required_args():
    schedule_entry = settings.CELERY_BEAT_SCHEDULE[SCHEDULE_NAME]

    assert tuple(schedule_entry.get("args", ())) == ()
    assert dict(schedule_entry.get("kwargs", {})) == {}


def test_previous_day_analytics_snapshot_task_computes_previous_local_date(monkeypatch):
    calls = []

    def fake_compute_daily_analytics_snapshot(snapshot_date):
        calls.append(snapshot_date)

        return SimpleNamespace(
            id=uuid4(),
            date=snapshot_date,
            total_revenue=Decimal("0.00"),
            total_orders=0,
            new_customers=0,
            top_vendor_id=None,
            top_product_id=None,
        )

    monkeypatch.setattr(
        "apps.analytics.tasks.compute_daily_analytics_snapshot",
        fake_compute_daily_analytics_snapshot,
    )

    result = compute_previous_day_analytics_snapshot_task()

    expected_date = timezone.localdate() - timedelta(days=1)

    assert calls == [expected_date]
    assert result["date"] == expected_date.isoformat()
    assert result["total_revenue"] == "0.00"