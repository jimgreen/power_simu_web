from __future__ import annotations

import json
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
        measurement("converter.p", "DCACConverter", "grid-converter-1", "P_AC", 5),
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

    def test_incremental_balance_uses_diesel_margin_and_storage_boundary_without_load(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselMinKw"], 20)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 125.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
        predicted_diesel = (
            plan["metrics"]["dieselCurrentKw"]
            - (plan["metrics"]["renewableTarget"] - plan["metrics"]["renewableCurrentKw"])
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
        converter_power["value"] = 10
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 45.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], 35.0)

    def test_converter_capacity_limits_storage_target_before_diesel_target_is_calculated(self):
        snapshot = renewable_snapshot()
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

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 50.0)
        self.assertAlmostEqual(plan["metrics"]["storageMinTargetKw"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["storageMaxTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -50.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 55.0)
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
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 90.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
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
        self.assertEqual(first_client["revision"], second_client["revision"])
        self.assertEqual(first_client["modelId"], "shared")
        self.assertTrue(any(item.get("result") == "方式切换" for item in runtime_logs))


if __name__ == "__main__":
    unittest.main()
