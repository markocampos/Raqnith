from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.view_cart, name="detail"),
    path("add/", views.add_to_cart, name="add"),
    path("remove/<int:item_id>/", views.remove_from_cart, name="remove"),
]
