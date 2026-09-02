from django.test import TestCase

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt
from apps.payments.services.state_machine import (
    PAYMENT_ATTEMPT_TRANSITIONS,
    is_valid_transition,
)


class PaymentAttemptTransitionTests(TestCase):
    """Exhaustively assert every allowed and forbidden attempt edge.

    The map under test is the same one the service enforces at runtime, so
    these tests document and lock the lifecycle: created → awaiting_action
    (attach happens server-side immediately) → processing → succeeded/failed,
    with terminal states frozen.
    """

    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=10000, total_amount=10000)

    def _attempt(self, status):
        return PaymentAttempt.objects.create(order=self.order, amount=10000, status=status)

    def test_expected_transition_map(self):
        expected = {
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
        self.assertEqual(PAYMENT_ATTEMPT_TRANSITIONS, expected)

    def test_valid_transitions_match_map(self):
        for from_status, to_statuses in PAYMENT_ATTEMPT_TRANSITIONS.items():
            for to_status in to_statuses:
                with self.subTest(from_status=from_status, to_status=to_status):
                    self.assertTrue(is_valid_transition(from_status, to_status))

    def test_invalid_transitions_rejected(self):
        for from_status in PAYMENT_ATTEMPT_TRANSITIONS:
            allowed = PAYMENT_ATTEMPT_TRANSITIONS[from_status]
            for to_status in PaymentAttempt.Status:
                if to_status in allowed:
                    continue
                with self.subTest(from_status=from_status, to_status=to_status):
                    self.assertFalse(is_valid_transition(from_status, to_status))

    def test_terminal_states_are_frozen(self):
        for terminal in (
            PaymentAttempt.Status.SUCCEEDED,
            PaymentAttempt.Status.FAILED,
            PaymentAttempt.Status.CANCELLED,
        ):
            for target in PaymentAttempt.Status:
                with self.subTest(terminal=terminal, target=target):
                    self.assertFalse(is_valid_transition(terminal, target))

    def test_succeeded_only_reachable_via_processing(self):
        # succeeded must NOT be reachable directly from pre-processing states.
        for status in (
            PaymentAttempt.Status.CREATED,
            PaymentAttempt.Status.AWAITING_METHOD,
            PaymentAttempt.Status.AWAITING_ACTION,
        ):
            self.assertNotIn(
                PaymentAttempt.Status.SUCCEEDED,
                PAYMENT_ATTEMPT_TRANSITIONS[status],
            )


class OrderTransitionTests(TestCase):
    """Exhaustively assert Order lifecycle edges (the AGENTS.md Phase 19 map)."""

    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=10000, total_amount=10000)

    def test_expected_transition_map(self):
        expected = {
            Order.Status.DRAFT: {Order.Status.PENDING_PAYMENT, Order.Status.CANCELLED},
            Order.Status.PENDING_PAYMENT: {
                Order.Status.PAID,
                Order.Status.PAYMENT_FAILED,
                Order.Status.CANCELLED,
            },
            Order.Status.PAYMENT_FAILED: {
                Order.Status.PENDING_PAYMENT,
                Order.Status.CANCELLED,
            },
            Order.Status.PAID: {Order.Status.FULFILLED},
            Order.Status.FULFILLED: set(),
            Order.Status.CANCELLED: set(),
        }
        self.assertEqual(Order.ALLOWED_TRANSITIONS, expected)

    def test_valid_transitions_apply(self):
        cases = [
            (Order.Status.DRAFT, Order.Status.PENDING_PAYMENT),
            (Order.Status.DRAFT, Order.Status.CANCELLED),
            (Order.Status.PENDING_PAYMENT, Order.Status.PAID),
            (Order.Status.PENDING_PAYMENT, Order.Status.PAYMENT_FAILED),
            (Order.Status.PENDING_PAYMENT, Order.Status.CANCELLED),
            (Order.Status.PAYMENT_FAILED, Order.Status.PENDING_PAYMENT),
            (Order.Status.PAYMENT_FAILED, Order.Status.CANCELLED),
            (Order.Status.PAID, Order.Status.FULFILLED),
        ]
        for from_status, to_status in cases:
            with self.subTest(from_status=from_status, to_status=to_status):
                order = Order.objects.create(
                    subtotal_amount=10000, total_amount=10000, status=from_status
                )
                order.transition_to(to_status)
                self.assertEqual(order.status, to_status)

    def test_invalid_transitions_raise(self):
        for from_status in Order.Status:
            allowed = Order.ALLOWED_TRANSITIONS[from_status]
            for to_status in Order.Status:
                if to_status == from_status or to_status in allowed:
                    continue
                with self.subTest(from_status=from_status, to_status=to_status):
                    order = Order.objects.create(
                        subtotal_amount=10000, total_amount=10000, status=from_status
                    )
                    with self.assertRaises(ValueError):
                        order.transition_to(to_status)

    def test_paid_sets_paid_at_once(self):
        order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, status=Order.Status.PENDING_PAYMENT
        )
        order.transition_to(Order.Status.PAID)
        first_paid_at = order.paid_at
        self.assertIsNotNone(first_paid_at)
        order.transition_to(Order.Status.FULFILLED)
        order.refresh_from_db()
        self.assertEqual(order.paid_at, first_paid_at)

    def test_terminal_states_are_frozen(self):
        for terminal in (Order.Status.FULFILLED, Order.Status.CANCELLED):
            for target in Order.Status:
                if target == terminal:
                    continue
                with self.subTest(terminal=terminal, target=target):
                    order = Order.objects.create(
                        subtotal_amount=10000,
                        total_amount=10000,
                        status=terminal,
                    )
                    with self.assertRaises(ValueError):
                        order.transition_to(target)
