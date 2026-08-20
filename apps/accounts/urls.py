from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("privacy/", views.PrivacyPolicyView.as_view(), name="privacy"),
    path("terms/", views.TermsView.as_view(), name="terms"),
]
