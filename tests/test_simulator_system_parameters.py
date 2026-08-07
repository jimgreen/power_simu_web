from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path


class SimulatorSystemParametersTest(unittest.TestCase):
    def test_legacy_percent_storage_initial_soc_is_normalized_to_decimal_ratio(self):
        from simu.service import _storage_initial_soc

        self.assertEqual(_storage_initial_soc(50), 0.5)
        self.assertEqual(_storage_initial_soc("50"), 0.5)
        self.assertEqual(_storage_initial_soc("50%"), 0.5)
        self.assertEqual(_storage_initial_soc(0.5), 0.5)

    def test_service_saves_clock_speed_and_compute_interval_per_model(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

        result = service.set_system_parameters({"clock_speed": 5, "compute_interval_seconds": 0.5})

        self.assertEqual(result["clock"]["speed"], 5.0)
        self.assertEqual(result["system_parameters"]["clock_speed"], 5.0)
        self.assertEqual(result["system_parameters"]["compute_interval_seconds"], 0.5)
        self.assertEqual(result["system_parameters"]["clock_step_seconds"], 1.0)
        self.assertEqual(result["system_parameters"]["effective_step_seconds"], 5.0)
        self.assertEqual(service.snapshot()["system_parameters"]["compute_interval_seconds"], 0.5)
        self.assertEqual(service.local_settings["system_parameters"]["clock_speed"], 5.0)

        stopped = service.control_clock({"action": "stop"})
        self.assertEqual(stopped["speed"], 5.0)

        restored = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        self.assertEqual(restored.snapshot()["system_parameters"]["clock_speed"], 5.0)
        self.assertEqual(restored.snapshot()["system_parameters"]["compute_interval_seconds"], 0.5)
        self.assertEqual(restored.snapshot()["system_parameters"]["clock_step_seconds"], 1.0)
        self.assertEqual(restored.snapshot()["system_parameters"]["effective_step_seconds"], 5.0)

    def test_storage_initial_soc_defaults_persists_and_resets_on_stop_start(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

        self.assertEqual(service.snapshot()["system_parameters"]["storage_initial_soc"], 0.5)

        result = service.set_system_parameters({"storage_initial_soc": 0.65})
        self.assertEqual(result["system_parameters"]["storage_initial_soc"], 0.65)
        self.assertEqual(service.local_settings["system_parameters"]["storage_initial_soc"], 0.65)

        def current_soc() -> float:
            return float(service.runtime_stat_book.data["StorageSoc"].data[0]["soc_curr"])

        service.runtime_stat_book.data["StorageSoc"].data[0]["soc_curr"] = "0.21"
        service.control_clock({"action": "stop"})
        self.assertAlmostEqual(current_soc(), 0.65)

        service.runtime_stat_book.data["StorageSoc"].data[0]["soc_curr"] = "0.31"
        service.control_clock({"action": "start"})
        self.assertAlmostEqual(current_soc(), 0.65)

        restored = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        self.assertEqual(restored.snapshot()["system_parameters"]["storage_initial_soc"], 0.65)

    def test_storage_soc_resets_when_day_simulation_wraps_to_zero_clock(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        service.set_system_parameters({"storage_initial_soc": 0.72})
        service.control_clock({"action": "start", "minute": 1439, "step_minutes": 1, "speed": 1})
        service.runtime_stat_book.data["StorageSoc"].data[0]["soc_curr"] = "0.24"

        snapshot = service.step(advance_minutes=1)

        self.assertEqual(snapshot["clock"]["time"], "00:00:00")
        self.assertEqual(snapshot["clock"]["minute"], 0)
        self.assertAlmostEqual(float(service.runtime_stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.72)
        storage_devices = [item for item in snapshot["devices"] if item.get("soc_curr") is not None]
        self.assertTrue(storage_devices)
        self.assertTrue(all(float(item["soc_curr"]) == 0.72 for item in storage_devices))

    def test_clock_worker_respects_configured_compute_interval(self):
        from simu.generate_simple_model import write_model_dir
        from simu.server import _advance_clock_if_due
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        service.control_clock({"action": "start"})
        service.set_system_parameters({"clock_speed": 1, "compute_interval_seconds": 60})
        original_steps = service.snapshot()["clock"]["step_count"]

        _advance_clock_if_due(service, time.monotonic())
        self.assertEqual(service.snapshot()["clock"]["step_count"], original_steps)

        service.set_system_parameters({"compute_interval_seconds": 0.1})
        _advance_clock_if_due(service, time.monotonic() - 1)
        self.assertEqual(service.snapshot()["clock"]["step_count"], original_steps + 1)


if __name__ == "__main__":
    unittest.main()
