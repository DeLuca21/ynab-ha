import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import aiohttp
import logging

from .const import DOMAIN

API_URL = "https://api.youneedabudget.com/v1"
_LOGGER = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = {
    "USD": "US Dollar ($)",
    "EUR": "Euro (€)",
    "GBP": "British Pound (£)",
    "AUD": "Australian Dollar (A$)",
    "CAD": "Canadian Dollar (C$)",
    "NZD": "New Zealand Dollar (NZ$)",
    "JPY": "Japanese Yen (¥)",
}

default_update_interval = 300  # in seconds
default_category_group_summaries = True

async def async_get_ynab_budgets(api_key, hass):
    """Fetch budgets from YNAB API asynchronously."""
    headers = {"Authorization": f"Bearer {api_key}"}
    session = async_get_clientsession(hass)

    try:
        async with session.get(f"{API_URL}/budgets", headers=headers, timeout=10) as response:
            response.raise_for_status()
            data = await response.json()
            return {budget["id"]: budget["name"] for budget in data["data"]["budgets"]}
    except aiohttp.ClientError as e:
        _LOGGER.error("YNAB API error: %s", e)
        return {}

class YNABConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the YNAB config flow."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors = {}

        if user_input is not None:
            api_key = user_input["api_key"]
            budgets = await async_get_ynab_budgets(api_key, self.hass)

            if not budgets:
                errors["base"] = "no_budgets_found"
            else:
                self.budgets = budgets
                self.api_key = api_key
                return await self.async_step_budget_selection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("api_key"): str
                }
            ),
            errors=errors,
        )

    async def async_step_budget_selection(self, user_input=None):
        """Let user select a budget, set instance name, and choose currency."""
        errors = {}

        if user_input is not None:
            return self.async_create_entry(
                title=user_input["instance_name"] or self.budgets[user_input["budget_id"]],
                data={
                    "api_key": self.api_key,
                    "budget_id": user_input["budget_id"],
                    "instance_name": user_input["instance_name"],
                },
                options={
                    "currency": user_input["currency"],
                    "update_interval": default_update_interval,
                    "category_group_summaries": default_category_group_summaries
                }
            )

        return self.async_show_form(
            step_id="budget_selection",
            data_schema=vol.Schema({
                vol.Required("budget_id"): vol.In(self.budgets),
                vol.Required("instance_name", default=""): str,
                vol.Required("currency", default="USD"): vol.In(SUPPORTED_CURRENCIES)
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return YNABOptionsFlowHandler(config_entry)

class YNABOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for YNAB."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "currency",
                    default=self._config_entry.options.get("currency", "USD")
                ): vol.In(SUPPORTED_CURRENCIES),
                vol.Optional(
                    "update_interval",
                    default=self._config_entry.options.get("update_interval", default_update_interval)
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                vol.Optional(
                    "category_group_summaries",
                    default=self._config_entry.options.get("category_group_summaries", default_category_group_summaries)
                ): bool
            })
        )
