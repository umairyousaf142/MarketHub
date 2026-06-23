import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.cart.models import CartItem
from apps.catalog.models import Category, Product
from apps.orders.models import Order
from apps.vendors.models import Vendor
from core.services.cache_service import (
    invalidate_bestsellers_global_cache,
    invalidate_cart_cache,
    invalidate_category_tree_cache,
    invalidate_product_detail_cache,
    invalidate_vendor_profile_cache,
)


logger = logging.getLogger(__name__)


@receiver(
    post_save,
    sender=Product,
    dispatch_uid="invalidate_product_detail_cache_on_product_save",
)
def invalidate_product_cache_on_save(sender, instance, **kwargs):
    invalidate_product_detail_cache(instance.id)


@receiver(
    post_save,
    sender=Category,
    dispatch_uid="invalidate_category_tree_cache_on_category_save",
)
def invalidate_category_cache_on_save(sender, instance, **kwargs):
    invalidate_category_tree_cache()


@receiver(
    post_delete,
    sender=Category,
    dispatch_uid="invalidate_category_tree_cache_on_category_delete",
)
def invalidate_category_cache_on_delete(sender, instance, **kwargs):
    invalidate_category_tree_cache()


@receiver(
    post_save,
    sender=Vendor,
    dispatch_uid="invalidate_vendor_profile_cache_on_vendor_save",
)
def invalidate_vendor_cache_on_save(sender, instance, **kwargs):
    invalidate_vendor_profile_cache(instance.id)


@receiver(
    post_save,
    sender=Order,
    dispatch_uid="invalidate_bestsellers_global_cache_on_order_save",
)
def invalidate_bestsellers_cache_on_order_save(sender, instance, created, **kwargs):
    if created:
        invalidate_bestsellers_global_cache()


@receiver(
    post_save,
    sender=CartItem,
    dispatch_uid="invalidate_cart_cache_on_cart_item_save",
)
def invalidate_cart_cache_on_cart_item_save(sender, instance, **kwargs):
    cart = getattr(instance, "cart", None)

    if cart and getattr(cart, "session_key", None):
        invalidate_cart_cache(cart.session_key)


@receiver(
    post_delete,
    sender=CartItem,
    dispatch_uid="invalidate_cart_cache_on_cart_item_delete",
)
def invalidate_cart_cache_on_cart_item_delete(sender, instance, **kwargs):
    cart = getattr(instance, "cart", None)

    if cart and getattr(cart, "session_key", None):
        invalidate_cart_cache(cart.session_key)