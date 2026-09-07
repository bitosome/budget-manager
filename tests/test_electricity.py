"""Electricity forecasting and budget integration regressions (synthetic data)."""
from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
import importlib
import sys
from types import ModuleType, SimpleNamespace
from contextlib import ExitStack
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_model as support

electricity = importlib.import_module("custom_components.budget_manager.electricity")
source = importlib.import_module("custom_components.budget_manager.electricity_source")


class ElectricityTests(unittest.TestCase):
    def setUp(self):
        self.settings = electricity.normalize_settings({"fees": [{"name": "Network", "amount": 10}, {"name": "Supplier", "amount": 5}],
            "fallback_monthly_kwh": 1000, "fallback_price": .2, "buffer_percent": 20})
        self.history = electricity.normalize_history([{"month": "2026-08", "kwh": 1000, "grid_cost": 200, "fixed_fees": 12}])
        self.today = date(2026, 9, 6)

    def test_previous_month_actual_has_no_buffer_or_new_fees(self):
        result = electricity.forecast("2026-09", self.settings, self.history, {}, {}, self.today)
        self.assertEqual(result["consumption_month"], "2026-08")
        self.assertEqual(result["amount"], 212)
        self.assertEqual(result["buffer"], 0)
        self.assertEqual(result["status"], "actual")
        self.history["2026-08"]["source"] = "recorder"
        self.assertEqual(electricity.forecast("2026-09", self.settings, self.history, {}, {}, self.today)["status"], "measured")

    def test_year_boundary_and_future_buffer_once(self):
        result = electricity.forecast("2027-01", self.settings, {}, {}, {}, self.today)
        self.assertEqual(result["consumption_month"], "2026-12")
        self.assertEqual(result["amount"], 255)

    def test_buffer_only_applies_to_unmeasured_remainder(self):
        live = {"month":"2026-09", "grid_cost":100,"kwh":500,"elapsed_days":15,"month_coverage":1}
        result = electricity.forecast("2026-10", self.settings, {}, {}, live, self.today)
        self.assertEqual(result["grid_cost"], 100)
        self.assertEqual(result["amount"], 235)
        self.assertEqual(result["buffer"], 20)

    def test_partial_data_not_treated_as_full_month(self):
        live={"month":"2026-09","grid_cost":100,"kwh":500,"elapsed_days":15,"month_coverage":.5}
        result=electricity.forecast("2026-10",self.settings,{}, {},live,self.today)
        self.assertEqual(result["amount"],255)
        self.assertEqual(result["grid_cost"],0)

    def test_no_data_is_explicit_not_free_electricity(self):
        settings=electricity.normalize_settings()
        self.assertEqual(electricity.forecast("2026-10",settings,{}, {},{},self.today)["status"],"missing")

    def test_fee_effective_months(self):
        settings=electricity.normalize_settings({"fees":[{"name":"Fee","amount":20,"from_month":"2026-10","to_month":"2026-12"}]})
        self.assertEqual(electricity.fixed_fees(settings,"2026-09"),0)
        self.assertEqual(electricity.fixed_fees(settings,"2026-12"),20)
        self.assertEqual(electricity.fixed_fees(settings,"2027-01"),0)

    def test_training_excludes_future_disabled_and_zero_usage(self):
        history=electricity.normalize_history([
            {"month":"2026-08","grid_cost":100,"kwh":1000},
            {"month":"2026-09","grid_cost":10000,"kwh":1000},
            {"month":"2026-07","grid_cost":10000,"kwh":1000,"enabled":False},
            {"month":"2026-06","grid_cost":10000,"kwh":0}])
        model=electricity.train(history,self.settings,"2026-09")
        self.assertEqual(model["samples"],1)
        self.assertAlmostEqual(model["unit_price"],.1)

    def test_recent_price_adapts_but_single_hour_does_not(self):
        model=electricity.train(self.history,self.settings,"2026-09")
        base=electricity.forecast("2026-11",self.settings,{},model,{},self.today)
        spike=electricity.forecast("2026-11",self.settings,{},model,{"recent_unit_price":.8,"recent_days":4},self.today)
        hourly=electricity.forecast("2026-11",self.settings,{},model,{"recent_unit_price":.8,"recent_days":.1},self.today)
        self.assertGreater(spike["amount"],base["amount"])
        self.assertEqual(hourly["amount"],base["amount"])

    def test_validation_rejects_nonfinite_duplicates_and_bad_intervals(self):
        for raw in ({"buffer_percent":float("nan")},{"history_months":3.5},{"fees":[{"name":"fee","amount":-1}]},{"learning_enabled":"no"}):
            with self.assertRaises(ValueError): electricity.normalize_settings(raw)
        with self.assertRaises(ValueError): electricity.normalize_history(list(self.history.values())*2)

    def test_walk_forward_metrics_and_local_model_size(self):
        rows=[{"month":electricity.shift_month("2024-01",i),"kwh":1000+i*3,"grid_cost":200+i,"fixed_fees":10} for i in range(24)]
        history=electricity.normalize_history(rows)
        model=electricity.train(history,self.settings,"2026-01")
        self.assertEqual(model["samples"],24)
        self.assertEqual(len(model["coefficients"]),3)
        self.assertEqual(len(model["price_coefficients"]),3)
        self.assertEqual(electricity.backtest(history,self.settings)["evaluated_months"],18)

    def test_statistics_dst_and_gaps(self):
        tz=ZoneInfo("Europe/Tallinn")
        start=datetime(2026,3,1,tzinfo=tz); end=datetime(2026,4,1,tzinfo=tz)
        hours=int((end.timestamp()-start.timestamp())/3600)
        self.assertEqual(hours,743)
        rows=[{"start":start.timestamp()+i*3600,"change":1,"sum":999999} for i in range(hours)]
        with patch.object(source.dt_util,"as_local",lambda d:d.astimezone(tz),create=True), patch.object(source.dt_util,"UTC",timezone.utc,create=True):
            observations,live=source.aggregate_statistics(rows,rows,end,self.settings)
            self.assertEqual(observations["2026-03"]["grid_cost"],743)
            observations,_=source.aggregate_statistics(rows[:-1],rows,end,self.settings)
            self.assertNotIn("2026-03",observations)


class RecorderReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_uses_stored_units_and_supports_legacy_metadata(self):
        tz = ZoneInfo("Europe/Tallinn")
        now = datetime(2026, 9, 1, tzinfo=tz)
        start = datetime(2026, 8, 1, tzinfo=tz)
        rows = [{"start": start.timestamp() + i * 3600, "change": 1} for i in range(744)]
        settings = electricity.normalize_settings({"cost_statistic_id": "sensor.cost", "energy_statistic_id": "sensor.energy"})
        for unit_field in ("statistics_unit_of_measurement", "unit_of_measurement"):
            with self.subTest(unit_field=unit_field):
                metadata = [{"statistic_id": "sensor.cost", unit_field: "EUR", "display_unit_of_measurement": "USD", "has_sum": True},
                    {"statistic_id": "sensor.energy", unit_field: "kWh", "display_unit_of_measurement": "Wh", "has_sum": True}]
                calls = []
                def list_ids(hass, statistic_ids=None, statistic_type=None):
                    if statistic_ids is not None and statistic_type is not None:
                        raise ValueError("Providing statistic_type is mutually exclusive of statistic_ids")
                    self.assertEqual(statistic_ids, {"sensor.cost", "sensor.energy"})
                    return metadata
                def statistics(*args): return {"sensor.cost": rows, "sensor.energy": rows}
                async def executor(fn, *args):
                    calls.append(fn)
                    return fn(*args)
                recorder = ModuleType("homeassistant.components.recorder")
                recorder.get_instance = lambda hass: SimpleNamespace(async_add_executor_job=executor)
                stats = ModuleType("homeassistant.components.recorder.statistics")
                stats.list_statistic_ids = list_ids
                stats.statistics_during_period = statistics
                with ExitStack() as stack:
                    stack.enter_context(patch.dict(sys.modules, {recorder.__name__:recorder, stats.__name__:stats}))
                    for name, value in {"now":lambda:now,"as_local":lambda dt:dt.astimezone(tz),"as_utc":lambda dt:dt.astimezone(timezone.utc),"UTC":timezone.utc}.items():
                        stack.enter_context(patch.object(source.dt_util, name, value, create=True))
                    observations, _, _ = await source.async_read_statistics(object(), settings, full=True)
                    self.assertEqual(observations["2026-08"]["grid_cost"], 744)
                    self.assertEqual(calls, [list_ids, statistics])
                    calls.clear()
                    metadata[1]["has_sum"] = False
                    rejected, _, warning = await source.async_read_statistics(object(), settings, full=True)
                    self.assertEqual(rejected, {})
                    self.assertIn("sum statistics", warning)
                    self.assertEqual(calls, [list_ids])


class ElectricityManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=support.manager_module.BudgetManager(object(),"electricity-test")
        self.manager.today=lambda:date(2026,9,6)
        self.manager.data["months"]["2026-09"]=support.model.make_month("2026-09")
        self.manager.data["settings"]["electricity"]=electricity.normalize_settings({"fallback_monthly_kwh":1000,"fallback_price":.2,"buffer_percent":10})

    async def test_record_bill_reconciles_without_payment_or_duplicate_fees(self):
        await self.manager.async_upsert_item("2026-09", {"name":"Electricity", "expense_type":"electricity", "amount":0})
        state = self.manager.data["electricity"]
        state["history"] = electricity.normalize_history([{"month":"2026-07", "kwh":900, "grid_cost":180}])
        state["observations"] = electricity.normalize_history([{"month":"2026-08", "kwh":1000, "grid_cost":200, "source":"recorder"}])
        state["ignored_months"] = ["2026-08"]
        item = self.manager.data["months"]["2026-09"]["items"][0]
        settings = deepcopy(self.manager.data["settings"])
        balance = self.manager.data["months"]["2026-09"]["account_balance"]
        bill = {"payment_month":"2026-09", "item_id":item["id"], "total":223.45, "kwh":1010, "fixed_fees":26.96}
        result = await self.manager.async_electricity_action("bill", bill)
        self.assertEqual(item["amount"], 223.45)
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["electricity"]["status"], "actual")
        self.assertEqual(item["electricity"]["buffer"], 0)
        self.assertEqual(result["history"]["2026-08"]["grid_cost"], 196.49)
        self.assertEqual(result["history"]["2026-07"]["grid_cost"], 180)
        self.assertEqual(result["model"]["samples"], 2)
        self.assertEqual(result["ignored_months"], [])
        self.assertEqual(self.manager.data["settings"], settings)
        self.assertEqual(self.manager.data["months"]["2026-09"]["account_balance"], balance)
        # Repeated corrections update one month, including after a Recorder refresh.
        await self.manager.async_electricity_action("bill", {**bill,"total":225})
        self.assertEqual(len(self.manager.data["electricity"]["history"]), 2)
        self.assertEqual(item["amount"], 225)
        self.manager.data["electricity"]["observations"]["2026-08"]["grid_cost"] = 201
        await self.manager._async_commit()
        self.assertEqual(item["amount"], 225)

    async def test_bill_validation_is_atomic_and_paid_items_are_protected(self):
        await self.manager.async_upsert_item("2026-09", {"name":"Electricity", "expense_type":"electricity", "amount":0, "recurrence":"monthly", "recurrence_end":"2026-12-31"})
        item = self.manager.data["months"]["2026-09"]["items"][0]
        bill = {"payment_month":"2026-09", "item_id":item["id"], "total":123, "kwh":500, "fixed_fees":12}
        for changes in ({"total":-1}, {"kwh":float("nan")}, {"enabled":"yes"}, {"fixed_fees":None}, {"item_id":"missing"}):
            before = deepcopy(self.manager.data)
            with self.assertRaises(support.model.BudgetValidationError):
                await self.manager.async_electricity_action("bill", {**bill, **changes})
            self.assertEqual(self.manager.data, before)
        future = self.manager.data["months"]["2026-10"]["items"][0]
        with self.assertRaisesRegex(support.model.BudgetValidationError, "month has ended"):
            await self.manager.async_electricity_action("bill", {**bill,"payment_month":"2026-10","item_id":future["id"]})
        await self.manager.async_set_item_status("2026-09",item["id"],"paid")
        with self.assertRaisesRegex(support.model.BudgetValidationError, "Reopen"):
            await self.manager.async_electricity_action("bill", bill)

    async def test_bill_respects_learning_pause_and_exclusion(self):
        await self.manager.async_upsert_item("2026-09", {"name":"Electricity", "expense_type":"electricity", "amount":0})
        item = self.manager.data["months"]["2026-09"]["items"][0]
        bill = {"payment_month":"2026-09", "item_id":item["id"], "total":123, "kwh":500, "fixed_fees":12}
        await self.manager.async_electricity_action("bill", bill)
        model = deepcopy(self.manager.data["electricity"]["model"])
        self.manager.data["settings"]["electricity"]["learning_enabled"] = False
        await self.manager.async_electricity_action("bill", {**bill, "total":200})
        self.assertEqual(self.manager.data["electricity"]["model"], model)
        self.assertEqual(item["amount"], 200)
        self.manager.data["settings"]["electricity"]["learning_enabled"] = True
        await self.manager.async_electricity_action("bill", {**bill, "enabled":False})
        self.assertEqual(self.manager.data["electricity"]["model"]["samples"], 0)
        self.assertEqual(item["amount"], 123)

    async def test_smart_recurrence_paid_freeze_and_export(self):
        await self.manager.async_upsert_item("2026-09",{"name":"Electricity","expense_type":"electricity","amount":999,"recurrence":"monthly","recurrence_end":"2026-12-31"})
        item=self.manager.data["months"]["2026-10"]["items"][0]
        self.assertEqual(item["amount"],220)
        await self.manager.async_set_item_status("2026-10",item["id"],"paid")
        await self.manager.async_update_settings({"electricity":{**self.manager.data["settings"]["electricity"],"buffer_percent":50}})
        self.assertEqual(item["amount"],220)
        self.assertEqual(self.manager.data["months"]["2026-11"]["items"][0]["amount"],300)
        await self.manager.async_import_data(self.manager.export_data())
        saved=self.manager.data["months"]["2026-10"]["items"][0]
        self.assertEqual(saved["status"],"paid")
        self.assertEqual(saved["amount"],220)
        await self.manager.async_set_item_status("2026-10",saved["id"],"pending")
        self.assertEqual(saved["amount"],300)

    async def test_history_import_actual_training_pause_reset(self):
        document={"format":electricity.HISTORY_FORMAT,"version":1,"records":[{"month":"2026-08","grid_cost":100,"kwh":1000,"fixed_fees":15}]}
        await self.manager.async_electricity_action("history",document)
        await self.manager.async_upsert_item("2026-09",{"name":"Electricity","expense_type":"electricity","amount":0})
        self.assertEqual(self.manager.data["months"]["2026-09"]["items"][0]["amount"],115)
        await self.manager.async_update_settings({"electricity":{**self.manager.data["settings"]["electricity"],"learning_enabled":False}})
        trained=deepcopy(self.manager.data["electricity"]["model"])
        document["records"][0]["grid_cost"]=500
        await self.manager.async_electricity_action("history",document)
        self.assertEqual(self.manager.data["electricity"]["model"],trained)
        await self.manager.async_electricity_action("retrain")
        self.assertAlmostEqual(self.manager.data["electricity"]["model"]["unit_price"],.5)
        await self.manager.async_electricity_action("reset")
        self.assertEqual(self.manager.data["electricity"]["model"]["samples"],0)
        self.assertTrue(self.manager.data["electricity"]["history"])

    async def test_history_validation_is_atomic_and_rejects_partial_month(self):
        before=deepcopy(self.manager.data)
        with self.assertRaises(support.model.BudgetValidationError):
            await self.manager.async_electricity_action("history",{"format":electricity.HISTORY_FORMAT,"version":1,"records":[{"month":"2026-09","grid_cost":100,"kwh":1000}]})
        self.assertEqual(self.manager.data,before)

    async def test_missing_data_cannot_be_marked_paid(self):
        self.manager.data["settings"]["electricity"]=electricity.normalize_settings()
        await self.manager.async_upsert_item("2026-09",{"name":"Electricity","expense_type":"electricity","amount":0})
        item=self.manager.data["months"]["2026-09"]["items"][0]
        with self.assertRaises(support.model.BudgetValidationError):
            await self.manager.async_set_item_status("2026-09",item["id"],"paid")
        with self.assertRaises(support.model.BudgetValidationError):
            await self.manager.async_set_item_status("2026-09",item["id"],"received")
        await self.manager.async_update_settings({"automatic_savings_enabled": True})
        month = self.manager.data["months"]["2026-09"]
        month["account_balance"] = 5000
        summary = support.model.calculate_month(month, settings=self.manager.data["settings"], today=self.manager.today())
        self.assertTrue(summary["incomplete"])
        self.assertEqual(summary["dynamic_savings"], 0)

    async def test_removed_recorder_month_stays_removed(self):
        state = self.manager.data["electricity"]
        state["observations"] = electricity.normalize_history([{"month":"2026-08","kwh":1000,"grid_cost":200,"source":"recorder"}])
        await self.manager.async_electricity_action("history", {"format":electricity.HISTORY_FORMAT,"version":1,"records":[]})
        self.assertEqual(electricity.combined_history(state), {})
        self.assertEqual(electricity.combined_history(electricity.normalize_state(state)), {})
        await self.manager.async_electricity_action("history", {"format":electricity.HISTORY_FORMAT,"version":1,"records":[{"month":"2026-08","kwh":1000,"grid_cost":210}]})
        self.assertEqual(electricity.combined_history(state)["2026-08"]["grid_cost"], 210)

    async def test_training_status_is_real_and_unrelated_commits_do_not_retrain(self):
        empty = await self.manager.async_electricity_action("retrain")
        self.assertEqual(empty["training"]["status"], "no_data")
        self.assertEqual(empty["training"]["samples"], 0)
        self.assertIn("No usable", empty["training"]["message"])
        self.assertIsNotNone(empty["training"]["finished_at"])
        self.assertGreaterEqual(empty["training"]["duration_ms"], 0)
        await self.manager.async_electricity_action("history", {"format":electricity.HISTORY_FORMAT,"version":1,"records":[{"month":"2026-08","kwh":1000,"grid_cost":210}]})
        trained = deepcopy(self.manager.data["electricity"]["training"])
        self.assertEqual(trained["status"], "trained")
        self.assertEqual(trained["samples"], 1)
        await self.manager._async_commit()
        self.assertEqual(self.manager.data["electricity"]["training"], trained)
        reset = await self.manager.async_electricity_action("reset")
        self.assertEqual(reset["training"]["status"], "reset")

    async def test_refresh_reports_missing_sources_and_recorder_errors(self):
        result = await self.manager.async_electricity_action("refresh")
        self.assertEqual(result["refresh"]["status"], "not_configured")
        self.assertIn("sources", result["refresh"]["message"])
        self.manager.data["settings"]["electricity"].update(cost_statistic_id="sensor.cost",energy_statistic_id="sensor.energy")
        with self.assertLogs(support.manager_module._LOGGER, level="ERROR"), patch.object(source, "async_read_statistics", side_effect=RuntimeError("unavailable")):
            failed = await self.manager.async_electricity_action("refresh")
        self.assertEqual(failed["refresh"]["status"], "error")
        with patch.object(source, "async_read_statistics", return_value=({}, {}, "No complete paired hours")):
            warning = await self.manager.async_electricity_action("refresh")
        self.assertEqual(warning["refresh"]["status"], "warning")
        self.assertIn("No complete paired hours", warning["refresh"]["message"])


if __name__ == "__main__": unittest.main()
