from django import template

register = template.Library()


@register.filter
def centavos(value):
    """Format an integer number of centavos as ₱1,234.56."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""
    return f"₱{value // 100:,}.{value % 100:02d}"


@register.filter
def php_or_free(value):
    """Format centavos as ₱1,234.56, or "Free" when below the minimum
    transaction amount (₱1). Sub-₱1 products are free at checkout."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""
    if value < 100:
        return "Free"
    return f"₱{value // 100:,}.{value % 100:02d}"


@register.filter(name="cents_to_php")
def cents_to_php(value):
    return centavos(value)


@register.filter
def pesos_raw(value):
    """Return centavos as a plain decimal string (e.g. 49900 -> "499.00").

    Used for machine-readable price output such as JSON-LD.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""
    return f"{value / 100:.2f}"
