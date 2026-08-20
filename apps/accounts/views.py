from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.forms import (
    ChangePasswordForm,
    UserLoginForm,
    UserProfileForm,
    UserRegistrationForm,
)
from apps.cart.services import merge_cart_on_login
from apps.orders.models import Order


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("accounts:profile")
        form = UserRegistrationForm()
        next_url = request.GET.get("next", "")
        return render(request, "accounts/register.html", {"form": form, "next": next_url})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("accounts:profile")

        form = UserRegistrationForm(request.POST)
        next_url = request.POST.get("next") or request.GET.get("next") or ""

        if form.is_valid():
            old_session_key = request.session.session_key
            user = form.save()
            login(request, user)
            merge_cart_on_login(request, user, old_session_key=old_session_key)

            greeting = user.first_name or user.username
            messages.success(request, f"Welcome to Raqnith, {greeting}! Your account is ready.")

            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect("accounts:profile")

        return render(
            request,
            "accounts/register.html",
            {"form": form, "next": next_url},
            status=400,
        )


class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("accounts:profile")
        form = UserLoginForm(request=request)
        next_url = request.GET.get("next", "")
        return render(request, "accounts/login.html", {"form": form, "next": next_url})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("accounts:profile")

        form = UserLoginForm(request=request, data=request.POST)
        next_url = request.POST.get("next") or request.GET.get("next") or ""

        if form.is_valid():
            old_session_key = request.session.session_key
            user = form.get_user()
            login(request, user)
            merge_cart_on_login(request, user, old_session_key=old_session_key)

            greeting = user.first_name or user.username
            messages.success(request, f"Welcome back, {greeting}!")

            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect("accounts:profile")

        return render(
            request,
            "accounts/login.html",
            {"form": form, "next": next_url},
            status=400,
        )


class LogoutView(View):
    def get(self, request):
        return self._do_logout(request)

    def post(self, request):
        return self._do_logout(request)

    def _do_logout(self, request):
        if request.user.is_authenticated:
            logout(request)
            messages.info(request, "You've been safely signed out. See you next time!")
        return redirect("catalog:home")


class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        form = UserProfileForm(instance=request.user)
        return self._render_profile(request, form)

    def post(self, request):
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile details have been updated successfully.")
            return redirect("accounts:profile")
        return self._render_profile(request, form, status=400)

    def _render_profile(self, request, form, status=200):
        orders = Order.objects.filter(user=request.user).order_by("-created_at")
        total_orders = orders.count()
        paid_orders = orders.filter(status=Order.Status.PAID)
        paid_count = paid_orders.count()
        total_spent_cents = paid_orders.aggregate(total=Sum("total_amount"))["total"] or 0

        context = {
            "form": form,
            "orders": orders,
            "total_orders": total_orders,
            "paid_orders_count": paid_count,
            "total_spent_cents": total_spent_cents,
        }
        return render(request, "accounts/profile.html", context, status=status)


class SettingsView(LoginRequiredMixin, View):
    def get(self, request):
        password_form = ChangePasswordForm(user=request.user)
        return render(request, "accounts/settings.html", {"password_form": password_form})

    def post(self, request):
        action = request.POST.get("action", "change_password")
        if action == "change_password":
            password_form = ChangePasswordForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save(request=request)
                messages.success(request, "Your password has been changed successfully.")
                return redirect("accounts:settings")
            return render(
                request,
                "accounts/settings.html",
                {"password_form": password_form},
                status=400,
            )

        elif action == "update_preferences":
            messages.success(request, "Your account preferences have been saved.")
            return redirect("accounts:settings")

        return redirect("accounts:settings")


class PrivacyPolicyView(TemplateView):
    template_name = "accounts/privacy_policy.html"


class TermsView(TemplateView):
    template_name = "accounts/terms.html"
