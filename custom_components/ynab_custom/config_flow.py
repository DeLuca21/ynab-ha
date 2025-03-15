from __future__ import annotations

import logging
import voluptuous as vol
from typing import Any, Dict

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.helpers import config_validation as cv
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_SELECTED_ACCOUNTS, CONF_SELECTED_CATEGORIES, CONF_CURRENCY, CONF_SELECTED_BUDGET, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
from .api import YNABApi

_LOGGER = logging.getLogger(__name__)

SELECT_ALL_OPTION = "Select All"

# Supported currency options
CURRENCY_OPTIONS = {
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

# Polling interval options (5-60 minutes)
POLLING_INTERVAL_OPTIONS = {i: f"{i} minute{'s' if i > 1 else ''}" for i in range(5, 61)}

# Function to sanitize the budget name
def sanitize_budget_name(budget_name: str) -> str:
    """Sanitize the budget name to create a valid Home Assistant entity ID."""
    # Replace spaces with underscores and remove any special characters
    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '', budget_name.replace(" ", "_"))
    return sanitized_name

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for YNAB Custom integration."""

    VERSION = "1.2.0"

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step to enter an access token."""
        errors = {}


        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(CONF_ACCESS_TOKEN): str,
                    vol.Required("Accept Terms", default=False): bool  # Checkbox for accepting the terms
                }),
                errors=errors
            )

        # Check if terms are accepted, otherwise prompt again
        if not user_input.get("Accept Terms"):
            errors["base"] = "Terms not accepted, please accept terms to continue"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(CONF_ACCESS_TOKEN): str,
                    vol.Required("Accept Terms", default=False): bool  # Custom label again for consistency
                }),
                errors=errors
            )

        # If terms are accepted, continue the flow
        try:
            self.access_token = user_input[CONF_ACCESS_TOKEN]
            self.api = YNABApi(self.access_token)

            budgets_response = await self.api.get_budgets()
            if not budgets_response or "budgets" not in budgets_response:
                raise CannotConnect

            self.budgets = {b["id"]: b["name"] for b in budgets_response["budgets"]}
            _LOGGER.debug("Available budgets: %s", self.budgets)

            return await self.async_step_budget_selection()

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(step_id="user", errors=errors)

    async def async_step_budget_selection(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Handle budget selection."""
        errors = {}

        if user_input is not None:
            selected_budget_id = user_input[CONF_SELECTED_BUDGET]

            if not selected_budget_id or selected_budget_id not in self.budgets:
                _LOGGER.error("Invalid budget selected: %s", selected_budget_id)
                return self.async_abort(reason="invalid_budget")

            self.budget_id = selected_budget_id
            self.budget_name = self.budgets[self.budget_id]

            # Fetch accounts and categories now that we know the budget
            accounts_response = await self.api.get_accounts(self.budget_id)
            categories_response = await self.api.get_categories(self.budget_id)

            self.accounts = {a["id"]: a["name"] for a in accounts_response.get("accounts", [])}
            self.categories = {
                c["id"]: c["name"]
                for group in categories_response.get("category_groups", [])
                for c in group.get("categories", [])
            }

            _LOGGER.debug("Fetched %d accounts and %d categories", len(self.accounts), len(self.categories))

            return await self.async_step_config_page()

        schema = vol.Schema({
            vol.Required(CONF_SELECTED_BUDGET): vol.In(self.budgets)
        })

        return self.async_show_form(
            step_id="budget_selection",
            data_schema=schema,
            errors=errors
        )

    async def async_step_config_page(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Prompt for instance name, currency, update interval, accounts, and categories on a single page."""
        errors = {}

        # Default values for the prompt fields
        if user_input is None:
            user_input = {}

        selected_accounts = user_input.get(CONF_SELECTED_ACCOUNTS, [SELECT_ALL_OPTION])  # Default to "Select All"
        selected_categories = user_input.get(CONF_SELECTED_CATEGORIES, [SELECT_ALL_OPTION])  # Default to "Select All"

        # Ensure that if a currency was previously selected, it remains selected in UI
        selected_currency = user_input.get(CONF_CURRENCY, getattr(self, "selected_currency", "USD"))

        update_interval = user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)  # Default to 10 minutes

        if user_input:
            self.instance_name = user_input.get("instance_name", self.budget_name)  # Default to raw budget name
            self.selected_currency = selected_currency
            self.update_interval = update_interval

            # If "Select All" is selected, use the entire list of accounts/categories
            if SELECT_ALL_OPTION in selected_accounts:
                selected_accounts = list(self.accounts.keys())
            if SELECT_ALL_OPTION in selected_categories:
                selected_categories = list(self.categories.keys())

            self.selected_accounts = selected_accounts
            self.selected_categories = selected_categories

            return await self.async_step_create_entry()

        # Add "Select All" as an option to the dropdown
        account_options = {**self.accounts, SELECT_ALL_OPTION: "Select All Accounts"}
        category_options = {**self.categories, SELECT_ALL_OPTION: "Select All Categories"}

        schema = vol.Schema({
            vol.Optional("instance_name", default=self.budget_name): str,  # Default to raw budget name
            vol.Required(CONF_CURRENCY, default=self.selected_currency if hasattr(self, "selected_currency") else "USD"): vol.In(CURRENCY_OPTIONS),  # Default currency
            vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.In(POLLING_INTERVAL_OPTIONS),
            vol.Required(CONF_SELECTED_ACCOUNTS, default=[SELECT_ALL_OPTION]): cv.multi_select(account_options),
            vol.Required(CONF_SELECTED_CATEGORIES, default=[SELECT_ALL_OPTION]): cv.multi_select(category_options),
        })
        
        return self.async_show_form(
            step_id="config_page",
            data_schema=schema,
            errors=errors
        )

    async def async_step_create_entry(self) -> FlowResult:
        """Create the entry with the user data."""
        currency_to_store = self.selected_currency 
        _LOGGER.error(f"🔴 DEBUG: Storing selected currency in config entry: {currency_to_store}")
    
        return self.async_create_entry(
            title=self.instance_name,  # Use the raw instance name (display name)
            data={
                CONF_ACCESS_TOKEN: self.access_token,
                "budget_id": self.budget_id,
                "budget_name": self.budget_name,  # Store the raw budget name
                CONF_CURRENCY: currency_to_store,  # Store selected currency
                CONF_SELECTED_ACCOUNTS: self.selected_accounts,
                CONF_SELECTED_CATEGORIES: self.selected_categories,
                "instance_name": self.instance_name,  # Make sure instance_name is added here
            },
            options={  # Store CONF_UPDATE_INTERVAL in options instead of data
                CONF_UPDATE_INTERVAL: self.update_interval
            }
        )

# Define CannotConnect exception
class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

# Define InvalidAuth exception
class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate invalid authentication."""
