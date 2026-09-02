import json
import uuid
from unittest.mock import patch

import httpx
from django.test import TestCase
from django.urls import reverse

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt
from apps.payments.tests.helpers import (
    intent_flow_handler,
    intent_payload,
    make_mock_client,
)


class CreateIntentViewTests(TestCase):
    def setUp(self):
        # Establish an anonymous session and an order owned by that session.
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key=self.session_key
        )

    def _post(self, order_id=None, payment_method=None):
        body = {"order_id": str(order_id or self.order.id)}
        if payment_method is not None:
            body["payment_method"] = payment_method
        return self.client.post(
            reverse("payments:intents"),
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_create_intent_success(self):
        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(intent_flow_handler()),
        ):
            resp = self._post()

        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["payment_intent_id"], "pi_test_1")
        self.assertEqual(body["client_key"], "ck_test_1")
        self.assertEqual(body["qr_url"], "data:image/png;base64,aGVsbG8=")
        self.assertEqual(body["redirect_url"], "")
        self.assertEqual(body["amount"], 10000)
        self.assertEqual(body["currency"], "PHP")

        attempt = PaymentAttempt.objects.get()
        self.assertEqual(body["payment_id"], str(attempt.id))
        self.assertEqual(attempt.status, PaymentAttempt.Status.AWAITING_ACTION)

    def test_create_intent_gcash_returns_redirect(self):
        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(
                intent_flow_handler(
                    payment_type="gcash", redirect_url="https://pay.gcash.example/auth"
                )
            ),
        ):
            resp = self._post(payment_method="gcash")

        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["qr_url"], "")
        self.assertEqual(body["redirect_url"], "https://pay.gcash.example/auth")

    def test_create_intent_invalid_payment_method_rejected(self):
        resp = self._post(payment_method="bitcoin")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PaymentAttempt.objects.count(), 0)

    def test_create_intent_defaults_to_qrph(self):
        def handler(request):
            if str(request.url).endswith("/payment_methods"):
                return httpx.Response(201, json={"data": {"id": "pm_1", "type": "payment_method"}})
            if "/attach" in str(request.url):
                return httpx.Response(
                    200,
                    json=intent_payload(qr_image_url="data:image/png;base64,aGVsbG8="),
                )
            return httpx.Response(201, json=intent_payload())

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self._post()

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["qr_url"], "data:image/png;base64,aGVsbG8=")

    def test_create_intent_api_error(self):
        def handler(request):
            return httpx.Response(
                400, json={"errors": [{"code": "invalid_parameter", "detail": "amount is invalid"}]}
            )

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self._post()

        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"], "invalid_parameter")
        attempt = PaymentAttempt.objects.get()
        self.assertEqual(attempt.status, PaymentAttempt.Status.FAILED)
        self.assertEqual(self.order.status, Order.Status.DRAFT)

    def test_create_intent_timeout(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        with patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        ):
            resp = self._post()

        self.assertEqual(resp.status_code, 504)
        attempt = PaymentAttempt.objects.get()
        self.assertEqual(attempt.status, PaymentAttempt.Status.AWAITING_METHOD)
        self.assertEqual(attempt.failure_message, "still checking")
        self.assertEqual(self.order.status, Order.Status.DRAFT)

    def test_paid_order_rejected(self):
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        resp = self._post()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(PaymentAttempt.objects.count(), 0)

    def test_wrong_session_returns_404(self):
        other = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key="someone-else"
        )
        resp = self._post(order_id=other.id)
        self.assertEqual(resp.status_code, 404)

    def test_missing_order_id_returns_400(self):
        resp = self.client.post(
            reverse("payments:intents"), data=json.dumps({}), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)


class PaymentStatusViewTests(TestCase):
    def setUp(self):
        # Establish an anonymous session and an order owned by that session.
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key=self.session_key
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            status=PaymentAttempt.Status.PROCESSING,
        )

    def test_returns_attempt_state_for_owner(self):
        resp = self.client.get(reverse("payments:status", args=[self.attempt.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], PaymentAttempt.Status.PROCESSING)
        self.assertEqual(body["failure_code"], "")
        self.assertEqual(body["failure_message"], "")

    def test_other_session_returns_404(self):
        other_order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key="someone-else"
        )
        other_attempt = PaymentAttempt.objects.create(order=other_order, amount=10000)
        resp = self.client.get(reverse("payments:status", args=[other_attempt.id]))
        self.assertEqual(resp.status_code, 404)

    def test_unknown_attempt_returns_404(self):
        resp = self.client.get(reverse("payments:status", args=[uuid.uuid4()]))
        self.assertEqual(resp.status_code, 404)


class PaymentReturnViewTests(TestCase):
    def setUp(self):
        # Establish an anonymous session and an order owned by that session.
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
            paymongo_intent_id="pi_return_test",
            status=PaymentAttempt.Status.AWAITING_ACTION,
        )

    def _get(self, intent_id="pi_return_test"):
        return self.client.get(reverse("payments:return"), {"payment_intent_id": intent_id})

    def _patch_client(self, handler):
        return patch(
            "apps.payments.services.payment_service.PayMongoClient",
            return_value=make_mock_client(handler),
        )

    def test_succeeded_intent_marks_order_paid_and_redirects(self):
        def handler(request):
            payload = intent_payload(intent_id="pi_return_test", status="succeeded")
            payload["data"]["attributes"]["source"] = {
                "id": "src_test_1",
                "type": "qrph",
            }
            return httpx.Response(200, json=payload)

        with self._patch_client(handler):
            resp = self._get()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("orders:success", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.SUCCEEDED)
        self.assertEqual(self.attempt.payment_method, "qrph")

    def test_still_authenticating_renders_confirming_page(self):
        def handler(request):
            return httpx.Response(200, json=intent_payload(status="awaiting_next_action"))

        with self._patch_client(handler):
            resp = self._get()

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "payments/return.html")
        self.assertContains(resp, "Confirming your payment")
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.AWAITING_ACTION)

    def test_failed_intent_redirects_to_status_page(self):
        def handler(request):
            payload = intent_payload(intent_id="pi_return_test", status="failed")
            payload["data"]["attributes"]["last_payment_error"] = {
                "code": "authentication_failed",
                "message": "Customer did not complete authentication",
            }
            return httpx.Response(200, json=payload)

        with self._patch_client(handler):
            resp = self._get()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("orders:status", args=[self.order.id]))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.FAILED)
        self.assertEqual(self.attempt.failure_code, "authentication_failed")
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.Status.PAID)

    def test_missing_intent_param_returns_404(self):
        resp = self.client.get(reverse("payments:return"))
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "payments/return.html")

    def test_forged_intent_id_returns_404(self):
        resp = self._get(intent_id="pi_someone_elses_intent")
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "payments/return.html")

    def test_other_sessions_attempt_returns_404(self):
        other_order = Order.objects.create(
            subtotal_amount=10000,
            total_amount=10000,
            session_key="someone-else",
        )
        PaymentAttempt.objects.create(
            order=other_order,
            amount=10000,
            paymongo_intent_id="pi_other_attempt",
        )
        resp = self._get(intent_id="pi_other_attempt")
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "payments/return.html")

    def test_provider_unreachable_renders_confirming_page(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        with self._patch_client(handler):
            resp = self._get()

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "payments/return.html")
        self.assertContains(resp, "Confirming your payment")
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.AWAITING_ACTION)

    def test_already_paid_order_redirects_to_success(self):
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        with self._patch_client(lambda request: httpx.Response(200, json={})):
            resp = self._get()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("orders:success", args=[self.order.id]))
