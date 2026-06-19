import factory

from apps.accounts.tests.factories import CustomerUserFactory
from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product
from apps.catalog.tests.factories import ProductFactory
from apps.inventory.models import InventoryRecord
from apps.inventory.tests.factories import InventoryRecordFactory


class CartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cart

    customer = factory.SubFactory(CustomerUserFactory)
    status = Cart.Status.ACTIVE


class ActiveProductFactory(ProductFactory):
    status = Product.Status.ACTIVE


class CartItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CartItem

    cart = factory.SubFactory(CartFactory)
    product = factory.SubFactory(ActiveProductFactory)
    variant = None
    quantity = 1

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        product = kwargs.get("product")
        variant = kwargs.get("variant")
        quantity = kwargs.get("quantity", 1)

        if product and not InventoryRecord.objects.filter(
            product=product,
            variant=variant,
        ).exists():
            InventoryRecordFactory(
                product=product,
                variant=variant,
                quantity_on_hand=max(quantity, 100),
                quantity_reserved=0,
                track_inventory=True,
                allow_backorder=False,
            )

        return super()._create(model_class, *args, **kwargs)