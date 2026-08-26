from django.conf import settings
from django.db import models

from apps.fields import HTTPSURLField


class SellerApplication(models.Model):
    """An application from a third-party creator who wants to sell on Raqnith.

    Applications are reviewed by the store team. Approved creators get their
    products curated and published by the store via admin, they never touch
    the storefront themselves.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    brand_name = models.CharField(
        max_length=150,
        help_text="Store or brand name the creator sells under.",
    )
    portfolio_url = HTTPSURLField(
        blank=True,
        help_text="Website, GitHub, Behance, or any work showcase.",
    )
    social_url = HTTPSURLField(
        blank=True,
        help_text="Instagram, TikTok, Facebook page, or similar.",
    )
    category = models.ForeignKey(
        "catalog.Category",
        related_name="seller_applications",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Category the applicant plans to sell in.",
    )
    message = models.TextField(
        help_text="What the creator wants to sell and why it fits Raqnith.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.brand_name} ({self.email})"
