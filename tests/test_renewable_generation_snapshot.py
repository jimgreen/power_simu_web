from __future__ import annotations

import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import simu_loop
import simu.service as service_module
from simu.generate_simple_model import write_model_dir
from simu.renewable_control import RenewableControlSettings, calculate_renewable_control_plan
from simu.service import COMMAND_HISTORY_RECENT_LIMIT, PolarMicrogridSimulator
from tests.test_trainee_renewable_backend_control import (
    append_model_row,
    make_control_manager,
    measurement,
    renewable_snapshot,
)


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

    @staticmethod
    def _ess_run_stat(service: PolarMicrogridSimulator) -> str:
        row = next(
            row
            for row in service.runtime_stat_book.data["RunStat"].data
            if row.get("dev_type") == "ESS" and row.get("dev_name") == "ess01"
        )
        return str(row["run_stat"])

    def test_generation_overwrites_matching_controls_and_stop_keeps_them_latched(self):
        service = self._service()

        stopped = service.apply_student_commands(
            {
                "command_origin": "automatic",
                "strategy_id": "renewable_priority",
                "generation": 1,
                "replace_strategy_generation": True,
                "run_status": [
                    {"dev_type": "ESS", "dev_name": "ess01", "run_stat": 0}
                ],
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 0,
                    }
                ],
            },
            source="trainee-renewable-priority-backend",
        )

        self.assertEqual(stopped["run_status"], 1)
        self.assertEqual(stopped["set_values"], 1)
        self.assertEqual(self._ess_run_stat(service), "0")
        self.assertEqual(self._ess_value(service), "0")

        started = service.apply_student_commands(
            {
                "command_origin": "automatic",
                "strategy_id": "renewable_priority",
                "generation": 2,
                "replace_strategy_generation": True,
                "run_status": [
                    {"dev_type": "ESS", "dev_name": "ess01", "run_stat": 1}
                ],
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

        self.assertEqual(started["run_status"], 1)
        self.assertEqual(started["set_values"], 1)
        self.assertEqual(self._ess_run_stat(service), "1")
        self.assertEqual(self._ess_value(service), "20")
        self.assertTrue(service.command_history[-2]["cancelled"])

        cancelled = service.apply_student_commands(
            {
                "action": "cancel_strategy_generation",
                "strategy_id": "renewable_priority",
                "cancel_all_generations": True,
                "reason": "controller_stopped",
            },
            source="trainee-renewable-priority-backend",
        )

        self.assertEqual(cancelled["cancelled_generations"], 1)
        self.assertEqual(cancelled["cancelled_controls"], 2)
        self.assertEqual(self._ess_run_stat(service), "1")
        self.assertEqual(self._ess_value(service), "20")

    def test_empty_generation_does_not_restore_omitted_control_points(self):
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
        self.assertEqual(self._ess_value(service), "20")
        self.assertTrue(service.command_history[-2]["cancelled"])
        self.assertEqual(
            service.command_history[-2]["cancelled_reason"],
            "superseded_strategy_generation",
        )
        self.assertEqual(service.command_history[-1]["strategy_id"], "renewable_priority")
        self.assertEqual(service.command_history[-1]["generation"], 2)

    def test_identical_generation_retry_is_idempotent_without_materialize_or_persist(self):
        service = self._service()
        payload = {
            "command_origin": "automatic",
            "strategy_id": "renewable_priority",
            "generation": "cycle-1",
            "replace_strategy_generation": True,
            "set_values": [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "set_value": 20,
                }
            ],
        }
        first = service.apply_student_commands(
            payload,
            source="trainee-renewable-priority-backend",
        )
        history_size = len(service.command_history)

        with patch.object(
            service,
            "_materialize_active_control_commands",
            wraps=service._materialize_active_control_commands,
        ) as materialize, patch.object(
            service_module,
            "_write_json",
            wraps=service_module._write_json,
        ) as write_json:
            second = service.apply_student_commands(
                copy.deepcopy(payload),
                source="trainee-renewable-priority-backend",
            )

        command_writes = [
            call
            for call in write_json.call_args_list
            if Path(call.args[0]) == service.commands_file
        ]
        self.assertEqual(second, first)
        self.assertEqual(len(service.command_history), history_size)
        self.assertEqual(materialize.call_count, 0)
        self.assertEqual(command_writes, [])

    def test_new_generation_materializes_once_and_persists_commands_once(self):
        service = self._service()
        source = "trainee-renewable-priority-backend"
        base_payload = {
            "command_origin": "automatic",
            "strategy_id": "renewable_priority",
            "replace_strategy_generation": True,
            "set_values": [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "set_value": 20,
                }
            ],
        }
        service.apply_student_commands(
            {**base_payload, "generation": 1},
            source=source,
        )

        with patch.object(
            service,
            "_materialize_active_control_commands",
            wraps=service._materialize_active_control_commands,
        ) as materialize, patch.object(
            service_module,
            "_write_json",
            wraps=service_module._write_json,
        ) as write_json:
            service.apply_student_commands(
                {**base_payload, "generation": 2},
                source=source,
            )

        command_writes = [
            call
            for call in write_json.call_args_list
            if Path(call.args[0]) == service.commands_file
        ]
        self.assertEqual(materialize.call_count, 1)
        self.assertEqual(len(command_writes), 1)

    def test_generation_replacement_does_not_rescan_unbounded_history(self):
        service = self._service()
        source = "trainee-renewable-priority-backend"
        payload = {
            "command_origin": "automatic",
            "strategy_id": "renewable_priority",
            "replace_strategy_generation": True,
            "set_values": [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "set_value": 20,
                }
            ],
        }
        service.apply_student_commands(
            {**payload, "generation": 1},
            source=source,
        )
        for index in range(1000):
            service._append_command_history_entry(
                {
                    "command_origin": "manual",
                    "manual_hold": True,
                    "source": "performance-fixture",
                    "sequence": index,
                    "accepted": {"run_status": 0, "set_values": 0},
                    "normalized": {"run_status": [], "set_values": []},
                }
            )

        with patch.object(
            service,
            "_command_entry_is_active",
            wraps=service._command_entry_is_active,
        ) as active_check, patch.object(
            service,
            "_strategy_generation_entry_metadata",
            wraps=service._strategy_generation_entry_metadata,
        ) as generation_metadata:
            service.apply_student_commands(
                {**payload, "generation": 2},
                source=source,
            )

        self.assertLessEqual(
            active_check.call_count,
            COMMAND_HISTORY_RECENT_LIMIT + 5,
        )
        self.assertLessEqual(generation_metadata.call_count, 5)

    def test_controller_stop_retires_generation_without_reverting_device_target(self):
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
        self.assertEqual(self._ess_value(service), "20")
        self.assertEqual(
            service.command_history[-1]["cancelled_reason"],
            "controller_stopped",
        )

    def test_controller_stop_keeps_latest_point_value_for_the_simulation_cycle(self):
        service = self._service()
        for generation, value in ((11, 20), (12, 30)):
            service.apply_student_commands(
                {
                    "command_origin": "automatic",
                    "strategy_id": "renewable_priority",
                    "generation": generation,
                    "replace_strategy_generation": True,
                    "set_values": [
                        {
                            "dev_type": "ESS",
                            "dev_name": "ess01",
                            "set_type": "p_set",
                            "set_value": value,
                        }
                    ],
                },
                source="trainee-renewable-priority-backend",
            )

        result = service.apply_student_commands(
            {
                "action": "cancel_strategy_generation",
                "strategy_id": "renewable_priority",
                "cancel_all_generations": True,
                "reason": "controller_stopped",
            },
            source="trainee-renewable-priority-backend",
        )

        self.assertEqual(result["cancelled_generations"], 1)
        self.assertEqual(self._ess_value(service), "30")
        self.assertEqual(
            service.command_history[-2]["cancelled_reason"],
            "controller_stopped",
        )


class RenewableControllerCommandLifecycleTest(unittest.TestCase):
    @staticmethod
    def _service(runtime_dir):
        service = type("ControlService", (), {})()
        service.model_id = "shared"
        service.runtime_dir = Path(runtime_dir)
        service.lock = threading.RLock()
        return service

    @staticmethod
    def _plan(clock_key: str, commands):
        return {
            "time": clock_key,
            "clockKey": clock_key,
            "metrics": {},
            "commands": copy.deepcopy(commands),
            "commandRows": [],
            "dataQuality": {"dispatchAllowed": True},
        }

    def test_dispatch_uses_replaceable_generation_and_stop_retires_generation_only(self):
        dispatched = []

        def command_sink(model_id, payload):
            dispatched.append((model_id, copy.deepcopy(payload)))
            if payload.get("action") == "cancel_strategy_generation":
                return {"cancelled_generations": 1, "cancelled_controls": 1}
            return {"set_values": len(payload.get("set_values", []))}

        with tempfile.TemporaryDirectory() as temporary:
            manager = make_control_manager(
                self._service(temporary),
                command_sink=command_sink,
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            plan = self._plan(
                "1|10|00:10:00",
                [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 20.0,
                    }
                ],
            )
            try:
                with patch(
                    "simu.renewable_control.calculate_renewable_control_plan",
                    return_value=plan,
                ):
                    manager.run_once(
                        "shared",
                        trigger="auto",
                        allow_dispatch=True,
                        record_log=False,
                    )
                    stopped = manager.apply_action("shared", {"action": "stop"})
            finally:
                manager.close()

        self.assertEqual(len(dispatched), 2)
        command_payload = dispatched[0][1]
        self.assertEqual(command_payload["command_origin"], "automatic")
        self.assertEqual(command_payload["strategy_id"], "renewable_priority")
        self.assertEqual(command_payload["generation"], "1|10|00:10:00")
        self.assertTrue(command_payload["replace_strategy_generation"])
        cancel_payload = dispatched[1][1]
        self.assertEqual(cancel_payload["action"], "cancel_strategy_generation")
        self.assertEqual(cancel_payload["strategy_id"], "renewable_priority")
        self.assertTrue(cancel_payload["cancel_all_generations"])
        self.assertEqual(cancel_payload["reason"], "controller_stopped")
        self.assertFalse(stopped["enabled"])
        self.assertIn("已下发指令保持有效", stopped["status"])

    def test_retired_controller_clears_effective_hydrogen_generation_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            manager = make_control_manager(service)
            state = manager._state_for("shared")
            with state.lock:
                state.enabled = True
                state.desired_enabled = True
                state.strategy_generation_active = True
                state.strategy_cancel_pending = True
                state.effective_target_snapshot = {
                    "commands": [
                        {
                            "dev_type": "ACLoad",
                            "dev_name": "electrolyzer-load",
                            "set_type": "p_set",
                            "set_value": 6.0,
                        }
                    ]
                }
            try:
                removed = manager.remove_model_for_service(service)
            finally:
                manager.close()

        self.assertTrue(removed)
        self.assertFalse(state.enabled)
        self.assertFalse(state.desired_enabled)
        self.assertFalse(state.strategy_generation_active)
        self.assertFalse(state.strategy_cancel_pending)
        self.assertIsNone(state.effective_target_snapshot)

    def test_empty_closed_loop_plan_replaces_previous_nonempty_generation_once(self):
        dispatched = []

        def command_sink(model_id, payload):
            dispatched.append((model_id, copy.deepcopy(payload)))
            return {"set_values": len(payload.get("set_values", []))}

        with tempfile.TemporaryDirectory() as temporary:
            manager = make_control_manager(
                self._service(temporary),
                command_sink=command_sink,
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            plans = [
                self._plan(
                    "1|20|00:20:00",
                    [
                        {
                            "dev_type": "ESS",
                            "dev_name": "ess01",
                            "set_type": "p_set",
                            "set_value": 20.0,
                        }
                    ],
                ),
                self._plan("1|21|00:21:00", []),
                self._plan("1|22|00:22:00", []),
            ]
            try:
                with patch(
                    "simu.renewable_control.calculate_renewable_control_plan",
                    side_effect=plans,
                ):
                    for _ in plans:
                        manager.run_once(
                            "shared",
                            trigger="auto",
                            allow_dispatch=True,
                            record_log=False,
                        )
            finally:
                manager.close()

        self.assertEqual(len(dispatched), 2)
        self.assertEqual(len(dispatched[0][1]["set_values"]), 1)
        self.assertEqual(dispatched[1][1]["set_values"], [])
        self.assertEqual(dispatched[1][1]["generation"], "1|21|00:21:00")
        self.assertTrue(dispatched[1][1]["replace_strategy_generation"])

    def test_consecutive_generations_keep_unchanged_renewables_in_full_snapshot(self):
        dispatched = []

        def command_sink(model_id, payload):
            dispatched.append((model_id, copy.deepcopy(payload)))
            return {"set_values": len(payload.get("set_values", []))}

        first_snapshot = renewable_snapshot()
        second_snapshot = copy.deepcopy(first_snapshot)
        second_snapshot["clock"].update(
            {
                "time": "12:01:00",
                "minute": 721,
                "absolute_minute": 721,
            }
        )
        settings = RenewableControlSettings(step_coefficient=0.0)
        plans = [
            calculate_renewable_control_plan(first_snapshot, settings),
            calculate_renewable_control_plan(second_snapshot, settings),
        ]

        with tempfile.TemporaryDirectory() as temporary:
            manager = make_control_manager(
                self._service(temporary),
                snapshot=first_snapshot,
                command_sink=command_sink,
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                with patch(
                    "simu.renewable_control.calculate_renewable_control_plan",
                    side_effect=plans,
                ):
                    manager.run_once(
                        "shared",
                        trigger="auto",
                        allow_dispatch=True,
                        record_log=False,
                    )
                    manager.run_once(
                        "shared",
                        trigger="auto",
                        allow_dispatch=True,
                        record_log=False,
                    )
            finally:
                manager.close()

        self.assertEqual(len(dispatched), 2)
        for _model_id, payload in dispatched:
            targets = {
                (
                    command.get("dev_type"),
                    command.get("dev_name"),
                    command.get("set_type"),
                ): command.get("set_value")
                for command in payload["set_values"]
            }
            self.assertAlmostEqual(
                targets[("ACGenerator", "wind-1", "p_set")],
                30.0,
            )
            self.assertAlmostEqual(
                targets[("DCGenerator", "pv-1", "p_set")],
                20.0,
            )
            self.assertTrue(payload["replace_strategy_generation"])
        self.assertNotEqual(
            dispatched[0][1]["generation"],
            dispatched[1][1]["generation"],
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

    def test_renewable_dispatch_uses_ac_setpoint_when_dc_control_is_none(self):
        snapshot = renewable_snapshot()
        converter = next(
            row
            for row in snapshot["devices"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        )
        converter["mode"] = "PQ"
        converter["set_types"] = ["p_ac_set", "p_dc_set"]
        converter["raw"].update(
            {
                "ac_control_type": "PQ",
                "dc_control_type": "NONE",
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

        self.assertEqual(command_row["set_type"], "p_ac_set")
        self.assertEqual(command["set_type"], "p_ac_set")
        self.assertAlmostEqual(command["set_value"], command_row["commandKw"])

    def test_two_parallel_converters_support_all_side_control_combinations(self):
        cases = {
            "mixed": (("NONE", "P"), ("PQ", "NONE")),
            "both_dc": (("NONE", "P"), ("NONE", "P")),
            "both_ac": (("PQ", "NONE"), ("PQ", "NONE")),
            "double_none": (("NONE", "NONE"), ("NONE", "NONE")),
        }

        for label, modes in cases.items():
            with self.subTest(label=label):
                snapshot = renewable_snapshot()
                first = next(
                    row
                    for row in snapshot["devices"]
                    if row.get("dev_type") == "DCACConverter"
                    and row.get("dev_name") == "grid-converter-1"
                )
                first["set_types"] = ["p_ac_set", "p_dc_set"]
                first["raw"].update(
                    {
                        "rated_capacity": "60",
                        "p_ac_min": "-60",
                        "p_ac_max": "60",
                    }
                )
                second = copy.deepcopy(first)
                second["dev_name"] = "grid-converter-2"
                second["raw"].update(
                    {
                        "idx": "2",
                        "rated_capacity": "20",
                        "p_ac_min": "-20",
                        "p_ac_max": "20",
                    }
                )
                snapshot["devices"].append(second)

                first_model = next(
                    row
                    for row in snapshot["definitions"]["model"]["DCACConverter"]["rows"]
                    if row.get("name") == "grid-converter-1"
                )
                first_model.update(
                    {
                        "p_ac_min": -60,
                        "p_ac_max": 60,
                        "p_ac_set": -12,
                        "p_dc_set": 12,
                    }
                )
                append_model_row(
                    snapshot,
                    "DCACConverter",
                    {
                        "idx": 2,
                        "name": "grid-converter-2",
                        "ac_node": 2,
                        "dc_node": 3,
                        "ac_control_type": "PQ",
                        "dc_control_type": "NONE",
                        "p_ac_set": -4,
                        "p_dc_set": 4,
                        "p_ac_min": -20,
                        "p_ac_max": 20,
                        "run_stat": 1,
                    },
                )
                second_model = next(
                    row
                    for row in snapshot["definitions"]["model"]["DCACConverter"]["rows"]
                    if row.get("name") == "grid-converter-2"
                )

                converter_measurements = [
                    row
                    for row in snapshot["measurements"]["scada"]
                    if row.get("dev_type") == "DCACConverter"
                    and row.get("dev_name") == "grid-converter-1"
                ]
                self.assertEqual(len(converter_measurements), 1)
                second_measurement = measurement(
                    "converter-2.p",
                    "DCACConverter",
                    "grid-converter-2",
                    "P_AC",
                    -4,
                )
                snapshot["measurements"]["scada"].append(second_measurement)

                snapshot["definitions"]["control"]["SetValue"]["rows"] = [
                    row
                    for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
                    if row.get("dev_type") != "DCACConverter"
                ]
                for device_name in ("grid-converter-1", "grid-converter-2"):
                    for set_type in ("p_ac_set", "p_dc_set"):
                        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
                            {
                                "dev_type": "DCACConverter",
                                "dev_name": device_name,
                                "set_type": set_type,
                            }
                        )

                for device, model_row, measured_row, mode, current_kw in zip(
                    (first, second),
                    (first_model, second_model),
                    (converter_measurements[0], second_measurement),
                    modes,
                    (-12.0, -4.0),
                ):
                    ac_mode, dc_mode = mode
                    device["mode"] = "P" if dc_mode == "P" or ac_mode == "NONE" else ac_mode
                    device["raw"].update(
                        {
                            "ac_control_type": ac_mode,
                            "dc_control_type": dc_mode,
                            "p_ac_set": current_kw,
                            "p_dc_set": -current_kw,
                        }
                    )
                    model_row.update(
                        {
                            "ac_control_type": ac_mode,
                            "dc_control_type": dc_mode,
                            "p_ac_set": current_kw,
                            "p_dc_set": -current_kw,
                        }
                    )
                    use_dc = dc_mode == "P" or (dc_mode == "NONE" and ac_mode == "NONE")
                    measured_row["meas_type"] = "P_DC" if use_dc else "P_AC"
                    measured_row["value"] = -current_kw if use_dc else current_kw

                plan = calculate_renewable_control_plan(snapshot)
                converter_rows = sorted(
                    (
                        row
                        for row in plan["commandRows"]
                        if row.get("dev_type") == "DCACConverter"
                        and row.get("dev_name") in {"grid-converter-1", "grid-converter-2"}
                    ),
                    key=lambda row: row["dev_name"],
                )
                converter_commands = {
                    row["dev_name"]: row
                    for row in plan["commands"]
                    if row.get("dev_type") == "DCACConverter"
                    and row.get("dev_name") in {"grid-converter-1", "grid-converter-2"}
                }
                expected_fields = [
                    "p_dc_set"
                    if dc_mode == "P" or (dc_mode == "NONE" and ac_mode == "NONE")
                    else "p_ac_set"
                    for ac_mode, dc_mode in modes
                ]

                self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
                self.assertEqual(len(converter_rows), 2)
                self.assertEqual([row["set_type"] for row in converter_rows], expected_fields)
                self.assertTrue(all(row["commandable"] for row in converter_rows))
                self.assertEqual(set(converter_commands), {"grid-converter-1", "grid-converter-2"})
                self.assertEqual(
                    plan["metrics"]["converterSystemPowerConvention"],
                    "P_DC",
                )
                self.assertEqual(
                    plan["metrics"]["converterSystemPositiveDirection"],
                    "DC_TO_AC",
                )
                self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], 16.0)
                self.assertAlmostEqual(
                    plan["metrics"]["acdcCurrentKw"],
                    -sum(row["currentKw"] for row in converter_rows),
                )
                self.assertAlmostEqual(
                    plan["metrics"]["acdcTargetKw"],
                    -sum(row["commandKw"] for row in converter_rows),
                )
                self.assertGreater(plan["metrics"]["acdcTargetKw"], 0.0)
                self.assertAlmostEqual(
                    converter_rows[0]["commandKw"] / 60.0,
                    converter_rows[1]["commandKw"] / 20.0,
                    places=6,
                )
                for row in converter_rows:
                    command = converter_commands[row["dev_name"]]
                    self.assertEqual(command["set_type"], row["set_type"])
                    expected_value = (
                        -row["commandKw"]
                        if row["set_type"] == "p_dc_set"
                        else row["commandKw"]
                    )
                    self.assertAlmostEqual(command["set_value"], expected_value)

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
