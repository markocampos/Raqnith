"""Tests for post-launch delivery features:

* auto-issued license keys on settlement
* membership access windows (access_until) and expiry gating
* per-order daily download rate limiting via DownloadLog
* the downloadable PDF receipt
"""

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, ProductFile
from apps.orders.models import DownloadLog, LicenseKey, Order, OrderItem
from apps.orders.services.delivery import (
    can_access_file,
    downloads_remaining_today,
    downloads_today,
    order_access_token,
)
from apps.orders.services.license_keys import (
    generate_license_key,
    issue_license_keys,
)
from apps.orders.services.order_service import mark_order_paid


class FulfillmentTestBase(TestCase):
    def setUp(self):
        super().setUp()
        self.client.get(reverse("cart:detail"))
        self.session_key = self.client.session.session_key

    def make_order(self, status=Order.Status.PENDING_PAYMENT, **kwargs):
        kwargs.setdefault("email", "juan@example.com")
        kwargs.setdefault("session_key", self.session_key)
        return Order.objects.create(
            subtotal_amount=100000,
            total_amount=112000,
            status=status,
            paid_at=timezone.now() if status == Order.Status.PAID else None,
            **kwargs,
        )

    def add_item(self, order, product=None, **product_kwargs):
        product = product or Product.objects.create(
            name=product_kwargs.pop("name", "Kit"),
            slug=f"p-{Product.objects.count()}-{order.id.hex[:6]}",
            price_cents=100000,
            **product_kwargs,
        )
        return OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price_cents=100000,
        )

    def attach_file(self, item, name="asset.zip", kind=ProductFile.Kind.DOWNLOAD):
        return ProductFile.objects.create(
            product=item.product,
            name=name,
            kind=kind,
            file=SimpleUploadedFile(name, b"file-bytes")
            if kind == ProductFile.Kind.DOWNLOAD
            else None,
            external_url="https://portal.example.com/x" if kind == ProductFile.Kind.STREAM else "",
        )


class LicenseKeyTests(FulfillmentTestBase):
    def test_key_format_is_grouped_and_unambiguous(self):
        for _ in range(20):
            key = generate_license_key()
            groups = key.split("-")
            self.assertEqual(len(groups), 4)
            self.assertEqual(groups[0], "RAQ")
            for g in groups[1:]:
                self.assertEqual(len(g), 4)
                self.assertFalse(set(g) & set("ILOU01"))

    def test_settlement_issues_keys_only_for_flagged_products(self):
        order = self.make_order()
        software = self.add_item(order)
        software.product.requires_license_key = True
        software.product.save()
        plain = self.add_item(order)

        mark_order_paid(order)

        self.assertTrue(LicenseKey.objects.filter(order_item=software).exists())
        self.assertFalse(LicenseKey.objects.filter(order_item=plain).exists())

    def test_issue_is_idempotent(self):
        order = self.make_order(status=Order.Status.PAID)
        item = self.add_item(order)
        item.product.requires_license_key = True
        item.product.save()

        issue_license_keys(order)
        issue_license_keys(order)
        mark_order_paid(order)  # replays through settlement too

        self.assertEqual(LicenseKey.objects.filter(order_item=item).count(), 1)

    def test_keys_render_on_receipt_success_and_pdf(self):
        order = self.make_order()
        item = self.add_item(order, name="Dev Kit Pro")
        item.product.requires_license_key = True
        item.product.save()
        mark_order_paid(order)

        receipt = self.client.get(reverse("orders:receipt", args=[order.id]))
        self.assertContains(receipt, "Your License Keys")

        success = self.client.get(reverse("orders:success", args=[order.id]))
        self.assertContains(success, "RAQ-")

        pdf = self.client.get(reverse("orders:receipt_pdf", args=[order.id]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn(b"%PDF", b"".join(pdf.streaming_content))


class MembershipAccessTests(FulfillmentTestBase):
    def make_membership(self, duration_days=30):
        product = Product.objects.create(
            name="VIP Club",
            slug=f"vip-{Product.objects.count()}",
            price_cents=49900,
            product_type=Product.ProductType.MEMBERSHIP,
            membership_duration_days=duration_days,
        )
        return product

    def test_access_until_set_on_settlement(self):
        order = self.make_order()
        item = self.add_item(order, product=self.make_membership(30))
        before = timezone.now()

        mark_order_paid(order)
        item.refresh_from_db()

        expected_low = before + timedelta(days=30) - timedelta(seconds=5)
        self.assertIsNotNone(item.access_until)
        self.assertGreaterEqual(item.access_until, expected_low)
        self.assertTrue(item.has_active_access)

    def test_non_membership_items_have_no_window(self):
        order = self.make_order()
        item = self.add_item(order)
        mark_order_paid(order)
        item.refresh_from_db()
        self.assertIsNone(item.access_until)
        self.assertTrue(item.has_active_access)

    def test_expired_membership_blocks_download_with_notice(self):
        order = self.make_order(status=Order.Status.PAID)
        item = self.add_item(order, product=self.make_membership(30))
        file_obj = self.attach_file(item)
        # Simulate a purchase made 31 days ago.
        Order.objects.filter(pk=order.pk).update(paid_at=timezone.now() - timedelta(days=31))
        order.paid_at = timezone.now() - timedelta(days=31)
        item.access_until = order.paid_at + timedelta(days=30)
        item.save(update_fields=["access_until"])

        self.assertFalse(can_access_file(order, file_obj))

        resp = self.client.get(
            reverse("orders:download_file", args=[order.id, file_obj.id]), follow=True
        )
        self.assertRedirects(resp, reverse("orders:receipt", args=[order.id]))
        body = resp.content.decode()
        self.assertIn("ended", body)
        self.assertIn("Renew", body)

    def test_expired_membership_hidden_from_receipt_listing(self):
        order = self.make_order(status=Order.Status.PAID)
        expired_item = self.add_item(order, product=self.make_membership(30))
        active_item = self.add_item(order)
        self.attach_file(expired_item, name="vip-lounge.txt")
        self.attach_file(active_item, name="kit.zip")
        expired_item.access_until = timezone.now() - timedelta(days=1)
        expired_item.save(update_fields=["access_until"])

        resp = self.client.get(reverse("orders:receipt", args=[order.id]))
        content = resp.content.decode()
        self.assertNotIn("vip-lounge.txt", content)
        self.assertIn("kit.zip", content)
        self.assertIn("membership ended", content.lower())


@override_settings(MAX_DOWNLOADS_PER_DAY_PER_ORDER=3)
class DownloadRateLimitTests(FulfillmentTestBase):
    def setUp(self):
        super().setUp()
        self.order = self.make_order(status=Order.Status.PAID)
        self.item = self.add_item(self.order)
        self.file_a = self.attach_file(self.item, name="a.zip")
        self.url = lambda f: reverse("orders:download_file", args=[self.order.id, f.id])

    def _download(self, file_obj=None):
        return self.client.get(self.url(file_obj or self.file_a))

    def test_downloads_within_cap_are_served_and_logged(self):
        resp = self._download()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(DownloadLog.objects.filter(order=self.order).count(), 1)
        log = DownloadLog.objects.latest("created_at")
        self.assertEqual(log.file_id, self.file_a.id)

    def test_cap_blocks_with_friendly_redirect(self):
        for i in range(3):
            self.attach_file(self.item, name=f"f{i}.zip")

        files = [self.file_a] + list(
            ProductFile.objects.exclude(id=self.file_a.id).order_by("name")
        )
        for f in files[:3]:
            resp = self._download(f)
            self.assertEqual(resp.status_code, 200)

        blocked = self._download(files[0])
        self.assertRedirects(blocked, reverse("orders:receipt", args=[self.order.id]))
        follow = self.client.get(self.url(files[0]), follow=True)
        self.assertIn(b"download limit", follow.content)

        # Nothing further was logged after the cap hit.
        self.assertEqual(downloads_today(self.order), 3)
        self.assertEqual(downloads_remaining_today(self.order), 0)

    def test_zero_limit_disables_cap(self):
        with override_settings(MAX_DOWNLOADS_PER_DAY_PER_ORDER=0):
            self.assertIsNone(downloads_remaining_today(self.order))

    def test_stream_downloads_count_toward_cap(self):
        stream = self.attach_file(self.item, name="lesson.mp4", kind=ProductFile.Kind.STREAM)
        resp = self.client.get(self.url(stream))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(DownloadLog.objects.filter(order=self.order).count(), 1)


class ReceiptPdfViewTests(FulfillmentTestBase):
    def test_unpaid_redirects_to_status(self):
        order = self.make_order(status=Order.Status.PENDING_PAYMENT)
        resp = self.client.get(reverse("orders:receipt_pdf", args=[order.id]))
        self.assertRedirects(resp, reverse("orders:status", args=[order.id]))

    def test_foreign_order_404s(self):
        order = self.make_order(status=Order.Status.PAID, session_key="other-session")
        resp = self.client.get(reverse("orders:receipt_pdf", args=[order.id]))
        self.assertEqual(resp.status_code, 404)

    def _pdf_text(self, resp):
        """Decode reportlab's ASCII85+Flate streams into searchable text."""
        import re
        import zlib
        from base64 import a85decode

        raw = getattr(resp, "_joined_pdf", None)
        if raw is None:
            raw = b"".join(resp.streaming_content)
            resp._joined_pdf = raw
        text = b""
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.DOTALL):
            data = match.group(1).strip()
            try:
                if data.endswith(b"~>"):
                    data = a85decode(data, adobe=True)
                text += zlib.decompress(data)
            except Exception:
                text += match.group(1)
        return raw + text

    def test_pdf_contains_order_and_totals(self):
        order = self.make_order(discount_amount=5000)
        self.add_item(order, name="Starter Kit")
        mark_order_paid(order)

        resp = self.client.get(reverse("orders:receipt_pdf", args=[order.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        text = self._pdf_text(resp)
        self.assertIn(b"%PDF", text[:1024])
        self.assertIn(b"Starter Kit", text)
        self.assertIn(b"(Php 1,120.00)", text)

    def test_magic_link_device_can_fetch_pdf_after_adopting(self):
        other_client = self.client_class()

        order = self.make_order(session_key="original-device", status=Order.Status.PENDING_PAYMENT)
        self.add_item(order, name="Bundle")
        mark_order_paid(order)

        token = order_access_token(order)
        # Adopt via magic link first…
        landing = other_client.get(reverse("orders:access", args=[token]), follow=True)
        self.assertEqual(landing.status_code, 200)
        # …then the PDF works on this device too.
        pdf = other_client.get(reverse("orders:receipt_pdf", args=[order.id]))
        self.assertEqual(pdf.status_code, 200)
        self.assertIn(b"%PDF", b"".join(pdf.streaming_content))
