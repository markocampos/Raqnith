import pytest

from apps.orders.models import Order
from apps.payments.models import PaymentAttempt


@pytest.fixture
def order():
    return Order.objects.create(subtotal_amount=1000, discount_amount=0, total_amount=1000)


@pytest.fixture
def payment_attempt(order):
    return PaymentAttempt.objects.create(order=order, amount=1000, paymongo_intent_id="pi_test")
