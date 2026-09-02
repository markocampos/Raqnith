import uuid

from django.db import models
from django.urls import reverse

from apps.fields import HTTPSURLField


class Category(models.Model):
    ICON_CHOICES = [
        ("zap", "⚡ Zap (Smoke / Test Products)"),
        ("panels-top-left", "📐 Layout (Templates / Themes)"),
        ("code-xml", "💻 Code (Dev Kits / APIs)"),
        ("terminal", "⌨️ Terminal (Software / Tools)"),
        ("book-open", "📚 Book (Guides / Docs)"),
        ("box", "📦 Box (Digital Assets & Bundles)"),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon = models.CharField(
        max_length=50,
        default="box",
        choices=ICON_CHOICES,
        help_text="Lucide icon for visual card banners.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    class ProductType(models.TextChoices):
        DIGITAL_DOWNLOAD = "digital_download", "Digital Download"
        COURSE = "course", "Course or Tutorial"
        EBOOK = "ebook", "E-book"
        MEMBERSHIP = "membership", "Membership"
        BUNDLE = "bundle", "Bundle"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(
        Category,
        related_name="products",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    product_type = models.CharField(
        max_length=30,
        choices=ProductType.choices,
        default=ProductType.DIGITAL_DOWNLOAD,
        help_text=(
            "What the buyer receives. Delivery is file/link based for all "
            "types: downloads for files, links for course portals, etc."
        ),
    )
    requires_license_key = models.BooleanField(
        default=False,
        help_text=(
            "Auto-generate a unique license/access code per order item on "
            "payment (recommended for software, kits, and API products)."
        ),
    )
    membership_duration_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Memberships only: days of access from payment. Leave empty for "
            "lifetime access. Buyer files/links lock automatically at expiry."
        ),
    )
    description = models.TextField(
        blank=True,
        default="Instant digital license with automated receipt confirmation and download access.",
        help_text="Customizable product description shown on cards and product detail page.",
    )
    price_cents = models.PositiveBigIntegerField()
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.slug])

    @property
    def primary_image(self):
        return self.images.first()


class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="product_gallery/")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.product.name} Image"


def product_file_upload_path(instance, filename):
    """Store deliverables under a per-product private media folder."""
    return f"products/{instance.product_id}/{filename}"


class ProductFile(models.Model):
    """A downloadable or linked deliverable attached to a product.

    ``file`` serves binary assets (zip, pdf, epub…). They are never exposed
    through /media/ URLs — the orders app streams them through a
    permission-checked view after payment.

    ``external_url`` serves hosted content (course portal, streaming page,
    Notion workspace…). Buyers are redirected there after an access check.
    """

    class Kind(models.TextChoices):
        DOWNLOAD = "download", "Download"
        STREAM = "stream", "Stream / External Link"

    # UUID pk keeps buyer download URLs unguessable and non-enumerable.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product,
        related_name="files",
        on_delete=models.CASCADE,
    )
    name = models.CharField(
        max_length=200,
        help_text="Buyer-facing label, e.g. 'Starter Kit (ZIP)'",
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.DOWNLOAD,
    )
    file = models.FileField(
        upload_to=product_file_upload_path,
        blank=True,
        help_text="Upload the deliverable. Required when kind is Download.",
    )
    external_url = HTTPSURLField(
        blank=True,
        help_text="Destination link for Stream items (course portal, video page…).",
    )
    file_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="Bytes; auto-filled on upload.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return f"{self.product.name} — {self.name}"

    def save(self, *args, **kwargs):
        if self.file and hasattr(self.file, "size"):
            try:
                self.file_size = self.file.size
            except (OSError, ValueError):
                pass
        super().save(*args, **kwargs)
