from django.apps import AppConfig


class VendorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.vendors"
    label = "vendors"

    def ready(self):
        from core.events import cache_invalidation  # noqa: F401
