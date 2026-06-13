import factory
from django.contrib.auth import get_user_model

from apps.accounts.models import Address

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    role = User.Role.CUSTOMER
    is_active = True
    is_verified = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        raw_password = extracted or "StrongPass123!"
        self.set_password(raw_password)

        if create:
            self.save(update_fields=["password"])


class AdminUserFactory(UserFactory):
    role = User.Role.ADMIN
    is_staff = True
    is_superuser = True


class VendorUserFactory(UserFactory):
    role = User.Role.VENDOR


class CustomerUserFactory(UserFactory):
    role = User.Role.CUSTOMER


class AddressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Address

    user = factory.SubFactory(CustomerUserFactory)
    label = factory.Sequence(lambda n: f"Home {n}")
    street = factory.Sequence(lambda n: f"Street {n}")
    city = "Lahore"
    country = "Pakistan"
    is_default = False