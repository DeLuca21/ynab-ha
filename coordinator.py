"""YNAB Data Update Coordinator."""

import logging
from datetime import datetime, timedelta
from collections import deque

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store
from homeassistant.config_entries import ConfigEntry

from .api import YNABApi
from .const import (
    DOMAIN,
    CONF_SELECTED_ACCOUNTS,
    CONF_SELECTED_CATEGORIES,
    CONF_CURRENCY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    get_currency_symbol,
)

_LOGGER = logging.getLogger(__name__)


class YNABDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching YNAB data from API + user values."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        budget_id: str,
        budget_name: str,
        due_days: dict[str, int] | None = None,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.budget_id = budget_id
        self.budget_name = budget_name

        # ================================
        # 🔵 SHARED API REQUEST TRACKING
        # ================================
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}

        api_token_key = f"api_tracking_{entry.data['access_token'][-8:]}"
        if api_token_key not in hass.data[DOMAIN]:
            hass.data[DOMAIN][api_token_key] = {
                "request_timestamps": deque(),
                "total_requests": 0,
            }

        self.api = YNABApi(
            entry.data["access_token"],
            hass.data[DOMAIN][api_token_key],
        )
        self.selected_accounts = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
        self.selected_categories = entry.data.get(CONF_SELECTED_CATEGORIES, [])

        # ================================
        # 🔵 API STATUS STRUCTURE
        # ================================
        self.api_status: dict[str, object] = {
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

        # Keep your persistent key for API data
        self.persistent_data_key = f"ynab_data_{entry.entry_id}"

        # ================================
        # 🔵 USER-EDITABLE VALUE STORAGE
        # ================================
        # Separate store JUST for credit limits / APRs so config_entry
        # changes don’t reload the whole integration.
        self._user_store = Store(
            hass,
            version=1,
            key=f"{DOMAIN}_userdata_{entry.entry_id}",
        )

        # In-memory copies used by entities
        self.credit_limits: dict[str, float] = {}
        self.aprs: dict[str, float] = {}
        self.due_days: dict[str, int] = {}

        # ================================
        # 🔵 CURRENCY + UPDATE INTERVAL
        # ================================
        update_interval = (
            self.entry.options.get(CONF_UPDATE_INTERVAL)
            or self.entry.data.get(CONF_UPDATE_INTERVAL)
            or DEFAULT_UPDATE_INTERVAL
        )

        self.currency_symbol = get_currency_symbol(
            self.entry.data.get(CONF_CURRENCY, "USD")
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"YNAB Coordinator - {budget_name}",
            update_interval=timedelta(minutes=update_interval),
        )

    # ================================================================
    # 🔥 STARTUP LOADING: USER VALUES + API CACHE
    # ================================================================
    async def async_load_persistent_data(self) -> None:
        """Load user values and cached API data at startup."""
        await self._load_user_values()
        await self._load_persistent_data()

    # ----------------------------------------------------------------
    # USER VALUES: CREDIT LIMITS / APRS
    # ----------------------------------------------------------------
    async def _load_user_values(self) -> None:
        """Load credit limits, APRs, and due days from HA storage (with migration)."""
        stored = await self._user_store.async_load() or {}

        self.credit_limits = {
            k: float(v) for k, v in stored.get("credit_limits", {}).items()
        }
        self.aprs = {
            k: float(v) for k, v in stored.get("aprs", {}).items()
        }
        self.due_days = {
            k: int(v) for k, v in stored.get("due_days", {}).items()
        }

        # Migration from old config-entry options
        migrated = False
        opts = self.entry.options

        if not self.credit_limits and "credit_limits" in opts:
            self.credit_limits = {
                k: float(v) for k, v in opts["credit_limits"].items()
            }
            migrated = True

        if not self.aprs and "aprs" in opts:
            self.aprs = {
                k: float(v) for k, v in opts["aprs"].items()
            }
            migrated = True

        if not self.due_days and "due_days" in opts:
            self.due_days = {
                k: int(v) for k, v in opts["due_days"].items()
            }
            migrated = True

        if migrated:
            new_opts = dict(opts)
            new_opts.pop("credit_limits", None)
            new_opts.pop("aprs", None)
            new_opts.pop("due_days", None)

            self.hass.config_entries.async_update_entry(
                self.entry,
                options=new_opts,
            )

            _LOGGER.warning(
                "YNAB: migrated credit_limits/aprs/due_days from config entry → storage"
            )

        # Ensure store is written (covers first-run case)
        await self._user_store.async_save(
            {
                "credit_limits": self.credit_limits,
                "aprs": self.aprs,
                "due_days": self.due_days,
            }
        )

    async def async_save_user_values(self) -> None:
        """Persist user-editable values to storage."""
        await self._user_store.async_save(
            {
                "credit_limits": self.credit_limits,
                "aprs": self.aprs,
                "due_days": self.due_days,
            }
        )
        _LOGGER.debug("Saved YNAB user limits/APRs/due_days to HA storage")

    # Convenient helpers for the Number entities
    def _get_credit_card_accounts(self):
        accounts = self.coordinator.data.get("accounts", [])
        return [a for a in accounts if a.get("type") == "creditCard"]

    def _notify_dependents(self) -> None:
        self.async_set_updated_data(self.data)

    def get_credit_limit(self, account_id: str) -> float:
        return float(self.credit_limits.get(account_id, 0.0))

    def get_apr(self, account_id: str) -> float:
        return float(self.aprs.get(account_id, 0.0))

    def get_due_day(self, account_id: str) -> int | None:
        return self.due_days.get(account_id)

    async def async_set_credit_limit(self, account_id: str, value: float) -> None:
        self.credit_limits[account_id] = float(value)
        await self.async_save_user_values()
        self._notify_dependents()

    async def async_set_due_day(self, account_id: str, value: int) -> None:
        self.due_days[account_id] = int(value)
        await self.async_save_user_values()
        self._notify_dependents()

    async def async_set_apr(self, account_id: str, value: float) -> None:
        self.aprs[account_id] = float(value)
        await self.async_save_user_values()
        self._notify_dependents()

    # ================================================================
    # 🔵 API DATA PERSISTENCE (UNCHANGED CONCEPTUALLY)
    # ================================================================
    async def _load_persistent_data(self) -> None:
        """Load cached API data from HA storage."""
        try:
            store = Store(
                self.hass,
                version=1,
                key=f"ynab_data_{self.entry.entry_id}",
                private=True,
            )
            persistent_data = await store.async_load()
            if persistent_data:
                self.data = persistent_data
                if "api_status" in persistent_data:
                    self.api_status.update(persistent_data["api_status"])
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Failed to load persistent API data for %s: %s",
                self.budget_name,
                exc,
            )

    def _save_persistent_data(self, data: dict) -> None:
        """Store API data snapshot (budget summary, categories, etc.)."""
        try:
            store = Store(
                self.hass,
                version=1,
                key=f"ynab_data_{self.entry.entry_id}",
                private=True,
            )
            self.hass.async_create_task(store.async_save(data))
            _LOGGER.debug(
                "Saved persistent YNAB API dataset for %s",
                self.budget_name,
            )
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Failed to save persistent API data for %s: %s",
                self.budget_name,
                exc,
            )

    # ================================================================
    # 🔵 ORIGINAL UPDATE LOGIC
    # ================================================================
    @staticmethod
    def get_current_month() -> str:
        """Return current month in YYYY-MM-01 format."""
        return datetime.now().strftime("%Y-%m-01")

    async def _async_update_data(self) -> dict:
        """Fetch budget details from the API."""
        try:
            _LOGGER.debug("Fetching latest YNAB data...")

            if self.api_status["consecutive_failures"] > 0:
                _LOGGER.debug("Attempting API calls after previous failures...")

            current_month = self.get_current_month()
            _LOGGER.debug(
                "Fetching data for budget_id: %s and month: %s",
                self.budget_id,
                current_month,
            )

            budget_data = await self.api.get_budget(self.budget_id)
            accounts = await self.api.get_accounts(self.budget_id)
            categories = await self.api.get_categories(self.budget_id)
            monthly_summary = await self.api.get_monthly_summary(
                self.budget_id,
                current_month,
            )
            transactions = await self.api.get_transactions(self.budget_id)

            rate_limit_info = self.api.get_rate_limit_info()

            self.api_status.update(
                {
                    "status": "Connected",
                    "last_error": "None",
                    "consecutive_failures": 0,
                }
            )
            self.api_status.update(rate_limit_info)
            self.api_status["is_at_limit"] = (
                self.api_status["status"] == "Rate Limited"
            )

            last_successful_poll = datetime.now().strftime(
                "%B %d, %Y - %I:%M %p"
            )
            self.api_status["last_successful_request"] = last_successful_poll

            budget_data["accounts"] = [
                a
                for a in accounts.get("accounts", [])
                if a["id"] in self.selected_accounts
            ]
            _LOGGER.debug("Filtered accounts: %s", budget_data["accounts"])
            for account in budget_data["accounts"]:
                account_id = account["id"]

                if account_id in self.credit_limits:
                    account["credit_limit"] = self.credit_limits[account_id]

                if account_id in self.aprs:
                    account["apr"] = self.aprs[account_id]

            budget_data["categories"] = [
                c
                for c_group in categories.get("category_groups", [])
                for c in c_group.get("categories", [])
                if c["id"] in self.selected_categories
            ]

            budget_data["monthly_summary"] = monthly_summary
            budget_data["transactions"] = transactions.get("transactions", [])
            budget_data["last_successful_poll"] = last_successful_poll
            budget_data["api_status"] = self.api_status.copy()

            all_transactions = budget_data["transactions"]
            unapproved_transactions = len(
                [t for t in all_transactions if not t.get("approved", True)]
            )

            selected_active_account_ids = {
                a["id"]
                for a in accounts.get("accounts", [])
                if not a.get("closed", False)
                and not a.get("deleted", False)
                and a["id"]
                in [acc["id"] for acc in budget_data["accounts"]]
            }

            uncleared_transactions = len(
                [
                    t
                    for t in all_transactions
                    if t.get("cleared") == "uncleared"
                    and t.get("account_id") in selected_active_account_ids
                    and not t.get("scheduled_transaction_id")
                ]
            )

            overspent_categories = len(
                [
                    c
                    for c in monthly_summary.get("month", {}).get(
                        "categories", []
                    )
                    if c.get("balance", 0) < 0
                ]
            )

            needs_attention_count = sum(
                [
                    unapproved_transactions > 0,
                    uncleared_transactions > 0,
                    overspent_categories > 0,
                ]
            )

            budget_data["unapproved_transactions"] = unapproved_transactions
            budget_data["uncleared_transactions"] = uncleared_transactions
            budget_data["overspent_categories"] = overspent_categories
            budget_data["needs_attention_count"] = needs_attention_count

            self._save_persistent_data(budget_data)
            return budget_data

        except Exception as exc:  # pylint: disable=broad-except
            error_time = datetime.now().strftime("%B %d, %Y - %I:%M %p")
            self.api_status["consecutive_failures"] += 1
            self.api_status["last_error_time"] = error_time

            rate_limit_info = self.api.get_rate_limit_info()
            error_str = str(exc)

            if "429" in error_str or "rate limit" in error_str.lower():
                self.api_status["status"] = "Rate Limited"
                self.api_status["last_error"] = "429 - Too Many Requests"
                _LOGGER.warning(
                    "YNAB API rate limited. Consecutive failures: %s",
                    self.api_status["consecutive_failures"],
                )
            elif "401" in error_str or "unauthorized" in error_str.lower():
                self.api_status["status"] = "Unauthorized"
                self.api_status["last_error"] = "401 - Invalid API Token"
            elif "503" in error_str or "service unavailable" in error_str.lower():
                self.api_status["status"] = "Service Unavailable"
                self.api_status["last_error"] = "503 - YNAB Service Down"
            else:
                self.api_status["status"] = "API Error"
                self.api_status["last_error"] = f"Error: {error_str[:100]}"

            self.api_status.update(rate_limit_info)
            self.api_status["is_at_limit"] = (
                self.api_status["status"] == "Rate Limited"
            )

            _LOGGER.error("Error fetching YNAB data: %s", exc)

            if not getattr(self, "data", None):
                await self._load_persistent_data()

            if getattr(self, "data", None):
                updated_data = self.data.copy()
                updated_data["api_status"] = self.api_status.copy()
                if "last_successful_poll" in updated_data:
                    updated_data["api_status"][
                        "last_successful_request"
                    ] = updated_data["last_successful_poll"]
                _LOGGER.info(
                    "Rate limited/API error – preserving existing sensor data"
                )
                return updated_data

            _LOGGER.warning(
                "No previous data available during API error – sensors may be empty"
            )
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
                "last_successful_poll": "Never",
            }

    async def manual_refresh(self, call) -> None:
        """Manually refresh YNAB data when the service is called."""
        _LOGGER.info("Manual refresh triggered for YNAB")
        await self.async_refresh()
