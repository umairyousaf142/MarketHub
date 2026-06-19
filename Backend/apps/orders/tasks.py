from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from apps.orders.models import Order, VendorOrder


def get_default_from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@markethub.local")


def get_admin_notification_emails():
    configured_emails = getattr(settings, "MARKETHUB_ADMIN_NOTIFICATION_EMAILS", None)

    if configured_emails:
        return list(configured_emails)

    admins = getattr(settings, "ADMINS", [])

    return [email for _, email in admins]


def money(value):
    return f"{Decimal(str(value)).quantize(Decimal('0.01'))}"

def get_user_display_name(user):
    first_name = getattr(user, "first_name", "")
    full_name = getattr(user, "full_name", "")
    name = getattr(user, "name", "")

    display_name = first_name or full_name or name or getattr(user, "email", "")

    return display_name or str(user)


def get_order(order_id):
    return (
        Order.objects.select_related(
            "customer",
            "source_cart",
        )
        .prefetch_related(
            "items",
            "items__vendor",
            "items__product",
            "items__variant",
            "items__inventory_record",
            "vendor_orders",
            "vendor_orders__vendor",
        )
        .get(id=order_id)
    )


def get_vendor_order(vendor_order_id):
    return (
        VendorOrder.objects.select_related(
            "order",
            "order__customer",
            "vendor",
            "vendor__user",
        )
        .prefetch_related(
            "order__items",
            "order__items__vendor",
            "order__items__product",
            "order__items__variant",
            "order__items__inventory_record",
        )
        .get(id=vendor_order_id)
    )


def build_order_items_text(order):
    lines = []

    for item in order.items.all():
        title = item.product_name

        if item.variant_name:
            title = f"{title} - {item.variant_name}"

        lines.append(
            f"- {title} | Qty: {item.quantity} | "
            f"Unit: {money(item.unit_price)} | Line total: {money(item.line_total)}"
        )

    return "\n".join(lines)


def build_vendor_order_items_text(vendor_order):
    lines = []

    items = vendor_order.order.items.filter(vendor=vendor_order.vendor)

    for item in items:
        title = item.product_name

        if item.variant_name:
            title = f"{title} - {item.variant_name}"

        lines.append(
            f"- {title} | Qty: {item.quantity} | "
            f"Unit: {money(item.unit_price)} | Line total: {money(item.line_total)}"
        )

    return "\n".join(lines)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_order_confirmation_email_task(self, order_id):
    order = get_order(order_id)

    customer_email = order.customer.email

    if not customer_email:
        return {
            "sent": False,
            "reason": "Customer email is missing.",
            "order_id": str(order.id),
        }

    subject = f"Order Confirmation - {order.order_number}"

    body = (
        f"Hi {get_user_display_name(order.customer)},\n\n"
        f"Thank you for your order.\n\n"
        f"Order Number: {order.order_number}\n"
        f"Order Status: {order.status}\n"
        f"Payment Status: {order.payment_status}\n"
        f"Inventory Status: {order.inventory_status}\n\n"
        f"Items:\n"
        f"{build_order_items_text(order)}\n\n"
        f"Subtotal: {money(order.subtotal_amount)}\n"
        f"Shipping: {money(order.shipping_amount)}\n"
        f"Tax: {money(order.tax_amount)}\n"
        f"Discount: {money(order.discount_amount)}\n"
        f"Total: {money(order.total_amount)}\n\n"
        f"We will notify you when your order status changes.\n\n"
        f"MarketHub Team"
    )

    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": sent_count > 0,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def notify_vendors_new_order_task(self, order_id):
    order = get_order(order_id)

    results = []

    for vendor_order in order.vendor_orders.select_related("vendor", "vendor__user"):
        vendor_email = vendor_order.vendor.user.email

        if not vendor_email:
            results.append(
                {
                    "sent": False,
                    "reason": "Vendor email is missing.",
                    "vendor_order_id": str(vendor_order.id),
                }
            )
            continue

        subject = f"New Vendor Order - {order.order_number}"

        body = (
            f"Hi {vendor_order.vendor.store_name},\n\n"
            f"You have received a new order.\n\n"
            f"Order Number: {order.order_number}\n"
            f"Vendor Order ID: {vendor_order.id}\n"
            f"Status: {vendor_order.status}\n\n"
            f"Items:\n"
            f"{build_vendor_order_items_text(vendor_order)}\n\n"
            f"Subtotal: {money(vendor_order.subtotal_amount)}\n"
            f"Total Quantity: {vendor_order.total_quantity}\n\n"
            f"Please review this order in your vendor dashboard.\n\n"
            f"MarketHub Team"
        )

        sent_count = send_mail(
            subject=subject,
            message=body,
            from_email=get_default_from_email(),
            recipient_list=[vendor_email],
            fail_silently=False,
        )

        results.append(
            {
                "sent": sent_count > 0,
                "vendor_order_id": str(vendor_order.id),
                "recipient": vendor_email,
            }
        )

    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "results": results,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def notify_admin_new_order_task(self, order_id):
    order = get_order(order_id)

    admin_emails = get_admin_notification_emails()

    if not admin_emails:
        return {
            "sent": False,
            "reason": "No admin notification emails configured.",
            "order_id": str(order.id),
        }

    subject = f"New Order Placed - {order.order_number}"

    body = (
        f"A new order has been placed.\n\n"
        f"Order Number: {order.order_number}\n"
        f"Customer: {order.customer.email}\n"
        f"Status: {order.status}\n"
        f"Payment Status: {order.payment_status}\n"
        f"Inventory Status: {order.inventory_status}\n"
        f"Total: {money(order.total_amount)}\n"
        f"Vendor Orders: {order.vendor_orders.count()}\n"
        f"Items: {order.item_count}\n"
        f"Total Quantity: {order.total_quantity}\n"
    )

    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=get_default_from_email(),
        recipient_list=admin_emails,
        fail_silently=False,
    )

    return {
        "sent": sent_count > 0,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipients": admin_emails,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_order_paid_email_task(self, order_id):
    order = get_order(order_id)

    customer_email = order.customer.email

    if not customer_email:
        return {
            "sent": False,
            "reason": "Customer email is missing.",
            "order_id": str(order.id),
        }

    subject = f"Payment Confirmed - {order.order_number}"

    body = (
        f"Hi {get_user_display_name(order.customer)},\n\n"
        f"Your payment has been confirmed.\n\n"
        f"Order Number: {order.order_number}\n"
        f"Order Status: {order.status}\n"
        f"Payment Status: {order.payment_status}\n"
        f"Inventory Status: {order.inventory_status}\n"
        f"Total Paid: {money(order.total_amount)}\n\n"
        f"Your order is now confirmed.\n\n"
        f"MarketHub Team"
    )

    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": sent_count > 0,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_order_cancelled_email_task(self, order_id):
    order = get_order(order_id)

    customer_email = order.customer.email

    if not customer_email:
        return {
            "sent": False,
            "reason": "Customer email is missing.",
            "order_id": str(order.id),
        }

    subject = f"Order Cancelled - {order.order_number}"

    body = (
        f"Hi {get_user_display_name(order.customer)},\n\n"
        f"Your order has been cancelled.\n\n"
        f"Order Number: {order.order_number}\n"
        f"Order Status: {order.status}\n"
        f"Payment Status: {order.payment_status}\n"
        f"Inventory Status: {order.inventory_status}\n\n"
        f"MarketHub Team"
    )

    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": sent_count > 0,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def notify_vendors_order_cancelled_task(self, order_id):
    order = get_order(order_id)

    results = []

    for vendor_order in order.vendor_orders.select_related("vendor", "vendor__user"):
        vendor_email = vendor_order.vendor.user.email

        if not vendor_email:
            results.append(
                {
                    "sent": False,
                    "reason": "Vendor email is missing.",
                    "vendor_order_id": str(vendor_order.id),
                }
            )
            continue

        subject = f"Order Cancelled - {order.order_number}"

        body = (
            f"Hi {vendor_order.vendor.store_name},\n\n"
            f"The following order has been cancelled.\n\n"
            f"Order Number: {order.order_number}\n"
            f"Vendor Order ID: {vendor_order.id}\n"
            f"Vendor Order Status: {vendor_order.status}\n\n"
            f"MarketHub Team"
        )

        sent_count = send_mail(
            subject=subject,
            message=body,
            from_email=get_default_from_email(),
            recipient_list=[vendor_email],
            fail_silently=False,
        )

        results.append(
            {
                "sent": sent_count > 0,
                "vendor_order_id": str(vendor_order.id),
                "recipient": vendor_email,
            }
        )

    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "results": results,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_vendor_order_status_update_email_task(self, vendor_order_id):
    vendor_order = get_vendor_order(vendor_order_id)

    order = vendor_order.order
    customer_email = order.customer.email

    if not customer_email:
        return {
            "sent": False,
            "reason": "Customer email is missing.",
            "vendor_order_id": str(vendor_order.id),
        }

    subject = f"Order Status Updated - {order.order_number}"

    body = (
        f"Hi {get_user_display_name(order.customer)},\n\n"
        f"One part of your order has been updated.\n\n"
        f"Order Number: {order.order_number}\n"
        f"Vendor: {vendor_order.vendor.store_name}\n"
        f"Vendor Order Status: {vendor_order.status}\n"
        f"Main Order Status: {order.status}\n\n"
        f"MarketHub Team"
    )

    sent_count = send_mail(
        subject=subject,
        message=body,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": sent_count > 0,
        "vendor_order_id": str(vendor_order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def check_low_stock_after_order_task(self, order_id):
    order = get_order(order_id)

    admin_emails = get_admin_notification_emails()
    alerts = []

    for item in order.items.select_related(
        "inventory_record",
        "vendor",
        "vendor__user",
    ):
        inventory_record = item.inventory_record

        if not inventory_record:
            continue

        if not inventory_record.track_inventory:
            continue

        if not inventory_record.is_low_stock:
            continue

        title = item.product_name

        if item.variant_name:
            title = f"{title} - {item.variant_name}"

        vendor_email = item.vendor.user.email

        subject = f"Low Stock Alert - {title}"

        body = (
            f"Low stock alert triggered after order {order.order_number}.\n\n"
            f"Product: {title}\n"
            f"Vendor: {item.vendor.store_name}\n"
            f"Quantity On Hand: {inventory_record.quantity_on_hand}\n"
            f"Quantity Reserved: {inventory_record.quantity_reserved}\n"
            f"Available Quantity: {inventory_record.available_quantity}\n"
            f"Low Stock Threshold: {inventory_record.low_stock_threshold}\n"
        )

        recipients = []

        if vendor_email:
            recipients.append(vendor_email)

        recipients.extend(admin_emails)

        recipients = list(dict.fromkeys(recipients))

        if not recipients:
            alerts.append(
                {
                    "sent": False,
                    "reason": "No recipient configured.",
                    "inventory_record_id": str(inventory_record.id),
                }
            )
            continue

        sent_count = send_mail(
            subject=subject,
            message=body,
            from_email=get_default_from_email(),
            recipient_list=recipients,
            fail_silently=False,
        )

        alerts.append(
            {
                "sent": sent_count > 0,
                "inventory_record_id": str(inventory_record.id),
                "product": title,
                "recipients": recipients,
            }
        )

    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "alerts": alerts,
    }