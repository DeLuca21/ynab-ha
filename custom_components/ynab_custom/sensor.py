import logging
import re
from datetime import datetime
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import CONF_CURRENCY
from homeassistant.core import callback
from .coordinator import YNABDataUpdateCoordinator
from .const import DOMAIN
from .icons import CATEGORY_ICONS, ACCOUNT_ICONS
from homeassistant.helpers.entity import EntityCategory

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
        "NIS": "₪",
    }
    return currency_map.get(currency_code, "$")

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up YNAB sensors."""
    coordinator: YNABDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("🔹 Setting up YNAB sensors...")

    # Fetch the currency symbol directly from coordinator
    currency_symbol = coordinator.currency_symbol

    entities = []
    raw_budget_name = entry.data["budget_name"]
    sanitized_budget_name = sanitize_budget_name(raw_budget_name)

    # Create monthly summary sensor - it will use data from coordinator.data
    # No need to fetch data here, the coordinator handles all API calls
    entities.append(YNABExtrasSensor(coordinator, currency_symbol, raw_budget_name))

    # Ensure diagnostics sensors are always added
    entities.append(YNABAPIStatusSensor(coordinator, raw_budget_name))

    _LOGGER.debug(f"🔹 Coordinator Accounts Data: {coordinator.data.get('accounts', [])}")

    # Create account sensors
    for account in coordinator.data.get("accounts", []):
        if account["id"] in coordinator.selected_accounts:
            _LOGGER.debug(f"🔹 Adding Account Sensor: {account}")
            entities.append(YNABAccountSensor(coordinator, account, entry, currency_symbol, raw_budget_name))

    # Create category sensors
    for category in coordinator.data.get("categories", []):
        if category["id"] in coordinator.selected_categories:
            _LOGGER.debug(f"🔹 Adding Category Sensor: {category}")
            entities.append(YNABCategorySensor(coordinator, category, entry, currency_symbol, raw_budget_name))

    # Add the entity list for the sensors
    async_add_entities(entities)

class YNABExtrasSensor(CoordinatorEntity, SensorEntity):
    """Representation of the YNAB Extras sensor (combining Monthly Budget & Diagnostics as separate sensors)."""

    def __init__(self, coordinator: YNABDataUpdateCoordinator, currency_symbol, instance_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.currency_symbol = currency_symbol
        self.instance_name = instance_name
        self._state = None
        # Updated name format
        self._name = f"Latest Month Summary YNAB {self.instance_name}"
        self._unique_id = f"latest_month_summary_ynab_{self.coordinator.entry.entry_id}"
        self._attr_extra_state_attributes = {}

        # Set default icon for the sensor
        self._attr_icon = "mdi:calendar-month"

        # Define as an Extras device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_extras")},
            "name": f"YNAB {self.instance_name} - Extras",
            "manufacturer": "YNAB",
            "model": "YNAB Extras",
            "entry_type": "service",
        }
        self._attr_native_unit_of_measurement = self.currency_symbol
        _LOGGER.debug(f"Initialized YNABExtrasSensor with ID: {self._unique_id}")

    @property
    def device_class(self):
        """Return the device class for statistics support."""
        return SensorDeviceClass.MONETARY

    @property
    def state_class(self):
        """Return the state class for statistics support."""
        return SensorStateClass.TOTAL

    async def async_added_to_hass(self):
        """Call when entity is added to hass."""
        await super().async_added_to_hass()
        # Fetch and update attributes when the sensor is added to HA
        self.update_attributes()

    def update_attributes(self):
        """Update attributes for Sensors - works like other sensors, using coordinator.data."""
        # Get monthly summary data from coordinator (same as other sensors)
        monthly_summary = self.coordinator.data.get("monthly_summary", {})
        
        if monthly_summary and "month" in monthly_summary:
            month_data = monthly_summary.get("month", {})
            if month_data:
                # Set the state as the activity (default to activity if not found)
                self._state = month_data.get("activity", 0) / 1000  # Default to 0 if activity is missing

                # Fix attribute formatting (keep proper case)
                self._attr_extra_state_attributes = {
                    "Budgeted": month_data.get("budgeted", 0) / 1000,
                    "Activity": month_data.get("activity", 0) / 1000,
                    "To Be Budgeted": month_data.get("to_be_budgeted", 0) / 1000,
                    "Age of Money": month_data.get("age_of_money", 0),
                }
    
                # Add new attention/transaction-related metrics
                unapproved = self.coordinator.data.get("unapproved_transactions", 0)
                uncleared = self.coordinator.data.get("uncleared_transactions", 0)
                overspent = self.coordinator.data.get("overspent_categories", 0)
                needs_attention = self.coordinator.data.get("needs_attention_count", 0)
    
                self._attr_extra_state_attributes.update({
                    "Unapproved Transactions": unapproved,
                    "Uncleared Transactions": uncleared,
                    "Overspent Categories": overspent,
                    "Needs Attention Count": needs_attention
                })
    
            else:
                _LOGGER.error(f"Failed to retrieve valid month data for {self.instance_name}")
                self._state = None
        else:
            _LOGGER.warning(f"No monthly summary data available for {self.instance_name}")
            self._state = None

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
        """Return structured attributes with proper formatting."""
        return self._attr_extra_state_attributes

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return self.currency_symbol  # Use currency symbol here

    @property
    def icon(self):
        """Return the icon for the sensor."""
        return self._attr_icon  # Return the default icon for the monthly summary sensor

class YNABAPIStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor to track YNAB API connection status and health."""

    def __init__(self, coordinator, instance_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.instance_name = instance_name
        self._attr_name = f"YNAB API Status YNAB {self.instance_name}"
        self._attr_unique_id = f"ynab_api_status_ynab_{self.coordinator.entry.entry_id}"
        self._attr_icon = "mdi:api"
        
        # Assign to the "Extras" device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_extras")},
            "name": f"YNAB {self.instance_name} - Extras",
            "manufacturer": "YNAB",
            "model": "YNAB Extras",
            "entry_type": "service",
        }

        # Assign to the Diagnostic Category
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current API status."""
        api_status = self.coordinator.data.get("api_status", {})
        base_status = api_status.get("status", "Unknown")
        
        # Only show "Rate Limited" if we're actually getting 429 errors
        # Don't override based on our estimated 200 limit since YNAB's real limit appears higher
        return base_status

    @property
    def extra_state_attributes(self):
        """Return additional API status attributes."""
        api_status = self.coordinator.data.get("api_status", {})
        return {
            "last_error": api_status.get("last_error", "None"),
            "last_error_time": api_status.get("last_error_time", "Never"),
            "consecutive_failures": api_status.get("consecutive_failures", 0),
            "requests_made_total_all_integrations": api_status.get("requests_made_total", 0),
            "requests_this_hour_all_integrations": api_status.get("requests_this_hour", 0),
            "estimated_remaining": api_status.get("estimated_remaining", 200),
            "rate_limit_resets_at": api_status.get("rate_limit_resets_at", "Unknown"),
            "is_at_limit": api_status.get("is_at_limit", False),
            "last_successful_request": api_status.get("last_successful_request", "Never"),
            "note": "Counts include all YNAB integrations using the same API token",
        }

class YNABAccountSensor(CoordinatorEntity, SensorEntity):
    """YNAB Account Sensor."""

    def __init__(self, coordinator, account, entry, currency_symbol, instance_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.account = account
        self.currency_symbol = currency_symbol
        self.instance_name = instance_name

        # Preserve your naming structure
        self._attr_unique_id = f"ynab_{instance_name}_{account['id']}"
        
        # Add (Closed) suffix for closed accounts, matching category pattern
        account_name = account["name"]
        if account.get("closed"):
            account_name += " (Closed)"
        self._attr_name = f"{account_name} YNAB {instance_name}"  # Friendly name for sensor

        budget_id = entry.data["budget_id"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_accounts")},
            "name": f"YNAB {instance_name} - Accounts",  # Friendly name for device
            "manufacturer": "YNAB",
            "model": "YNAB Account",
            "entry_type": "service",
        }

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

    @property
    def device_class(self):
        """Return the device class for statistics support."""
        return SensorDeviceClass.MONETARY

    @property
    def state_class(self):
        """Return the state class for statistics support."""
        return SensorStateClass.TOTAL

    @property
    def native_unit_of_measurement(self):
        """Return the correct currency symbol explicitly for HA to recognize it."""
        return self.currency_symbol  # Ensure HA correctly applies the currency

    @property
    def native_value(self):
        """Return the state of the sensor (cleared balance)."""
        return self.account.get("cleared_balance", 0) / 1000  # Convert from milliunits

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "balance": self.account.get("balance", 0) / 1000,
            "cleared_balance": self.account.get("cleared_balance", 0) / 1000,
            "uncleared_balance": self.account.get("uncleared_balance", 0) / 1000,
            "on_budget": self.account.get("on_budget", False),
            "type": self.account.get("type", "Unknown"),
        }

    async def async_added_to_hass(self):
        """When added to Home Assistant, subscribe to updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        _LOGGER.debug(f"🔹 Account Sensor Added: {self.name} (ID: {self._attr_unique_id})")

    @callback
    def _handle_coordinator_update(self):
        """Handle an update from the coordinator."""
        _LOGGER.debug(f"🔹 Updating Account Sensor: {self.name}")

        # Find the updated account in the coordinator data
        self.account = next(
            (a for a in self.coordinator.data.get("accounts", []) if a["id"] == self.account["id"]),
            self.account  # Keep the old data if not found
        )


        # Update the icon if the account type changed
        account_type = self.account.get("type", "").lower()
        self._attr_icon = self.get_account_icon(account_type)

        # Write the new state to Home Assistant
        self.async_write_ha_state()

class YNABCategorySensor(CoordinatorEntity, SensorEntity):
    """YNAB Category Sensor."""

    def __init__(self, coordinator, category, entry, currency_symbol, instance_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.category = category
        self.currency_symbol = currency_symbol
        self.instance_name = instance_name

        budget_id = entry.data["budget_id"]
        self._attr_unique_id = f"ynab_{instance_name}_{category['id']}"  # Use instance_name for unique_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_categories")},
            "name": f"YNAB {instance_name} - Categories",  # Friendly name for device
            "manufacturer": "YNAB",
            "model": "YNAB Category",
            "entry_type": "service",
        }
        name = category["name"]  # Friendly name for sensor
        if category.get("hidden"):
            name += " (Hidden)"
        self._attr_name = f"{name} YNAB {instance_name}"

        self._attr_native_unit_of_measurement = self.currency_symbol

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

    @property
    def device_class(self):
        """Return the device class for statistics support."""
        return SensorDeviceClass.MONETARY

    @property
    def state_class(self):
        """Return the state class for statistics support."""
        return SensorStateClass.TOTAL

    @property
    def native_unit_of_measurement(self):
        """Return the correct currency symbol explicitly for HA to recognize it."""
        return self.currency_symbol  # Ensure HA correctly applies the currency

    @property
    def native_value(self):
        """Return the state of the sensor (category balance)."""
        return (self.category.get("balance") or 0) / 1000  # Convert from milliunits

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "budgeted": (self.category.get("budgeted") or 0) / 1000,
            "activity": (self.category.get("activity") or 0) / 1000,
            "balance":  (self.category.get("balance")  or 0) / 1000,
            "category_group": self.category.get("category_group_name") or self.category.get("group_name", "Unknown"),
            "goal_type": self.category.get("goal_type", None),
            "goal_target": (self.category.get("goal_target") or 0) / 1000,
            "goal_percentage_complete": (self.category.get("goal_percentage_complete") or 0),
            "goal_overall_left": (self.category.get("goal_overall_left") or 0) / 1000,
            "percentage_spent": (
                round(
                    abs(self.category.get("activity") or 0) /
                    abs(self.category.get("budgeted") or 1) * 100,
                    2
                )
                if (self.category.get("budgeted") or 0) else 0.0
            ),
            "needs_attention": (
                (self.category.get("balance") or 0) < 0 or
                (
                    (self.category.get("goal_target") or 0) > 0 and
                    (self.category.get("goal_overall_left") or 0) > 0
                )
            ),
            "attention_reason": (
                "Overspent" if (self.category.get("balance") or 0) < 0 else
                "Underfunded" if (
                    (self.category.get("goal_target") or 0) > 0 and
                    (self.category.get("goal_overall_left") or 0) > 0
                ) else
                "Ok"
            ),
            "hidden": self.category.get("hidden", False),
        }

    async def async_added_to_hass(self):
        """When added to Home Assistant, subscribe to updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self):
        """Handle an update from the coordinator."""
        # Find the updated category in the coordinator data
        self.category = next(
            (c for c in self.coordinator.data.get("categories", []) if c["id"] == self.category["id"]),
            self.category  # Keep the old data if not found
        )


        # Update the icon in case the category name changed
        category_name = self.category.get("name", "").lower().replace(" ", "_")
        self._attr_icon = self.get_category_icon(category_name)

        # Write the new state to Home Assistant
        self.async_write_ha_state()
