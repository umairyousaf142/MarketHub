"""
Central signal registry.
All custom Django signals are defined here so every app
imports from one place.

Usage:
    from core.events import order_created
    order_created.send(sender=Order, instance=order)
"""
from django.dispatch import Signal

# ── Order signals ─────────────────────────────────────────────────────────────
order_created   = Signal()
order_paid      = Signal()
order_cancelled = Signal()
order_refunded  = Signal()

# ── Vendor signals ────────────────────────────────────────────────────────────
vendor_approved = Signal()
vendor_suspended = Signal()

# ── Payment signals ───────────────────────────────────────────────────────────
payment_success = Signal()
payment_failed  = Signal()

# ── Inventory signals ─────────────────────────────────────────────────────────
low_stock_alert = Signal()
