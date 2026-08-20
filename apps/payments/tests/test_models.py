from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt, WebhookEvent
from apps.payments.selectors import get_attempt_for_user


class PaymentAttemptTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=1000, total_amount=1000)

    def test_defaults(self):
        attempt = PaymentAttempt.objects.create(order=self.order, amount=1000)
        self.assertEqual(attempt.status, PaymentAttempt.Status.CREATED)
        self.assertEqual(attempt.provider, "paymongo")
        self.assertEqual(attempt.currency, "PHP")
        self.assertEqual(attempt.payment_method, "")
        self.assertEqual(attempt.failure_code, "")
        self.assertEqual(attempt.failure_message, "")
        self.assertIsNone(attempt.paymongo_intent_id)
        self.assertEqual(attempt.client_key, "")

    def test_status_choices(self):
        expected = {
            PaymentAttempt.Status.CREATED,
            PaymentAttempt.Status.AWAITING_METHOD,
            PaymentAttempt.Status.AWAITING_ACTION,
            PaymentAttempt.Status.PROCESSING,
            PaymentAttempt.Status.SUCCEEDED,
            PaymentAttempt.Status.FAILED,
            PaymentAttempt.Status.CANCELLED,
        }
        self.assertEqual(set(PaymentAttempt.Status), expected)

    def test_paymongo_intent_id_unique(self):
        PaymentAttempt.objects.create(order=self.order, amount=1000, paymongo_intent_id="pi_1")
        with self.assertRaises(IntegrityError):
            PaymentAttempt.objects.create(order=self.order, amount=1000, paymongo_intent_id="pi_1")

    def test_money_field_rejects_float(self):
        with self.assertRaises(ValueError):
            PaymentAttempt.objects.create(order=self.order, amount=9.99)

    def test_money_field_rejects_negative(self):
        attempt = PaymentAttempt(order=self.order, amount=-5)
        with self.assertRaises(ValidationError):
            attempt.full_clean()

    def test_order_delete_is_protected(self):
        PaymentAttempt.objects.create(order=self.order, amount=1000)
        with self.assertRaises(ProtectedError):
            self.order.delete()


class WebhookEventTests(TestCase):
    def test_provider_event_id_unique(self):
        WebhookEvent.objects.create(
            provider_event_id="evt_1", event_type="payment.paid", payload={}
        )
        with self.assertRaises(IntegrityError):
            WebhookEvent.objects.create(
                provider_event_id="evt_1", event_type="payment.paid", payload={}
            )

    def test_defaults(self):
        event = WebhookEvent.objects.create(
            provider_event_id="evt_2", event_type="payment.paid", payload={"a": 1}
        )
        self.assertFalse(event.processed)
        self.assertIsNone(event.processed_at)
        self.assertEqual(event.payload, {"a": 1})


class SelectorTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=1000, total_amount=1000)

    def test_get_attempt_for_user(self):
        attempt = PaymentAttempt.objects.create(order=self.order, amount=1000)
        self.assertEqual(get_attempt_for_user(attempt.id, self.order), attempt)

    def test_get_attempt_for_user_wrong_order(self):
        attempt = PaymentAttempt.objects.create(order=self.order, amount=1000)
        other = Order.objects.create(subtotal_amount=1000, total_amount=1000)
        with self.assertRaises(PaymentAttempt.DoesNotExist):
            get_attempt_for_user(attempt.id, other)
