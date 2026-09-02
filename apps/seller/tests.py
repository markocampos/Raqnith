from django.test import TestCase
from django.urls import reverse

from apps.seller.forms import SellerApplicationForm
from apps.seller.models import SellerApplication


def valid_payload(**overrides):
    data = {
        "full_name": "Juan Dela Cruz",
        "email": "juan@pixelforge.dev",
        "brand_name": "PixelForge Studio",
        "portfolio_url": "https://pixelforge.dev",
        "social_url": "",
        "category": "",
        "message": "We make premium Notion templates for freelancers.",
    }
    data.update(overrides)
    return data


class SellerApplicationFormTests(TestCase):
    def test_valid_application_saves_as_pending(self):
        form = SellerApplicationForm(data=valid_payload())
        self.assertTrue(form.is_valid(), form.errors)
        application = form.save()
        self.assertEqual(application.status, SellerApplication.Status.PENDING)

    def test_optional_fields_can_be_blank(self):
        payload = valid_payload(portfolio_url="", social_url="", category="")
        form = SellerApplicationForm(data=payload)
        self.assertTrue(form.is_valid(), form.errors)

    def test_message_is_required(self):
        form = SellerApplicationForm(data=valid_payload(message=""))
        self.assertFalse(form.is_valid())
        self.assertIn("message", form.errors)

    def test_message_needs_some_detail(self):
        form = SellerApplicationForm(data=valid_payload(message="templates"))
        self.assertFalse(form.is_valid())
        self.assertIn("message", form.errors)

    def test_name_must_contain_letters(self):
        form = SellerApplicationForm(data=valid_payload(full_name="123456"))
        self.assertFalse(form.is_valid())
        self.assertIn("full_name", form.errors)

    def test_brand_name_must_contain_letters(self):
        form = SellerApplicationForm(data=valid_payload(brand_name="--==--"))
        self.assertFalse(form.is_valid())
        self.assertIn("brand_name", form.errors)

    def test_whitespace_is_tidyied_and_email_lowercased(self):
        form = SellerApplicationForm(
            data=valid_payload(
                full_name="   Juan    Dela   Cruz  ",
                email="JUAN@PixelForge.DEV",
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["full_name"], "Juan Dela Cruz")
        self.assertEqual(form.cleaned_data["email"], "juan@pixelforge.dev")

    def test_duplicate_pending_application_is_blocked(self):
        SellerApplication.objects.create(
            full_name="Juan Dela Cruz",
            email="juan@pixelforge.dev",
            brand_name="PixelForge Studio",
            message="We make premium Notion templates for freelancers.",
        )
        form = SellerApplicationForm(data=valid_payload(brand_name="Second Try"))
        self.assertFalse(form.is_valid())
        self.assertIn("already have your application", form.errors["email"][0])
        self.assertEqual(SellerApplication.objects.count(), 1)

    def test_duplicate_check_ignores_old_or_closed_applications(self):
        existing = SellerApplication.objects.create(
            **{
                "full_name": "Juan Dela Cruz",
                "email": "juan@pixelforge.dev",
                "brand_name": "PixelForge Studio",
                "message": "We make premium Notion templates for freelancers.",
                "status": SellerApplication.Status.APPROVED,
            }
        )
        form = SellerApplicationForm(data=valid_payload())
        self.assertTrue(form.is_valid(), form.errors)
        existing.delete()


class SellerApplyViewTests(TestCase):
    def setUp(self):
        self.url = reverse("seller:apply")

    def test_page_loads_for_guests(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sell on Virtus")
        self.assertContains(response, "Submit Application")

    def test_form_is_phased(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-panel="1"')
        self.assertContains(response, 'data-panel="2"')
        self.assertContains(response, 'data-panel="3"')
        self.assertContains(response, "apply-progress-bar")
        self.assertNotContains(response, "\u2014")  # no em dashes in buyer copy

    def test_form_autosaves_draft_across_refresh(self):
        response = self.client.get(self.url)
        self.assertContains(response, "virtus_seller_apply_draft")
        self.assertContains(response, "restoreDraft")

    def test_footer_links_to_apply_page(self):
        response = self.client.get(reverse("catalog:home"))
        self.assertContains(response, self.url)
        self.assertNotContains(response, ">Sign Out</a>")

    def test_successful_submission_redirects_and_saves(self):
        response = self.client.post(self.url, valid_payload())
        self.assertEqual(SellerApplication.objects.count(), 1)
        self.assertRedirects(response, f"{self.url}?sent=1")

        follow_up = self.client.get(f"{self.url}?sent=1")
        self.assertContains(follow_up, "Application received!")
        self.assertNotContains(follow_up, "<form")

    def test_invalid_submission_rerenders_with_errors(self):
        response = self.client.post(self.url, valid_payload(email="not-an-email"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SellerApplication.objects.count(), 0)
        self.assertContains(response, "Submit Application", status_code=400)

    def test_honeypot_fakes_success_without_saving(self):
        response = self.client.post(self.url, valid_payload(website="http://spam.example"))
        self.assertRedirects(response, f"{self.url}?sent=1")
        self.assertEqual(SellerApplication.objects.count(), 0)
