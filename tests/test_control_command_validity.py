from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


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
        import simu_loop

        book = simu_loop.EBook(service.files["stat"])
        for row in book.data["SetValue"].data:
            if row["dev_type"] == dev_type and row["dev_name"] == dev_name and row["set_type"] == set_type:
                return str(row["set_value"])
        return ""

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

    def test_trainee_control_command_expires_without_refresh(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 1,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        service.step()
        service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

    def test_trainee_control_command_can_remain_active_until_absolute_expiry(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "expires_at_absolute_minute": 10,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(result["set_values"], 1)
        for _ in range(6):
            service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "20")
        for _ in range(5):
            service.step()
        self.assertEqual(self._set_value(service, "ESS", "ess01", "p_set"), "10")

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
            service.files["device"],
            service.runtime_dir / "work",
            60.0,
        )
        wind_generator = next(
            row
            for row in merged_book.data["ACGenerator"].data
            if row["name"] == "wt01_10kw"
        )
        self.assertAlmostEqual(float(wind_generator["p_set"]), 3.3)


if __name__ == "__main__":
    unittest.main()
