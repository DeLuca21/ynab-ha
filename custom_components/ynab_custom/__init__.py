"""The YNAB Custom integration."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
import re

from .const import DOMAIN
from .coordinator import YNABDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

def sanitize_budget_name(budget_name: str) -> str:
    """Sanitize the budget name to create a valid Home Assistant entity ID."""
    # Replace spaces with underscores and remove any special characters
    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '', budget_name.replace(" ", "_"))
    return sanitized_name

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up YNAB Custom from a config entry."""
    budget_id = entry.data.get("budget_id")
    budget_name = entry.data.get("budget_name")

    if not budget_id or not budget_name:
        _LOGGER.error("Missing budget_id or budget_name in config entry.")
        return False

    # Sanitize the budget name to avoid issues with special characters or spaces
    sanitized_budget_name = sanitize_budget_name(budget_name)

    coordinator = YNABDataUpdateCoordinator(hass, entry, budget_id, sanitized_budget_name)
    await coordinator.async_config_entry_first_refresh()

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    _LOGGER.info(f"YNAB Custom integration for {sanitized_budget_name} successfully loaded.")  # Log the sanitized name

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)

    if coordinator:
        await coordinator.async_shutdown()

    return await hass.config_entries.async_unload_platforms(entry, ["sensor"])
