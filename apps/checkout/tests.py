from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
        self.assertContains(resp, "Email &amp; Receipt Information")

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


