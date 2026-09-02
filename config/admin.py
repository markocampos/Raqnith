"""Custom admin site for Virtus with a store-overview dashboard.

The admin index is not just a model list: it surfaces the numbers staff
check every morning (revenue, orders awaiting payment, webhook health,
seller applications, refund requests) plus latest activity, so the marketplace
can be operated smoothly without touching the ORM.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.coupons.models import Coupon
from apps.orders.models import DownloadLog, Order
from apps.payments.models import PaymentAttempt, Refund, WebhookEvent
from apps.seller.models import SellerApplication

User = get_user_model()


def pesos(cents):
    """Format integer centavos as a peso string: 249900 -> ₱2,499.00."""
    return f"\u20b1{(cents or 0) / 100:,.2f}"


class VirtusAdminSite(admin.AdminSite):
    site_header = "Virtus Store Console"
    site_title = "Virtus Admin"
    index_title = "Marketplace Overview"

    def index(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "dashboard": self._dashboard()}
        return super().index(request, extra_context)

    @staticmethod
    def _dashboard():
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_ago = now - timedelta(hours=24)
        month_ago = now - timedelta(days=30)

        paid_statuses = [Order.Status.PAID, Order.Status.FULFILLED]
        order_stats = Order.objects.aggregate(
            revenue_today=Sum("total_amount", filter=Q(paid_at__gte=today_start)),
            revenue_30d=Sum(
                "total_amount",
                filter=Q(paid_at__gte=month_ago, status__in=paid_statuses),
            ),
            revenue_all_time=Sum("total_amount", filter=Q(status__in=paid_statuses)),
            paid_orders_today=Count("id", filter=Q(paid_at__gte=today_start)),
            paid_orders_30d=Count("id", filter=Q(paid_at__gte=month_ago, status__in=paid_statuses)),
            paid_orders_all_time=Count("id", filter=Q(status__in=paid_statuses)),
            awaiting_payment=Count("id", filter=Q(status=Order.Status.PENDING_PAYMENT)),
            total_orders=Count("id"),
        )

        failed_payments_24h = PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.FAILED,
            created_at__gte=day_ago,
        ).count()
        webhooks_unprocessed = WebhookEvent.objects.filter(processed=False).count()
        webhooks_failing = WebhookEvent.objects.filter(processed=False, failure_count__gt=0).count()
        pending_applications = SellerApplication.objects.filter(
            status=SellerApplication.Status.PENDING
        ).count()
        pending_refunds = Refund.objects.filter(status=Refund.Status.PENDING).count()
        active_coupons = Coupon.objects.filter(active=True).exclude(expires_at__lte=now).count()
        downloads_today = DownloadLog.objects.filter(created_at__gte=today_start).count()
        total_downloads = DownloadLog.objects.count()
        total_products = Product.objects.filter(is_available=True).count()
        total_categories = Category.objects.count()
        total_customers = User.objects.filter(is_staff=False).count()

        is_live = getattr(settings, "PAYMONGO_PUBLIC_KEY", "").startswith("pk_live_")

        cards = [
            {
                "label": "Today's Revenue",
                "value": pesos(order_stats["revenue_today"]),
                "sub": f"{order_stats['paid_orders_today']} paid order(s)",
                "url": "admin:orders_order_changelist",
                "query": "?paid_at__gte=" + today_start.date().isoformat(),
                "tone": "ok",
                "icon": "circle-dollar-sign",
            },
            {
                "label": "30-Day Volume",
                "value": pesos(order_stats["revenue_30d"]),
                "sub": f"{order_stats['paid_orders_30d']} orders · {pesos(order_stats['revenue_all_time'])} all-time",
                "url": "admin:orders_order_changelist",
                "query": f"?paid_at__gte={month_ago.date().isoformat()}&status__in=paid%2Cfulfilled",
                "tone": "default",
                "icon": "trending-up",
            },
            {
                "label": "Pending Payment",
                "value": str(order_stats["awaiting_payment"]),
                "sub": "Awaiting customer QR scan",
                "url": "admin:orders_order_changelist",
                "query": "?status__exact=pending_payment",
                "tone": "warn" if order_stats["awaiting_payment"] else "default",
                "icon": "qr-code",
            },
            {
                "label": "Live Products",
                "value": str(total_products),
                "sub": f"{total_categories} active categories",
                "url": "admin:catalog_product_changelist",
                "query": "?is_available__exact=1",
                "tone": "default",
                "icon": "package",
            },
            {
                "label": "Downloads Served",
                "value": str(downloads_today),
                "sub": f"{total_downloads} total delivered",
                "url": "admin:orders_downloadlog_changelist",
                "query": "",
                "tone": "default",
                "icon": "file-down",
            },
        ]

        attention = []
        if pending_refunds:
            attention.append(
                {
                    "count": pending_refunds,
                    "label": "refund request(s) awaiting review & processing",
                    "url": "admin:payments_refund_changelist",
                    "query": "?status__exact=pending",
                    "tone": "bad",
                }
            )
        if pending_applications:
            attention.append(
                {
                    "count": pending_applications,
                    "label": "creator seller application(s) awaiting review",
                    "url": "admin:seller_sellerapplication_changelist",
                    "query": "?status__exact=pending",
                    "tone": "warn",
                }
            )
        if webhooks_failing:
            attention.append(
                {
                    "count": webhooks_failing,
                    "label": "webhook event(s) failing to process",
                    "url": "admin:payments_webhookevent_changelist",
                    "query": "?processed__exact=0&failing=1",
                    "tone": "bad",
                }
            )
        if webhooks_unprocessed > webhooks_failing:
            attention.append(
                {
                    "count": webhooks_unprocessed - webhooks_failing,
                    "label": "webhook event(s) queued for processing",
                    "url": "admin:payments_webhookevent_changelist",
                    "query": "?processed__exact=0",
                    "tone": "warn",
                }
            )
        if failed_payments_24h:
            attention.append(
                {
                    "count": failed_payments_24h,
                    "label": "failed payment attempt(s) in the last 24 hours",
                    "url": "admin:payments_paymentattempt_changelist",
                    "query": f"?status__exact=failed&created_at__gte={day_ago.date().isoformat()}",
                    "tone": "bad",
                }
            )

        latest = (
            Order.objects.select_related("user")
            .prefetch_related("items", "payment_attempts")
            .order_by("-created_at")[:8]
        )
        for order in latest:
            order.display_total = pesos(order.total_amount)
            attempt = order.payment_attempts.filter(status=PaymentAttempt.Status.SUCCEEDED).first() or order.payment_attempts.first()
            if attempt and attempt.paymongo_payment_id:
                order.paymongo_url = f"https://dashboard.paymongo.com/payments/{attempt.paymongo_payment_id}"
            elif attempt and attempt.paymongo_intent_id:
                order.paymongo_url = f"https://dashboard.paymongo.com/payments?search={attempt.paymongo_intent_id}"
            else:
                order.paymongo_url = "https://dashboard.paymongo.com/payments"

        recent_refunds = (
            Refund.objects.select_related("payment__order")
            .order_by("-created_at")[:5]
        )

        return {
            "is_live": is_live,
            "gateway_mode": "Live Production" if is_live else "Sandbox / Test",
            "cards": cards,
            "attention": attention,
            "latest_orders": latest,
            "recent_refunds": recent_refunds,
            "total_customers": total_customers,
            "total_products": total_products,
        }


admin_site = VirtusAdminSite(name="admin")
