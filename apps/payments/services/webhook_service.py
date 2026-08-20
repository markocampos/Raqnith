import logging

from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.services.order_service import mark_order_paid
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import PaymentService, masked_payment_method

logger = logging.getLogger(__name__)


class WebhookMismatch(Exception):
    """A webhook's amount or currency does not match the stored attempt."""


class WebhookService:
    """Process verified PayMongo webhook events.

    The webhook is the authoritative source of payment truth for asynchronous
    settlement. Each handler is idempotent: a ``payment.paid`` for an
    already-succeeded attempt/paid order is a no-op, so replays and the
    return-view reconciliation path never double-transition.
    """

    def __init__(self, payment_service=None):
        self.payment_service = (
            payment_service if payment_service is not None else PaymentService()
        )

    def process_event(self, payload, webhook_event):
        """Dispatch ``payload`` by event type; all supported events are processed."""
        event_type = self._event_type(payload) or ""

        KNOWN_EVENTS = {
            "payment.paid", "payment.failed", "payment.refunded", "payment.refund.updated",
            "qrph.expired", "qr.expired", "qr.paid", "checkout_session.payment.paid",
            "source.chargeable", "link.payment.paid",
        }

        if event_type in ("payment.paid", "qr.paid", "checkout_session.payment.paid"):
            self._handle_payment_paid(payload, webhook_event)
        elif event_type in ("payment.failed", "qrph.expired", "qr.expired"):
            failure_code = "qr_expired" if "expired" in event_type else "payment_failed"
            self._handle_payment_failed(payload, webhook_event, failure_code=failure_code)
        elif event_type in ("payment.refunded", "payment.refund.updated"):
            self._handle_refunded(payload, webhook_event)
        elif event_type in KNOWN_EVENTS:
            # Other known events are acknowledged and marked processed safely.
            self._mark_processed(webhook_event)
        # else: unknown event — recorded but left unprocessed (view still returns 200).



    # ---- helpers ----

    @staticmethod
    def _event_type(payload):
        return (payload or {}).get("data", {}).get("attributes", {}).get("type")

    @staticmethod
    def _extract_payment(payload):
        """Return payment attributes from a payment.paid/payment.failed event."""
        resource = (
            (payload or {})
            .get("data", {})
            .get("attributes", {})
            .get("data", {})
        )
        attrs = resource.get("attributes", {}) or {}
        source = attrs.get("source") or {}
        return {
            "payment_id": resource.get("id"),
            "payment_intent_id": attrs.get("payment_intent_id"),
            "amount": attrs.get("amount"),
            "currency": attrs.get("currency"),
            "source": source,
        }

    def _mark_processed(self, webhook_event):
        webhook_event.processed = True
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=["processed", "processed_at"])

    # ---- handlers ----

    def _handle_payment_paid(self, payload, webhook_event):
        payment = self._extract_payment(payload)
        intent_id = payment["payment_intent_id"]
        if not intent_id:
            logger.warning("payment.paid missing payment_intent_id; event acknowledged.")
            self._mark_processed(webhook_event)
            return

        attempt = PaymentAttempt.objects.filter(paymongo_intent_id=intent_id).first()
        if attempt is None:
            logger.warning(
                "payment.paid for unknown intent %s; event acknowledged.", intent_id
            )
            self._mark_processed(webhook_event)
            return

        if (
            attempt.amount != payment["amount"]
            or attempt.currency != payment["currency"]
        ):
            logger.warning(
                "payment.paid amount/currency mismatch for attempt %s: "
                "expected %s %s, got %s %s.",
                attempt.id,
                attempt.amount,
                attempt.currency,
                payment["amount"],
                payment["currency"],
            )
            raise WebhookMismatch(
                f"amount/currency mismatch for attempt {attempt.id}"
            )

        with transaction.atomic():
            attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
            order = Order.objects.select_for_update().get(pk=attempt.order_id)

            self.payment_service.mark_attempt_succeeded(attempt)
            masked = masked_payment_method(payment["source"])
            if masked and not attempt.payment_method:
                attempt.payment_method = masked
                attempt.save(update_fields=["payment_method", "updated_at"])
            if payment.get("payment_id") and not attempt.paymongo_payment_id:
                attempt.paymongo_payment_id = payment["payment_id"]
                attempt.save(update_fields=["paymongo_payment_id", "updated_at"])

            mark_order_paid(order)
            self._mark_processed(webhook_event)

    def _handle_payment_failed(self, payload, webhook_event, failure_code="payment_failed"):
        payment = self._extract_payment(payload)
        intent_id = payment.get("payment_intent_id")
        if not intent_id:
            # Check if resource has id or payment_intent_id directly
            resource = (payload or {}).get("data", {}).get("attributes", {}).get("data", {})
            attrs = resource.get("attributes", {}) or {}
            intent_id = attrs.get("payment_intent_id") or resource.get("id")

        if not intent_id:
            logger.warning("payment.failed missing payment_intent_id; event acknowledged.")
            self._mark_processed(webhook_event)
            return

        attempt = PaymentAttempt.objects.filter(paymongo_intent_id=intent_id).first()
        if attempt is None:
            logger.warning(
                "payment.failed for unknown intent %s; event acknowledged.", intent_id
            )
            self._mark_processed(webhook_event)
            return

        with transaction.atomic():
            attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
            if attempt.status not in (
                PaymentAttempt.Status.SUCCEEDED,
                PaymentAttempt.Status.FAILED,
            ):
                msg = "QR code expired." if failure_code == "qr_expired" else "Payment failed."
                self.payment_service.mark_payment_failed(
                    attempt, code=failure_code, message=msg
                )
            self._mark_processed(webhook_event)


    def _handle_refunded(self, payload, webhook_event):
        # Placeholder — refunds are implemented in Phase 15.
        self._mark_processed(webhook_event)
