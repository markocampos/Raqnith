import re

from django import forms
from django.utils import timezone

from apps.seller.models import SellerApplication

DUPLICATE_WINDOW_DAYS = 14


class SellerApplicationForm(forms.ModelForm):
    """Public application form for third-party creators.

    Kept short and friendly, only what the review team needs to decide.
    Every field is cleaned defensively because applicants type quickly and
    browsers autocomplete aggressively.
    """

    class Meta:
        model = SellerApplication
        fields = [
            "full_name",
            "email",
            "brand_name",
            "portfolio_url",
            "social_url",
            "category",
            "message",
        ]
        widgets = {
            "full_name": forms.TextInput(
                attrs={"placeholder": "e.g. Juan Dela Cruz", "autofocus": "autofocus"}
            ),
            "email": forms.EmailInput(attrs={"placeholder": "you@email.com"}),
            "brand_name": forms.TextInput(attrs={"placeholder": "e.g. PixelForge Studio"}),
            "portfolio_url": forms.URLInput(attrs={"placeholder": "https://…"}),
            "social_url": forms.URLInput(attrs={"placeholder": "https://…"}),
            "message": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": (
                        "Tell us what you make, like templates, kits or e-books, "
                        "and why Virtus buyers will love it."
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].empty_label = "Not sure yet"
        self.fields["portfolio_url"].required = False
        self.fields["social_url"].required = False
        self.fields["category"].required = False
        self.fields["full_name"].min_length = 2
        self.fields["brand_name"].min_length = 2
        too_short = "This looks too short. Please double-check it."
        self.fields["full_name"].error_messages["min_length"] = too_short
        self.fields["brand_name"].error_messages["min_length"] = too_short

    def clean_full_name(self):
        name = self.cleaned_data.get("full_name", "").strip()
        # Names contain letters. Reject pure numbers/symbols/gibberish.
        if name and not re.search(r"[^\W\d_]", name, re.UNICODE):
            raise forms.ValidationError("Please enter your real name.")
        return re.sub(r"\s+", " ", name)

    def clean_brand_name(self):
        brand = self.cleaned_data.get("brand_name", "").strip()
        if brand and not re.search(r"[^\W\d_]", brand, re.UNICODE):
            raise forms.ValidationError("Please give your brand a readable name.")
        return re.sub(r"\s+", " ", brand)

    def clean_email(self):
        return self.cleaned_data.get("email", "").strip().lower()

    def clean_message(self):
        message = self.cleaned_data.get("message", "").strip()
        if message and len(message) < 20:
            raise forms.ValidationError(
                "Please tell us a bit more about your products (at least 20 characters)."
            )
        return re.sub(r"\n{3,}", "\n\n", message)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")

        # One open application per email. Friendly stop instead of silent dupes.
        if email and not self.errors:
            cutoff = timezone.now() - timezone.timedelta(days=DUPLICATE_WINDOW_DAYS)
            exists = SellerApplication.objects.filter(
                email__iexact=email,
                status=SellerApplication.Status.PENDING,
                created_at__gte=cutoff,
            ).exclude(pk=self.instance.pk)
            if exists.exists():
                self.add_error(
                    "email",
                    "We already have your application. Our team will email you soon.",
                )
        return cleaned
