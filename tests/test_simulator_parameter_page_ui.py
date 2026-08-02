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
        self.assertIn('id="parameterStorageInitialSoc"', html)
        self.assertIn("时钟倍率", html)
        self.assertIn("每次触发推进量", html)
        self.assertIn("仿真周期", html)
        self.assertIn("后台计算触发间隔", html)
        self.assertIn("储能SOC初始值", html)
        for speed in (1, 5, 15, 30, 60, 300, 900, 1800, 3600):
            self.assertIn(f'<option value="{speed}">{speed}:1</option>', html)
        self.assertIn("function renderSystemParameters", script)
        self.assertIn('api("/api/config"', script)
        self.assertIn("compute_interval_seconds", script)
        self.assertIn("effective_step_seconds", script)
        self.assertIn("storage_initial_soc", script)
        self.assertIn(".parameter-page-layout", styles)
        self.assertIn(".system-parameter-table", styles)


if __name__ == "__main__":
    unittest.main()
