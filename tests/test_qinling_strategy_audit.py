from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from simu.qinling_strategy_audit import (
    STATUS_FAIL,
    STATUS_PASS,
    _optimization_balance_check,
    _parallel_converter_check,
    build_inventory,
    load_qinling_snapshot,
    resolve_qinling_model_dir,
    run_audit,
    write_audit_outputs,
)
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


class QinlingStrategyAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_qinling_snapshot(ROOT)
        cls.inventory = build_inventory(cls.snapshot)

    def test_qinling_inventory_uses_stable_parameter_relations_and_topology(self):
        self.assertEqual(len(self.inventory.by_technology("wind")), 11)
        self.assertEqual(len(self.inventory.by_technology("pv")), 4)
        self.assertEqual(len(self.inventory.by_technology("storage")), 8)
        self.assertEqual(len(self.inventory.by_technology("diesel")), 4)
        self.assertEqual(len(self.inventory.grid_converters), 2)

        by_key = {resource.key: resource for resource in self.inventory.resources}
        for resource in self.inventory.by_technology("wind"):
            raw = resource.device["raw"]
            expected = 50.0 if resource.source_index == "24" else 10.1
            self.assertEqual(float(raw["p_min"]), 0.0)
            self.assertEqual(float(raw["p_max"]), expected)
        for resource in self.inventory.by_technology("pv"):
            raw = resource.device["raw"]
            expected = 20.0 if resource.side == "AC" else 50.0
            self.assertEqual(float(raw["p_min"]), 0.0)
            self.assertEqual(float(raw["p_max"]), expected)
            self.assertEqual(float(resource.parameter["reference_irradiance"]), 1000.0)
        for resource in self.inventory.by_technology("storage"):
            raw = resource.device["raw"]
            expected = 100.0 if resource.side == "AC" else 60.0
            self.assertEqual(float(raw["p_min"]), -expected)
            self.assertEqual(float(raw["p_max"]), expected)
        for resource in self.inventory.by_technology("diesel"):
            raw = resource.device["raw"]
            self.assertEqual(float(raw["p_min"]), 70.0)
            self.assertEqual(float(raw["p_max"]), 300.0)
            self.assertEqual(float(resource.parameter["rated_power"]), 300.0)
            self.assertEqual(float(resource.parameter["p_min"]), 70.0)
            self.assertEqual(float(resource.parameter["p_max"]), 300.0)
        self.assertEqual(len(by_key), 27)

    def test_service_snapshot_includes_diesel_parameter_relations(self):
        model_dir = resolve_qinling_model_dir(ROOT)
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = PolarMicrogridSimulator(
                model_dir,
                runtime_dir,
                kernel=lambda _config: None,
                model_id="qinling-test",
            )
            parameters = service.snapshot()["device_parameters"]

        self.assertEqual(len(parameters["ACDieselGen"]), 4)
        self.assertEqual(parameters["ACDieselGen"][0]["idx_acgenerator"], 27)

    def test_inventory_classification_does_not_depend_on_raw_dev_type(self):
        snapshot = copy.deepcopy(self.snapshot)
        for device in snapshot["devices"]:
            device["dev_type"] = "opaque-device-token"
            if isinstance(device.get("raw"), dict):
                device["raw"]["dev_type"] = "opaque-device-token"

        inventory = build_inventory(snapshot)

        self.assertEqual(len(inventory.by_technology("wind")), 11)
        self.assertEqual(len(inventory.by_technology("pv")), 4)
        self.assertEqual(len(inventory.by_technology("storage")), 8)
        self.assertEqual(len(inventory.by_technology("diesel")), 4)
        self.assertEqual(len(inventory.grid_converters), 2)

    def test_small_random_audit_is_deterministic_balanced_and_passes(self):
        first = run_audit(ROOT, count=8, seed=20260809)
        second = run_audit(ROOT, count=8, seed=20260809)

        self.assertEqual(
            [item["categories"] for item in first["scenarios"]],
            [item["categories"] for item in second["scenarios"]],
        )
        self.assertEqual(first["summary"]["overall_pass"], 8)
        self.assertEqual(first["summary"]["overall_fail"], 0)
        self.assertEqual(first["summary"]["operational_summary"]["warning_scenarios"], 0)
        for scenario in first["scenarios"]:
            self.assertLess(abs(scenario["values"]["initial_ac_balance_residual_kw"]), 1e-7)
            self.assertLess(abs(scenario["values"]["initial_dc_balance_residual_kw"]), 1e-7)
            self.assertTrue(scenario["optimization"]["all_islands_successful"])
            self.assertTrue(scenario["data_quality"]["dispatchAllowed"])
            self.assertTrue(
                all(
                    check["status"] != STATUS_FAIL
                    for check in scenario["checks"].values()
                )
            )

    def test_parallel_converter_checker_rejects_non_proportional_targets(self):
        rows = [
            {
                "category": "交直流变流器",
                "online": True,
                "dev_name": "converter-a",
                "dcTransferGroupId": "DC:1",
                "transferCapacityKw": 300.0,
                "commandKw": 100.0,
            },
            {
                "category": "交直流变流器",
                "online": True,
                "dev_name": "converter-b",
                "dcTransferGroupId": "DC:1",
                "transferCapacityKw": 300.0,
                "commandKw": 80.0,
            },
        ]

        result = _parallel_converter_check(rows)

        self.assertEqual(result.status, STATUS_FAIL)
        rows[1]["commandKw"] = 100.0
        self.assertEqual(_parallel_converter_check(rows).status, STATUS_PASS)

    def test_optimization_balance_checker_rejects_slack_solution(self):
        result = _optimization_balance_check(
            {"metrics": {"optimizationMaxBalanceResidualKw": 12.5}}
        )

        self.assertEqual(result.status, STATUS_FAIL)
        self.assertIn("12.500", result.detail)

    def test_optimization_balance_checker_accepts_minimum_slack_with_warning(self):
        result = _optimization_balance_check(
            {
                "metrics": {
                    "optimizationMaxBalanceResidualKw": 12.5,
                    "optimizationIslands": [
                        {
                            "status": "optimal_safety_override_with_balance_slack",
                            "maxBalanceDeltaKw": 12.5,
                        }
                    ],
                },
                "warnings": [
                    "优化岛x在设备物理与安全边界内无法精确配平，"
                    "按最小功率平衡松弛继续形成策略"
                ],
            }
        )

        self.assertEqual(result.status, STATUS_PASS)
        self.assertIn("12.500", result.detail)

    def test_output_names_and_csv_columns_follow_actual_scenario_count(self):
        result = run_audit(ROOT, count=3, seed=20260809)

        with tempfile.TemporaryDirectory() as output_dir:
            paths = write_audit_outputs(result, Path(output_dir))
            self.assertEqual(paths["json"].name, "qinling_strategy_audit_3.json")
            self.assertEqual(paths["csv"].name, "qinling_strategy_audit_3.csv")
            self.assertEqual(paths["report"].name, "qinling_strategy_audit_3.md")
            csv_header = paths["csv"].read_text(encoding="utf-8-sig").splitlines()[0]

        self.assertIn("ac_renewable_power_kw", csv_header)
        self.assertIn("dc_renewable_power_kw", csv_header)
        self.assertIn("converter_p_ac_kw", csv_header)
        self.assertIn("initial_ac_balance_residual_kw", csv_header)
        self.assertIn("initial_dc_balance_residual_kw", csv_header)


if __name__ == "__main__":
    unittest.main()
