"""Options flow for YNAB Custom integration."""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import DOMAIN, CONF_CURRENCY

_LOGGER = logging.getLogger(__name__)

# Predefined options for the update interval (in minutes)
POLLING_INTERVAL_OPTIONS = {i: f"{i} minute{'s' if i > 1 else ''}" for i in range(5, 61)}

class YNABOptionsFlowHandler(config_entries.OptionsFlow):
    """Handles the options flow for YNAB Custom integration."""

    def __init__(self, config_entry):
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the integration options."""
        hass: HomeAssistant = self.hass
        coordinator = hass.data[DOMAIN].get(self.config_entry.entry_id)

        if not coordinator:
            _LOGGER.error("Coordinator not found. Cannot load options.")
            return self.async_abort(reason="unknown_error")

        # Fetch available accounts and categories
        account_options = {acc["id"]: acc["name"] for acc in coordinator.accounts}
        category_options = {cat["id"]: cat["name"] for cat in coordinator.categories}

        # Get user-configured options (default values if not set)
        current_accounts = self.config_entry.options.get("selected_accounts", list(account_options.keys()))
        current_categories = self.config_entry.options.get("selected_categories", list(category_options.keys()))
        current_interval = self.config_entry.options.get("update_interval", 5)
        current_currency = self.config_entry.options.get(CONF_CURRENCY, "USD")

        # Supported currency options
        currency_options = {
            "USD": "$ (US Dollar)",
            "EUR": "€ (Euro)",
            "GBP": "£ (British Pound)",
            "AUD": "A$ (Australian Dollar)",
            "CAD": "C$ (Canadian Dollar)",
            "JPY": "¥ (Japanese Yen)",
            "CHF": "CHF (Swiss Franc)",
            "SEK": "kr (Swedish Krona)",
            "NZD": "NZ$ (New Zealand Dollar)",
        }

        # Allow the user to change the update interval via a dropdown
        schema = vol.Schema({
            vol.Optional("selected_accounts", default=current_accounts): vol.In(account_options),
            vol.Optional("selected_categories", default=current_categories): vol.In(category_options),
            vol.Optional("update_interval", default=current_interval): vol.In(POLLING_INTERVAL_OPTIONS),  # Dropdown for interval
            vol.Optional(CONF_CURRENCY, default=current_currency): vol.In(currency_options),  # Currency selection
        })

        return self.async_show_form(step_id="init", data_schema=schema)
