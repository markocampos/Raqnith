"""Explicit PaymentAttempt state machine — single source of truth.

A payment attempt is a separate state machine from its order. Every status
change must follow one of the allowed edges below; the enforcement lives in
``PaymentService._transition``. Tests import this map so the allowed/forbidden
transitions are asserted against the same data the service uses.
"""

from apps.payments.models import PaymentAttempt

# A given status may only move to the statuses listed here. SUCCEEDED is only
# reachable via PROCESSING (or through the async webhook path, which routes
# through PROCESSING first).
PAYMENT_ATTEMPT_TRANSITIONS = {
    PaymentAttempt.Status.CREATED: {
        PaymentAttempt.Status.AWAITING_METHOD,
        PaymentAttempt.Status.AWAITING_ACTION,
        PaymentAttempt.Status.FAILED,
        PaymentAttempt.Status.CANCELLED,
    },
    PaymentAttempt.Status.AWAITING_METHOD: {
        PaymentAttempt.Status.AWAITING_ACTION,
        PaymentAttempt.Status.PROCESSING,
        PaymentAttempt.Status.FAILED,
        PaymentAttempt.Status.CANCELLED,
    },
    PaymentAttempt.Status.AWAITING_ACTION: {
        PaymentAttempt.Status.PROCESSING,
        PaymentAttempt.Status.FAILED,
        PaymentAttempt.Status.CANCELLED,
    },
    PaymentAttempt.Status.PROCESSING: {
        PaymentAttempt.Status.SUCCEEDED,
        PaymentAttempt.Status.FAILED,
    },
    PaymentAttempt.Status.SUCCEEDED: set(),
    PaymentAttempt.Status.FAILED: set(),
    PaymentAttempt.Status.CANCELLED: set(),
}

# Attempts in any of these states could still settle or be attached; an order
# may have at most one of them at a time.
ACTIVE_ATTEMPT_STATUSES = [
    PaymentAttempt.Status.CREATED,
    PaymentAttempt.Status.AWAITING_METHOD,
    PaymentAttempt.Status.AWAITING_ACTION,
    PaymentAttempt.Status.PROCESSING,
]

# Pre-charge attempts: no money has moved yet, so they are safe to cancel when
# a fresh attempt replaces them (retry path). AWAITING_ACTION is included
# because this checkout is QR Ph / e-wallet only: no 3DS is in flight, and an
# un-authenticated attach has not moved any money.
STALE_ATTEMPT_STATUSES = [
    PaymentAttempt.Status.CREATED,
    PaymentAttempt.Status.AWAITING_METHOD,
    PaymentAttempt.Status.AWAITING_ACTION,
]


def is_valid_transition(from_status, to_status):
    """Return True when ``from_status -> to_status`` is an allowed edge."""
    return to_status in PAYMENT_ATTEMPT_TRANSITIONS.get(from_status, set())
