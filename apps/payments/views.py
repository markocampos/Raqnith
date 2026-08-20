import json
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.orders.models import Order
from apps.orders.selectors import get_order_for_checkout
from apps.orders.services.order_service import mark_order_paid
from apps.payments.models import PaymentAttempt, WebhookEvent
from apps.payments.selectors import get_attempt_for_checkout
from apps.payments.services.payment_service import (
    ALLOWED_PAYMENT_METHODS,
    ActiveAttemptExists,
    AlreadyPaid,
    PaymentService,
)
from apps.payments.services.paymongo import (
    InvalidWebhookSignature,
    PayMongoAPIError,
    PayMongoNetworkError,
    PayMongoTimeoutError,
    verify_webhook_signature,
)
from apps.payments.services.webhook_service import WebhookMismatch, WebhookService

logger = logging.getLogger(__name__)

WEBHOOK_SIGNATURE_HEADER = "Paymongo-Signature"


class CreateIntentView(View):
    """Create a PayMongo PaymentIntent for an existing (unpaid) order.

    Returns only public data: payment id, intent id, client key, amount,
    currency, and the QR image or redirect URL. The amount comes from the
    server-computed order total; any amount supplied in the request body is
    ignored. The chosen payment method (qrph/gcash/paymaya) is validated
    server-side.
    """

    def post(self, request):
        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {"error": "invalid_request", "detail": "Invalid JSON body."}, status=400
            )

        order_id = body.get("order_id")
        if not order_id:
            return JsonResponse(
                {"error": "missing_order_id", "detail": "order_id is required."}, status=400
            )

        payment_method = body.get("payment_method", "qrph")
        if payment_method not in ALLOWED_PAYMENT_METHODS:
            return JsonResponse(
                {"error": "invalid_payment_method", "detail": "Unsupported payment method."},
                status=400,
            )

        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            order = get_order_for_checkout(order_id, user_or_session)
        except (Order.DoesNotExist, ValidationError):
            return JsonResponse(
                {"error": "not_found", "detail": "Order not found."}, status=404
            )

        service = PaymentService()
        try:
            attempt = service.initiate_payment(
                order=order, payment_method=payment_method
            )
        except AlreadyPaid:
            return JsonResponse(
                {"error": "already_paid", "detail": "This order has already been paid."},
                status=409,
            )
        except ActiveAttemptExists:
            return JsonResponse(
                {
                    "error": "active_attempt_exists",
                    "detail": "A payment is already in progress for this order.",
                },
                status=409,
            )
        except (PayMongoTimeoutError, PayMongoNetworkError):
            return JsonResponse(
                {
                    "error": "payment_gateway_unavailable",
                    "detail": (
                        "We're still checking your payment. "
                        "Please don't submit another payment yet."
                    ),
                },
                status=504,
            )
        except PayMongoAPIError as exc:
            return JsonResponse(
                {"error": exc.code or "payment_error", "detail": exc.message},
                status=502,
            )

        request.session["active_attempt_id"] = str(attempt.id)
        request.session["active_order_id"] = str(order.id)
        request.session.modified = True

        return JsonResponse(
            {
                "payment_id": str(attempt.id),
                "payment_intent_id": attempt.paymongo_intent_id,
                "client_key": attempt.client_key,
                "qr_url": attempt.qr_url,
                "redirect_url": attempt.redirect_url,
                "amount": attempt.amount,
                "currency": attempt.currency,
            },
            status=201,
        )



class PaymentStatusView(View):
    """Return the current state of a payment attempt to its owner.

    Used by the checkout to poll a ``processing`` attempt. Only the attempt's
    own order owner (authenticated user or session) may read it. The webhook
    (Phase 8) is the authoritative writer of these states; this endpoint simply
    exposes them for the browser's polling loop.
    """

    def get(self, request, attempt_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            attempt = get_attempt_for_checkout(attempt_id, user_or_session)
        except PaymentAttempt.DoesNotExist:
            active_order_id = request.session.get("active_order_id")
            if active_order_id:
                try:
                    attempt = PaymentAttempt.objects.select_related("order").get(
                        id=attempt_id, order_id=active_order_id
                    )
                except (PaymentAttempt.DoesNotExist, ValidationError):
                    return JsonResponse(
                        {"error": "not_found", "detail": "Payment attempt not found."}, status=404
                    )
            else:
                return JsonResponse(
                    {"error": "not_found", "detail": "Payment attempt not found."}, status=404
                )

        if attempt.status in (
            PaymentAttempt.Status.AWAITING_ACTION,
            PaymentAttempt.Status.PROCESSING,
        ):
            if attempt.is_expired:
                attempt.failure_code = "qr_expired"
                attempt.failure_message = "QR code has expired. Please generate a new one."
                attempt.status = PaymentAttempt.Status.FAILED
                attempt.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
            elif attempt.paymongo_intent_id:
                try:
                    PaymentService().reconcile_payment(attempt)
                    attempt.refresh_from_db()
                except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError):
                    pass

        return JsonResponse(
            {
                "status": attempt.status,
                "failure_code": attempt.failure_code,
                "failure_message": attempt.failure_message,
                "is_expired": attempt.is_expired,
                "seconds_remaining": attempt.seconds_remaining,
                "order_id": str(attempt.order_id),
            }
        )




class RetryPaymentView(View):
    """Create a fresh PaymentAttempt for an order, replacing a stale attempt.

    Used by the checkout retry flow. Timeout ≠ failure: if the existing attempt
    is still ambiguous (it has an intent id and is not terminal), it is
    reconciled against PayMongo first — a hidden success is settled without a
    new charge, and an in-flight ``processing`` intent blocks the retry.
    """

    def post(self, request, attempt_id):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        payment_method = body.get("payment_method", "qrph")
        if payment_method not in ALLOWED_PAYMENT_METHODS:
            return JsonResponse(
                {"error": "invalid_payment_method", "detail": "Unsupported payment method."},
                status=400,
            )

        try:
            attempt = get_attempt_for_checkout(attempt_id, user_or_session)
        except PaymentAttempt.DoesNotExist:
            active_order_id = request.session.get("active_order_id")
            if active_order_id:
                try:
                    attempt = PaymentAttempt.objects.select_related("order").get(
                        id=attempt_id, order_id=active_order_id
                    )
                except (PaymentAttempt.DoesNotExist, ValidationError):
                    return JsonResponse(
                        {"error": "not_found", "detail": "Payment attempt not found."}, status=404
                    )
            else:
                return JsonResponse(
                    {"error": "not_found", "detail": "Payment attempt not found."}, status=404
                )

        order = attempt.order
        if order.status == Order.Status.PAID:
            return JsonResponse(
                {"error": "already_paid", "detail": "This order has already been paid."},
                status=409,
            )

        service = PaymentService()

        if attempt.paymongo_intent_id and attempt.status not in (
            PaymentAttempt.Status.FAILED,
            PaymentAttempt.Status.CANCELLED,
            PaymentAttempt.Status.SUCCEEDED,
        ):
            try:
                service.reconcile_payment(attempt)
            except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError):
                return JsonResponse(
                    {
                        "error": "payment_gateway_unavailable",
                        "detail": (
                            "We're still checking your payment. "
                            "Please don't submit another payment yet."
                        ),
                    },
                    status=504,
                )

            attempt.refresh_from_db()
            if attempt.status == PaymentAttempt.Status.SUCCEEDED:
                mark_order_paid(order)
                return JsonResponse(
                    {"status": "succeeded", "order_id": str(order.id)}, status=200
                )
            if attempt.status == PaymentAttempt.Status.PROCESSING:
                return JsonResponse({"status": "processing"}, status=202)

        try:
            new_attempt = service.initiate_payment(
                order=order, payment_method=payment_method, replace_stale=True
            )
        except AlreadyPaid:
            return JsonResponse(
                {"error": "already_paid", "detail": "This order has already been paid."},
                status=409,
            )
        except ActiveAttemptExists:
            return JsonResponse(
                {
                    "error": "active_attempt_exists",
                    "detail": "A payment is already in progress for this order.",
                },
                status=409,
            )
        except (PayMongoTimeoutError, PayMongoNetworkError):
            return JsonResponse(
                {
                    "error": "payment_gateway_unavailable",
                    "detail": (
                        "We're still checking your payment. "
                        "Please don't submit another payment yet."
                    ),
                },
                status=504,
            )
        except PayMongoAPIError as exc:
            return JsonResponse(
                {"error": exc.code or "payment_error", "detail": exc.message}, status=502
            )

        request.session["active_attempt_id"] = str(new_attempt.id)
        request.session["active_order_id"] = str(order.id)
        request.session.modified = True

        return JsonResponse(
            {
                "payment_id": str(new_attempt.id),
                "payment_intent_id": new_attempt.paymongo_intent_id,
                "client_key": new_attempt.client_key,
                "qr_url": new_attempt.qr_url,
                "redirect_url": new_attempt.redirect_url,
                "amount": new_attempt.amount,
                "currency": new_attempt.currency,
                "seconds_remaining": new_attempt.seconds_remaining,
                "order_id": str(order.id),
            },
            status=201,
        )




class PaymentReturnView(View):
    """Handle the browser's return from a 3DS / bank authentication flow.

    The query parameters PayMongo appends (payment_intent_id, status, …) are
    treated as hints only and are never trusted. The authoritative verdict is
    the Payment Intent state retrieved server-side from PayMongo.

    Outcomes:
    * intent succeeded     → settle locally, redirect to the success page
    * intent failed        → redirect to the order status page (retry screen)
    * still authenticating → render a "Confirming your payment…" page that
                             polls the status endpoint until it resolves
    * provider unreachable → render the confirming page; do not fail
    """

    def get(self, request):
        user_or_session = (
            request.user if request.user.is_authenticated else request.session.session_key
        )

        intent_id_hint = request.GET.get("payment_intent_id", "")
        if not intent_id_hint:
            return render(request, "payments/return.html", {"state": "not_found"}, status=404)

        try:
            attempt = PaymentAttempt.objects.select_related("order").get(
                paymongo_intent_id=intent_id_hint
            )
        except PaymentAttempt.DoesNotExist:
            return render(request, "payments/return.html", {"state": "not_found"}, status=404)

        try:
            attempt = get_attempt_for_checkout(attempt.id, user_or_session)
        except PaymentAttempt.DoesNotExist:
            return render(request, "payments/return.html", {"state": "not_found"}, status=404)

        order = attempt.order
        if order.status == Order.Status.PAID:
            return redirect("orders:success", order_id=order.id)

        service = PaymentService()
        try:
            service.reconcile_payment(attempt)
        except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError):
            logger.warning(
                "Payment return reconciliation failed for intent %s", intent_id_hint
            )
            return render(
                request,
                "payments/return.html",
                {
                    "state": "confirming",
                    "order": order,
                    "poll": {"attempt_id": str(attempt.id), "order_id": str(order.id)},
                },
            )

        attempt.refresh_from_db()

        if attempt.status == PaymentAttempt.Status.SUCCEEDED:
            mark_order_paid(order)
            return redirect("orders:success", order_id=order.id)

        if attempt.status == PaymentAttempt.Status.FAILED:
            return redirect("orders:status", order_id=order.id)

        return render(
            request,
            "payments/return.html",
            {
                "state": "confirming",
                "order": order,
                "poll": {"attempt_id": str(attempt.id), "order_id": str(order.id)},
            },
        )


@method_decorator(csrf_exempt, name="dispatch")
class PayMongoWebhookView(View):
    """Accept verified PayMongo webhooks.

    Order of operations:
    1. Verify the HMAC signature (reject with 401 before anything else).
    2. Upsert the WebhookEvent by provider event id — an existing event is a
       replay, so return 200 without reprocessing (idempotency gate).
    3. Process the event; a processing failure returns 500 so PayMongo retries.
    """

    def post(self, request):
        raw_body = request.body
        signature = request.headers.get(WEBHOOK_SIGNATURE_HEADER)

        try:
            verify_webhook_signature(
                raw_body, signature, settings.PAYMONGO_WEBHOOK_SECRET
            )
        except InvalidWebhookSignature:
            logger.warning("Rejected PayMongo webhook with invalid signature.")
            return JsonResponse({"error": "invalid_signature"}, status=401)

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "invalid_payload"}, status=400)

        data = payload.get("data") or {}
        event_id = data.get("id")
        event_type = (data.get("attributes") or {}).get("type", "")
        if not event_id:
            return JsonResponse({"error": "missing_event_id"}, status=400)

        webhook_event, created = WebhookEvent.objects.get_or_create(
            provider_event_id=event_id,
            defaults={"event_type": event_type, "payload": payload},
        )
        if not created:
            # Already delivered once — replay is a no-op.
            return JsonResponse({"received": True}, status=200)

        try:
            WebhookService().process_event(payload, webhook_event)
        except WebhookMismatch as exc:
            # Permanent inconsistency: acknowledge it (don't make PayMongo
            # retry a payload that will never match), but leave it unprocessed.
            logger.warning("Webhook mismatch: %s", exc)
            return JsonResponse({"received": True, "status": "mismatch"}, status=200)
        except Exception:
            logger.exception("Webhook processing failed for event %s", event_id)
            return JsonResponse({"error": "processing_failed"}, status=500)

        return JsonResponse({"received": True}, status=200)
