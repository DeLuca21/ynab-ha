"""YNAB Data Update Coordinator."""

import logging
from datetime import datetime, timedelta
from collections import deque
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store
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
        
        
        # Initialize shared request tracking in HA data registry
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        
        # Create a shared request tracking key for this API token
        api_token_key = f"api_tracking_{entry.data['access_token'][-8:]}"  # Last 8 chars for uniqueness
        
        if api_token_key not in hass.data[DOMAIN]:
            hass.data[DOMAIN][api_token_key] = {
                "request_timestamps": deque(),
                "total_requests": 0
            }
        
        # Pass the shared tracking to the API instance
        self.api = YNABApi(entry.data["access_token"], hass.data[DOMAIN][api_token_key])
        self.selected_accounts = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
        self.selected_categories = entry.data.get(CONF_SELECTED_CATEGORIES, [])
        
        # Initialize API status tracking
        self.api_status = {
            "status": "Unknown",
            "last_error": "None",
            "last_error_time": "Never",
            "consecutive_failures": 0,
            "last_successful_request": "Never",
            "requests_made_total": 0,
            "requests_this_hour": 0,
            "estimated_remaining": 200,
            "rate_limit_resets_at": "Unknown",
            "is_at_limit": False,
        }
        
        # Create persistent data key for this budget
        self.persistent_data_key = f"ynab_data_{entry.entry_id}"
        
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
        
        # Load any existing persistent data
        # Note: This will be called asynchronously during coordinator initialization

    async def async_load_persistent_data(self):
        """Load persistent data during coordinator initialization."""
        await self._load_persistent_data()

    def get_current_month(self):
        """Returns the current month in YYYY-MM-01 format."""
        return datetime.now().strftime("%Y-%m-01")
    
    async def _load_persistent_data(self):
        """Load persistent data from HA storage."""
        try:
            # Use HA's built-in storage system for true persistence
            store = Store(
                self.hass,
                version=1,
                key=f"ynab_data_{self.entry.entry_id}",
                private=True
            )
            
            # Load data asynchronously
            persistent_data = await store.async_load()
            if persistent_data:
                # Set the coordinator's data to the persistent data
                self.data = persistent_data
                # Also restore the API status from persistent data
                if "api_status" in persistent_data:
                    self.api_status.update(persistent_data["api_status"])
        except Exception as e:
            _LOGGER.warning(f"Failed to load persistent data for {self.budget_name}: {e}")
    
    def _save_persistent_data(self, data):
        """Save data to HA storage for true persistence across restarts."""
        try:
            # Use HA's built-in storage system for true persistence
            store = Store(
                self.hass,
                version=1,
                key=f"ynab_data_{self.entry.entry_id}",
                private=True
            )
            
            # Save data asynchronously
            self.hass.async_create_task(store.async_save(data))
            _LOGGER.debug(f"💾 Saved persistent data for {self.budget_name}")
        except Exception as e:
            _LOGGER.warning(f"Failed to save persistent data for {self.budget_name}: {e}")

    async def _async_update_data(self):
        """Fetch budget details from the API."""
        api_call_success = False
        try:
            _LOGGER.debug("Fetching latest YNAB data...")
            
            # Reset consecutive failures on new attempt
            if self.api_status["consecutive_failures"] > 0:
                _LOGGER.debug("Attempting API calls after previous failures...")
    
            # Get current month in YYYY-MM-01 format
            current_month = self.get_current_month()
            _LOGGER.debug(f"Fetching data for budget_id: {self.budget_id} and month: {current_month}")
            
            # Fetch data - each call can potentially fail
            budget_data = await self.api.get_budget(self.budget_id)
            accounts = await self.api.get_accounts(self.budget_id)
            categories = await self.api.get_categories(self.budget_id)
            
            # Fetch the monthly summary using the current month
            monthly_summary = await self.api.get_monthly_summary(self.budget_id, current_month)
            transactions = await self.api.get_transactions(self.budget_id)

            # If we get here, all API calls succeeded
            api_call_success = True
            
            # Get rate limit info from API
            rate_limit_info = self.api.get_rate_limit_info()
            
            # Update API status - SUCCESS
            self.api_status.update({
                "status": "Connected",
                "last_error": "None",
                "consecutive_failures": 0,
            })
            
            # Add rate limit info to API status
            self.api_status.update(rate_limit_info)
            
            # Fix is_at_limit logic - check actual status, not just request count
            self.api_status["is_at_limit"] = (self.api_status["status"] == "Rate Limited")

            # Only update last successful poll timestamp when API calls actually succeed
            last_successful_poll = datetime.now().strftime("%B %d, %Y - %I:%M %p")
            
            # Update the api_status with the same timestamp
            self.api_status["last_successful_request"] = last_successful_poll
            
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

            # Store Last Successful Poll in budget_data (only when API calls succeed)
            budget_data["last_successful_poll"] = last_successful_poll

            # Store API status in budget_data
            budget_data["api_status"] = self.api_status.copy()

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

            # Save successful data persistently
            self._save_persistent_data(budget_data)
            
            return budget_data

        except Exception as e:
            # Update API status - FAILURE
            error_time = datetime.now().strftime("%B %d, %Y - %I:%M %p")
            self.api_status["consecutive_failures"] += 1
            self.api_status["last_error_time"] = error_time
            
            # Get rate limit info even during failures
            rate_limit_info = self.api.get_rate_limit_info()
            
            # Determine error type and status
            error_str = str(e)
            if "429" in error_str or "rate limit" in error_str.lower():
                self.api_status["status"] = "Rate Limited"
                self.api_status["last_error"] = "429 - Too Many Requests"
                _LOGGER.warning(f"YNAB API rate limited. Consecutive failures: {self.api_status['consecutive_failures']}")
            elif "401" in error_str or "unauthorized" in error_str.lower():
                self.api_status["status"] = "Unauthorized"
                self.api_status["last_error"] = "401 - Invalid API Token"
            elif "503" in error_str or "service unavailable" in error_str.lower():
                self.api_status["status"] = "Service Unavailable"
                self.api_status["last_error"] = "503 - YNAB Service Down"
            else:
                self.api_status["status"] = "API Error"
                self.api_status["last_error"] = f"Error: {error_str[:100]}"  # Truncate long errors
            
            # Add rate limit info to API status
            self.api_status.update(rate_limit_info)
            
            # Fix is_at_limit logic - check actual status, not just request count
            self.api_status["is_at_limit"] = (self.api_status["status"] == "Rate Limited")
            
            _LOGGER.error("Error fetching YNAB data: %s", e)
            
            # Try to get persistent data if current data is empty
            if not self.data:
                await self._load_persistent_data()
            
            # Keep ALL previous data but update API status - this preserves sensor data when rate limited
            if self.data:
                updated_data = self.data.copy()
                updated_data["api_status"] = self.api_status.copy()
                # Preserve last_successful_poll from previous data
                if "last_successful_poll" in updated_data:
                    updated_data["api_status"]["last_successful_request"] = updated_data["last_successful_poll"]
                _LOGGER.info("🔄 Rate limited - preserving existing sensor data, not updating")
                return updated_data
            else:
                # No previous data - this should not happen during normal operation
                # If we get here, it means the coordinator was reset or this is the first run
                _LOGGER.warning("🔄 No previous data available during API error - this may cause sensors to disappear")
                return {
                    "api_status": self.api_status.copy(),
                    "accounts": [],
                    "categories": [],
                    "transactions": [],
                    "monthly_summary": {},
                    "unapproved_transactions": 0,
                    "uncleared_transactions": 0,
                    "overspent_categories": 0,
                    "needs_attention_count": 0,
                    "last_successful_poll": "Never"
                }

    async def manual_refresh(self, call):
        """Manually refresh YNAB data when the service is called."""
        _LOGGER.info("Manual refresh triggered for YNAB.")
        await self.async_refresh()  # Ensures it triggers the refresh / Broken in v1.2.0
