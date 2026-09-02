"""Delivery, downloads, magic access links, and confirmation email tests.

Also regression-covers the settlement crash that 500'd the receipt page:
money arriving for an order locally CANCELLED/FULFILLED must settle cleanly.
"""

from unittest.mock import patch

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, ProductFile
from apps.orders.models import Order, OrderItem
from apps.orders.services.delivery import (
    order_access_token,
    resolve_access_token,
)
from apps.orders.services.email_service import send_order_confirmation
from apps.orders.services.order_service import mark_order_paid
from apps.payments.models import PaymentAttempt


def make_paid_order(session_key, **kwargs):
    kwargs.setdefault("email", "juan@example.com")
    order = Order.objects.create(
        subtotal_amount=100000,
        total_amount=112000,
        session_key=session_key,
        status=Order.Status.PAID,
        paid_at=timezone.now(),
        **kwargs,
    )
    return order


def attach_file(order, product=None, **file_kwargs):
    items = list(order.items.select_related("product"))
    if product is None:
        product = (
            items[0].product
            if items
            else Product.objects.create(
                name="Starter Kit", slug=f"kit-{str(order.id)[:8]}", price_cents=100000
            )
        )
    if not any(item.product_id == product.id for item in items):
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name, unit_price_cents=100000
        )
    defaults = dict(
        name="starter-kit.zip",
        kind=ProductFile.Kind.DOWNLOAD,
        file=SimpleUploadedFile("starter-kit.zip", b"zip-bytes"),
    )
    defaults.update(file_kwargs)
    return ProductFile.objects.create(product=product, **defaults)


class SessionClientMixin(TestCase):
    def setUp(self):
        super().setUp()
        # Establish a session so the guest "owns" created orders.
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key


class MarkOrderPaidToleranceTests(SessionClientMixin):
    """mark_order_paid must never raise — money is authoritative."""

    def test_pending_transitions_normally(self):
        order = Order.objects.create(
            subtotal_amount=1000,
            total_amount=1000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
        )
        mark_order_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertIsNotNone(order.paid_at)

    def test_already_paid_is_noop(self):
        order = make_paid_order(self.session_key)
        before = order.paid_at
        mark_order_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.paid_at, before)

    def test_fulfilled_does_not_raise_and_stays_settled(self):
        order = make_paid_order(self.session_key)
        order.transition_to(Order.Status.FULFILLED)
        mark_order_paid(order)  # previously raised ValueError → 500 loop
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FULFILLED)

    def test_cancelled_with_money_force_settles(self):
        """Regression: webhook/poll for a cancelled-but-paid order 500'd."""
        order = Order.objects.create(
            subtotal_amount=1000,
            total_amount=1000,
            session_key=self.session_key,
            status=Order.Status.CANCELLED,
            email="juan@example.com",
        )
        with self.assertLogs("apps.orders.services.order_service", level="ERROR"):
            mark_order_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertIsNotNone(order.paid_at)


class ReceiptPageRegressionTests(SessionClientMixin):
    """/orders/<id>/receipt/ must render (not 500/redirect-loop) once settled."""

    def test_receipt_renders_for_fulfilled_order(self):
        order = make_paid_order(self.session_key)
        order.transition_to(Order.Status.FULFILLED)
        resp = self.client.get(reverse("orders:receipt", args=[order.id]))
        self.assertEqual(resp.status_code, 200)

    def test_status_page_renders_paid_for_fulfilled_order(self):
        order = make_paid_order(self.session_key)
        order.transition_to(Order.Status.FULFILLED)
        resp = self.client.get(reverse("orders:status", args=[order.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Payment confirmed")

    def test_success_renders_for_fulfilled_order(self):
        order = make_paid_order(self.session_key)
        order.transition_to(Order.Status.FULFILLED)
        resp = self.client.get(reverse("orders:success", args=[order.id]))
        self.assertEqual(resp.status_code, 200)


class DownloadViewTests(SessionClientMixin):
    def setUp(self):
        super().setUp()
        self.order = make_paid_order(self.session_key)
        self.file_obj = attach_file(self.order)

    def test_owner_downloads_file(self):
        resp = self.client.get(
            reverse("orders:download_file", args=[self.order.id, self.file_obj.id])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), b"zip-bytes")
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_other_session_gets_404(self):
        other = make_paid_order("someone-else-session")
        foreign_file = attach_file(other)
        resp = self.client.get(reverse("orders:download_file", args=[other.id, foreign_file.id]))
        self.assertEqual(resp.status_code, 404)

    def test_unpaid_order_redirects_to_status(self):
        pending = Order.objects.create(
            subtotal_amount=1000,
            total_amount=1000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
        )
        file_for_pending = attach_file(pending)
        resp = self.client.get(
            reverse("orders:download_file", args=[pending.id, file_for_pending.id])
        )
        self.assertRedirects(resp, reverse("orders:status", args=[pending.id]))

    def test_stream_kind_redirects_to_external_url(self):
        stream = attach_file(
            self.order,
            name="Lesson 1 Video",
            kind=ProductFile.Kind.STREAM,
            external_url="https://video.example.com/lesson-1",
        )
        resp = self.client.get(reverse("orders:download_file", args=[self.order.id, stream.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://video.example.com/lesson-1")

    def test_inactive_file_404s(self):
        self.file_obj.is_active = False
        self.file_obj.save()
        resp = self.client.get(
            reverse("orders:download_file", args=[self.order.id, self.file_obj.id])
        )
        self.assertEqual(resp.status_code, 404)

    def test_receipt_lists_deliverables(self):
        resp = self.client.get(reverse("orders:receipt", args=[self.order.id]))
        self.assertContains(resp, "Your Downloads")
        self.assertContains(resp, "starter-kit.zip")


class MagicAccessLinkTests(SessionClientMixin):
    def setUp(self):
        super().setUp()
        self.order = make_paid_order("original-device-session")

    def test_token_roundtrip(self):
        token = order_access_token(self.order)
        self.assertEqual(resolve_access_token(token).id, self.order.id)

    def test_tampered_token_rejected(self):
        self.assertIsNone(resolve_access_token("garbage-token"))

    def test_expired_token_rejected(self):
        from apps.orders.services import delivery

        token = signing.dumps(str(self.order.id), salt=delivery.ACCESS_SALT)
        with patch.object(delivery, "ACCESS_TOKEN_MAX_AGE", -1):
            self.assertIsNone(resolve_access_token(token))

    def test_link_adopts_session_and_lands_on_receipt(self):
        token = order_access_token(self.order)
        resp = self.client.get(reverse("orders:access", args=[token]), follow=True)
        self.assertContains(resp, "Order receipt")
        # The order now belongs to this visitor's session.
        self.assertEqual(
            Order.objects.get(id=self.order.id).session_key,
            self.client.session.session_key,
        )

    def test_invalid_link_shows_friendly_404(self):
        resp = self.client.get(reverse("orders:access", args=["bad-token"]))
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "expired", status_code=404)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ConfirmationEmailTests(SessionClientMixin):
    def setUp(self):
        super().setUp()
        from django.core import mail

        self.mail = mail
        mail.outbox = []
        self.order = make_paid_order(self.session_key)
        attach_file(self.order)

    def test_sends_single_email_with_access_link(self):
        sent = send_order_confirmation(self.order)
        self.assertTrue(sent)
        self.assertEqual(len(self.mail.outbox), 1)
        msg = self.mail.outbox[0]
        self.assertIn("juan@example.com", msg.to)
        self.assertIn("#" + str(self.order.id)[:8], msg.subject)
        body = msg.body
        self.assertIn("/orders/a/", body)  # signed magic link
        self.assertIn("/orders/" + str(self.order.id)[:8], body[:0] + body)  # receipt link present
        self.assertEqual(len(msg.alternatives), 1)  # HTML alternative attached

    def test_idempotent_no_double_send(self):
        send_order_confirmation(self.order)
        again = send_order_confirmation(self.order)
        self.assertFalse(again)
        self.assertEqual(len(self.mail.outbox), 1)

    def test_skips_orders_without_email(self):
        order = make_paid_order(self.session_key, email="")
        self.assertFalse(send_order_confirmation(order))
        self.assertEqual(len(self.mail.outbox), 0)

    def test_failure_resets_guard_for_retry(self):
        with patch(
            "apps.orders.services.email_service.EmailMultiAlternatives.send",
            side_effect=ConnectionError("smtp down"),
        ):
            sent = send_order_confirmation(self.order)
        self.assertFalse(sent)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.confirmation_sent_at)
        # Retry works after transient failure.
        self.assertTrue(send_order_confirmation(self.order))

    def test_mark_order_paid_queues_email_on_commit(self):
        order = Order.objects.create(
            subtotal_amount=1000,
            total_amount=1000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
            email="juan@example.com",
        )
        product = Product.objects.create(
            name="Commit Kit", slug=f"commit-{str(order.id)[:8]}", price_cents=100000
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price_cents=100000,
        )
        with self.captureOnCommitCallbacks(execute=True):
            mark_order_paid(order)
        self.assertEqual(len(self.mail.outbox), 1)


class CheckoutCancelGuardTests(SessionClientMixin):
    """A new checkout must NOT cancel a pending order already paid upstream."""

    def _seed_cart(self):
        from apps.cart.models import Cart, CartItem

        cart, _ = Cart.objects.get_or_create(session_key=self.session_key)
        product = Product.objects.create(name="Guard Kit", slug="guard-kit", price_cents=1000)
        CartItem.objects.create(cart=cart, product=product)
        return product

    def _make_prev_pending_with_succeeded_attempt(self):
        prev = Order.objects.create(
            subtotal_amount=1000,
            total_amount=1000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
            email="juan@example.com",
        )
        PaymentAttempt.objects.create(
            order=prev,
            amount=1000,
            paymongo_intent_id="pi_hidden_success",
            status=PaymentAttempt.Status.SUCCEEDED,
        )
        return prev

    def test_new_checkout_keeps_order_with_succeeded_attempt(self):
        self._seed_cart()
        prev = self._make_prev_pending_with_succeeded_attempt()

        resp = self.client.post(
            reverse("checkout:index"),
            {"email": "juan@example.com", "terms": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        prev.refresh_from_db()
        self.assertEqual(prev.status, Order.Status.PENDING_PAYMENT)

    def test_plain_stale_pending_still_cancelled(self):
        self._seed_cart()
        stale = Order.objects.create(
            subtotal_amount=1000,
            total_amount=1000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
            email="juan@example.com",
        )
        self.client.post(
            reverse("checkout:index"),
            {"email": "juan@example.com", "terms": "on"},
        )
        stale.refresh_from_db()
        self.assertEqual(stale.status, Order.Status.CANCELLED)
