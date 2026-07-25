from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path


class SimulatorSystemParametersTest(unittest.TestCase):
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
        self.assertEqual(service.snapshot()["system_parameters"]["compute_interval_seconds"], 0.5)
        self.assertEqual(service.local_settings["system_parameters"]["clock_speed"], 5.0)

        stopped = service.control_clock({"action": "stop"})
        self.assertEqual(stopped["speed"], 5.0)

        restored = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        self.assertEqual(restored.snapshot()["system_parameters"]["clock_speed"], 5.0)
        self.assertEqual(restored.snapshot()["system_parameters"]["compute_interval_seconds"], 0.5)

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
