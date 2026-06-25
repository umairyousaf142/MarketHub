from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.analytics.services import (
    compute_daily_analytics_snapshot,
    serialize_analytics_snapshot,
)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def compute_daily_analytics_snapshot_task(self, snapshot_date=None):
    snapshot = compute_daily_analytics_snapshot(snapshot_date)

    return serialize_analytics_snapshot(snapshot)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def compute_previous_day_analytics_snapshot_task(self):
    snapshot_date = timezone.localdate() - timedelta(days=1)

    snapshot = compute_daily_analytics_snapshot(snapshot_date)

    return serialize_analytics_snapshot(snapshot)