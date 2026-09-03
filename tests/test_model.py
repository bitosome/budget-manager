"""Tests for the pure Budget Manager model."""

from __future__ import annotations

from datetime import date, datetime
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
payroll = importlib.import_module(
    "custom_components.budget_manager.estonian_payroll"
)
care_leave = importlib.import_module(
    "custom_components.budget_manager.estonian_care_leave"
)


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
homeassistant_exceptions = types.ModuleType("homeassistant.exceptions")
homeassistant_exceptions.HomeAssistantError = Exception
homeassistant_helpers = types.ModuleType("homeassistant.helpers")
homeassistant_helpers.__path__ = []
homeassistant_storage = types.ModuleType("homeassistant.helpers.storage")
homeassistant_storage.Store = _FakeStore
homeassistant_entity_registry = types.ModuleType(
    "homeassistant.helpers.entity_registry"
)
homeassistant_entity_registry.async_get = lambda _hass: None
homeassistant_entity_registry.async_entries_for_config_entry = (
    lambda _registry, _entry_id: []
)
homeassistant_event = types.ModuleType("homeassistant.helpers.event")
homeassistant_event.async_track_time_change = lambda *_args, **_kwargs: lambda: None
homeassistant_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
homeassistant_aiohttp.async_get_clientsession = lambda _hass: None
homeassistant_util = types.ModuleType("homeassistant.util")
homeassistant_util.__path__ = []
homeassistant_util_dt = types.ModuleType("homeassistant.util.dt")
homeassistant_util_dt.now = lambda: datetime.now().astimezone()
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", homeassistant_core)
sys.modules.setdefault("homeassistant.exceptions", homeassistant_exceptions)
sys.modules.setdefault("homeassistant.helpers", homeassistant_helpers)
sys.modules.setdefault("homeassistant.helpers.storage", homeassistant_storage)
sys.modules.setdefault(
    "homeassistant.helpers.entity_registry", homeassistant_entity_registry
)
sys.modules.setdefault("homeassistant.helpers.event", homeassistant_event)
sys.modules.setdefault("homeassistant.helpers.aiohttp_client", homeassistant_aiohttp)
sys.modules.setdefault("homeassistant.util", homeassistant_util)
sys.modules.setdefault("homeassistant.util.dt", homeassistant_util_dt)

manager_module = importlib.import_module("custom_components.budget_manager.manager")
notification_module = importlib.import_module(
    "custom_components.budget_manager.notifications"
)
calendar_module = importlib.import_module(
    "custom_components.budget_manager.estonian_calendar"
)


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

    def test_active_budget_month_remains_previous_through_cycle_end(self) -> None:
        data = model.empty_data()
        data["settings"]["cycle_end_day"] = 2
        data["months"]["2026-08"] = model.make_month("2026-08")
        data["months"]["2026-09"] = model.make_month("2026-09")

        self.assertEqual(
            model.current_month_key(data, today=date(2026, 9, 1)), "2026-08"
        )
        self.assertEqual(
            model.current_month_key(data, today=date(2026, 9, 2)), "2026-08"
        )
        self.assertEqual(
            model.current_month_key(data, today=date(2026, 9, 3)), "2026-09"
        )

    def test_estonian_august_working_hours_match_public_calendar(self) -> None:
        holidays = payroll.statutory_estonian_holidays(2026)
        result = payroll.estonian_working_time("2026-08", holidays)

        self.assertEqual(result["working_days"], 20)
        self.assertEqual(result["working_hours"], 160)
        self.assertIn("2026-08-20", result["public_holidays"])

    def test_estonian_working_hours_include_shortened_preholiday_days(self) -> None:
        holidays = payroll.statutory_estonian_holidays(2026)
        holidays.update(payroll.statutory_estonian_holidays(2027))

        february = payroll.estonian_working_time("2026-02", holidays)
        december = payroll.estonian_working_time("2026-12", holidays)

        self.assertEqual(february["working_hours"], 149)
        self.assertEqual(february["shortened_workdays"], ["2026-02-23"])
        self.assertEqual(december["working_hours"], 162)
        self.assertEqual(
            december["shortened_workdays"], ["2026-12-23", "2026-12-31"]
        )

    def test_estonian_hourly_payroll_defaults_match_2026_rules(self) -> None:
        result = payroll.calculate_estonian_payroll(
            {
                "mode": "estonian_hourly",
                "hourly_gross": 14,
                "working_hours_mode": "automatic",
                "working_hours": 160,
                "apply_social_tax_minimum": True,
                "apply_tax_free_income": True,
                "tax_free_income": 700,
                "employee_unemployment": True,
                "employer_unemployment": True,
                "funded_pension_rate": 0,
            },
            payment_year=2026,
        )

        self.assertEqual(result["gross_income"], 2240)
        self.assertEqual(result["employee_unemployment_amount"], 35.84)
        self.assertEqual(result["income_tax_amount"], 330.92)
        self.assertEqual(result["net_income"], 1873.24)
        self.assertEqual(result["social_tax_amount"], 739.2)
        self.assertEqual(result["employer_unemployment_amount"], 17.92)
        self.assertEqual(result["employer_cost"], 2997.12)
        self.assertFalse(result["funded_pension_joined"])
        self.assertEqual(result["funded_pension_rate"], 0)

    def test_unchecked_funded_pension_always_forces_zero_percent(self) -> None:
        result = payroll.calculate_estonian_payroll(
            {
                "mode": "estonian_hourly",
                "hourly_gross": 14,
                "working_hours_mode": "manual",
                "working_hours": 160,
                "funded_pension_joined": False,
                "funded_pension_rate": 6,
            },
            payment_year=2026,
        )

        self.assertFalse(result["funded_pension_joined"])
        self.assertEqual(result["funded_pension_rate"], 0)
        self.assertEqual(result["funded_pension_amount"], 0)

    def test_previous_income_work_period_crosses_year_boundary(self) -> None:
        self.assertEqual(
            payroll.income_working_time_month("2026-09", "previous_month"),
            "2026-08",
        )
        self.assertEqual(
            payroll.income_working_time_month("2027-01", "previous_month"),
            "2026-12",
        )

    def test_weekend_care_leave_adds_benefit_without_salary_hours(self) -> None:
        result = care_leave.calculate_care_period(
            {"id": "weekend", "start": "2026-09-05", "end": "2026-09-06"},
            hourly_gross=14,
            previous_year_working_hours=0,
            benefit_basis_mode="actual_previous_year_income",
            actual_previous_year_income=36500,
            public_holidays=[],
            shortened_workdays=[],
            benefit_year=2026,
        )

        self.assertEqual(result["calendar_days"], 2)
        self.assertEqual(result["missed_working_hours"], 0)
        self.assertEqual(result["estimated_net_benefit"], 124.8)
        self.assertEqual(result["benefit_basis_mode"], "actual_previous_year_income")

    def test_hourly_care_benefit_basis_is_clearly_an_estimate(self) -> None:
        result = care_leave.calculate_care_period(
            {"id": "weekday", "start": "2026-09-07", "end": "2026-09-07"},
            hourly_gross=14,
            previous_year_working_hours=2000,
            benefit_basis_mode="estimated_hourly",
            actual_previous_year_income=0,
            public_holidays=[],
            shortened_workdays=[],
            benefit_year=2026,
        )

        self.assertEqual(result["missed_working_hours"], 8)
        self.assertEqual(result["estimated_previous_year_gross"], 28000)
        self.assertTrue(result["estimated"])

    def test_care_leave_periods_must_not_overlap(self) -> None:
        with self.assertRaisesRegex(model.BudgetValidationError, "cannot overlap"):
            model.normalize_item(
                {
                    "name": "Child-care sick leave",
                    "kind": "expense",
                    "amount": 0,
                    "expense_type": "child_care_leave",
                    "care_leave": {
                        "linked_income_item_id": "salary",
                        "work_month": "2026-09",
                        "income_month": "2026-10",
                        "periods": [
                            {"id": "one", "start": "2026-09-05", "end": "2026-09-07"},
                            {"id": "two", "start": "2026-09-07", "end": "2026-09-08"},
                        ],
                        "benefit_basis_mode": "estimated_hourly",
                    },
                }
            )

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

    def test_automatic_savings_ignores_stored_amount_and_hits_target(self) -> None:
        month = model.make_month("2026-09")
        month["payday"] = "2026-09-30"
        month["account_balance"] = 2000
        month["items"] = [
            model.normalize_item(
                {"name": "Bills", "kind": "expense", "amount": 500}
            ),
            model.normalize_item(
                {
                    "name": "Savings",
                    "kind": "savings",
                    "amount": 999,
                    "automatic_savings": True,
                }
            ),
        ]
        summary = model.calculate_month(
            month,
            settings={
                "automatic_savings_enabled": True,
                "savings_target_threshold": 45,
                "savings_floor_threshold": 40,
            },
            today=date(2026, 9, 1),
        )
        savings = month["items"][1]
        self.assertEqual(summary["effective_amounts"][savings["id"]], 150)
        self.assertEqual(summary["daily_allowance"], 45)

    def test_rag_uses_the_displayed_daily_allowance_at_threshold(self) -> None:
        month = model.make_month("2027-03")
        month["account_balance"] = 2207.03
        month["items"] = [
            model.normalize_item(
                {
                    "name": "Savings",
                    "kind": "savings",
                    "amount": 800,
                }
            )
        ]

        summary = model.calculate_month(
            month,
            settings={
                "daily_green_threshold": 45,
                "daily_yellow_threshold": 40,
                "savings_target_threshold": 45,
                "savings_floor_threshold": 40,
            },
            today=date(2026, 8, 31),
        )

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

    def test_copy_month_skips_event_specific_care_leave_data(self) -> None:
        source = model.make_month("2026-09")
        source["items"] = [
            model.normalize_item(
                {
                    "name": "Child-care sick leave",
                    "kind": "expense",
                    "amount": 0,
                    "expense_type": "child_care_leave",
                    "care_leave": {
                        "linked_income_item_id": "salary",
                        "work_month": "2026-09",
                        "income_month": "2026-10",
                        "periods": [
                            {"id": "period", "start": "2026-09-05", "end": "2026-09-06"}
                        ],
                        "benefit_basis_mode": "estimated_hourly",
                    },
                }
            ),
            model.normalize_item(
                {
                    "name": "Tervisekassa benefit",
                    "kind": "income",
                    "amount": 100,
                    "generated_type": "tervisekassa_care_benefit",
                    "generated": {"source_care_item_id": "care", "source_period_id": "period"},
                }
            ),
        ]

        copied = model.copy_month_data(source, "2026-09", "2027-09")

        self.assertEqual(copied["items"], [])

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

    def test_review_flag_defaults_false_and_can_be_imported(self) -> None:
        normal = model.normalize_item(
            {"name": "Water", "kind": "expense", "amount": 50}
        )
        review = model.normalize_item(
            {
                "name": "Insurance",
                "kind": "expense",
                "amount": 100,
                "needs_review": True,
            }
        )
        self.assertFalse(normal["needs_review"])
        self.assertTrue(review["needs_review"])

    def test_due_day_is_clamped(self) -> None:
        self.assertEqual(model.due_date("2027-02", 31), date(2027, 2, 28))

    def test_assigned_item_defaults_to_nine_and_requires_due_day(self) -> None:
        item = model.normalize_item(
            {
                "name": "Water",
                "kind": "expense",
                "amount": 42,
                "due_day": 15,
                "assignee_user_id": "user-1",
            }
        )

        self.assertEqual(item["assignee_user_id"], "user-1")
        self.assertEqual(item["reminder_time"], "09:00")
        with self.assertRaisesRegex(
            model.BudgetValidationError, "Assigned items require a due day"
        ):
            model.normalize_item(
                {
                    "name": "Water",
                    "kind": "expense",
                    "amount": 42,
                    "assignee_user_id": "user-1",
                }
            )

    def test_reminder_time_is_validated_and_cleared_without_assignee(self) -> None:
        unassigned = model.normalize_item(
            {
                "name": "Water",
                "kind": "expense",
                "amount": 42,
                "due_day": 15,
                "reminder_time": "14:30",
            }
        )
        self.assertIsNone(unassigned["reminder_time"])
        with self.assertRaisesRegex(
            model.BudgetValidationError, "Reminder time must use HH:MM"
        ):
            model.normalize_item(
                {
                    "name": "Water",
                    "kind": "expense",
                    "amount": 42,
                    "due_day": 15,
                    "assignee_user_id": "user-1",
                    "reminder_time": "25:00",
                }
            )

    def test_calendar_titles_use_signed_amounts(self) -> None:
        self.assertEqual(
            model.event_summary(
                {"name": "Apple iCloud", "kind": "expense", "amount": 9.99}
            ),
            "Apple iCloud -€9.99",
        )
        self.assertEqual(
            model.event_summary(
                {"name": "Валя", "kind": "income", "amount": 1873.24}
            ),
            "Валя +€1873.24",
        )

    def test_reminders_repeat_hourly_on_due_day_until_completed(self) -> None:
        data = model.empty_data()
        month = model.make_month("2026-09")
        item = model.normalize_item(
            {
                "name": "Water",
                "kind": "expense",
                "amount": 42,
                "due_day": 3,
                "assignee_user_id": "user-1",
                "reminder_time": "09:30",
            }
        )
        month["items"].append(item)
        data["months"]["2026-09"] = month

        self.assertEqual(
            [
                row["uid"]
                for row in model.reminder_rows(
                    data, datetime(2026, 9, 3, 9, 30)
                )
            ],
            [item["id"]],
        )
        self.assertEqual(
            [
                row["uid"]
                for row in model.reminder_rows(
                    data, datetime(2026, 9, 3, 21, 30)
                )
            ],
            [item["id"]],
        )
        self.assertEqual(
            model.reminder_rows(data, datetime(2026, 9, 3, 10, 0)), []
        )
        item["status"] = "paid"
        self.assertEqual(
            model.reminder_rows(data, datetime(2026, 9, 3, 22, 30)), []
        )

    def test_portable_export_round_trip(self) -> None:
        data = model.empty_data()
        data["settings"]["cycle_end_day"] = 5
        data["settings"]["daily_green_threshold"] = 52
        data["settings"]["automatic_savings_enabled"] = True
        month = model.make_month("2026-09", cycle_end_day=5)
        month["account_balance"] = 1234.56
        month["items"] = [
            model.normalize_item(
                {
                    "name": "Water",
                    "kind": "expense",
                    "amount": 42.5,
                    "needs_review": True,
                    "special": True,
                    "special_label": "Annual renewal",
                }
            ),
            model.normalize_item(
                {
                    "name": "Savings",
                    "kind": "savings",
                    "amount": 0,
                    "automatic_savings": True,
                }
            ),
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
        self.assertTrue(imported["settings"]["automatic_savings_enabled"])
        self.assertEqual(imported["months"]["2026-09"]["account_balance"], 1234.56)
        self.assertEqual(imported["months"]["2026-09"]["items"][0]["name"], "Water")
        self.assertTrue(
            imported["months"]["2026-09"]["items"][0]["needs_review"]
        )
        self.assertTrue(
            imported["months"]["2026-09"]["items"][1]["automatic_savings"]
        )

    def test_portable_export_preserves_hourly_income_configuration(self) -> None:
        data = model.empty_data()
        month = model.make_month("2026-08")
        calculation = payroll.calculate_estonian_payroll(
            {
                "mode": "estonian_hourly",
                "hourly_gross": 14,
                "working_hours_mode": "automatic",
                "working_hours": 160,
                "working_days": 20,
                "calendar_source": "nager_date",
                "apply_social_tax_minimum": True,
                "apply_tax_free_income": True,
                "tax_free_income": 700,
                "employee_unemployment": True,
                "employer_unemployment": True,
                "funded_pension_rate": 0,
            },
            payment_year=2026,
        )
        month["items"] = [
            model.normalize_item(
                {
                    "name": "Hourly salary",
                    "kind": "income",
                    "amount": calculation["net_income"],
                    "income_calculation": calculation,
                }
            )
        ]
        data["months"]["2026-08"] = month

        imported = model.normalize_import_document(
            model.export_data_document(data)
        )
        restored = imported["months"]["2026-08"]["items"][0]

        self.assertEqual(restored["amount"], 1873.24)
        self.assertEqual(restored["income_calculation"]["hourly_gross"], 14)
        self.assertEqual(restored["income_calculation"]["working_hours"], 160)
        self.assertEqual(
            restored["income_calculation"]["calendar_source"], "nager_date"
        )

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


class BudgetReminderTests(unittest.IsolatedAsyncioTestCase):

    async def test_coordinator_targets_user_and_deduplicates_each_minute(self) -> None:
        data = model.empty_data()
        month = model.make_month("2026-09")
        item = model.normalize_item(
            {
                "name": "Apple iCloud",
                "kind": "expense",
                "amount": 9.99,
                "due_day": 3,
                "assignee_user_id": "user-1",
                "reminder_time": "09:00",
            }
        )
        month["items"].append(item)
        data["months"]["2026-09"] = month

        class FakeServices:
            def __init__(self) -> None:
                self.calls = []

            async def async_call(self, *args, **kwargs) -> None:
                self.calls.append((args, kwargs))

        services = FakeServices()
        hass = types.SimpleNamespace(services=services)
        manager = types.SimpleNamespace(data=data)
        coordinator = notification_module.BudgetReminderCoordinator(hass, manager)
        original_targets = notification_module.mobile_notify_targets
        notification_module.mobile_notify_targets = (
            lambda _hass: {"user-1": ["notify.phone", "notify.tablet"]}
        )
        try:
            now = datetime(2026, 9, 3, 9, 0)
            await coordinator._async_check(now)
            await coordinator._async_check(now)
            await coordinator._async_check(datetime(2026, 9, 3, 10, 0))
            item["status"] = "paid"
            await coordinator._async_check(datetime(2026, 9, 3, 11, 0))
        finally:
            notification_module.mobile_notify_targets = original_targets

        self.assertEqual(len(services.calls), 2)
        args, kwargs = services.calls[0]
        self.assertEqual(args[:2], ("notify", "send_message"))
        self.assertIn("Apple iCloud -€9.99", args[2]["message"])
        self.assertEqual(
            kwargs["target"]["entity_id"], ["notify.phone", "notify.tablet"]
        )
        self.assertFalse(kwargs["blocking"])


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

    async def test_recurring_hourly_income_uses_each_months_working_hours(self) -> None:
        class FakeCalendar:
            async def async_month(self, month_key):
                hours = {"2026-08": 160, "2026-09": 176}[month_key]
                return {
                    "working_days": hours // 8,
                    "working_hours": hours,
                    "calendar_source": "test",
                }

        self.manager._estonian_calendar = FakeCalendar()
        self.manager.data["months"]["2026-08"] = model.make_month("2026-08")
        await self.manager.async_upsert_item(
            "2026-08",
            {
                "name": "Hourly salary",
                "kind": "income",
                "amount": 0,
                "recurrence": "monthly",
                "recurrence_end": "2026-09-30",
                "income_calculation": {
                    "mode": "estonian_hourly",
                    "hourly_gross": 14,
                    "working_hours_mode": "automatic",
                    "apply_social_tax_minimum": True,
                    "apply_tax_free_income": True,
                    "tax_free_income": 700,
                    "employee_unemployment": True,
                    "employer_unemployment": True,
                    "funded_pension_rate": 0,
                },
            },
        )

        august = self.manager.data["months"]["2026-08"]["items"][0]
        september = self.manager.data["months"]["2026-09"]["items"][0]
        self.assertEqual(august["income_calculation"]["working_hours"], 160)
        self.assertEqual(september["income_calculation"]["working_hours"], 176)
        self.assertEqual(august["amount"], 1873.24)
        self.assertEqual(september["amount"], 2045.17)

    async def test_hourly_income_can_use_previous_months_working_hours(self) -> None:
        class FakeCalendar:
            async def async_month(self, month_key):
                self.requested_month = month_key
                return {
                    "working_days": 20,
                    "working_hours": 160,
                    "calendar_source": "test",
                }

        fake_calendar = FakeCalendar()
        self.manager._estonian_calendar = fake_calendar
        created = await self.manager.async_upsert_item(
            "2026-09",
            {
                "name": "Salary paid afterward",
                "kind": "income",
                "amount": 0,
                "recurrence": "single",
                "income_calculation": {
                    "mode": "estonian_hourly",
                    "hourly_gross": 14,
                    "working_hours_mode": "automatic",
                    "work_period": "previous_month",
                    "funded_pension_joined": False,
                    "funded_pension_rate": 6,
                },
            },
        )

        self.assertEqual(fake_calendar.requested_month, "2026-08")
        self.assertEqual(created["income_calculation"]["working_time_month"], "2026-08")
        self.assertEqual(created["income_calculation"]["funded_pension_rate"], 0)
        self.assertEqual(created["amount"], 1873.24)

    async def test_care_leave_adjusts_following_salary_and_generates_benefit(self) -> None:
        class FakeCalendar:
            async def async_month(self, month_key):
                return {
                    "month": month_key,
                    "working_days": 22,
                    "working_hours": 176,
                    "public_holidays": [],
                    "shortened_workdays": [],
                    "calendar_source": "test",
                }

        self.manager._estonian_calendar = FakeCalendar()
        self.manager.data["months"]["2026-10"] = model.make_month("2026-10")
        salary = await self.manager.async_upsert_item(
            "2026-10",
            {
                "name": "Hourly salary",
                "kind": "income",
                "amount": 0,
                "recurrence": "single",
                "income_calculation": {
                    "mode": "estonian_hourly",
                    "hourly_gross": 14,
                    "working_hours_mode": "automatic",
                    "work_period": "previous_month",
                    "funded_pension_joined": False,
                    "funded_pension_rate": 0,
                },
            },
        )
        baseline_salary = salary["amount"]
        care_item = await self.manager.async_upsert_item(
            "2026-09",
            {
                "name": "Child-care sick leave",
                "kind": "expense",
                "amount": 0,
                "recurrence": "single",
                "expense_type": "child_care_leave",
                "care_leave": {
                    "linked_income_item_id": salary["id"],
                    "linked_income_name": salary["name"],
                    "work_month": "2026-09",
                    "income_month": "2026-10",
                    "periods": [],
                    "benefit_basis_mode": "actual_previous_year_income",
                    "actual_previous_year_income": 36500,
                },
            },
        )

        weekend = await self.manager.async_upsert_care_leave_period(
            "2026-09",
            care_item["id"],
            {"start": "2026-09-05", "end": "2026-09-06"},
        )
        october_items = self.manager.data["months"]["2026-10"]["items"]
        adjusted_salary = next(item for item in october_items if item["id"] == salary["id"])
        benefits = [item for item in october_items if item.get("generated_type")]
        self.assertEqual(adjusted_salary["amount"], baseline_salary)
        self.assertEqual(len(benefits), 1)
        self.assertEqual(benefits[0]["amount"], 124.8)
        self.assertEqual(benefits[0]["name"], "Tervisekassa care benefit")

        weekday = await self.manager.async_upsert_care_leave_period(
            "2026-09",
            care_item["id"],
            {"start": "2026-09-07", "end": "2026-09-07"},
        )
        october_items = self.manager.data["months"]["2026-10"]["items"]
        adjusted_salary = next(item for item in october_items if item["id"] == salary["id"])
        benefits = [item for item in october_items if item.get("generated_type")]
        self.assertLess(adjusted_salary["amount"], baseline_salary)
        self.assertEqual(adjusted_salary["income_calculation"]["care_leave_hours"], 8)
        self.assertEqual(len(benefits), 2)

        await self.manager.async_delete_care_leave_period(
            "2026-09", care_item["id"], weekday["id"]
        )
        october_items = self.manager.data["months"]["2026-10"]["items"]
        restored_salary = next(item for item in october_items if item["id"] == salary["id"])
        benefits = [item for item in october_items if item.get("generated_type")]
        self.assertEqual(restored_salary["amount"], baseline_salary)
        self.assertEqual(len(benefits), 1)
        self.assertEqual(benefits[0]["generated"]["source_period_id"], weekend["id"])

    async def test_generated_care_benefit_cannot_be_edited_or_deleted_directly(self) -> None:
        generated = model.normalize_item(
            {
                "name": "Tervisekassa care benefit",
                "kind": "income",
                "amount": 100,
                "generated_type": "tervisekassa_care_benefit",
                "generated": {"source_care_item_id": "care", "source_period_id": "period"},
            }
        )
        self.manager.data["months"]["2026-09"]["items"].append(generated)

        with self.assertRaisesRegex(model.BudgetValidationError, "managed"):
            await self.manager.async_upsert_item("2026-09", {**generated, "amount": 120})
        with self.assertRaisesRegex(model.BudgetValidationError, "source care-leave period"):
            await self.manager.async_delete_item("2026-09", generated["id"])

    async def test_copied_hourly_income_uses_target_month_working_hours(self) -> None:
        class FakeCalendar:
            async def async_month(self, month_key):
                hours = {"2026-08": 160, "2026-10": 176}[month_key]
                return {
                    "working_days": hours // 8,
                    "working_hours": hours,
                    "calendar_source": "test",
                }

        self.manager._estonian_calendar = FakeCalendar()
        self.manager.data["months"]["2026-08"] = model.make_month("2026-08")
        await self.manager.async_upsert_item(
            "2026-08",
            {
                "name": "Hourly salary",
                "kind": "income",
                "amount": 0,
                "recurrence": "single",
                "income_calculation": {
                    "mode": "estonian_hourly",
                    "hourly_gross": 14,
                    "working_hours_mode": "automatic",
                    "apply_social_tax_minimum": True,
                    "apply_tax_free_income": True,
                    "tax_free_income": 700,
                    "employee_unemployment": True,
                    "employer_unemployment": True,
                    "funded_pension_rate": 0,
                },
            },
        )

        await self.manager.async_create_month(
            "2026-10", source="2026-08"
        )
        copied = self.manager.data["months"]["2026-10"]["items"][0]

        self.assertEqual(copied["income_calculation"]["working_hours"], 176)
        self.assertEqual(copied["amount"], 2045.17)

    async def test_estonian_calendar_provider_uses_public_api_response(self) -> None:
        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            async def json(self):
                return [
                    {
                        "date": "2026-08-20",
                        "countryCode": "EE",
                        "global": True,
                        "types": ["Public"],
                    }
                ]

        class FakeSession:
            def get(self, *_args, **_kwargs):
                return FakeResponse()

        original = calendar_module.async_get_clientsession
        calendar_module.async_get_clientsession = lambda _hass: FakeSession()
        try:
            provider = calendar_module.EstonianWorkingHoursProvider(object())
            result = await provider.async_month("2026-08")
        finally:
            calendar_module.async_get_clientsession = original

        self.assertEqual(result["calendar_source"], "nager_date")
        self.assertEqual(result["working_days"], 20)
        self.assertEqual(result["working_hours"], 160)

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

    async def test_item_review_flag_persists_until_full_edit_clears_it(self) -> None:
        created = await self.manager.async_upsert_item(
            "2026-09",
            {
                "name": "Water",
                "kind": "expense",
                "amount": 50,
                "recurrence": "single",
                "needs_review": True,
            },
        )
        self.assertTrue(created["needs_review"])
        updated = await self.manager.async_upsert_item(
            "2026-09", {**created, "amount": 55, "needs_review": False}
        )
        self.assertFalse(updated["needs_review"])
        self.assertEqual(updated["amount"], 55)

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

    async def test_enabling_automatic_savings_populates_every_month(self) -> None:
        self.manager.data["months"]["2026-10"] = model.make_month("2026-10")
        existing = model.normalize_item(
            {"name": "My savings plan", "kind": "savings", "amount": 350}
        )
        self.manager.data["months"]["2026-09"]["items"] = [existing]

        await self.manager.async_update_settings(
            {"automatic_savings_enabled": True}
        )

        for month in self.manager.data["months"].values():
            automatic = [
                item for item in month["items"] if item.get("automatic_savings")
            ]
            self.assertEqual(len(automatic), 1)
            self.assertEqual(automatic[0]["name"], "Savings")
            self.assertEqual(automatic[0]["amount"], 0)
            self.assertTrue(automatic[0]["dynamic"])

    async def test_automatic_savings_is_created_with_new_month(self) -> None:
        self.manager.data["settings"]["automatic_savings_enabled"] = True
        created = await self.manager.async_create_month("2026-10")

        savings = [item for item in created["items"] if item["kind"] == "savings"]
        self.assertEqual(len(savings), 1)
        self.assertTrue(savings[0]["automatic_savings"])

    async def test_enabling_automatic_savings_reuses_transferred_savings(self) -> None:
        month = self.manager.data["months"]["2026-09"]
        transferred = model.normalize_item(
            {
                "name": "Old savings",
                "kind": "savings",
                "amount": 300,
                "status": "paid",
            }
        )
        month["items"] = [transferred]

        await self.manager.async_update_settings(
            {"automatic_savings_enabled": True}
        )

        savings = [item for item in month["items"] if item["kind"] == "savings"]
        self.assertEqual(len(savings), 1)
        self.assertEqual(savings[0]["id"], transferred["id"])
        self.assertEqual(savings[0]["amount"], 300)
        self.assertEqual(savings[0]["status"], "paid")
        self.assertTrue(savings[0]["automatic_savings"])

    async def test_disabling_automatic_savings_freezes_calculated_amount(self) -> None:
        month = self.manager.data["months"]["2026-09"]
        month["payday"] = "2026-09-30"
        month["account_balance"] = 2000
        month["items"] = [
            model.normalize_item(
                {
                    "name": "Savings",
                    "kind": "savings",
                    "amount": 0,
                    "automatic_savings": True,
                }
            )
        ]
        self.manager.data["settings"]["automatic_savings_enabled"] = True
        self.manager.today = lambda: date(2026, 9, 1)

        await self.manager.async_update_settings(
            {"automatic_savings_enabled": False}
        )

        savings = month["items"][0]
        self.assertEqual(savings["amount"], 650)
        self.assertFalse(savings["automatic_savings"])
        self.assertFalse(savings["dynamic"])

    async def test_transferred_automatic_savings_stops_affecting_daily_money(self) -> None:
        month = self.manager.data["months"]["2026-09"]
        month["payday"] = "2026-09-30"
        month["account_balance"] = 2000
        savings = model.normalize_item(
            {
                "name": "Savings",
                "kind": "savings",
                "amount": 0,
                "automatic_savings": True,
            }
        )
        month["items"] = [savings]
        self.manager.data["settings"]["automatic_savings_enabled"] = True
        self.manager.today = lambda: date(2026, 9, 1)

        await self.manager.async_set_item_status("2026-09", savings["id"], "paid")
        self.assertEqual(savings["amount"], 650)
        paid_summary = model.calculate_month(
            month,
            settings=self.manager.data["settings"],
            today=date(2026, 9, 1),
        )
        self.assertEqual(paid_summary["planned_savings"], 0)
        self.assertEqual(paid_summary["daily_allowance"], 66.67)

        await self.manager.async_set_item_status(
            "2026-09", savings["id"], "pending"
        )
        self.assertEqual(savings["amount"], 0)
        reopened_summary = model.calculate_month(
            month,
            settings=self.manager.data["settings"],
            today=date(2026, 9, 1),
        )
        self.assertEqual(reopened_summary["planned_savings"], 650)
        self.assertEqual(reopened_summary["daily_allowance"], 45)

    async def test_automatic_savings_cannot_be_manually_created(self) -> None:
        self.manager.data["settings"]["automatic_savings_enabled"] = True
        with self.assertRaisesRegex(
            model.BudgetValidationError, "Turn off automatic savings"
        ):
            await self.manager.async_upsert_item(
                "2026-09",
                {"name": "Manual savings", "kind": "savings", "amount": 100},
            )

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
        self.assertFalse(migrated["needs_review"])
        self.assertIsNone(migrated["income_calculation"])

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

    async def test_snapshot_places_checked_items_after_open_items(self) -> None:
        month = self.manager.data["months"]["2026-09"]
        month["items"] = [
            model.normalize_item(
                {
                    "name": "Received first",
                    "kind": "income",
                    "amount": 10,
                    "status": "received",
                    "sort_order": 0,
                }
            ),
            model.normalize_item(
                {
                    "name": "Open second",
                    "kind": "income",
                    "amount": 20,
                    "status": "pending",
                    "sort_order": 1,
                }
            ),
            model.normalize_item(
                {
                    "name": "Paid first",
                    "kind": "expense",
                    "amount": 30,
                    "status": "paid",
                    "sort_order": 0,
                }
            ),
            model.normalize_item(
                {
                    "name": "Open second expense",
                    "kind": "expense",
                    "amount": 40,
                    "status": "pending",
                    "sort_order": 1,
                }
            ),
        ]

        items = self.manager.snapshot(2026)["months"]["2026-09"]["items"]
        self.assertEqual(
            [item["name"] for item in items],
            ["Open second", "Received first", "Open second expense", "Paid first"],
        )

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
