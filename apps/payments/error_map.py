"""Friendly, human-readable messages for PayMongo payment errors.

This is the single source of truth for error translation. The Django backend
exposes ``FRIENDLY_ERROR_MESSAGES`` to the checkout template so the browser uses
the exact same mapping, and it is unit-tested here without a browser.

PayMongo decline reasons arrive as a ``sub_code`` (or ``code``) on the payment
intent's ``last_payment_error`` or on the HTTP error response body. We map the
most specific code we recognise and fall back to a generic message otherwise.

Never expose raw fraud/risk codes (``fraudulent``, ``blocked``, …) to the
customer — those deliberately fall through to the generic decline message.
"""

FRIENDLY_ERROR_MESSAGES = {
    # Decline reasons
    "insufficient_funds": (
        "Your card doesn't have enough available funds. "
        "Try another card or payment method."
    ),
    "credit_limit_exceeded": (
        "Your card has reached its credit limit. Try another card."
    ),
    "generic_decline": "Your card was declined. Try another card or payment method.",
    "do_not_honor": "Your card was declined. Try another card or payment method.",
    "payment_refused": "Your card was declined. Try another card or payment method.",
    "card_declined": "Your card was declined. Try another card or payment method.",
    "processor_declined": "Your card was declined. Try another card or payment method.",
    "acquirer_declined": "Your card was declined. Try another card or payment method.",
    "issuer_declined": (
        "Your card was declined by your bank. Please contact them for more information."
    ),
    "card_not_supported": (
        "This card isn't supported for this purchase. Try another card."
    ),
    # Invalid card details
    "card_number_invalid": "Enter a valid card number.",
    "card_type_mismatch": "This card type doesn't match the card number entered.",
    "card_expired": "This card appears to be expired.",
    "expired_card": "This card appears to be expired.",
    "cvc_invalid": "Please check your card security code.",
    "cvc_incorrect": "Please check your card security code.",
    "network_timeout": (
        "We're still checking your payment. Please don't submit another payment yet."
    ),
    "network_error": (
        "We couldn't reach the payment provider. Please check your connection and try again."
    ),
    "qr_expired": "This QR Ph code has expired. Please generate a fresh code to pay.",
    "qrph_expired": "This QR Ph code has expired. Please generate a fresh code to pay.",
}

DEFAULT_ERROR_MESSAGE = (
    "We couldn't process your payment. Please try again or generate a fresh QR code."
)



def translate_error(code):
    """Return a friendly message for a PayMongo error ``code``.

    Unknown, empty, or missing codes return ``DEFAULT_ERROR_MESSAGE`` so no raw
    provider code is ever shown to the customer.
    """
    if not code:
        return DEFAULT_ERROR_MESSAGE
    return FRIENDLY_ERROR_MESSAGES.get(code, DEFAULT_ERROR_MESSAGE)
