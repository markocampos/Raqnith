"""Order confirmation email — sent exactly once per order.

The buyer-facing promise ("Receipt sent to …") is kept here: a friendly
receipt with a signed download link that works on any device, account or
not. Failures never break settlement; they are logged for retry.
"""

import logging

from django.conf import settings
from django.contrib.humanize.templatetags.humanize import intcomma
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.services.delivery import order_access_token

logger = logging.getLogger(__name__)


def _money(cents):
    """Format integer centavos as ₱2,499.00 (AGENTS.md copy rules)."""
    return f"₱{intcomma(int(cents) // 100)}.{int(cents) % 100:02d}"


def build_confirmation_context(order):
    """Everything the email templates need (no request object required)."""
    from apps.orders.models import LicenseKey

    token = order_access_token(order)
    base = settings.BASE_URL.rstrip("/")
    free_order = order.total_amount < 100
    return {
        "order": order,
        "items": list(order.items.select_related("product")),
        "total": "Free" if free_order else _money(order.total_amount),
        "subtotal": _money(order.subtotal_amount),
        "discount": _money(order.discount_amount) if order.discount_amount else "",
        "is_free_order": free_order,
        "license_keys": LicenseKey.objects.filter(
            order_item__order=order, revoked_at__isnull=True
        ).select_related("order_item__product"),
        "memberships": [i for i in order.items.select_related("product") if i.access_until],
        "access_url": f"{base}{reverse('orders:access', args=[token])}",
        "receipt_url": f"{base}{reverse('orders:receipt', args=[order.id])}",
        "track_url": f"{base}{reverse('orders:track')}",
    }


def send_payment_recovery(order):
    """Nudge a buyer whose QR expired before they paid ("here's a fresh one").

    Called by the ``send_recovery_emails`` command ~15+ minutes after the
    order went pending. Idempotent via an atomic claim on
    ``recovery_email_sent_at``; never raises.
    """
    if not order.email:
        return False

    claimed = Order.objects.filter(
        pk=order.pk,
        recovery_email_sent_at__isnull=True,
        status=Order.Status.PENDING_PAYMENT,
    ).update(recovery_email_sent_at=timezone.now())
    if not claimed:
        return False

    try:
        base = settings.BASE_URL.rstrip("/")
        context = {
            "order": order,
            "items": list(order.items.select_related("product")),
            "total": _money(order.total_amount),
            "pay_url": f"{base}{reverse('orders:resume', args=[order.id])}",
            "track_url": f"{base}{reverse('orders:track')}",
        }
        subject = render_to_string(
            "emails/payment_recovery_subject.txt", context
        ).strip()
        text_body = render_to_string("emails/payment_recovery.txt", context)
        html_body = render_to_string("emails/payment_recovery.html", context)

        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[order.email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
        logger.info("Recovery email sent order=%s to=%s", order.id, order.email)
        return True
    except Exception:
        # Allow the next scheduled run to retry.
        Order.objects.filter(pk=order.pk).update(recovery_email_sent_at=None)
        logger.exception("Failed to send recovery email for order %s.", order.id)
        return False


def send_order_confirmation(order):
    """Send the receipt email once. Safe to call from every settle path."""
    if not order.email:
        logger.info("No email on order %s; skipping confirmation.", order.id)
        return False

    # Atomic claim so concurrent settle paths can't double-send.
    claimed = Order.objects.filter(
        pk=order.pk, confirmation_sent_at__isnull=True
    ).update(confirmation_sent_at=timezone.now())
    if not claimed:
        return False

    try:
        context = build_confirmation_context(order)
        subject = render_to_string(
            "emails/order_confirmation_subject.txt", context
        ).strip()
        text_body = render_to_string("emails/order_confirmation.txt", context)
        html_body = render_to_string("emails/order_confirmation.html", context)

        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[order.email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)

        logger.info("Confirmation email sent order=%s to=%s", order.id, order.email)
        return True
    except Exception:
        # Never block settlement on delivery hiccups. Reset the guard so the
        # next reconcile/retry can attempt the send again.
        Order.objects.filter(pk=order.pk).update(confirmation_sent_at=None)
        logger.exception("Failed to send confirmation for order %s.", order.id)
        return False
