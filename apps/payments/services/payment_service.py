import logging

from django.conf import settings
from django.db import transaction

from apps.orders.models import Order
from apps.orders.services.order_service import mark_order_paid
from apps.payments.models import PaymentAttempt, Refund
from apps.payments.services.paymongo import (
    PayMongoAPIError,
    PayMongoClient,
    PayMongoNetworkError,
    PayMongoTimeoutError,
)
from apps.payments.services.state_machine import (
    ACTIVE_ATTEMPT_STATUSES,
    STALE_ATTEMPT_STATUSES,
    is_valid_transition,
)

logger = logging.getLogger("payments.service")

# Payment methods supported by this checkout and their PayMongo API values.
# Maya's API value is "paymaya"; the UI label is "Maya".
ALLOWED_PAYMENT_METHODS = {
    "qrph": "qrph",
    "gcash": "gcash",
    "paymaya": "paymaya",
}


class AlreadyPaid(Exception):
    """The order is already paid and cannot start another payment."""


class ActiveAttemptExists(Exception):
    """An order already has an active (non-terminal) payment attempt."""

    def __init__(self, attempt):
        self.attempt = attempt
        super().__init__(f"An active attempt {attempt.id} already exists for the order.")


class InvalidStateTransition(Exception):
    """A payment attempt transition violates the allowed state machine."""


def masked_payment_method(source):
    """Return a display-safe payment method string from a PayMongo source.

    Only the brand + last4 are kept for cards (e.g. "visa •••• 4242"); the raw
    PAN never appears. Non-card methods keep their type (gcash, qrph, …).
    """
    if not source:
        return ""
    method_type = (source.get("type") or "").lower()
    if method_type == "card":
        brand = (source.get("brand") or "").lower()
        last4 = source.get("last4") or ""
        if brand and last4:
            return f"{brand} •••• {last4}"
        return "card"
    return method_type


class PaymentService:
    def __init__(self, client=None):
        self.client = client if client is not None else PayMongoClient(settings.PAYMONGO_SECRET_KEY)

    def _transition(self, attempt, to_status):
        if not is_valid_transition(attempt.status, to_status):
            raise InvalidStateTransition(
                f"Invalid payment attempt transition: {attempt.status} -> {to_status}."
            )
        attempt.status = to_status
        attempt.save(update_fields=["status", "updated_at"])
        return attempt

    def initiate_payment(self, *, order, payment_method="qrph", replace_stale=False):
        """Create a PayMongo intent and its PaymentAttempt for an unpaid order.

        The full Payment Intent workflow is performed server-side: create the
        intent, create a (non-sensitive) payment method for the chosen method,
        and attach it. Attaching produces the QR image for QR Ph or the
        provider redirect URL for e-wallets.

        Hardened against double-charges:
        * the order row is locked (``select_for_update``) and the paid check
          happens inside the same atomic block as attempt creation;
        * at most one active (non-terminal) attempt may exist — a second
          concurrent attempt raises ``ActiveAttemptExists``;
        * ``replace_stale=True`` (the retry path) first cancels any pre-attach
          ``created``/``awaiting_method`` attempts so history is kept but no
          stale attempt stays live.

        The PayMongo calls run outside the transaction so the DB lock is not
        held across an external HTTP round-trip.
        """
        payment_method_allowed = [ALLOWED_PAYMENT_METHODS[payment_method]]

        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order.id)
            if order.status == Order.Status.PAID:
                raise AlreadyPaid("Order is already paid.")

            active = PaymentAttempt.objects.filter(
                order=order, status__in=ACTIVE_ATTEMPT_STATUSES
            ).first()

            if active is not None:
                if not replace_stale:
                    raise ActiveAttemptExists(active)
                # Never silently replace an in-flight 3DS/processing attempt.
                if active.status not in STALE_ATTEMPT_STATUSES:
                    raise ActiveAttemptExists(active)
                PaymentAttempt.objects.filter(
                    order=order, status__in=STALE_ATTEMPT_STATUSES
                ).update(status=PaymentAttempt.Status.CANCELLED)

            attempt = PaymentAttempt.objects.create(
                order=order,
                amount=order.total_amount,
                currency=order.currency,
                status=PaymentAttempt.Status.CREATED,
            )

        desc = (
            f"Order {order.id} - {order.email}".strip(" -") if order.email else f"Order {order.id}"
        )
        meta = {"order_id": str(order.id)}
        if order.email:
            meta["customer_email"] = order.email

        try:
            intent = self.client.create_payment_intent(
                amount=order.total_amount,
                currency=order.currency,
                description=desc,
                statement_descriptor="Virtus",
                payment_method_allowed=payment_method_allowed,
                metadata=meta,
            )

            intent = self._attach_method(intent, payment_method)
        except (PayMongoTimeoutError, PayMongoNetworkError):
            # Timeout ≠ failure: the intent may have been created. Keep the
            # attempt open for reconciliation instead of marking it failed.
            attempt.failure_message = "still checking"
            attempt.save(update_fields=["failure_message"])
            self._transition(attempt, PaymentAttempt.Status.AWAITING_METHOD)
            raise
        except PayMongoAPIError as exc:
            self.mark_payment_failed(attempt, code=exc.code, message=exc.message)
            raise

        attempt.paymongo_intent_id = intent["id"]
        attempt.client_key = intent.get("client_key", "")
        attempt.qr_url = self._qr_url_from(intent)
        attempt.redirect_url = self._redirect_url_from(intent)
        attempt.save(update_fields=["paymongo_intent_id", "client_key", "qr_url", "redirect_url"])
        self._transition(attempt, PaymentAttempt.Status.AWAITING_ACTION)
        return attempt

    def _attach_method(self, intent, payment_method):
        """Create and attach a payment method to a freshly created intent.

        E-wallet payment methods (gcash/paymaya) require a ``return_url`` on
        the attach call: the page the customer lands on after provider
        authentication. QR Ph does not.
        """
        return_url = ""
        if payment_method in ("gcash", "paymaya"):
            return_url = f"{settings.BASE_URL.rstrip('/')}/payments/return/"
        method = self.client.create_payment_method(payment_method)
        attached = self.client.attach_payment_method(
            intent["id"], method["id"], intent.get("client_key"), return_url=return_url
        )
        return attached

    @staticmethod
    def _qr_url_from(intent):
        """Extract the QR image (Base64 data URL) from an attached intent.

        PayMongo returns it under ``next_action.code.image_url`` for QR Ph.
        """
        next_action = intent.get("next_action") or {}
        code = next_action.get("code") or {}
        return code.get("image_url", "") or ""

    @staticmethod
    def _redirect_url_from(intent):
        """Extract the provider authentication URL for e-wallet payments."""
        next_action = intent.get("next_action") or {}
        redirect = next_action.get("redirect") or {}
        return redirect.get("url", "") or ""

    def mark_payment_succeeded(self, attempt):
        return self._transition(attempt, PaymentAttempt.Status.SUCCEEDED)

    def mark_attempt_succeeded(self, attempt):
        """Transition an attempt to SUCCEEDED from any pre-success state.

        The async webhook can arrive while the attempt is still
        awaiting_method/awaiting_action, so it is routed through processing
        first. Idempotent: an already-succeeded attempt is returned untouched.
        """
        if attempt.status == PaymentAttempt.Status.SUCCEEDED:
            return attempt
        if attempt.status != PaymentAttempt.Status.PROCESSING:
            self._transition(attempt, PaymentAttempt.Status.PROCESSING)
        return self._transition(attempt, PaymentAttempt.Status.SUCCEEDED)

    def mark_payment_failed(self, attempt, code="", message=""):
        attempt.failure_code = code
        attempt.failure_message = message
        attempt.save(update_fields=["failure_code", "failure_message"])
        return self._transition(attempt, PaymentAttempt.Status.FAILED)

    def reconcile_payment(self, attempt):
        logger.info(
            "reconcile attempt=%s order=%s intent=%s current=%s",
            attempt.id,
            attempt.order_id,
            attempt.paymongo_intent_id,
            attempt.status,
        )
        intent = self.client.retrieve_payment_intent(attempt.paymongo_intent_id)
        status = intent.get("status")

        if status == "succeeded":
            if attempt.status != PaymentAttempt.Status.SUCCEEDED:
                if attempt.status != PaymentAttempt.Status.PROCESSING:
                    self._transition(attempt, PaymentAttempt.Status.PROCESSING)
                self._transition(attempt, PaymentAttempt.Status.SUCCEEDED)
            masked = masked_payment_method(intent.get("source"))
            if masked and not attempt.payment_method:
                attempt.payment_method = masked
                attempt.save(update_fields=["payment_method", "updated_at"])
            if intent.get("payment_id") and not attempt.paymongo_payment_id:
                attempt.paymongo_payment_id = intent["payment_id"]
                attempt.save(update_fields=["paymongo_payment_id", "updated_at"])
            if attempt.order.status != Order.Status.PAID:
                mark_order_paid(attempt.order)
        elif status == "processing":
            if attempt.status in (
                PaymentAttempt.Status.AWAITING_METHOD,
                PaymentAttempt.Status.AWAITING_ACTION,
            ):
                self._transition(attempt, PaymentAttempt.Status.PROCESSING)
        elif status == "awaiting_next_action":
            if attempt.status == PaymentAttempt.Status.AWAITING_METHOD:
                self._transition(attempt, PaymentAttempt.Status.AWAITING_ACTION)
        elif status == "failed":
            if attempt.status != PaymentAttempt.Status.FAILED:
                error = intent.get("last_payment_error") or {}
                self.mark_payment_failed(
                    attempt,
                    code=error.get("code", ""),
                    message=error.get("message", ""),
                )
        # awaiting_payment_method → leave the attempt as-is

        logger.info(
            "reconcile resolved attempt=%s status=%s",
            attempt.id,
            attempt.status,
        )
        return attempt

    def refund_payment(self, attempt, amount, reason=""):
        """Refund a paid attempt, tracking the provider state in a Refund row.

        The order total is never modified to represent a refund; a Refund row
        records the money movement. Refund rows start ``pending`` and are
        settled against PayMongo immediately; a network failure leaves the
        row ``pending`` for later reconciliation rather than marking it failed
        (the refund may still have been created provider-side).
        """
        if attempt.status != PaymentAttempt.Status.SUCCEEDED:
            raise ValueError("Only succeeded attempts can be refunded.")
        if amount <= 0 or amount > attempt.amount:
            raise ValueError("Refund amount must be within the paid amount.")

        refund = Refund.objects.create(
            payment=attempt,
            amount=amount,
            reason=reason,
            status=Refund.Status.PENDING,
        )

        try:
            result = self.client.refund_payment(
                payment_id=attempt.paymongo_payment_id or attempt.paymongo_intent_id,
                amount=amount,
                reason=reason,
            )
        except (PayMongoTimeoutError, PayMongoNetworkError):
            refund.failure_message = "still checking"
            refund.save(update_fields=["failure_message"])
            logger.warning(
                "refund ambiguous refund=%s attempt=%s amount=%s",
                refund.id,
                attempt.id,
                amount,
            )
            raise
        except PayMongoAPIError as exc:
            refund.status = Refund.Status.FAILED
            refund.failure_message = exc.message
            refund.save(update_fields=["status", "failure_message"])
            logger.error(
                "refund failed refund=%s attempt=%s code=%s message=%s",
                refund.id,
                attempt.id,
                exc.code,
                exc.message,
            )
            raise

        refund.provider_refund_id = result.get("id")
        if result.get("status") == "succeeded":
            refund.status = Refund.Status.SUCCEEDED
        refund.save(update_fields=["provider_refund_id", "status"])

        logger.info(
            "refund created refund=%s provider_refund_id=%s attempt=%s amount=%s",
            refund.id,
            refund.provider_refund_id,
            attempt.id,
            amount,
        )
        return refund
