import factory

from apps.reviews.models import Review


class ReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Review

    rating = 5
    body = "Excellent product."
    is_visible = True