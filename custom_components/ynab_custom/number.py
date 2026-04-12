"""Number entities for YNAB credit account settings."""

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class YNABCreditLimitNumber(CoordinatorEntity, NumberEntity):
    """Editable credit limit for credit/line of credit accounts."""

    _attr_icon = "mdi:account-credit-card"
    _attr_mode = "box"
    _attr_native_min_value = 0
    _attr_native_max_value = 20000
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, account, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.account = account

        account_id = account["id"]
        budget_id = entry.data["budget_id"]

        self._attr_name = f"{account['name']} Credit Limit"
        self._attr_unique_id = f"{budget_id}_{account_id}_credit_limit"
        self._attr_native_unit_of_measurement = coordinator.currency_symbol
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_{account_id}")},
            "name": account["name"],
            "manufacturer": "YNAB",
            "model": "Credit Card",
        }

    @property
    def native_value(self):
        return self.coordinator.get_credit_limit(self.account["id"])

    async def async_set_native_value(self, value: float) -> None:
        self.account["credit_limit"] = value
        await self.coordinator.async_set_credit_limit(self.account["id"], value)
        self.async_write_ha_state()


class YNABDueDayNumber(CoordinatorEntity, NumberEntity):
    """Monthly credit card payment due day (1-28)."""

    _attr_icon = "mdi:calendar-month"
    _attr_mode = "box"
    _attr_native_min_value = 1
    _attr_native_max_value = 28
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, account, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.account = account

        account_id = account["id"]
        budget_id = entry.data["budget_id"]

        self._attr_name = f"{account['name']} Due Day"
        self._attr_unique_id = f"{budget_id}_{account_id}_due_day"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_{account_id}")},
            "name": account["name"],
            "manufacturer": "YNAB",
            "model": "Credit Card",
        }

    @property
    def native_value(self):
        return self.coordinator.get_due_day(self.account["id"])

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_due_day(self.account["id"], int(value))
        self.async_write_ha_state()


class YNABAPRNumber(CoordinatorEntity, NumberEntity):
    """Editable APR for credit accounts."""

    _attr_icon = "mdi:percent"
    _attr_mode = "box"
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.01
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, account, entry):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.account = account

        account_id = account["id"]
        budget_id = entry.data["budget_id"]

        self._attr_name = f"{account['name']} APR"
        self._attr_unique_id = f"{budget_id}_{account_id}_apr"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{budget_id}_{account_id}")},
            "name": account["name"],
            "manufacturer": "YNAB",
            "model": "Credit Card",
        }

    @property
    def native_value(self):
        return self.coordinator.get_apr(self.account["id"])

    async def async_set_native_value(self, value: float) -> None:
        self.account["apr"] = value
        await self.coordinator.async_set_apr(self.account["id"], value)
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up YNAB number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for account in coordinator.data.get("accounts", []):
        account_type = account.get("type")
        if account_type in ("creditCard", "lineOfCredit"):
            entities.append(YNABCreditLimitNumber(coordinator, account, entry))
            entities.append(YNABDueDayNumber(coordinator, account, entry))

        if account_type in ("creditCard", "personalLoan"):
            entities.append(YNABAPRNumber(coordinator, account, entry))

    async_add_entities(entities)
