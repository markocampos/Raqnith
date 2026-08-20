import json

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt, WebhookEvent
from apps.payments.tests.helpers import payment_event_payload, sign_payload


class WebhookTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            subtotal_amount=10000,
            total_amount=10000,
            status=Order.Status.PENDING_PAYMENT,
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            currency="PHP",
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.AWAITING_METHOD,
        )
        self.url = reverse("payments:webhook")

    def _post(self, payload, secret=None, signature=None):
        raw_body = json.dumps(payload).encode()
        if signature is None:
            signature = sign_payload(raw_body, secret or settings.PAYMONGO_WEBHOOK_SECRET)
        return self.client.post(
            self.url,
            data=raw_body,
            content_type="application/json",
            HTTP_PAYMONGO_SIGNATURE=signature,
        )

    # ---- happy path ----

    def test_valid_signature_marks_paid(self):
        payload = payment_event_payload(intent_id="pi_test_1", amount=10000, currency="PHP")
        resp = self._post(payload)

        self.assertEqual(resp.status_code, 200)
        self.attempt.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)
        self.assertEqual(self.attempt.payment_method, "qrph")
        self.assertEqual(self.attempt.paymongo_payment_id, "pay_test_1")
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)

        event = WebhookEvent.objects.get()
        self.assertTrue(event.processed)
        self.assertIsNotNone(event.processed_at)
        self.assertEqual(event.event_type, "payment.paid")
        # Exactly one attempt and one event were involved.
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_invalid_signature_returns_401(self):
        payload = payment_event_payload(intent_id="pi_test_1")
        resp = self._post(payload, signature="deadbeef")

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(WebhookEvent.objects.count(), 0)
        self.attempt.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.AWAITING_METHOD)
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)

    def test_missing_signature_returns_401(self):
        payload = payment_event_payload(intent_id="pi_test_1")
        raw_body = json.dumps(payload).encode()
        resp = self.client.post(
            self.url, data=raw_body, content_type="application/json"
        )

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_duplicate_event_is_noop(self):
        payload = payment_event_payload(intent_id="pi_test_1")
        first = self._post(payload)
        self.assertEqual(first.status_code, 200)

        self.order.refresh_from_db()
        paid_at = self.order.paid_at
        self.attempt.refresh_from_db()
        succeeded_at = self.attempt.updated_at

        second = self._post(payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WebhookEvent.objects.count(), 1)

        self.order.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.paid_at, paid_at)
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)
        self.assertEqual(self.attempt.updated_at, succeeded_at)

    def test_amount_mismatch_not_paid(self):
        payload = payment_event_payload(intent_id="pi_test_1", amount=50000)
        with self.assertLogs("apps.payments.services.webhook_service", level="WARNING") as logs:
            resp = self._post(payload)

        self.assertEqual(resp.status_code, 200)
        self.attempt.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.AWAITING_METHOD)
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)
        self.assertIsNone(self.order.paid_at)
        self.assertTrue(any("mismatch" in line for line in logs.output))

    def test_currency_mismatch_not_paid(self):
        payload = payment_event_payload(intent_id="pi_test_1", currency="USD")
        with self.assertLogs("apps.payments.services.webhook_service", level="WARNING") as logs:
            resp = self._post(payload)

        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)
        self.assertTrue(any("mismatch" in line for line in logs.output))

    def test_unknown_event_type_recorded_unprocessed(self):
        payload = payment_event_payload(event_type="some.unknown.event")
        resp = self._post(payload)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(WebhookEvent.objects.count(), 1)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.event_type, "some.unknown.event")
        self.assertFalse(event.processed)
        self.assertIsNone(event.processed_at)

    def test_paid_stores_masked_card_method(self):
        payload = payment_event_payload(
            intent_id="pi_test_1",
            amount=10000,
            currency="PHP",
            payment_method="card",
            brand="Visa",
            last4="4242",
        )
        resp = self._post(payload)

        self.assertEqual(resp.status_code, 200)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.payment_method, "visa •••• 4242")

    def test_webhook_before_return_is_idempotent(self):
        # The webhook settles first; a later replay (what the return-view
        # reconciliation would effectively do) must not double-transition.
        payload = payment_event_payload(intent_id="pi_test_1")
        self.assertEqual(self._post(payload).status_code, 200)

        self.order.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)

        # Replaying the same event again is a no-op.
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_webhook_url_aliases_accepted(self):
        for alias_url in ("/webhook/paymongo/", "/webhooks/paymongo/", "/payments/webhook/paymongo/"):
            payload = payment_event_payload(
                event_id=f"evt_{alias_url.replace('/', '_')}",
                intent_id="pi_test_1",
            )
            raw_body = json.dumps(payload).encode()
            sig = sign_payload(raw_body, settings.PAYMONGO_WEBHOOK_SECRET)
            resp = self.client.post(
                alias_url,
                data=raw_body,
                content_type="application/json",
                HTTP_PAYMONGO_SIGNATURE=sig,
            )
            self.assertEqual(resp.status_code, 200, f"Failed on alias: {alias_url}")

    def test_qrph_expired_webhook_marks_attempt_failed(self):
        payload = payment_event_payload(
            event_id="evt_qr_exp_1",
            event_type="qrph.expired",
            intent_id="pi_test_1",
        )
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.FAILED)
        self.assertEqual(self.attempt.failure_code, "qr_expired")


