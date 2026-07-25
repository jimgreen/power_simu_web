from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulatorParameterPageUiTest(unittest.TestCase):
    def test_simulator_has_system_parameter_configuration_page(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-nav-page="parameters"', html)
        self.assertIn('data-page="parameters"', html)
        self.assertIn('id="parameterClockSpeed"', html)
        self.assertIn('id="parameterComputeInterval"', html)
        self.assertIn("仿真步长", html)
        self.assertIn("仿真周期", html)
        self.assertIn("function renderSystemParameters", script)
        self.assertIn('api("/api/config"', script)
        self.assertIn("compute_interval_seconds", script)
        self.assertIn(".parameter-page-layout", styles)
        self.assertIn(".system-parameter-table", styles)


if __name__ == "__main__":
    unittest.main()
