import hashlib
import hmac

import httpx

from apps.payments.services.paymongo import PayMongoClient


def payment_event_payload(
    event_id="evt_test_1",
    event_type="payment.paid",
    intent_id="pi_test_1",
    amount=10000,
    currency="PHP",
    status="paid",
    payment_method="qrph",
    brand=None,
    last4=None,
):
    """Build a PayMongo webhook event payload (payment.paid/failed shape)."""
    source = {"id": "src_test_1", "type": payment_method}
    if brand:
        source["brand"] = brand
    if last4:
        source["last4"] = last4
    return {
        "data": {
            "id": event_id,
            "type": "event",
            "attributes": {
                "type": event_type,
                "livemode": False,
                "created_at": 1700000000,
                "data": {
                    "id": "pay_test_1",
                    "type": "payment",
                    "attributes": {
                        "amount": amount,
                        "currency": currency,
                        "status": status,
                        "payment_intent_id": intent_id,
                        "source": source,
                    },
                },
            },
        }
    }


def sign_payload(raw_body, secret, timestamp="1700000000", live=True):
    """Return the PayMongo webhook Paymongo-Signature header string for ``raw_body``."""
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    to_sign = f"{timestamp}.".encode() + raw_body
    sig = hmac.new(secret.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()
    if live:
        return f"t={timestamp},te=,li={sig}"
    return f"t={timestamp},te={sig},li="


def make_mock_client(handler):
    """Build a PayMongoClient backed by httpx.MockTransport(handler)."""
    return PayMongoClient("sk_test_stub", transport=httpx.MockTransport(handler))


def intent_payload(
    intent_id="pi_test_1",
    client_key="ck_test_1",
    amount=10000,
    currency="PHP",
    status="awaiting_next_action",
    qr_image_url=None,
    redirect_url=None,
    source=None,
):
    """Build a Payment Intent payload.

    After a successful attach the intent is ``awaiting_next_action`` and
    ``next_action`` carries either the QR image (``code.image_url``) for QR Ph
    or the provider redirect URL for e-wallets.
    """
    attributes = {
        "client_key": client_key,
        "amount": amount,
        "currency": currency,
        "status": status,
    }
    if qr_image_url:
        attributes["next_action"] = {"type": "qr_code", "code": {"image_url": qr_image_url}}
    elif redirect_url:
        attributes["next_action"] = {"type": "redirect", "redirect": {"url": redirect_url}}
    if source is not None:
        attributes["source"] = source
    return {
        "data": {
            "id": intent_id,
            "type": "payment_intent",
            "attributes": attributes,
        }
    }


def payment_method_payload(method_id="pm_test_1", payment_type="qrph"):
    """Build a Payment Method payload for a non-sensitive method (qrph/gcash/...)."""
    return {
        "data": {
            "id": method_id,
            "type": "payment_method",
            "attributes": {"type": payment_type},
        }
    }


def intent_flow_handler(
    payment_type="qrph",
    intent_id="pi_test_1",
    client_key="ck_test_1",
    amount=10000,
    qr_image_url="data:image/png;base64,aGVsbG8=",
    redirect_url=None,
    status="awaiting_next_action",
):
    """Build a transport handler for the full server-side intent workflow.

    Serves, in order: create Payment Intent, create Payment Method, attach
    Payment Method (which returns the QR image or redirect URL).
    """
    if redirect_url:
        qr_image_url = None

    def handler(request):
        path = str(request.url)
        if path.endswith("/payment_methods"):
            return httpx.Response(201, json=payment_method_payload(payment_type=payment_type))
        if "/attach" in path:
            return httpx.Response(
                200,
                json=intent_payload(
                    intent_id=intent_id,
                    client_key=client_key,
                    amount=amount,
                    status=status,
                    qr_image_url=qr_image_url,
                    redirect_url=redirect_url,
                ),
            )
        # create payment intent
        return httpx.Response(201, json=intent_payload(intent_id=intent_id, amount=amount))

    return handler


def error_payload(code, detail):
    return {"errors": [{"code": code, "detail": detail}]}
