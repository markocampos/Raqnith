import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product
from apps.orders.models import Order
from apps.payments.models import PaymentAttempt

User = get_user_model()


class CheckoutViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Widget", slug="co-widget", price_cents=100000
        )
        self.user = User.objects.create_user(
            username="marko", email="markocamposmail@gmail.com", password="password123"
        )

    def _cart(self, user=None):
        # Force session/cart creation via the cart view, then reuse that cart.
        self.client.get(reverse("cart:detail"))
        session_key = self.client.session.session_key
        if user:
            cart, _ = Cart.objects.get_or_create(user=user)
        else:
            cart, _ = Cart.objects.get_or_create(session_key=session_key)
        CartItem.objects.create(cart=cart, product=self.product)
        return cart

    def test_checkout_renders_summary_with_correct_totals(self):
        self._cart()
        resp = self.client.get(reverse("checkout:index"))
        self.assertEqual(resp.status_code, 200)
        # subtotal 100000 (₱1,000.00) + 12% tax (₱120.00) = ₱1,120.00
        self.assertContains(resp, "₱1,000.00")
        self.assertContains(resp, "₱1,120.00")
        self.assertContains(resp, 'data-total-cents="112000"')

    def test_unauthenticated_session_cart_flow(self):
        self._cart()
        resp = self.client.get(reverse("checkout:index"))
        self.assertEqual(resp.status_code, 200)
        # 100000 subtotal + 12% tax = 112000 (₱1,120.00)
        self.assertContains(resp, "₱1,120.00")
        self.assertContains(resp, "Your receipt and download link go here.")

    def test_empty_cart_redirects_to_cart(self):
        resp = self.client.get(reverse("checkout:index"))
        self.assertRedirects(resp, reverse("cart:detail"))

    def test_unauthenticated_checkout_post_creates_guest_order(self):
        self._cart()
        resp = self.client.post(
            reverse("checkout:index"),
            data={"email": "markocamposmail@gmail.com", "terms": "on"},
        )
        order = Order.objects.filter(email="markocamposmail@gmail.com").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertRedirects(resp, reverse("checkout:order", kwargs={"order_id": order.id}))

    def test_unauthenticated_checkout_json_returns_order_id(self):
        self._cart()
        resp = self.client.post(
            reverse("checkout:index"),
            data='{"contact": {"email": "markocamposmail@gmail.com"}, "terms": true}',
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("order_id", data)
        order = Order.objects.get(id=data["order_id"])
        self.assertEqual(order.email, "markocamposmail@gmail.com")
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

    def test_checkout_invalid_email_validation(self):
        self._cart()
        resp = self.client.post(
            reverse("checkout:index"),
            data={"email": "not-an-email", "terms": "on"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Please enter a valid email address.", status_code=400)

    def test_checkout_unchecked_terms_validation(self):
        self._cart()
        resp = self.client.post(
            reverse("checkout:index"),
            data={"email": "markocamposmail@gmail.com", "terms": "off"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "You must agree to the terms and conditions to proceed.", status_code=400)

    def test_authenticated_user_checkout_creates_order(self):
        self.client.force_login(self.user)
        self._cart(user=self.user)
        resp = self.client.post(
            reverse("checkout:index"),
            data={"email": "markocamposmail@gmail.com", "terms": "on"},
        )
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.email, "markocamposmail@gmail.com")
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertRedirects(resp, reverse("checkout:order", kwargs={"order_id": order.id}))

    def test_new_checkout_cancels_previous_pending_orders(self):
        self.client.force_login(self.user)
        # Create an existing pending order
        old_order = Order.objects.create(
            user=self.user,
            email="mark@example.com",
            subtotal_amount=5000,
            total_amount=5000,
            status=Order.Status.PENDING_PAYMENT,
        )
        old_attempt = PaymentAttempt.objects.create(
            order=old_order,
            amount=5000,
            status=PaymentAttempt.Status.AWAITING_ACTION,
        )

        self._cart(user=self.user)
        self.client.post(
            reverse("checkout:index"),
            data={"email": "mark@example.com", "terms": "on"},
        )

        old_order.refresh_from_db()
        old_attempt.refresh_from_db()
        self.assertEqual(old_order.status, Order.Status.CANCELLED)
        self.assertEqual(old_attempt.status, PaymentAttempt.Status.CANCELLED)

    def test_order_checkout_view_renders_payment_page(self):
        self._cart()
        order = Order.objects.create(
            session_key=self.client.session.session_key,
            email="buyer@example.com",
            subtotal_amount=100000,
            total_amount=112000,
            status=Order.Status.PENDING_PAYMENT,
        )
        PaymentAttempt.objects.create(
            order=order,
            amount=112000,
            currency="PHP",
            status=PaymentAttempt.Status.AWAITING_ACTION,
            qr_url="https://paymongo.test/qr.png",
        )
        resp = self.client.get(reverse("checkout:order", kwargs={"order_id": order.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "buyer@example.com")
        self.assertContains(resp, "Scan to Pay with QR Ph")
        self.assertContains(resp, "₱1,120.00")

    def test_order_checkout_view_renders_confirmed_if_already_paid(self):
        self._cart()
        order = Order.objects.create(
            session_key=self.client.session.session_key,
            email="buyer@example.com",
            subtotal_amount=100000,
            total_amount=112000,
            status=Order.Status.PAID,
        )
        resp = self.client.get(reverse("checkout:order", kwargs={"order_id": order.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Payment Confirmed")
        self.assertContains(resp, "buyer@example.com")

    def test_order_checkout_view_cross_device_access(self):
        # Even without matching session key, UUID access loads the payment page
        order = Order.objects.create(
            user=self.user,
            email="buyer@example.com",
            subtotal_amount=100000,
            total_amount=112000,
            status=Order.Status.PENDING_PAYMENT,
        )
        PaymentAttempt.objects.create(
            order=order,
            amount=112000,
            currency="PHP",
            status=PaymentAttempt.Status.AWAITING_ACTION,
            qr_url="https://paymongo.test/qr.png",
        )
        # Separate client without login/session
        other_client = self.client_class()
        resp = other_client.get(reverse("checkout:order", kwargs={"order_id": order.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "buyer@example.com")
        self.assertContains(resp, "Scan to Pay with QR Ph")

    def test_apply_coupon_success(self):
        from apps.coupons.models import Coupon
        Coupon.objects.create(code="SAVE20", discount_percent=20)
        self._cart()
        resp = self.client.post(reverse("checkout:apply_coupon"), data={"coupon_code": "SAVE20"})
        self.assertRedirects(resp, reverse("checkout:index"))
        self.assertEqual(self.client.session.get("checkout_coupon"), "SAVE20")

    def test_apply_coupon_invalid(self):
        self._cart()
        resp = self.client.post(reverse("checkout:apply_coupon"), data={"coupon_code": "INVALID99"})
        self.assertRedirects(resp, reverse("checkout:index"))
        self.assertIsNone(self.client.session.get("checkout_coupon"))

    def test_remove_coupon(self):
        self._cart()
        session = self.client.session
        session["checkout_coupon"] = "SAVE20"
        session.save()
        resp = self.client.post(reverse("checkout:remove_coupon"))
        self.assertRedirects(resp, reverse("checkout:index"))
        self.assertNotIn("checkout_coupon", self.client.session)

    def test_checkout_renders_with_coupon_discount(self):
        from apps.coupons.models import Coupon
        Coupon.objects.create(code="SAVE10", discount_percent=10)
        self._cart()
        session = self.client.session
        session["checkout_coupon"] = "SAVE10"
        session.save()
        resp = self.client.get(reverse("checkout:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SAVE10")
        self.assertContains(resp, "Discount")

    def test_json_order_create_applies_session_coupon_to_total(self):
        # The checkout page's JS posts to /orders/; the coupon applied in the
        # UI (stored in the session) must reach the order's final total.
        from apps.coupons.models import Coupon
        Coupon.objects.create(code="SAVE20", discount_percent=20)
        self._cart()  # ₱1,000.00 subtotal
        session = self.client.session
        session["checkout_coupon"] = "SAVE20"
        session.save()

        resp = self.client.post(
            reverse("orders:create"),
            data=json.dumps({"contact": {"email": "markocamposmail@gmail.com"}, "terms": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        order = Order.objects.get(id=resp.json()["order_id"])
        self.assertEqual(order.discount_amount, 20000)  # 20% of ₱1,000.00
        # (1000 - 200 discount pesos) + 12% tax = ₱896.00
        self.assertEqual(order.total_amount, 89600)

    def test_success_page_clears_session_coupon(self):
        from apps.coupons.models import Coupon
        Coupon.objects.create(code="SAVE10", discount_percent=10)
        self._cart()
        session = self.client.session
        session["checkout_coupon"] = "SAVE10"
        session.save()

        order = Order.objects.create(
            session_key=self.client.session.session_key,
            email="buyer@example.com",
            subtotal_amount=100000,
            total_amount=112000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        resp = self.client.get(reverse("orders:success", args=[order.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("checkout_coupon", self.client.session)




class FreeCheckoutFlowTests(TestCase):
    """Carts totaling < ₱1 settle as free orders: same email + terms
    confirmation, full fulfillment workflow, but no QR Ph / PayMongo step."""

    def setUp(self):
        self.free_product = Product.objects.create(
            name="Free Starter Kit", slug="free-starter-kit", price_cents=0
        )
        self.paid_product = Product.objects.create(
            name="Pro Kit", slug="pro-kit", price_cents=100000
        )

    def _add_to_cart(self, product):
        self.client.get(reverse("cart:detail"))
        session_key = self.client.session.session_key
        cart, _ = Cart.objects.get_or_create(session_key=session_key)
        CartItem.objects.create(cart=cart, product=product)
        return cart

    def _json_post(self, url):
        return self.client.post(
            url,
            data='{"contact": {"email": "juan@example.com"}, "terms": true}',
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_free_order_settles_immediately_and_redirects_to_success(self):
        from django.core import mail

        self._add_to_cart(self.free_product)
        resp = self._json_post(reverse("orders:create"))
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("redirect_url", data)

        order = Order.objects.get(id=data["order_id"])
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertIsNotNone(order.paid_at)
        self.assertEqual(order.total_amount, 0)
        # No payment attempt is ever created for free checkout.
        self.assertFalse(PaymentAttempt.objects.filter(order=order).exists())
        # Cart cleared after settlement.
        self.assertFalse(CartItem.objects.exists())
        # Success page renders the confirmed free order.
        page = self.client.get(data["redirect_url"])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Free — no payment needed")

    def test_free_checkout_page_shows_no_payment_needed_ui(self):
        self._add_to_cart(self.free_product)
        resp = self.client.get(reverse("checkout:index"))
        self.assertContains(resp, "Complete Order · Free")
        self.assertNotContains(resp, "Scan with any PH app")

    def test_mixed_cart_still_goes_through_payment_flow(self):
        self._add_to_cart(self.free_product)
        self._add_to_cart(self.paid_product)
        resp = self._json_post(reverse("orders:create"))
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertNotIn("redirect_url", data)
        order = Order.objects.get(id=data["order_id"])
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(order.total_amount, 112000)  # ₱1,000 + 12% VAT
