"""The YNAB Custom integration."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import entity_registry as er
import re

from .const import DOMAIN, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, CONF_INCLUDE_CLOSED_ACCOUNTS, CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_HIDDEN_CATEGORIES, CONF_SELECTED_ACCOUNTS, CONF_SELECTED_CATEGORIES
from .coordinator import YNABDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

def sanitize_budget_name(budget_name: str) -> str:
    """Sanitize the budget name to create a valid Home Assistant entity ID."""
    # Replace spaces with underscores and remove any special characters
    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '', budget_name.replace(" ", "_"))
    return sanitized_name

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry from version 1 to version 2."""
    _LOGGER.info(f"Migrating YNAB config entry {entry.entry_id} from version {entry.version} to version 2")
    _LOGGER.debug(f"Entry data before migration: {entry.data}")
    _LOGGER.debug(f"Entry options before migration: {entry.options}")
    
    try:
        # Create new data and options dictionaries
        new_data = dict(entry.data)
        new_options = dict(entry.options) if entry.options else {}
        
        # Migrate update_interval from data to options if it exists in data
        if CONF_UPDATE_INTERVAL in entry.data:
            new_options.setdefault(CONF_UPDATE_INTERVAL, entry.data[CONF_UPDATE_INTERVAL])
            # Remove from data since it should be in options
            new_data.pop(CONF_UPDATE_INTERVAL, None)
        else:
            # Ensure update_interval exists in options with default
            new_options.setdefault(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        
        # Add new checkbox options with safe defaults
        new_options.setdefault(CONF_INCLUDE_CLOSED_ACCOUNTS, DEFAULT_INCLUDE_CLOSED_ACCOUNTS)
        new_options.setdefault(CONF_INCLUDE_HIDDEN_CATEGORIES, DEFAULT_INCLUDE_HIDDEN_CATEGORIES)
        
        # Update the config entry
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=new_options,
            version=2
        )
        
        _LOGGER.info(f"Successfully migrated YNAB config entry {entry.entry_id} to version 2")
        _LOGGER.debug(f"Entry data after migration: {new_data}")
        _LOGGER.debug(f"Entry options after migration: {new_options}")
        return True
        
    except Exception as e:
        _LOGGER.exception(f"Failed to migrate YNAB config entry {entry.entry_id}: {e}")
        return False

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up YNAB Custom from a config entry."""
    _LOGGER.debug(f"Setting up YNAB integration {entry.entry_id}")
    
    budget_id = entry.data.get("budget_id")
    budget_name = entry.data.get("budget_name")

    if not budget_id or not budget_name:
        _LOGGER.error("Missing budget_id or budget_name in config entry.")
        return False

    # Sanitize the budget name to avoid issues with special characters or spaces
    sanitized_budget_name = sanitize_budget_name(budget_name)
    coordinator = YNABDataUpdateCoordinator(hass, entry, budget_id, sanitized_budget_name)

    # Load persistent data before first refresh
    await coordinator.async_load_persistent_data()
    
    await coordinator.async_config_entry_first_refresh()  # Ensure the first update occurs
    hass.async_create_task(coordinator.async_refresh())  # 🔹 Manually force an update on startup

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "number"])



    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info(f"YNAB Custom integration for {sanitized_budget_name} successfully loaded.")
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    
    # Get the coordinator to check what changed
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        old_accounts = set(coordinator.selected_accounts)
        old_categories = set(coordinator.selected_categories)
        new_accounts = set(entry.data.get(CONF_SELECTED_ACCOUNTS, []))
        new_categories = set(entry.data.get(CONF_SELECTED_CATEGORIES, []))
        
        _LOGGER.debug(f"Options update - OLD accounts: {old_accounts}, NEW accounts: {new_accounts}")
        _LOGGER.debug(f"Options update - OLD categories: {old_categories}, NEW categories: {new_categories}")
        
        if old_accounts != new_accounts or old_categories != new_categories:
            _LOGGER.info(f"Account/category selections changed - doing full unload/reload cycle")
            
            # Force a complete unload/reload cycle to ensure clean state
            unload_result = await hass.config_entries.async_unload(entry.entry_id)
            setup_result = await hass.config_entries.async_setup(entry.entry_id)
            
            _LOGGER.info(f"Unload/reload cycle complete - Unload: {unload_result}, Setup: {setup_result}")
            return
        else:
            _LOGGER.debug(f"Only settings changed, doing simple reload")
    else:
        _LOGGER.warning(f"No coordinator found for {entry.entry_id}")
    
    # Simple reload for non-selection changes
    await hass.config_entries.async_reload(entry.entry_id)
    _LOGGER.debug(f"Simple reload complete")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    
    # Clean up entity registry entries for this config entry
    entity_registry = er.async_get(hass)
    entities_to_remove = []
    
    for entity_entry in entity_registry.entities.values():
        if entity_entry.config_entry_id == entry.entry_id:
            entities_to_remove.append(entity_entry.entity_id)
    
    # Remove entities from registry
    removed_entities = []
    for entity_id in entities_to_remove:
        entity_registry.async_remove(entity_id)
        removed_entities.append(entity_id)
    
    coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)

    if coordinator:
        await coordinator.async_shutdown()

    result = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    
    if removed_entities:
        _LOGGER.debug(f"Unload complete for {entry.entry_id} - removed {len(removed_entities)} entities")
    else:
        _LOGGER.debug(f"Unload complete for {entry.entry_id}")
    
    return result
