"""Webhook monitoring: self-healing replays, failure tracking, admin alerts."""

import json
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.payments.models import WebhookEvent
from apps.payments.services.alerts import notify_webhook_failures
from apps.payments.tests.helpers import payment_event_payload, sign_payload


class WebhookMonitoringTests(TestCase):
    def setUp(self):
        mail.outbox = []
        self.url = reverse("payments:webhook")

    def _post(self, payload, event_id="evt_1", secret=None, signature=None):
        payload.setdefault("data", {}).setdefault("id", event_id)
        raw_body = json.dumps(payload).encode()
        if signature is None:
            signature = sign_payload(raw_body, secret or settings.PAYMONGO_WEBHOOK_SECRET)
        return self.client.post(
            self.url,
            data=raw_body,
            content_type="application/json",
            HTTP_PAYMONGO_SIGNATURE=signature,
        )

    def _payload(self):
        return payment_event_payload(intent_id="pi_test_1", amount=10000, currency="PHP")

    def test_processed_replay_is_noop(self):
        payload = self._payload()
        first = self._post(payload)
        self.assertEqual(first.status_code, 200)

        # Mark processed manually to simulate a healthy first delivery.
        event = WebhookEvent.objects.get()
        from django.utils import timezone

        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["processed", "processed_at"])

        second = self._post(payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_unprocessed_event_is_retried_not_acked(self):
        """Regression: replays of failed events must be reprocessed, not 200'd."""
        payload = self._payload()

        with patch(
            "apps.payments.views.WebhookService.process_event",
            side_effect=ValueError("boom"),
        ):
            self._post(payload)
        event = WebhookEvent.objects.get()
        self.assertFalse(event.processed)

        from django.utils import timezone

        def succeed(_payload, ev):
            ev.processed = True
            ev.processed_at = timezone.now()
            ev.save(update_fields=["processed", "processed_at"])

        with patch(
            "apps.payments.views.WebhookService.process_event",
            side_effect=succeed,
        ) as mock_process:
            second = self._post(payload)

        self.assertEqual(second.status_code, 200)
        mock_process.assert_called()  # it WAS retried
        event.refresh_from_db()
        self.assertTrue(event.processed)
        self.assertEqual(event.failure_count, 0)  # trail cleared after recovery

    def test_failure_increments_and_records_error(self):
        payload = self._payload()

        with patch(
            "apps.payments.views.WebhookService.process_event",
            side_effect=ValueError("boom"),
        ):
            resp = self._post(payload)

        self.assertEqual(resp.status_code, 500)
        event = WebhookEvent.objects.get()
        self.assertEqual(event.failure_count, 1)
        self.assertIn("boom", event.last_error)
        self.assertFalse(event.processed)

    @override_settings(WEBHOOK_ALERT_THRESHOLD=2)
    def test_alert_sent_once_at_threshold(self):
        payload = self._payload()

        with patch(
            "apps.payments.views.WebhookService.process_event",
            side_effect=ValueError("boom"),
        ):
            self._post(payload)  # failure 1 — below threshold, no email
            self.assertEqual(len(mail.outbox), 0)
            event = WebhookEvent.objects.get()
            self.assertEqual(event.failure_count, 1)

            self._post(payload)  # failure 2 — crosses threshold → alert

        event.refresh_from_db()
        self.assertEqual(event.failure_count, 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Webhook failing", mail.outbox[0].subject)
        self.assertIn("boom", mail.outbox[0].body)

        # Third failure does NOT spam another alert.
        with patch(
            "apps.payments.views.WebhookService.process_event",
            side_effect=ValueError("boom again"),
        ):
            self._post(payload)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(ADMIN_NOTIFY_EMAIL="ops@virtus.test", ADMINS=[])
    def test_alert_recipient_from_env_setting(self):
        sent = notify_webhook_failures(_fake_event(failure_count=3), threshold=3)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ops@virtus.test"])

    @override_settings(ADMIN_NOTIFY_EMAIL="", ADMINS=[])
    def test_no_recipients_logs_instead_of_emailing(self):
        sent = notify_webhook_failures(_fake_event(failure_count=3), threshold=3)
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)


def _fake_event(failure_count):
    from types import SimpleNamespace

    return SimpleNamespace(
        provider_event_id="evt_fake",
        event_type="payment.paid",
        received_at=None,
        failure_count=failure_count,
        last_error="ValueError: boom",
    )
