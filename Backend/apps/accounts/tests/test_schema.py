import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_openapi_schema_endpoint_is_available(api_client):
    url = reverse("schema")

    response = api_client.get(url)

    assert response.status_code == 200
    assert b"openapi" in response.content.lower()


@pytest.mark.django_db
def test_swagger_docs_endpoint_is_available(api_client):
    url = reverse("swagger-ui")

    response = api_client.get(url)

    assert response.status_code == 200