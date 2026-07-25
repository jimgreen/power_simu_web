from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulationModeUiTest(unittest.TestCase):
    def test_global_simulation_mode_controls_curve_resolution_and_backend_mode(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="simulationModeSelector"', index_html)
        self.assertIn('<option value="year">年仿真</option>', index_html)
        self.assertIn('<option value="day">日仿真</option>', index_html)
        self.assertIn("loadCurvesFromSnapshot", app_js)
        self.assertIn("switchSimulationMode", app_js)
        self.assertIn("await saveCurves()", app_js)
        self.assertIn("simulationModeSelector", app_js)


if __name__ == "__main__":
    unittest.main()
