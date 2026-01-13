from __future__ import annotations

import logging
import re
import voluptuous as vol
from typing import Any, Dict

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.helpers import config_validation as cv
from homeassistant.data_entry_flow import FlowResult
from homeassistant.core import callback

from .const import DOMAIN, CONF_SELECTED_ACCOUNTS, CONF_SELECTED_CATEGORIES, CONF_CURRENCY, CONF_SELECTED_BUDGET, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, CONF_INCLUDE_CLOSED_ACCOUNTS, CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_HIDDEN_CATEGORIES
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
    "CZK": "Kč (Czech Crown)",
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

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return OptionsFlow(config_entry)

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
            
            # Initialize shared request tracking for config flow
            if DOMAIN not in self.hass.data:
                self.hass.data[DOMAIN] = {}
            
            api_token_key = f"api_tracking_{self.access_token[-8:]}"
            if api_token_key not in self.hass.data[DOMAIN]:
                from collections import deque
                self.hass.data[DOMAIN][api_token_key] = {
                    "request_timestamps": deque(),
                    "total_requests": 0
                }
            
            self.api = YNABApi(self.access_token, self.hass.data[DOMAIN][api_token_key])

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
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate limit" in error_str.lower():
                errors["base"] = "rate_limited"
            else:
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

            try:
                # Fetch accounts and categories now that we know the budget
                accounts_response = await self.api.get_accounts(self.budget_id)
                categories_response = await self.api.get_categories(self.budget_id)

                # Store all accounts and categories for later filtering based on user preferences
                self.all_accounts = {a["id"]: a["name"] for a in accounts_response.get("accounts", [])}
                self.all_categories = {
                    c["id"]: c["name"]
                    for group in categories_response.get("category_groups", [])
                    for c in group.get("categories", [])
                }
                
                # Store additional info for filtering
                self.accounts_info = {a["id"]: a for a in accounts_response.get("accounts", [])}
                self.categories_info = {
                    c["id"]: c
                    for group in categories_response.get("category_groups", [])
                    for c in group.get("categories", [])
                }

                _LOGGER.debug("Fetched %d accounts and %d categories", len(self.all_accounts), len(self.all_categories))

                return await self.async_step_config_page()
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate limit" in error_str.lower():
                    errors["base"] = "rate_limited"
                else:
                    _LOGGER.exception("Error fetching accounts/categories")
                    errors["base"] = "unknown"

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
        
        # Filter options - default to excluding closed accounts and hidden categories
        include_closed_accounts = user_input.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)
        include_hidden_categories = user_input.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)
        
        # Apply filtering based on user preferences
        self.accounts = self._filter_accounts(include_closed_accounts)
        self.categories = self._filter_categories(include_hidden_categories)

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
            vol.Optional(CONF_INCLUDE_CLOSED_ACCOUNTS, default=DEFAULT_INCLUDE_CLOSED_ACCOUNTS): bool,  # Checkbox for including closed accounts
            vol.Optional(CONF_INCLUDE_HIDDEN_CATEGORIES, default=DEFAULT_INCLUDE_HIDDEN_CATEGORIES): bool,  # Checkbox for including hidden categories
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

    def _filter_accounts(self, include_closed: bool) -> Dict[str, str]:
        """Filter accounts based on closed status."""
        filtered = {}
        
        for account_id, name in self.all_accounts.items():
            is_closed = self.accounts_info.get(account_id, {}).get("closed", False)
            
            # Skip closed accounts if not including them
            if is_closed and not include_closed:
                continue
            
            # Add (Closed) prefix for closed accounts
            display_name = f"(Closed) {name}" if is_closed else name
            filtered[account_id] = display_name
        
        return filtered

    def _filter_categories(self, include_hidden: bool) -> Dict[str, str]:
        """Filter categories based on hidden status."""
        filtered = {}
        
        for category_id, name in self.all_categories.items():
            is_hidden = self.categories_info.get(category_id, {}).get("hidden", False)
            
            # Skip hidden categories if not including them
            if is_hidden and not include_hidden:
                continue
            
            # Add (Hidden) prefix for hidden categories
            display_name = f"(Hidden) {name}" if is_hidden else name
            filtered[category_id] = display_name
        
        return filtered

    def _build_config_schema(self, defaults: Dict[str, Any]) -> vol.Schema:
        """Build the configuration schema with provided defaults."""
        # Apply filtering based on user preferences
        include_closed = defaults.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)
        include_hidden = defaults.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)
        
        filtered_accounts = self._filter_accounts(include_closed)
        filtered_categories = self._filter_categories(include_hidden)
        
        # Add "Select All" as an option to the dropdown
        account_options = {**filtered_accounts, SELECT_ALL_OPTION: "Select All Accounts"}
        category_options = {**filtered_categories, SELECT_ALL_OPTION: "Select All Categories"}

        return vol.Schema({
            vol.Optional("instance_name", default=defaults.get("instance_name", "")): str,
            vol.Required(CONF_CURRENCY, default=defaults.get(CONF_CURRENCY, "USD")): vol.In(CURRENCY_OPTIONS),
            vol.Required(CONF_UPDATE_INTERVAL, default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): vol.In(POLLING_INTERVAL_OPTIONS),
            vol.Optional(CONF_INCLUDE_CLOSED_ACCOUNTS, default=defaults.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)): bool,
            vol.Optional(CONF_INCLUDE_HIDDEN_CATEGORIES, default=defaults.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)): bool,
            vol.Required(CONF_SELECTED_ACCOUNTS, default=defaults.get(CONF_SELECTED_ACCOUNTS, [SELECT_ALL_OPTION])): cv.multi_select(account_options),
            vol.Required(CONF_SELECTED_CATEGORIES, default=defaults.get(CONF_SELECTED_CATEGORIES, [SELECT_ALL_OPTION])): cv.multi_select(category_options),
        })

class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for YNAB integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        try:
            # Store config entry data we need, not the entry itself
            self.entry_data = config_entry.data
            self.entry_options = config_entry.options
            self.entry_id = config_entry.entry_id
            self.access_token = config_entry.data[CONF_ACCESS_TOKEN]  # Store token directly
            self.budget_id = config_entry.data["budget_id"]
            self.budget_name = config_entry.data["budget_name"]
            
            # We'll initialize the API with shared tracking in async_step_init
            # since we need access to self.hass which isn't available yet
            self.api = None
            
            _LOGGER.debug(f"OptionsFlow initialized for budget: {self.budget_name}")
        except Exception as e:
            _LOGGER.error(f"Error initializing OptionsFlow: {e}")
            raise

    async def async_step_init(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step of options flow."""
        errors = {}
        _LOGGER.debug(f"OptionsFlow async_step_init called with user_input: {user_input is not None}")

        # Initialize API with shared tracking if not already done
        if self.api is None:
            # Initialize shared request tracking for options flow
            if DOMAIN not in self.hass.data:
                self.hass.data[DOMAIN] = {}
            
            api_token_key = f"api_tracking_{self.access_token[-8:]}"
            if api_token_key not in self.hass.data[DOMAIN]:
                from collections import deque
                self.hass.data[DOMAIN][api_token_key] = {
                    "request_timestamps": deque(),
                    "total_requests": 0
                }
            
            self.api = YNABApi(self.access_token, self.hass.data[DOMAIN][api_token_key])
            _LOGGER.debug("OptionsFlow API initialized with shared tracking")

        if user_input is not None:
            # Process the form submission
            instance_name = user_input.get("instance_name", self.entry_data.get("instance_name", self.budget_name))
            selected_currency = user_input.get(CONF_CURRENCY)
            update_interval = user_input.get(CONF_UPDATE_INTERVAL)
            include_closed_accounts = user_input.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)
            include_hidden_categories = user_input.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)
            
            _LOGGER.debug(f"Form submitted with include_closed: {include_closed_accounts}, include_hidden: {include_hidden_categories}")
            selected_accounts = user_input.get(CONF_SELECTED_ACCOUNTS, [])
            selected_categories = user_input.get(CONF_SELECTED_CATEGORIES, [])

            # Handle filtering changes and "Select All" logic
            filtered_accounts = self._filter_accounts(include_closed_accounts)
            filtered_categories = self._filter_categories(include_hidden_categories)
            
            if SELECT_ALL_OPTION in selected_accounts:
                # Select all filtered accounts
                selected_accounts = list(filtered_accounts.keys())
            else:
                # Use the form selection, but add newly available items when checkboxes are enabled
                current_filtered = set(filtered_accounts.keys())
                
                # If include_closed was just enabled, add newly available closed accounts
                old_include_closed = self.entry_options.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)
                if include_closed_accounts and not old_include_closed:
                    # Closed accounts were just enabled, add them to selection
                    newly_available = current_filtered - set(self._filter_accounts(False).keys())
                    selected_accounts = list(set(selected_accounts) | newly_available)
                    _LOGGER.debug(f"Added newly available closed accounts: {newly_available}")
                
                # Filter out accounts that are no longer available
                selected_accounts = [acc for acc in selected_accounts if acc in current_filtered]
            
            if SELECT_ALL_OPTION in selected_categories:
                # Select all filtered categories
                selected_categories = list(filtered_categories.keys())
            else:
                # Use the form selection, but add newly available items when checkboxes are enabled
                current_filtered = set(filtered_categories.keys())
                
                # If include_hidden was just enabled, add newly available hidden categories
                old_include_hidden = self.entry_options.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)
                if include_hidden_categories and not old_include_hidden:
                    # Hidden categories were just enabled, add them to selection
                    newly_available = current_filtered - set(self._filter_categories(False).keys())
                    selected_categories = list(set(selected_categories) | newly_available)
                    _LOGGER.debug(f"Added newly available hidden categories: {newly_available}")
                
                # Filter out categories that are no longer available
                selected_categories = [cat for cat in selected_categories if cat in current_filtered]

            # Update the config entry
            new_data = dict(self.entry_data)
            new_data.update({
                "instance_name": instance_name,
                CONF_CURRENCY: selected_currency,
                CONF_SELECTED_ACCOUNTS: selected_accounts,
                CONF_SELECTED_CATEGORIES: selected_categories,
            })

            new_options = dict(self.entry_options)
            new_options.update({
                CONF_UPDATE_INTERVAL: update_interval,
                CONF_INCLUDE_CLOSED_ACCOUNTS: include_closed_accounts,
                CONF_INCLUDE_HIDDEN_CATEGORIES: include_hidden_categories,
            })

            # Get config entry from hass
            config_entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if config_entry:
                self.hass.config_entries.async_update_entry(
                    config_entry,
                    data=new_data,
                    options=new_options,
                    title=instance_name,
                )

            return self.async_create_entry(title="", data={})

        # Fetch current accounts and categories
        try:
            accounts_response = await self.api.get_accounts(self.budget_id)
            categories_response = await self.api.get_categories(self.budget_id)

            self.all_accounts = {a["id"]: a["name"] for a in accounts_response.get("accounts", [])}
            self.all_categories = {
                c["id"]: c["name"]
                for group in categories_response.get("category_groups", [])
                for c in group.get("categories", [])
            }
            
            # Store additional info for filtering
            self.accounts_info = {a["id"]: a for a in accounts_response.get("accounts", [])}
            self.categories_info = {
                c["id"]: c
                for group in categories_response.get("category_groups", [])
                for c in group.get("categories", [])
            }

        except Exception as e:
            _LOGGER.error(f"Error fetching YNAB data for options: {e}")
            errors["base"] = "cannot_connect"

        if not errors:
            # Get current filter settings - need to check if they were explicitly set
            # If not in options, check if we can infer from current selections
            current_include_closed = self.entry_options.get(CONF_INCLUDE_CLOSED_ACCOUNTS)
            current_include_hidden = self.entry_options.get(CONF_INCLUDE_HIDDEN_CATEGORIES)
            
            # If not explicitly set, try to infer from current account/category selections
            if current_include_closed is None:
                # Check if any currently selected accounts are closed
                selected_accounts = self.entry_data.get(CONF_SELECTED_ACCOUNTS, [])
                closed_account_ids = {
                    acc_id for acc_id, acc_info in self.accounts_info.items() 
                    if acc_info.get("closed", False)
                }
                current_include_closed = bool(set(selected_accounts) & closed_account_ids)
                _LOGGER.debug(f"Inferred include_closed: {current_include_closed} (selected: {len(selected_accounts)}, closed: {len(closed_account_ids)}, intersection: {len(set(selected_accounts) & closed_account_ids)})")
            
            if current_include_hidden is None:
                # Check if any currently selected categories are hidden
                selected_categories = self.entry_data.get(CONF_SELECTED_CATEGORIES, [])
                hidden_category_ids = {
                    cat_id for cat_id, cat_info in self.categories_info.items() 
                    if cat_info.get("hidden", False)
                }
                current_include_hidden = bool(set(selected_categories) & hidden_category_ids)
                _LOGGER.debug(f"Inferred include_hidden: {current_include_hidden} (selected: {len(selected_categories)}, hidden: {len(hidden_category_ids)}, intersection: {len(set(selected_categories) & hidden_category_ids)})")
            
            # Filter current accounts/categories based on current filter settings
            filtered_accounts = self._filter_accounts(current_include_closed)
            filtered_categories = self._filter_categories(current_include_hidden)
            
            # Get all currently selected accounts/categories
            all_current_accounts = self.entry_data.get(CONF_SELECTED_ACCOUNTS, [])
            all_current_categories = self.entry_data.get(CONF_SELECTED_CATEGORIES, [])
            
            # Filter current selections to only include available ones
            current_selected_accounts = [
                acc_id for acc_id in all_current_accounts
                if acc_id in filtered_accounts
            ]
            current_selected_categories = [
                cat_id for cat_id in all_current_categories
                if cat_id in filtered_categories
            ]
            
            # Check if all available items are selected (show "Select All")
            if set(current_selected_accounts) == set(filtered_accounts.keys()) and current_selected_accounts:
                current_selected_accounts = [SELECT_ALL_OPTION]
            # Don't default to "Select All" if no items are selected - let user choose
                
            if set(current_selected_categories) == set(filtered_categories.keys()) and current_selected_categories:
                current_selected_categories = [SELECT_ALL_OPTION]
            # Don't default to "Select All" if no items are selected - let user choose

            # Prepare current values for the form
            current_values = {
                "instance_name": self.entry_data.get("instance_name", self.budget_name),
                CONF_CURRENCY: self.entry_data.get(CONF_CURRENCY, "USD"),
                CONF_UPDATE_INTERVAL: self.entry_options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                CONF_INCLUDE_CLOSED_ACCOUNTS: current_include_closed,
                CONF_INCLUDE_HIDDEN_CATEGORIES: current_include_hidden,
                CONF_SELECTED_ACCOUNTS: current_selected_accounts,
                CONF_SELECTED_CATEGORIES: current_selected_categories,
            }

            schema = self._build_config_schema(current_values)

            return self.async_show_form(
                step_id="init",
                data_schema=schema,
                errors=errors,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    def _filter_accounts(self, include_closed: bool) -> Dict[str, str]:
        """Filter accounts based on closed status."""
        filtered = {}
        
        for account_id, name in self.all_accounts.items():
            is_closed = self.accounts_info.get(account_id, {}).get("closed", False)
            
            # Skip closed accounts if not including them
            if is_closed and not include_closed:
                continue
            
            # Add (Closed) prefix for closed accounts
            display_name = f"(Closed) {name}" if is_closed else name
            filtered[account_id] = display_name
        
        return filtered

    def _filter_categories(self, include_hidden: bool) -> Dict[str, str]:
        """Filter categories based on hidden status."""
        filtered = {}
        
        for category_id, name in self.all_categories.items():
            is_hidden = self.categories_info.get(category_id, {}).get("hidden", False)
            
            # Skip hidden categories if not including them
            if is_hidden and not include_hidden:
                continue
            
            # Add (Hidden) prefix for hidden categories
            display_name = f"(Hidden) {name}" if is_hidden else name
            filtered[category_id] = display_name
        
        return filtered

    def _build_config_schema(self, defaults: Dict[str, Any]) -> vol.Schema:
        """Build the configuration schema with provided defaults."""
        # Apply filtering based on user preferences
        include_closed = defaults.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)
        include_hidden = defaults.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)
        
        filtered_accounts = self._filter_accounts(include_closed)
        filtered_categories = self._filter_categories(include_hidden)
        
        # Add "Select All" as an option to the dropdown
        account_options = {**filtered_accounts, SELECT_ALL_OPTION: "Select All Accounts"}
        category_options = {**filtered_categories, SELECT_ALL_OPTION: "Select All Categories"}

        return vol.Schema({
            vol.Optional("instance_name", default=defaults.get("instance_name", "")): str,
            vol.Required(CONF_CURRENCY, default=defaults.get(CONF_CURRENCY, "USD")): vol.In(CURRENCY_OPTIONS),
            vol.Required(CONF_UPDATE_INTERVAL, default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): vol.In(POLLING_INTERVAL_OPTIONS),
            vol.Optional(CONF_INCLUDE_CLOSED_ACCOUNTS, default=defaults.get(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)): bool,
            vol.Optional(CONF_INCLUDE_HIDDEN_CATEGORIES, default=defaults.get(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)): bool,
            vol.Required(CONF_SELECTED_ACCOUNTS, default=defaults.get(CONF_SELECTED_ACCOUNTS, [SELECT_ALL_OPTION])): cv.multi_select(account_options),
            vol.Required(CONF_SELECTED_CATEGORIES, default=defaults.get(CONF_SELECTED_CATEGORIES, [SELECT_ALL_OPTION])): cv.multi_select(category_options),
        })


# Define CannotConnect exception
class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

# Define InvalidAuth exception
class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate invalid authentication."""
