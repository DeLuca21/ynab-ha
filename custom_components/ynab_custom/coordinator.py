"""YNAB Data Update Coordinator."""

import logging
from datetime import datetime, timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from .api import YNABApi
from .const import DOMAIN, CONF_SELECTED_ACCOUNTS, CONF_SELECTED_CATEGORIES, CONF_CURRENCY, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, get_currency_symbol

_LOGGER = logging.getLogger(__name__)


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
        
        # Get the user-defined update interval with fallbacks: options -> data -> default
        update_interval = (
            self.entry.options.get(CONF_UPDATE_INTERVAL) or 
            self.entry.data.get(CONF_UPDATE_INTERVAL) or 
            DEFAULT_UPDATE_INTERVAL
        )

        # Fetch the currency symbol from the config entry
        self.currency_symbol = get_currency_symbol(self.entry.data.get(CONF_CURRENCY, "USD"))  # Convert to correct symbol



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
            transactions = await self.api.get_transactions(self.budget_id)

            # Update last successful poll timestamp
            self.last_successful_poll = datetime.now().strftime("%B %d, %Y - %I:%M %p")
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
            budget_data["transactions"] = transactions.get("transactions", [])

            # Store Last Successful Poll in self.data
            budget_data["last_successful_poll"] = self.last_successful_poll

            # === New summary counts ===
            all_transactions = budget_data["transactions"]
            unapproved_transactions = len([t for t in all_transactions if not t.get("approved", True)])
            
            # Only count selected accounts that are currently returned from the API and not closed/deleted
            selected_active_account_ids = {
                a["id"]
                for a in accounts.get("accounts", [])
                if not a.get("closed", False)
                and not a.get("deleted", False)
                and a["id"] in [acc["id"] for acc in budget_data["accounts"]]
            }
            
            # Count uncleared transactions (only 'uncleared', non-scheduled, from selected active accounts)
            uncleared_transactions = len([
                t for t in all_transactions
                if t.get("cleared") == "uncleared"
                and t.get("account_id") in selected_active_account_ids
                and not t.get("scheduled_transaction_id")
            ])
            
            # Count categories with a negative balance in the current month's budget
            overspent_categories = len([
                c for c in monthly_summary.get("month", {}).get("categories", [])
                if c.get("balance", 0) < 0
            ])
            
            # Combined attention metric
            needs_attention_count = sum([
                unapproved_transactions > 0,
                uncleared_transactions > 0,
                overspent_categories > 0
            ])

            # Add to coordinator data
            budget_data["unapproved_transactions"] = unapproved_transactions
            budget_data["uncleared_transactions"] = uncleared_transactions
            budget_data["overspent_categories"] = overspent_categories
            budget_data["needs_attention_count"] = needs_attention_count

            return budget_data

        except Exception as e:
            _LOGGER.error("Error fetching YNAB data: %s", e)
            return self.data  # Keep previous data to avoid resetting sensors

    async def manual_refresh(self, call):
        """Manually refresh YNAB data when the service is called."""
        _LOGGER.info("Manual refresh triggered for YNAB.")
        await self.async_refresh()  # Ensures it triggers the refresh / Broken in v1.2.0
