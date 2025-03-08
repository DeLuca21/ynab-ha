import logging
import re
from datetime import datetime
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_CURRENCY
from .coordinator import YNABDataUpdateCoordinator
from .const import DOMAIN
from .icons import CATEGORY_ICONS, ACCOUNT_ICONS

_LOGGER = logging.getLogger(__name__)

def sanitize_budget_name(budget_name: str) -> str:
    """Sanitize the budget name to create a valid Home Assistant entity ID."""
    # Sanitize for the entity ID (replace spaces with underscores and remove special characters)
    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '', budget_name.replace(" ", "_"))
    return sanitized_name

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
    }
    return currency_map.get(currency_code, "$")

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up YNAB sensors."""
    coordinator: YNABDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    selected_currency = entry.data.get(CONF_CURRENCY, "USD")  # Get user-selected currency
    currency_symbol = get_currency_symbol(selected_currency)  # Convert to symbol

    entities = []
    raw_budget_name = entry.data["budget_name"]
    sanitized_budget_name = sanitize_budget_name(raw_budget_name)  # Sanitize the budget name for unique ID

    # Use the raw budget name for instance name (display)
    instance_name = raw_budget_name

    # Get the current month in YYYY-MM-01 format
    current_month = datetime.now().strftime("%Y-%m-01")

    # Fetch monthly summary for the current month
    try:
        monthly_summary = await coordinator.api.get_monthly_summary(coordinator.budget_id, current_month)
        _LOGGER.debug(f"Monthly Summary Response: {monthly_summary}")
    except Exception as e:
        _LOGGER.error(f"Error fetching monthly summary for {current_month}: {e}")
        return

    # Log the response for debugging
    if "month" not in monthly_summary:
        _LOGGER.error(f"No 'month' data found in response for {current_month}. Full response: {monthly_summary}")
        return

    # If the monthly_summary is empty or not fetched properly, log and return
    if not monthly_summary or "month" not in monthly_summary:
        _LOGGER.error(f"Monthly summary data is empty or not correctly structured for {current_month}. Full response: {monthly_summary}")
        return

    # Create a separate Monthly Summary sensor as its own device/service
    entities.append(YNABMonthSummarySensor(coordinator, monthly_summary, currency_symbol, instance_name))

    # Create account sensors
    for account in coordinator.data.get("accounts", []):
        if account["id"] in coordinator.selected_accounts:
            entities.append(YNABAccountSensor(coordinator, account, entry, currency_symbol, instance_name))

    # Create category sensors
    for category in coordinator.data.get("categories", []):
        if category["id"] in coordinator.selected_categories:
            entities.append(YNABCategorySensor(coordinator, category, entry, currency_symbol, instance_name))

    # Add the entity list for the sensors
    async_add_entities(entities)


class YNABMonthSummarySensor(SensorEntity):
    """Representation of the YNAB monthly summary sensor."""

    def __init__(self, coordinator: YNABDataUpdateCoordinator, monthly_summary, currency_symbol, instance_name):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.monthly_summary = monthly_summary
        self.currency_symbol = currency_symbol  # Now passing currency_symbol from the config flow
        self.instance_name = instance_name
        self._state = None
        # Updated name format
        self._name = f"Latest Monthly Summary {self.instance_name}"
        self._unique_id = f"ynab_{self.coordinator.entry.entry_id}_monthly_summary"
        self._attr_extra_state_attributes = {}

        # Set default icon for the sensor
        self._attr_icon = "mdi:calendar-month"

        # Define the unique ID for the device (monthly summary will be a separate device)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_extras")},  # Generic device name
            "name": f"YNAB {self.instance_name} - Extras",  # Name the device/service as "YNAB <instance_name> - Extras"
            "manufacturer": "YNAB",
            "model": "YNAB Extras",
            "entry_type": "service",
        }

        _LOGGER.debug(f"Initialized YNABMonthSummarySensor with ID: {self._unique_id}")

    async def async_added_to_hass(self):
        """Call when entity is added to hass."""
        await super().async_added_to_hass()
        # Fetch and update attributes when the sensor is added to HA
        self.update_attributes()

    def update_attributes(self):
        """Update attributes from coordinator data."""
        if self.monthly_summary and 'month' in self.monthly_summary:
            month_data = self.monthly_summary.get('month', {})
            if month_data:
                # Set the state as the activity (default to activity if not found)
                self._state = month_data.get('activity', 0) / 1000  # Default to 0 if activity is missing
                self._attr_extra_state_attributes = {
                    "budgeted": month_data.get('budgeted', 0) / 1000,
                    "activity": month_data.get('activity', 0) / 1000,
                    "to_be_budgeted": month_data.get('to_be_budgeted', 0) / 1000,
                    "age_of_money": month_data.get('age_of_money', 0),
                }
            else:
                _LOGGER.error(f"Failed to retrieve valid month data for {self.instance_name}")
                self._state = None
        else:
            _LOGGER.error(f"No month data found in coordinator data for {self.instance_name}")

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique id of the sensor."""
        return self._unique_id

    @property
    def native_value(self):
        """Return the state of the sensor (activity)."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return self._attr_extra_state_attributes

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return self.currency_symbol  # Use currency symbol here

    @property
    def icon(self):
        """Return the icon for the sensor."""
        return self._attr_icon  # Return the default icon for the monthly summary sensor


class YNABAccountSensor(CoordinatorEntity, SensorEntity):
    """YNAB Account Sensor."""

    def __init__(self, coordinator, account, entry, currency_symbol, instance_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        budget_id = entry.data["budget_id"]
        self._attr_unique_id = f"ynab_{instance_name}_{account['id']}"  # Use instance_name for unique_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_accounts")},
            "name": f"YNAB {instance_name} - Accounts",  # Friendly name for device
            "manufacturer": "YNAB",
            "model": "YNAB Account",
            "entry_type": "service",
        }
        self._attr_name = f"{account['name']} YNAB {instance_name}"  # Friendly name for sensor
        self._attr_native_unit_of_measurement = currency_symbol

        balance = account.get("balance", 0) or 0
        cleared_balance = account.get("cleared_balance", 0) or 0
        uncleared_balance = account.get("uncleared_balance", 0) or 0

        self._attr_extra_state_attributes = {
            "balance": balance / 1000,
            "cleared_balance": cleared_balance / 1000,
            "uncleared_balance": uncleared_balance / 1000,
            "on_budget": account.get("on_budget", False),
            "type": account.get("type", "Unknown"),
        }
        self._attr_native_value = cleared_balance / 1000  # Use Cleared Balance as State

        # Set the appropriate icon based on the account type
        account_type = account.get("type", "").lower()
        self._attr_icon = self.get_account_icon(account_type)  # Get the icon based on type

    def get_account_icon(self, account_type: str):
        """Return the appropriate icon based on the account type."""
        # Loop through the keys in ACCOUNT_ICONS and check if any part of the account_type matches
        for key, icon in ACCOUNT_ICONS.items():
            if key in account_type:  # Check if the account type contains any key in ACCOUNT_ICONS
                return icon
        return ACCOUNT_ICONS["default"]  # Default icon if no match is found

class YNABCategorySensor(CoordinatorEntity, SensorEntity):
    """YNAB Category Sensor."""

    def __init__(self, coordinator, category, entry, currency_symbol, instance_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        budget_id = entry.data["budget_id"]
        self._attr_unique_id = f"ynab_{instance_name}_{category['id']}"  # Use instance_name for unique_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_categories")},
            "name": f"YNAB {instance_name} - Categories",  # Friendly name for device
            "manufacturer": "YNAB",
            "model": "YNAB Category",
            "entry_type": "service",
        }
        self._attr_name = f"{category['name']} YNAB {instance_name}"  # Friendly name for sensor
        self._attr_native_unit_of_measurement = currency_symbol

        category_group = category.get("category_group_name") or category.get("group_name") or "Unknown"

        budgeted = category.get("budgeted", 0) or 0
        activity = category.get("activity", 0) or 0
        balance = category.get("balance", 0) or 0
        goal_target = category.get("goal_target", 0) or 0
        goal_percentage_complete = category.get("goal_percentage_complete", 0) or 0

        self._attr_extra_state_attributes = {
            "budgeted": budgeted / 1000,
            "activity": activity / 1000,
            "balance": balance / 1000,
            "category_group": category_group,
            "goal_type": category.get("goal_type", None),
            "goal_target": goal_target / 1000,
            "goal_percentage_complete": goal_percentage_complete,
        }

        self._attr_native_value = balance / 1000  # Make "balance" the state value

        # Set the appropriate icon based on the category name
        category_name = category.get("name", "").lower().replace(" ", "_")  # Normalise the category name to match keys
        self._attr_icon = self.get_category_icon(category_name)

    def get_category_icon(self, category_name: str):
        """Return the appropriate icon based on the category name."""
        # Look for a matching word in the category name that matches the keys in CATEGORY_ICONS
        for key in CATEGORY_ICONS:
            if category_name.startswith(key):  # Check if the category name starts with any key in CATEGORY_ICONS
                return CATEGORY_ICONS[key]
        return "mdi:currency-usd"  # Default icon if no match is found