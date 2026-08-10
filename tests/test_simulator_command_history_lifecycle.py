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
        manual_result = service.apply_student_commands(
            {
                "command_origin": "manual",
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
                ]
            },
            source="trainee-ui",
        )
        assert manual_result["run_status"] == 1
        assert manual_result["set_values"] == 1
        automatic_result = service.apply_student_commands(
            {
                "command_origin": "automatic",
                "valid_for_minutes": 120,
                "run_status": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "wt01_10kw",
                        "run_stat": 1,
                    }
                ],
                "set_values": [
                    {
                        "dev_type": "ESS",
                        "dev_name": "ess01",
                        "set_type": "p_set",
                        "set_value": 5,
                    }
                ],
            },
            source="trainee-automatic-control",
        )
        assert automatic_result["run_status"] == 1
        assert automatic_result["set_values"] == 1
        assert len(service.command_history) == 2

    def test_simulator_service_start_removes_automatic_commands_and_keeps_manual_commands(self) -> None:
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

            self.assertEqual(len(service.command_history), 1)
            self.assertEqual(service.command_history[0]["command_origin"], "manual")
            persisted = json.loads(service.commands_file.read_text(encoding="utf-8"))
            self.assertEqual(persisted, service.command_history)
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ACGenerator.wt01_10kw.run_stat")),
                "0",
            )
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ESS.ess01.p_set")),
                "20",
            )

    def test_simulator_clock_stop_removes_automatic_commands_and_keeps_manual_controls(self) -> None:
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
            manual_result = service.apply_student_commands(
                {
                    "command_origin": "manual",
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
                    ]
                },
                source="trainee-ui",
            )
            self.assertEqual(manual_result["run_status"], 1)
            self.assertEqual(manual_result["set_values"], 1)
            automatic_result = service.apply_student_commands(
                {
                    "command_origin": "automatic",
                    "valid_for_minutes": 120,
                    "run_status": [
                        {
                            "dev_type": "ACGenerator",
                            "dev_name": "wt01_10kw",
                            "run_stat": 1,
                        }
                    ],
                    "set_values": [
                        {
                            "dev_type": "ESS",
                            "dev_name": "ess01",
                            "set_type": "p_set",
                            "set_value": 5,
                        }
                    ],
                },
                source="trainee-automatic-control",
            )
            self.assertEqual(automatic_result["run_status"], 1)
            self.assertEqual(automatic_result["set_values"], 1)
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ESS.ess01.p_set")),
                "5",
            )

            service.control_clock({"action": "stop"})

            self.assertEqual(len(service.command_history), 1)
            self.assertEqual(service.command_history[0]["command_origin"], "manual")
            self.assertEqual(
                json.loads(service.commands_file.read_text(encoding="utf-8")),
                service.command_history,
            )
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ACGenerator.wt01_10kw.run_stat")),
                "0",
            )
            self.assertEqual(
                str(service.latest_control_values()["values"].get("ESS.ess01.p_set")),
                "20",
            )

    def test_simulator_service_start_keeps_manual_definition_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            copytree(SIMPLE_MODEL_SOURCE, source)
            service = PolarMicrogridSimulator(
                source,
                runtime,
                model_id="manual",
                kernel=lambda _config: None,
                clear_commands_on_start_and_reset=True,
            )
            service.update_device_parameters(
                {
                    "block_name": "ACGenerator",
                    "row_key": {"idx": "2", "name": "diesel_300kw"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"p_set": 95},
                }
            )

            restarted = PolarMicrogridSimulator(
                source,
                runtime,
                model_id="manual",
                kernel=lambda _config: None,
                clear_commands_on_start_and_reset=True,
            )

            row = next(
                item
                for item in restarted.definition_snapshot.model_book.data["ACGenerator"].data
                if item.get("name") == "diesel_300kw"
            )
            self.assertEqual(row["p_set"], "95")
            self.assertEqual(restarted.manual_definition_changes()["count"], 1)

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

            self.assertEqual(len(service.command_history), 2)
            self.assertEqual(len(json.loads(service.commands_file.read_text(encoding="utf-8"))), 2)


if __name__ == "__main__":
    unittest.main()
