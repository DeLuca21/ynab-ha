"""Exercise production logging paths with synthetic private data.

Run with: python -m unittest discover -s tests -v
Functions are loaded from their AST so these focused tests do not require a
running Home Assistant or import the integration's unrelated HA dependencies.
"""

import ast
from datetime import datetime
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components/ynab_custom"
LOGGER = logging.getLogger("ynab_logging_privacy_test")


def load_function(filename, name, **extra_globals):
    """Compile the actual function body, with external dependencies supplied."""
    source = INTEGRATION_DIR.joinpath(filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )
    constants = {}
    const_tree = ast.parse(INTEGRATION_DIR.joinpath("const.py").read_text(encoding="utf-8"))
    for node in const_tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            constants.update({target.id: node.value.value for target in node.targets if isinstance(target, ast.Name)})
    namespace = {"_LOGGER": LOGGER, "datetime": datetime, **constants, **extra_globals}
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(INTEGRATION_DIR / filename), "exec"), namespace)
    return namespace[name]


class LoggingPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_keeps_credentials_but_not_in_debug_logs(self):
        migrate = load_function("__init__.py", "async_migrate_entry")
        for interval in (None, 25):
            with self.subTest(interval=interval):
                data = {"access_token": "synthetic-private-token", "budget_name": "private-budget-name"}
                if interval is not None:
                    data["Update Interval"] = interval
                original_data = dict(data)
                entry = SimpleNamespace(
                    entry_id="test-entry", version=1, data=data,
                    options={"private_note": "private-option-note", "Include Closed Accounts": True},
                )
                update = Mock()
                hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
                with self.assertLogs(LOGGER, level=logging.DEBUG) as logs:
                    self.assertTrue(await migrate(hass, entry))
                output = "\n".join(logs.output)
                for value in ("synthetic-private-token", "private-budget-name", "private-option-note"):
                    self.assertNotIn(value, output)
                update.assert_called_once()
                migrated = update.call_args.kwargs
                self.assertEqual(migrated["data"]["access_token"], data["access_token"])
                self.assertNotIn("Update Interval", migrated["data"])
                self.assertEqual(migrated["options"]["Update Interval"], interval or 10)
                self.assertTrue(migrated["options"]["Include Closed Accounts"])
                self.assertFalse(migrated["options"]["Include Hidden Categories"])
                self.assertEqual(migrated["options"]["private_note"], "private-option-note")
                self.assertEqual(migrated["version"], 2)
                self.assertEqual(entry.data, original_data)

    async def test_failed_migration_does_not_dump_configuration(self):
        migrate = load_function("__init__.py", "async_migrate_entry")
        entry = SimpleNamespace(
            entry_id="test-entry", version=1,
            data={"access_token": "synthetic-private-token"}, options={},
        )
        update = Mock(side_effect=RuntimeError("Storage unavailable"))
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
        with self.assertLogs(LOGGER, level=logging.DEBUG) as logs:
            self.assertFalse(await migrate(hass, entry))
        self.assertNotIn("synthetic-private-token", "\n".join(logs.output))
        self.assertIn("Storage unavailable", "\n".join(logs.output))

    async def test_sensor_setup_does_not_log_financial_payloads(self):
        accounts = [{"id": "account", "name": "private-account", "note": "private-account-note", "balance": 987654321}]
        categories = [{"id": "category", "name": "private-category", "note": "private-category-note"}]
        coordinator = SimpleNamespace(
            data={"accounts": accounts, "categories": categories}, currency_symbol="£",
            selected_accounts=["account"], selected_categories=["category"],
        )
        entry = SimpleNamespace(entry_id="test-entry", data={"budget_name": "private-budget"})
        hass = SimpleNamespace(data={"ynab_custom": {entry.entry_id: coordinator}})
        sensor = Mock(side_effect=lambda *args: object())
        setup = load_function(
            "sensor.py", "async_setup_entry", sanitize_budget_name=lambda name: name,
            YNABExtrasSensor=sensor, YNABAPIStatusSensor=sensor,
            YNABAccountSensor=sensor, YNABCategorySensor=sensor,
        )
        add_entities = Mock()
        with self.assertLogs(LOGGER, level=logging.DEBUG) as logs:
            await setup(hass, entry, add_entities)
        self.assertEqual(len(add_entities.call_args.args[0]), 4)
        output = "\n".join(logs.output)
        for value in ("private-account", "private-category", "987654321"):
            self.assertNotIn(value, output)

    async def test_refresh_does_not_log_account_objects(self):
        account = {"id": "account", "name": "private-account", "note": "private-note", "balance": 987654321}
        api = SimpleNamespace(
            get_budget=AsyncMock(return_value={}),
            get_accounts=AsyncMock(return_value={"accounts": [account]}),
            get_categories=AsyncMock(return_value={"category_groups": []}),
            get_monthly_summary=AsyncMock(return_value={}),
            get_transactions=AsyncMock(return_value={"transactions": []}),
            get_rate_limit_info=Mock(return_value={}),
        )
        coordinator = SimpleNamespace(
            api=api, api_status={"consecutive_failures": 0}, budget_id="test-budget-id",
            selected_accounts=["account"], selected_categories=[],
            get_current_month=lambda: "2026-01-01", _save_persistent_data=Mock(),
        )
        refresh = load_function("coordinator.py", "_async_update_data")
        with self.assertLogs(LOGGER, level=logging.DEBUG) as logs:
            result = await refresh(coordinator)
        self.assertEqual(result["accounts"], [account])
        coordinator._save_persistent_data.assert_called_once_with(result)
        output = "\n".join(logs.output)
        for value in ("private-account", "private-note", "987654321"):
            self.assertNotIn(value, output)

    async def test_budget_discovery_does_not_log_budget_names(self):
        api = SimpleNamespace(get_budgets=AsyncMock(return_value={"budgets": [{"id": "budget", "name": "private-budget-name"}]}))
        flow = SimpleNamespace(
            hass=SimpleNamespace(data={}), async_step_budget_selection=AsyncMock(return_value={"step_id": "budget_selection"}),
        )
        discover = load_function(
            "config_flow.py", "async_step_user", CONF_ACCESS_TOKEN="access_token",
            YNABApi=Mock(return_value=api), CannotConnect=ConnectionError, InvalidAuth=PermissionError,
        )
        with self.assertLogs(LOGGER, level=logging.DEBUG) as logs:
            result = await discover(flow, {"access_token": "synthetic-private-token", "Accept Terms": True})
        self.assertEqual(result, {"step_id": "budget_selection"})
        self.assertEqual(flow.budgets, {"budget": "private-budget-name"})
        output = "\n".join(logs.output)
        self.assertNotIn("private-budget-name", output)
        self.assertNotIn("synthetic-private-token", output)


if __name__ == "__main__":
    unittest.main()
