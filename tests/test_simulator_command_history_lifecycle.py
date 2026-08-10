from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from simu.service import MultiModelSimulator, PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


class SimulatorCommandHistoryLifecycleTest(unittest.TestCase):
    @staticmethod
    def _seed_command_history(source: Path, runtime: Path) -> None:
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        result = service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 20,
                    }
                ]
            },
            source="trainee-ui",
        )
        assert result["set_values"] == 1
        assert service.command_history

    def test_simulator_service_start_clears_persisted_command_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            copytree(SIMPLE_MODEL_SOURCE, source)
            self._seed_command_history(source, runtime)

            service = PolarMicrogridSimulator(
                source,
                runtime,
                kernel=lambda _config: None,
                clear_commands_on_start_and_reset=True,
            )

            self.assertEqual(service.command_history, [])
            self.assertEqual(json.loads(service.commands_file.read_text(encoding="utf-8")), [])

    def test_simulator_clock_stop_clears_memory_file_and_effective_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            copytree(SIMPLE_MODEL_SOURCE, source)
            service = PolarMicrogridSimulator(
                source,
                runtime,
                kernel=lambda _config: None,
                clear_commands_on_start_and_reset=True,
            )
            result = service.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": "ESS",
                            "dev_name": "ess01",
                            "set_type": "p_set",
                            "set_value": 20,
                        }
                    ]
                },
                source="trainee-ui",
            )
            self.assertEqual(result["set_values"], 1)
            self.assertTrue(service.command_history)
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ESS.ess01.p_set")),
                "20",
            )

            service.control_clock({"action": "stop"})

            self.assertEqual(service.command_history, [])
            self.assertEqual(json.loads(service.commands_file.read_text(encoding="utf-8")), [])
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ESS.ess01.p_set")),
                "10",
            )

    def test_simulator_new_model_starts_with_empty_command_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "base")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                root / "runtime",
                models_dir=models_root,
                runtime_role="simulator",
            )

            manager.clone_model("base", "created")
            created = manager.service_for("created")

            self.assertEqual(created.command_history, [])
            self.assertEqual(json.loads(created.commands_file.read_text(encoding="utf-8")), [])

    def test_trainee_service_start_preserves_persisted_command_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            copytree(SIMPLE_MODEL_SOURCE, source)
            self._seed_command_history(source, runtime)

            service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

            self.assertTrue(service.command_history)
            self.assertNotEqual(json.loads(service.commands_file.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
