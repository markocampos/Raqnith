from django.urls import path

from . import views

app_name = "checkout"

urlpatterns = [
    path("", views.CheckoutView.as_view(), name="index"),
    path("coupon/apply/", views.ApplyCouponView.as_view(), name="apply_coupon"),
    path("coupon/remove/", views.RemoveCouponView.as_view(), name="remove_coupon"),
    path("<uuid:order_id>/", views.OrderCheckoutView.as_view(), name="order"),
]
