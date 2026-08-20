import json
import threading
from unittest.mock import patch

import httpx
from django.conf import settings
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt, WebhookEvent
from apps.payments.services.payment_service import ActiveAttemptExists, PaymentService
from apps.payments.tests.helpers import (
    intent_flow_handler,
    intent_payload,
    make_mock_client,
    payment_event_payload,
    sign_payload,
)


class RedirectBeforeWebhookTests(TestCase):
    """Race: the browser return arrives before the webhook."""

    def setUp(self):
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000,
            total_amount=10000,
            status=Order.Status.PENDING_PAYMENT,
            session_key=self.session_key,
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.AWAITING_ACTION,
        )

    def test_return_reconciles_then_webhook_is_noop(self):
        def handler(request):
            payload = intent_payload(intent_id="pi_test_1", status="succeeded")
            payload["data"]["attributes"]["source"] = {
                "id": "src_test_1",
                "type": "qrph",
            }
            return httpx.Response(200, json=payload)

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self.client.get(reverse("payments:return"), {"payment_intent_id": "pi_test_1"})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("orders:success", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        paid_at = self.order.paid_at
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)

        # The webhook then arrives — acknowledged, no double transition.
        payload = payment_event_payload(intent_id="pi_test_1", amount=10000, currency="PHP")
        raw_body = json.dumps(payload).encode()
        signature = sign_payload(raw_body, settings.PAYMONGO_WEBHOOK_SECRET)
        resp = self.client.post(
            reverse("payments:webhook"),
            data=raw_body,
            content_type="application/json",
            HTTP_PAYMONGO_SIGNATURE=signature,
        )
        self.assertEqual(resp.status_code, 200)

        self.order.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.paid_at, paid_at)
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)
        # The first delivery stores the provider payment id; status/paid_at are
        # untouched, so no double transition occurred.
        self.assertEqual(self.attempt.paymongo_payment_id, "pay_test_1")
        self.assertEqual(WebhookEvent.objects.count(), 1)


class ReopenOrderResolvesAmbiguousTests(TestCase):
    """Race: the browser closes while the payment is still processing."""

    def setUp(self):
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000,
            total_amount=10000,
            status=Order.Status.PENDING_PAYMENT,
            session_key=self.session_key,
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.PROCESSING,
        )

    def test_reopening_order_page_reconciles_hidden_success(self):
        # Provider actually succeeded while the browser reported a timeout/close.
        def handler(request):
            return httpx.Response(
                200, json=intent_payload(intent_id="pi_test_1", status="succeeded")
            )

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self.client.get(reverse("orders:status", args=[self.order.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "orders/detail.html")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)

    def test_reopening_with_failed_provider_shows_retry(self):
        def handler(request):
            return httpx.Response(
                200,
                json=intent_payload(intent_id="pi_test_1", status="failed"),
            )

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self.client.get(reverse("orders:status", args=[self.order.id]))

        self.assertEqual(resp.status_code, 200)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.FAILED)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.Status.PAID)


class ConcurrentInitiateTests(TransactionTestCase):
    """Race: two browser tabs submit payment for the same order at once."""

    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=10000, total_amount=10000)

    def test_two_tabs_yield_exactly_one_attempt(self):
        results = []
        errors = []

        def pay():
            try:
                with patch(
                    "apps.payments.services.payment_service.PayMongoClient",
                    return_value=make_mock_client(
                        intent_flow_handler(intent_id="pi_race_1")
                    ),
                ):
                    attempt = PaymentService().initiate_payment(order=self.order)
                results.append(attempt.id)
            except Exception as exc:  # noqa: BLE001 - captured for assertions
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=pay) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ActiveAttemptExists)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertEqual(
            PaymentAttempt.objects.get().status, PaymentAttempt.Status.AWAITING_ACTION
        )


class ConcurrentWebhookTests(TransactionTestCase):
    """Race: PayMongo delivers the same event twice concurrently."""

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
        self.payload = payment_event_payload(
            intent_id="pi_test_1", amount=10000, currency="PHP"
        )
        self.raw_body = json.dumps(self.payload).encode()
        self.signature = sign_payload(self.raw_body, settings.PAYMONGO_WEBHOOK_SECRET)
        self.url = reverse("payments:webhook")

    def test_duplicate_delivery_processed_once(self):
        statuses = []

        def deliver():
            try:
                resp = Client().post(
                    self.url,
                    data=self.raw_body,
                    content_type="application/json",
                    HTTP_PAYMONGO_SIGNATURE=self.signature,
                )
                statuses.append(resp.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=deliver) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(statuses), [200, 200])
        self.assertEqual(WebhookEvent.objects.count(), 1)
        self.assertTrue(WebhookEvent.objects.get().processed)
        self.order.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)
