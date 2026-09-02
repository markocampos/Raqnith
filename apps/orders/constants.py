CURRENCY = "PHP"
TAX_RATE_PERCENT = 12  # Philippines VAT, applied to the taxable amount.
ORDER_EXPIRATION_MINUTES = 60  # Unpaid orders transition to CANCELLED after 60 minutes.
ORDER_PURGE_DAYS = (
    30  # Unpaid/cancelled orders older than 30 days (1 month) are purged to free storage.
)
ORDER_PURGE_MINUTES = ORDER_PURGE_DAYS * 24 * 60  # 43,200 minutes (30 days)
