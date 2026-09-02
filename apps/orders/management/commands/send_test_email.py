"""Send a test email to verify the mail configuration.

Usage:
    python manage.py send_test_email --to you@example.com
    python manage.py send_test_email --to you@example.com --html
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email through the configured EMAIL_BACKEND."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient email address.")
        parser.add_argument(
            "--html",
            action="store_true",
            help="Also include an HTML alternative part.",
        )

    def handle(self, *args, **options):
        to = options["to"]
        subject = "Virtus test email"
        body = (
            "This is a test email from Virtus.\n\n"
            f"Backend: {settings.EMAIL_BACKEND}\n"
            f"From: {settings.DEFAULT_FROM_EMAIL}\n\n"
            "If you can read this, your email configuration works."
        )

        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to],
        )
        if options["html"]:
            message.attach_alternative(
                "<html><body style='font-family:sans-serif'>"
                "<h2>Virtus test email</h2>"
                f"<p>Backend: <code>{settings.EMAIL_BACKEND}</code></p>"
                "<p>If you can read this, your email configuration works.</p>"
                "</body></html>",
                "text/html",
            )
        try:
            sent = message.send(fail_silently=False)
        except Exception as exc:
            raise CommandError(f"FAILED: {exc}") from exc

        if sent:
            self.stdout.write(
                self.style.SUCCESS(f"Sent test email to {to} via {settings.EMAIL_BACKEND}")
            )
        else:
            self.stderr.write(self.style.ERROR("Message was not sent."))
