from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from simu.control_config import default_boolean, default_integer, default_number
from simu.renewable_control import (
    RenewableControlSettings,
    calculate_renewable_control_plan,
)
from simu.renewable_optimization import optimize_topology_islands
from simu.resource_topology import ResourceTopology


ROOT = Path(__file__).resolve().parents[1]


def storage(
    name: str,
    *,
    current: float,
    charge: float,
    discharge: float,
) -> dict:
    return {
        "technology": "storage",
        "dev_type": "ACGenerator",
        "dev_name": name,
        "connectionSide": "AC",
        "gridComponentId": "AC:1",
        "online": True,
        "commandable": True,
        "stateEligible": True,
        "currentKw": current,
        "chargePower": charge,
        "dischargePower": discharge,
        "maxChargePowerKw": charge,
        "maxDischargePowerKw": discharge,
        "role": "balance",
        "soc": 0.5,
        "socMin": 0.1,
        "socMax": 0.9,
        "set_type": "p_set",
    }


def renewable(name: str, *, side: str, current: float, capacity: float) -> dict:
    component = f"{side}:1"
    return {
        "technology": "wind",
        "dev_type": "ACGenerator" if side == "AC" else "DCGenerator",
        "dev_name": name,
        "connectionSide": side,
        "gridComponentId": component if side == "AC" else "",
        "dcTransferGroupId": component if side == "DC" else "",
        "online": True,
        "commandable": True,
        "planningCurrentKw": current,
        "currentKw": current,
        "capacityKw": capacity,
        "weatherAvailableKnown": False,
        "weatherAvailableKw": None,
        "set_type": "p_set",
    }


def diesel(name: str, *, current: float, minimum: float, maximum: float) -> dict:
    return {
        "dev_type": "ACGenerator",
        "dev_name": name,
        "connectionSide": "AC",
        "gridComponentId": "AC:1",
        "online": True,
        "commandable": True,
        "stateEligible": True,
        "currentKw": current,
        "minKw": minimum,
        "capacityKw": maximum,
        "set_type": "p_set",
    }


def converter(name: str, *, capacity: float) -> dict:
    return {
        "dev_type": "DCACConverter",
        "model_block": "DCACConverter",
        "dev_name": name,
        "online": True,
        "commandable": True,
        "currentKw": 0.0,
        "transferCapacityKw": capacity,
        "signedMinTargetKw": -capacity,
        "signedMaxTargetKw": capacity,
        "set_type": "p_ac_set",
    }


class RenewableControlParameterizationTest(unittest.TestCase):
    def test_step_settings_export_fixed_per_decision_fields(self):
        settings = RenewableControlSettings().updated(
            {
                "renewableStepRatio": 0.04,
                "storageStepRatio": 0.02,
                "storageSocCorrectionStepScale": 0.25,
            }
        )

        self.assertEqual(settings.step_coefficient, 0.04)
        self.assertEqual(settings.storage_step_ratio, 0.02)
        self.assertEqual(settings.storage_soc_correction_step_scale, 0.25)
        self.assertEqual(settings.payload()["renewableStepRatio"], 0.04)
        self.assertEqual(settings.payload()["storageStepRatio"], 0.02)
        self.assertEqual(settings.payload()["storageSocCorrectionStepScale"], 0.25)
        self.assertNotIn("renewableStepRatePerMinute", settings.payload())
        self.assertNotIn("storageStepRatePerMinute", settings.payload())

    def test_legacy_per_minute_step_fields_are_only_accepted_as_input_aliases(self):
        settings = RenewableControlSettings().updated(
            {
                "renewableStepRatePerMinute": 0.04,
                "storageStepRatePerMinute": 0.02,
            }
        )

        self.assertEqual(settings.step_coefficient, 0.04)
        self.assertEqual(settings.storage_step_ratio, 0.02)
        self.assertNotIn("renewableStepRatePerMinute", settings.payload())
        self.assertNotIn("storageStepRatePerMinute", settings.payload())

    def test_soc_correction_step_scale_is_clamped_to_ten_through_one_hundred_percent(self):
        below = RenewableControlSettings().updated(
            {"storageSocCorrectionStepScale": 0.0}
        )
        above = RenewableControlSettings().updated(
            {"storageSocCorrectionStepScale": 2.0}
        )

        self.assertEqual(below.storage_soc_correction_step_scale, 0.10)
        self.assertEqual(above.storage_soc_correction_step_scale, 1.0)
        self.assertEqual(
            below.payload()["storageSocCorrectionStepScale"],
            0.10,
        )
        self.assertEqual(
            above.payload()["storageSocCorrectionStepScale"],
            1.0,
        )

    def test_control_plan_keeps_steps_fixed_when_simulation_timing_changes(self):
        from tests.test_trainee_renewable_backend_control import renewable_snapshot

        snapshot = renewable_snapshot()
        snapshot["simulation_timing"] = {
            "simulation_step_seconds": 300.0,
            "simulation_period_seconds": 1.0,
        }

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                interval_seconds=2.0,
                step_coefficient=0.03,
                storage_step_ratio=0.02,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["controlIntervalSeconds"], 2.0)
        self.assertEqual(metrics["simulationControlIntervalSeconds"], 2.0)
        self.assertEqual(metrics["controlIntervalClock"], "simulation")
        self.assertAlmostEqual(metrics["renewableStepRatio"], 0.03)
        self.assertAlmostEqual(metrics["gridFollowingStorageStepRatio"], 0.02)
        self.assertAlmostEqual(metrics["renewableEffectiveDecisionStepRatio"], 0.03)
        self.assertAlmostEqual(metrics["storageEffectiveDecisionStepRatio"], 0.02)
        self.assertNotIn("renewableStepRatePerMinute", metrics)
        self.assertNotIn("storageStepRatePerMinute", metrics)
        self.assertNotIn("simulationStepSeconds", metrics)
        self.assertNotIn("simulationPeriodSeconds", metrics)
        self.assertNotIn("simulationTimingKnown", metrics)

    def test_control_plan_scales_grid_forming_soc_correction_with_violation_energy(self):
        from tests.test_trainee_renewable_backend_control import renewable_snapshot

        snapshot = renewable_snapshot()
        snapshot["system_parameters"] = {
            "effective_step_minutes": 5.0,
            "compute_interval_seconds": 1.0,
        }
        snapshot["simulation_timing"] = {
            "simulation_step_seconds": 300.0,
            "simulation_period_seconds": 1.0,
        }
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "storage-1" and row["meas_type"] == "SOC":
                row["value"] = 0.951
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                interval_seconds=600.0,
                storage_step_ratio=0.03,
                grid_forming_storage_protection_ratio=0.0,
                soc_deadband=0.05,
            ),
        )
        row = next(
            item
            for item in plan["commandRows"]
            if item.get("technology") == "storage"
        )

        energy_correction_kw = (
            (0.951 - 0.90) * 100.0 * 0.95 / (10.0 / 60.0)
        )
        expected_step_kw = 40.0 * 0.03
        expected_correction_kw = min(
            expected_step_kw,
            max(expected_step_kw * 0.20, energy_correction_kw),
        )
        self.assertEqual(row["controlHorizonMinutes"], 10.0)
        self.assertAlmostEqual(row["commandKw"], expected_correction_kw, places=5)
        self.assertFalse(row["strategyCommand"])

    def test_control_plan_limits_severe_grid_forming_soc_correction_to_one_step(self):
        from tests.test_trainee_renewable_backend_control import renewable_snapshot

        snapshot = renewable_snapshot()
        snapshot["system_parameters"] = {
            "effective_step_minutes": 5.0,
            "compute_interval_seconds": 1.0,
        }
        snapshot["simulation_timing"] = {
            "simulation_step_seconds": 300.0,
            "simulation_period_seconds": 1.0,
        }
        for measurement in snapshot["measurements"]["scada"]:
            if measurement["dev_name"] == "storage-1" and measurement["meas_type"] == "SOC":
                measurement["value"] = 1.6762
            elif measurement["dev_name"] == "storage-1" and measurement["meas_type"] == "P_GEN":
                measurement["value"] = 8.85

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                interval_seconds=600.0,
                storage_step_ratio=0.03,
                grid_forming_storage_protection_ratio=0.0,
                soc_deadband=0.05,
            ),
        )
        row = next(
            item
            for item in plan["commandRows"]
            if item.get("technology") == "storage"
        )

        expected_step_kw = 40.0 * 0.03
        self.assertEqual(row["controlHorizonMinutes"], 10.0)
        self.assertAlmostEqual(row["currentKw"], 8.85, places=5)
        self.assertAlmostEqual(
            row["commandKw"],
            8.85 + expected_step_kw,
            places=5,
        )
        self.assertFalse(row["strategyCommand"])

    def test_power_protection_bands_are_persisted_as_ratios(self):
        settings = RenewableControlSettings().updated(
            {
                "gridFormingStorageProtectionRatio": 0.12,
                "dieselPowerProtectionRatio": 0.08,
            }
        )

        self.assertAlmostEqual(settings.grid_forming_storage_protection_ratio, 0.12)
        self.assertAlmostEqual(settings.diesel_power_protection_ratio, 0.08)
        self.assertEqual(
            settings.payload()["gridFormingStorageProtectionRatio"],
            0.12,
        )
        self.assertEqual(settings.payload()["dieselPowerProtectionRatio"], 0.08)
        self.assertNotIn("storageSwitchDeadbandKw", settings.payload())
        self.assertNotIn("dieselDeadbandRatio", settings.payload())

    def test_legacy_power_protection_fields_migrate_without_being_reexported(self):
        settings = RenewableControlSettings().updated(
            {
                "storageSwitchDeadbandKw": 5.0,
                "dieselDeadbandRatio": 0.04,
            }
        )

        self.assertAlmostEqual(settings.grid_forming_storage_protection_ratio, 0.05)
        self.assertAlmostEqual(settings.diesel_power_protection_ratio, 0.04)
        self.assertNotIn("storageSwitchDeadbandKw", settings.payload())
        self.assertNotIn("dieselDeadbandRatio", settings.payload())

    def test_grid_forming_storage_protection_ratio_scales_directional_limits(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        charging = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "构网储能充电边界",
                    current=-50.0,
                    charge=50.0,
                    discharge=100.0,
                )
            ],
            converter_rows=[],
            grid_forming_storage_protection_ratio=0.10,
        )
        discharging = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "构网储能放电边界",
                    current=100.0,
                    charge=50.0,
                    discharge=100.0,
                )
            ],
            converter_rows=[],
            grid_forming_storage_protection_ratio=0.10,
        )

        self.assertAlmostEqual(
            charging.targets[("ACGenerator", "构网储能充电边界")],
            -45.0,
            places=3,
        )
        self.assertAlmostEqual(
            discharging.targets[("ACGenerator", "构网储能放电边界")],
            90.0,
            places=3,
        )

    def test_diesel_power_protection_ratio_scales_rated_capacity(self):
        result = optimize_topology_islands(
            ResourceTopology(resources={}, dc_transfer_groups={}),
            renewable_rows=[],
            diesel_rows=[diesel("柴发", current=20.0, minimum=20.0, maximum=100.0)],
            storage_rows=[],
            converter_rows=[],
            diesel_power_protection_ratio=0.10,
        )

        self.assertAlmostEqual(result.targets[("ACGenerator", "柴发")], 30.0, places=5)

    def test_parallel_converters_share_dc_to_ac_transfer_by_capacity(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "变流器1"): ("AC:1", "DC:1"),
                ("DCACConverter", "变流器2"): ("AC:1", "DC:1"),
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[renewable("直流风电", side="DC", current=10.0, capacity=100.0)],
            diesel_rows=[diesel("柴发", current=80.0, minimum=20.0, maximum=100.0)],
            storage_rows=[],
            converter_rows=[
                converter("变流器1", capacity=100.0),
                converter("变流器2", capacity=200.0),
            ],
            step_coefficient=0.30,
            diesel_power_protection_ratio=0.0,
        )

        first = result.targets[("DCACConverter", "变流器1")]
        second = result.targets[("DCACConverter", "变流器2")]
        self.assertAlmostEqual(first, 10.0, places=4)
        self.assertAlmostEqual(second, 20.0, places=4)
        self.assertAlmostEqual(first / 100.0, second / 200.0, places=6)

    def test_parallel_converters_share_ac_to_dc_transfer_by_capacity(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "变流器1"): ("AC:1", "DC:1"),
                ("DCACConverter", "变流器2"): ("AC:1", "DC:1"),
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[renewable("交流风电", side="AC", current=10.0, capacity=100.0)],
            diesel_rows=[],
            storage_rows=[
                {
                    **storage("直流跟网储能", current=0.0, charge=100.0, discharge=100.0),
                    "dev_type": "DCGenerator",
                    "connectionSide": "DC",
                    "gridComponentId": "",
                    "dcTransferGroupId": "DC:1",
                    "role": "grid_following",
                    "stateEligible": False,
                }
            ],
            converter_rows=[
                converter("变流器1", capacity=100.0),
                converter("变流器2", capacity=200.0),
            ],
            step_coefficient=0.30,
            storage_step_ratio=1.0,
        )

        first = result.targets[("DCACConverter", "变流器1")]
        second = result.targets[("DCACConverter", "变流器2")]
        self.assertAlmostEqual(first, -10.0, places=4)
        self.assertAlmostEqual(second, -20.0, places=4)
        self.assertAlmostEqual(first / 100.0, second / 200.0, places=6)

    def test_converter_adjustment_square_term_is_not_configurable(self):
        signature = inspect.signature(optimize_topology_islands)
        settings = RenewableControlSettings()
        defaults = (ROOT / "simu" / "config" / "renewable_control_defaults.json").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("converter_adjustment_square_weight", signature.parameters)
        self.assertFalse(hasattr(settings, "optimization_converter_adjustment_square_weight"))
        self.assertNotIn("optimization_converter_adjustment_square_weight", defaults)
        self.assertNotIn("optimizationConverterAdjustmentSquareWeight", settings.payload())

    def test_measurement_noise_multiplier_and_capacity_tolerance_are_removed(self):
        defaults = (ROOT / "simu" / "config" / "renewable_control_defaults.json").read_text(
            encoding="utf-8"
        )
        backend = (ROOT / "simu" / "renewable_control.py").read_text(
            encoding="utf-8"
        )

        for removed in (
            "generation_capacity_tolerance_ratio",
            "generation_capacity_tolerance_cap_ratio",
            "measurement_noise_sigma_multiplier",
            "GENERATION_CAPACITY_TOLERANCE_RATIO",
            "GENERATION_CAPACITY_TOLERANCE_CAP_RATIO",
            "MEASUREMENT_NOISE_SIGMA_MULTIPLIER",
        ):
            self.assertNotIn(removed, defaults)
            self.assertNotIn(removed, backend)

    def test_weather_statistics_require_device_parameters_without_control_defaults(self):
        from simu.renewable_control import _renewable_weather_available_kw

        defaults = (ROOT / "simu" / "config" / "renewable_control_defaults.json").read_text(
            encoding="utf-8"
        )
        for removed in (
            "wind_default_cut_in_speed",
            "wind_default_rated_speed",
            "wind_default_cut_out_speed",
            "pv_default_reference_irradiance",
            "pv_default_reference_temperature",
            "pv_default_temperature_coefficient",
        ):
            self.assertNotIn(removed, defaults)

        self.assertIsNone(
            _renewable_weather_available_kw(
                "wind",
                {},
                100.0,
                wind_speed=10.0,
                solar_irradiance=None,
                air_temperature=None,
            )
        )
        self.assertIsNone(
            _renewable_weather_available_kw(
                "pv",
                {},
                100.0,
                wind_speed=None,
                solar_irradiance=800.0,
                air_temperature=20.0,
            )
        )

    def test_storage_soc_and_efficiency_do_not_add_policy_defaults(self):
        defaults = (ROOT / "simu" / "config" / "renewable_control_defaults.json").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("storage_default_soc", defaults)
        self.assertNotIn("storage_default_efficiency", defaults)

    def test_hydrogen_control_defaults_match_the_recommended_parameter_set(self):
        settings = RenewableControlSettings()
        expected = {
            "hydrogen_pressure_deadband_ratio": 0.05,
            "electrolyzer_power_min_ratio": 0.20,
            "electrolyzer_power_max_ratio": 0.90,
            "electrolyzer_power_deadband_ratio": 0.10,
            "electrolyzer_power_step_ratio": 0.10,
            "electrolyzer_diesel_power_limit_ratio": 0.35,
            "electrolyzer_diesel_power_deadband_ratio": 0.05,
            "electrolyzer_storage_soc_start_minimum": 0.70,
            "electrolyzer_storage_soc_stop_maximum": 0.30,
            "electrolyzer_hydrogen_storage_soc_stop_minimum": 0.90,
            "fuel_cell_power_min_ratio": 0.20,
            "fuel_cell_power_max_ratio": 0.90,
            "fuel_cell_power_deadband_ratio": 0.10,
            "fuel_cell_power_step_ratio": 0.10,
            "fuel_cell_diesel_power_limit_ratio": 0.50,
            "fuel_cell_storage_soc_limit": 0.30,
            "fuel_cell_hydrogen_storage_soc_upper_limit": 0.30,
            "fuel_cell_hydrogen_storage_soc_lower_limit": 0.20,
        }

        self.assertTrue(default_boolean("hydrogen_closed_loop_enabled"))
        self.assertTrue(settings.hydrogen_closed_loop_enabled)
        for field_name, value in expected.items():
            self.assertAlmostEqual(getattr(settings, field_name), value)
        self.assertEqual(settings.updated({}), settings.normalized())

        customized = settings.updated(
            {
                "hydrogenClosedLoopEnabled": False,
                "fuelCellPowerMinRatio": 0.42,
            }
        )
        self.assertFalse(customized.hydrogen_closed_loop_enabled)
        self.assertAlmostEqual(customized.fuel_cell_power_min_ratio, 0.42)

    def test_storage_efficiency_uses_model_value_and_only_falls_back_when_missing(self):
        from simu.renewable_control import _storage_efficiency

        self.assertEqual(_storage_efficiency({"charge_discharge_efficiency": 0.82}), 0.82)
        self.assertEqual(_storage_efficiency({"charge_discharge_efficiency": 82}), 82.0)
        self.assertEqual(_storage_efficiency({}), 1.0)
        self.assertEqual(_storage_efficiency({"charge_discharge_efficiency": "invalid"}), 1.0)
        self.assertEqual(_storage_efficiency({"charge_discharge_efficiency": 0}), 1.0)
        self.assertEqual(_storage_efficiency({"charge_discharge_efficiency": -0.5}), 1.0)

    def test_solver_defaults_come_from_parameter_configuration(self):
        self.assertEqual(
            default_number("optimization_curtailment_square_weight"),
            1e-6,
        )
        self.assertEqual(
            default_number(
                "optimization_source_storage_adjustment_square_weight"
            ),
            1e-6,
        )
        self.assertEqual(
            default_number("optimization_balance_delta_square_weight"),
            1e4,
        )
        self.assertEqual(default_number("optimization_balance_tolerance_kw"), 0.1)
        self.assertEqual(default_number("optimization_bound_tolerance_kw"), 0.1)
        self.assertEqual(default_number("optimization_ftol"), 1e-3)
        self.assertEqual(default_integer("optimization_max_iterations"), 100)

    def test_soc_limit_curves_are_interpolated_into_optimizer_hard_bounds(self):
        from tests.test_trainee_renewable_backend_control import renewable_snapshot
        from simu.renewable_control import calculate_renewable_control_plan

        cases = (
            {
                "direction": "charge",
                "soc": 0.75,
                "current": -30.0,
                "diesel": 20.0,
                "settings": {
                    "storageChargeDeratingCurve": [
                        {"soc": 0.60, "powerRatio": 1.00},
                        {"soc": 0.80, "powerRatio": 0.20},
                        {"soc": 0.90, "powerRatio": 0.00},
                    ]
                },
                "factor_key": "chargeDeratingFactor",
                "power_key": "chargePower",
                "expected_factor": 0.40,
                "expected_limit": 16.0,
                "target_relation": "minimum",
            },
            {
                "direction": "discharge",
                "soc": 0.25,
                "current": 30.0,
                "diesel": 80.0,
                "settings": {
                    "storageDischargeDeratingCurve": [
                        {"soc": 0.10, "powerRatio": 0.00},
                        {"soc": 0.30, "powerRatio": 0.40},
                        {"soc": 0.40, "powerRatio": 1.00},
                    ]
                },
                "factor_key": "dischargeDeratingFactor",
                "power_key": "dischargePower",
                "expected_factor": 0.30,
                "expected_limit": 12.0,
                "target_relation": "maximum",
            },
        )
        for case in cases:
            with self.subTest(direction=case["direction"]):
                snapshot = renewable_snapshot()
                parameter = snapshot["device_parameters"]["DCStorageGen"][0]
                parameter["soc_lower_limit"] = 0.10
                parameter["soc_upper_limit"] = 0.90
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = case["soc"]
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = case["current"]
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = case["diesel"]

                plan = calculate_renewable_control_plan(
                    snapshot,
                    RenewableControlSettings().updated(case["settings"]),
                )
                row = next(
                    item
                    for item in plan["commandRows"]
                    if item.get("technology") == "storage"
                )
                target = float(row["commandKw"])

                self.assertAlmostEqual(
                    row[case["factor_key"]],
                    case["expected_factor"],
                    places=6,
                )
                self.assertAlmostEqual(
                    row[case["power_key"]],
                    case["expected_limit"],
                    places=6,
                )
                if case["target_relation"] == "minimum":
                    self.assertGreaterEqual(target, -case["expected_limit"] - 0.1)
                else:
                    self.assertLessEqual(target, case["expected_limit"] + 0.1)

    def test_ui_uses_percentage_power_protection_fields_and_new_solver_defaults(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("构网储能功率保护带(%)", html)
        self.assertIn('id="gridFormingStorageProtectionRatio"', html)
        self.assertIn(
            'id="storageSocCorrectionStepScale" type="number" min="10" max="100" step="0.1" value="20"',
            html,
        )
        self.assertIn("柴发功率保护带(%)", html)
        self.assertIn('id="dieselPowerProtectionRatio"', html)
        self.assertNotIn('id="storageSwitchDeadbandKw"', html)
        self.assertNotIn('id="dieselDeadbandRatio"', html)
        self.assertNotIn('id="optimizationConverterAdjustmentSquareWeight"', html)
        self.assertIn('id="optimizationCurtailmentSquareWeight" type="number" min="0" step="0.000001" value="0.000001"', html)
        self.assertIn('id="optimizationSourceStorageAdjustmentSquareWeight" type="number" min="0" step="0.000001" value="0.000001"', html)
        self.assertIn('id="optimizationBalanceDeltaSquareWeight" type="number" min="0" step="1000" value="10000"', html)
        self.assertIn('id="optimizationBalanceToleranceKw" type="number" min="0" step="0.1" value="0.1"', html)
        self.assertIn('id="optimizationBoundToleranceKw" type="number" min="0" step="0.1" value="0.1"', html)
        self.assertIn('id="optimizationFtol" type="number" min="0" step="0.001" value="0.001"', html)
        self.assertIn('id="optimizationMaxIterations" type="number" min="1" step="1" value="100"', html)

        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'storageSocCorrectionStepScale: ratio("storageSocCorrectionStepScale", 20, 10, 100)',
            script,
        )


if __name__ == "__main__":
    unittest.main()
