from django.urls import path

from . import views

app_name = "seller"

urlpatterns = [
    path("apply/", views.SellerApplyView.as_view(), name="apply"),
]
