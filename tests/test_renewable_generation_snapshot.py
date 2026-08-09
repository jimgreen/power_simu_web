from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import simu_loop
from simu.generate_simple_model import write_model_dir
from simu.renewable_control import RenewableControlSettings, calculate_renewable_control_plan
from simu.service import PolarMicrogridSimulator
from tests.test_trainee_renewable_backend_control import renewable_snapshot


class AutomaticStrategyGenerationTest(unittest.TestCase):
    def _service(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        return PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

    @staticmethod
    def _ess_value(service: PolarMicrogridSimulator) -> str:
        values = service.latest_control_values()["values"]
        return str(values["ESS.ess01.p_set"])

    def test_empty_generation_atomically_replaces_previous_snapshot(self):
        service = self._service()

        first = service.apply_student_commands(
            {
                "command_origin": "automatic",
                "strategy_id": "renewable_priority",
                "generation": 1,
                "replace_strategy_generation": True,
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 20,
                    }
                ],
            },
            source="trainee-renewable-priority-backend",
        )
        self.assertEqual(first["set_values"], 1)
        self.assertEqual(self._ess_value(service), "20")

        second = service.apply_student_commands(
            {
                "command_origin": "automatic",
                "strategy_id": "renewable_priority",
                "generation": 2,
                "replace_strategy_generation": True,
                "set_values": [],
            },
            source="trainee-renewable-priority-backend",
        )

        self.assertEqual(second["set_values"], 0)
        self.assertEqual(self._ess_value(service), "10")
        self.assertTrue(service.command_history[-2]["cancelled"])
        self.assertEqual(
            service.command_history[-2]["cancelled_reason"],
            "superseded_strategy_generation",
        )
        self.assertEqual(service.command_history[-1]["strategy_id"], "renewable_priority")
        self.assertEqual(service.command_history[-1]["generation"], 2)

    def test_current_strategy_generation_can_be_cancelled_without_point_names(self):
        service = self._service()
        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "strategy_id": "renewable_priority",
                "generation": 7,
                "replace_strategy_generation": True,
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 20,
                    }
                ],
            },
            source="trainee-renewable-priority-backend",
        )

        result = service.apply_student_commands(
            {
                "action": "cancel_strategy_generation",
                "strategy_id": "renewable_priority",
                "generation": 7,
                "reason": "controller_stopped",
            },
            source="trainee-renewable-priority-backend",
        )

        self.assertEqual(result["cancelled_generations"], 1)
        self.assertEqual(self._ess_value(service), "10")
        self.assertEqual(
            service.command_history[-1]["cancelled_reason"],
            "controller_stopped",
        )


class BidirectionalAcdcSafetyTest(unittest.TestCase):
    def test_physical_limits_clamp_each_converter_in_both_directions(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        write_model_dir(root)
        book = simu_loop.EBook(root / "model.e")
        grid = next(
            row
            for row in book.data["DCACConverter"].data
            if row.get("dev_type") == "grid-acdc-converter"
        )
        stat = simu_loop.EBook({})
        define = simu_loop._capability_define_book(book)

        grid["p_ac_set"] = "999"
        simu_loop.apply_device_capability_limits_book(book, {}, stat, define)
        self.assertEqual(float(grid["p_ac_set"]), 50.0)

        grid["p_ac_set"] = "-999"
        simu_loop.apply_device_capability_limits_book(book, {}, stat, define)
        self.assertEqual(float(grid["p_ac_set"]), -50.0)

    def test_dc_terminal_setpoint_uses_opposite_sign_and_its_own_limits(self):
        book = simu_loop.EBook(
            {
                "ACNode": [{"idx": 1, "name": "ac-terminal", "run_stat": 1}],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 1, "run_stat": 1}],
                "DCNode": [{"idx": 1, "name": "dc-terminal", "run_stat": 1}],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 1, "run_stat": 1}],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "dc-port-link",
                        "dev_type": "grid-dcac-converter",
                        "ac_node": 1,
                        "dc_node": 1,
                        "p_dc_set": 999,
                        "p_dc_min": -30,
                        "p_dc_max": 40,
                        "run_stat": 1,
                    }
                ]
            }
        )
        row = book.data["DCACConverter"].data[0]

        simu_loop.apply_acdc_limits(book)

        self.assertEqual(float(row["p_dc_set"]), 40.0)
        self.assertNotIn("p_ac_set", row)

    def test_dc_terminal_control_has_priority_when_both_sides_are_active(self):
        book = simu_loop.EBook(
            {
                "ACNode": [{"idx": 1, "name": "ac-terminal", "run_stat": 1}],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 1, "run_stat": 1}],
                "DCNode": [{"idx": 1, "name": "dc-terminal", "run_stat": 1}],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 1, "run_stat": 1}],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "dc-port-link",
                        "dev_type": "grid-dcac-converter",
                        "ac_node": 1,
                        "dc_node": 1,
                        "ac_control_type": "PQ",
                        "dc_control_type": "P",
                        "p_ac_set": -999,
                        "p_dc_set": 999,
                        "p_dc_min": -30,
                        "p_dc_max": 40,
                        "run_stat": 1,
                    }
                ]
            }
        )
        row = book.data["DCACConverter"].data[0]

        simu_loop.apply_acdc_limits(book)

        self.assertEqual(float(row["p_dc_set"]), 40.0)
        self.assertEqual(float(row["p_ac_set"]), -999.0)

    def test_renewable_dispatch_prefers_dc_control_and_converts_the_setpoint(self):
        snapshot = renewable_snapshot()
        converter = next(
            row
            for row in snapshot["devices"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        )
        converter["mode"] = "P"
        converter["set_types"] = ["p_ac_set", "p_dc_set"]
        converter["raw"].update(
            {
                "ac_control_type": "PQ",
                "dc_control_type": "P",
                "p_ac_set": 0,
                "p_dc_set": 0,
            }
        )
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-converter-1",
                "set_type": "p_dc_set",
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        command_row = next(
            row
            for row in plan["commandRows"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        )
        command = next(
            row
            for row in plan["commands"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        )

        self.assertLess(command_row["commandKw"], 0.0)
        self.assertEqual(command["set_type"], "p_dc_set")
        self.assertAlmostEqual(command["set_value"], -command_row["commandKw"])

    def test_dc_terminal_control_does_not_fall_back_to_inactive_p_ac_set(self):
        snapshot = renewable_snapshot()
        converter = next(
            row
            for row in snapshot["devices"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        )
        converter["mode"] = "P"
        converter["set_types"] = ["p_ac_set", "p_dc_set"]
        converter["raw"].update(
            {
                "ac_control_type": "NONE",
                "dc_control_type": "P",
                "p_ac_set": 0,
                "p_dc_set": 0,
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        command_row = next(
            row
            for row in plan["commandRows"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        )

        self.assertEqual(command_row["set_type"], "")
        self.assertFalse(command_row["commandable"])
        self.assertFalse(
            any(
                row.get("dev_type") == "DCACConverter"
                and row.get("dev_name") == "grid-converter-1"
                for row in plan["commands"]
            )
        )

    def test_invalid_diesel_topology_fails_closed(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["ACDieselGen"] = [
            {
                "idx": 1,
                "idx_acgenerator": 2,
                "rated_power": 200,
                "p_min": 20,
                "p_max": 200,
            }
        ]
        diesel_model = next(
            row
            for row in snapshot["definitions"]["model"]["ACGenerator"]["rows"]
            if row["idx"] == 2
        )
        diesel_model["node"] = 999

        plan = calculate_renewable_control_plan(snapshot)
        diesel = next(
            row
            for row in plan["commandRows"]
            if row.get("dev_name") == "diesel-1"
        )

        self.assertEqual(diesel["connectionSide"], "INVALID")
        self.assertFalse(diesel["activelyConnected"])
        self.assertFalse(diesel["commandable"])
        self.assertFalse(diesel["strategyCommand"])
        self.assertFalse(
            any(
                command["dev_type"] == "ACGenerator"
                and command["dev_name"] == "diesel-1"
                for command in plan["commands"]
            )
        )

    def test_ac_renewable_can_charge_dc_storage_through_positive_p_ac_target(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["ACDieselGen"] = [
            {
                "idx": 1,
                "idx_acgenerator": 2,
                "rated_power": 200,
                "p_min": 20,
                "p_max": 200,
            }
        ]
        converter = next(
            row
            for row in snapshot["devices"]
            if row["dev_type"] == "DCACConverter"
        )
        converter["raw"].update(
            {
                "dev_type": "grid-acdc-converter",
                "p_ac_min": "-50",
                "p_ac_max": "50",
            }
        )
        converter_model = snapshot["definitions"]["model"]["DCACConverter"]["rows"][0]
        converter_model.update(
            {
                "dev_type": "grid-acdc-converter",
                "p_ac_min": -50,
                "p_ac_max": 50,
            }
        )

        storage = next(
            row
            for row in snapshot["devices"]
            if row.get("dev_name") == "storage-1"
        )
        storage["mode"] = "P"
        storage["set_types"] = ["p_set"]
        storage_model = next(
            row
            for row in snapshot["definitions"]["model"]["DCGenerator"]["rows"]
            if row["idx"] == 2
        )
        storage_model["control_type"] = "P"
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {"dev_type": "DCGenerator", "dev_name": "storage-1", "set_type": "p_set"}
        )

        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN":
                row["value"] = 30
            elif row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN":
                row["value"] = 80
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                # Stay above the protected diesel lower boundary so this case
                # isolates AC renewable transfer into DC storage.  P_AC and
                # p_ac_set are positive from AC to DC.
                row["value"] = 30
            elif row["dev_name"] == "grid-converter-1" and row["meas_type"] == "P_AC":
                row["value"] = 0
            elif row["dev_name"] == "weather" and row["meas_type"] == "SOLAR_IRRADIANCE":
                # Keep the 80 kW PV operating point physically available so
                # this case isolates AC renewable transfer into DC storage.
                row["value"] = 1000

        plan = calculate_renewable_control_plan(
            copy.deepcopy(snapshot),
            RenewableControlSettings(step_coefficient=0.1, converter_step_ratio=0.1),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertGreater(rows["grid-converter-1"]["commandKw"], 0.0)
        self.assertGreater(rows["wind-1"]["commandKw"], 30.0)
        self.assertLess(rows["storage-1"]["commandKw"], 0.0)
        self.assertLessEqual(rows["grid-converter-1"]["commandKw"], 50.0)
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])


if __name__ == "__main__":
    unittest.main()
