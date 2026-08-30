"""Tests for the pure Budget Manager model."""

from __future__ import annotations

from datetime import date
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Import the pure model without executing the Home Assistant-dependent integration
# package initializer. This keeps these tests runnable with the standard library.
custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(ROOT / "custom_components")]
budget_package = types.ModuleType("custom_components.budget_manager")
budget_package.__path__ = [str(ROOT / "custom_components" / "budget_manager")]
sys.modules.setdefault("custom_components", custom_components)
sys.modules.setdefault("custom_components.budget_manager", budget_package)

model = importlib.import_module("custom_components.budget_manager.model")


class _FakeStore:
    def __init__(self, *_args, **_kwargs) -> None:
        self.saved = None

    async def async_load(self):
        return self.saved

    async def async_save(self, data) -> None:
        self.saved = data


homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []
homeassistant_core = types.ModuleType("homeassistant.core")
homeassistant_core.HomeAssistant = object
homeassistant_helpers = types.ModuleType("homeassistant.helpers")
homeassistant_helpers.__path__ = []
homeassistant_storage = types.ModuleType("homeassistant.helpers.storage")
homeassistant_storage.Store = _FakeStore
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", homeassistant_core)
sys.modules.setdefault("homeassistant.helpers", homeassistant_helpers)
sys.modules.setdefault("homeassistant.helpers.storage", homeassistant_storage)

manager_module = importlib.import_module("custom_components.budget_manager.manager")


class BudgetModelTests(unittest.TestCase):

    def test_default_cycle_ends_on_second_of_following_month(self) -> None:
        self.assertEqual(model.default_payday("2026-09"), "2026-10-02")
        self.assertEqual(model.default_payday("2026-12"), "2027-01-02")
        self.assertEqual(model.default_payday("2027-01", 31), "2027-02-28")

    def test_cycle_end_day_requires_whole_day_in_range(self) -> None:
        for invalid in (0, 32, 2.5, "tomorrow"):
            with self.subTest(invalid=invalid), self.assertRaises(
                model.BudgetValidationError
            ):
                model.normalize_cycle_end_day(invalid)

    def test_dynamic_savings_preserves_plan_inside_rag_band(self) -> None:
        month = model.make_month("2026-09")
        month["payday"] = "2026-09-30"
        month["account_balance"] = 1500
        month["items"] = [
            model.normalize_item(
                {"name": "Savings", "kind": "savings", "amount": 225}
            )
        ]
        summary = model.calculate_month(month, today=date(2026, 9, 1))
        self.assertEqual(summary["dynamic_savings"], 225)
        self.assertEqual(summary["savings_adjustment"], 0)
        self.assertEqual(summary["daily_allowance"], 42.5)
        self.assertEqual(summary["rag"], "yellow")

    def test_dynamic_savings_only_takes_money_above_green_daily_target(self) -> None:
        month = model.make_month("2026-09")
        month["payday"] = "2026-09-30"
        month["account_balance"] = 2000
        month["items"] = [
            model.normalize_item(
                {"name": "Bills", "kind": "expense", "amount": 500}
            ),
            model.normalize_item(
                {"name": "Savings", "kind": "savings", "amount": 0}
            ),
        ]
        summary = model.calculate_month(
            month,
            settings={
                "daily_green_threshold": 45,
                "daily_yellow_threshold": 40,
            },
            today=date(2026, 9, 1),
        )
        self.assertEqual(summary["dynamic_savings"], 150)
        self.assertEqual(summary["daily_allowance"], 45)
        self.assertEqual(summary["rag"], "green")

    def test_dynamic_savings_is_zero_when_daily_allowance_is_below_target(self) -> None:
        month = model.make_month("2026-09")
        month["payday"] = "2026-09-30"
        month["account_balance"] = 1200
        month["items"] = [
            model.normalize_item(
                {"name": "Savings", "kind": "savings", "amount": 500}
            )
        ]
        summary = model.calculate_month(month, today=date(2026, 9, 1))
        self.assertEqual(summary["dynamic_savings"], 0)
        self.assertEqual(summary["daily_allowance"], 40)
        self.assertEqual(summary["rag"], "yellow")

    def test_savings_range_is_independent_from_rag_colors(self) -> None:
        month = model.make_month("2026-09")
        month["payday"] = "2026-09-30"
        month["account_balance"] = 1800
        month["items"] = [
            model.normalize_item(
                {"name": "Savings", "kind": "savings", "amount": 0}
            )
        ]
        summary = model.calculate_month(
            month,
            settings={
                "daily_green_threshold": 70,
                "daily_yellow_threshold": 60,
                "savings_target_threshold": 50,
                "savings_floor_threshold": 35,
            },
            today=date(2026, 9, 1),
        )
        self.assertEqual(summary["dynamic_savings"], 300)
        self.assertEqual(summary["daily_allowance"], 50)
        self.assertEqual(summary["rag"], "red")
        self.assertEqual(summary["savings_target_threshold"], 50)
        self.assertEqual(summary["savings_floor_threshold"], 35)

    def test_threshold_order_is_validated(self) -> None:
        with self.assertRaisesRegex(
            model.BudgetValidationError, "cannot exceed"
        ):
            model.normalize_thresholds(
                {
                    "daily_green_threshold": 40,
                    "daily_yellow_threshold": 45,
                }
            )

    def test_savings_threshold_order_is_validated(self) -> None:
        with self.assertRaisesRegex(
            model.BudgetValidationError, "floor cannot exceed"
        ):
            model.normalize_savings_thresholds(
                {
                    "savings_target_threshold": 40,
                    "savings_floor_threshold": 45,
                }
            )

    def test_paid_expense_and_received_income_leave_forecast(self) -> None:
        month = model.make_month("2026-09")
        month["account_balance"] = 100
        month["items"] = [
            model.normalize_item(
                {"name": "Salary", "kind": "income", "amount": 1000}
            ),
            model.normalize_item(
                {"name": "Water", "kind": "expense", "amount": 50}
            ),
        ]
        initial = model.calculate_month(month, today=date(2026, 9, 1))
        self.assertEqual(initial["remaining"], 1050)
        month["items"][0]["status"] = "received"
        month["items"][1]["status"] = "paid"
        completed = model.calculate_month(month, today=date(2026, 9, 1))
        self.assertEqual(completed["remaining"], 100)

    def test_copy_month_resets_balance_and_status(self) -> None:
        source = model.make_month("2026-09")
        source["account_balance"] = 500
        source["payday"] = "2026-10-02"
        item = model.normalize_item(
            {"name": "Water", "kind": "expense", "amount": 50}
        )
        item["status"] = "paid"
        item["paid_at"] = "2026-09-03T10:00:00+00:00"
        source["items"] = [item]
        copied = model.copy_month_data(source, "2026-09", "2027-01")
        self.assertEqual(copied["account_balance"], 0)
        self.assertEqual(copied["payday"], "2027-02-02")
        self.assertEqual(copied["items"][0]["status"], "pending")
        self.assertIsNone(copied["items"][0]["paid_at"])
        self.assertNotEqual(copied["items"][0]["id"], item["id"])

    def test_bounded_monthly_recurrence(self) -> None:
        months = model.iter_recurrence_months(
            "2026-11", "monthly", "2027-02-15"
        )
        self.assertEqual(
            months, ["2026-11", "2026-12", "2027-01", "2027-02"]
        )

    def test_bounded_yearly_recurrence(self) -> None:
        months = model.iter_recurrence_months(
            "2026-11", "yearly", "2029-11-30"
        )
        self.assertEqual(months, ["2026-11", "2027-11", "2028-11", "2029-11"])

    def test_recurring_item_requires_end_date(self) -> None:
        with self.assertRaisesRegex(
            model.BudgetValidationError, "require an end date"
        ):
            model.normalize_item(
                {
                    "name": "Subscription",
                    "kind": "expense",
                    "amount": 10,
                    "recurrence": "monthly",
                }
            )

    def test_due_day_is_clamped(self) -> None:
        self.assertEqual(model.due_date("2027-02", 31), date(2027, 2, 28))

    def test_portable_export_round_trip(self) -> None:
        data = model.empty_data()
        data["settings"]["cycle_end_day"] = 5
        data["settings"]["daily_green_threshold"] = 52
        month = model.make_month("2026-09", cycle_end_day=5)
        month["account_balance"] = 1234.56
        month["items"] = [
            model.normalize_item(
                {
                    "name": "Water",
                    "kind": "expense",
                    "amount": 42.5,
                    "special": True,
                    "special_label": "Annual renewal",
                }
            )
        ]
        data["months"][month["month"]] = month
        document = model.export_data_document(data)
        imported = model.normalize_import_document(document)
        self.assertEqual(document["format"], "budget-manager")
        self.assertEqual(document["version"], 1)
        self.assertNotIn("configured", document["settings"])
        self.assertNotIn("created_from", document["months"]["2026-09"])
        self.assertEqual(imported["settings"]["cycle_end_day"], 5)
        self.assertEqual(imported["months"]["2026-09"]["payday"], "2026-10-05")
        self.assertEqual(imported["settings"]["daily_green_threshold"], 52)
        self.assertEqual(imported["months"]["2026-09"]["account_balance"], 1234.56)
        self.assertEqual(imported["months"]["2026-09"]["items"][0]["name"], "Water")

    def test_import_rejects_non_budget_json(self) -> None:
        with self.assertRaisesRegex(model.BudgetValidationError, "Not a Budget"):
            model.normalize_import_document({"format": "other", "version": 1})

    def test_year_view_always_contains_twelve_slots(self) -> None:
        data = model.empty_data()
        data["months"]["2026-09"] = model.make_month("2026-09")
        year = model.calculate_year(data, 2026, today=date(2026, 9, 1))
        self.assertEqual(len(year["months"]), 12)
        self.assertFalse(year["months"][0]["exists"])
        self.assertTrue(year["months"][8]["exists"])


class BudgetManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.manager = manager_module.BudgetManager(object(), "test")
        self.manager._data = model.empty_data()
        self.manager._data["months"]["2026-09"] = model.make_month("2026-09")

    async def test_recurring_create_materializes_until_end(self) -> None:
        await self.manager.async_upsert_item(
            "2026-09",
            {
                "name": "Water",
                "kind": "expense",
                "amount": 50,
                "recurrence": "monthly",
                "recurrence_end": "2026-11-30",
            },
        )
        self.assertEqual(
            sorted(self.manager.data["months"]),
            ["2026-09", "2026-10", "2026-11"],
        )
        occurrences = [
            self.manager.data["months"][key]["items"][0]
            for key in sorted(self.manager.data["months"])
        ]
        self.assertEqual(len({item["series_id"] for item in occurrences}), 1)
        self.assertEqual(len({item["id"] for item in occurrences}), 3)

    async def test_delete_future_preserves_paid_history(self) -> None:
        await self.manager.async_upsert_item(
            "2026-09",
            {
                "name": "Water",
                "kind": "expense",
                "amount": 50,
                "recurrence": "monthly",
                "recurrence_end": "2026-11-30",
            },
        )
        october = self.manager.data["months"]["2026-10"]["items"][0]
        await self.manager.async_set_item_status("2026-10", october["id"], "paid")
        september = self.manager.data["months"]["2026-09"]["items"][0]
        await self.manager.async_delete_item(
            "2026-09", september["id"], scope="future"
        )
        self.assertEqual(self.manager.data["months"]["2026-09"]["items"], [])
        self.assertEqual(
            self.manager.data["months"]["2026-10"]["items"][0]["status"],
            "paid",
        )
        self.assertEqual(self.manager.data["months"]["2026-11"]["items"], [])

    async def test_create_year_preserves_existing_months_without_overwrite(self) -> None:
        self.manager.data["months"]["2026-09"]["account_balance"] = 321
        await self.manager.async_create_year(2026, overwrite=False)
        self.assertEqual(len(self.manager.data["months"]), 12)
        self.assertEqual(
            self.manager.data["months"]["2026-09"]["account_balance"], 321
        )

    async def test_new_install_starts_empty_and_ready(self) -> None:
        manager = manager_module.BudgetManager(object(), "new")
        await manager.async_load()
        self.assertTrue(manager.data["settings"]["configured"])
        self.assertEqual(manager.data["months"], {})

    async def test_import_replaces_existing_budget(self) -> None:
        source = model.empty_data()
        source["settings"]["savings_target_threshold"] = 48
        source["months"]["2027-01"] = model.make_month("2027-01")
        await self.manager.async_import_data(model.export_data_document(source))
        self.assertEqual(sorted(self.manager.data["months"]), ["2027-01"])
        self.assertEqual(self.manager.data["settings"]["savings_target_threshold"], 48)

    async def test_failed_import_preserves_existing_budget(self) -> None:
        before = self.manager.data
        with self.assertRaises(model.BudgetValidationError):
            await self.manager.async_import_data(
                {"format": "budget-manager", "version": 99, "months": {}}
            )
        self.assertIs(self.manager.data, before)
        self.assertIn("2026-09", self.manager.data["months"])

    async def test_settings_update_stores_rag_and_savings_separately(self) -> None:
        await self.manager.async_update_settings(
            {
                "cycle_end_day": 7,
                "daily_green_threshold": 52,
                "daily_yellow_threshold": 41,
                "savings_target_threshold": 47,
                "savings_floor_threshold": 36,
            }
        )
        settings = self.manager.data["settings"]
        self.assertEqual(settings["cycle_end_day"], 7)
        self.assertEqual(
            self.manager.data["months"]["2026-09"]["payday"], "2026-10-07"
        )
        self.assertEqual(settings["daily_green_threshold"], 52)
        self.assertEqual(settings["daily_yellow_threshold"], 41)
        self.assertEqual(settings["savings_target_threshold"], 47)
        self.assertEqual(settings["savings_floor_threshold"], 36)

    async def test_new_month_uses_global_cycle_end_day(self) -> None:
        await self.manager.async_update_settings({"cycle_end_day": 12})
        created = await self.manager.async_create_month("2026-10")
        self.assertEqual(created["payday"], "2026-11-12")

    async def test_marking_dynamic_savings_paid_freezes_transfer(self) -> None:
        month = self.manager.data["months"]["2026-09"]
        month["payday"] = "2026-09-30"
        month["account_balance"] = 2000
        item = model.normalize_item(
            {"name": "Savings", "kind": "savings", "amount": 0}
        )
        month["items"] = [item]
        expected_transfer = model.calculate_month(
            month, settings=self.manager.data["settings"]
        )["dynamic_savings"]
        await self.manager.async_set_item_status("2026-09", item["id"], "paid")
        stored = month["items"][0]
        self.assertEqual(stored["status"], "paid")
        self.assertEqual(stored["amount"], expected_transfer)
        summary = model.calculate_month(
            month,
            settings=self.manager.data["settings"],
            today=date(2026, 9, 1),
        )
        self.assertEqual(summary["planned_savings"], 0)
        self.assertEqual(summary["daily_allowance"], 66.67)

    async def test_existing_storage_migrates_savings_without_reconfiguration(self) -> None:
        manager = manager_module.BudgetManager(object(), "old")
        old = model.empty_data()
        old["settings"].pop("configured")
        month = model.make_month("2026-09")
        month["items"] = [
            model.normalize_item(
                {"name": "Savings", "kind": "expense", "amount": 300}
            )
        ]
        old["months"]["2026-09"] = month
        manager._store.saved = old
        await manager.async_load()
        self.assertTrue(manager.data["settings"]["configured"])
        migrated = manager.data["months"]["2026-09"]["items"][0]
        self.assertEqual(migrated["kind"], "savings")
        self.assertTrue(migrated["dynamic"])

    async def test_existing_zero_value_expenses_are_preserved(self) -> None:
        manager = manager_module.BudgetManager(object(), "old-zero")
        old = model.empty_data()
        old["settings"].pop("configured")
        month = model.make_month("2026-09")
        month["items"] = [
            model.normalize_item(
                {"name": "Annual tax placeholder", "kind": "expense", "amount": 0}
            ),
            model.normalize_item(
                {"name": "Water", "kind": "expense", "amount": 100}
            ),
        ]
        old["months"]["2026-09"] = month
        manager._store.saved = old
        await manager.async_load()
        self.assertEqual(
            [item["name"] for item in manager.data["months"]["2026-09"]["items"]],
            ["Annual tax placeholder", "Water"],
        )

    async def test_snapshot_contains_selected_and_next_year_months(self) -> None:
        self.manager.data["months"]["2027-01"] = model.make_month("2027-01")
        snapshot = self.manager.snapshot(2026)
        self.assertEqual(snapshot["plan_years"], [2026, 2027])
        self.assertIn("2026-09", snapshot["months"])
        self.assertIn("2027-01", snapshot["months"])

    async def test_month_notes_are_removed_during_migration(self) -> None:
        manager = manager_module.BudgetManager(object(), "old-note")
        old = model.empty_data()
        old["settings"]["configured"] = True
        month = model.make_month("2026-09")
        month["note"] = "Remove me"
        old["months"]["2026-09"] = month
        manager._store.saved = old
        await manager.async_load()
        self.assertNotIn("note", manager.data["months"]["2026-09"])


if __name__ == "__main__":
    unittest.main()
