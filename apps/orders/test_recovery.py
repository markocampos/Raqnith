"""Pending-payment recovery email tests ("your QR expired — fresh one here")."""
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.services.email_service import send_payment_recovery


class RecoveryTestBase(TestCase):
    def setUp(self):
        super().setUp()
        mail.outbox = []

    def make_pending(self, age_minutes=20, email="juan@example.com", **kwargs):
        tag = kwargs.pop("tag", "x")
        order = Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            session_key=f"sess-{tag}",
            status=Order.Status.PENDING_PAYMENT,
            **{"email": email, **kwargs},
        )
        if age_minutes:
            # auto_now_add overrides values passed to create(), so backdate
            # with an explicit update.
            Order.objects.filter(pk=order.pk).update(
                created_at=timezone.now() - timedelta(minutes=age_minutes)
            )
            order.refresh_from_db()
        return order


class RecoveryServiceTests(RecoveryTestBase):
    def test_sends_with_resume_link_and_total(self):
        order = self.make_pending()
        sent = send_payment_recovery(order)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)

        msg = mail.outbox[0]
        self.assertIn("juan@example.com", msg.to)
        self.assertIn("waiting", msg.subject.lower())
        body = msg.body
        self.assertIn(f"/orders/{str(order.id)[:8]}", body)  # resume link
        self.assertIn("₱1,120.00", body)
        self.assertEqual(len(msg.alternatives), 1)

    def test_idempotent_single_send(self):
        order = self.make_pending()
        self.assertTrue(send_payment_recovery(order))
        self.assertFalse(send_payment_recovery(order))
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_non_pending_orders(self):
        paid = self.make_pending()
        Order.objects.filter(pk=paid.pk).update(
            status=Order.Status.PAID, paid_at=timezone.now()
        )
        self.assertFalse(send_payment_recovery(Order.objects.get(pk=paid.pk)))
        self.assertEqual(len(mail.outbox), 0)

    def test_skips_missing_email(self):
        self.assertFalse(send_payment_recovery(self.make_pending(email="")))
        self.assertEqual(len(mail.outbox), 0)

    def test_failure_resets_guard_for_next_run(self):
        order = self.make_pending()
        with patch(
            "apps.orders.services.email_service.EmailMultiAlternatives.send",
            side_effect=ConnectionError("smtp down"),
        ):
            self.assertFalse(send_payment_recovery(order))
        order.refresh_from_db()
        self.assertIsNone(order.recovery_email_sent_at)


class RecoveryCommandTests(RecoveryTestBase):
    def _run(self, dry_run=False):
        call_command("send_recovery_emails", *(["--dry-run"] if dry_run else []))

    def test_eligible_order_gets_exactly_one_email(self):
        order = self.make_pending(age_minutes=20)
        self._run()
        self.assertEqual(len(mail.outbox), 1)
        order.refresh_from_db()
        self.assertIsNotNone(order.recovery_email_sent_at)

        # Second run: still nothing new.
        self._run()
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_sends_nothing(self):
        self.make_pending(age_minutes=20)
        call_command("send_recovery_emails", "--dry-run")
        self.assertEqual(len(mail.outbox), 0)

    def test_fresh_and_stale_orders_ignored(self):
        self.make_pending(age_minutes=5, tag="fresh")
        self.make_pending(age_minutes=55, tag="stale")
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_paid_orders_ignored_even_in_window(self):
        paid = self.make_pending(age_minutes=20)
        Order.objects.filter(pk=paid.pk).update(status=Order.Status.PAID)
        self._run()
        self.assertEqual(len(mail.outbox), 0)


class ResumeViewTests(TestCase):
    def test_resume_redirects_to_qr_screen_for_any_device(self):
        order = Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            session_key="whatever-device",
            status=Order.Status.PENDING_PAYMENT,
        )
        resp = self.client.get(reverse("orders:resume", args=[order.id]))
        self.assertRedirects(resp, reverse("checkout:order", args=[order.id]))

    def test_resume_unknown_order_404s(self):
        from uuid import uuid4

        resp = self.client.get(reverse("orders:resume", args=[uuid4()]))
        self.assertEqual(resp.status_code, 404)
