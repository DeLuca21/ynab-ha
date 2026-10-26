"""Tests for the options flow keeping its settings."""

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_ACCESS_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ynab_custom.const import (
    CONF_CURRENCY,
    CONF_INCLUDE_CLOSED_ACCOUNTS,
    CONF_INCLUDE_HIDDEN_CATEGORIES,
    CONF_MONEY_MOVERS,
    CONF_SELECTED_ACCOUNTS,
    CONF_SELECTED_CATEGORIES,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)


async def test_options_flow_saves_money_movers(hass):
    user = await hass.auth.async_create_user("Julie")
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_ACCESS_TOKEN: "token-12345678", "budget_id": "b", "budget_name": "Law"},
        options={CONF_UPDATE_INTERVAL: 10},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.ynab_custom.config_flow.YNABApi") as api_cls:
        api = api_cls.return_value
        api.get_accounts = AsyncMock(return_value={"accounts": [{"id": "a1", "name": "Checking"}]})
        api.get_categories = AsyncMock(return_value={
            "category_groups": [{"categories": [{"id": "c1", "name": "Savings"}]}]
        })

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            CONF_CURRENCY: "USD",
            CONF_UPDATE_INTERVAL: 15,
            CONF_INCLUDE_CLOSED_ACCOUNTS: False,
            CONF_INCLUDE_HIDDEN_CATEGORIES: False,
            CONF_SELECTED_ACCOUNTS: ["a1"],
            CONF_SELECTED_CATEGORIES: ["c1"],
            CONF_MONEY_MOVERS: [user.id],
        })

    assert result["type"] == "create_entry"
    assert entry.options[CONF_MONEY_MOVERS] == [user.id]
    assert entry.options[CONF_UPDATE_INTERVAL] == 15
