"""Recover pending payments: email buyers whose QR expired before paying.

Designed for cron (same cadence as reconcile_payments, e.g. every 10-15
minutes):

    */15 * * * * python manage.py send_recovery_emails

Eligible order = still PENDING_PAYMENT, has an email, is 15-50 minutes old
(fresh enough that the payment window hasn't closed at 60), no recovery
email sent yet. Each buyer gets exactly one nudge with a fresh-QR link.
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.services.email_service import send_payment_recovery

logger = logging.getLogger("payments.recovery")

MIN_AGE_MINUTES = 15
# Orders expire (and cancel) at 60 minutes; stop nudging before that so a
# buyer who clicks still has time to actually pay.
MAX_AGE_MINUTES = 50


class Command(BaseCommand):
    help = (
        "Send one 'your QR expired — here's a fresh one' email per pending "
        "order older than 15 minutes. Safe to run repeatedly."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List eligible orders without sending anything.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        window_start = now - timedelta(minutes=MAX_AGE_MINUTES)
        window_end = now - timedelta(minutes=MIN_AGE_MINUTES)

        eligible = (
            Order.objects.filter(
                status=Order.Status.PENDING_PAYMENT,
                recovery_email_sent_at__isnull=True,
                created_at__range=(window_start, window_end),
            )
            .exclude(email="")
            .order_by("created_at")
        )

        if options["dry_run"]:
            for order in eligible:
                self.stdout.write(f"[dry-run] would email {order.email} — order {order.id}")
            self.stdout.write(self.style.SUCCESS(f"{eligible.count()} order(s) eligible."))
            return

        sent = skipped = 0
        for order in eligible:
            if send_payment_recovery(order):
                sent += 1
            else:
                # Lost an idempotency race or transient failure — either way,
                # don't block the rest of the batch.
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(f"Recovery run complete: {sent} sent, {skipped} skipped.")
        )
