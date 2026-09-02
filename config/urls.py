from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

from apps.accounts.views import PrivacyPolicyView, TermsView
from apps.payments.views import PayMongoWebhookView

from .admin import admin_site

urlpatterns = [
    path("admin/", admin_site.urls),
    path("", include("apps.catalog.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("cart/", include("apps.cart.urls")),
    path("checkout/", include("apps.checkout.urls")),
    path("payments/", include("apps.payments.urls")),
    path("orders/", include("apps.orders.urls")),
    path("sell/", include("apps.seller.urls")),
    # Top-level legal and info routes:
    path("privacy/", PrivacyPolicyView.as_view(), name="privacy_policy"),
    path("privacy-policy/", PrivacyPolicyView.as_view(), name="privacy_policy_alias"),
    path("terms/", TermsView.as_view(), name="terms_of_service"),
    # PayMongo webhook routes:
    path("webhook/paymongo/", PayMongoWebhookView.as_view(), name="webhook_alias_1"),
    path("webhooks/paymongo/", PayMongoWebhookView.as_view(), name="webhook_alias_2"),
]

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
