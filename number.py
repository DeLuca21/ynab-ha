import logging
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import EntityCategory
from .coordinator import YNABDataUpdateCoordinator
from .const import DOMAIN
_LOGGER = logging.getLogger(__name__)

class YNABCreditLimitNumber(CoordinatorEntity, NumberEntity):
    """Editable credit limit for credit card accounts."""

    _attr_icon = "mdi:account-credit-card"
    _attr_mode = "box"

    # Sensible defaults
    _attr_native_min_value = 0
    _attr_native_max_value = 20000
    _attr_native_step = 1


    def __init__(self, coordinator, account, entry):
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.account = account
        self.entry = entry

        account_id = account["id"]
        budget_id = entry.data["budget_id"]

        self._attr_name = f"{account['name']} Credit Limit"
        self._attr_unique_id = f"{budget_id}_{account_id}_credit_limit"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_native_unit_of_measurement = self.coordinator.hass.config.currency


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
        account_id = self.account["id"]

        # 1️⃣ Update in-memory account object (used by sensors)
        self.account["credit_limit"] = value

        # 2️⃣ Persist via coordinator Store
        await self.coordinator.async_set_credit_limit(account_id, value)

        # 3️⃣ Tell HA the entity state changed
        self.async_write_ha_state()

class YNABDueDayNumber(CoordinatorEntity, NumberEntity):
    """Monthly credit card payment due day (1–31)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    _attr_native_min_value = 1
    _attr_native_max_value = 28
    _attr_native_step = 1
    _attr_mode = "box"

    _attr_icon = "mdi:calendar-month"

    def __init__(self, coordinator, account: dict, entry):
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.account = account
        self.entry = entry

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
    def native_value(self) -> int | None:
        return self.coordinator.get_due_day(self.account["id"])

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_due_day(self.account["id"],int(value))
        self.async_write_ha_state()

class YNABAPRNumber(CoordinatorEntity, NumberEntity):
    """APR number entity for credit card accounts."""

    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:percent"
    _attr_mode = "box"

    # Sensible defaults
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.01

    def __init__(self, coordinator, account, entry):
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.account = account
        self.entry = entry

        account_id = account["id"]
        budget_id = entry.data["budget_id"]

        self._attr_name = f"{account['name']} APR"
        self._attr_unique_id = f"{budget_id}_{account_id}_apr"
        self._attr_entity_category = EntityCategory.CONFIG

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
        account_id = self.account["id"]

        self.account["apr"] = value
        await self.coordinator.async_set_apr(account_id, value)
        self.async_write_ha_state()

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    accounts = coordinator.data.get("accounts", [])
    for account in accounts:
        account_type = account.get("type")

        # Credit Limit → credit cards and line of credit
        if account_type in ("creditCard", "lineOfCredit"):
            entities.append(YNABCreditLimitNumber(coordinator, account, entry))
            

        # APR → credit cards AND personal loans
        if account_type in ("creditCard", "personalLoan"):
            entities.append(YNABAPRNumber(coordinator, account, entry))
            entities.append(YNABDueDayNumber(coordinator, account, entry))

    async_add_entities(entities)
