from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.tests.factories import CustomerUserFactory
from apps.coupons.models import Coupon, CouponUsage


class CouponFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Coupon

    code = factory.Sequence(lambda n: f"COUPON{n}")
    type = Coupon.Type.FIXED
    value = Decimal("10.00")
    max_discount = None
    scope = Coupon.Scope.GLOBAL
    vendor = None
    category = None
    min_order_value = Decimal("0.00")
    usage_limit = None
    per_user_limit = 1
    valid_from = factory.LazyFunction(lambda: timezone.now() - timedelta(days=1))
    valid_until = factory.LazyFunction(lambda: timezone.now() + timedelta(days=30))
    is_active = True


class CouponUsageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CouponUsage

    coupon = factory.SubFactory(CouponFactory)
    user = factory.SubFactory(CustomerUserFactory)