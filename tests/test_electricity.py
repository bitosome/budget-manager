"""Electricity forecasting and budget integration regressions (synthetic data)."""
from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
import importlib
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


class ElectricityManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=support.manager_module.BudgetManager(object(),"electricity-test")
        self.manager.today=lambda:date(2026,9,6)
        self.manager.data["months"]["2026-09"]=support.model.make_month("2026-09")
        self.manager.data["settings"]["electricity"]=electricity.normalize_settings({"fallback_monthly_kwh":1000,"fallback_price":.2,"buffer_percent":10})

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


if __name__ == "__main__": unittest.main()
