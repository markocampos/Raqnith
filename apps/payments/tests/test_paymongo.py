import json

import httpx
from django.test import TestCase

from apps.payments.services.paymongo import (
    InvalidWebhookSignature,
    PayMongoAPIError,
    PayMongoNetworkError,
    PayMongoTimeoutError,
    verify_webhook_signature,
)
from apps.payments.tests.helpers import (
    intent_payload,
    make_mock_client,
    sign_payload,
)


class PayMongoClientTests(TestCase):
    def test_create_intent_success(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), "https://api.paymongo.com/v1/payment_intents")
            attrs = json.loads(request.content)["data"]["attributes"]
            self.assertEqual(attrs["amount"], 10000)
            self.assertEqual(attrs["currency"], "PHP")
            self.assertEqual(attrs["payment_method_allowed"], ["qrph"])
            return httpx.Response(201, json=intent_payload(status="awaiting_payment_method"))

        client = make_mock_client(handler)
        intent = client.create_payment_intent(
            amount=10000, currency="PHP", payment_method_allowed=["qrph"]
        )
        self.assertEqual(intent["id"], "pi_test_1")
        self.assertEqual(intent["client_key"], "ck_test_1")
        self.assertEqual(intent["amount"], 10000)
        self.assertEqual(intent["currency"], "PHP")
        self.assertEqual(intent["status"], "awaiting_payment_method")

    def test_create_payment_method(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), "https://api.paymongo.com/v1/payment_methods")
            attrs = json.loads(request.content)["data"]["attributes"]
            self.assertEqual(attrs["type"], "gcash")
            return httpx.Response(201, json={"data": {"id": "pm_test_1", "type": "payment_method"}})

        client = make_mock_client(handler)
        method = client.create_payment_method("gcash")
        self.assertEqual(method["id"], "pm_test_1")

    def test_attach_payment_method_returns_qr_image(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertIn("/payment_intents/pi_test_1/attach", str(request.url))
            attrs = json.loads(request.content)["data"]["attributes"]
            self.assertEqual(attrs["payment_method"], "pm_test_1")
            return httpx.Response(200, json=intent_payload(qr_image_url="data:image/png;base64,QR"))

        client = make_mock_client(handler)
        intent = client.attach_payment_method("pi_test_1", "pm_test_1")
        self.assertEqual(intent["status"], "awaiting_next_action")
        self.assertEqual(
            intent["next_action"]["code"]["image_url"], "data:image/png;base64,QR"
        )

    def test_attach_payment_method_returns_redirect(self):
        def handler(request):
            return httpx.Response(
                200,
                json=intent_payload(redirect_url="https://pay.gcash.example/auth"),
            )

        client = make_mock_client(handler)
        intent = client.attach_payment_method("pi_test_1", "pm_test_1")
        self.assertEqual(intent["next_action"]["redirect"]["url"], "https://pay.gcash.example/auth")

    def test_retrieve_intent(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertIn("/payment_intents/pi_test_1", str(request.url))
            return httpx.Response(200, json=intent_payload(status="succeeded"))

        client = make_mock_client(handler)
        intent = client.retrieve_payment_intent("pi_test_1")
        self.assertEqual(intent["id"], "pi_test_1")
        self.assertEqual(intent["status"], "succeeded")

    def test_api_error_400(self):
        def handler(request):
            return httpx.Response(
                400, json={"errors": [{"code": "invalid_parameter", "detail": "amount is invalid"}]}
            )

        client = make_mock_client(handler)
        with self.assertRaises(PayMongoAPIError) as cm:
            client.create_payment_intent(amount=1, currency="PHP")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.code, "invalid_parameter")
        self.assertEqual(cm.exception.message, "amount is invalid")

    def test_api_error_401_429_500(self):
        for status in (401, 429, 500):
            def handler(request, status=status):
                return httpx.Response(
                    status, json={"errors": [{"code": f"err_{status}", "detail": "boom"}]}
                )

            client = make_mock_client(handler)
            with self.assertRaises(PayMongoAPIError) as cm:
                client.create_payment_intent(amount=1, currency="PHP")
            self.assertEqual(cm.exception.status_code, status)

    def test_timeout(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        client = make_mock_client(handler)
        with self.assertRaises(PayMongoTimeoutError):
            client.create_payment_intent(amount=1, currency="PHP")

    def test_network_error(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        client = make_mock_client(handler)
        with self.assertRaises(PayMongoNetworkError):
            client.create_payment_intent(amount=1, currency="PHP")


class VerifyWebhookSignatureTests(TestCase):
    def test_valid_live_signature(self):
        raw_body = b'{"data": {"id": "evt_1"}}'
        signature = sign_payload(raw_body, "whsec_test_stub", live=True)
        verify_webhook_signature(raw_body, signature, "whsec_test_stub")  # no raise

    def test_valid_test_mode_signature(self):
        raw_body = b'{"data": {"id": "evt_1"}}'
        signature = sign_payload(raw_body, "whsec_test_stub", live=False)
        verify_webhook_signature(raw_body, signature, "whsec_test_stub")  # no raise

    def test_valid_bare_hex_signature(self):
        import hashlib, hmac
        raw_body = b'{"data": {"id": "evt_1"}}'
        signature = hmac.new(b"whsec_test_stub", raw_body, hashlib.sha256).hexdigest()
        verify_webhook_signature(raw_body, signature, "whsec_test_stub")  # no raise

    def test_invalid_signature_raises(self):
        raw_body = b'{"data": {"id": "evt_1"}}'
        with self.assertRaises(InvalidWebhookSignature):
            verify_webhook_signature(raw_body, "t=1700000000,te=deadbeef,li=", "whsec_test_stub")

    def test_missing_signature_raises(self):
        raw_body = b'{"data": {"id": "evt_1"}}'
        with self.assertRaises(InvalidWebhookSignature):
            verify_webhook_signature(raw_body, None, "whsec_test_stub")

    def test_missing_secret_raises(self):
        raw_body = b'{"data": {"id": "evt_1"}}'
        with self.assertRaises(InvalidWebhookSignature):
            verify_webhook_signature(raw_body, "sig", "")

