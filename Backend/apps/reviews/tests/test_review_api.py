from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.tests.factories import AdminUserFactory, CustomerUserFactory
from apps.catalog.tests.factories import ProductVariantFactory
from apps.reviews.models import Review
from apps.reviews.tests.factories import ReviewFactory
from apps.reviews.tests.test_review_models import (
    create_completed_order_with_variant_item,
    create_non_completed_order_with_variant_item,
)


pytestmark = pytest.mark.django_db


def api_client(user=None):
    client = APIClient()

    if user is not None:
        client.force_authenticate(user=user)

    return client


def get_results(response):
    data = response.data

    if isinstance(data, dict) and "results" in data:
        return data["results"]

    return data


def get_error_details(response):
    data = response.data

    if isinstance(data, dict) and "error" in data:
        return data["error"].get("details", {})

    return data


def assert_error_field(response, field_name):
    details = get_error_details(response)

    assert field_name in details


def decimal_value(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_unauthenticated_user_cannot_access_customer_reviews():
    client = api_client()

    response = client.get(reverse("customer-reviews-list"))

    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ]


def test_public_reviews_list_is_accessible_without_authentication():
    client = api_client()

    response = client.get(reverse("public-reviews-list"))

    assert response.status_code == status.HTTP_200_OK


def test_customer_can_create_review_for_completed_order_item():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 5,
            "body": "Excellent product.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert str(response.data["order_item"]) == str(order_item.id)
    assert str(response.data["reviewer"]) == str(customer.id)
    assert str(response.data["variant"]) == str(variant.id)
    assert response.data["rating"] == 5
    assert response.data["body"] == "Excellent product."
    assert response.data["is_visible"] is True

    assert Review.objects.filter(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
    ).exists()


def test_customer_cannot_create_review_for_non_completed_order_item():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_non_completed_order_with_variant_item(
        customer=customer,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 5,
            "body": "Order is not completed yet.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_item")


def test_customer_cannot_review_another_customer_order_item():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=other_customer,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 5,
            "body": "Not allowed.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "reviewer")


def test_customer_cannot_review_wrong_variant():
    customer = CustomerUserFactory()
    order, order_item, product, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    wrong_variant = ProductVariantFactory(
        product=product,
        price=Decimal("60.00"),
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(wrong_variant.id),
            "rating": 5,
            "body": "Wrong variant.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "variant")


def test_customer_cannot_review_same_order_item_twice():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    client = api_client(customer)

    first_response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 5,
            "body": "First review.",
        },
        format="json",
    )

    second_response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 4,
            "body": "Duplicate review.",
        },
        format="json",
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(second_response, "order_item")


def test_customer_cannot_create_review_with_rating_below_one():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 0,
            "body": "Invalid rating.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "rating")


def test_customer_cannot_create_review_with_rating_above_five():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 6,
            "body": "Invalid rating.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "rating")


def test_customer_cannot_create_review_with_blank_body():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-reviews-list"),
        {
            "order_item": str(order_item.id),
            "variant": str(variant.id),
            "rating": 5,
            "body": "",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "body")


def test_customer_lists_only_own_reviews():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )
    other_order, other_item, _, other_variant, _, _ = create_completed_order_with_variant_item(
        customer=other_customer,
    )

    own_review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
    )
    other_review = ReviewFactory(
        order_item=other_item,
        reviewer=other_customer,
        variant=other_variant,
        rating=4,
    )

    client = api_client(customer)

    response = client.get(reverse("customer-reviews-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(own_review.id) in ids
    assert str(other_review.id) not in ids


def test_customer_filters_reviews_by_variant_and_rating():
    customer = CustomerUserFactory()

    first_order, first_item, _, first_variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )
    second_order, second_item, _, second_variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    matching_review = ReviewFactory(
        order_item=first_item,
        reviewer=customer,
        variant=first_variant,
        rating=5,
    )
    other_review = ReviewFactory(
        order_item=second_item,
        reviewer=customer,
        variant=second_variant,
        rating=3,
    )

    client = api_client(customer)

    response = client.get(
        reverse("customer-reviews-list"),
        {
            "variant_id": str(first_variant.id),
            "rating": 5,
        },
    )

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(matching_review.id) in ids
    assert str(other_review.id) not in ids


def test_customer_can_retrieve_own_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
    )

    client = api_client(customer)

    response = client.get(
        reverse("customer-reviews-detail", kwargs={"pk": str(review.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(review.id)
    assert str(response.data["reviewer"]) == str(customer.id)


def test_customer_cannot_retrieve_other_customer_review():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=other_customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=other_customer,
        variant=variant,
        rating=5,
    )

    client = api_client(customer)

    response = client.get(
        reverse("customer-reviews-detail", kwargs={"pk": str(review.id)})
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_public_reviews_list_shows_visible_reviews_only():
    first_customer = CustomerUserFactory()
    first_order, first_item, _, first_variant, _, _ = create_completed_order_with_variant_item(
        customer=first_customer,
    )

    second_customer = CustomerUserFactory()
    second_order, second_item, _, second_variant, _, _ = create_completed_order_with_variant_item(
        customer=second_customer,
    )

    visible_review = ReviewFactory(
        order_item=first_item,
        reviewer=first_customer,
        variant=first_variant,
        rating=5,
        is_visible=True,
    )
    hidden_review = ReviewFactory(
        order_item=second_item,
        reviewer=second_customer,
        variant=second_variant,
        rating=1,
        is_visible=False,
    )

    client = api_client()

    response = client.get(reverse("public-reviews-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(visible_review.id) in ids
    assert str(hidden_review.id) not in ids


def test_public_can_retrieve_visible_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )

    client = api_client()

    response = client.get(
        reverse("public-reviews-detail", kwargs={"pk": str(review.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(review.id)
    assert response.data["rating"] == 5


def test_public_cannot_retrieve_hidden_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        is_visible=False,
    )

    client = api_client()

    response = client.get(
        reverse("public-reviews-detail", kwargs={"pk": str(review.id)})
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_public_summary_requires_variant_id():
    client = api_client()

    response = client.get(reverse("public-reviews-summary"))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "variant_id")


def test_public_summary_returns_404_for_unknown_variant():
    client = api_client()

    response = client.get(
        reverse("public-reviews-summary"),
        {
            "variant_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert_error_field(response, "variant_id")


def test_public_summary_returns_visible_rating_aggregate():
    first_customer = CustomerUserFactory()
    first_order, first_item, product, variant, _, _ = create_completed_order_with_variant_item(
        customer=first_customer,
    )

    second_customer = CustomerUserFactory()
    second_order, second_item, _, _, _, _ = create_completed_order_with_variant_item(
        customer=second_customer,
        product=product,
        variant=variant,
    )

    third_customer = CustomerUserFactory()
    third_order, third_item, _, _, _, _ = create_completed_order_with_variant_item(
        customer=third_customer,
        product=product,
        variant=variant,
    )

    ReviewFactory(
        order_item=first_item,
        reviewer=first_customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )
    ReviewFactory(
        order_item=second_item,
        reviewer=second_customer,
        variant=variant,
        rating=3,
        is_visible=True,
    )
    ReviewFactory(
        order_item=third_item,
        reviewer=third_customer,
        variant=variant,
        rating=1,
        is_visible=False,
    )

    client = api_client()

    response = client.get(
        reverse("public-reviews-summary"),
        {
            "variant_id": str(variant.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert str(response.data["variant_id"]) == str(variant.id)
    assert response.data["review_count"] == 2
    assert decimal_value(response.data["average_rating"]) == Decimal("4.00")


def test_admin_lists_all_reviews():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    first_order, first_item, _, first_variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )
    second_order, second_item, _, second_variant, _, _ = create_completed_order_with_variant_item(
        customer=other_customer,
    )

    first_review = ReviewFactory(
        order_item=first_item,
        reviewer=customer,
        variant=first_variant,
        rating=5,
    )
    second_review = ReviewFactory(
        order_item=second_item,
        reviewer=other_customer,
        variant=second_variant,
        rating=3,
    )

    client = api_client(admin)

    response = client.get(reverse("admin-reviews-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(first_review.id) in ids
    assert str(second_review.id) in ids


def test_admin_filters_reviews_by_visibility_and_rating():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    first_order, first_item, _, first_variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )
    second_order, second_item, _, second_variant, _, _ = create_completed_order_with_variant_item(
        customer=other_customer,
    )

    visible_review = ReviewFactory(
        order_item=first_item,
        reviewer=customer,
        variant=first_variant,
        rating=5,
        is_visible=True,
    )
    hidden_review = ReviewFactory(
        order_item=second_item,
        reviewer=other_customer,
        variant=second_variant,
        rating=1,
        is_visible=False,
    )

    client = api_client(admin)

    response = client.get(
        reverse("admin-reviews-list"),
        {
            "is_visible": "false",
            "rating": 1,
        },
    )

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(hidden_review.id) in ids
    assert str(visible_review.id) not in ids


def test_admin_can_retrieve_review():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
    )

    client = api_client(admin)

    response = client.get(
        reverse("admin-reviews-detail", kwargs={"pk": str(review.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(review.id)
    assert str(response.data["reviewer"]) == str(customer.id)


def test_customer_cannot_access_admin_reviews():
    customer = CustomerUserFactory()
    client = api_client(customer)

    response = client.get(reverse("admin-reviews-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_patch_review_visibility():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )

    client = api_client(admin)

    response = client.patch(
        reverse("admin-reviews-detail", kwargs={"pk": str(review.id)}),
        {
            "is_visible": False,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["is_visible"] is False

    review.refresh_from_db()

    assert review.is_visible is False


def test_admin_can_hide_review():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )

    client = api_client(admin)

    response = client.post(
        reverse("admin-reviews-hide", kwargs={"pk": str(review.id)}),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["is_visible"] is False

    review.refresh_from_db()

    assert review.is_visible is False


def test_admin_can_show_review():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        is_visible=False,
    )

    client = api_client(admin)

    response = client.post(
        reverse("admin-reviews-show", kwargs={"pk": str(review.id)}),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["is_visible"] is True

    review.refresh_from_db()

    assert review.is_visible is True


def test_admin_can_see_hidden_reviews():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=2,
        is_visible=False,
    )

    client = api_client(admin)

    response = client.get(
        reverse("admin-reviews-detail", kwargs={"pk": str(review.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(review.id)
    assert response.data["is_visible"] is False