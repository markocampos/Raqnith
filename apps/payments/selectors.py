from apps.payments.models import PaymentAttempt


def get_attempt_for_user(attempt_uuid, order):
    """Return the attempt belonging to ``order``, or raise DoesNotExist."""
    return PaymentAttempt.objects.get(id=attempt_uuid, order=order)


def get_attempt_for_checkout(attempt_uuid, user_or_session):
    """Return the attempt only if its order belongs to the caller.

    ``user_or_session`` is either a user object or a session key string.
    Raises PaymentAttempt.DoesNotExist when the attempt is missing or owned by
    someone else, so callers cannot enumerate other customers' payments.
    """
    attempt = PaymentAttempt.objects.select_related("order").get(id=attempt_uuid)
    order = attempt.order

    if user_or_session is None:
        raise PaymentAttempt.DoesNotExist("Payment attempt not found.")

    if isinstance(user_or_session, str):
        if order.session_key != user_or_session:
            raise PaymentAttempt.DoesNotExist("Payment attempt not found.")
    elif order.user_id != user_or_session.id:
        raise PaymentAttempt.DoesNotExist("Payment attempt not found.")

    return attempt


