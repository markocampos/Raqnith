from decouple import config

from .base import *  # noqa: F401,F403

SECRET_KEY = config("DJANGO_SECRET_KEY")

DEBUG = False

ALLOWED_HOSTS = [
    h.strip()
    for h in config(
        "DJANGO_ALLOWED_HOSTS",
        default="virtusdigital.store,www.virtusdigital.store,localhost,127.0.0.1",
    ).split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in config(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        default="https://virtusdigital.store,https://www.virtusdigital.store,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]
BASE_URL = config("DJANGO_BASE_URL", default="https://virtusdigital.store")

SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", default=True, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = config("DJANGO_HSTS_SECONDS", default=3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

X_FRAME_OPTIONS = "DENY"

# PayMongo keys are required in production. Failing loudly here prevents a
# silent misconfiguration from reaching live traffic.
PAYMONGO_PUBLIC_KEY = config("PAYMONGO_PUBLIC_KEY")
PAYMONGO_SECRET_KEY = config("PAYMONGO_SECRET_KEY")
PAYMONGO_WEBHOOK_SECRET = config("PAYMONGO_WEBHOOK_SECRET")
