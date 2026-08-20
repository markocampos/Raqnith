import httpx
from django.test import TestCase

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt, Refund
from apps.payments.services.payment_service import PaymentService
from apps.payments.services.paymongo import PayMongoAPIError
from apps.payments.tests.helpers import make_mock_client


def refund_payload(refund_id="rfr_test_1", amount=10000, status="succeeded"):
    return {
        "data": {
            "id": refund_id,
            "type": "refund",
            "attributes": {
                "amount": amount,
                "currency": "PHP",
                "status": status,
                "payment_id": "pay_test_1",
            },
        }
    }


class PayMongoRefundClientTests(TestCase):
    def test_refund_creates_refund(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), "https://api.paymongo.com/v1/refunds")
            attrs = request.content
            self.assertIn(b'"payment_id":"pay_test_1"', attrs)
            self.assertIn(b'"amount":5000', attrs)
            return httpx.Response(201, json=refund_payload(amount=5000))

        client = make_mock_client(handler)
        result = client.refund_payment(
            payment_id="pay_test_1", amount=5000, reason="requested_by_customer"
        )
        self.assertEqual(result["id"], "rfr_test_1")
        self.assertEqual(result["amount"], 5000)
        self.assertEqual(result["status"], "succeeded")


class RefundServiceTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, status=Order.Status.PAID
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            paymongo_payment_id="pay_test_1",
            status=PaymentAttempt.Status.SUCCEEDED,
        )

    def test_refund_success_creates_succeeded_refund(self):
        def handler(request):
            return httpx.Response(201, json=refund_payload())

        refund = PaymentService(client=make_mock_client(handler)).refund_payment(
            self.attempt, amount=10000
        )

        self.assertEqual(refund.status, Refund.Status.SUCCEEDED)
        self.assertEqual(refund.provider_refund_id, "rfr_test_1")
        self.assertEqual(refund.payment, self.attempt)
        self.assertEqual(refund.amount, 10000)

    def test_refund_api_error_marks_failed(self):
        def handler(request):
            return httpx.Response(
                400, json={"errors": [{"code": "invalid_parameter", "detail": "amount too big"}]}
            )

        with self.assertRaises(PayMongoAPIError):
            PaymentService(client=make_mock_client(handler)).refund_payment(
                self.attempt, amount=10000
            )

        refund = Refund.objects.get()
        self.assertEqual(refund.status, Refund.Status.FAILED)
        self.assertEqual(refund.failure_message, "amount too big")

    def test_refund_timeout_stays_pending(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        from apps.payments.services.paymongo import PayMongoTimeoutError

        with self.assertRaises(PayMongoTimeoutError):
            PaymentService(client=make_mock_client(handler)).refund_payment(
                self.attempt, amount=10000
            )

        refund = Refund.objects.get()
        self.assertEqual(refund.status, Refund.Status.PENDING)
        self.assertEqual(refund.failure_message, "still checking")

    def test_refund_rejects_non_succeeded_attempt(self):
        self.attempt.status = PaymentAttempt.Status.AWAITING_METHOD
        self.attempt.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            PaymentService().refund_payment(self.attempt, amount=10000)
        self.assertEqual(Refund.objects.count(), 0)

    def test_refund_rejects_bad_amount(self):
        with self.assertRaises(ValueError):
            PaymentService().refund_payment(self.attempt, amount=20000)
        with self.assertRaises(ValueError):
            PaymentService().refund_payment(self.attempt, amount=0)
        self.assertEqual(Refund.objects.count(), 0)
