from django.test import SimpleTestCase

from apps.payments.error_map import DEFAULT_ERROR_MESSAGE, translate_error


class ErrorMapTests(SimpleTestCase):
    def test_insufficient_funds(self):
        self.assertEqual(
            translate_error("insufficient_funds"),
            "Your card doesn't have enough available funds. "
            "Try another card or payment method.",
        )

    def test_invalid_cvc(self):
        expected = "Please check your card security code."
        self.assertEqual(translate_error("cvc_invalid"), expected)
        self.assertEqual(translate_error("cvc_incorrect"), expected)

    def test_expired_card(self):
        expected = "This card appears to be expired."
        self.assertEqual(translate_error("card_expired"), expected)
        self.assertEqual(translate_error("expired_card"), expected)

    def test_invalid_card_number(self):
        self.assertEqual(translate_error("card_number_invalid"), "Enter a valid card number.")

    def test_network_timeout(self):
        self.assertEqual(
            translate_error("network_timeout"),
            "We're still checking your payment. Please don't submit another payment yet.",
        )

    def test_generic_decline(self):
        expected = "Your card was declined. Try another card or payment method."
        self.assertEqual(translate_error("generic_decline"), expected)
        self.assertEqual(translate_error("card_declined"), expected)

    def test_unknown_code_falls_back(self):
        self.assertEqual(translate_error("some_mystery_code"), DEFAULT_ERROR_MESSAGE)

    def test_empty_code_falls_back(self):
        self.assertEqual(translate_error(""), DEFAULT_ERROR_MESSAGE)

    def test_none_code_falls_back(self):
        self.assertEqual(translate_error(None), DEFAULT_ERROR_MESSAGE)
