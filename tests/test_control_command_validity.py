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
        self.assertEqual(self._set_value(service, "DCDCConverter", "ess01_dcdc", "p_set"), "10")

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
        self.assertEqual(self._set_value(service, "DCDCConverter", "ess01_dcdc", "p_set"), "10")

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
        self.assertEqual(self._set_value(service, "DCDCConverter", "ess01_dcdc", "p_set"), "20")
        service.step()
        service.step()
        self.assertEqual(self._set_value(service, "DCDCConverter", "ess01_dcdc", "p_set"), "10")


if __name__ == "__main__":
    unittest.main()
