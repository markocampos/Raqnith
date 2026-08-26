import io
import json
import logging
import os

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.cart.services import get_cart
from apps.catalog.models import ProductFile
from apps.orders.exceptions import OrderBuildError
from apps.orders.models import LicenseKey, Order
from apps.orders.selectors import get_order_for_checkout
from apps.orders.services import delivery
from apps.orders.services.order_service import (
    build_order_from_cart,
    is_free_order,
    mark_order_paid,
    settle_free_order,
)
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import PaymentService
from apps.payments.services.paymongo import (
    PayMongoAPIError,
    PayMongoNetworkError,
    PayMongoTimeoutError,
)

logger = logging.getLogger(__name__)

# Contact fields we persist in the session so a retry keeps them while
# resetting only the payment fields. Digital checkout collects only the email.
CHECKOUT_CONTACT_FIELDS = ("email",)

# Statuses that mean "the buyer owns this purchase" for delivery pages.
SETTLED_STATUSES = (Order.Status.PAID, Order.Status.FULFILLED)


def _payment_method_for(order):
    """Return the masked payment method from the succeeded attempt, if any."""
    attempt = order.payment_attempts.filter(
        status=PaymentAttempt.Status.SUCCEEDED
    ).first()
    return attempt.payment_method if attempt else ""


def _delivery_context(order):
    """Shared context for settled-order pages (status/success/receipt).

    Attaches each item's active deliverables as ``item.buyer_files`` so
    buyers see real downloads instead of a decorative button. Expired
    membership items are hidden from the list (with a notice instead), and
    issued license keys are included.
    """
    items = list(order.items.select_related("product"))
    product_ids = [item.product_id for item in items]
    files_by_product = {}
    if product_ids:
        files = ProductFile.objects.filter(
            product_id__in=product_ids, is_active=True
        ).order_by("sort_order", "created_at")
        for f in files:
            files_by_product.setdefault(f.product_id, []).append(f)
    expired_items = []
    for item in items:
        item.buyer_files = []
        if item.is_membership and not item.has_active_access:
            expired_items.append(item)
            continue
        item.buyer_files = files_by_product.get(item.product_id, [])
    has_files = any(item.buyer_files for item in items)

    license_keys = LicenseKey.objects.filter(
        order_item__order=order, revoked_at__isnull=True
    ).select_related("order_item__product")

    return {
        "order": order,
        "items": items,
        "payment_method": _payment_method_for(order),
        "has_deliverables": has_files,
        "license_keys": license_keys,
        "expired_memberships": expired_items,
        "downloads_remaining": delivery.downloads_remaining_today(order),
        "max_downloads_per_day": settings.MAX_DOWNLOADS_PER_DAY_PER_ORDER,
    }


class CreateOrderView(View):
    """Build and persist an Order from the current cart.

    Validates the contact email and terms acceptance, saves the contact to
    the session, and builds the Order tied to the authenticated user or the
    guest session. Guests proceed to payment without an account.
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
                from django.core.exceptions import ValidationError
                from django.core.validators import validate_email
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
                coupon_code=request.session.get("checkout_coupon") or None,
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

        # Free cart (< ₱1): confirm immediately — no QR Ph step, but the same
        # fulfillment, email, and receipt workflow as a paid order.
        if is_free_order(order):
            request.session["active_order_id"] = str(order.id)
            request.session.modified = True
            settle_free_order(order)
            return JsonResponse(
                {
                    "order_id": str(order.id),
                    "redirect_url": reverse("orders:success", args=[order.id]),
                },
                status=201,
            )

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

        if order.status in SETTLED_STATUSES:
            return render(
                request,
                "orders/detail.html",
                {"state": "paid", **_delivery_context(order)},
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
                {"state": "paid", **_delivery_context(order)},
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

        if order.status not in SETTLED_STATUSES:
            return redirect("orders:status", order_id=order.id)

        request.session.pop("active_order_id", None)
        request.session.pop("active_attempt_id", None)
        # The promo code has been consumed by this purchase; don't let it
        # silently discount a future order.
        request.session.pop("checkout_coupon", None)
        request.session.modified = True

        return render(
            request,
            "orders/success.html",
            _delivery_context(order),
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

        if order.status not in SETTLED_STATUSES:
            return redirect("orders:status", order_id=order.id)

        return render(
            request,
            "orders/receipt.html",
            _delivery_context(order),
        )


class OrderFileView(View):
    """Serve a purchased product file to the order's owner only.

    Access requires ALL of:
    * the caller owns the order (authenticated user or guest session), or
      arrived through a signed access link (already adopted upstream);
    * the order is settled (PAID / FULFILLED);
    * the file belongs to a product in this order, is active, and — for
      memberships — the access window is still open;
    * the order hasn't hit its daily download cap.

    Download items stream straight from storage with an attachment
    disposition; Stream items redirect to their hosted destination. The
    on-disk/media URL is never exposed. Every served download is logged.
    """

    def get(self, request, order_id, file_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = get_order_for_checkout(order_id, user_or_session)
        except Order.DoesNotExist:
            return render(request, "orders/not_found.html", status=404)

        if not delivery.settled(order):
            return redirect("orders:status", order_id=order.id)

        try:
            file_obj = ProductFile.objects.select_related("product").get(
                id=file_id, is_active=True
            )
        except ProductFile.DoesNotExist:
            return HttpResponseNotFound("That file is no longer available.")

        if not delivery.can_access_file(order, file_obj):
            # Distinguish expired memberships from foreign files so the
            # buyer gets a human explanation instead of a 404.
            from django.utils.dateformat import format as date_format

            for item in order.items.select_related("product"):
                if item.product_id == file_obj.product_id and not item.has_active_access:
                    expiry = date_format(
                        timezone.localtime(item.access_until), "M j, Y"
                    )
                    messages.warning(
                        request,
                        f"Your access to {item.product_name} ended on "
                        f"{expiry}. Renew to regain instant access.",
                    )
                    return redirect("orders:receipt", order_id=order.id)
            return render(request, "orders/not_found.html", status=404)

        remaining = delivery.downloads_remaining_today(order)
        if remaining is not None and remaining <= 0:
            messages.warning(
                request,
                f"You've reached today's download limit "
                f"({settings.MAX_DOWNLOADS_PER_DAY_PER_ORDER} per day) for "
                "this order. It resets at midnight. Need more? Contact support.",
            )
            logger.info("download rate-limited order=%s file=%s", order.id, file_obj.id)
            return redirect("orders:receipt", order_id=order.id)

        if file_obj.kind == ProductFile.Kind.STREAM and file_obj.external_url:
            delivery.record_download(order, file_obj, request)
            return redirect(file_obj.external_url)

        if not file_obj.file:
            return HttpResponseNotFound("That file is no longer available.")

        delivery.record_download(order, file_obj, request)
        filename = os.path.basename(file_obj.file.name)
        response = FileResponse(file_obj.file.open("rb"), as_attachment=True)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        logger.info("download served order=%s file=%s", order.id, file_obj.id)
        return response


class OrderAccessView(View):
    """Signed-link entry point from the confirmation email.

    The token (order id, signed, 30-day expiry) unlocks the order on any
    device — no account needed. The order is adopted into the current
    session/user exactly like Track Order, then the buyer lands directly on
    the receipt with their downloads.
    """

    def get(self, request, token):
        order = delivery.resolve_access_token(token)
        if order is None:
            context = {
                "error": (
                    "This download link has expired or is invalid. "
                    "Use Track My Order with your email and order number."
                )
            }
            return render(request, "orders/not_found.html", context, status=404)

        # Adopt the order so the standard status/receipt/download views work.
        if request.user.is_authenticated:
            if order.user_id != request.user.id:
                order.user = request.user
                order.save(update_fields=["user", "updated_at"])
        else:
            if not request.session.session_key:
                request.session.create()
            if order.session_key != request.session.session_key:
                order.session_key = request.session.session_key
                order.save(update_fields=["session_key", "updated_at"])

        if not delivery.settled(order):
            return redirect("orders:status", order_id=order.id)
        return redirect("orders:receipt", order_id=order.id)


class OrderReceiptPdfView(View):
    """Downloadable PDF receipt for a settled, owned order.

    Same access rules as the receipt page. Generated on the fly — no file
    storage needed.
    """

    def get(self, request, order_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = get_order_for_checkout(order_id, user_or_session)
        except Order.DoesNotExist:
            return render(request, "orders/not_found.html", status=404)

        if not delivery.settled(order):
            return redirect("orders:status", order_id=order.id)

        from apps.orders.services.receipt_pdf import build_receipt_pdf

        context = _delivery_context(order)
        pdf_bytes = build_receipt_pdf(
            order,
            context["items"],
            payment_method=context["payment_method"],
            license_keys=context["license_keys"],
        )
        response = FileResponse(
            io.BytesIO(pdf_bytes),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="Raqnith-Receipt-{str(order.id)[:8]}.pdf"'
        )
        logger.info("receipt pdf served order=%s", order.id)
        return response


class OrderResumeView(View):
    """Landing page for recovery-email links on pending orders.

    Simply hands off to the dedicated QR screen, which adopts the order into
    whatever session/device clicked the link and generates a fresh QR when
    the old one has expired.
    """

    def get(self, request, order_id):
        try:
            Order.objects.only("id").get(id=order_id)
        except (Order.DoesNotExist, ValidationError):
            return render(request, "orders/not_found.html", status=404)
        return redirect("checkout:order", order_id=order_id)


class TrackOrderView(View):
    """Guest order lookup: email + order number unlocks the order screen.

    Buyers who checked out without an account paste the order number from
    their confirmation page or receipt together with their email. A match
    adopts the order into the current session so every existing
    status/receipt view keeps working unchanged.
    """

    def get(self, request):
        return render(
            request,
            "orders/track.html",
            {"email": request.GET.get("email", ""), "order_ref": ""},
        )

    def post(self, request):
        import re

        email = (request.POST.get("email") or "").strip()
        raw_ref = (request.POST.get("order_ref") or "").strip()

        context = {"email": email, "order_ref": raw_ref}

        if not email or not raw_ref:
            context["error"] = "Please enter both your email and your order number."
            return render(request, "orders/track.html", context, status=400)

        # Accept a full UUID, a bare short code, or a pasted confirmation URL.
        candidate = ""
        for token in reversed(re.split(r"[\s/]+", raw_ref)):
            token = token.strip("#").strip()
            if re.fullmatch(r"[0-9a-fA-F-]{8,36}", token):
                candidate = token
                break
        if not candidate:
            context["error"] = (
                "That doesn't look like an order number. "
                "It looks like 12345678-abcd-… from your confirmation page."
            )
            return render(request, "orders/track.html", context, status=400)

        orders = Order.objects.filter(email__iexact=email)

        order = None
        if len(candidate) == 36:
            try:
                order = orders.get(id=candidate)
            except (Order.DoesNotExist, ValueError):
                order = None
        if order is None and len(candidate) >= 8:
            order = orders.filter(id__istartswith=candidate[:8]).first()

        if (
            order is None
            or order.status not in (Order.Status.PAID, Order.Status.FULFILLED)
        ):
            context["error"] = (
                "We couldn't find a completed order with that email and order "
                "number. Double-check the confirmation email we sent you."
            )
            return render(request, "orders/track.html", context, status=404)

        # Adopt the order into this visitor's session/user so the standard
        # status → success → receipt flow works as if they just paid.
        if request.user.is_authenticated:
            if order.user_id != request.user.id:
                order.user = request.user
                order.save(update_fields=["user", "updated_at"])
        else:
            if not request.session.session_key:
                request.session.create()
            if order.session_key != request.session.session_key:
                order.session_key = request.session.session_key
                order.save(update_fields=["session_key", "updated_at"])

        return redirect("orders:status", order_id=order.id)
