from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)


API_PREFIX = 'api/v1'

urlpatterns = [
    path('admin/', admin.site.urls),

    # ── App routes — uncomment as you create each app ─────────────────────────
    path(f'{API_PREFIX}/auth/',          include('apps.accounts.urls')),
    path(f'{API_PREFIX}/vendors/',       include('apps.vendors.urls')),
    # path(f'{API_PREFIX}/catalog/',       include('apps.catalog.urls')),
    # path(f'{API_PREFIX}/inventory/',     include('apps.inventory.urls')),
    # path(f'{API_PREFIX}/cart/',          include('apps.cart.urls')),
    # path(f'{API_PREFIX}/orders/',        include('apps.orders.urls')),
    # path(f'{API_PREFIX}/payments/',      include('apps.payments.urls')),
    # path(f'{API_PREFIX}/coupons/',       include('apps.coupons.urls')),
    # path(f'{API_PREFIX}/reviews/',       include('apps.reviews.urls')),
    # path(f'{API_PREFIX}/notifications/', include('apps.notifications.urls')),
    # path(f'{API_PREFIX}/analytics/',     include('apps.analytics.urls')),


    # ── API Documentation ────────────────────────────────────────────────────
    path(f"{API_PREFIX}/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        f"{API_PREFIX}/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        f"{API_PREFIX}/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
