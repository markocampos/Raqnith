from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.coupons.models import Coupon


class CouponTests(TestCase):
    def test_defaults(self):
        coupon = Coupon.objects.create(code="SAVE10", discount_percent=10)
        self.assertTrue(coupon.active)
        self.assertFalse(coupon.is_expired)
        self.assertEqual(str(coupon), "SAVE10")

    def test_expired(self):
        coupon = Coupon.objects.create(
            code="OLD", discount_percent=10, expires_at=timezone.now() - timedelta(days=1)
        )
        self.assertTrue(coupon.is_expired)

    def test_future_not_expired(self):
        coupon = Coupon.objects.create(
            code="FUTURE", discount_percent=10, expires_at=timezone.now() + timedelta(days=1)
        )
        self.assertFalse(coupon.is_expired)

    def test_no_expiry_not_expired(self):
        coupon = Coupon.objects.create(code="EVER", discount_percent=10)
        self.assertFalse(coupon.is_expired)

    def test_code_unique(self):
        Coupon.objects.create(code="SAVE10", discount_percent=10)
        with self.assertRaises(IntegrityError):
            Coupon.objects.create(code="SAVE10", discount_percent=20)

    def test_discount_percent_upper_bound(self):
        coupon = Coupon(code="BAD", discount_percent=101)
        with self.assertRaises(ValidationError):
            coupon.full_clean()

    def test_discount_percent_lower_bound(self):
        coupon = Coupon(code="BAD2", discount_percent=-1)
        with self.assertRaises(ValidationError):
            coupon.full_clean()
