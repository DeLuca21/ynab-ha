"""Services for moving money in YNAB from Home Assistant.

The services that move money change real budget data, so every call is
checked against the per-budget allowlist of Home Assistant users set in the
integration options. Calls without a user behind them (automations, the
developer tools of a system user) are refused, as are calls from anyone not
on the list. An empty list means nobody can move money. Each move is also
written to the category ledger with the name of the user who made it.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import YNABApiError
from .const import (
    CONF_MONEY_MOVERS,
    DOMAIN,
    EVENT_MONEY_MOVED,
    READY_TO_ASSIGN_NAMES,
    SERVICE_GET_CATEGORY_HISTORY,
    SERVICE_MOVE_CATEGORY_MONEY,
    SERVICE_TRANSFER_ACCOUNT_MONEY,
)

_LOGGER = logging.getLogger(__name__)

# YNAB ids are UUIDs, and the sensors' unique ids end with them.
YNAB_ID_LENGTH = 36
MEMO_MAX_LENGTH = 200

# Debt accounts carry negative balances, so "available" does not apply.
LIABILITY_ACCOUNT_TYPES = {
    "creditCard", "lineOfCredit", "otherLiability", "mortgage", "autoLoan",
    "studentLoan", "personalLoan", "medicalDebt", "otherDebt",
}

AMOUNT = vol.All(vol.Coerce(float), vol.Range(min=0.01, max=1_000_000))

MOVE_CATEGORY_MONEY_SCHEMA = vol.Schema(
    {
        vol.Optional("from_category"): cv.entity_id,
        vol.Optional("to_category"): cv.entity_id,
        vol.Required("amount"): AMOUNT,
        vol.Optional("allow_overdraw", default=False): cv.boolean,
    }
)

GET_CATEGORY_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Required("category"): cv.entity_id,
        vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=2000)),
    }
)

TRANSFER_ACCOUNT_MONEY_SCHEMA = vol.Schema(
    {
        vol.Required("from_account"): cv.entity_id,
        vol.Required("to_account"): cv.entity_id,
        vol.Required("amount"): AMOUNT,
        vol.Optional("category"): cv.entity_id,
        vol.Optional("memo"): cv.string,
        vol.Optional("allow_overdraw", default=False): cv.boolean,
    }
)


def _to_milliunits(amount: float) -> int:
    return int(round(amount * 1000))


def _format(milliunits: int, currency_symbol: str) -> str:
    return f"{currency_symbol}{milliunits / 1000:,.2f}"


def _resolve(hass: HomeAssistant, entity_id: str, kind: str):
    """Map a YNAB sensor entity to its coordinator and YNAB record.

    kind is "accounts" or "categories", matching the coordinator data keys.
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN:
        raise ServiceValidationError(f"{entity_id} is not a YNAB sensor")

    coordinator = hass.data.get(DOMAIN, {}).get(entry.config_entry_id)
    if coordinator is None or not coordinator.data:
        raise ServiceValidationError(f"The YNAB budget for {entity_id} is not loaded")

    ynab_id = (entry.unique_id or "")[-YNAB_ID_LENGTH:]
    record = next((r for r in coordinator.data.get(kind, []) if r.get("id") == ynab_id), None)
    if record is None:
        label = "account" if kind == "accounts" else "category"
        raise ServiceValidationError(f"{entity_id} is not a YNAB {label} sensor")

    return coordinator, record


async def _authorize(hass: HomeAssistant, call: ServiceCall, coordinator):
    """Return the calling user if they may move money in this budget."""
    user_id = call.context.user_id
    allowed = coordinator.entry.options.get(CONF_MONEY_MOVERS, [])

    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None or not user.is_active or user.id not in allowed:
        _LOGGER.warning(
            "Refused YNAB %s for user %s on budget %s",
            call.service,
            user.name if user else "(none)",
            coordinator.budget_name,
        )
        raise Unauthorized(context=call.context)

    return user


def _single_coordinator(*coordinators):
    present = [c for c in coordinators if c is not None]
    if len({c.entry.entry_id for c in present}) > 1:
        raise ServiceValidationError("Money can only be moved within one YNAB budget")
    return present[0]


async def _move_category_money(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Reassign budgeted money between two categories for the current month.

    Leaving out from_category or to_category (or picking the Ready to Assign
    sensor) moves the money from or to Ready to Assign. YNAB has no "move"
    endpoint: assigned amounts are set as totals, so each side is read and
    then written back adjusted. No transaction is created.
    """
    amount = _to_milliunits(call.data["amount"])

    sides = {}
    for side in ("from_category", "to_category"):
        entity_id = call.data.get(side)
        if entity_id:
            coordinator, category = _resolve(hass, entity_id, "categories")
            sides[side] = (coordinator, None if category["name"] in READY_TO_ASSIGN_NAMES else category)
        else:
            sides[side] = (None, None)

    coordinator = (
        _single_coordinator(sides["from_category"][0], sides["to_category"][0])
        if any(c for c, _ in sides.values())
        else None
    )
    if coordinator is None:
        raise ServiceValidationError("Pick at least one category to move money from or to")

    source = sides["from_category"][1]
    target = sides["to_category"][1]
    if source is None and target is None:
        raise ServiceValidationError("Moving from Ready to Assign to Ready to Assign does nothing")
    if source is not None and target is not None and source["id"] == target["id"]:
        raise ServiceValidationError("The source and destination categories are the same")

    user = await _authorize(hass, call, coordinator)
    api = coordinator.api
    budget_id = coordinator.budget_id
    symbol = coordinator.currency_symbol

    try:
        if source is not None:
            source_now = await api.get_month_category(budget_id, source["id"])
            available = source_now.get("balance", 0)
            source_label = source["name"]
        else:
            available = (await api.get_month(budget_id)).get("to_be_budgeted", 0)
            source_label = "Ready to Assign"

        if amount > available and not call.data["allow_overdraw"]:
            raise ServiceValidationError(
                f"Only {_format(available, symbol)} available in {source_label}"
            )

        target_now = (
            await api.get_month_category(budget_id, target["id"]) if target is not None else None
        )

        source_after = None
        if source is not None:
            source_after = await api.set_month_category_budgeted(
                budget_id, source["id"], source_now.get("budgeted", 0) - amount
            )

        target_after = None
        if target is not None:
            try:
                target_after = await api.set_month_category_budgeted(
                    budget_id, target["id"], target_now.get("budgeted", 0) + amount
                )
            except YNABApiError as err:
                if source is not None:
                    # Put the source back so the money is not left in limbo.
                    try:
                        await api.set_month_category_budgeted(
                            budget_id, source["id"], source_now.get("budgeted", 0)
                        )
                    except YNABApiError as rollback_err:
                        raise YNABApiError(
                            f"{err}; {source_label} could not be restored "
                            f"({rollback_err}), so {_format(amount, symbol)} "
                            "is now in Ready to Assign"
                        ) from err
                raise
    except YNABApiError as err:
        raise HomeAssistantError(f"YNAB rejected the move: {err}") from err

    target_label = target["name"] if target is not None else "Ready to Assign"
    month = coordinator.get_current_month()
    if source_after:
        coordinator.ledger.record_move(
            source["id"], -amount, user.name, f"To {target_label}", source_after, month
        )
    if target_after:
        coordinator.ledger.record_move(
            target["id"], amount, user.name, f"From {source_label}", target_after, month
        )
    result = {
        "amount": amount / 1000,
        "from": source_label,
        "to": target_label,
        "from_balance": source_after.get("balance", 0) / 1000 if source_after else None,
        "to_balance": target_after.get("balance", 0) / 1000 if target_after else None,
        "user": user.name,
    }
    _LOGGER.info(
        "%s moved %s from %s to %s in %s",
        user.name, _format(amount, symbol), source_label, target_label, coordinator.budget_name,
    )
    hass.bus.async_fire(
        EVENT_MONEY_MOVED,
        {"type": "category", "budget": coordinator.budget_name, **result},
        context=call.context,
    )
    await coordinator.async_request_refresh()
    return result


async def _transfer_account_money(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Record a transfer between two accounts as a YNAB transfer transaction.

    YNAB creates the matching transaction in the destination account itself.
    A transfer between an on-budget and a tracking account needs a category
    for the on-budget side, which YNAB would otherwise leave uncategorized.
    """
    amount = _to_milliunits(call.data["amount"])

    from_coordinator, source = _resolve(hass, call.data["from_account"], "accounts")
    to_coordinator, target = _resolve(hass, call.data["to_account"], "accounts")
    category_coordinator, category = (
        _resolve(hass, call.data["category"], "categories") if call.data.get("category") else (None, None)
    )
    coordinator = _single_coordinator(from_coordinator, to_coordinator, category_coordinator)

    if source["id"] == target["id"]:
        raise ServiceValidationError("The source and destination accounts are the same")
    if source.get("on_budget") != target.get("on_budget") and category is None:
        raise ServiceValidationError(
            "A transfer between an on-budget and a tracking account needs a category"
        )

    user = await _authorize(hass, call, coordinator)
    api = coordinator.api
    budget_id = coordinator.budget_id
    symbol = coordinator.currency_symbol

    memo = call.data.get("memo") or f"Moved by {user.name} via Home Assistant"

    transfer_payee_id = target.get("transfer_payee_id")
    if not transfer_payee_id:
        raise ServiceValidationError(f"YNAB does not allow transfers into {target['name']}")

    try:
        if source.get("type") not in LIABILITY_ACCOUNT_TYPES and not call.data["allow_overdraw"]:
            source_now = await api.get_account(budget_id, source["id"])
            if amount > source_now.get("balance", 0):
                raise ServiceValidationError(
                    f"Only {_format(source_now.get('balance', 0), symbol)} available in {source['name']}"
                )

        transaction = {
            "account_id": source["id"],
            "date": dt_util.now().date().isoformat(),
            "amount": -amount,
            "payee_id": transfer_payee_id,
            "memo": memo[:MEMO_MAX_LENGTH],
            "cleared": "cleared",
            "approved": True,
        }
        if category is not None:
            transaction["category_id"] = category["id"]
        created = await api.create_transaction(budget_id, transaction)
    except YNABApiError as err:
        raise HomeAssistantError(f"YNAB rejected the transfer: {err}") from err

    result = {
        "amount": amount / 1000,
        "from": source["name"],
        "to": target["name"],
        "transaction_id": created.get("id"),
        "user": user.name,
    }
    _LOGGER.info(
        "%s transferred %s from %s to %s in %s",
        user.name, _format(amount, symbol), source["name"], target["name"], coordinator.budget_name,
    )
    hass.bus.async_fire(
        EVENT_MONEY_MOVED,
        {"type": "account", "budget": coordinator.budget_name, **result},
        context=call.context,
    )
    await coordinator.async_request_refresh()
    return result


async def _get_category_history(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Return a category's recorded balance changes, newest first.

    Read-only, so it is open to anyone who can already see the balances.
    """
    coordinator, category = _resolve(hass, call.data["category"], "categories")
    return {
        "category": category["name"],
        "changes": coordinator.ledger.entries(category["id"], call.data["limit"]),
    }


def async_register_services(hass: HomeAssistant) -> None:
    """Register the money movement services once for the integration."""
    if hass.services.has_service(DOMAIN, SERVICE_MOVE_CATEGORY_MONEY):
        return

    async def move_category_money(call: ServiceCall) -> ServiceResponse:
        return await _move_category_money(hass, call)

    async def transfer_account_money(call: ServiceCall) -> ServiceResponse:
        return await _transfer_account_money(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_MOVE_CATEGORY_MONEY,
        move_category_money,
        schema=MOVE_CATEGORY_MONEY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async def get_category_history(call: ServiceCall) -> ServiceResponse:
        return await _get_category_history(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CATEGORY_HISTORY,
        get_category_history,
        schema=GET_CATEGORY_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TRANSFER_ACCOUNT_MONEY,
        transfer_account_money,
        schema=TRANSFER_ACCOUNT_MONEY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
