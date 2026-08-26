from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.CreateOrderView.as_view(), name="create"),
    path("track/", views.TrackOrderView.as_view(), name="track"),
    path("a/<str:token>/", views.OrderAccessView.as_view(), name="access"),
    path("<uuid:order_id>/resume/", views.OrderResumeView.as_view(), name="resume"),
    path("<uuid:order_id>/", views.OrderStatusView.as_view(), name="status"),
    path("<uuid:order_id>/success/", views.OrderSuccessView.as_view(), name="success"),
    path("<uuid:order_id>/receipt/", views.OrderReceiptView.as_view(), name="receipt"),
    path(
        "<uuid:order_id>/receipt.pdf/",
        views.OrderReceiptPdfView.as_view(),
        name="receipt_pdf",
    ),
    path(
        "<uuid:order_id>/files/<uuid:file_id>/",
        views.OrderFileView.as_view(),
        name="download_file",
    ),
]
