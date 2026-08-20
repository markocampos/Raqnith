from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cart.models import Cart
from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem

User = get_user_model()


class AppConfigSmokeTests(TestCase):
    def test_apps_are_installed(self):
        for label in ("accounts", "catalog", "cart", "orders", "payments"):
            with self.subTest(app=label):
                self.assertTrue(apps.is_installed(f"apps.{label}"))

    def test_custom_user_model(self):
        app_config = apps.get_app_config("accounts")
        self.assertEqual(app_config.get_model("User")._meta.label, "accounts.User")


class RegistrationTests(TestCase):
    def test_get_registration_page(self):
        resp = self.client.get(reverse("accounts:register"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create your account")

    def test_successful_registration(self):
        data = {
            "username": "juan_delacruz",
            "email": "juan@example.com",
            "first_name": "Juan",
            "last_name": "Dela Cruz",
            "password": "ComplexPassword123!",
            "password_confirm": "ComplexPassword123!",
            "agree_terms": "on",
        }
        resp = self.client.post(reverse("accounts:register"), data)
        self.assertRedirects(resp, reverse("accounts:profile"))

        user = User.objects.get(username="juan_delacruz")
        self.assertEqual(user.email, "juan@example.com")
        self.assertEqual(user.first_name, "Juan")
        self.assertTrue(user.check_password("ComplexPassword123!"))

    def test_registration_with_next_param(self):
        data = {
            "username": "maria_santos",
            "email": "maria@example.com",
            "first_name": "Maria",
            "last_name": "Santos",
            "password": "ComplexPassword123!",
            "password_confirm": "ComplexPassword123!",
            "agree_terms": "on",
        }
        resp = self.client.post(reverse("accounts:register") + "?next=/privacy/", data)
        self.assertRedirects(resp, "/privacy/")

    def test_duplicate_username_fails(self):
        User.objects.create_user(
            username="juan_delacruz",
            email="other@example.com",
            password="PassWord123!",
        )
        data = {
            "username": "juan_delacruz",
            "email": "juan@example.com",
            "password": "ComplexPassword123!",
            "password_confirm": "ComplexPassword123!",
        }
        resp = self.client.post(reverse("accounts:register"), data)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(
            resp, "A user with that username already exists", status_code=400
        )

    def test_duplicate_email_fails(self):
        User.objects.create_user(
            username="user1", email="juan@example.com", password="PassWord123!"
        )
        data = {
            "username": "user2",
            "email": "juan@example.com",
            "password": "ComplexPassword123!",
            "password_confirm": "ComplexPassword123!",
        }
        resp = self.client.post(reverse("accounts:register"), data)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(
            resp, "An account with this email address already exists", status_code=400
        )

    def test_password_mismatch_fails(self):
        data = {
            "username": "juan_delacruz",
            "email": "juan@example.com",
            "password": "ComplexPassword123!",
            "password_confirm": "DifferentPassword123!",
        }
        resp = self.client.post(reverse("accounts:register"), data)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Passwords do not match", status_code=400)


class LoginAndLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            first_name="Tester",
            password="SecurePassword123!",
        )

    def test_get_login_page(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sign in to Raqnith")

    def test_login_with_username(self):
        resp = self.client.post(reverse("accounts:login"), {
            "username_or_email": "testuser",
            "password": "SecurePassword123!",
        })
        self.assertRedirects(resp, reverse("accounts:profile"))

    def test_login_with_email(self):
        resp = self.client.post(reverse("accounts:login"), {
            "username_or_email": "testuser@example.com",
            "password": "SecurePassword123!",
        })
        self.assertRedirects(resp, reverse("accounts:profile"))

    def test_login_with_next_param(self):
        resp = self.client.post(reverse("accounts:login") + "?next=/privacy/", {
            "username_or_email": "testuser",
            "password": "SecurePassword123!",
        })
        self.assertRedirects(resp, "/privacy/")

    def test_login_invalid_password(self):
        resp = self.client.post(reverse("accounts:login"), {
            "username_or_email": "testuser",
            "password": "WrongPassword!",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Invalid username/email or password", status_code=400)

    def test_logout(self):
        self.client.login(username="testuser", password="SecurePassword123!")
        resp = self.client.get(reverse("accounts:logout"), follow=True)
        self.assertRedirects(resp, reverse("catalog:home"))
        self.assertContains(resp, "You&#x27;ve been safely signed out. See you next time!")


class CartMigrationOnAuthTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Pro Toolkit", slug="pro-toolkit", price_cents=5000
        )

    def test_cart_migrates_on_login(self):
        # 1. Anonymous user adds item to cart
        self.client.post(reverse("cart:add"), {"product": self.product.id})
        anon_cart = Cart.objects.get(session_key=self.client.session.session_key)
        self.assertEqual(anon_cart.items.count(), 1)

        # 2. User registers and logs in
        user = User.objects.create_user(
            username="shopper",
            email="shopper@example.com",
            password="SecurePassword123!",
        )
        self.client.post(reverse("accounts:login"), {
            "username_or_email": "shopper",
            "password": "SecurePassword123!",
        })

        # 3. User's cart now contains the item
        user_cart = Cart.objects.get(user=user)
        self.assertEqual(user_cart.items.count(), 1)
        self.assertEqual(user_cart.items.first().product, self.product)


class ProfileAndSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="juan",
            email="juan@example.com",
            first_name="Juan",
            last_name="Dela Cruz",
            password="SecurePassword123!",
        )
        self.product = Product.objects.create(
            name="Digital Book", slug="digital-book", price_cents=3000
        )
        self.order = Order.objects.create(
            user=self.user,
            subtotal_amount=3000,
            total_amount=3000,
            status=Order.Status.PAID,
            email="juan@example.com",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            unit_price_cents=3000,
        )

    def test_profile_requires_login(self):
        resp = self.client.get(reverse("accounts:profile"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_profile_view_and_order_history(self):
        self.client.login(username="juan", password="SecurePassword123!")
        resp = self.client.get(reverse("accounts:profile"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Juan")
        self.assertContains(resp, "juan@example.com")
        self.assertContains(resp, str(self.order.id)[:8])
        self.assertContains(resp, "Digital Book")

    def test_profile_update(self):
        self.client.login(username="juan", password="SecurePassword123!")
        resp = self.client.post(reverse("accounts:profile"), {
            "first_name": "Juanito",
            "last_name": "Santos",
            "email": "juanito@example.com",
        })
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Juanito")
        self.assertEqual(self.user.last_name, "Santos")
        self.assertEqual(self.user.email, "juanito@example.com")

    def test_settings_password_change(self):
        self.client.login(username="juan", password="SecurePassword123!")
        resp = self.client.post(reverse("accounts:settings"), {
            "action": "change_password",
            "current_password": "SecurePassword123!",
            "new_password": "NewUltraPassword456!",
            "confirm_password": "NewUltraPassword456!",
        })
        self.assertRedirects(resp, reverse("accounts:settings"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewUltraPassword456!"))

    def test_settings_wrong_current_password(self):
        self.client.login(username="juan", password="SecurePassword123!")
        resp = self.client.post(reverse("accounts:settings"), {
            "action": "change_password",
            "current_password": "WrongPassword!",
            "new_password": "NewUltraPassword456!",
            "confirm_password": "NewUltraPassword456!",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Incorrect current password", status_code=400)


class LegalPagesTests(TestCase):
    def test_privacy_policy_page(self):
        resp = self.client.get(reverse("privacy_policy"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Privacy Policy")
        self.assertContains(resp, "PayMongo")

    def test_terms_of_service_page(self):
        resp = self.client.get(reverse("terms_of_service"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Terms of Service")
