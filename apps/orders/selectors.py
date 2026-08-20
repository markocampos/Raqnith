from apps.orders.models import Order


def get_order_for_checkout(order_id, user_or_session):
    """Return the order only if it belongs to the caller.

    ``user_or_session`` is either a user object or a session key string.
    Raises Order.DoesNotExist when the order is missing or owned by someone
    else, so callers cannot enumerate other customers' orders.
    """
    order = Order.objects.select_related("user").get(id=order_id)

    if user_or_session is None:
        raise Order.DoesNotExist("Order not found.")

    if isinstance(user_or_session, str):
        if order.session_key != user_or_session:
            raise Order.DoesNotExist("Order not found.")
    elif order.user_id != user_or_session.id:
        raise Order.DoesNotExist("Order not found.")

    return order


