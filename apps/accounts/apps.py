from django.apps import AppConfig
from django.contrib.auth.apps import AuthConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"


class VirtusAuthConfig(AuthConfig):
    """Human-readable label for Django's auth app in the admin index.

    Same app and models underneath, only the admin section heading changes:
    'Authentication and Authorization' reads like backend jargon.
    """

    verbose_name = "Access & Roles"
