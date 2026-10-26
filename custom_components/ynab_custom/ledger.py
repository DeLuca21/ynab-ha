"""Permanent record of why each category's balance changed.

Home Assistant's history only shows that a balance went up or down, and the
recorder purges it after a few days. The ledger keeps one entry per change,
with the reason where it can be told: a move made through this integration
(and who made it), an assignment changed in YNAB itself, or the transactions
that changed the category's activity. It is stored in .storage alongside the
other integration data, so it survives restarts and is part of HA backups.

Entries are kept in milliunits internally and exposed in currency units.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 10

# A category changing a few times a day stays far below this for years; the
# cap only keeps a runaway category from growing the file without bound.
MAX_ENTRIES_PER_CATEGORY = 2000

# How many recent entries the category sensors carry as an attribute.
RECENT_ENTRIES = 5

# Kinds of change, as stored in each entry.
KIND_MOVE = "move"
KIND_ASSIGNED = "assigned"
KIND_SPENDING = "spending"
KIND_INFLOW = "inflow"
KIND_ADJUSTMENT = "adjustment"

MAX_DETAIL_TRANSACTIONS = 3


def _units(milliunits: int) -> float:
    return round(milliunits / 1000, 2)


def _transactions_for(category_id: str, transactions: list) -> list:
    """Return (payee, amount) for each transaction or split touching the category."""
    found = []
    for t in transactions:
        if t.get("category_id") == category_id:
            found.append((t.get("payee_name") or "Unknown payee", t.get("amount", 0), t.get("deleted", False)))
        for sub in t.get("subtransactions") or []:
            if sub.get("category_id") == category_id:
                found.append((
                    sub.get("payee_name") or t.get("payee_name") or "Unknown payee",
                    sub.get("amount", 0),
                    t.get("deleted", False) or sub.get("deleted", False),
                ))
    return found


def _describe(found: list, symbol: str) -> str:
    parts = []
    for payee, amount, deleted in found[:MAX_DETAIL_TRANSACTIONS]:
        label = f"{payee} {'+' if amount >= 0 else '-'}{symbol}{abs(amount) / 1000:,.2f}"
        parts.append(f"{label} (deleted)" if deleted else label)
    if len(found) > MAX_DETAIL_TRANSACTIONS:
        parts.append(f"and {len(found) - MAX_DETAIL_TRANSACTIONS} more")
    return ", ".join(parts)


class CategoryLedger:
    """Per-budget ledger of category balance changes."""

    def __init__(self, hass: HomeAssistant, entry_id: str, currency_symbol: str):
        self._store = Store(hass, STORAGE_VERSION, f"ynab_ledger_{entry_id}", private=True)
        self._symbol = currency_symbol
        # category id -> {"month", "budgeted", "activity", "balance"} in milliunits
        self._snapshots: dict[str, dict] = {}
        # category id -> list of entries, oldest first
        self._entries: dict[str, list] = {}

    async def async_load(self) -> None:
        try:
            stored = await self._store.async_load() or {}
        except Exception as err:  # A corrupt ledger must not stop the integration
            _LOGGER.warning("Could not load the YNAB category ledger: %s", err)
            stored = {}
        self._snapshots = stored.get("snapshots", {})
        self._entries = stored.get("entries", {})

    def _schedule_save(self) -> None:
        self._store.async_delay_save(
            lambda: {"snapshots": self._snapshots, "entries": self._entries},
            SAVE_DELAY_SECONDS,
        )

    def _append(self, category_id: str, entry: dict) -> None:
        entries = self._entries.setdefault(category_id, [])
        entries.append(entry)
        if len(entries) > MAX_ENTRIES_PER_CATEGORY:
            del entries[: len(entries) - MAX_ENTRIES_PER_CATEGORY]

    def entries(self, category_id: str, limit: int | None = None) -> list:
        """Return a category's entries, newest first."""
        entries = list(reversed(self._entries.get(category_id, [])))
        return entries[:limit] if limit else entries

    def recent(self, category_id: str) -> list:
        return self.entries(category_id, RECENT_ENTRIES)

    def record_move(
        self, category_id: str, amount: int, by: str, detail: str, after: dict, month: str
    ) -> None:
        """Record a move made through this integration.

        after is the category as YNAB returned it from the write. Taking it as
        the new snapshot keeps the next poll from recording the same change
        again as an assignment made in YNAB.
        """
        self._append(category_id, {
            "at": dt_util.now().isoformat(timespec="seconds"),
            "kind": KIND_MOVE,
            "amount": _units(amount),
            "balance": _units(after.get("balance", 0)),
            "by": by,
            "detail": detail,
        })
        self._snapshots[category_id] = {
            "month": month,
            "budgeted": after.get("budgeted", 0),
            "activity": after.get("activity", 0),
            "balance": after.get("balance", 0),
        }
        self._schedule_save()

    def observe(self, categories: list, month: str, changed_transactions: list, full_refresh: bool) -> None:
        """Compare freshly polled categories with the last snapshot and record the differences.

        changed_transactions are the transactions YNAB reported as changed
        in this poll; they name the payees behind an activity change. On a
        full refresh every transaction comes back, so none can be singled out.
        """
        now = dt_util.now().isoformat(timespec="seconds")
        changed = False

        for category in categories:
            category_id = category["id"]
            current = {
                "month": month,
                "budgeted": category.get("budgeted") or 0,
                "activity": category.get("activity") or 0,
                "balance": category.get("balance") or 0,
            }
            previous = self._snapshots.get(category_id)
            self._snapshots[category_id] = current
            if previous is None:
                changed = True  # First sight of this category: baseline only
                continue
            if previous == current:
                continue
            changed = True

            if previous.get("month") != month:
                # Assigned and activity start again from zero in a new month.
                previous = {**previous, "budgeted": 0, "activity": 0}

            budgeted_delta = current["budgeted"] - previous["budgeted"]
            activity_delta = current["activity"] - previous["activity"]
            residual = (current["balance"] - previous["balance"]) - budgeted_delta - activity_delta

            found = [] if full_refresh else _transactions_for(category_id, changed_transactions)
            running = previous["balance"]

            def add(kind, amount, detail, running_balance):
                self._append(category_id, {
                    "at": now,
                    "kind": kind,
                    "amount": _units(amount),
                    "balance": _units(running_balance),
                    "by": None,
                    "detail": detail,
                })

            if budgeted_delta:
                running += budgeted_delta
                add(
                    KIND_ASSIGNED,
                    budgeted_delta,
                    "Assigned in YNAB" if budgeted_delta > 0 else "Unassigned in YNAB",
                    running,
                )
            if activity_delta:
                running += activity_delta
                add(
                    KIND_INFLOW if activity_delta > 0 else KIND_SPENDING,
                    activity_delta,
                    _describe(found, self._symbol) or "Transactions in YNAB",
                    running,
                )
            if residual:
                running += residual
                if previous.get("month") != month:
                    detail = "Month rollover"
                elif not activity_delta and found:
                    detail = f"Earlier month: {_describe(found, self._symbol)}"
                else:
                    detail = "Change in an earlier month"
                add(KIND_ADJUSTMENT, residual, detail, running)

        if changed:
            self._schedule_save()
