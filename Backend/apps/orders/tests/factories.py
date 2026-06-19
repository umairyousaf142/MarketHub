from decimal import Decimal

import factory

from apps.accounts.tests.factories import CustomerUserFactory
from apps.catalog.tests.factories import ProductFactory
from apps.orders.models import Order, OrderItem, VendorOrder


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    customer = factory.SubFactory(CustomerUserFactory)
    source_cart = None

    status = Order.Status.PENDING
    payment_status = Order.PaymentStatus.PENDING
    inventory_status = Order.InventoryStatus.NOT_RESERVED

    subtotal_amount = Decimal("100.00")
    shipping_amount = Decimal("0.00")
    tax_amount = Decimal("0.00")
    discount_amount = Decimal("0.00")

    shipping_address = {}
    billing_address = {}
    notes = ""


class OrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    product = factory.SubFactory(ProductFactory)
    variant = None
    inventory_record = None

    vendor = factory.LazyAttribute(lambda obj: obj.product.vendor)

    product_name = ""
    product_sku = ""
    variant_name = ""
    variant_sku = ""
    vendor_store_name = ""

    quantity = 1
    unit_price = Decimal("100.00")


class VendorOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorOrder

    order = factory.SubFactory(OrderFactory)
    vendor = None
    status = VendorOrder.Status.PENDING

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        order = kwargs.get("order")

        if not order:
            order = OrderFactory()
            kwargs["order"] = order

        vendor = kwargs.get("vendor")

        if vendor is None:
            item = OrderItemFactory(order=order)
            kwargs["vendor"] = item.vendor
        else:
            if not order.items.filter(vendor=vendor).exists():
                product = ProductFactory(vendor=vendor)
                OrderItemFactory(order=order, product=product)

        return super()._create(model_class, *args, **kwargs)