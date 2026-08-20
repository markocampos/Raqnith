from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import PaymentService
from apps.payments.tests.helpers import intent_payload, make_mock_client


class ReconcilePaymentsCommandTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, status=Order.Status.PENDING_PAYMENT
        )

    def _stale_attempt(self, status=PaymentAttempt.Status.PROCESSING, updated_at=None):
        attempt = PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=status,
        )
        # auto_now overrides updated_at on save(); force it stale via .update().
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            updated_at=updated_at or (timezone.now() - timezone.timedelta(hours=1))
        )
        return PaymentAttempt.objects.get(pk=attempt.pk)

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("reconcile_payments", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_dry_run_lists_stale_without_calling_provider(self):
        attempt = self._stale_attempt()
        out, _ = self._run("--dry-run")
        self.assertIn("Found 1 stale attempt(s)", out)
        self.assertIn(str(attempt.id), out)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.PROCESSING)

    def test_fresh_attempt_not_considered_stale(self):
        self._stale_attempt(updated_at=timezone.now())
        out, _ = self._run("--dry-run")
        self.assertIn("Found 0 stale attempt(s)", out)

    def test_reconcile_settles_hidden_success(self):
        attempt = self._stale_attempt()

        def handler(request):
            return httpx.Response(200, json=intent_payload(status="succeeded"))

        with patch(
            "apps.payments.management.commands.reconcile_payments.PaymentService",
            return_value=PaymentService(client=make_mock_client(handler)),
        ):
            out, _ = self._run()

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.SUCCEEDED)
        self.assertIn("Done: 1 reconciled", out)

    def test_reconcile_marks_failed(self):
        attempt = self._stale_attempt(status=PaymentAttempt.Status.AWAITING_METHOD)

        def handler(request):
            return httpx.Response(200, json=intent_payload(status="failed"))

        with patch(
            "apps.payments.management.commands.reconcile_payments.PaymentService",
            return_value=PaymentService(client=make_mock_client(handler)),
        ):
            out, _ = self._run()

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.FAILED)

    def test_reconcile_errors_are_reported(self):
        self._stale_attempt()

        def handler(request):
            raise httpx.TimeoutException("timed out")

        with patch(
            "apps.payments.management.commands.reconcile_payments.PaymentService",
            return_value=PaymentService(client=make_mock_client(handler)),
        ):
            out, err = self._run()

        self.assertIn("reconcile error attempt=", err)
        self.assertIn("Done: 0 reconciled, 1 errored", out)
