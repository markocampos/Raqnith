class OrderBuildError(Exception):
    """Raised when an order cannot be built from a cart.

    ``errors`` is a dict mapping a field name to a human-readable message,
    suitable for turning directly into an API error payload.
    """

    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"Unable to build order: {errors}")
