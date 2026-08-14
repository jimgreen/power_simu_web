from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class CommandHistoryStartupFilterTest(unittest.TestCase):
    def test_startup_discards_commands_missing_from_current_control_definition(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        runtime.mkdir(parents=True, exist_ok=True)

        valid_run = {
            "dev_type": "ACGenerator",
            "dev_name": "diesel_300kw",
            "run_stat": 0,
        }
        removed_run = {
            "dev_type": "DCGenerator",
            "dev_name": "removed_pv_vsrc",
            "run_stat": 0,
        }
        valid_set = {
            "dev_type": "ACGenerator",
            "dev_name": "diesel_300kw",
            "set_type": "p_set",
            "set_value": 123,
        }
        undefined_set = {
            "dev_type": "ACGenerator",
            "dev_name": "diesel_300kw",
            "set_type": "not_defined",
            "set_value": 456,
        }
        stale_only = {
            "dev_type": "ESS",
            "dev_name": "removed_storage",
            "run_stat": 0,
        }
        history = [
            {
                "time": "2026-07-28T10:00:00",
                "source": "trainee-ui",
                "eligible_source": True,
                "manual_hold": True,
                "accepted": {"run_status": 2, "set_values": 2, "ignored": 0},
                "normalized": {
                    "run_status": [valid_run, removed_run],
                    "set_values": [valid_set, undefined_set],
                },
                "payload": {
                    "source": "trainee-ui",
                    "run_status": [valid_run, removed_run],
                    "set_values": [valid_set, undefined_set],
                },
            },
            {
                "time": "2026-07-28T10:01:00",
                "source": "trainee-ui",
                "eligible_source": True,
                "manual_hold": True,
                "accepted": {"run_status": 1, "set_values": 0, "ignored": 0},
                "normalized": {"run_status": [stale_only], "set_values": []},
                "payload": {"source": "trainee-ui", "run_status": [stale_only], "set_values": []},
            },
        ]
        commands_file = runtime / "commands.json"
        commands_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

        self.assertEqual(len(service.command_history), 1)
        retained = service.command_history[0]
        self.assertEqual(
            retained["normalized"],
            {
                "run_status": [{**valid_run, "run_stat": "0"}],
                "set_values": [{**valid_set, "set_value": "123"}],
            },
        )
        self.assertNotIn("run_status", retained["payload"])
        self.assertNotIn("set_values", retained["payload"])
        self.assertEqual(retained["payload"]["run_status_count"], 1)
        self.assertEqual(retained["payload"]["set_values_count"], 1)
        self.assertEqual(retained["accepted"], {"run_status": 1, "set_values": 1, "ignored": 2})

        persisted = json.loads(commands_file.read_text(encoding="utf-8"))
        self.assertEqual(persisted, service.command_history)

        run_rows = service.runtime_stat_book.data["RunStat"].data
        diesel_run = next(
            row for row in run_rows
            if row.get("dev_type") == "ACGenerator" and row.get("dev_name") == "diesel_300kw"
        )
        self.assertEqual(diesel_run["run_stat"], "0")
        set_rows = service.runtime_stat_book.data["SetValue"].data
        diesel_set = next(
            row for row in set_rows
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "diesel_300kw"
            and row.get("set_type") == "p_set"
        )
        self.assertEqual(diesel_set["set_value"], "123")


if __name__ == "__main__":
    unittest.main()
