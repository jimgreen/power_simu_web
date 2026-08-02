from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path


MODE_CASES = {
    "hour": {"step_minutes": 1 / 60, "point_count": 3600, "speed": 1, "duration_minutes": 60},
    "day": {"step_minutes": 1, "point_count": 1440, "speed": 60, "duration_minutes": 24 * 60},
    "week": {"step_minutes": 1, "point_count": 7 * 1440, "speed": 60, "duration_minutes": 7 * 1440},
    "month": {"step_minutes": 60, "point_count": 30 * 24, "speed": 3600, "duration_minutes": 30 * 1440},
    "year": {"step_minutes": 60, "point_count": 365 * 24, "speed": 3600, "duration_minutes": 365 * 1440},
}


class SimulationClockModesTest(unittest.TestCase):
    def create_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        return PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

    @staticmethod
    def curve_payload(mode: str):
        config = MODE_CASES[mode]
        return {
            "mode": mode,
            "time_step_minutes": config["step_minutes"],
            "point_count": config["point_count"],
            "weather": [],
            "loads": {},
        }

    def test_all_modes_use_the_confirmed_default_clock_speed(self):
        service = self.create_service()

        self.assertEqual(service.curves["mode"], "day")
        self.assertEqual(service.snapshot()["clock"]["speed"], MODE_CASES["day"]["speed"])

        for mode in ("hour", "week", "month", "year", "day"):
            service.set_curves(self.curve_payload(mode))
            snapshot = service.snapshot()
            self.assertEqual(snapshot["curves"]["mode"], mode)
            self.assertEqual(snapshot["clock"]["speed"], MODE_CASES[mode]["speed"])
            self.assertAlmostEqual(snapshot["curves"]["time_step_minutes"], MODE_CASES[mode]["step_minutes"])
            self.assertEqual(snapshot["curves"]["point_count"], MODE_CASES[mode]["point_count"])

    def test_single_step_uses_clock_ratio_instead_of_curve_sampling_interval(self):
        service = self.create_service()

        for mode, config in MODE_CASES.items():
            service.control_clock({"action": "stop"})
            service.set_curves(self.curve_payload(mode))
            before_seconds = service.snapshot()["clock"]["absolute_second"]
            clock = service.control_clock({"action": "step"})
            self.assertAlmostEqual(clock["absolute_second"] - before_seconds, config["speed"], places=6)
            self.assertAlmostEqual(clock["effective_step_seconds"], config["speed"], places=6)

    def test_curve_sampling_interval_does_not_multiply_a_user_selected_clock_ratio(self):
        service = self.create_service()

        for mode in ("hour", "day", "week", "month", "year"):
            service.control_clock({"action": "stop"})
            service.set_curves(self.curve_payload(mode))
            service.set_system_parameters({"clock_speed": 60, "compute_interval_seconds": 1})
            clock = service.control_clock({"action": "step"})
            self.assertAlmostEqual(clock["absolute_second"], 60, places=6, msg=mode)
            self.assertAlmostEqual(clock["effective_step_seconds"], 60, places=6, msg=mode)

    def test_worker_preserves_ratio_when_compute_interval_is_not_one_second(self):
        from simu.server import _advance_clock_if_due

        service = self.create_service()
        service.set_curves(self.curve_payload("hour"))
        service.set_system_parameters({"clock_speed": 5, "compute_interval_seconds": 0.5})
        service.control_clock({"action": "start"})

        _advance_clock_if_due(service, time.monotonic() - 1)

        clock = service.snapshot()["clock"]
        self.assertAlmostEqual(clock["absolute_second"], 2.5, places=6)
        self.assertAlmostEqual(clock["effective_step_seconds"], 2.5, places=6)

    def test_clock_speed_controls_cover_all_confirmed_ratios(self):
        service = self.create_service()
        expected = [1, 5, 15, 30, 60, 300, 900, 1800, 3600]

        observed = [service.control_clock({"speed": 1})["speed"]]
        for _index in range(len(expected) - 1):
            observed.append(service.control_clock({"action": "faster"})["speed"])

        self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
