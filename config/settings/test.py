from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = "test-only-secret-key"

# Fast, isolated tests. PayMongo values are stubbed; real credentials are never
# used in the test environment.
PAYMONGO_PUBLIC_KEY = "pk_test_stub"
PAYMONGO_SECRET_KEY = "sk_test_stub"
PAYMONGO_WEBHOOK_SECRET = "whsec_test_stub"

# Deterministic email assertions: every test can inspect django.core.mail.outbox.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Ops alerts land somewhere inspectable during tests. Reset ADMINS too —
# base.py builds it from the real .env, and it would otherwise leak in.
ADMIN_NOTIFY_EMAIL = "ops@test.local"
ADMINS = []
