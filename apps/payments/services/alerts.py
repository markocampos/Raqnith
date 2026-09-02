"""Operations alerts that reach a human, not just the log file."""

import logging
import socket

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger("payments.alerts")


def admin_recipients():
    """Emails from settings.ADMINS plus ADMIN_NOTIFY_EMAIL env override."""
    recipients = {email for _name, email in getattr(settings, "ADMINS", ()) or ()}
    if getattr(settings, "ADMIN_NOTIFY_EMAIL", ""):
        recipients.add(settings.ADMIN_NOTIFY_EMAIL)
    return sorted(recipients)


def notify_webhook_failures(webhook_event, threshold):
    """Alert admins once when an event keeps failing to process.

    Called by the webhook view after each processing failure; the email goes
    out exactly when ``failure_count`` first reaches ``threshold`` so PayMongo
    retries don't flood the inbox.
    """
    if not webhook_event.failure_count or webhook_event.failure_count < threshold:
        return False
    if webhook_event.failure_count > threshold:
        return False  # already alerted at the threshold crossing

    recipients = admin_recipients()
    if not recipients:
        logger.error(
            "Webhook event %s failed %s times but no admin email is configured "
            "(set DJANGO_ADMIN_NOTIFY_EMAIL). Last error: %s",
            webhook_event.provider_event_id,
            webhook_event.failure_count,
            webhook_event.last_error,
        )
        return False

    subject = f"[Virtus] Webhook failing: {webhook_event.event_type}"
    body = (
        f"A PayMongo webhook has failed to process {webhook_event.failure_count} times.\n\n"
        f"Event type:  {webhook_event.event_type}\n"
        f"Event ID:    {webhook_event.provider_event_id}\n"
        f"Received:    {webhook_event.received_at}\n"
        f"Host:        {socket.gethostname()}\n\n"
        f"Last error:\n{webhook_event.last_error or '(none recorded)'}\n\n"
        "Money movement may be missing locally. Check the Payments admin and "
        "the reconcile_payments command output."
    )
    try:
        EmailMessage(
            subject=subject,
            body=body,
            from_email=getattr(settings, "SERVER_EMAIL", None),
            to=recipients,
        ).send(fail_silently=False)
        logger.warning(
            "webhook alert sent event=%s failures=%s",
            webhook_event.provider_event_id,
            webhook_event.failure_count,
        )
        return True
    except Exception:
        # Alerting must never break webhook handling.
        logger.exception("Failed to send webhook alert for %s.", webhook_event.id)
        return False
