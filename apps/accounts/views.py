from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView
from django_ratelimit.decorators import ratelimit

from apps.accounts.forms import (
    ChangePasswordForm,
    UserLoginForm,
    UserProfileForm,
    UserRegistrationForm,
)
from apps.cart.services import merge_cart_on_login
from apps.orders.models import Order
from apps.payments.models import PaymentAttempt


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("accounts:profile")
        form = UserRegistrationForm()
        next_url = request.GET.get("next", "")
        return render(request, "accounts/register.html", {"form": form, "next": next_url})

    @method_decorator(ratelimit(key="ip", rate="5/h", block=False))
    def post(self, request):
        if getattr(request, "limited", False):
            messages.error(request, "Too many registration attempts. Please try again later.")
            form = UserRegistrationForm()
            next_url = request.POST.get("next") or request.GET.get("next") or ""
            return render(
                request, "accounts/register.html", {"form": form, "next": next_url}, status=429
            )

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
            messages.success(request, f"Welcome to Virtus, {greeting}! Your account is ready.")

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

    @method_decorator(ratelimit(key="ip", rate="10/m", block=False))
    def post(self, request):
        if getattr(request, "limited", False):
            messages.error(request, "Too many login attempts. Please try again in a minute.")
            form = UserLoginForm(request=request)
            next_url = request.POST.get("next") or request.GET.get("next") or ""
            return render(
                request, "accounts/login.html", {"form": form, "next": next_url}, status=429
            )

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
        return self._render_profile(request)

    def _render_profile(self, request, status=200):
        # 1. Purge unpaid orders older than 30 days (1 month) to free storage
        Order.purge_unpaid_overdue()

        # 2. Fetch user orders and check expiration
        orders = list(
            Order.objects.filter(user=request.user)
            .prefetch_related("items")
            .order_by("-created_at")
        )
        for order in orders:
            order.expire_if_overdue()

        # 3. Ensure only the single newest pending order stays active; cancel older pending ones
        pending_orders = [o for o in orders if o.status == Order.Status.PENDING_PAYMENT]
        if len(pending_orders) > 1:
            for older_pending in pending_orders[1:]:
                older_pending.transition_to(Order.Status.CANCELLED)
                PaymentAttempt.objects.filter(
                    order=older_pending,
                    status__in=[
                        PaymentAttempt.Status.CREATED,
                        PaymentAttempt.Status.AWAITING_METHOD,
                        PaymentAttempt.Status.AWAITING_ACTION,
                    ],
                ).update(status=PaymentAttempt.Status.CANCELLED)

        total_orders = len(orders)
        paid_orders = [o for o in orders if o.status in (Order.Status.PAID, Order.Status.FULFILLED)]
        paid_count = len(paid_orders)
        pending_count = len([o for o in orders if o.status == Order.Status.PENDING_PAYMENT])
        cancelled_count = len(
            [o for o in orders if o.status in (Order.Status.CANCELLED, Order.Status.PAYMENT_FAILED)]
        )
        total_spent_cents = sum(o.total_amount for o in paid_orders)

        # 4. Status Filtering (All, Paid, Pending, Expired)
        status_filter = request.GET.get("status", "all").lower().strip()
        if status_filter == "paid":
            filtered_orders = paid_orders
        elif status_filter == "pending":
            filtered_orders = [o for o in orders if o.status == Order.Status.PENDING_PAYMENT]
        elif status_filter in ("cancelled", "expired"):
            filtered_orders = [
                o
                for o in orders
                if o.status in (Order.Status.CANCELLED, Order.Status.PAYMENT_FAILED)
            ]
        else:
            status_filter = "all"
            filtered_orders = orders

        # 5. Pagination (6 orders per page)
        paginator = Paginator(filtered_orders, 6)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "orders": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "status_filter": status_filter,
            "total_orders": total_orders,
            "paid_orders_count": paid_count,
            "pending_orders_count": pending_count,
            "cancelled_orders_count": cancelled_count,
            "pending_order_id": pending_orders[0].id if pending_orders else None,
            "total_spent_cents": total_spent_cents,
        }
        return render(request, "accounts/profile.html", context, status=status)


class SettingsView(LoginRequiredMixin, View):
    def get(self, request):
        profile_form = UserProfileForm(instance=request.user)
        password_form = ChangePasswordForm(user=request.user)
        paid_orders_count = Order.objects.filter(
            user=request.user,
            status__in=[Order.Status.PAID, Order.Status.FULFILLED],
        ).count()
        return render(
            request,
            "accounts/settings.html",
            {
                "profile_form": profile_form,
                "password_form": password_form,
                "paid_orders_count": paid_orders_count,
                "active_tab": request.GET.get("tab", "profile"),
            },
        )

    def post(self, request):
        action = request.POST.get("action", "change_password")
        paid_orders_count = Order.objects.filter(
            user=request.user,
            status__in=[Order.Status.PAID, Order.Status.FULFILLED],
        ).count()

        if action == "update_profile":
            profile_form = UserProfileForm(request.POST, instance=request.user)
            password_form = ChangePasswordForm(user=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Your personal details have been updated successfully.")
                return redirect(reverse("accounts:settings") + "?tab=profile")
            return render(
                request,
                "accounts/settings.html",
                {
                    "profile_form": profile_form,
                    "password_form": password_form,
                    "paid_orders_count": paid_orders_count,
                    "active_tab": "profile",
                },
                status=400,
            )

        elif action == "change_password":
            profile_form = UserProfileForm(instance=request.user)
            password_form = ChangePasswordForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save(request=request)
                messages.success(request, "Your password has been changed successfully.")
                return redirect(reverse("accounts:settings") + "?tab=security")
            return render(
                request,
                "accounts/settings.html",
                {
                    "profile_form": profile_form,
                    "password_form": password_form,
                    "paid_orders_count": paid_orders_count,
                    "active_tab": "security",
                },
                status=400,
            )

        elif action == "update_preferences":
            messages.success(request, "Your account preferences have been saved.")
            return redirect(reverse("accounts:settings") + "?tab=notifications")

        return redirect("accounts:settings")


class PrivacyPolicyView(TemplateView):
    template_name = "accounts/privacy_policy.html"


class TermsView(TemplateView):
    template_name = "accounts/terms.html"
