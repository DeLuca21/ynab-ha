"""Tests that polling feeds the category ledger."""

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ynab_custom.const import CONF_SELECTED_CATEGORIES, DOMAIN
from custom_components.ynab_custom.coordinator import YNABDataUpdateCoordinator

CAT = "22222222-2222-2222-2222-222222222222"
RTA = "44444444-4444-4444-4444-444444444444"


def _categories(balance, activity):
    return {"category_groups": [{"categories": [
        {"id": CAT, "name": "Savings Hazel", "budgeted": 10_000, "activity": activity, "balance": balance},
        {"id": RTA, "name": "Inflow: Ready to Assign", "budgeted": 0, "activity": 0, "balance": 99_000},
    ]}]}


async def test_poll_records_spending_with_payee(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={
        "access_token": "token-12345678", "budget_id": "b", "budget_name": "Law",
        CONF_SELECTED_CATEGORIES: [CAT, RTA],
    })
    entry.add_to_hass(hass)
    coordinator = YNABDataUpdateCoordinator(hass, entry, "b", "Law")

    api = coordinator.api
    api.get_budget = AsyncMock(return_value={})
    api.get_accounts = AsyncMock(return_value={"accounts": []})
    api.get_monthly_summary = AsyncMock(return_value={})
    api.get_categories = AsyncMock(return_value=_categories(10_000, 0))
    api.get_transactions = AsyncMock(return_value={"transactions": [], "server_knowledge": 1})
    await coordinator._async_update_data()

    api.get_categories = AsyncMock(return_value=_categories(7_500, -2_500))
    api.get_transactions = AsyncMock(return_value={"server_knowledge": 2, "transactions": [
        {"id": "t1", "date": "2099-01-01", "category_id": CAT, "payee_name": "Bookshop", "amount": -2_500},
    ]})
    await coordinator._async_update_data()

    [entry] = coordinator.ledger.entries(CAT)
    assert entry["kind"] == "spending" and entry["detail"] == "Bookshop -$2.50"
    assert coordinator.ledger.entries(RTA) == []
