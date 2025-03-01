from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import aiohttp
import asyncio
import logging
from datetime import timedelta

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api.youneedabudget.com/v1"
UPDATE_INTERVAL = timedelta(minutes=10)

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "JPY": "¥"
}


class YNABCoordinator(DataUpdateCoordinator):
    """Class to manage fetching YNAB data efficiently."""

    def __init__(self, hass, api_key, budget_id, update_interval):
        """Initialize the coordinator."""
        self.api_key = api_key
        self.budget_id = budget_id
        self.session = async_get_clientsession(hass)
        self.last_data = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"YNAB-{budget_id}",
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self):
        """Fetch data from YNAB API efficiently."""
        new_data = await self._async_get_ynab_data()
        if new_data == self.last_data:
            _LOGGER.info("No changes detected in YNAB data, skipping update")
            return self.last_data
        self.last_data = new_data
        return new_data

    async def _async_get_ynab_data(self):
        """Fetch accounts & categories from YNAB API with rate limit handling."""
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async def fetch_url(url):
            try:
                async with self.session.get(url, headers=headers, timeout=15) as response:
                    if response.status == 429:
                        _LOGGER.warning("YNAB API rate limit reached, retrying in 30 sec")
                        await asyncio.sleep(30)
                        return await fetch_url(url)
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                _LOGGER.error("YNAB API error: %s", e)
                return None

        accounts_url = f"{API_URL}/budgets/{self.budget_id}/accounts"
        categories_url = f"{API_URL}/budgets/{self.budget_id}/categories"

        accounts = await fetch_url(accounts_url)
        categories = await fetch_url(categories_url)

        return {
            "accounts": accounts["data"]["accounts"] if accounts else [],
            "categories": categories["data"]["category_groups"] if categories else [],
        }


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up YNAB sensors."""
    api_key = entry.data["api_key"]
    budget_id = entry.data["budget_id"]
    instance_name = entry.data.get("instance_name", "api")

    currency = entry.options.get("currency", "USD")
    update_interval = entry.options.get("update_interval", 300)
    include_category_summaries = entry.options.get("category_group_summaries", True)
    include_budget_summary_sensors = entry.options.get("budget_wide_summary", True)

    coordinator = YNABCoordinator(hass, api_key, budget_id, update_interval)
    await coordinator.async_config_entry_first_refresh()

    if coordinator.data is None:
        _LOGGER.error("No data retrieved from YNAB API, sensors not added")
        return

    sensors = []

    # 1) Budget Sensor (API Status)
    sensors.append(
        YNABBudgetSensor(
            coordinator,
            budget_id,
            instance_name,
            currency
        )
    )

    # 2) Account Sensors
    for account in coordinator.data["accounts"]:
        sensors.append(
            YNABAccountSensor(
                coordinator,
                budget_id,
                instance_name,
                account["id"],
                account["name"],
                currency
            )
        )

    # 3) Category Group + Category Sensors
    for group in coordinator.data["categories"]:
        if include_category_summaries:
            sensors.append(
                YNABCategoryGroupSensor(
                    coordinator,
                    budget_id,
                    instance_name,
                    group["id"],
                    group["name"],
                    currency,
                    "budgeted",
                    f"YNAB {group['name']} Assigned"
                )
            )
            sensors.append(
                YNABCategoryGroupSensor(
                    coordinator,
                    budget_id,
                    instance_name,
                    group["id"],
                    group["name"],
                    currency,
                    "activity",
                    f"YNAB {group['name']} Activity"
                )
            )
            sensors.append(
                YNABCategoryGroupSensor(
                    coordinator,
                    budget_id,
                    instance_name,
                    group["id"],
                    group["name"],
                    currency,
                    "balance",
                    f"YNAB {group['name']} Balance"
                )
            )

        for category in group["categories"]:
            sensors.append(
                YNABCategorySensor(
                    coordinator,
                    budget_id,
                    instance_name,
                    category["id"],
                    category["name"],
                    currency,
                    "activity",
                    "YNAB Budget - Categories - Activity"
                )
            )
            sensors.append(
                YNABCategorySensor(
                    coordinator,
                    budget_id,
                    instance_name,
                    category["id"],
                    category["name"],
                    currency,
                    "budgeted",
                    "YNAB Budget - Categories - Assigned"
                )
            )
            sensors.append(
                YNABCategorySensor(
                    coordinator,
                    budget_id,
                    instance_name,
                    category["id"],
                    category["name"],
                    currency,
                    "balance",
                    "YNAB Budget - Categories - Balance"
                )
            )

    # 4) Budget-Wide Summary Sensors
    if include_budget_summary_sensors:
        sensors.append(
            YNABBudgetSummarySensor(
                coordinator,
                budget_id,
                instance_name,
                currency,
                "budgeted",
                "YNAB Entire Budget - Assigned"
            )
        )
        sensors.append(
            YNABBudgetSummarySensor(
                coordinator,
                budget_id,
                instance_name,
                currency,
                "activity",
                "YNAB Entire Budget - Activity"
            )
        )
        sensors.append(
            YNABBudgetSummarySensor(
                coordinator,
                budget_id,
                instance_name,
                currency,
                "balance",
                "YNAB Entire Budget - Balance"
            )
        )

    async_add_entities(sensors, True)
    async_register_admin_service(hass, "ynab_custom", "refresh", coordinator.async_refresh)


#
# Sensor Classes
#
class YNABBudgetSensor(CoordinatorEntity, SensorEntity):
    """YNAB API Status sensor for Home Assistant."""

    def __init__(self, coordinator, budget_id, instance_name, currency):
        super().__init__(coordinator)
        self.budget_id = budget_id
        self.instance_name = instance_name
        self.currency = currency

        self._attr_unique_id = f"ynab_{instance_name}_{budget_id}_api_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_api_status")},
            "name": "YNAB Budget - API Status",
            "manufacturer": "YNAB",
            "model": "YNAB API Status"
        }
        self._attr_icon = "mdi:api"

    @property
    def name(self):
        return f"YNAB API {self.instance_name} Status"

    @property
    def state(self):
        return self.coordinator.last_update_success


class YNABAccountSensor(CoordinatorEntity, SensorEntity):
    """YNAB Account Balance sensor for Home Assistant."""

    def __init__(self, coordinator, budget_id, instance_name, account_id, account_name, currency):
        super().__init__(coordinator)
        self.budget_id = budget_id
        self.instance_name = instance_name
        self.account_id = account_id
        self.account_name = account_name
        self.currency = currency

        self._attr_unique_id = f"ynab_{instance_name}_{budget_id}_{account_id}_account"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_accounts")},
            "name": "YNAB Budget - Accounts",
            "manufacturer": "YNAB",
            "model": "YNAB Budget"
        }
        self._attr_icon = "mdi:bank"

    @property
    def name(self):
        return f"YNAB {self.instance_name} {self.account_name} Balance"

    @property
    def state(self):
        """Retrieve the latest account balance."""
        if self.coordinator.data["accounts"]:
            for account in self.coordinator.data["accounts"]:
                if account["id"] == self.account_id:
                    return f"{CURRENCY_SYMBOLS.get(self.currency, '')}{account['balance'] / 1000}"
        return None


class YNABCategorySensor(CoordinatorEntity, SensorEntity):
    """YNAB Category sensor for Home Assistant."""

    def __init__(
        self, coordinator, budget_id, instance_name, category_id, category_name,
        currency, field, device_name
    ):
        super().__init__(coordinator)
        self.budget_id = budget_id
        self.instance_name = instance_name
        self.category_id = category_id
        self.category_name = category_name
        self.currency = currency
        self.field = field

        self._attr_unique_id = f"ynab_{instance_name}_{budget_id}_{category_id}_{field}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_{field}")},
            "name": device_name,
            "manufacturer": "YNAB",
            "model": "YNAB Budget"
        }

        # Field-based icons
        if self.field == "activity":
            self._attr_icon = "mdi:swap-horizontal"
        elif self.field == "budgeted":
            self._attr_icon = "mdi:cash-multiple"
        elif self.field == "balance":
            self._attr_icon = "mdi:currency-usd"
        else:
            self._attr_icon = "mdi:currency-usd"

    @property
    def name(self):
        return f"YNAB {self.instance_name} {self.category_name} {self.field.capitalize()}"

    @property
    def state(self):
        """Retrieve category data."""
        for group in self.coordinator.data["categories"]:
            for category in group["categories"]:
                if category["id"] == self.category_id:
                    return f"{CURRENCY_SYMBOLS.get(self.currency, '')}{category[self.field] / 1000}"
        return None


class YNABCategoryGroupSensor(CoordinatorEntity, SensorEntity):
    """YNAB Category Group sensor for a single field (assigned/activity/balance)."""

    def __init__(
        self, coordinator, budget_id, instance_name, group_id, group_name,
        currency, field, device_name
    ):
        super().__init__(coordinator)
        self.budget_id = budget_id
        self.instance_name = instance_name
        self.group_id = group_id
        self.group_name = group_name
        self.currency = currency
        self.field = field

        self._attr_unique_id = f"ynab_{instance_name}_{budget_id}_{group_id}_{field}_group"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_category_groups")},
            "name": "YNAB Budget - Category Groups",
            "manufacturer": "YNAB",
            "model": "YNAB Budget"
        }
        self._device_name = device_name

        if self.field == "budgeted":
            self._attr_icon = "mdi:cash-multiple"
        elif self.field == "activity":
            self._attr_icon = "mdi:swap-horizontal"
        elif self.field == "balance":
            self._attr_icon = "mdi:currency-usd"
        else:
            self._attr_icon = "mdi:currency-usd"

    @property
    def name(self):
        return f"{self._device_name} - {self.instance_name}"

    @property
    def state(self):
        """Compute the total assigned, activity, or balance for the group."""
        categories = self._get_group_categories()
        total = sum(cat[self.field] for cat in categories)
        return f"{CURRENCY_SYMBOLS.get(self.currency, '')}{total / 1000}"

    def _get_group_categories(self):
        for group in self.coordinator.data["categories"]:
            if group["id"] == self.group_id:
                return group["categories"]
        return []


class YNABBudgetSummarySensor(CoordinatorEntity, SensorEntity):
    """YNAB Entire Budget sensor for a single field (budgeted/activity/balance)."""

    def __init__(
        self, coordinator, budget_id, instance_name, currency, field, device_name
    ):
        super().__init__(coordinator)
        self.budget_id = budget_id
        self.instance_name = instance_name
        self.currency = currency
        self.field = field

        self._attr_unique_id = f"ynab_{instance_name}_{budget_id}_{field}_budget_summary"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_budget_summary_device")},
            "name": "YNAB Budget - Summary Sensors",
            "manufacturer": "YNAB",
            "model": "YNAB Budget Summary"
        }
        self._device_name = device_name

        if self.field == "budgeted":
            self._attr_icon = "mdi:cash-multiple"
        elif self.field == "activity":
            self._attr_icon = "mdi:swap-horizontal"
        elif self.field == "balance":
            self._attr_icon = "mdi:currency-usd"
        else:
            self._attr_icon = "mdi:currency-usd"

    @property
    def name(self):
        return f"{self._device_name} - {self.instance_name}"

    @property
    def state(self):
        """Sum up the specified field across all categories in this budget."""
        total = 0
        for group in self.coordinator.data["categories"]:
            for category in group["categories"]:
                total += category[self.field]
        return f"{CURRENCY_SYMBOLS.get(self.currency, '')}{total / 1000}"
