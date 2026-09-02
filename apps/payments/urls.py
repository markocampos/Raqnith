from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("intents/", views.CreateIntentView.as_view(), name="intents"),
    path("<uuid:attempt_id>/status/", views.PaymentStatusView.as_view(), name="status"),
    path("<uuid:attempt_id>/retry/", views.RetryPaymentView.as_view(), name="retry"),
    path("return/", views.PaymentReturnView.as_view(), name="return"),
    path("webhooks/paymongo/", views.PayMongoWebhookView.as_view(), name="webhook"),
    path("webhook/paymongo/", views.PayMongoWebhookView.as_view(), name="webhook_singular"),
]
