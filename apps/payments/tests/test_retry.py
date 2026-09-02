import json
from unittest.mock import patch

import httpx
from django.test import TestCase
from django.urls import reverse

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import ActiveAttemptExists, PaymentService
from apps.payments.tests.helpers import (
    intent_flow_handler,
    intent_payload,
    make_mock_client,
)


class InitiatePaymentHardeningTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=10000, total_amount=10000)

    def _service(self, handler):
        return PaymentService(client=make_mock_client(handler))

    def _ok_handler(self, intent_id="pi_test_1"):
        return intent_flow_handler(intent_id=intent_id)

    def test_active_attempt_blocks_second_initiate(self):
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            status=PaymentAttempt.Status.AWAITING_METHOD,
        )
        with self.assertRaises(ActiveAttemptExists):
            self._service(self._ok_handler()).initiate_payment(order=self.order)
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    def test_replace_stale_cancels_and_creates_new(self):
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            status=PaymentAttempt.Status.AWAITING_METHOD,
        )
        new = self._service(self._ok_handler()).initiate_payment(
            order=self.order, replace_stale=True
        )
        self.assertEqual(PaymentAttempt.objects.count(), 2)
        old = PaymentAttempt.objects.exclude(pk=new.pk).get()
        self.assertEqual(old.status, PaymentAttempt.Status.CANCELLED)
        self.assertEqual(new.status, PaymentAttempt.Status.AWAITING_ACTION)

    def test_replace_stale_blocks_inflight_processing(self):
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            status=PaymentAttempt.Status.PROCESSING,
        )
        with self.assertRaises(ActiveAttemptExists):
            self._service(self._ok_handler()).initiate_payment(order=self.order, replace_stale=True)

    def test_replace_stale_cancels_abandoned_awaiting_action(self):
        # QR/e-wallet only: an un-authenticated awaiting_action attempt is
        # pre-charge, so retry may cancel it.
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            status=PaymentAttempt.Status.AWAITING_ACTION,
        )
        new = self._service(self._ok_handler()).initiate_payment(
            order=self.order, replace_stale=True
        )
        old = PaymentAttempt.objects.exclude(pk=new.pk).get()
        self.assertEqual(old.status, PaymentAttempt.Status.CANCELLED)


class CreateIntentDoublePostTests(TestCase):
    def setUp(self):
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key=self.session_key
        )

    def _post(self):
        return self.client.post(
            reverse("payments:intents"),
            data=json.dumps({"order_id": str(self.order.id)}),
            content_type="application/json",
        )

    def test_second_post_returns_409_one_active_attempt(self):
        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(intent_flow_handler()),
        ):
            first = self._post()
            self.assertEqual(first.status_code, 201)
            second = self._post()
            self.assertEqual(second.status_code, 409)

        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertEqual(PaymentAttempt.objects.get().status, PaymentAttempt.Status.AWAITING_ACTION)


class RetryPaymentViewTests(TestCase):
    def setUp(self):
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000,
            total_amount=10000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.FAILED,
        )

    def _url(self, attempt=None):
        return reverse("payments:retry", args=[attempt.id if attempt else self.attempt.id])

    def test_retry_on_paid_order_rejected(self):
        self.order.transition_to(Order.Status.PAID)
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 409)

    def test_retry_creates_fresh_attempt(self):
        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(
                intent_flow_handler(intent_id="pi_test_2", client_key="ck_test_2")
            ),
        ):
            resp = self.client.post(self._url())

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["payment_intent_id"], "pi_test_2")
        self.assertEqual(resp.json()["qr_url"], "data:image/png;base64,aGVsbG8=")
        self.assertEqual(PaymentAttempt.objects.count(), 2)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.FAILED)
        self.assertEqual(
            PaymentAttempt.objects.exclude(pk=self.attempt.pk).get().status,
            PaymentAttempt.Status.AWAITING_ACTION,
        )

    def test_retry_reconciles_hidden_success(self):
        # Timeout during attach: the attempt is ambiguous, but the provider
        # actually succeeded. Retry must settle it without a second charge.
        self.attempt.status = PaymentAttempt.Status.AWAITING_METHOD
        self.attempt.save(update_fields=["status"])

        def handler(request):
            return httpx.Response(200, json=intent_payload(status="succeeded"))

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self.client.post(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "succeeded")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    def test_retry_other_session_returns_404(self):
        other = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key="someone-else"
        )
        other_attempt = PaymentAttempt.objects.create(
            order=other, amount=10000, paymongo_intent_id="pi_other"
        )
        resp = self.client.post(self._url(attempt=other_attempt))
        self.assertEqual(resp.status_code, 404)

    def test_retry_on_expired_order_rejected(self):
        from django.utils import timezone

        self.order.created_at = timezone.now() - timezone.timedelta(minutes=65)
        self.order.save(update_fields=["created_at"])
        resp = self.client.post(self._url())
        self.assertEqual(resp.status_code, 410)
        self.assertEqual(resp.json()["error"], "order_expired")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
