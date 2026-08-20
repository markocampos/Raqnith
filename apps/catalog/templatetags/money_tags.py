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
