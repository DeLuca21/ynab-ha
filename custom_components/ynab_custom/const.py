"""Constants for YNAB Custom integration."""

DOMAIN = "ynab_custom"

CONF_SELECTED_ACCOUNTS = "Select Accounts to Import"
CONF_SELECTED_CATEGORIES = "Select Categories to Import"
CONF_CURRENCY = "Select Currency"
CONF_SELECTED_BUDGET = "Select Budget to Import"
CONF_UPDATE_INTERVAL = "Update Interval"
CONF_BUDGET_NAME = "budget_name"
CONF_INCLUDE_CLOSED_ACCOUNTS = "Include Closed Accounts"
CONF_INCLUDE_HIDDEN_CATEGORIES = "Include Hidden Categories"
CONF_MONEY_MOVERS = "Users Allowed to Move Money"
DEFAULT_UPDATE_INTERVAL = 10  # Default to 10 minutes
DEFAULT_INCLUDE_CLOSED_ACCOUNTS = False  # Default to excluding closed accounts
DEFAULT_INCLUDE_HIDDEN_CATEGORIES = False  # Default to excluding hidden categories


PLATFORMS = ["sensor"]

SERVICE_MOVE_CATEGORY_MONEY = "move_category_money"
SERVICE_TRANSFER_ACCOUNT_MONEY = "transfer_account_money"
SERVICE_GET_CATEGORY_HISTORY = "get_category_history"
EVENT_MONEY_MOVED = f"{DOMAIN}_money_moved"
READY_TO_ASSIGN_NAMES = ("Inflow: Ready to Assign", "Ready to Assign")

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
        "CZK": "Kč",
        "NIS": "₪",
    }
    return currency_map.get(currency_code, "$")  # Default to USD if not found
