from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class ControlCommandValidityTest(unittest.TestCase):
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

    def _make_service_with_breaker_control(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        breaker_control = (
            "<CbOpenStat>\n"
            "@ dev_type dev_name status\n"
            "# ACBreak br1 1\n"
            "</CbOpenStat>\n"
        )
        for file_name in ("stat.e", "control.e"):
            path = source / file_name
            path.write_text(path.read_text(encoding="utf-8") + breaker_control, encoding="utf-8")
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        return workspace, service

    @staticmethod
    def _set_value(service, dev_type: str, dev_name: str, set_type: str) -> str:
        return str(service.latest_control_values()["values"].get(f"{dev_type}.{dev_name}.{set_type}", ""))

    @staticmethod
    def _run_stat(service, dev_type: str, dev_name: str) -> str:
        return str(service.latest_control_values()["values"].get(f"{dev_type}.{dev_name}.run_stat", ""))

    def test_ignores_control_commands_not_sent_by_trainee_station(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="simulator-local",
        )

        self.assertEqual(result["set_values"], 0)
        self.assertEqual(result["ignored"], 1)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_ignores_control_commands_without_trainee_source(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            }
        )

        self.assertEqual(result["set_values"], 0)
        self.assertEqual(result["ignored"], 1)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_strategy_control_command_ignores_short_ttl_until_cycle_reset(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 1,
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-renewable-priority",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        service.step()
        service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        service.clock.absolute_minute = 1440
        service.clock.minute = 0
        service._materialize_active_control_commands(1440)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_materialization_applies_only_the_latest_automatic_owner_per_control_point(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "strategy_id": "renewable_priority",
                "generation": 1,
                "replace_strategy_generation": True,
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 12,
                    },
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "wt01_10kw",
                        "set_type": "p_set",
                        "set_value": 6,
                    },
                ],
            },
            source="trainee-renewable-priority",
        )
        service.apply_student_commands(
            {
                "strategy_id": "renewable_priority",
                "generation": 2,
                "replace_strategy_generation": True,
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 18,
                    }
                ],
            },
            source="trainee-renewable-priority",
        )

        applied = service._materialize_active_control_commands(service.clock.absolute_minute)

        self.assertEqual(applied["active_commands"], 2)
        self.assertEqual(applied["set_values"], 2)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "18")
        self.assertEqual(self._set_value(service, "ACGenerator", "wt01_10kw", "p_set"), "6")

    def test_automatic_control_command_is_valid_until_cycle_end(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-renewable-priority",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(service.command_history[-1]["valid_for_minutes"], 1440.0)
        self.assertEqual(service.command_history[-1]["expires_at_absolute_minute"], 1440.0)
        for _ in range(120):
            service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        service.clock.absolute_minute = 1440
        service.clock.minute = 0
        service._materialize_active_control_commands(1440)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_explicit_automatic_expiry_does_not_shorten_cycle_latch(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "expires_at_absolute_minute": 10,
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-renewable-priority",
        )

        self.assertEqual(result["set_values"], 1)
        for _ in range(6):
            service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        for _ in range(5):
            service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

    def test_manual_control_commands_have_no_time_limit(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertTrue(service.command_history[-1]["manual_hold"])
        self.assertIsNone(service.command_history[-1]["expires_at_absolute_minute"])
        for _ in range(30):
            service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

    def test_explicit_command_origin_controls_manual_priority_and_cycle_latch(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.control_clock({"action": "start", "minute": 0})
        service.apply_student_commands(
            {
                "command_origin": "manual",
                "valid_for_minutes": 1,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-api",
        )
        manual_entry = service.command_history[-1]

        self.assertEqual(manual_entry["command_origin"], "manual")
        self.assertTrue(manual_entry["manual_hold"])
        self.assertIsNone(manual_entry["expires_at_absolute_minute"])

        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "manual_hold": True,
                "valid_for_minutes": 1,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 5}
                ],
            },
            source="trainee-ui",
        )
        automatic_entry = service.command_history[-1]

        self.assertEqual(automatic_entry["command_origin"], "automatic")
        self.assertFalse(automatic_entry["manual_hold"])
        self.assertEqual(automatic_entry["expires_at_absolute_minute"], 1440.0)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        service.clock.absolute_minute = 2
        service.clock.minute = 2
        service._materialize_active_control_commands(2)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

    def test_new_simulation_run_clears_automatic_commands_but_keeps_manual_commands(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        first_run = service.control_clock({"action": "start", "minute": 0})
        service.apply_student_commands(
            {
                "command_origin": "manual",
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0}
                ],
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )
        manual_entry = service.command_history[-1]
        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "valid_for_minutes": 120,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 1}
                ],
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 5}
                ],
            },
            source="trainee-automatic-control",
        )
        automatic_entry = service.command_history[-1]
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "0")

        service.control_clock({"action": "stop"})
        second_run = service.control_clock({"action": "start", "minute": 0})

        self.assertNotEqual(first_run["run_id"], second_run["run_id"])
        self.assertFalse(manual_entry.get("cancelled", False))
        self.assertTrue(automatic_entry.get("cancelled", False))
        self.assertEqual(automatic_entry.get("cancelled_reason"), "simulation_restart")
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "0")
        effective = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
        )["commands"]["effective"]
        self.assertEqual(effective, [manual_entry])

    def test_clock_stop_zero_reset_immediately_clears_automatic_commands(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "run_status": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "wt01_10kw",
                        "run_stat": 0,
                    }
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
            source="trainee-automatic-control",
        )
        automatic_entry = service.command_history[-1]
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "0")
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        stopped = service.control_clock({"action": "stop"})

        self.assertEqual(stopped["absolute_minute"], 0.0)
        self.assertTrue(automatic_entry["cancelled"])
        self.assertEqual(automatic_entry["cancelled_reason"], "simulation_restart")
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "1")
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_zero_start_from_pause_starts_new_lifecycle_and_old_automatic_command_cannot_reactivate(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        first_run = service.control_clock({"action": "start", "minute": 100})
        service.apply_student_commands(
            {
                "command_origin": "manual",
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )
        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "valid_for_minutes": 120,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 5}
                ],
            },
            source="trainee-automatic-control",
        )
        automatic_entry = service.command_history[-1]
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        service.clock.step_count = 9
        service.control_clock({"action": "pause"})
        restarted = service.control_clock({"action": "start", "minute": 0})

        self.assertEqual(restarted["run_id"], first_run["run_id"] + 1)
        self.assertEqual(restarted["step_count"], 0)
        self.assertTrue(automatic_entry.get("cancelled", False))
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        service.clock.absolute_minute = 100
        service.clock.minute = 100
        service._materialize_active_control_commands(100)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

    def test_breaker_status_command_is_counted_as_materialized_remote_control(self):
        workspace, service = self._make_service_with_breaker_control()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "run_status": [
                    {"dev_type": "ACBreak", "dev_name": "br1", "status": 0}
                ],
            },
            source="trainee-ui",
        )
        materialized = service._materialize_active_control_commands(service.clock.absolute_minute)

        self.assertEqual(result["run_status"], 1)
        self.assertEqual(materialized["run_status"], 1)
        self.assertEqual(service.latest_control_values()["values"]["ACBreak.br1.status"], 0)

        breaker_status = next(
            row
            for row in service.runtime_stat_book.data["CbOpenStat"].data
            if row["dev_type"] == "ACBreak" and row["dev_name"] == "br1"
        )
        self.assertEqual(str(breaker_status["closed_status_set"]), "0")
        self.assertEqual(str(breaker_status["closed_status"]), "1")

    def test_breaker_status_command_log_records_field_and_target_value(self):
        workspace, service = self._make_service_with_breaker_control()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "run_status": [
                    {"dev_type": "ACBreak", "dev_name": "br1", "status": 0}
                ],
            },
            source="trainee-ui",
        )

        detail = "\n".join(str(item) for item in service.runtime_logs[-1]["detail"])
        self.assertIn("ACBreak.br1.status=0", detail)

    def test_manual_command_overrides_active_strategy_command(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "grid_inv_acp",
                        "set_type": "p_set",
                        "set_value": -40,
                    }
                ],
            },
            source="trainee-ui",
        )
        service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "grid_inv_acp",
                        "set_type": "p_set",
                        "set_value": 0,
                    }
                ],
            },
            source="trainee-renewable-priority",
        )

        self.assertEqual(self._set_value(service, "DCACConverter", "grid_inv_acp", "p_set"), "-40")
        by_name = {item["name"]: item for item in service.latest_control_values()["items"]}
        effective = by_name["DCACConverter.grid_inv_acp.p_set"]
        self.assertTrue(effective["active"])
        self.assertEqual(effective["command_origin"], "manual")
        self.assertIsNone(effective["expires_at_absolute_minute"])

        service.clock.absolute_minute = 6
        service.clock.minute = 6
        service._materialize_active_control_commands(6)

        self.assertEqual(self._set_value(service, "DCACConverter", "grid_inv_acp", "p_set"), "-40")
        resumed = {
            item["name"]: item for item in service.latest_control_values()["items"]
        }["DCACConverter.grid_inv_acp.p_set"]
        self.assertEqual(resumed["command_origin"], "manual")
        self.assertIsNone(resumed["expires_at_absolute_minute"])

    def test_simulator_ui_runtime_control_edit_overrides_active_strategy(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "set_value": 60,
                    }
                ],
            },
            source="trainee-renewable-priority",
        )
        self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "60")

        result = service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"idx": "2", "name": "diesel_300kw"},
                "revision": service.definition_snapshot.revision,
                "changes": {"p_set": 95},
            }
        )

        self.assertEqual(result["record"]["p_set"], 95)
        self.assertEqual(result["runtime_control"]["set_values"]["p_set"], 95)
        self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "95")
        self.assertEqual(
            next(
                row
                for row in service.source_stat_book.data["SetValue"].data
                if row["dev_type"] == "ACGenerator"
                and row["dev_name"] == "diesel_300kw"
                and row["set_type"] == "p_set"
            )["set_value"],
            "95",
        )

        service.clock.absolute_minute = 6
        service.clock.minute = 6
        service._materialize_active_control_commands(6)

        self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "95")

    def test_simulator_ui_run_state_edit_overrides_manual_and_automatic_remote_control(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "valid_for_minutes": 5,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 1}
                ],
            },
            source="trainee-automatic-control",
        )
        service.apply_student_commands(
            {
                "command_origin": "manual",
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 1}
                ],
            },
            source="trainee-ui",
        )
        result = service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"name": "wt01_10kw"},
                "revision": service.definition_snapshot.revision,
                "changes": {"run_stat": 0},
            }
        )

        self.assertEqual(result["runtime_control"]["run_stat"], 0)
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "0")
        latest = {
            item["name"]: item for item in service.latest_control_values()["items"]
        }["ACGenerator.wt01_10kw.run_stat"]
        self.assertEqual(latest["command_origin"], "simulator-ui")

    def test_manual_control_commands_are_not_evicted_by_frequent_strategy_refreshes(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )
        for index in range(250):
            service.apply_student_commands(
                {
                    "valid_for_minutes": 5,
                    "strategy": {"name": "renewable_priority", "seq": index},
                    "set_values": [
                        {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 5}
                    ],
                },
                source="trainee-renewable-priority",
            )

        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        from simu.service import PolarMicrogridSimulator

        restarted = PolarMicrogridSimulator(service.sim_dir, service.runtime_dir, kernel=lambda _config: None)
        restarted.control_clock({"action": "start", "minute": 0})
        self.assertEqual(self._set_value(restarted, "ESS", "ess01", "p_set"), "20")

    def test_snapshot_keeps_effective_manual_command_outside_recent_history_window(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )
        manual_entry = service.command_history[-1]
        for index in range(60):
            service.apply_student_commands(
                {
                    "valid_for_minutes": 120,
                    "strategy": {"name": "renewable_priority", "seq": index},
                    "set_values": [
                        {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 5}
                    ],
                },
                source="trainee-renewable-priority",
            )

        self.assertNotIn(manual_entry, service.command_history[-50:])
        commands = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
        )["commands"]
        history = commands["history"]

        self.assertIn(manual_entry, history)
        self.assertLessEqual(len(history), 51)
        self.assertEqual(len(commands["effective"]), 1)
        self.assertIs(commands["effective"][0], manual_entry)
        self.assertEqual(commands["effective"][0]["source"], "trainee-ui")

    def test_manual_exit_only_cancels_manual_hold_and_keeps_automatic_command_active(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "grid_inv_acp",
                        "set_type": "p_set",
                        "set_value": -40,
                    }
                ],
            },
            source="trainee-ui",
        )
        manual_entry = service.command_history[-1]
        queued = service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "grid_inv_acp",
                        "set_type": "p_set",
                        "set_value": 0,
                    }
                ],
            },
            source="trainee-renewable-priority",
        )
        automatic_entry = service.command_history[-1]

        self.assertEqual(queued["set_values"], 1)
        self.assertEqual(queued["ignored"], 0)
        self.assertEqual(queued["queued"], 1)
        self.assertEqual(queued["received_by"], "simulator")
        self.assertEqual(queued["receive_state"], "completed")
        self.assertEqual(queued["queue_owner"], "simulator")
        self.assertEqual(queued["queue_state"], "waiting")
        self.assertEqual(queued["blocked"][0]["reason"], "higher_priority_manual_command")
        self.assertEqual(automatic_entry["queue_owner_at_acceptance"], "simulator")
        self.assertEqual(automatic_entry["queue_state_at_acceptance"], "waiting")
        self.assertEqual(automatic_entry["received_by"], "simulator")
        self.assertEqual(automatic_entry["receive_state"], "completed")
        self.assertEqual(automatic_entry["blocked_at_acceptance"], queued["blocked"])
        self.assertEqual(
            automatic_entry["normalized"]["set_values"][0]["set_value"],
            "0",
        )

        waiting_commands = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
            include_command_history=False,
        )["commands"]
        self.assertEqual(waiting_commands["effective"], [manual_entry])
        self.assertEqual(len(waiting_commands["queued"]), 1)
        self.assertEqual(
            waiting_commands["queued"][0]["normalized"]["set_values"],
            automatic_entry["normalized"]["set_values"],
        )
        self.assertEqual(
            waiting_commands["queued"][0]["blocked"][0]["reason"],
            "higher_priority_manual_command",
        )

        result = service.cancel_student_commands(
            {
                "command_origin": "manual",
                "cancel_commands": [{"name": "DCACConverter.grid_inv_acp.p_set"}],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["remote_adjustments"], 1)
        self.assertEqual(result["command_origin"], "manual")
        self.assertTrue(manual_entry["cancelled"])
        self.assertFalse(automatic_entry.get("cancelled", False))
        self.assertEqual(self._set_value(service, "DCACConverter", "grid_inv_acp", "p_set"), "0")
        released_commands = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
            include_command_history=False,
        )["commands"]
        self.assertEqual(released_commands["queued"], [])
        self.assertEqual(released_commands["effective"], [automatic_entry])

        service.clock.absolute_minute = 6
        service.clock.minute = 6
        service._materialize_active_control_commands(6)
        self.assertEqual(self._set_value(service, "DCACConverter", "grid_inv_acp", "p_set"), "0")

    def test_queue_exposes_only_latest_automatic_candidate_for_each_control_point(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.apply_student_commands(
            {
                "command_origin": "manual",
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 20,
                    }
                ],
            },
            source="trainee-ui",
        )
        manual_entry = service.command_history[-1]
        automatic_entries = []
        for value in (1, 2):
            service.apply_student_commands(
                {
                    "command_origin": "automatic",
                    "valid_for_minutes": 5,
                    "set_values": [
                        {
                            "dev_type": "ESS",
                            "dev_name": "ess01",
                            "set_type": "p_set",
                            "set_value": value,
                        }
                    ],
                },
                source="trainee-renewable-priority",
            )
            automatic_entries.append(service.command_history[-1])

        commands = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
            include_command_history=False,
        )["commands"]
        self.assertEqual(commands["effective"], [manual_entry])
        self.assertEqual(len(commands["queued"]), 1)
        self.assertEqual(
            commands["queued"][0]["normalized"]["set_values"][0]["set_value"],
            "2",
        )
        self.assertNotEqual(
            commands["queued"][0]["normalized"]["set_values"],
            automatic_entries[0]["normalized"]["set_values"],
        )

        service.cancel_student_commands(
            {
                "command_origin": "manual",
                "cancel_commands": [{"name": "ESS.ess01.p_set"}],
            },
            source="trainee-ui",
        )
        released = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
            include_command_history=False,
        )["commands"]
        self.assertEqual(released["queued"], [])
        self.assertEqual(released["effective"], [automatic_entries[-1]])

    def test_manual_acdc_active_power_command_with_stale_trainee_expiry_survives_next_step(self):
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        source = Path(workspace.name) / "source"
        copytree(SIMPLE_MODEL_SOURCE, source)
        service = PolarMicrogridSimulator(source, Path(workspace.name) / "runtime", kernel=lambda _config: None)

        service.control_clock({"action": "start", "minute": 0, "step_minutes": 30})
        service.clock.absolute_minute = 43 * 1440 + 23 * 60 + 30
        service.clock.minute = 23 * 60 + 30
        result = service.apply_student_commands(
            {
                "sent_absolute_minute": 0,
                "expires_at_absolute_minute": 1440,
                "set_values": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "grid_inv_acp",
                        "set_type": "p_set",
                        "set_value": -12.5,
                    }
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(self._set_value(service, "DCACConverter", "grid_inv_acp", "p_set"), "-12.5")
        service.step(advance_minutes=30)
        service.step(advance_minutes=30)
        self.assertEqual(self._set_value(service, "DCACConverter", "grid_inv_acp", "p_set"), "-12.5")

    def test_manual_control_commands_survive_stop_start_and_service_restart_until_cancelled(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        first_run = service.control_clock({"action": "start", "minute": 100})
        result = service.apply_student_commands(
            {
                "expires_at_absolute_minute": 500,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(service.command_history[-1]["run_id"], first_run["run_id"])
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        service.control_clock({"action": "pause"})
        service.control_clock({"action": "start"})
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        service.control_clock({"action": "stop"})
        second_run = service.control_clock({"action": "start", "minute": 200})

        self.assertNotEqual(first_run["run_id"], second_run["run_id"])
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        from simu.service import PolarMicrogridSimulator

        restarted = PolarMicrogridSimulator(service.sim_dir, service.runtime_dir, kernel=lambda _config: None)
        restarted.control_clock({"action": "start", "minute": 0})
        self.assertEqual(self._set_value(restarted, "ESS", "ess01", "p_set"), "20")
        by_name = {item["name"]: item for item in restarted.latest_control_values()["items"]}
        self.assertTrue(by_name["ESS.ess01.p_set"]["active"])

        restarted.cancel_student_commands(
            {"cancel_commands": [{"name": "ESS.ess01.p_set"}]},
            source="trainee-ui",
        )
        self.assertEqual(self._set_value(restarted, "ESS", "ess01", "p_set"), "10")

    def test_cancelled_manual_command_does_not_reactivate_when_clock_restarts_earlier(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.control_clock({"action": "start", "minute": 100})
        service.apply_student_commands(
            {
                "expires_at_absolute_minute": 150,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0}
                ],
            },
            source="trainee-ui",
        )
        service.clock.absolute_minute = 200
        service.clock.minute = 200
        service.apply_student_commands(
            {
                "expires_at_absolute_minute": 500,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0}
                ],
            },
            source="trainee-ui",
        )
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "0")

        service.clock.absolute_minute = 200
        service.clock.minute = 200
        result = service.cancel_student_commands(
            {"cancel_commands": [{"name": "ACGenerator.wt01_10kw.run_stat"}]},
            source="trainee-ui",
        )
        self.assertEqual(result["remote_controls"], 1)
        cancelled_rows = [
            item for item in service.command_history
            if item.get("cancelled")
            and any(
                row.get("dev_name") == "wt01_10kw"
                for row in item.get("normalized", {}).get("run_status", [])
                if isinstance(row, dict)
            )
        ]
        self.assertEqual(len(cancelled_rows), 2)
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "1")

        service.control_clock({"action": "stop"})
        service.control_clock({"action": "start", "minute": 0})
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "1")
        by_name = {item["name"]: item for item in service.latest_control_values()["items"]}
        self.assertFalse(by_name["ACGenerator.wt01_10kw.run_stat"]["active"])

    def test_legacy_cancel_history_entries_cancel_previous_manual_commands(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.control_clock({"action": "start", "minute": 100})
        service.apply_student_commands(
            {
                "expires_at_absolute_minute": 150,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0}
                ],
            },
            source="trainee-ui",
        )
        service.clock.absolute_minute = 200
        service.clock.minute = 200
        service.apply_student_commands(
            {
                "expires_at_absolute_minute": 500,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0}
                ],
            },
            source="trainee-ui",
        )
        self.assertEqual(self._run_stat(service, "ACGenerator", "wt01_10kw"), "0")

        service.command_history.append(
            {
                "time": "2026-07-26T16:39:15",
                "received_wall_time": "2026-07-26T16:39:15",
                "received_simu_time": "03:20:00",
                "received_absolute_minute": 200.0,
                "run_id": service.clock.run_id,
                "source": "trainee-ui",
                "eligible_source": True,
                "issued_absolute_minute": 200.0,
                "expires_at_absolute_minute": 205.0,
                "valid_for_minutes": 5.0,
                "accepted": {"run_status": 0, "set_values": 0, "ignored": 0},
                "normalized": {"run_status": [], "set_values": []},
                "payload": {
                    "source": "trainee-ui",
                    "cancel_commands": [{"name": "ACGenerator.wt01_10kw.run_stat"}],
                },
            }
        )
        service._write_command_history()

        from simu.service import PolarMicrogridSimulator

        restarted = PolarMicrogridSimulator(service.sim_dir, service.runtime_dir, kernel=lambda _config: None)
        restarted.control_clock({"action": "start", "minute": 0})
        self.assertEqual(self._run_stat(restarted, "ACGenerator", "wt01_10kw"), "1")
        by_name = {item["name"]: item for item in restarted.latest_control_values()["items"]}
        self.assertFalse(by_name["ACGenerator.wt01_10kw.run_stat"]["active"])

    def test_command_history_records_receive_wall_and_simulation_times(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "sent_wall_time": "10:18:09",
                "sent_simu_time": "00:00:00",
                "expires_at_absolute_minute": 10,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )

        entry = service.command_history[-1]
        self.assertIn("received_wall_time", entry)
        self.assertEqual(entry["received_simu_time"], "00:00:00")
        self.assertEqual(entry["received_absolute_minute"], 0.0)
        self.assertEqual(entry["run_id"], service.clock.run_id)
        self.assertEqual(entry["payload"]["sent_wall_time"], "10:18:09")
        self.assertEqual(entry["payload"]["sent_simu_time"], "00:00:00")

    def test_wind_generator_setpoint_command_updates_ac_generator_boundary(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "set_values": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "set_type": "p_set", "set_value": 3.3}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)

        import simu_loop

        _merged_path, _changed, merged_book = simu_loop.apply_realtime_inputs(
            service.files["model"],
            service.files["weather"],
            service.files["stat"],
            service.files["yt_ctrl"],
            None,
            service.runtime_dir / "work",
            60.0,
        )
        wind_generator = next(
            row
            for row in merged_book.data["ACGenerator"].data
            if row["name"] == "wt01_10kw"
        )
        self.assertAlmostEqual(float(wind_generator["p_set"]), 3.3)

    def test_trainee_can_cancel_active_remote_adjustment_command_by_name(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "expires_at_absolute_minute": 10,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")

        result = service.cancel_student_commands(
            {
                "cancel_commands": [
                    {"name": "ESS.ess01.p_set"}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["remote_adjustments"], 1)
        self.assertEqual(result["remote_controls"], 0)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")
        self.assertFalse(service.latest_control_values()["values"]["ESS.ess01.p_set"] == 20)

    def test_trainee_can_cancel_active_remote_control_command_by_name(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "expires_at_absolute_minute": 10,
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "run_stat": 0}
                ],
            },
            source="trainee-ui",
        )

        result = service.cancel_student_commands(
            {
                "commands": [
                    {"name": "ACGenerator.diesel_300kw.run_stat"}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["remote_controls"], 1)
        self.assertEqual(result["remote_adjustments"], 0)
        self.assertEqual(result["missing"], 0)
        by_name = {item["name"]: item for item in service.latest_control_values()["items"]}
        self.assertFalse(by_name["ACGenerator.diesel_300kw.run_stat"]["active"])

    def test_automatic_adjustment_cannot_be_cancelled_or_deleted_before_simulation_reset(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.apply_student_commands(
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

        cancelled = service.cancel_student_commands(
            {
                "command_origin": "automatic",
                "cancel_commands": [{"name": "ESS.ess01.p_set"}],
            },
            source="trainee-ui",
        )
        deleted = service.delete_active_commands(
            {"commands": [{"name": "ESS.ess01.p_set"}]},
            source="simulator-ui",
        )

        self.assertEqual(cancelled["remote_adjustments"], 0)
        self.assertEqual(cancelled["missing"], 1)
        self.assertEqual(deleted["remote_adjustments"], 0)
        self.assertEqual(deleted["missing"], 1)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        self.assertTrue(
            any(
                entry.get("command_origin") == "automatic"
                and entry.get("accepted", {}).get("set_values") == 1
                and not entry.get("cancelled")
                for entry in service.command_history
            )
        )


if __name__ == "__main__":
    unittest.main()
