import factory

from apps.accounts.tests.factories import CustomerUserFactory
from apps.notifications.models import Notification


class NotificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Notification

    user = factory.SubFactory(CustomerUserFactory)
    type = Notification.Type.ORDER_CREATED
    channel = Notification.Channel.IN_APP
    title = "Order created"
    body = "Your order has been created."
    is_read = False