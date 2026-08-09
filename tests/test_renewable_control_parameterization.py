from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from simu.control_config import default_integer, default_number
from simu.renewable_control import RenewableControlSettings
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


if __name__ == "__main__":
    unittest.main()
