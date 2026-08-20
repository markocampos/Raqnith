from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.CreateOrderView.as_view(), name="create"),
    path("<uuid:order_id>/", views.OrderStatusView.as_view(), name="status"),
    path("<uuid:order_id>/success/", views.OrderSuccessView.as_view(), name="success"),
    path("<uuid:order_id>/receipt/", views.OrderReceiptView.as_view(), name="receipt"),
]
