from django.urls import path

from . import views

app_name = "checkout"

urlpatterns = [
    path("", views.CheckoutView.as_view(), name="index"),
    path("<uuid:order_id>/", views.OrderCheckoutView.as_view(), name="order"),
]

