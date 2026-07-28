from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree


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

    def test_strategy_control_command_expires_without_refresh(self):
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
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_strategy_control_command_can_remain_active_until_absolute_expiry(self):
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
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

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

    def test_manual_control_commands_override_later_strategy_commands(self):
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
        service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "strategy": {"name": "renewable_priority"},
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 5}
                ],
            },
            source="trainee-renewable-priority",
        )

        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        by_name = {item["name"]: item for item in service.latest_control_values()["items"]}
        self.assertTrue(by_name["ESS.ess01.p_set"]["active"])
        self.assertIsNone(by_name["ESS.ess01.p_set"]["expires_at_absolute_minute"])

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

    def test_manual_acdc_active_power_command_with_stale_trainee_expiry_survives_next_step(self):
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        source = Path(workspace.name) / "source"
        copytree(ROOT / "models" / "simulator" / "source" / "默认模型", source)
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
                        "dev_name": "ACDC变流器-1",
                        "set_type": "p_ac_set",
                        "set_value": -12.5,
                    }
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(self._set_value(service, "DCACConverter", "ACDC变流器-1", "p_ac_set"), "-12.5")
        service.step(advance_minutes=30)
        service.step(advance_minutes=30)
        self.assertEqual(self._set_value(service, "DCACConverter", "ACDC变流器-1", "p_ac_set"), "-12.5")

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


if __name__ == "__main__":
    unittest.main()
