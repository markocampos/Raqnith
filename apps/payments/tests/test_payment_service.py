import httpx
from django.test import TestCase

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import (
    AlreadyPaid,
    InvalidStateTransition,
    PaymentService,
    masked_payment_method,
)
from apps.payments.services.paymongo import PayMongoAPIError, PayMongoTimeoutError
from apps.payments.tests.helpers import (
    intent_flow_handler,
    intent_payload,
    make_mock_client,
    payment_method_payload,
)


def service_with(handler):
    return PaymentService(client=make_mock_client(handler))


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=10000, total_amount=10000)

    def test_initiate_success_qrph(self):
        attempt = service_with(intent_flow_handler()).initiate_payment(order=self.order)

        self.assertEqual(attempt.paymongo_intent_id, "pi_test_1")
        self.assertEqual(attempt.client_key, "ck_test_1")
        self.assertEqual(attempt.qr_url, "data:image/png;base64,aGVsbG8=")
        self.assertEqual(attempt.redirect_url, "")
        self.assertEqual(attempt.amount, 10000)
        self.assertEqual(attempt.currency, "PHP")
        self.assertEqual(attempt.status, PaymentAttempt.Status.AWAITING_ACTION)
        self.assertEqual(attempt.order_id, self.order.id)

    def test_initiate_gcash_stores_redirect_url(self):
        attempt = service_with(
            intent_flow_handler(
                payment_type="gcash", redirect_url="https://pay.gcash.example/auth"
            )
        ).initiate_payment(order=self.order, payment_method="gcash")

        self.assertEqual(attempt.qr_url, "")
        self.assertEqual(attempt.redirect_url, "https://pay.gcash.example/auth")
        self.assertEqual(attempt.status, PaymentAttempt.Status.AWAITING_ACTION)

    def test_initiate_without_next_action_stores_empty(self):
        def handler(request):
            path = str(request.url)
            if path.endswith("/payment_methods"):
                return httpx.Response(201, json=payment_method_payload())
            if "/attach" in path:
                return httpx.Response(
                    200, json=intent_payload(status="awaiting_payment_method")
                )
            return httpx.Response(201, json=intent_payload(status="awaiting_payment_method"))

        attempt = service_with(handler).initiate_payment(order=self.order)
        self.assertEqual(attempt.qr_url, "")
        self.assertEqual(attempt.redirect_url, "")

    def test_initiate_api_error_marks_failed(self):
        def handler(request):
            return httpx.Response(
                400, json={"errors": [{"code": "invalid_parameter", "detail": "amount is invalid"}]}
            )

        with self.assertRaises(PayMongoAPIError):
            service_with(handler).initiate_payment(order=self.order)

        attempt = PaymentAttempt.objects.get()
        self.assertEqual(attempt.status, PaymentAttempt.Status.FAILED)
        self.assertEqual(attempt.failure_code, "invalid_parameter")
        self.assertEqual(attempt.failure_message, "amount is invalid")
        self.assertEqual(self.order.status, Order.Status.DRAFT)

    def test_initiate_timeout_stays_awaiting_method(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        with self.assertRaises(PayMongoTimeoutError):
            service_with(handler).initiate_payment(order=self.order)

        attempt = PaymentAttempt.objects.get()
        self.assertEqual(attempt.status, PaymentAttempt.Status.AWAITING_METHOD)
        self.assertEqual(attempt.failure_message, "still checking")
        self.assertEqual(self.order.status, Order.Status.DRAFT)

    def test_paid_order_rejected(self):
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])

        with self.assertRaises(AlreadyPaid):
            PaymentService(client=object()).initiate_payment(order=self.order)
        self.assertEqual(PaymentAttempt.objects.count(), 0)

    def test_transition_guard_awaiting_method_to_succeeded(self):
        attempt = PaymentAttempt.objects.create(order=self.order, amount=10000)
        attempt.status = PaymentAttempt.Status.AWAITING_METHOD
        attempt.save(update_fields=["status"])

        with self.assertRaises(InvalidStateTransition):
            PaymentService().mark_payment_succeeded(attempt)

    def test_transition_awaiting_method_to_processing_then_succeeded(self):
        attempt = PaymentAttempt.objects.create(order=self.order, amount=10000)
        attempt.status = PaymentAttempt.Status.AWAITING_METHOD
        attempt.save(update_fields=["status"])

        service = PaymentService()
        service._transition(attempt, PaymentAttempt.Status.PROCESSING)
        service.mark_payment_succeeded(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.SUCCEEDED)


class MaskedPaymentMethodTests(TestCase):
    def test_card_keeps_brand_and_last4_only(self):
        self.assertEqual(
            masked_payment_method({"type": "card", "brand": "Visa", "last4": "4242"}),
            "visa •••• 4242",
        )

    def test_card_without_brand_or_last4(self):
        self.assertEqual(masked_payment_method({"type": "card"}), "card")

    def test_non_card_keeps_type(self):
        self.assertEqual(masked_payment_method({"type": "gcash"}), "gcash")

    def test_empty_source(self):
        self.assertEqual(masked_payment_method(None), "")
        self.assertEqual(masked_payment_method({}), "")

    def test_no_pan_substring(self):
        source = {
            "type": "card",
            "brand": "visa",
            "last4": "4242",
            "number": "4242424242424242",
        }
        self.assertNotIn("4242424242424242", masked_payment_method(source))
