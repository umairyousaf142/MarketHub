from .base import *

DEBUG = True

ALLOWED_HOSTS = ['*']

# ─── Dev-only apps ────────────────────────────────────────────────────────────
INSTALLED_APPS += []

# ─── Django debug toolbar (install separately: pip install django-debug-toolbar)
# INSTALLED_APPS += ['debug_toolbar']
# MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
# INTERNAL_IPS = ['127.0.0.1']

# ─── Email — print to console in dev ─────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ─── CORS — allow all in dev ──────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} — {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
    'loggers': {
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'DEBUG',   # Shows every SQL query in dev
            'propagate': False,
        },
    },
}
