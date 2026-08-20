from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = "test-only-secret-key"

# Fast, isolated tests. PayMongo values are stubbed; real credentials are never
# used in the test environment.
PAYMONGO_PUBLIC_KEY = "pk_test_stub"
PAYMONGO_SECRET_KEY = "sk_test_stub"
PAYMONGO_WEBHOOK_SECRET = "whsec_test_stub"
