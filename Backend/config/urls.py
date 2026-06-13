from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

API_PREFIX = 'api/v1'

urlpatterns = [
    path('admin/', admin.site.urls),

    # ── App routes — uncomment as you create each app ─────────────────────────
    # path(f'{API_PREFIX}/auth/',          include('apps.accounts.urls')),
    # path(f'{API_PREFIX}/vendors/',       include('apps.vendors.urls')),
    # path(f'{API_PREFIX}/catalog/',       include('apps.catalog.urls')),
    # path(f'{API_PREFIX}/inventory/',     include('apps.inventory.urls')),
    # path(f'{API_PREFIX}/cart/',          include('apps.cart.urls')),
    # path(f'{API_PREFIX}/orders/',        include('apps.orders.urls')),
    # path(f'{API_PREFIX}/payments/',      include('apps.payments.urls')),
    # path(f'{API_PREFIX}/coupons/',       include('apps.coupons.urls')),
    # path(f'{API_PREFIX}/reviews/',       include('apps.reviews.urls')),
    # path(f'{API_PREFIX}/notifications/', include('apps.notifications.urls')),
    # path(f'{API_PREFIX}/analytics/',     include('apps.analytics.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
