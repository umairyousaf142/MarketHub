from decimal import Decimal

import factory
from django.utils import timezone

from apps.analytics.models import AnalyticsSnapshot


class AnalyticsSnapshotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnalyticsSnapshot

    date = factory.LazyFunction(timezone.localdate)
    total_revenue = Decimal("0.00")
    total_orders = 0
    new_customers = 0
    top_vendor = None
    top_product = None