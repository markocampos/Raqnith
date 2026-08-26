import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product
from apps.coupons.models import Coupon
from apps.orders.exceptions import OrderBuildError
from apps.orders.models import Order, OrderItem
from apps.orders.selectors import get_order_for_checkout
from apps.orders.services.order_service import (
    build_order_from_cart,
    mark_order_paid,
    unique_products,
)
from apps.orders.validators import (
    validate_coupon,
    validate_currency,
    validate_minimum_transaction,
    validate_product,
    validate_shipping_option,
)
from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import PaymentService
from apps.payments.tests.helpers import intent_payload, make_mock_client


class OrderModelTests(TestCase):
    def test_default_status_is_draft(self):
        order = Order.objects.create(subtotal_amount=1000, total_amount=1000)
        self.assertEqual(order.status, Order.Status.DRAFT)
        self.assertFalse(order.is_paid)

    def test_status_choices(self):
        expected = {
            Order.Status.DRAFT,
            Order.Status.PENDING_PAYMENT,
            Order.Status.PAID,
            Order.Status.CANCELLED,
            Order.Status.PAYMENT_FAILED,
            Order.Status.FULFILLED,
        }
        self.assertEqual(set(Order.Status), expected)

    def test_default_currency_and_discount(self):
        order = Order.objects.create(subtotal_amount=2000, total_amount=2000)
        self.assertEqual(order.currency, "PHP")
        self.assertEqual(order.discount_amount, 0)
        self.assertIsNone(order.paid_at)

    def test_money_field_rejects_float(self):
        with self.assertRaises(ValueError):
            Order.objects.create(subtotal_amount=19.99, total_amount=19.99)

    def test_money_field_rejects_negative_on_validation(self):
        order = Order(total_amount=-100, subtotal_amount=-100)
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_money_field_rejects_negative_on_save(self):
        with self.assertRaises(IntegrityError):
            Order.objects.create(subtotal_amount=-100, total_amount=-100)


class OrderItemTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Widget", slug="widget", price_cents=2500)

    def test_product_delete_is_protected_by_order_item(self):
        order = Order.objects.create(subtotal_amount=2500, total_amount=2500)
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price_cents=self.product.price_cents,
        )
        with self.assertRaises(ProtectedError):
            self.product.delete()

    def test_order_product_unique_together(self):
        order = Order.objects.create(subtotal_amount=2500, total_amount=2500)
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price_cents=self.product.price_cents,
        )
        with self.assertRaises(IntegrityError):
            OrderItem.objects.create(
                order=order,
                product=self.product,
                product_name=self.product.name,
                unit_price_cents=self.product.price_cents,
            )

    def test_line_total_cents(self):
        order = Order.objects.create(subtotal_amount=5000, total_amount=5000)
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price_cents=self.product.price_cents,
        )
        self.assertEqual(item.line_total_cents, 2500)


class OrderTransitionTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(subtotal_amount=1000, total_amount=1000)

    def test_draft_to_pending_payment(self):
        self.order.transition_to(Order.Status.PENDING_PAYMENT)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)

    def test_invalid_transition_rejected(self):
        with self.assertRaises(ValueError):
            self.order.transition_to(Order.Status.PAID)

    def test_paid_sets_paid_at(self):
        self.order.transition_to(Order.Status.PENDING_PAYMENT)
        self.order.transition_to(Order.Status.PAID)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)

    def test_payment_failed_can_retry(self):
        self.order.transition_to(Order.Status.PENDING_PAYMENT)
        self.order.transition_to(Order.Status.PAYMENT_FAILED)
        self.order.transition_to(Order.Status.PENDING_PAYMENT)
        self.order.transition_to(Order.Status.PAID)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)


class ValidatorTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Widget", slug="widget", price_cents=1000)

    def test_validate_product_available(self):
        self.assertEqual(validate_product(self.product), self.product)

    def test_validate_product_unavailable(self):
        self.product.is_available = False
        self.product.save()
        with self.assertRaises(ValidationError):
            validate_product(self.product)

    def test_validate_coupon_none(self):
        with self.assertRaises(ValidationError):
            validate_coupon(None)

    def test_validate_coupon_inactive(self):
        coupon = Coupon.objects.create(code="OFF", discount_percent=10, active=False)
        with self.assertRaises(ValidationError):
            validate_coupon(coupon)

    def test_validate_coupon_expired(self):
        coupon = Coupon.objects.create(
            code="OLD", discount_percent=10, expires_at=timezone.now() - timedelta(days=1)
        )
        with self.assertRaises(ValidationError):
            validate_coupon(coupon)

    def test_validate_coupon_valid(self):
        coupon = Coupon.objects.create(code="SAVE10", discount_percent=10)
        self.assertEqual(validate_coupon(coupon), coupon)

    def test_validate_shipping_option(self):
        self.assertEqual(validate_shipping_option("standard"), "standard")
        with self.assertRaises(ValidationError):
            validate_shipping_option("bogus")

    def test_validate_currency(self):
        self.assertEqual(validate_currency("PHP"), "PHP")
        with self.assertRaises(ValidationError):
            validate_currency("USD")

    def test_validate_minimum_transaction(self):
        self.assertEqual(validate_minimum_transaction(100), 100)
        # Sub-peso totals are accepted: checkout settles them as free orders.
        self.assertEqual(validate_minimum_transaction(99), 99)
        self.assertEqual(validate_minimum_transaction(0), 0)
        with self.assertRaises(ValidationError):
            validate_minimum_transaction(-1)


class OrderServiceTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Widget", slug="widget", price_cents=1000
        )
        self.cart = Cart.objects.create(session_key="cart-session-1")
        CartItem.objects.create(cart=self.cart, product=self.product)

    def _build(self, **kwargs):
        defaults = {"cart": self.cart, "shipping_method": "standard"}
        defaults.update(kwargs)
        return build_order_from_cart(**defaults)

    def test_basic_totals_with_tax(self):
        order = self._build()
        self.assertEqual(order.subtotal_amount, 1000)
        self.assertEqual(order.discount_amount, 0)
        self.assertEqual(order.total_amount, 1120)  # 1000 + 12% tax
        self.assertEqual(order.currency, "PHP")
        self.assertEqual(order.status, Order.Status.DRAFT)

        item = order.items.get()
        self.assertEqual(item.product_name, "Widget")
        self.assertEqual(item.unit_price_cents, 1000)

    def test_shipping_and_tax_addition(self):
        order = self._build(shipping_method="express")
        # 1000 subtotal + 15000 shipping = 16000 taxable; 12% tax = 1920
        self.assertEqual(order.total_amount, 17920)

    def test_discount_applied_and_rounded(self):
        Coupon.objects.create(code="SAVE10", discount_percent=10)
        order = self._build(coupon_code="SAVE10")
        self.assertEqual(order.discount_amount, 100)
        # 1000 - 100 = 900 taxable; 12% tax = 108
        self.assertEqual(order.total_amount, 1008)

    def test_price_sourced_from_database(self):
        # A browser only supplies the product; the price must come from
        # the DB even if the product price changed after the cart was built.
        self.product.price_cents = 1500
        self.product.save()
        order = self._build()
        self.assertEqual(order.subtotal_amount, 1500)
        self.assertEqual(order.items.get().unit_price_cents, 1500)

    def test_invalid_coupon_creates_no_order(self):
        before = Order.objects.count()
        with self.assertRaises(OrderBuildError) as cm:
            self._build(coupon_code="NOPE")
        self.assertIn("coupon", cm.exception.errors)
        self.assertEqual(Order.objects.count(), before)

    def test_expired_coupon_rejected(self):
        Coupon.objects.create(
            code="OLD", discount_percent=10, expires_at=timezone.now() - timedelta(days=1)
        )
        with self.assertRaises(OrderBuildError) as cm:
            self._build(coupon_code="OLD")
        self.assertIn("coupon", cm.exception.errors)

    def test_inactive_coupon_rejected(self):
        Coupon.objects.create(code="OFF", discount_percent=10, active=False)
        with self.assertRaises(OrderBuildError) as cm:
            self._build(coupon_code="OFF")
        self.assertIn("coupon", cm.exception.errors)

    def test_empty_cart_rejected(self):
        cart = Cart.objects.create(session_key="cart-empty")
        with self.assertRaises(OrderBuildError) as cm:
            build_order_from_cart(cart, shipping_method="standard")
        self.assertIn("cart", cm.exception.errors)

    def test_invalid_shipping_rejected(self):
        with self.assertRaises(OrderBuildError) as cm:
            self._build(shipping_method="teleport")
        self.assertIn("shipping_method", cm.exception.errors)

    def test_sub_peso_cart_builds_as_free_order(self):
        product = Product.objects.create(name="Cheap", slug="cheap", price_cents=50)
        cart = Cart.objects.create(session_key="cart-cheap")
        CartItem.objects.create(cart=cart, product=product)
        order = build_order_from_cart(cart, shipping_method="standard")
        # Sub-peso totals no longer fail the minimum check: checkout settles
        # them as free orders (total < ₱1 → settle_free_order).
        self.assertLess(order.total_amount, 100)

    def test_unique_products_dedupes(self):
        other = Product.objects.create(name="Gadget", slug="gadget", price_cents=2000)
        items = [
            SimpleNamespace(product=self.product),
            SimpleNamespace(product=self.product),
            SimpleNamespace(product=other),
        ]
        self.assertEqual(unique_products(items), [self.product, other])

    def test_build_sets_user_owner(self):
        user = get_user_model().objects.create_user(username="owner", email="o@x.com")
        order = self._build(user_or_session=user)
        self.assertEqual(order.user, user)
        self.assertIsNone(order.session_key)

    def test_build_sets_session_owner(self):
        order = self._build(user_or_session="sess-xyz")
        self.assertEqual(order.session_key, "sess-xyz")
        self.assertIsNone(order.user)

    def test_build_derives_owner_from_cart(self):
        order = self._build()
        self.assertEqual(order.session_key, "cart-session-1")


class OrderSelectorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", email="o@x.com")
        self.other = get_user_model().objects.create_user(username="other", email="x@o.com")
        self.order = Order.objects.create(
            subtotal_amount=1000, total_amount=1000, user=self.user
        )

    def test_returns_order_for_owner(self):
        self.assertEqual(get_order_for_checkout(self.order.id, self.user), self.order)

    def test_rejects_other_user(self):
        with self.assertRaises(Order.DoesNotExist):
            get_order_for_checkout(self.order.id, self.other)

    def test_rejects_wrong_session(self):
        with self.assertRaises(Order.DoesNotExist):
            get_order_for_checkout(self.order.id, "other-session")

    def test_rejects_missing_user_or_session(self):
        with self.assertRaises(Order.DoesNotExist):
            get_order_for_checkout(self.order.id, None)

    def test_session_owned_order(self):
        order = Order.objects.create(
            subtotal_amount=1000, total_amount=1000, session_key="sess-1"
        )
        self.assertEqual(get_order_for_checkout(order.id, "sess-1"), order)

    def test_nonexistent_order(self):
        with self.assertRaises(Order.DoesNotExist):
            get_order_for_checkout(uuid.uuid4(), self.user)


class MarkOrderPaidCartTests(TestCase):
    """Paying an order removes exactly the purchased products from the
    buyer's cart; unrelated items and other buyers' carts stay untouched."""

    def setUp(self):
        self.purchased = Product.objects.create(
            name="Widget", slug="widget", price_cents=1000
        )
        self.extra = Product.objects.create(
            name="Gadget", slug="gadget", price_cents=2000
        )

    def _pending_session_order(self, session_key, cart):
        CartItem.objects.get_or_create(cart=cart, product=self.purchased)
        order = build_order_from_cart(
            cart, shipping_method="standard", user_or_session=session_key
        )
        order.transition_to(Order.Status.PENDING_PAYMENT)
        return order

    def test_paid_guest_order_clears_purchased_items_only(self):
        cart = Cart.objects.create(session_key="sess-1")
        order = self._pending_session_order("sess-1", cart)
        # Item the buyer added while payment was pending must survive.
        CartItem.objects.create(cart=cart, product=self.extra)

        mark_order_paid(order)

        self.assertEqual(order.status, Order.Status.PAID)
        remaining = list(cart.items.values_list("product__slug", flat=True))
        self.assertEqual(remaining, ["gadget"])

    def test_mark_order_paid_is_idempotent(self):
        cart = Cart.objects.create(session_key="sess-1")
        order = self._pending_session_order("sess-1", cart)

        mark_order_paid(order)
        mark_order_paid(order)  # replay / double-settle must not raise

        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(cart.items.count(), 0)

    def test_paid_user_order_clears_user_cart(self):
        user = get_user_model().objects.create_user(
            username="owner", email="owner@example.com", password="password123"
        )
        cart = Cart.objects.create(user=user)
        CartItem.objects.get_or_create(cart=cart, product=self.purchased)
        order = build_order_from_cart(
            cart, shipping_method="standard", user_or_session=user
        )
        order.transition_to(Order.Status.PENDING_PAYMENT)
        self.assertEqual(cart.items.count(), 1)

        mark_order_paid(order)
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 0)

    def test_other_sessions_cart_untouched(self):
        cart_a = Cart.objects.create(session_key="sess-a")
        cart_b = Cart.objects.create(session_key="sess-b")
        CartItem.objects.create(cart=cart_b, product=self.purchased)
        order = self._pending_session_order("sess-a", cart_a)

        mark_order_paid(order)

        self.assertEqual(cart_a.items.count(), 0)
        self.assertEqual(cart_b.items.count(), 1)


class CreateOrderViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Widget", slug="co-widget", price_cents=100000
        )
        self.user = get_user_model().objects.create_user(
            username="marko", email="marko@example.com", password="password123"
        )

    def _cart(self, user=None):
        self.client.get(reverse("cart:detail"))
        session_key = self.client.session.session_key
        if user:
            cart, _ = Cart.objects.get_or_create(user=user)
        else:
            cart, _ = Cart.objects.get_or_create(session_key=session_key)
        CartItem.objects.create(cart=cart, product=self.product)
        return cart

    def test_create_order_unauthenticated_creates_guest_order(self):
        self._cart()
        resp = self.client.post(
            reverse("orders:create"),
            data=json.dumps({"contact": {"email": "marko@example.com"}, "terms": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("order_id", data)
        order = Order.objects.get(id=data["order_id"])
        self.assertEqual(order.email, "marko@example.com")
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(self.client.session["checkout_contact"]["email"], "marko@example.com")

    def test_create_order_authenticated_builds_from_cart_and_marks_pending(self):
        self.client.force_login(self.user)
        self._cart(user=self.user)
        resp = self.client.post(
            reverse("orders:create"),
            data=json.dumps({"contact": {"email": "marko@example.com"}, "terms": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

        order = Order.objects.get(user=self.user)
        self.assertEqual(resp.json()["order_id"], str(order.id))
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        # ₱1,000.00 subtotal + 12% tax = ₱1,120.00
        self.assertEqual(order.total_amount, 112000)
        self.assertEqual(order.user, self.user)

    def test_empty_cart_authenticated_returns_400_and_creates_no_order(self):
        self.client.force_login(self.user)
        self.client.get(reverse("cart:detail"))
        resp = self.client.post(
            reverse("orders:create"), data="{}", content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_create_order_invalid_email_validation(self):
        self.client.force_login(self.user)
        self._cart(user=self.user)
        resp = self.client.post(
            reverse("orders:create"),
            data=json.dumps({"contact": {"email": "invalid-email"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "validation_error")


class SuccessViewTests(TestCase):
    def setUp(self):
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            session_key=self.session_key,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
            email="juan@example.com",
        )
        PaymentAttempt.objects.create(
            order=self.order,
            amount=112000,
            status=PaymentAttempt.Status.SUCCEEDED,
            payment_method="qrph",
        )

    def test_success_renders_for_paid_owner(self):
        resp = self.client.get(reverse("orders:success", args=[self.order.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Payment confirmed")
        self.assertContains(resp, "qrph")
        self.assertContains(resp, "juan@example.com")

    def test_success_redirects_unpaid_to_status(self):
        unpaid = Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
        )
        resp = self.client.get(reverse("orders:success", args=[unpaid.id]))
        self.assertRedirects(resp, reverse("orders:status", args=[unpaid.id]))

    def test_receipt_renders_for_paid_owner(self):
        resp = self.client.get(reverse("orders:receipt", args=[self.order.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Order receipt")
        self.assertContains(resp, "qrph")

    def test_receipt_redirects_unpaid(self):
        unpaid = Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
        )
        resp = self.client.get(reverse("orders:receipt", args=[unpaid.id]))
        self.assertRedirects(resp, reverse("orders:status", args=[unpaid.id]))

    def test_other_session_returns_404(self):
        other = Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            session_key="someone-else",
            status=Order.Status.PAID,
        )
        resp = self.client.get(reverse("orders:success", args=[other.id]))
        self.assertEqual(resp.status_code, 404)


class AdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.client.force_login(self.admin)

    def test_order_admin_renders_paid_failed_pending(self):
        for status in (
            Order.Status.PAID,
            Order.Status.PAYMENT_FAILED,
            Order.Status.PENDING_PAYMENT,
        ):
            order = Order.objects.create(
                subtotal_amount=1000,
                total_amount=1120,
                status=status,
                email="buyer@example.com",
            )
            PaymentAttempt.objects.create(
                order=order,
                amount=1120,
                status=PaymentAttempt.Status.SUCCEEDED,
                payment_method="visa •••• 4242",
            )
        resp = self.client.get(reverse("admin:orders_order_changelist"))
        self.assertEqual(resp.status_code, 200)

    def test_payment_admin_renders(self):
        order = Order.objects.create(subtotal_amount=1000, total_amount=1000)
        PaymentAttempt.objects.create(order=order, amount=1000)
        resp = self.client.get(reverse("admin:payments_paymentattempt_changelist"))
        self.assertEqual(resp.status_code, 200)


class OrderStatusViewTests(TestCase):
    def setUp(self):
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key
        self.order = Order.objects.create(
            subtotal_amount=10000,
            total_amount=10000,
            session_key=self.session_key,
            status=Order.Status.PENDING_PAYMENT,
        )

    def _mock_service(self, status):
        def handler(request):
            return httpx.Response(200, json=intent_payload(status=status))
        return PaymentService(client=make_mock_client(handler))

    def test_processing_attempt_reconciles_to_succeeded(self):
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.PROCESSING,
        )
        with patch(
            "apps.orders.views.PaymentService",
            return_value=self._mock_service("succeeded"),
        ):
            resp = self.client.get(reverse("orders:status", args=[self.order.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Payment confirmed")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    def test_timeout_attempt_reconciles_to_succeeded(self):
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.AWAITING_METHOD,
            failure_message="still checking",
        )
        with patch(
            "apps.orders.views.PaymentService",
            return_value=self._mock_service("succeeded"),
        ):
            resp = self.client.get(reverse("orders:status", args=[self.order.id]))

        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    def test_failed_attempt_renders_retry(self):
        PaymentAttempt.objects.create(
            order=self.order,
            amount=10000,
            paymongo_intent_id="pi_test_1",
            status=PaymentAttempt.Status.FAILED,
        )
        resp = self.client.get(reverse("orders:status", args=[self.order.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Payment wasn't completed")
        self.assertContains(resp, "Try again")

    def test_other_session_returns_404(self):
        other = Order.objects.create(
            subtotal_amount=10000, total_amount=10000, session_key="someone-else"
        )
        resp = self.client.get(reverse("orders:status", args=[other.id]))
        self.assertEqual(resp.status_code, 404)


class OrderExpirationTests(TestCase):
    def test_order_is_expired_after_60_minutes(self):
        order = Order.objects.create(
            subtotal_amount=5000,
            total_amount=5000,
            status=Order.Status.PENDING_PAYMENT,
        )
        self.assertFalse(order.is_expired)

        # Fast-forward 65 minutes
        order.created_at = timezone.now() - timezone.timedelta(minutes=65)
        order.save(update_fields=["created_at"])

        self.assertTrue(order.is_expired)
        expired = order.expire_if_overdue()
        self.assertTrue(expired)
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_paid_order_never_expires(self):
        order = Order.objects.create(
            subtotal_amount=5000,
            total_amount=5000,
            status=Order.Status.PAID,
        )
        order.created_at = timezone.now() - timezone.timedelta(days=2)
        order.save(update_fields=["created_at"])
        self.assertFalse(order.is_expired)
        self.assertFalse(order.expire_if_overdue())
        self.assertEqual(order.status, Order.Status.PAID)

    def test_purge_unpaid_overdue_deletes_orders_after_30_days(self):
        # 1. Unpaid order created 31 days ago -> should be purged
        stale_order = Order.objects.create(
            subtotal_amount=5000,
            total_amount=5000,
            status=Order.Status.CANCELLED,
        )
        Order.objects.filter(pk=stale_order.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=31)
        )
        PaymentAttempt.objects.create(
            order=stale_order,
            amount=5000,
            status=PaymentAttempt.Status.CANCELLED,
        )

        # 2. Paid order created 31 days ago -> must NEVER be purged
        paid_order = Order.objects.create(
            subtotal_amount=5000,
            total_amount=5000,
            status=Order.Status.PAID,
            paid_at=timezone.now() - timezone.timedelta(days=31),
        )
        Order.objects.filter(pk=paid_order.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=31)
        )

        # 3. Recent unpaid order created 5 days ago -> should NOT be purged
        recent_order = Order.objects.create(
            subtotal_amount=5000,
            total_amount=5000,
            status=Order.Status.PENDING_PAYMENT,
        )

        purged_count = Order.purge_unpaid_overdue()
        self.assertEqual(purged_count, 1)
        self.assertFalse(Order.objects.filter(pk=stale_order.pk).exists())
        self.assertTrue(Order.objects.filter(pk=paid_order.pk).exists())
        self.assertTrue(Order.objects.filter(pk=recent_order.pk).exists())
