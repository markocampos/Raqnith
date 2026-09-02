import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.models import PaymentAttempt
from apps.payments.services.payment_service import PaymentService
from apps.payments.services.paymongo import (
    PayMongoAPIError,
    PayMongoNetworkError,
    PayMongoTimeoutError,
)

logger = logging.getLogger("payments.reconcile")

# Stale thresholds (minutes): an attempt left in these states longer than the
# threshold is queried against PayMongo and repaired to the provider's truth.
STALE_THRESHOLDS = {
    PaymentAttempt.Status.PROCESSING: 5,
    PaymentAttempt.Status.AWAITING_METHOD: 30,
    PaymentAttempt.Status.AWAITING_ACTION: 30,
}


class Command(BaseCommand):
    """Reconcile ambiguous payment attempts against PayMongo.

    Finds attempts that have been stuck in a non-terminal state past the
    threshold (processing > 5 min, awaiting_* > 30 min), queries the provider,
    and repairs local state. This is the safety net for provider/webhook
    outages: a payment that actually succeeded is settled, one that failed is
    marked failed, and a pending one is left for a later run.
    """

    help = (
        "Reconcile stale/ambiguous payment attempts against PayMongo. "
        "Finds processing > 5min and awaiting_* > 30min, queries the provider, "
        "and repairs local state."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report stale attempts without calling PayMongo or changing state.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        service = PaymentService()

        stale = []
        for status, minutes in STALE_THRESHOLDS.items():
            attempts = PaymentAttempt.objects.filter(
                status=status,
                paymongo_intent_id__isnull=False,
                updated_at__lte=now - timezone.timedelta(minutes=minutes),
            )
            stale.extend(attempts)

        self.stdout.write(f"Found {len(stale)} stale attempt(s).")

        resolved = 0
        errors = 0
        for attempt in stale:
            if dry_run:
                self.stdout.write(
                    f"  would reconcile attempt={attempt.id} "
                    f"order={attempt.order_id} status={attempt.status} "
                    f"intent={attempt.paymongo_intent_id}"
                )
                continue
            try:
                service.reconcile_payment(attempt)
            except (PayMongoTimeoutError, PayMongoNetworkError, PayMongoAPIError) as exc:
                errors += 1
                self.stderr.write(f"  reconcile error attempt={attempt.id}: {exc}")
                logger.warning(
                    "reconcile error attempt=%s order=%s intent=%s error=%s",
                    attempt.id,
                    attempt.order_id,
                    attempt.paymongo_intent_id,
                    exc,
                )
                continue
            attempt.refresh_from_db()
            resolved += 1
            self.stdout.write(f"  reconciled attempt={attempt.id} -> {attempt.status}")

        # 2. Cancel overdue pending orders (> 60 minutes)
        from apps.orders.models import Order

        overdue_orders = Order.objects.filter(
            status=Order.Status.PENDING_PAYMENT,
            created_at__lte=now - timezone.timedelta(minutes=60),
        )
        expired_orders_count = 0
        for order in overdue_orders:
            if dry_run:
                self.stdout.write(f"  would cancel expired order={order.id}")
            else:
                order.transition_to(Order.Status.CANCELLED)
                PaymentAttempt.objects.filter(
                    order=order,
                    status__in=[
                        PaymentAttempt.Status.CREATED,
                        PaymentAttempt.Status.AWAITING_METHOD,
                        PaymentAttempt.Status.AWAITING_ACTION,
                    ],
                ).update(status=PaymentAttempt.Status.CANCELLED)
            expired_orders_count += 1

        # 3. Purge unpaid orders older than 120 minutes (2 hours) to free storage
        purged_count = 0
        if not dry_run:
            purged_count = Order.purge_unpaid_overdue()
        else:
            purged_count = Order.objects.filter(
                created_at__lte=now - timezone.timedelta(minutes=120),
                paid_at__isnull=True,
                status__in=[
                    Order.Status.CANCELLED,
                    Order.Status.PAYMENT_FAILED,
                    Order.Status.DRAFT,
                    Order.Status.PENDING_PAYMENT,
                ],
            ).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {resolved} reconciled, {errors} errored, "
                f"{expired_orders_count} overdue order(s) cancelled, "
                f"{purged_count} stale unpaid order(s) purged."
            )
        )
