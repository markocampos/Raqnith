import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from apps.cart.services import get_cart
from apps.orders.exceptions import OrderBuildError
from apps.orders.models import Order
from apps.orders.selectors import get_order_for_checkout
from apps.orders.services.order_service import build_order_from_cart, mark_order_paid
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import PaymentService
from apps.payments.services.paymongo import (
    PayMongoAPIError,
    PayMongoNetworkError,
    PayMongoTimeoutError,
)

# Contact fields we persist in the session so a retry keeps them while
# resetting only the payment fields. Digital checkout collects only the email.
CHECKOUT_CONTACT_FIELDS = ("email",)


def _payment_method_for(order):
    """Return the masked payment method from the succeeded attempt, if any."""
    attempt = order.payment_attempts.filter(
        status=PaymentAttempt.Status.SUCCEEDED
    ).first()
    return attempt.payment_method if attempt else ""


class CreateOrderView(View):
    """Build and persist an Order from the current cart.

    Validates contact email and user data. If the user is not authenticated,
    saves contact information to the session and returns require_login: true
    with the redirect URL to /accounts/login/?next=/checkout/.
    When authenticated, builds the Order tied directly to request.user.
    """

    def post(self, request):
        cart = get_cart(request)

        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}

        contact = body.get("contact") or {}
        if not isinstance(contact, dict):
            contact = {}
        normalized = {
            field: str(contact.get(field) or "") for field in CHECKOUT_CONTACT_FIELDS
        }
        email = normalized.get("email", "").strip()
        terms_val = body.get("terms")
        terms_accepted = (terms_val in (True, "true", "on", "1", 1)) if "terms" in body else True

        # 1. Validate user data
        form_errors = {}
        if email:
            try:
                from django.core.validators import validate_email
                from django.core.exceptions import ValidationError
                validate_email(email)
            except ValidationError:
                form_errors["email"] = "Please enter a valid email address."

        if not terms_accepted:
            form_errors["terms"] = "You must agree to the terms and conditions to proceed."

        if form_errors:
            return JsonResponse(
                {"error": "validation_error", "errors": form_errors}, status=400
            )

        if email:
            request.session["checkout_contact"] = {"email": email}
            request.session.modified = True

        # 2. Build order (supports both authenticated user and guest session)
        if not request.session.session_key:
            request.session.save()

        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = build_order_from_cart(
                cart,
                shipping_method="standard",
                user_or_session=user_or_session,
            )
        except OrderBuildError as exc:
            return JsonResponse(
                {"error": "invalid_order", "errors": exc.errors}, status=400
            )

        if email:
            order.email = email
        elif request.user.is_authenticated and request.user.email:
            order.email = request.user.email
        order.save(update_fields=["email"])
        order.transition_to(Order.Status.PENDING_PAYMENT)
        request.session["active_order_id"] = str(order.id)
        request.session.modified = True
        return JsonResponse({"order_id": str(order.id)}, status=201)



class OrderStatusView(View):
    """Resolve an owned order's current state, reconciling ambiguous payments.

    - paid → confirmation page
    - pending attempt → reconcile against PayMongo, then settle/confirm/retry
    - failed → retry screen
    """

    def get(self, request, order_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = get_order_for_checkout(order_id, user_or_session)
        except Order.DoesNotExist:
            return render(request, "orders/not_found.html", status=404)

        if order.status == Order.Status.PAID:
            return render(
                request,
                "orders/detail.html",
                {
                    "order": order,
                    "state": "paid",
                    "payment_method": _payment_method_for(order),
                },
            )

        attempt = order.payment_attempts.first()
        if attempt is None:
            return render(
                request, "orders/detail.html", {"order": order, "state": "failed"}
            )

        if attempt.paymongo_intent_id and attempt.status not in (
            PaymentAttempt.Status.FAILED,
            PaymentAttempt.Status.CANCELLED,
            PaymentAttempt.Status.SUCCEEDED,
        ):
            service = PaymentService()
            try:
                service.reconcile_payment(attempt)
            except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError):
                return render(
                    request, "orders/detail.html", {"order": order, "state": "pending"}
                )

        attempt.refresh_from_db()

        if attempt.status == PaymentAttempt.Status.SUCCEEDED:
            mark_order_paid(order)
            return render(
                request,
                "orders/detail.html",
                {
                    "order": order,
                    "state": "paid",
                    "payment_method": _payment_method_for(order),
                },
            )

        if attempt.status == PaymentAttempt.Status.FAILED:
            return render(
                request,
                "orders/detail.html",
                {"order": order, "state": "failed", "retry_attempt_id": str(attempt.id)},
            )

        return render(
            request, "orders/detail.html", {"order": order, "state": "pending"}
        )




class OrderSuccessView(View):
    """Render the ✓ PAYMENT CONFIRMED page for an owned, paid order."""

    def get(self, request, order_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = get_order_for_checkout(order_id, user_or_session)
        except Order.DoesNotExist:
            return render(request, "orders/not_found.html", status=404)

        if order.status != Order.Status.PAID:
            return redirect("orders:status", order_id=order.id)

        request.session.pop("active_order_id", None)
        request.session.pop("active_attempt_id", None)
        request.session.modified = True

        return render(
            request,
            "orders/success.html",
            {"order": order, "payment_method": _payment_method_for(order)},
        )




class OrderReceiptView(View):
    """Render the full receipt for an owned, paid order."""

    def get(self, request, order_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = get_order_for_checkout(order_id, user_or_session)
        except Order.DoesNotExist:
            return render(request, "orders/not_found.html", status=404)

        if order.status != Order.Status.PAID:
            return redirect("orders:status", order_id=order.id)

        return render(
            request,
            "orders/receipt.html",
            {
                "order": order,
                "items": list(order.items.select_related("product")),
                "payment_method": _payment_method_for(order),
            },
        )
