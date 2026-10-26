"""Tests for the category ledger's attribution of balance changes."""

import pytest

from custom_components.ynab_custom.ledger import CategoryLedger

CAT = "22222222-2222-2222-2222-222222222222"
OCT = "2026-10-01"
NOV = "2026-11-01"


def _cat(budgeted, activity, balance):
    return {"id": CAT, "name": "Savings Hazel", "budgeted": budgeted, "activity": activity, "balance": balance}


@pytest.fixture
def ledger(hass):
    ledger = CategoryLedger(hass, "entry", "$")
    ledger.observe([_cat(10_000, -2_000, 8_000)], OCT, [], full_refresh=True)
    return ledger


async def test_first_poll_is_only_a_baseline(ledger):
    assert ledger.entries(CAT) == []


async def test_assignment_in_ynab_is_recorded(ledger):
    ledger.observe([_cat(15_000, -2_000, 13_000)], OCT, [], full_refresh=False)
    [entry] = ledger.entries(CAT)
    assert entry["kind"] == "assigned"
    assert entry["amount"] == 5.0 and entry["balance"] == 13.0
    assert entry["by"] is None and entry["detail"] == "Assigned in YNAB"


async def test_spending_names_the_payees(ledger):
    changed = [
        {"category_id": CAT, "payee_name": "Lego Store", "amount": -12_500},
        {"category_id": "other", "payee_name": "Groceries", "amount": -50_000},
        {"category_id": None, "payee_name": "Target", "amount": -9_000,
         "subtransactions": [{"category_id": CAT, "amount": -3_000}]},
    ]
    ledger.observe([_cat(10_000, -17_500, -7_500)], OCT, changed, full_refresh=False)
    [entry] = ledger.entries(CAT)
    assert entry["kind"] == "spending" and entry["amount"] == -15.5
    assert entry["detail"] == "Lego Store -$12.50, Target -$3.00"


async def test_move_is_not_recorded_twice(ledger):
    ledger.record_move(CAT, 5_000, "Julie", "From Allowance",
                       {"budgeted": 15_000, "activity": -2_000, "balance": 13_000}, OCT)
    ledger.observe([_cat(15_000, -2_000, 13_000)], OCT, [], full_refresh=False)
    [entry] = ledger.entries(CAT)
    assert entry["kind"] == "move" and entry["by"] == "Julie"


async def test_month_rollover_starts_assigned_and_activity_from_zero(ledger):
    # November starts with $8 carried over and $5 assigned.
    ledger.observe([_cat(5_000, 0, 13_000)], NOV, [], full_refresh=False)
    [entry] = ledger.entries(CAT)
    assert entry["kind"] == "assigned" and entry["amount"] == 5.0


async def test_earlier_month_change_is_an_adjustment(ledger):
    changed = [{"category_id": CAT, "payee_name": "Refund", "amount": 4_000}]
    ledger.observe([_cat(10_000, -2_000, 12_000)], OCT, changed, full_refresh=False)
    [entry] = ledger.entries(CAT)
    assert entry["kind"] == "adjustment"
    assert entry["detail"] == "Earlier month: Refund +$4.00"


async def test_ledger_survives_a_restart(hass, ledger):
    ledger.observe([_cat(15_000, -2_000, 13_000)], OCT, [], full_refresh=False)
    await ledger._store.async_save({"snapshots": ledger._snapshots, "entries": ledger._entries})

    reloaded = CategoryLedger(hass, "entry", "$")
    await reloaded.async_load()
    assert reloaded.entries(CAT) == ledger.entries(CAT)
