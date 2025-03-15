"""YNAB Data Update Coordinator."""

import logging
from datetime import datetime
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from .api import YNABApi
from .const import DOMAIN, CONF_SELECTED_ACCOUNTS, CONF_SELECTED_CATEGORIES, CONF_CURRENCY, CONF_UPDATE_INTERVAL, get_currency_symbol

_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_INTERVAL = 10  # Default to 10 minutes if no user selection

class YNABDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching YNAB data from API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, budget_id: str, budget_name: str):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.budget_id = budget_id
        self.budget_name = budget_name
        self.api = YNABApi(entry.data["access_token"])
        self.selected_accounts = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
        self.selected_categories = entry.data.get(CONF_SELECTED_CATEGORIES, [])
        
        # Get the user-defined update interval from the config entry, with a fallback to the default
        update_interval = self.entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

        # Fetch the currency symbol from the config entry
        self.currency_symbol = get_currency_symbol(self.entry.data.get(CONF_CURRENCY, "USD"))  # Convert to correct symbol
        _LOGGER.error(f"🔴 DEBUG: YNAB Currency Retrieved in Coordinator: {self.currency_symbol}")


        super().__init__(
            hass,
            _LOGGER,
            name=f"YNAB Coordinator - {budget_name}",
            update_interval=timedelta(minutes=update_interval),
        )

    def get_current_month(self):
        """Returns the current month in YYYY-MM-01 format."""
        return datetime.now().strftime("%Y-%m-01")

    async def _async_update_data(self):
        """Fetch budget details from the API."""
        try:
            _LOGGER.debug("Fetching latest YNAB data...")
    
            # Get current month in YYYY-MM-01 format
            current_month = self.get_current_month()
            _LOGGER.debug(f"Fetching data for budget_id: {self.budget_id} and month: {current_month}")  # Log the current month and budget_id
    
            # Fetch data
            budget_data = await self.api.get_budget(self.budget_id)
            accounts = await self.api.get_accounts(self.budget_id)
            categories = await self.api.get_categories(self.budget_id)
            
            # Fetch the monthly summary using the current month
            monthly_summary = await self.api.get_monthly_summary(self.budget_id, current_month)
    
            _LOGGER.debug(f"Accounts Response: {accounts}")
    
            # Filter accounts based on user selection
            budget_data["accounts"] = [
                a for a in accounts.get("accounts", []) if a["id"] in self.selected_accounts
            ]
    
            _LOGGER.debug(f"🔹 Filtered Accounts: {budget_data['accounts']}")
    
            # Filter categories based on user selection
            budget_data["categories"] = [
                c for c_group in categories.get("category_groups", [])
                for c in c_group.get("categories", []) if c["id"] in self.selected_categories
            ]
    
            # Store the monthly summary data
            budget_data["monthly_summary"] = monthly_summary
    
            return budget_data
    
        except Exception as e:
            _LOGGER.error("Error fetching YNAB data: %s", e)
            return {}

    async def manual_refresh(self, call):
        """Manually refresh YNAB data when the service is called."""
        _LOGGER.info("Manual refresh triggered for YNAB.")
        await self.async_refresh()  # Ensures it triggers the refresh / Broken in v1.2.0
