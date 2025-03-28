"""Constants for YNAB Custom integration."""

DOMAIN = "ynab_custom"

CONF_SELECTED_ACCOUNTS = "Select Accounts to Import"
CONF_SELECTED_CATEGORIES = "Select Categories to Import"
CONF_CURRENCY = "Select Currency"
CONF_SELECTED_BUDGET = "Select Budget to Import"
CONF_UPDATE_INTERVAL = "Update Interval"
CONF_BUDGET_NAME = "budget_name"
DEFAULT_UPDATE_INTERVAL = 10  # Default to 10 minutes


PLATFORMS = ["sensor"]

def get_currency_symbol(currency_code):
    """Convert currency code to symbol."""
    currency_map = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "AUD": "A$",
        "CAD": "C$",
        "JPY": "¥",
        "CHF": "CHF",
        "SEK": "kr",
        "NZD": "NZ$",
    }
    return currency_map.get(currency_code, "$")  # Default to USD if not found
