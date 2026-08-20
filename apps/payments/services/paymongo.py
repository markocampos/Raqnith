import hashlib
import hmac

import httpx

DEFAULT_BASE_URL = "https://api.paymongo.com/v1"


class PayMongoAPIError(Exception):
    """PayMongo returned a non-2xx response."""

    def __init__(self, status_code, code, message):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"PayMongo API error {status_code} ({code}): {message}")


class PayMongoNetworkError(Exception):
    """A transport-level failure (DNS, connection refused, etc.)."""


class PayMongoTimeoutError(Exception):
    """The request timed out; the payment outcome is unknown."""


class InvalidWebhookSignature(Exception):
    """A webhook signature is missing or does not match the signed body."""


class PayMongoClient:
    """Thin HTTP client for the PayMongo API.

    All PayMongo communication goes through this class; card data is never
    handled here (it goes browser → PayMongo directly). The transport is
    injectable so tests can use httpx.MockTransport.
    """

    def __init__(self, secret_key, *, base_url=DEFAULT_BASE_URL, transport=None, timeout=30.0):
        self.secret_key = secret_key
        self.base_url = base_url
        self._transport = transport
        self._timeout = timeout

    def _client(self):
        return httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(self.secret_key, ""),
            transport=self._transport,
            timeout=self._timeout,
        )

    def _request(self, method, path, json=None):
        try:
            with self._client() as client:
                response = client.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            raise PayMongoTimeoutError(str(exc)) from exc
        except httpx.NetworkError as exc:
            raise PayMongoNetworkError(str(exc)) from exc

        payload = self._parse_json(response)
        if response.is_error:
            code, message = self._extract_error(payload, response)
            raise PayMongoAPIError(response.status_code, code, message)

        return payload

    @staticmethod
    def _parse_json(response):
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _extract_error(payload, response):
        code = "unknown_error"
        message = response.text or "Unknown error."
        if isinstance(payload, dict):
            errors = payload.get("errors") or []
            if errors and isinstance(errors[0], dict):
                code = errors[0].get("code", code)
                message = errors[0].get("detail", message)
        return code, message

    def create_payment_intent(
        self,
        *,
        amount,
        currency,
        description="",
        statement_descriptor="",
        payment_method_allowed=None,
        metadata=None,
    ):
        attributes = {
            "amount": amount,
            "currency": currency,
            "payment_method_allowed": payment_method_allowed or [],
        }
        if metadata:
            attributes["metadata"] = metadata
        if description:
            attributes["description"] = description
        if statement_descriptor:
            attributes["statement_descriptor"] = statement_descriptor
        body = {"data": {"attributes": attributes}}
        payload = self._request("POST", "/payment_intents", json=body)
        return self._flatten_intent(payload)

    def retrieve_payment_intent(self, intent_id):
        payload = self._request("GET", f"/payment_intents/{intent_id}")
        return self._flatten_intent(payload)

    def refund_payment(self, payment_id, amount, reason=""):
        """Create a PayMongo refund against a payment.

        PayMongo refunds are issued against a payment ID (not an intent). The
        amount is in centavos and must not exceed the captured amount.
        """
        body = {
            "data": {
                "attributes": {
                    "payment_id": payment_id,
                    "amount": amount,
                    "reason": reason or "requested_by_customer",
                }
            }
        }
        payload = self._request("POST", "/refunds", json=body)
        data = (payload or {}).get("data", {})
        attributes = data.get("attributes", {})
        return {
            "id": data.get("id"),
            "amount": attributes.get("amount"),
            "currency": attributes.get("currency"),
            "status": attributes.get("status"),
            "payment_id": attributes.get("payment_id"),
        }

    def create_payment_method(self, payment_type):
        """Create a provider payment method for an e-wallet.

        E-wallet payment methods (gcash/maya) carry no sensitive data, so they
        can be created server-side without expanding PCI scope. Returns the
        flattened payment method id.
        """
        body = {"data": {"attributes": {"type": payment_type}}}
        payload = self._request("POST", "/payment_methods", json=body)
        data = (payload or {}).get("data", {})
        return {"id": data.get("id"), "type": data.get("type")}

    def attach_payment_method(self, intent_id, payment_method_id, client_key=None, return_url=""):
        """Attach a payment method to a Payment Intent.

        Server-side attach uses the secret key, so ``client_key`` is not
        required. After attach the intent moves to ``awaiting_next_action`` and
        ``next_action`` carries the QR image (QR Ph) or the redirect URL
        (e-wallets). E-wallets require ``return_url``: the page the customer
        lands on after provider authentication.
        """
        attributes = {"payment_method": payment_method_id}
        if client_key:
            attributes["client_key"] = client_key
        if return_url:
            attributes["return_url"] = return_url
        body = {"data": {"attributes": attributes}}
        payload = self._request("POST", f"/payment_intents/{intent_id}/attach", json=body)
        return self._flatten_intent(payload)

    @staticmethod
    def _flatten_intent(payload):
        data = (payload or {}).get("data", {})
        attributes = data.get("attributes", {})
        # The intent may expose the payment source (brand/last4) directly or via
        # its payments relationship, once a payment has been made.
        payments = attributes.get("payments") or []
        source = attributes.get("source")
        payment_id = None
        if not source and isinstance(payments, list) and payments:
            source = (payments[0] or {}).get("source")
            payment_id = (payments[0] or {}).get("id")
        return {
            "id": data.get("id"),
            "client_key": attributes.get("client_key"),
            "amount": attributes.get("amount"),
            "currency": attributes.get("currency"),
            "status": attributes.get("status"),
            "payment_method_id": attributes.get("payment_method_id"),
            "last_payment_error": attributes.get("last_payment_error"),
            "next_action": attributes.get("next_action"),
            "source": source,
            "payment_id": payment_id,
        }


def verify_webhook_signature(raw_body, signature_header, secret):
    """Verify a PayMongo webhook signature.

    PayMongo signs the raw request body with HMAC-SHA256 using the endpoint's
    ``whsk_...`` secret and places the timestamp and signatures in the
    ``Paymongo-Signature`` header (e.g. ``t=1675323267,te=...,li=...``).
    The comparison is constant-time.

    Raises InvalidWebhookSignature when the header is missing or the digest
    does not match; returns None on success.
    """
    if not secret:
        raise InvalidWebhookSignature("Webhook secret is not configured.")
    if not signature_header:
        raise InvalidWebhookSignature("Missing signature header.")

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    # PayMongo signature header format: t=<timestamp>,te=<test_sig>,li=<live_sig>
    parts = {}
    for item in signature_header.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            parts[k.strip()] = v.strip()

    if "t" in parts:
        timestamp = parts["t"]
        payload_to_sign = f"{timestamp}.".encode("utf-8") + raw_body
        expected = hmac.new(secret.encode("utf-8"), payload_to_sign, hashlib.sha256).hexdigest()

        signatures = [parts[k] for k in ("li", "te") if parts.get(k)]
        if not signatures:
            signatures = [v for k, v in parts.items() if k != "t" and v]

        for sig in signatures:
            if hmac.compare_digest(expected, sig):
                return
        raise InvalidWebhookSignature("Signature mismatch.")
    else:
        # Fallback for bare hex signatures
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        actual = signature_header.strip()
        if not hmac.compare_digest(expected, actual):
            raise InvalidWebhookSignature("Signature mismatch.")
