from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PowerFlowLogSummaryTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        return workspace, service

    def test_power_flow_log_uses_category_summary_instead_of_device_details(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service._append_power_flow_log(
            {"solver_info": "iter=2", "updated": 8, "missing": 0, "overlay_updates": 0},
            {
                "real": [
                    {"dev_type": "DCACConverter", "dev_name": "wt01_rect", "meas_type": "P_AC", "value": 8.0},
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": 8.0},
                    {"dev_type": "DCDCConverter", "dev_name": "pv01_dcdc", "meas_type": "P_TO", "value": 20.0},
                    {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "meas_type": "P_GEN", "value": 20.0},
                    {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "meas_type": "P_GEN", "value": 30.0},
                    {"dev_type": "ACLoad", "dev_name": "load_ac_1", "meas_type": "P_LOAD", "value": 90.0},
                    {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "P", "value": -5.0},
                    {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "SOC", "value": 0.55},
                    {"dev_type": "ACNode", "dev_name": "ac_bus", "meas_type": "V", "value": 380.0},
                    {"dev_type": "DCDCConverter", "dev_name": "ess01_dcdc", "meas_type": "P_FROM", "value": -5.0},
                ],
            },
            minute=0,
            absolute_minute=0,
            clock_advance=1,
            period_seconds=60.0,
            command_response_lines=["控制响应 本轮无新增学员台控制指令"],
        )

        self.assertEqual([item["type"] for item in service.runtime_logs[-2:]], ["控制响应", "潮流计算"])
        control_detail = service.runtime_logs[-2]["detail"]
        detail = service.runtime_logs[-1]["detail"]
        control_text = "\n".join(control_detail)
        text = "\n".join(detail)

        self.assertIn("风力发电总功率 8 kW", text)
        self.assertIn("光伏发电总功率 20 kW", text)
        self.assertIn("柴油发电总功率 30 kW", text)
        self.assertIn("负荷用电总功率 90 kW", text)
        self.assertIn("储能发电总功率 0 kW", text)
        self.assertIn("储能充电总功率 5 kW", text)
        self.assertIn("储能SOC 平均 55%", text)
        self.assertIn("功率平衡 电源发电总功率 58 kW", text)
        self.assertIn("用电及充电总功率 95 kW", text)
        self.assertIn("功率差额 -37 kW", text)
        self.assertIn("控制响应 本轮无新增学员台控制指令", control_text)
        self.assertIn("输入边界", control_text)
        self.assertIn("设值", control_text)
        self.assertNotIn("计算摘要", control_text)
        self.assertNotIn("SetValue 19 条：", control_text)
        self.assertNotIn("RunStat 投入", control_text)
        self.assertNotIn("控制响应", text)
        self.assertEqual(len(detail), 5)
        self.assertNotIn("DCACConverter.wt01_rect:", text)
        self.assertNotIn("ACNode.ac_bus:", text)
        self.assertIn("风力发电总功率 8 kW（1 台）", text)
        self.assertNotIn("风力发电总功率 16 kW", text)
        self.assertIn("新能源限值", control_text)

    def test_power_flow_summary_preserves_signed_realtime_measurements(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        lines = service._power_flow_summary_lines(
            [
                {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": -8.0},
                {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "meas_type": "P_GEN", "value": -20.0},
                {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "meas_type": "P_GEN", "value": -30.0},
                {"dev_type": "ACLoad", "dev_name": "load_ac_1", "meas_type": "P_LOAD", "value": -90.0},
                {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "P", "value": -5.0},
            ]
        )
        text = "\n".join(lines)

        self.assertIn("风力发电总功率 -8 kW", text)
        self.assertIn("光伏发电总功率 -20 kW", text)
        self.assertIn("柴油发电总功率 -30 kW", text)
        self.assertIn("负荷用电总功率 -90 kW", text)
        self.assertIn("储能充电总功率 5 kW", text)

    def test_converter_summary_normalizes_both_model_blocks_to_p_dc(self):
        import simu_loop

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.source_model_book.data["ACDCConverter"] = simu_loop.EBook(
            {
                "ACDCConverter": [
                    {
                        "idx": 1,
                        "name": "grid_inv_acp",
                        "dev_type": "grid-dcac-converter",
                        "ac_node": 5,
                        "dc_node": 7,
                        "control_type": "ACP",
                        "p_ac_set": 8.0,
                        "run_stat": 1,
                    }
                ]
            }
        ).data["ACDCConverter"]
        service._internal_power_converter_keys_cache = None

        summary = service._power_flow_summary(
            [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "wt01_rect",
                    "meas_type": "P_AC",
                    "value": 8.0,
                    "valid": 1,
                },
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_AC",
                    "value": 12.5,
                    "valid": 1,
                },
                {
                    "dev_type": "ACDCConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_AC",
                    "value": 8.0,
                    "valid": 1,
                },
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_DC",
                    "value": 99.0,
                    "valid": 1,
                },
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_invalid",
                    "meas_type": "P_AC",
                    "value": 100.0,
                    "valid": 1,
                },
            ]
        )

        converter_group = summary["flowGroups"]["acdcConverter"]
        self.assertEqual(converter_group["power"], -20.5)
        self.assertEqual(converter_group["totalCount"], 2)
        self.assertEqual(converter_group["onlineCount"], 2)
        self.assertEqual(converter_group["measuredCount"], 2)
        self.assertEqual(summary["counts"]["greenPowerConverter"], 2)
        self.assertEqual(converter_group["status"], "acToDc")
        self.assertEqual(converter_group["flowDirection"], "toDc")

        reverse_summary = service._power_flow_summary(
            [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_AC",
                    "value": -12.5,
                    "valid": 1,
                },
                {
                    "dev_type": "ACDCConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_AC",
                    "value": -8.0,
                    "valid": 1,
                },
            ]
        )
        reverse_group = reverse_summary["flowGroups"]["acdcConverter"]
        self.assertEqual(reverse_group["power"], 20.5)
        self.assertEqual(reverse_group["status"], "dcToAc")
        self.assertEqual(reverse_group["flowDirection"], "toAc")

        dc_terminal_fallback = service._power_flow_summary(
            [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_DC",
                    "value": 7.0,
                    "valid": 1,
                }
            ]
        )["flowGroups"]["acdcConverter"]
        self.assertEqual(dc_terminal_fallback["power"], 7.0)
        self.assertEqual(dc_terminal_fallback["status"], "dcToAc")
        self.assertEqual(dc_terminal_fallback["flowDirection"], "toAc")

        reverse_dc_terminal_fallback = service._power_flow_summary(
            [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_DC",
                    "value": -7.0,
                    "valid": 1,
                }
            ]
        )["flowGroups"]["acdcConverter"]
        self.assertEqual(reverse_dc_terminal_fallback["power"], -7.0)
        self.assertEqual(reverse_dc_terminal_fallback["status"], "acToDc")
        self.assertEqual(reverse_dc_terminal_fallback["flowDirection"], "toDc")

    def test_snapshot_power_summary_prefers_signed_scada_without_measurement_payload(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_measurements = {
            "definitions": [],
            "real": [
                {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": 18.0},
                {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "meas_type": "P_GEN", "value": 20.0},
                {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "meas_type": "P_GEN", "value": 30.0},
                {"dev_type": "ACLoad", "dev_name": "load_ac_1", "meas_type": "P_LOAD", "value": 90.0},
                {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "P", "value": 5.0},
                {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "SOC", "value": 0.55},
            ],
            "scada": [
                {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": -8.0},
                {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "meas_type": "P_GEN", "value": -20.0},
                {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "meas_type": "P_GEN", "value": -30.0},
                {"dev_type": "ACLoad", "dev_name": "load_ac_1", "meas_type": "P_LOAD", "value": -90.0},
                {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "P", "value": -5.0},
                {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "SOC", "value": 1.05},
            ],
        }

        snapshot = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_commands=False,
        )

        self.assertNotIn("measurements", snapshot)
        self.assertEqual(snapshot["power_summary"]["source"], "scada")
        self.assertEqual(snapshot["power_summary"]["wind"], -8.0)
        self.assertEqual(snapshot["power_summary"]["solar"], -20.0)
        self.assertEqual(snapshot["power_summary"]["diesel"], -30.0)
        self.assertEqual(snapshot["power_summary"]["load"], -90.0)
        self.assertEqual(snapshot["power_summary"]["storage"], -5.0)
        self.assertEqual(snapshot["power_summary"]["soc"], 105.0)

    def test_power_summary_classifies_indexed_chinese_wind_pv_storage_and_load_devices(self):
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = PolarMicrogridSimulator(
            ROOT / "models" / "simulator" / "source" / "秦岭站",
            Path(workspace.name) / "runtime",
            kernel=lambda _config: None,
        )

        summary = service._power_flow_summary(
            [
                {"dev_type": "ACGenerator", "dev_name": "交流风电-1", "meas_type": "P_GEN", "value": -3.0},
                {"dev_type": "DCGenerator", "dev_name": "直流光伏-1", "meas_type": "P_GEN", "value": -4.0},
                {"dev_type": "ACGenerator", "dev_name": "交流柴油发电机-27", "meas_type": "P_GEN", "value": -6.0},
                {"dev_type": "ACLoad", "dev_name": "交流负荷-1", "meas_type": "P_LOAD", "value": -7.0},
                {"dev_type": "DCGenerator", "dev_name": "电化学储能-1", "meas_type": "P_GEN", "value": -5.0},
                {"dev_type": "DCGenerator", "dev_name": "电化学储能-1", "meas_type": "SOC", "value": 1.05},
            ]
        )

        self.assertEqual(summary["wind"], -3.0)
        self.assertEqual(summary["solar"], -4.0)
        self.assertEqual(summary["diesel"], -6.0)
        self.assertEqual(summary["load"], -7.0)
        self.assertEqual(summary["storage"], -5.0)
        self.assertEqual(summary["soc"], 105.0)

    def test_power_summary_builds_topology_aware_energy_flow_groups(self):
        import simu_loop
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = PolarMicrogridSimulator(
            ROOT / "models" / "simulator" / "source" / "秦岭站",
            Path(workspace.name) / "runtime",
            kernel=lambda _config: None,
        )

        ac_generators = service.source_model_book.data["ACGenerator"].data
        dc_generators = service.source_model_book.data["DCGenerator"].data
        next(row for row in dc_generators if row.get("name") == "电化学储能-1")["control_type"] = "V"
        ac_generators.extend(
            [
                {
                    "idx": 89,
                    "name": "交流直连风电测试",
                    "dev_type": "ac-wind-source",
                    "node": 29,
                    "control_type": "PQ",
                    "run_stat": 1,
                    "rated_capacity": 25,
                },
                {
                    "idx": 90,
                    "name": "交流光伏测试",
                    "dev_type": "ac-pv-source",
                    "node": 29,
                    "control_type": "PQ",
                    "run_stat": 1,
                    "rated_capacity": 30,
                },
                {
                    "idx": 91,
                    "name": "交流构网储能测试",
                    "dev_type": "ac-storage",
                    "node": 29,
                    "control_type": "PH",
                    "run_stat": 1,
                    "rated_capacity": 50,
                },
                {
                    "idx": 92,
                    "name": "交流跟网储能测试",
                    "dev_type": "ac-storage",
                    "node": 29,
                    "control_type": "PQ",
                    "run_stat": 1,
                    "rated_capacity": 40,
                },
            ]
        )
        dc_generators.extend(
            [
                {
                    "idx": 90,
                    "name": "直流风电测试",
                    "dev_type": "dc-wind-source",
                    "node": 13,
                    "control_type": "P",
                    "run_stat": 1,
                    "rated_capacity": 20,
                },
                {
                    "idx": 91,
                    "name": "直流跟网储能测试",
                    "dev_type": "dc-storage",
                    "node": 13,
                    "control_type": "P",
                    "run_stat": 1,
                    "rated_capacity": 40,
                },
            ]
        )
        service.source_model_book.data["ACWindGen"].data.append(
            {"idx": 89, "idx_acgenerator": 89, "rated_power": 25}
        )
        service.source_model_book.data["ACPVGen"].data.append(
            {"idx": 90, "idx_acgenerator": 90, "rated_power": 30}
        )
        service.source_model_book.data["ACStorageGen"].data.extend(
            [
                {"idx": 91, "idx_acgenerator": 91, "energy_capacity": 50},
                {"idx": 92, "idx_acgenerator": 92, "energy_capacity": 40},
            ]
        )
        service.source_model_book.data["DCWindGen"] = simu_loop.EBook(
            {
                "DCWindGen": [
                    {"idx": 90, "idx_dcgenerator": 90, "rated_power": 20}
                ]
            }
        ).data["DCWindGen"]
        service.source_model_book.data["DCStorageGen"].data.append(
            {"idx": 91, "idx_dcgenerator": 91, "energy_capacity": 40}
        )

        summary = service._power_flow_summary(
            [
                {"dev_type": "ACGenerator", "dev_name": "交流直连风电测试", "meas_type": "P_GEN", "value": 3.0},
                {"dev_type": "DCGenerator", "dev_name": "直流风电测试", "meas_type": "P_GEN", "value": 2.0},
                {"dev_type": "DCGenerator", "dev_name": "直流光伏-1", "meas_type": "P_GEN", "value": 4.0},
                {"dev_type": "ACGenerator", "dev_name": "交流光伏测试", "meas_type": "P_GEN", "value": 5.0},
                {"dev_type": "DCGenerator", "dev_name": "电化学储能-1", "meas_type": "P_GEN", "value": 6.0},
                {"dev_type": "DCGenerator", "dev_name": "电化学储能-1", "meas_type": "SOC", "value": 0.55},
                {"dev_type": "DCGenerator", "dev_name": "直流跟网储能测试", "meas_type": "P_GEN", "value": -7.0},
                {"dev_type": "DCGenerator", "dev_name": "直流跟网储能测试", "meas_type": "SOC", "value": 0.65},
                {"dev_type": "ACGenerator", "dev_name": "交流构网储能测试", "meas_type": "P_GEN", "value": 8.0},
                {"dev_type": "ACGenerator", "dev_name": "交流构网储能测试", "meas_type": "SOC", "value": 0.75},
                {"dev_type": "ACGenerator", "dev_name": "交流跟网储能测试", "meas_type": "P_GEN", "value": -9.0},
                {"dev_type": "ACGenerator", "dev_name": "交流跟网储能测试", "meas_type": "SOC", "value": 0.85},
                {"dev_type": "ACLoad", "dev_name": "交流负荷-1", "meas_type": "P_LOAD", "value": 10.0},
                {"dev_type": "DCLoad", "dev_name": "直流负荷-1", "meas_type": "P_LOAD", "value": 12.0},
                {"dev_type": "ACGenerator", "dev_name": "交流柴油发电机-27", "meas_type": "P_GEN", "value": 11.0},
            ]
        )

        groups = summary["flowGroups"]
        expected_powers = {
            "dcWind": 2.0,
            "dcSolar": 4.0,
            "dcGridFollowingStorage": -7.0,
            "dcGridFormingStorage": 6.0,
            "acGridFormingStorage": 8.0,
            "acWind": 3.0,
            "acSolar": 5.0,
            "acGridFollowingStorage": -9.0,
            "dcLoad": 12.0,
            "acLoad": 10.0,
            "diesel": 11.0,
        }
        for key, expected in expected_powers.items():
            self.assertIn(key, groups)
            self.assertEqual(groups[key]["power"], expected)
            self.assertGreater(groups[key]["totalCount"], 0)

        self.assertAlmostEqual(groups["dcGridFormingStorage"]["soc"], 55.0)
        self.assertAlmostEqual(groups["dcGridFollowingStorage"]["soc"], 65.0)
        self.assertAlmostEqual(groups["acGridFormingStorage"]["soc"], 75.0)
        self.assertAlmostEqual(groups["acGridFollowingStorage"]["soc"], 85.0)
        self.assertEqual(groups["dcGridFollowingStorage"]["status"], "charge")
        self.assertEqual(groups["dcGridFollowingStorage"]["flowDirection"], "fromBus")
        self.assertEqual(groups["acGridFormingStorage"]["status"], "discharge")
        self.assertEqual(groups["acGridFormingStorage"]["flowDirection"], "toBus")
        self.assertEqual(groups["dcLoad"]["flowDirection"], "fromBus")
        self.assertEqual(groups["acLoad"]["flowDirection"], "fromBus")
        self.assertEqual(groups["diesel"]["flowDirection"], "toBus")
        self.assertEqual(summary["load"], 22.0)
        self.assertEqual(summary["greenPower"], 11.0)
        self.assertEqual(summary["greenPowerShare"], 50.0)

    def test_power_summary_exposes_effective_targets_and_renewable_max_available_power(self):
        import simu_loop

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        effective_model = simu_loop._clone_ebook(service.source_model_book)
        next(row for row in effective_model.data["ACGenerator"].data if row.get("name") == "wt01_10kw")["p_set"] = 6.0
        next(row for row in effective_model.data["DCGenerator"].data if row.get("name") == "pv01_vsrc")["p_set"] = 20.0
        next(row for row in effective_model.data["DCGenerator"].data if row.get("name") == "ess01_vsrc")["p_set"] = -8.0
        next(row for row in effective_model.data["ACGenerator"].data if row.get("name") == "diesel_300kw")["p_set"] = 70.0
        next(row for row in effective_model.data["ACLoad"].data if row.get("name") == "load_ac_1")["pv0"] = 75.0
        next(row for row in effective_model.data["DCACConverter"].data if row.get("name") == "grid_inv_acp")["p_ac_set"] = -35.0
        service.latest_model_book = effective_model

        weather = service.weather_book.data["Weather"].data[0]
        weather["wind_speed_mps"] = 15.0
        weather["solar_irradiance_w_m2"] = 1000.0
        weather["air_temp_c"] = 25.0

        service.source_model_book.data["ACGenerator"].data.append(
            {
                "idx": 99,
                "name": "offline-wind-target-must-not-count",
                "dev_type": "wind-source",
                "node": 1,
                "control_type": "P",
                "p_set": 999.0,
                "run_stat": 0,
            }
        )

        summary = service._power_flow_summary(
            [
                {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": 5.5},
                {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "meas_type": "P_GEN", "value": 18.0},
                {"dev_type": "DCGenerator", "dev_name": "ess01_vsrc", "meas_type": "P_GEN", "value": -7.5},
                {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "meas_type": "P_GEN", "value": 68.0},
                {"dev_type": "ACLoad", "dev_name": "load_ac_1", "meas_type": "P_LOAD", "value": 73.0},
                {"dev_type": "DCACConverter", "dev_name": "grid_inv_acp", "meas_type": "P_AC", "value": -34.0},
            ]
        )
        groups = summary["flowGroups"]

        self.assertEqual(groups["dcWind"]["targetPower"], 6.0)
        self.assertEqual(groups["dcWind"]["maxAvailablePower"], 10.0)
        self.assertEqual(groups["dcSolar"]["targetPower"], 20.0)
        self.assertEqual(groups["dcSolar"]["maxAvailablePower"], 50.0)
        self.assertEqual(groups["dcGridFollowingStorage"]["targetPower"], -8.0)
        self.assertEqual(groups["diesel"]["targetPower"], 70.0)
        self.assertEqual(groups["acLoad"]["targetPower"], 75.0)
        self.assertEqual(groups["acdcConverter"]["targetPower"], 35.0)
        self.assertEqual(groups["acdcConverter"]["power"], 34.0)
        self.assertEqual(groups["acdcConverter"]["status"], "dcToAc")
        self.assertEqual(groups["acdcConverter"]["flowDirection"], "toAc")
        self.assertEqual(groups["dcWind"]["onlineCount"], 1)

    def test_converter_target_uses_the_terminal_selected_by_side_control_fields(self):
        import simu_loop

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        effective_model = simu_loop._clone_ebook(service.source_model_book)
        converter = next(
            row
            for row in effective_model.data["DCACConverter"].data
            if row.get("name") == "grid_inv_acp"
        )
        converter.update(
            {
                "ac_control_type": "NONE",
                "dc_control_type": "P",
                "p_ac_set": 999.0,
                "p_dc_set": 12.0,
            }
        )
        service.latest_model_book = effective_model

        group = service._power_flow_summary(
            [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid_inv_acp",
                    "meas_type": "P_DC",
                    "value": 12.0,
                    "valid": 1,
                }
            ]
        )["flowGroups"]["acdcConverter"]

        self.assertEqual(group["targetPower"], 12.0)
        self.assertEqual(group["power"], 12.0)
        self.assertEqual(group["status"], "dcToAc")

    def test_parallel_converter_summary_normalizes_all_control_mode_combinations(self):
        import simu_loop
        from simu.model_semantics import grid_converter_keys

        cases = {
            "mixed": (("NONE", "P"), ("PQ", "NONE")),
            "both_dc": (("NONE", "P"), ("NONE", "P")),
            "both_ac": (("PQ", "NONE"), ("PQ", "NONE")),
            "double_none": (("NONE", "NONE"), ("NONE", "NONE")),
        }

        for label, modes in cases.items():
            with self.subTest(label=label):
                workspace, service = self._make_service()
                self.addCleanup(workspace.cleanup)
                source_model = service.source_model_book
                converter_block = source_model.data["DCACConverter"]
                grid_keys = sorted(
                    key
                    for key in grid_converter_keys(source_model)
                    if key[0] == "DCACConverter"
                )
                self.assertEqual(len(grid_keys), 1)
                first_name = grid_keys[0][1]
                first = next(row for row in converter_block.data if row.get("name") == first_name)
                second = copy.deepcopy(first)
                second.update({"idx": "3", "name": "parallel-grid-link"})
                converter_block.data.append(second)

                effective_model = simu_loop._clone_ebook(source_model)
                effective_rows = {
                    row["name"]: row
                    for row in effective_model.data["DCACConverter"].data
                    if row.get("name") in {first_name, "parallel-grid-link"}
                }
                target_p_ac = (-9.0, -3.0)
                measurements = []
                for source_row, mode, target_kw in zip(
                    (first, second), modes, target_p_ac
                ):
                    ac_mode, dc_mode = mode
                    source_row.update(
                        {
                            "ac_control_type": ac_mode,
                            "dc_control_type": dc_mode,
                        }
                    )
                    effective_row = effective_rows[source_row["name"]]
                    effective_row.update(
                        {
                            "ac_control_type": ac_mode,
                            "dc_control_type": dc_mode,
                            "p_ac_set": target_kw if dc_mode != "P" and ac_mode != "NONE" else 999.0,
                            "p_dc_set": -target_kw if dc_mode == "P" or ac_mode == "NONE" else 999.0,
                        }
                    )
                    use_dc = dc_mode == "P" or (dc_mode == "NONE" and ac_mode == "NONE")
                    measurements.append(
                        {
                            "dev_type": "DCACConverter",
                            "dev_name": source_row["name"],
                            "meas_type": "P_DC" if use_dc else "P_AC",
                            "value": -target_kw if use_dc else target_kw,
                            "valid": 1,
                        }
                    )

                service.latest_model_book = effective_model
                service._internal_power_converter_keys_cache = None
                group = service._power_flow_summary(measurements)["flowGroups"]["acdcConverter"]

                self.assertEqual(group["totalCount"], 2)
                self.assertEqual(group["onlineCount"], 2)
                self.assertEqual(group["measuredCount"], 2)
                self.assertEqual(group["powerConvention"], "P_DC")
                self.assertAlmostEqual(group["power"], 12.0)
                self.assertAlmostEqual(group["targetPower"], 12.0)
                self.assertEqual(group["status"], "dcToAc")
                self.assertEqual(group["flowDirection"], "toAc")

    def test_power_summary_keeps_missing_target_unknown_instead_of_copying_current_power(self):
        import simu_loop

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        effective_model = simu_loop._clone_ebook(service.source_model_book)
        next(row for row in effective_model.data["ACGenerator"].data if row.get("name") == "wt01_10kw")["p_set"] = ""
        service.latest_model_book = effective_model

        summary = service._power_flow_summary(
            [
                {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": 7.0},
            ]
        )

        group = summary["flowGroups"]["dcWind"]
        self.assertEqual(group["power"], 7.0)
        self.assertIsNone(group["targetPower"])

    def test_power_summary_keeps_same_named_ac_and_dc_loads_separate(self):
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = PolarMicrogridSimulator(
            ROOT / "models" / "simulator" / "source" / "秦岭站",
            Path(workspace.name) / "runtime",
            kernel=lambda _config: None,
        )
        shared_name = "同名交直流负荷"
        service.source_model_book.data["ACLoad"].data.append(
            {
                "idx": 90,
                "name": shared_name,
                "dev_type": "ac-load",
                "node": 32,
                "run_stat": 1,
                "pbase": 0,
            }
        )
        service.source_model_book.data["DCLoad"].data.append(
            {
                "idx": 90,
                "name": shared_name,
                "dev_type": "dc-load",
                "node": 38,
                "run_stat": 1,
                "pbase": 0,
            }
        )

        summary = service._power_flow_summary(
            [
                {"dev_type": "ACLoad", "dev_name": shared_name, "meas_type": "P_LOAD", "value": 13.0},
                {"dev_type": "DCLoad", "dev_name": shared_name, "meas_type": "P_LOAD", "value": 17.0},
            ]
        )

        self.assertEqual(summary["flowGroups"]["acLoad"]["power"], 13.0)
        self.assertEqual(summary["flowGroups"]["dcLoad"]["power"], 17.0)
        self.assertEqual(summary["load"], 30.0)

    def test_topology_groups_follow_final_real_bus_for_wind_pv_and_storage(self):
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = PolarMicrogridSimulator(
            ROOT / "models" / "simulator" / "source" / "秦岭站",
            Path(workspace.name) / "runtime",
            kernel=lambda _config: None,
        )

        ac_nodes = service.source_model_book.data["ACNode"].data
        dc_nodes = service.source_model_book.data["DCNode"].data
        ac_generators = service.source_model_book.data["ACGenerator"].data
        dc_generators = service.source_model_book.data["DCGenerator"].data
        dcac_converters = service.source_model_book.data["DCACConverter"].data

        ac_nodes.append({"idx": 90, "name": "跨域储能交流端", "vbase": 380, "run_stat": 1})
        dc_nodes.append({"idx": 90, "name": "跨域光伏直流端", "vbase": 750, "run_stat": 1})
        ac_generators.append(
            {
                "idx": 90,
                "name": "经变流器接直流母线的储能",
                "dev_type": "ac-storage",
                "node": 90,
                "control_type": "PQ",
                "run_stat": 1,
                "rated_capacity": 40,
            }
        )
        dc_generators.append(
            {
                "idx": 90,
                "name": "经变流器接交流母线的光伏",
                "dev_type": "dc-pv-source",
                "node": 90,
                "control_type": "P",
                "run_stat": 1,
                "rated_capacity": 30,
            }
        )
        dcac_converters.extend(
            [
                {
                    "idx": 90,
                    "name": "光伏并网逆变器测试",
                    "dev_type": "acdc-converter",
                    "ac_node": 29,
                    "dc_node": 90,
                    "run_stat": 1,
                },
                {
                    "idx": 91,
                    "name": "储能并网整流器测试",
                    "dev_type": "acdc-converter",
                    "ac_node": 90,
                    "dc_node": 13,
                    "run_stat": 1,
                },
            ]
        )
        service.source_model_book.data["ACStorageGen"].data.append(
            {"idx": 90, "idx_acgenerator": 90, "energy_capacity": 40}
        )
        service.source_model_book.data["DCPVGen"].data.append(
            {"idx": 90, "idx_dcgenerator": 90, "rated_power": 30}
        )

        summary = service._power_flow_summary(
            [
                {"dev_type": "ACGenerator", "dev_name": "交流风电-1", "meas_type": "P_GEN", "value": 3.0},
                {"dev_type": "DCGenerator", "dev_name": "经变流器接交流母线的光伏", "meas_type": "P_GEN", "value": 5.0},
                {"dev_type": "ACGenerator", "dev_name": "经变流器接直流母线的储能", "meas_type": "P_GEN", "value": -7.0},
            ]
        )

        groups = summary["flowGroups"]
        self.assertEqual(groups["dcWind"]["power"], 3.0)
        self.assertIsNone(groups["acWind"]["power"])
        self.assertEqual(groups["acWind"]["measuredCount"], 0)
        self.assertEqual(groups["acSolar"]["power"], 5.0)
        self.assertEqual(groups["dcGridFollowingStorage"]["power"], -7.0)
        self.assertIsNone(groups["acGridFollowingStorage"]["power"])
        self.assertEqual(groups["acGridFollowingStorage"]["measuredCount"], 0)

    def test_topology_groups_exclude_retired_and_dead_island_power(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        dc_generators = service.source_model_book.data["DCGenerator"].data
        next(row for row in dc_generators if row.get("name") == "ess01_vsrc")["control_type"] = "V"
        dc_generators.extend(
            [
                {
                    "idx": 90,
                    "name": "退运跟网储能",
                    "dev_type": "dc-storage",
                    "node": 1,
                    "control_type": "P",
                    "run_stat": 0,
                    "rated_capacity": 40,
                },
                {
                    "idx": 91,
                    "name": "死岛跟网储能",
                    "dev_type": "dc-storage",
                    "node": 1,
                    "control_type": "P",
                    "run_stat": 1,
                    "rated_capacity": 40,
                },
            ]
        )
        service.source_model_book.data["DCStorageGen"].data.extend(
            [
                {"idx": 90, "idx_dcgenerator": 90, "energy_capacity": 40},
                {"idx": 91, "idx_dcgenerator": 91, "energy_capacity": 40},
            ]
        )
        service.latest_device_states = [
            {
                "dev_type": "DCGenerator",
                "dev_name": "死岛跟网储能",
                "run_stat": 1,
                "dead_island": True,
            }
        ]

        summary = service._power_flow_summary(
            [
                {"dev_type": "DCGenerator", "dev_name": "退运跟网储能", "meas_type": "P_GEN", "value": 12.0},
                {"dev_type": "DCGenerator", "dev_name": "死岛跟网储能", "meas_type": "P_GEN", "value": 18.0},
            ]
        )
        group = summary["flowGroups"]["dcGridFollowingStorage"]

        self.assertEqual(group["power"], 0.0)
        self.assertEqual(group["onlineCount"], 0)
        self.assertEqual(group["retiredCount"], 1)
        self.assertEqual(group["deadIslandCount"], 1)
        self.assertEqual(group["status"], "deadIsland")
        self.assertEqual(group["flowDirection"], "idle")

    def test_storage_group_soc_is_weighted_by_energy_capacity(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        dc_generators = service.source_model_book.data["DCGenerator"].data
        next(row for row in dc_generators if row.get("name") == "ess01_vsrc")["control_type"] = "V"
        service.source_model_book.data["DCStorageGen"].data[0]["energy_capacity"] = 60
        next_idx = max(int(row.get("idx", 0)) for row in dc_generators) + 1
        dc_generators.append(
            {
                "idx": next_idx,
                "name": "ess_weighted_vsrc",
                "dev_type": "dc-storage",
                "node": 1,
                "control_type": "V",
                "run_stat": 1,
                "rated_capacity": 180,
            }
        )
        service.source_model_book.data["DCStorageGen"].data.append(
            {
                "idx": 90,
                "idx_dcgenerator": next_idx,
                "energy_capacity": 180,
                "state_of_charge": 75,
            }
        )

        summary = service._power_flow_summary(
            [
                {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "SOC", "value": 0.25},
                {"dev_type": "DCGenerator", "dev_name": "ess_weighted_vsrc", "meas_type": "SOC", "value": 0.75},
            ]
        )

        group = summary["flowGroups"]["dcGridFormingStorage"]
        self.assertAlmostEqual(group["soc"], 62.5)


if __name__ == "__main__":
    unittest.main()
