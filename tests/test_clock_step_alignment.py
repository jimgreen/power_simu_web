from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class ClockStepAlignmentTest(unittest.TestCase):
    def test_clock_time_is_aligned_down_to_the_simulation_step(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

        service.control_clock({"minute": 8 * 60 + 7})
        clock = service.control_clock({"step_minutes": 60})
        self.assertEqual(clock["minute"], 8 * 60)
        self.assertEqual(clock["time"], "08:00:00")

        clock = service.control_clock({"step_minutes": 15, "minute": 8 * 60 + 23})
        self.assertEqual(clock["minute"], 8 * 60 + 15)
        self.assertEqual(clock["time"], "08:15:00")

        clock = service.control_clock({"action": "start"})
        self.assertEqual(clock["minute"] % clock["step_minutes"], 0)

        service.control_clock({"minute": 8 * 60 + 7, "step_minutes": 1})
        service.set_curves(
            {
                "mode": "year",
                "time_step_minutes": 60,
                "point_count": 8760,
                "weather": [],
                "loads": {},
            }
        )
        clock = service.snapshot()["clock"]
        self.assertEqual(clock["step_minutes"], 60)
        self.assertEqual(clock["time"], "08:00:00")

        clock = service.control_clock({"step_minutes": 1, "minute": 72, "speed": 15})
        self.assertEqual(clock["time"], "01:00:00")
        self.assertEqual(clock["minute"] % 15, 0)

        clock = service.control_clock({"action": "step"})
        self.assertEqual(clock["time"], "01:15:00")
        self.assertEqual(clock["minute"] % 15, 0)


if __name__ == "__main__":
    unittest.main()
