"""Tests for the permissioned money movement services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ynab_custom.api import YNABApiError
from custom_components.ynab_custom.const import (
    CONF_MONEY_MOVERS,
    DOMAIN,
    EVENT_MONEY_MOVED,
    SERVICE_MOVE_CATEGORY_MONEY,
    SERVICE_TRANSFER_ACCOUNT_MONEY,
)
from custom_components.ynab_custom.ledger import CategoryLedger
from custom_components.ynab_custom.services import async_register_services

BUDGET = "11111111-1111-1111-1111-111111111111"
SAVINGS = "22222222-2222-2222-2222-222222222222"
ALLOWANCE = "33333333-3333-3333-3333-333333333333"
RTA = "44444444-4444-4444-4444-444444444444"
CHECKING = "55555555-5555-5555-5555-555555555555"
CASH = "66666666-6666-6666-6666-666666666666"
TRACKING = "77777777-7777-7777-7777-777777777777"


@pytest.fixture
async def setup(hass):
    """Register the services against a fake coordinator and sensor entities."""
    allowed = await hass.auth.async_create_user("Julie")
    other = await hass.auth.async_create_user("Sam")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"budget_id": BUDGET, "budget_name": "Law"},
        options={CONF_MONEY_MOVERS: [allowed.id]},
    )
    entry.add_to_hass(hass)

    api = MagicMock()
    api.get_month_category = AsyncMock()
    api.set_month_category_budgeted = AsyncMock()
    api.get_month = AsyncMock()
    api.get_account = AsyncMock()
    api.create_transaction = AsyncMock(return_value={"id": "txn"})

    coordinator = SimpleNamespace(
        entry=entry,
        api=api,
        budget_id=BUDGET,
        budget_name="Law",
        currency_symbol="$",
        ledger=CategoryLedger(hass, entry.entry_id, "$"),
        get_current_month=lambda: "2026-10-01",
        async_request_refresh=AsyncMock(),
        data={
            "categories": [
                {"id": SAVINGS, "name": "Savings"},
                {"id": ALLOWANCE, "name": "Allowance"},
                {"id": RTA, "name": "Inflow: Ready to Assign"},
            ],
            "accounts": [
                {"id": CHECKING, "name": "Checking", "type": "checking", "on_budget": True, "transfer_payee_id": "payee-checking"},
                {"id": CASH, "name": "Cash", "type": "cash", "on_budget": True, "transfer_payee_id": "payee-cash"},
                {"id": TRACKING, "name": "Brokerage", "type": "otherAsset", "on_budget": False, "transfer_payee_id": "payee-brokerage"},
            ],
        },
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    registry = er.async_get(hass)
    entities = {}
    for name, ynab_id in {
        "savings": SAVINGS, "allowance": ALLOWANCE, "rta": RTA,
        "checking": CHECKING, "cash": CASH, "tracking": TRACKING,
    }.items():
        entities[name] = registry.async_get_or_create(
            "sensor", DOMAIN, f"ynab_Law_{ynab_id}", config_entry=entry, suggested_object_id=name
        ).entity_id

    async_register_services(hass)
    return SimpleNamespace(api=api, coordinator=coordinator, allowed=allowed, other=other, e=entities)


def _call(hass, service, data, user):
    return hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def test_allowed_user_moves_between_categories(hass, setup):
    api = setup.api
    api.get_month_category.side_effect = [
        {"budgeted": 10_000, "balance": 20_000},  # from: Allowance
        {"budgeted": 5_000, "balance": 7_000},  # to: Savings
    ]
    api.set_month_category_budgeted.side_effect = [
        {"balance": 15_000}, {"balance": 12_000},
    ]
    events = []
    hass.bus.async_listen(EVENT_MONEY_MOVED, events.append)

    result = await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
        "from_category": setup.e["allowance"], "to_category": setup.e["savings"], "amount": 5,
    }, setup.allowed)

    api.set_month_category_budgeted.assert_any_await(BUDGET, ALLOWANCE, 5_000)
    api.set_month_category_budgeted.assert_any_await(BUDGET, SAVINGS, 10_000)
    assert result["to_balance"] == 12.0 and result["user"] == "Julie"
    await hass.async_block_till_done()
    assert events[0].data["to"] == "Savings"
    setup.coordinator.async_request_refresh.assert_awaited()

    ledger = setup.coordinator.ledger
    [moved_in] = ledger.entries(SAVINGS)
    assert moved_in["kind"] == "move" and moved_in["by"] == "Julie"
    assert moved_in["amount"] == 5.0 and moved_in["balance"] == 12.0
    assert moved_in["detail"] == "From Allowance"
    assert ledger.entries(ALLOWANCE)[0]["amount"] == -5.0

    history = await hass.services.async_call(
        DOMAIN, "get_category_history", {"category": setup.e["savings"]},
        blocking=True, return_response=True,
    )
    assert history["category"] == "Savings"
    assert history["changes"] == [moved_in]


async def test_user_not_on_list_is_refused(hass, setup):
    with pytest.raises(Unauthorized):
        await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
            "to_category": setup.e["savings"], "amount": 5,
        }, setup.other)
    setup.api.set_month_category_budgeted.assert_not_awaited()


async def test_call_without_user_is_refused(hass, setup):
    with pytest.raises(Unauthorized):
        await _call(hass, SERVICE_TRANSFER_ACCOUNT_MONEY, {
            "from_account": setup.e["checking"], "to_account": setup.e["cash"], "amount": 5,
        }, None)
    setup.api.create_transaction.assert_not_awaited()


async def test_empty_allowlist_blocks_everyone(hass, setup):
    hass.config_entries.async_update_entry(setup.coordinator.entry, options={})
    with pytest.raises(Unauthorized):
        await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
            "to_category": setup.e["savings"], "amount": 5,
        }, setup.allowed)


async def test_ready_to_assign_is_the_default_side(hass, setup):
    api = setup.api
    api.get_month_category.return_value = {"budgeted": 8_000, "balance": 8_000}
    api.set_month_category_budgeted.return_value = {"balance": 3_000}

    result = await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
        "from_category": setup.e["savings"], "to_category": setup.e["rta"], "amount": 5,
    }, setup.allowed)

    api.set_month_category_budgeted.assert_awaited_once_with(BUDGET, SAVINGS, 3_000)
    assert result["to"] == "Ready to Assign"


async def test_overdraw_is_refused_unless_allowed(hass, setup):
    api = setup.api
    api.get_month.return_value = {"to_be_budgeted": 1_000}
    with pytest.raises(ServiceValidationError, match=r"\$1.00"):
        await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
            "to_category": setup.e["savings"], "amount": 5,
        }, setup.allowed)

    api.get_month_category.return_value = {"budgeted": 0, "balance": 0}
    api.set_month_category_budgeted.return_value = {"balance": 5_000}
    await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
        "to_category": setup.e["savings"], "amount": 5, "allow_overdraw": True,
    }, setup.allowed)
    api.set_month_category_budgeted.assert_awaited_once_with(BUDGET, SAVINGS, 5_000)


async def test_failed_second_write_restores_source(hass, setup):
    api = setup.api
    api.get_month_category.side_effect = [
        {"budgeted": 10_000, "balance": 20_000}, {"budgeted": 0, "balance": 0},
    ]
    api.set_month_category_budgeted.side_effect = [{}, YNABApiError("500"), {}]

    with pytest.raises(HomeAssistantError, match="rejected"):
        await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
            "from_category": setup.e["allowance"], "to_category": setup.e["savings"], "amount": 5,
        }, setup.allowed)
    assert api.set_month_category_budgeted.await_args_list[-1].args == (BUDGET, ALLOWANCE, 10_000)


async def test_allowed_user_transfers_between_accounts(hass, setup):
    api = setup.api
    api.get_account.return_value = {"balance": 100_000}
    result = await _call(hass, SERVICE_TRANSFER_ACCOUNT_MONEY, {
        "from_account": setup.e["checking"], "to_account": setup.e["cash"], "amount": 12.5,
    }, setup.allowed)

    txn = api.create_transaction.await_args.args[1]
    assert txn["account_id"] == CHECKING
    assert txn["amount"] == -12_500
    assert txn["payee_id"] == "payee-cash"
    assert txn["memo"] == "Moved by Julie via Home Assistant"
    assert "category_id" not in txn
    assert result["transaction_id"] == "txn"


async def test_tracking_transfer_needs_category(hass, setup):
    with pytest.raises(ServiceValidationError, match="category"):
        await _call(hass, SERVICE_TRANSFER_ACCOUNT_MONEY, {
            "from_account": setup.e["checking"], "to_account": setup.e["tracking"], "amount": 5,
        }, setup.allowed)


async def test_wrong_sensor_kind_is_rejected(hass, setup):
    with pytest.raises(ServiceValidationError, match="account sensor"):
        await _call(hass, SERVICE_TRANSFER_ACCOUNT_MONEY, {
            "from_account": setup.e["savings"], "to_account": setup.e["cash"], "amount": 5,
        }, setup.allowed)


async def test_integration_setup_registers_services(hass):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, SERVICE_MOVE_CATEGORY_MONEY)
    assert hass.services.has_service(DOMAIN, SERVICE_TRANSFER_ACCOUNT_MONEY)


async def test_network_error_on_second_write_restores_source(hass, setup):
    api = setup.api
    api.get_month_category.side_effect = [
        {"budgeted": 10_000, "balance": 20_000}, {"budgeted": 0, "balance": 0},
    ]
    api.set_month_category_budgeted.side_effect = [
        {}, YNABApiError("request failed: timeout"), YNABApiError("request failed: timeout"),
    ]

    with pytest.raises(HomeAssistantError, match="could not be restored"):
        await _call(hass, SERVICE_MOVE_CATEGORY_MONEY, {
            "from_category": setup.e["allowance"], "to_category": setup.e["savings"], "amount": 5,
        }, setup.allowed)


async def test_credit_card_source_skips_balance_check(hass, setup):
    setup.coordinator.data["accounts"][0]["type"] = "creditCard"
    await _call(hass, SERVICE_TRANSFER_ACCOUNT_MONEY, {
        "from_account": setup.e["checking"], "to_account": setup.e["cash"], "amount": 5,
    }, setup.allowed)
    setup.api.get_account.assert_not_awaited()
    setup.api.create_transaction.assert_awaited_once()


async def test_account_without_transfer_payee_is_rejected(hass, setup):
    del setup.coordinator.data["accounts"][1]["transfer_payee_id"]
    with pytest.raises(ServiceValidationError, match="transfers into Cash"):
        await _call(hass, SERVICE_TRANSFER_ACCOUNT_MONEY, {
            "from_account": setup.e["checking"], "to_account": setup.e["cash"], "amount": 5,
        }, setup.allowed)
