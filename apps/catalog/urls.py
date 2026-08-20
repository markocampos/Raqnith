from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.LandingPageView.as_view(), name="home"),
    path("landing/", views.LandingPageView.as_view(), name="landing"),
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/<slug:slug>/", views.ProductDetailView.as_view(), name="product_detail"),
]
