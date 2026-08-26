"""Custom admin site for Raqnith with a store-overview dashboard.

The admin index is not just a model list: it surfaces the numbers staff
check every morning (revenue, orders awaiting payment, webhook health,
seller applications) plus the latest orders, so the marketplace can be
operated without touching the ORM.
"""

from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.coupons.models import Coupon
from apps.orders.models import DownloadLog, Order
from apps.payments.models import PaymentAttempt, WebhookEvent
from apps.seller.models import SellerApplication


def pesos(cents):
    """Format integer centavos as a peso string: 249900 -> ₱2,499.00."""
    return f"\u20b1{(cents or 0) / 100:,.2f}"


class RaqnithAdminSite(admin.AdminSite):
    site_header = "Raqnith Admin"
    site_title = "Raqnith Admin"
    index_title = "Store overview"

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
            paid_orders_today=Count("id", filter=Q(paid_at__gte=today_start)),
            paid_orders_30d=Count(
                "id", filter=Q(paid_at__gte=month_ago, status__in=paid_statuses)
            ),
            awaiting_payment=Count(
                "id", filter=Q(status=Order.Status.PENDING_PAYMENT)
            ),
        )

        failed_payments_24h = PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.FAILED,
            created_at__gte=day_ago,
        ).count()
        webhooks_unprocessed = WebhookEvent.objects.filter(processed=False).count()
        webhooks_failing = WebhookEvent.objects.filter(
            processed=False, failure_count__gt=0
        ).count()
        pending_applications = SellerApplication.objects.filter(
            status=SellerApplication.Status.PENDING
        ).count()
        active_coupons = (
            Coupon.objects.filter(active=True).exclude(expires_at__lte=now).count()
        )
        downloads_today = DownloadLog.objects.filter(
            created_at__gte=today_start
        ).count()

        cards = [
            {
                "label": "Revenue today",
                "value": pesos(order_stats["revenue_today"]),
                "sub": f"{order_stats['paid_orders_today']} paid order(s)",
                "url": "admin:orders_order_changelist",
                "query": "?paid_at__gte=" + today_start.date().isoformat(),
                "tone": "good",
            },
            {
                "label": "Revenue · last 30 days",
                "value": pesos(order_stats["revenue_30d"]),
                "sub": f"{order_stats['paid_orders_30d']} paid order(s)",
                "url": "admin:orders_order_changelist",
                "query": f"?paid_at__gte={month_ago.date().isoformat()}&status__in=paid%2Cfulfilled",
                "tone": "",
            },
            {
                "label": "Awaiting payment",
                "value": str(order_stats["awaiting_payment"]),
                "sub": "Orders waiting on QR scan",
                "url": "admin:orders_order_changelist",
                "query": "?status__exact=pending_payment",
                "tone": "warn" if order_stats["awaiting_payment"] else "",
            },
            {
                "label": "Downloads today",
                "value": str(downloads_today),
                "sub": "Files served to buyers",
                "url": "admin:orders_downloadlog_changelist",
                "query": "",
                "tone": "",
            },
            {
                "label": "Active coupons",
                "value": str(active_coupons),
                "sub": "Live discount codes",
                "url": "admin:coupons_coupon_changelist",
                "query": "?active__exact=1",
                "tone": "",
            },
        ]

        attention = []
        if pending_applications:
            attention.append(
                {
                    "count": pending_applications,
                    "label": "seller application(s) awaiting review",
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
            Order.objects.select_related("user").order_by("-created_at")[:8]
        )
        for order in latest:
            order.display_total = pesos(order.total_amount)

        return {
            "cards": cards,
            "attention": attention,
            "latest_orders": latest,
        }


admin_site = RaqnithAdminSite(name="admin")
