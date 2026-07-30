from __future__ import annotations

import json
import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
    calculate_renewable_control_plan,
)
from simu.server import make_http_server
from simu.service import MultiModelSimulator, SimulationModelSpec
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


def measurement(
    name: str,
    dev_type: str,
    dev_name: str,
    meas_type: str,
    value: float,
    *,
    valid: int = 1,
) -> dict:
    return {
        "name": name,
        "dev_type": dev_type,
        "dev_name": dev_name,
        "meas_type": meas_type,
        "value": value,
        "valid": valid,
    }


def renewable_snapshot() -> dict:
    devices = [
        {
            "dev_type": "ACGenerator",
            "dev_name": "wind-1",
            "run_stat": 1,
            "status": 1,
            "mode": "P",
            "set_types": ["p_set"],
            "raw": {"idx": "1", "rated_capacity": "100", "p_min": "0"},
        },
        {
            "dev_type": "DCGenerator",
            "dev_name": "pv-1",
            "run_stat": 1,
            "status": 1,
            "mode": "P",
            "set_types": ["p_set"],
            "raw": {"idx": "1", "rated_capacity": "80", "p_min": "0"},
        },
        {
            "dev_type": "DCGenerator",
            "dev_name": "storage-1",
            "run_stat": 1,
            "status": 1,
            "mode": "V",
            "set_types": ["v_set"],
            "raw": {"idx": "2", "rated_capacity": "100"},
        },
        {
            "dev_type": "ACGenerator",
            "dev_name": "diesel-1",
            "run_stat": 1,
            "status": 1,
            "mode": "PH",
            "set_types": ["p_set"],
            "raw": {"idx": "2", "dev_type": "diesel-source", "rated_capacity": "200", "p_min": "20"},
        },
        {
            "dev_type": "DCACConverter",
            "dev_name": "grid-converter-1",
            "run_stat": 1,
            "status": 1,
            "mode": "PQ",
            "set_types": ["p_ac_set"],
            "raw": {"idx": "1", "rated_capacity": "50", "ac_control_type": "PQ"},
        },
        {
            "dev_type": "ACLoad",
            "dev_name": "load-1",
            "run_stat": 1,
            "status": 1,
            "raw": {"idx": "1", "pv0": "999"},
        },
    ]
    scada = [
        measurement("wind.p", "ACGenerator", "wind-1", "P_GEN", 30),
        measurement("pv.p", "DCGenerator", "pv-1", "P_GEN", 20),
        measurement("storage.p", "DCGenerator", "storage-1", "P_GEN", -5),
        measurement("storage.soc", "DCGenerator", "storage-1", "SOC", 0.5),
        measurement("diesel.p", "ACGenerator", "diesel-1", "P_GEN", 60),
        measurement("converter.p", "DCACConverter", "grid-converter-1", "P_AC", 0),
        measurement("load.p", "ACLoad", "load-1", "P_LOAD", 100),
        measurement("weather.wind", "Environment", "weather", "WIND_SPEED", 8),
        measurement("weather.solar", "Environment", "weather", "SOLAR_IRRADIANCE", 500),
        measurement("weather.temp", "Environment", "weather", "AIR_TEMP", 25),
    ]
    return {
        "model": {"id": "renewable-model", "name": "Renewable Model"},
        "clock": {
            "state": "running",
            "time": "12:00:00",
            "minute": 720,
            "absolute_minute": 720,
            "step_minutes": 1,
            "run_id": 1,
        },
        "curve_boundary": {
            "target_minute": 720,
            "load_total": 999,
            "point": {
                "wind_speed_mps": 30,
                "solar_irradiance_w_m2": 1500,
                "air_temp_c": 25,
            },
        },
        "devices": devices,
        "measurements": {"scada": scada, "real": []},
        "device_parameters": {
            "ACWindGen": [
                {
                    "idx": 1,
                    "idx_acgenerator": 1,
                    "rated_power": 100,
                    "cut_in_wind_speed": 3,
                    "rated_wind_speed": 10,
                    "cut_out_wind_speed": 25,
                }
            ],
            "DCPVGen": [
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "module_efficiency": 0.2,
                    "array_area": 400,
                    "reference_irradiance": 1000,
                }
            ],
            "DCStorageGen": [
                {
                    "idx": 1,
                    "idx_dcgenerator": 2,
                    "energy_capacity": 100,
                    "charge_discharge_efficiency": 0.95,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                    "state_of_charge": 50,
                    "soc_upper_limit": 90,
                    "soc_lower_limit": 20,
                }
            ],
        },
        "definitions": {
            "control": {
                "SetValue": {
                    "rows": [
                        {"dev_type": "ACGenerator", "dev_name": "wind-1", "set_type": "p_set"},
                        {"dev_type": "DCGenerator", "dev_name": "pv-1", "set_type": "p_set"},
                        {"dev_type": "DCACConverter", "dev_name": "grid-converter-1", "set_type": "p_ac_set"},
                    ]
                }
            }
        },
        "settings": {"modes": []},
    }


class RenewableControlPlannerDataQualityTest(unittest.TestCase):
    def test_automatic_commands_default_to_two_hour_validity(self):
        settings = RenewableControlSettings()

        self.assertEqual(settings.command_valid_minutes, 120.0)
        self.assertEqual(settings.payload()["commandValidMinutes"], 120.0)

    def test_converter_step_ratio_is_configurable_and_exposed(self):
        settings = RenewableControlSettings().updated(
            {"converterStepRatio": 0.04, "storageStepRatio": 0.25}
        )

        self.assertAlmostEqual(settings.converter_step_ratio, 0.04)
        self.assertAlmostEqual(settings.payload()["converterStepRatio"], 0.04)
        self.assertFalse(hasattr(settings, "storage_step_ratio"))
        self.assertNotIn("storageStepRatio", settings.payload())

    def test_converter_soc_power_limits_default_and_payload(self):
        expected = [0.0, 0.0, 0.2, 0.4, 0.4, 0.5, 0.6, 0.8, 0.8, 1.0]

        settings = RenewableControlSettings()

        self.assertEqual(list(settings.converter_soc_power_limits), expected)
        self.assertEqual(settings.payload()["converterSocPowerLimits"], expected)

    def test_converter_soc_power_limits_reject_invalid_configurations(self):
        valid = [0.0, 0.0, 0.2, 0.4, 0.4, 0.5, 0.6, 0.8, 0.8, 1.0]
        invalid_cases = (
            valid[:-1],
            [*valid[:4], 0.25, *valid[5:]],
            [-0.1, *valid[1:]],
            [0.0, 0.2, 0.1, *valid[3:]],
        )

        for limits in invalid_cases:
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError):
                    RenewableControlSettings().updated(
                        {"converterSocPowerLimits": limits}
                    )

    def test_converter_forward_power_limit_uses_soc_piecewise_ratio_of_original_capacity(self):
        cases = (
            (-0.100, 0.00),
            (0.050, 0.00),
            (0.199, 0.00),
            (0.200, 0.20),
            (0.299, 0.20),
            (0.300, 0.40),
            (0.499, 0.40),
            (0.500, 0.50),
            (0.599, 0.50),
            (0.600, 0.60),
            (0.699, 0.60),
            (0.700, 0.80),
            (0.899, 0.80),
            (0.900, 1.00),
            (1.000, 1.00),
            (1.200, 1.00),
        )
        for soc, expected_ratio in cases:
            with self.subTest(soc=soc):
                snapshot = renewable_snapshot()
                storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
                storage_parameter["soc_lower_limit"] = 0
                storage_parameter["soc_upper_limit"] = 100
                storage_parameter["max_charge_power"] = 100
                storage_parameter["max_discharge_power"] = 100
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 0.0
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 200.0
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = 0.0

                plan = calculate_renewable_control_plan(
                    snapshot,
                    RenewableControlSettings(converter_step_ratio=1.0),
                )
                metrics = plan["metrics"]
                converter = next(row for row in plan["commandRows"] if row["category"] == "交直流变流器")
                expected_limit = 50.0 * expected_ratio

                self.assertAlmostEqual(metrics["converterRatedCapacityKw"], 50.0)
                self.assertAlmostEqual(metrics["converterSocLimitRatio"], expected_ratio)
                self.assertAlmostEqual(metrics["converterSocLimitKw"], expected_limit)
                self.assertAlmostEqual(metrics["converterTargetLowerLimitKw"], -expected_limit)
                self.assertAlmostEqual(metrics["converterTargetUpperLimitKw"], 0.0)
                self.assertAlmostEqual(metrics["acdcTargetKw"], -expected_limit)
                self.assertAlmostEqual(converter["availableKw"], expected_limit)
                self.assertAlmostEqual(converter["commandKw"], -expected_limit)

    def test_converter_forward_power_limit_uses_configured_soc_schedule(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 0
        storage_parameter["soc_upper_limit"] = 100
        storage_parameter["max_charge_power"] = 100
        storage_parameter["max_discharge_power"] = 100
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.35
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 0.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                converter_step_ratio=1.0,
                converter_soc_power_limits=(
                    0.0,
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.7,
                    0.8,
                    0.9,
                ),
            ),
        )

        self.assertAlmostEqual(plan["metrics"]["converterSocLimitRatio"], 0.3)
        self.assertAlmostEqual(plan["metrics"]["converterSocLimitKw"], 15.0)
        self.assertEqual(plan["metrics"]["converterSocBandIndex"], 3)
        self.assertEqual(plan["metrics"]["converterSocBandLowerPercent"], 30)
        self.assertEqual(plan["metrics"]["converterSocBandUpperPercent"], 40)
        self.assertAlmostEqual(plan["metrics"]["converterTargetLowerLimitKw"], -15.0)
        self.assertAlmostEqual(plan["metrics"]["converterTargetUpperLimitKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -15.0)
        self.assertTrue(
            any("当前SOC命中 30%-40% 区间" in line for line in plan["decisionDetail"])
        )

    def test_converter_automatic_target_never_requests_reverse_power(self):
        cases = (
            ("low_diesel", 0.50, 10.0, 0.0, 0.0),
            ("extreme_low_soc", 0.10, 60.0, 0.0, 0.0),
            ("existing_reverse_power", 0.50, 20.0, -5.0, 5.0),
        )
        for name, soc, diesel_current, storage_current, converter_current in cases:
            with self.subTest(name=name):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = diesel_current
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = storage_current
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot)
                converter_commands = [
                    row["commandKw"]
                    for row in plan["commandRows"]
                    if row["category"] == "交直流变流器"
                ]

                self.assertTrue(plan["metrics"]["converterReversePowerForbidden"])
                self.assertAlmostEqual(plan["metrics"]["converterTargetUpperLimitKw"], 0.0)
                self.assertLessEqual(plan["metrics"]["acdcDesiredTargetKw"], 0.0)
                self.assertLessEqual(plan["metrics"]["acdcTargetKw"], 0.0)
                self.assertTrue(all(value <= 0.0 for value in converter_commands))
                self.assertTrue(any("禁止交流侧向直流侧倒送" in line for line in plan["decisionDetail"]))

    def test_existing_reverse_converter_power_is_commanded_directly_to_zero(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -5.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 12.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.01),
        )

        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], 12.0)
        self.assertAlmostEqual(plan["metrics"]["acdcDesiredTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertTrue(plan["metrics"]["converterHardLimitApplied"])

    def test_lower_soc_deadband_slows_converter_increase_but_not_decrease(self):
        settings = RenewableControlSettings(converter_step_ratio=0.10)

        cases = (
            ("decrease", 0.25, 0.0, 1.0, -5.0),
            ("increase", 0.20, -5.0, 0.20, 1.0),
        )
        for direction, soc, converter_current, expected_scale, expected_adjustment in cases:
            with self.subTest(direction=direction, soc=soc):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 10.0
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertTrue(metrics["lowerSocDeadbandActive"])
                self.assertAlmostEqual(metrics["converterBaseStepKw"], 5.0)
                self.assertEqual(metrics["converterStepDirection"], direction)
                self.assertAlmostEqual(metrics["converterStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["converterStepKw"], 5.0 * expected_scale)
                self.assertAlmostEqual(metrics["acdcAdjustmentKw"], expected_adjustment)
                detail = "\n".join(plan["decisionDetail"])
                expected_text = (
                    "SOC下限死区内升功率，采用20%步长"
                    if direction == "increase"
                    else "SOC下限死区内降功率，保持原步长"
                )
                self.assertIn(expected_text, detail)

    def test_upper_soc_deadband_slows_renewable_increase_but_not_decrease(self):
        settings = RenewableControlSettings(step_coefficient=0.10)

        cases = (
            ("increase", 0.85, 60.0, -5.0, 0.20, 53.6),
            ("decrease", 0.90, 20.0, -10.0, 1.0, 32.0),
        )
        for direction, soc, diesel_current, storage_current, expected_scale, expected_target in cases:
            with self.subTest(direction=direction, soc=soc):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = diesel_current
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = storage_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertTrue(metrics["upperSocDeadbandActive"])
                self.assertEqual(metrics["renewableStepDirection"], direction)
                self.assertAlmostEqual(metrics["renewableStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["renewableEffectiveStepRatio"], 0.10 * expected_scale)
                self.assertAlmostEqual(metrics["renewableTarget"], expected_target)
                detail = "\n".join(plan["decisionDetail"])
                expected_text = (
                    "SOC上限死区内升功率，采用20%步长"
                    if direction == "increase"
                    else "SOC上限死区内降功率，保持原步长"
                )
                self.assertIn(expected_text, detail)

    def test_diesel_deadband_slows_converter_increase_but_not_decrease(self):
        settings = RenewableControlSettings(
            converter_step_ratio=0.10,
            diesel_deadband_ratio=0.10,
        )
        cases = (
            ("decrease", 0.96, 0.0, None, 1.0, -5.0),
            ("increase", 0.20, -5.0, 40.0, 0.20, 1.0),
        )
        for direction, soc, converter_current, soc_lower_limit, expected_scale, expected_adjustment in cases:
            with self.subTest(direction=direction, soc=soc):
                snapshot = renewable_snapshot()
                if soc_lower_limit is not None:
                    snapshot["device_parameters"]["DCStorageGen"][0]["soc_lower_limit"] = soc_lower_limit
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 0.0
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 20.0
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertFalse(metrics["lowerSocDeadbandActive"])
                self.assertTrue(metrics["dieselDeadbandActive"])
                self.assertEqual(metrics["converterStepDirection"], direction)
                self.assertAlmostEqual(metrics["converterBaseStepKw"], 5.0)
                self.assertAlmostEqual(metrics["converterStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["converterStepKw"], 5.0 * expected_scale)
                self.assertAlmostEqual(metrics["acdcAdjustmentKw"], expected_adjustment)
                detail = "\n".join(plan["decisionDetail"])
                expected_text = (
                    "柴发下限死区内升功率，采用20%步长"
                    if direction == "increase"
                    else "柴发下限死区内降功率，保持原步长"
                )
                self.assertIn(expected_text, detail)

    def test_removed_charge_source_threshold_settings_are_not_exposed(self):
        settings = RenewableControlSettings().updated(
            {
                "renewableNearZeroRatio": 0.5,
                "renewableChargeReserveRatio": 0.5,
            }
        )

        self.assertFalse(hasattr(settings, "renewable_near_zero_ratio"))
        self.assertFalse(hasattr(settings, "renewable_charge_reserve_ratio"))
        self.assertNotIn("renewableNearZeroRatio", settings.payload())
        self.assertNotIn("renewableChargeReserveRatio", settings.payload())

    def test_environment_measurements_are_ignored_by_default_control_policy(self):
        plan = calculate_renewable_control_plan(renewable_snapshot())

        self.assertEqual(plan["metrics"]["loadKw"], 100)
        self.assertIsNone(plan["weather"]["windSpeed"])
        self.assertIsNone(plan["weather"]["solarIrradiance"])
        self.assertIsNone(plan["weather"]["airTemp"])
        self.assertEqual(plan["weather"]["observedWindSpeed"], 8)
        self.assertEqual(plan["weather"]["observedSolarIrradiance"], 500)
        self.assertEqual(plan["weather"]["observedAirTemp"], 25)
        self.assertEqual(plan["dataQuality"]["inputs"]["load"]["source"], "scada")
        self.assertEqual(
            plan["dataQuality"]["inputs"]["windSpeed"]["source"],
            "ignored_by_control_policy",
        )
        self.assertFalse(plan["dataQuality"]["inputs"]["windSpeed"]["valid"])
        self.assertGreater(plan["metrics"]["recoveryKw"], 0)
        self.assertEqual(plan["dataQuality"]["status"], "ok")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_signed_realtime_power_values_are_preserved_for_every_control_category(self):
        snapshot = renewable_snapshot()
        signed_values = {
            ("wind-1", "P_GEN"): -3.0,
            ("pv-1", "P_GEN"): -4.0,
            ("storage-1", "P_GEN"): -5.0,
            ("diesel-1", "P_GEN"): -6.0,
            ("grid-converter-1", "P_AC"): -8.0,
            ("load-1", "P_LOAD"): -7.0,
        }
        for row in snapshot["measurements"]["scada"]:
            key = (row["dev_name"], row["meas_type"])
            if key in signed_values:
                row["value"] = signed_values[key]

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertAlmostEqual(metrics["windCurrentKw"], -3.0)
        self.assertAlmostEqual(metrics["pvCurrentKw"], -4.0)
        self.assertAlmostEqual(metrics["renewableCurrentKw"], -7.0)
        self.assertAlmostEqual(metrics["dieselCurrentKw"], -6.0)
        self.assertAlmostEqual(metrics["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(metrics["acdcCurrentKw"], -8.0)
        self.assertAlmostEqual(metrics["loadKw"], -7.0)
        self.assertLess(metrics["dieselTargetKw"], 0.0)

        current_by_category = {
            row["category"]: row.get("currentKw")
            for row in plan["commandRows"]
            if row.get("category") in {"风电", "光伏", "储能平衡源", "柴油发电", "交直流变流器"}
        }
        self.assertAlmostEqual(current_by_category["风电"], -3.0)
        self.assertAlmostEqual(current_by_category["光伏"], -4.0)
        self.assertAlmostEqual(current_by_category["储能平衡源"], -5.0)
        self.assertAlmostEqual(current_by_category["柴油发电"], -6.0)
        self.assertAlmostEqual(current_by_category["交直流变流器"], -8.0)

    def test_environment_presence_or_value_does_not_change_control_targets(self):
        baseline = calculate_renewable_control_plan(renewable_snapshot())
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if row["meas_type"] not in {"WIND_SPEED", "SOLAR_IRRADIANCE", "AIR_TEMP"}
        ]

        without_environment = calculate_renewable_control_plan(snapshot)
        changed_snapshot = renewable_snapshot()
        for row in changed_snapshot["measurements"]["scada"]:
            if row["meas_type"] == "WIND_SPEED":
                row["value"] = 70
            elif row["meas_type"] == "SOLAR_IRRADIANCE":
                row["value"] = 1500
            elif row["meas_type"] == "AIR_TEMP":
                row["value"] = 90
        changed_environment = calculate_renewable_control_plan(changed_snapshot)

        for metric in ("renewableTarget", "storageTarget", "acdcTargetKw", "dieselTargetKw"):
            self.assertAlmostEqual(without_environment["metrics"][metric], baseline["metrics"][metric])
            self.assertAlmostEqual(changed_environment["metrics"][metric], baseline["metrics"][metric])
        self.assertTrue(any("默认不参与新能源控制" in warning for warning in baseline["warnings"]))

    def test_live_soc_ratio_above_one_is_preserved_and_blocks_charging(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 3.358

        plan = calculate_renewable_control_plan(snapshot)
        storage = next(row for row in plan["commandRows"] if row["category"] == "储能平衡源")

        self.assertAlmostEqual(plan["metrics"]["storageSoc"], 3.358)
        self.assertAlmostEqual(storage["soc"], 3.358)
        self.assertEqual(storage["chargePower"], 0)
        self.assertGreater(storage["dischargePower"], 0)

    def test_soc_above_upper_limit_increases_storage_discharge_by_one_step(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 1.3
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN"
        )["value"] = 100
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN"
        )["value"] = 80
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN"
        )["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)
        storage = next(row for row in plan["commandRows"] if row["category"] == "储能平衡源")

        self.assertEqual(storage["chargePower"], 0)
        self.assertEqual(storage["socConstraint"], "above_upper")
        self.assertAlmostEqual(storage["dischargePower"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)
        for category in ("风电", "光伏", "交直流变流器"):
            rows = [row for row in plan["commandRows"] if row["category"] == category]
            self.assertTrue(rows)
            self.assertTrue(all(isinstance(row.get("commandKw"), (int, float)) for row in rows))
        self.assertTrue(any("SOC运行约束" in line and "禁止充电" in line for line in plan["decisionDetail"]))

    def test_soc_above_upper_plus_deadband_actively_increases_discharge_in_diesel_deadband(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.96
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertTrue(plan["metrics"]["socAboveUpperDeadband"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "increase_discharge_above_soc_upper_deadband",
        )
        self.assertTrue(plan["metrics"]["dieselDeadbandActive"])
        self.assertEqual(plan["metrics"]["converterStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 1.5)

    def test_soc_at_upper_immediately_stops_reverse_converter_power(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.94
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertFalse(plan["metrics"]["socAboveUpperDeadband"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "stop_reverse_power")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertTrue(plan["metrics"]["dieselDeadbandActive"])
        self.assertTrue(plan["metrics"]["converterReversePowerDetected"])
        self.assertEqual(plan["metrics"]["converterStepDirection"], "hold")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)

    def test_model_soc_limits_override_controller_default_limits(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 10
        storage_parameter["soc_upper_limit"] = 95
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 0.05

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(soc_min=0.3, soc_max=0.8),
        )
        storage = next(row for row in plan["commandRows"] if row["category"] == "储能平衡源")

        self.assertAlmostEqual(storage["socMin"], 0.1)
        self.assertAlmostEqual(storage["socMax"], 0.95)
        self.assertEqual(storage["socConstraint"], "below_lower")
        self.assertEqual(storage["dischargePower"], 0)
        self.assertGreater(storage["chargePower"], 0)
        self.assertTrue(any("SOC运行约束" in line and "禁止放电" in line for line in plan["decisionDetail"]))

    def test_diesel_deadband_holds_existing_storage_power_at_upper_boundary(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN":
                row["value"] = 100
            elif row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN":
                row["value"] = 80
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -3
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertAlmostEqual(plan["metrics"]["storageDesiredTargetKw"], -3.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")

    def test_high_diesel_output_increases_storage_discharge_when_renewables_are_fully_recovered(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN":
                row["value"] = 100
            elif row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN":
                row["value"] = 80
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "high")
        self.assertEqual(plan["metrics"]["storageControlAction"], "increase_discharge")
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)

    def test_high_diesel_controls_renewable_and_acdc_independently(self):
        snapshot = renewable_snapshot()
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["meas_type"] == "P_GEN" and row["dev_name"] == "storage-1"
        )["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertGreater(plan["metrics"]["renewableTarget"], plan["metrics"]["renewableCurrentKw"])
        self.assertGreater(plan["metrics"]["storageTarget"], plan["metrics"]["storageCurrentKw"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "increase_discharge",
        )
        self.assertFalse(plan["metrics"]["renewableStorageCoordinationActive"])
        self.assertAlmostEqual(plan["metrics"]["storageRenewableCoordinationKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)
        self.assertFalse(any("新能源储能协调" in line for line in plan["decisionDetail"]))
        self.assertTrue(any("两条策略相互独立" in line for line in plan["decisionDetail"]))

    def test_diesel_floor_holds_acdc_and_recovers_renewable_when_soc_has_space(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")

    def test_diesel_floor_does_not_force_extra_acdc_charging_when_soc_has_space(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -5
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")

    def test_soc_above_lower_limit_still_allows_high_diesel_discharge_step(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 0.22
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "P_GEN" and row["dev_name"] == "storage-1")["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["storageSocRegion"], "low_guard")
        self.assertEqual(plan["metrics"]["storageControlAction"], "increase_discharge")
        self.assertTrue(plan["metrics"]["lowerSocDeadbandActive"])
        self.assertEqual(plan["metrics"]["converterStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)

    def test_soc_below_twenty_percent_forces_converter_target_to_zero(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.15
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["storageSocRegion"], "below_lower")
        self.assertFalse(plan["metrics"]["dieselEmergencyChargeAllowed"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold_at_soc_lower")
        self.assertAlmostEqual(plan["metrics"]["converterSocLimitRatio"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["converterSocLimitKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)

    def test_soc_below_twenty_percent_stops_existing_converter_injection(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.5
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -0.5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(plan["metrics"]["socBelowLowerDeadband"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "stop_discharge_below_soc_lower_deadband",
        )
        self.assertAlmostEqual(plan["metrics"]["converterSocLimitRatio"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], -0.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], 0.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)

    def test_diesel_deadband_holds_acdc_while_renewable_recovers(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN")["value"] = 23
        next(row for row in snapshot["measurements"]["scada"] if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN")["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 23.0)

    def test_soc_below_upper_and_high_diesel_recovers_renewable_and_increases_discharge(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 0.87
        next(row for row in snapshot["measurements"]["scada"] if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN")["value"] = -10

        plan = calculate_renewable_control_plan(snapshot)
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        pv = next(row for row in plan["commandRows"] if row["dev_name"] == "pv-1")

        self.assertEqual(plan["metrics"]["storageSocRegion"], "high_guard")
        self.assertEqual(plan["metrics"]["dieselControlRegion"], "high")
        self.assertEqual(plan["metrics"]["renewableControlAction"], "recover_one_step")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertAlmostEqual(wind["commandKw"], 30.6)
        self.assertAlmostEqual(pv["commandKw"], 20.48)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -8.5)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)

    def test_soc_below_upper_in_diesel_deadband_recovers_renewable_and_holds_acdc(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.87
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 23

        plan = calculate_renewable_control_plan(snapshot)
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        pv = next(row for row in plan["commandRows"] if row["dev_name"] == "pv-1")

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertEqual(plan["metrics"]["renewableControlAction"], "recover_one_step")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertAlmostEqual(wind["commandKw"], 30.6)
        self.assertAlmostEqual(pv["commandKw"], 20.48)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 23.0)

    def test_full_soc_at_diesel_floor_curtails_one_full_decrease_step(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.90
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["renewableControlAction"], "curtail_one_step_full_soc")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertTrue(plan["metrics"]["dieselDeadbandActive"])
        self.assertEqual(plan["metrics"]["renewableStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["renewableStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 44.6)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -8.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 18.5)

    def test_full_soc_decrease_steps_are_not_reduced_by_deadbands(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.90
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.20),
        )

        self.assertEqual(plan["metrics"]["renewableStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["renewableStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["renewableEffectiveStepRatio"], 0.03)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 44.6)
        self.assertEqual(plan["metrics"]["converterStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["highSocStorageBalanceLimitKw"], 0.0)

    def test_low_diesel_does_not_request_reverse_power_when_converter_is_idle(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "low")
        self.assertEqual(plan["metrics"]["renewableControlAction"], "recover_one_step")
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold_low_diesel")
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselCurrentKw"])
        self.assertLess(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselMinKw"])
        self.assertFalse(plan["metrics"]["dieselViolationImproved"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_low_diesel_reduces_converter_injection_while_renewable_recovers(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["renewableControlAction"], "recover_one_step")
        self.assertGreater(plan["metrics"]["renewableTarget"], plan["metrics"]["renewableCurrentKw"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "reduce_discharge_low_diesel")
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -3.5)
        self.assertLessEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -1.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 11.5)
        self.assertTrue(plan["metrics"]["dieselViolationImproved"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_low_soc_never_requests_reverse_power_even_with_diesel_headroom(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 199.5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["dieselUpMarginKw"], 0.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertFalse(plan["metrics"]["dieselEmergencyChargeAllowed"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "reverse_power_forbidden_below_soc_lower_deadband")
        self.assertLessEqual(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselCapacityKw"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_low_soc_target_is_zero_without_diesel_upward_headroom(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["dieselUpMarginKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertFalse(plan["metrics"]["dieselEmergencyChargeAllowed"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "reverse_power_forbidden_below_soc_lower_deadband")

    def test_extreme_low_soc_reports_zero_converter_capacity_limit(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["converterSocLimitRatio"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["converterSocLimitKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["converterTargetLowerLimitKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["converterTargetUpperLimitKw"], 0.0)

    def test_extreme_low_soc_keeps_storage_feedback_without_direct_storage_control(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -5
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageDesiredTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageCandidateTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -5.0)
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "reverse_power_forbidden_below_soc_lower_deadband",
        )
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)

    def test_planner_has_no_dwell_or_pending_feedback_state_contract(self):
        signature = inspect.signature(calculate_renewable_control_plan)
        plan = calculate_renewable_control_plan(renewable_snapshot())

        self.assertNotIn("control_state", signature.parameters)
        self.assertNotIn("feedbackState", plan)
        self.assertNotIn("dispatchReady", plan)

    def test_load_value_and_validity_do_not_change_control_targets(self):
        baseline_snapshot = renewable_snapshot()
        baseline = calculate_renewable_control_plan(baseline_snapshot)
        changed_snapshot = renewable_snapshot()
        load_row = next(row for row in changed_snapshot["measurements"]["scada"] if row["meas_type"] == "P_LOAD")
        load_row["value"] = 900
        load_row["valid"] = 0
        changed_snapshot["curve_boundary"]["load_total"] = 1200

        changed = calculate_renewable_control_plan(changed_snapshot)

        self.assertEqual(changed["metrics"]["loadKw"], 1200)
        self.assertEqual(changed["dataQuality"]["inputs"]["load"]["source"], "curve_boundary")
        for metric in ("renewableTarget", "storageTarget", "acdcTargetKw", "dieselTargetKw"):
            self.assertAlmostEqual(changed["metrics"][metric], baseline["metrics"][metric])
        self.assertEqual(changed["dataQuality"]["dispatchAllowed"], baseline["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("负荷功率仅用于展示" in line for line in changed["decisionDetail"]))

    def test_missing_live_renewable_power_blocks_dispatch_even_when_weather_is_known(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN")
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("风电wind-1" in issue and "实时有功" in issue for issue in plan["dataQuality"]["issues"]))

    def test_non_commandable_renewable_is_kept_at_live_power_not_assumed_capability(self):
        snapshot = renewable_snapshot()
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] == "DCACConverter"
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableCurrentKw"], 50.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 50.0)
        renewable_rows = [row for row in plan["commandRows"] if row["category"] in {"风电", "光伏"}]
        self.assertTrue(all(row["commandable"] is False for row in renewable_rows))

    def test_environment_curve_parameters_do_not_block_default_recovery_strategy(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["ACWindGen"][0].pop("cut_in_wind_speed")

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "ok")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        self.assertIsNotNone(wind["commandKw"])
        self.assertFalse(any("风电wind-1" in issue and "最大可发" in issue for issue in plan["dataQuality"]["issues"]))

    def test_missing_converter_capacity_is_inferred_from_storage_power_boundary(self):
        missing_capacity = renewable_snapshot()
        converter = next(row for row in missing_capacity["devices"] if row["dev_type"] == "DCACConverter")
        converter["raw"].pop("rated_capacity")

        capacity_plan = calculate_renewable_control_plan(missing_capacity)
        converter_row = next(
            row for row in capacity_plan["commandRows"] if row["dev_type"] == "DCACConverter"
        )

        self.assertTrue(capacity_plan["dataQuality"]["dispatchAllowed"])
        self.assertEqual(capacity_plan["dataQuality"]["status"], "ok")
        self.assertAlmostEqual(converter_row["transferCapacityKw"], 40.0)
        self.assertEqual(converter_row["capacitySource"], "storage_boundary")
        self.assertFalse(any("变流器" in issue and "容量" in issue for issue in capacity_plan["dataQuality"]["issues"]))

    def test_parallel_converters_share_inferred_storage_power_boundary(self):
        snapshot = renewable_snapshot()
        first_converter = next(row for row in snapshot["devices"] if row["dev_type"] == "DCACConverter")
        first_converter["raw"].pop("rated_capacity")
        snapshot["devices"].append(
            {
                **first_converter,
                "dev_name": "grid-converter-2",
                "raw": {"idx": "2", "ac_control_type": "PQ"},
            }
        )
        snapshot["measurements"]["scada"].append(
            measurement("converter-2.p", "DCACConverter", "grid-converter-2", "P_AC", 0)
        )
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {"dev_type": "DCACConverter", "dev_name": "grid-converter-2", "set_type": "p_ac_set"}
        )

        plan = calculate_renewable_control_plan(snapshot)
        converter_rows = [row for row in plan["commandRows"] if row["dev_type"] == "DCACConverter"]

        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertEqual(len(converter_rows), 2)
        self.assertTrue(all(row["capacitySource"] == "storage_boundary" for row in converter_rows))
        self.assertTrue(all(abs(row["transferCapacityKw"] - 20.0) < 1e-9 for row in converter_rows))
        self.assertAlmostEqual(sum(row["commandKw"] for row in converter_rows), plan["metrics"]["acdcTargetKw"])

    def test_missing_converter_live_power_forbids_closed_loop_dispatch(self):
        missing_power = renewable_snapshot()

        missing_power["measurements"]["scada"] = [
            row
            for row in missing_power["measurements"]["scada"]
            if not (row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC")
        ]

        power_plan = calculate_renewable_control_plan(missing_power)

        self.assertFalse(power_plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("变流器" in issue and "实时有功" in issue for issue in power_plan["dataQuality"]["issues"]))

    def test_scada_noise_near_rated_capacity_is_clamped_without_quality_warning(self):
        snapshot = renewable_snapshot()
        wind_device = next(row for row in snapshot["devices"] if row["dev_name"] == "wind-1")
        wind_device["raw"]["rated_capacity"] = "10.1"
        snapshot["device_parameters"]["ACWindGen"][0]["rated_power"] = 10.1
        wind_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN"
        )
        wind_power["value"] = 10.12
        wind_power["weight"] = 10000

        plan = calculate_renewable_control_plan(snapshot)
        wind_row = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")

        self.assertAlmostEqual(wind_row["currentKw"], 10.12)
        self.assertAlmostEqual(wind_row["planningCurrentKw"], 10.1)
        self.assertEqual(plan["dataQuality"]["status"], "ok")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertFalse(any("风电wind-1" in issue and "额定容量" in issue for issue in plan["dataQuality"]["issues"]))

    def test_material_generation_overcapacity_remains_quality_warning(self):
        snapshot = renewable_snapshot()
        wind_device = next(row for row in snapshot["devices"] if row["dev_name"] == "wind-1")
        wind_device["raw"]["rated_capacity"] = "10.1"
        snapshot["device_parameters"]["ACWindGen"][0]["rated_power"] = 10.1
        wind_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN"
        )
        wind_power["value"] = 10.5
        wind_power["weight"] = 10000

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "degraded")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("风电wind-1" in issue and "额定容量" in issue for issue in plan["dataQuality"]["issues"]))

    def test_unknown_environment_and_missing_live_power_blocks_dispatch(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (
                row["dev_name"] == "wind-1"
                or row["meas_type"] in {"WIND_SPEED", "SOLAR_IRRADIANCE"}
            )
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        self.assertIsNone(wind["commandKw"])

    def test_unknown_environment_recovery_does_not_preconsume_diesel_margin_needed_by_storage(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselMinKw"], 20)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["renewableDeltaKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["renewableBalancingDeltaKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -1.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)
        predicted_diesel = (
            plan["metrics"]["dieselCurrentKw"]
            - (plan["metrics"]["storageTarget"] - plan["metrics"]["storageCurrentKw"])
        )
        self.assertAlmostEqual(predicted_diesel, plan["metrics"]["dieselTargetKw"])

    def test_converter_target_uses_live_power_as_incremental_storage_baseline(self):
        snapshot = renewable_snapshot()
        converter_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC"
        )
        converter_power["value"] = -10
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.5)
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], -10.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -11.5)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], -1.5)

    def test_converter_step_limits_effective_storage_adjustment(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.95
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.01),
        )

        self.assertAlmostEqual(plan["metrics"]["storageDesiredTargetKw"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 0.5)
        self.assertTrue(plan["metrics"]["converterStepLimited"])
        self.assertAlmostEqual(plan["metrics"]["acdcDesiredTargetKw"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -0.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 59.5)

    def test_converter_capacity_limits_storage_target_before_diesel_target_is_calculated(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["DCStorageGen"][0]["soc_upper_limit"] = 100
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] == "DCACConverter"
        ]
        converter_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC"
        )
        converter_power["value"] = -45
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["meas_type"] == "SOC"
        )["value"] = 0.95

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 50.0)
        self.assertAlmostEqual(plan["metrics"]["storageMinTargetKw"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["storageMaxTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -46.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_storage_power_is_held_when_no_online_power_control_converter_exists(self):
        snapshot = renewable_snapshot()
        snapshot["devices"] = [
            row for row in snapshot["devices"] if row["dev_type"] != "DCACConverter"
        ]
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
            if row["dev_type"] != "DCACConverter"
        ]
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] != "DCACConverter"
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageMinTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageMaxTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["renewableBalancingDeltaKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 60.0)
        self.assertEqual(plan["metrics"]["storageConverterCount"], 0)
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])

    def test_missing_online_diesel_power_blocks_closed_loop_dispatch(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN")
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("柴油" in issue and "实时有功" in issue for issue in plan["dataQuality"]["issues"]))


class RenewableControlBackendApiTest(unittest.TestCase):
    def test_same_simulation_time_dispatches_control_strategy_at_most_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {
                        "teacher_api_base": "http://teacher.invalid",
                        "snapshot_path": "/api/snapshot",
                        "command_path": "/api/student/commands",
                    },
                },
            )()

            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []

            def request_json(url, *, method="GET", payload=None):
                dispatched.append({"url": url, "method": method, "payload": payload})
                return {"set_values": len((payload or {}).get("set_values", []))}

            manager = TraineeRenewableControlManager(
                services,
                request_json=request_json,
                start_worker=False,
            )
            snapshot = renewable_snapshot()
            manager._snapshot_for_calculation = lambda _model_id: (snapshot, "remote", 0.0, None)
            manager._state_for("shared").loop_mode = "closed"
            try:
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
                self.assertEqual(len(dispatched), 1)
                self.assertEqual(
                    manager.state("shared")["lastDispatchedClockKey"],
                    "1|720|12:00:00",
                )

                snapshot["clock"]["absolute_minute"] += 1
                snapshot["clock"]["minute"] += 1
                snapshot["clock"]["time"] = "12:01:00"
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)

                snapshot["clock"].update(
                    {
                        "absolute_minute": 720,
                        "minute": 720,
                        "time": "12:00:00",
                        "run_id": 2,
                    }
                )
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
            finally:
                manager.close()

        self.assertEqual(len(dispatched), 3)

    def test_control_parameters_and_loop_mode_reload_from_model_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            model_root = source_root / "shared"
            model_root.mkdir(parents=True)
            for source in SIMPLE_MODEL_SOURCE.iterdir():
                if source.is_file():
                    (model_root / source.name).write_bytes(source.read_bytes())
            spec = SimulationModelSpec("shared", model_root, "Shared")
            runtime_root = root / "runtime"

            services = MultiModelSimulator(
                [spec],
                runtime_dir=runtime_root,
                models_root=source_root,
                kernel=lambda _config: None,
            )
            manager = TraineeRenewableControlManager(services, start_worker=False)
            try:
                manager.apply_action(
                    "shared",
                    {
                        "action": "update_settings",
                        "settings": {
                            "intervalSeconds": 1,
                            "renewableStepRatio": 0.10,
                            "converterStepRatio": 0.05,
                            "dieselDeadbandRatio": 0.04,
                            "socDeadband": 0.05,
                            "converterSocPowerLimits": [
                                0.0,
                                0.1,
                                0.2,
                                0.3,
                                0.4,
                                0.5,
                                0.6,
                                0.7,
                                0.8,
                                0.9,
                            ],
                        },
                    },
                )
                manager.apply_action("shared", {"action": "set_loop_mode", "loop_mode": "closed"})
                persistence_file = services.service_for("shared").runtime_dir / "renewable_control.json"
                self.assertTrue(persistence_file.exists())
            finally:
                manager.close()

            reloaded_services = MultiModelSimulator(
                [spec],
                runtime_dir=runtime_root,
                models_root=source_root,
                kernel=lambda _config: None,
            )
            reloaded_manager = TraineeRenewableControlManager(reloaded_services, start_worker=False)
            try:
                state = reloaded_manager.state("shared")
            finally:
                reloaded_manager.close()

        self.assertFalse(state["enabled"])
        self.assertEqual(state["loopMode"], "closed")
        self.assertEqual(state["settings"]["intervalSeconds"], 1.0)
        self.assertEqual(state["settings"]["renewableStepRatio"], 0.10)
        self.assertEqual(state["settings"]["converterStepRatio"], 0.05)
        self.assertEqual(state["settings"]["dieselDeadbandRatio"], 0.04)
        self.assertEqual(state["settings"]["socDeadband"], 0.05)
        self.assertEqual(
            state["settings"]["converterSocPowerLimits"],
            [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        )

    def test_invalid_converter_soc_limits_do_not_replace_persisted_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {},
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = TraineeRenewableControlManager(services, start_worker=False)
            valid = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
            try:
                manager.apply_action(
                    "shared",
                    {
                        "action": "update_settings",
                        "settings": {"converterSocPowerLimits": valid},
                    },
                )
                persisted_path = Path(temporary) / "renewable_control.json"
                persisted_before = persisted_path.read_text(encoding="utf-8")

                with self.assertRaises(ValueError):
                    manager.apply_action(
                        "shared",
                        {
                            "action": "update_settings",
                            "settings": {
                                "converterSocPowerLimits": [
                                    0.0,
                                    0.2,
                                    0.1,
                                    0.3,
                                    0.4,
                                    0.5,
                                    0.6,
                                    0.7,
                                    0.8,
                                    0.9,
                                ]
                            },
                        },
                    )

                state = manager.state("shared")
                persisted_after = persisted_path.read_text(encoding="utf-8")
            finally:
                manager.close()

        self.assertEqual(state["settings"]["converterSocPowerLimits"], valid)
        self.assertEqual(persisted_after, persisted_before)

    def test_converter_soc_limits_are_isolated_between_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = {}
            for model_id in ("first", "second"):
                runtime_dir = root / model_id
                runtime_dir.mkdir()
                targets[model_id] = type(
                    f"{model_id.title()}TargetService",
                    (),
                    {
                        "model_id": model_id,
                        "runtime_dir": runtime_dir,
                        "trainee_receive_state": lambda self: {},
                    },
                )()

            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, model_id: targets[str(model_id)],
                    "iter_services": lambda self: list(targets.values()),
                },
            )()
            first_limits = [0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0]
            second_limits = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
            manager = TraineeRenewableControlManager(services, start_worker=False)
            try:
                manager.apply_action(
                    "first",
                    {
                        "action": "update_settings",
                        "settings": {"converterSocPowerLimits": first_limits},
                    },
                )
                manager.apply_action(
                    "second",
                    {
                        "action": "update_settings",
                        "settings": {"converterSocPowerLimits": second_limits},
                    },
                )
                first_state = manager.state("first")
                second_state = manager.state("second")
            finally:
                manager.close()

        self.assertEqual(first_state["settings"]["converterSocPowerLimits"], first_limits)
        self.assertEqual(second_state["settings"]["converterSocPowerLimits"], second_limits)

    def test_two_web_clients_read_and_operate_one_shared_backend_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            model_root = source_root / "shared"
            model_root.mkdir(parents=True)
            for source in SIMPLE_MODEL_SOURCE.iterdir():
                if source.is_file():
                    (model_root / source.name).write_bytes(source.read_bytes())
            services = MultiModelSimulator(
                [SimulationModelSpec("shared", model_root, "Shared")],
                runtime_dir=root / "runtime",
                models_root=source_root,
                kernel=lambda _config: None,
            )
            manager = TraineeRenewableControlManager(services, start_worker=False)
            server = make_http_server(
                ("127.0.0.1", 0),
                services,
                role="trainee",
                renewable_control_manager=manager,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(
                    f"{base}/api/trainee/renewable-control?model_id=shared",
                    data=json.dumps({"action": "set_loop_mode", "loop_mode": "closed"}).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=5) as response:
                    first_client = json.loads(response.read().decode("utf-8"))
                limits = [0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0]
                settings_request = Request(
                    f"{base}/api/trainee/renewable-control?model_id=shared",
                    data=json.dumps(
                        {
                            "action": "update_settings",
                            "settings": {"converterSocPowerLimits": limits},
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(settings_request, timeout=5) as response:
                    updated_client = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"{base}/api/trainee/renewable-control?model_id=shared",
                    timeout=5,
                ) as response:
                    second_client = json.loads(response.read().decode("utf-8"))
                runtime_logs = list(services.service_for("shared").runtime_logs)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(first_client["loopMode"], "closed")
        self.assertEqual(second_client["loopMode"], "closed")
        self.assertEqual(updated_client["revision"], second_client["revision"])
        self.assertEqual(updated_client["settings"]["converterSocPowerLimits"], limits)
        self.assertEqual(second_client["settings"]["converterSocPowerLimits"], limits)
        self.assertEqual(first_client["modelId"], "shared")
        self.assertTrue(any(item.get("result") == "方式切换" for item in runtime_logs))


if __name__ == "__main__":
    unittest.main()
