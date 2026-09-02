import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from apps.cart.services import get_cart
from apps.checkout.selectors import build_checkout_context
from apps.coupons.models import Coupon
from apps.orders.exceptions import OrderBuildError
from apps.orders.models import Order
from apps.orders.services.order_service import (
    build_order_from_cart,
    is_free_order,
    settle_free_order,
)
from apps.payments.error_map import DEFAULT_ERROR_MESSAGE, FRIENDLY_ERROR_MESSAGES
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import AlreadyPaid, PaymentService
from apps.payments.services.paymongo import (
    PayMongoAPIError,
    PayMongoNetworkError,
    PayMongoTimeoutError,
)


def _order_may_be_paid(order, service):
    """Return True if the order may already be paid at PayMongo.

    Checked before cancelling a stale pending order: a succeeded attempt, or
    an in-flight intent that reconciles to SUCCEEDED, means money moved and
    the order must survive. Provider/network errors also count as "may be
    paid" — ambiguous is treated as paid rather than cancelling a capture.
    """
    latest = order.payment_attempts.order_by("-created_at").first()
    if latest is None:
        return False
    if latest.status == PaymentAttempt.Status.SUCCEEDED:
        return True
    if not latest.paymongo_intent_id or latest.status in (
        PaymentAttempt.Status.FAILED,
        PaymentAttempt.Status.CANCELLED,
    ):
        return False
    try:
        service.reconcile_payment(latest)
        latest.refresh_from_db()
    except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError):
        return True
    return latest.status == PaymentAttempt.Status.SUCCEEDED or (
        Order.objects.get(pk=order.pk).status == Order.Status.PAID
    )


class ApplyCouponView(View):
    def post(self, request):
        code = request.POST.get("coupon_code", "").strip().upper()
        if not code:
            messages.error(request, "Please enter a promo code.")
            return redirect("checkout:index")

        coupon = Coupon.objects.filter(code__iexact=code, active=True).first()
        if not coupon or coupon.is_expired:
            messages.error(request, f"Promo code '{code}' is invalid or expired.")
            return redirect("checkout:index")

        request.session["checkout_coupon"] = coupon.code
        messages.success(
            request, f"Promo code '{coupon.code}' applied! ({coupon.discount_percent}% off)"
        )
        return redirect("checkout:index")


class RemoveCouponView(View):
    def post(self, request):
        if "checkout_coupon" in request.session:
            del request.session["checkout_coupon"]
            messages.info(request, "Promo code removed.")
        return redirect("checkout:index")


class CheckoutView(View):
    """Initial checkout screen: validate user data, check login state, and proceed to payment."""

    def get(self, request):
        cart = get_cart(request)
        coupon_code = request.GET.get("coupon", "").strip() or request.session.get(
            "checkout_coupon", ""
        )
        try:
            context = build_checkout_context(cart, coupon_code=coupon_code)
        except OrderBuildError:
            return redirect("cart:detail")

        context["error_map"] = FRIENDLY_ERROR_MESSAGES
        context["error_map_default"] = DEFAULT_ERROR_MESSAGE

        email_query = request.GET.get("email", "").strip()
        contact = dict(request.session.get("checkout_contact", {}))
        if email_query:
            contact["email"] = email_query
        elif not contact.get("email") and request.user.is_authenticated:
            contact["email"] = request.user.email

        context["checkout_contact"] = contact
        context["is_authenticated"] = request.user.is_authenticated
        return render(request, "checkout/index.html", context)

    def post(self, request):
        cart = get_cart(request)
        coupon_code = request.POST.get("coupon", "").strip() or request.session.get(
            "checkout_coupon", ""
        )

        is_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.headers.get("Content-Type") == "application/json"
        )

        if is_json:
            try:
                body = json.loads(request.body or b"{}")
            except Exception:
                body = {}
            contact = body.get("contact", {}) if isinstance(body.get("contact"), dict) else {}
            email = str(contact.get("email") or body.get("email") or "").strip()
            terms_val = body.get("terms")
            terms_accepted = (
                (terms_val in (True, "true", "on", "1", 1)) if "terms" in body else True
            )
        else:
            email = request.POST.get("email", "").strip()
            terms_accepted = request.POST.get("terms") in ("on", "true", "1", True)

        # 1. Validate user data (email and terms acceptance)
        form_errors = {}
        if not email:
            form_errors["email"] = "Please enter an email address."
        else:
            try:
                validate_email(email)
            except ValidationError:
                form_errors["email"] = "Please enter a valid email address."

        if not terms_accepted:
            form_errors["terms"] = "You must agree to the terms and conditions to proceed."

        if form_errors:
            if is_json:
                return JsonResponse(
                    {"error": "validation_error", "errors": form_errors}, status=400
                )
            try:
                context = build_checkout_context(cart, coupon_code=coupon_code)
            except OrderBuildError:
                return redirect("cart:detail")
            context["error_map"] = FRIENDLY_ERROR_MESSAGES
            context["error_map_default"] = DEFAULT_ERROR_MESSAGE
            context["checkout_contact"] = {"email": email}
            context["form_errors"] = form_errors
            context["form_error"] = next(iter(form_errors.values()))
            context["is_authenticated"] = request.user.is_authenticated
            return render(request, "checkout/index.html", context, status=400)

        # Persist validated contact info to session
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
                coupon_code=coupon_code,
                shipping_method="standard",
                user_or_session=user_or_session,
            )
        except OrderBuildError:
            return redirect("cart:detail")

        order.email = email
        order.save(update_fields=["email"])
        order.transition_to(Order.Status.PENDING_PAYMENT)

        # Free cart (< ₱1): confirm immediately — no QR Ph step, same
        # fulfillment/email/receipt workflow as a paid order.
        if is_free_order(order):
            settle_free_order(order)
            if is_json:
                return JsonResponse({"order_id": str(order.id)}, status=201)
            return redirect("orders:success", order_id=order.id)

        # 3. Purge unpaid orders older than 120 minutes
        Order.purge_unpaid_overdue()

        # Cancel any previous unpaid/pending orders for this user, session, or email
        from django.db.models import Q

        q = Q()
        if request.user.is_authenticated:
            q |= Q(user=request.user)
        if request.session.session_key:
            q |= Q(session_key=request.session.session_key)
        if email:
            q |= Q(email__iexact=email)

        prev_orders = Order.objects.filter(q, status=Order.Status.PENDING_PAYMENT).exclude(
            id=order.id
        )

        service = PaymentService()
        for prev in prev_orders:
            if _order_may_be_paid(prev, service):
                # Money may already have been captured at PayMongo — never
                # cancel; leave it for reconciliation to settle as PAID.
                continue
            prev.transition_to(Order.Status.CANCELLED)
            PaymentAttempt.objects.filter(
                order=prev,
                status__in=[
                    PaymentAttempt.Status.CREATED,
                    PaymentAttempt.Status.AWAITING_METHOD,
                    PaymentAttempt.Status.AWAITING_ACTION,
                ],
            ).update(status=PaymentAttempt.Status.CANCELLED)

        if is_json:
            return JsonResponse({"order_id": str(order.id)}, status=201)

        return redirect("checkout:order", order_id=order.id)


class OrderCheckoutView(View):
    """Dedicated order payment page tied directly to the order UUID URL.

    - Loads order by UUID in the URL.
    - Checks API / PayMongo directly for live status.
    - Displays QR Ph code with countdown timer and expiration state.
    - If already paid, automatically redirects to order confirmation.
    """

    def get(self, request, order_id):
        if not request.session.session_key:
            request.session.save()

        try:
            order = Order.objects.select_related("user").get(id=order_id)
        except (Order.DoesNotExist, ValidationError):
            return render(request, "orders/not_found.html", status=404)

        if not order.user_id and request.user.is_authenticated:
            order.user = request.user
            order.save(update_fields=["user"])
        elif not order.session_key and request.session.session_key:
            order.session_key = request.session.session_key
            order.save(update_fields=["session_key"])

        request.session["active_order_id"] = str(order.id)
        request.session.modified = True

        order.expire_if_overdue()
        is_paid = order.status == Order.Status.PAID
        is_order_cancelled = order.status == Order.Status.CANCELLED
        service = PaymentService()
        attempt = order.payment_attempts.order_by("-created_at").first()

        # Opportunistic reconciliation for any in-flight attempt
        if not is_paid and attempt is not None and attempt.paymongo_intent_id:
            if attempt.status in (
                PaymentAttempt.Status.AWAITING_ACTION,
                PaymentAttempt.Status.PROCESSING,
            ):
                try:
                    service.reconcile_payment(attempt)
                    attempt.refresh_from_db()
                    order.refresh_from_db()
                except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError):
                    pass

                if (
                    order.status == Order.Status.PAID
                    or attempt.status == PaymentAttempt.Status.SUCCEEDED
                ):
                    is_paid = True
                    is_order_cancelled = False

        # If not paid and not cancelled, create a fresh QR Ph attempt if needed
        if (
            not is_paid
            and not is_order_cancelled
            and (
                attempt is None
                or attempt.is_expired
                or not attempt.qr_url
                or attempt.status == PaymentAttempt.Status.FAILED
            )
        ):
            try:
                attempt = service.initiate_payment(
                    order=order, payment_method="qrph", replace_stale=True
                )
            except AlreadyPaid:
                is_paid = True
            except Exception:
                pass

        context = {
            "order": order,
            "order_id": str(order.id),
            "line_items": list(order.items.select_related("product")),
            "total_cents": order.total_amount,
            "subtotal_cents": order.subtotal_amount,
            "discount_cents": order.discount_amount,
            "email": order.email,
            "attempt": attempt,
            "payment_id": str(attempt.id) if attempt else "",
            "qr_url": attempt.qr_url if attempt else "",
            "is_paid": is_paid,
            "is_order_cancelled": is_order_cancelled,
            "is_expired": False
            if (is_paid or is_order_cancelled)
            else (attempt.is_expired if attempt else False),
            "seconds_remaining": 0
            if (is_paid or is_order_cancelled)
            else (attempt.seconds_remaining if attempt else 0),
            "error_map": FRIENDLY_ERROR_MESSAGES,
            "error_map_default": DEFAULT_ERROR_MESSAGE,
        }
        return render(request, "checkout/payment.html", context)
