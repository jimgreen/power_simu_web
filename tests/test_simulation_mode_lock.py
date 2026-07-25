from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


class SimulationModeLockTest(unittest.TestCase):
    def test_ui_disables_mode_controls_until_simulation_is_stopped(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("simulationModeLocked", app_js)
        self.assertIn('clock.state !== "stopped"', app_js)
        self.assertIn("button.disabled = modeLocked", app_js)
        self.assertIn("selector.disabled = modeLocked", app_js)

    def test_backend_rejects_mode_change_while_running_or_paused(self):
        source = ROOT / "models" / "simulator" / "source" / "简单模型"
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir) / "runtime"
            service = PolarMicrogridSimulator(
                source,
                runtime,
                model_id="mode-lock-test",
                model_name="mode-lock-test",
            )
            original_mode = service.curves.get("mode", "day")
            next_mode = "year" if original_mode == "day" else "day"
            payload = {
                "mode": next_mode,
                "time_step_minutes": 60 if next_mode == "year" else 1,
                "point_count": 8760 if next_mode == "year" else 1440,
                "weather": [],
                "loads": {},
            }

            service.clock.state = "running"
            with self.assertRaisesRegex(ValueError, "仿真运行过程中不能切换仿真模式"):
                service.set_curves(payload)

            service.clock.state = "paused"
            with self.assertRaisesRegex(ValueError, "仿真运行过程中不能切换仿真模式"):
                service.set_curves(payload)

            service.clock.state = "stopped"
            result = service.set_curves(payload)
            self.assertEqual(result["mode"], next_mode)


if __name__ == "__main__":
    unittest.main()
