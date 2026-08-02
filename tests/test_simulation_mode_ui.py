from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulationModeUiTest(unittest.TestCase):
    def test_global_simulation_mode_controls_all_five_curve_resolutions(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="simulationModeSelector"', index_html)
        for mode, label in (
            ("hour", "时仿真"),
            ("day", "日仿真"),
            ("week", "周仿真"),
            ("month", "月仿真"),
            ("year", "年仿真"),
        ):
            self.assertIn(f'<option value="{mode}">{label}</option>', index_html)
            self.assertIn(f'data-curve-mode="{mode}"', index_html)
            self.assertIn(f'data-curve-display-mode="{mode}"', trainee_html)
        self.assertIn("loadCurvesFromSnapshot", app_js)
        self.assertIn("switchSimulationMode", app_js)
        self.assertIn("await saveCurves()", app_js)
        self.assertIn("simulationModeSelector", app_js)
        self.assertIn('hour: { key: "hour", label: "时曲线", pointCount: 3600, stepMinutes: 1 / 60', app_js)
        self.assertIn('week: { key: "week", label: "周曲线", pointCount: 10080, stepMinutes: 1', app_js)
        self.assertIn('month: { key: "month", label: "月曲线", pointCount: 720, stepMinutes: 60', app_js)
        self.assertIn('hour: { key: "hour", label: "时仿真", pointCount: 3600, stepMinutes: 1 / 60', trainee_js)
        self.assertIn('week: { key: "week", label: "周仿真", pointCount: 10080, stepMinutes: 1', trainee_js)
        self.assertIn('month: { key: "month", label: "月仿真", pointCount: 720, stepMinutes: 60', trainee_js)

    def test_clock_ratio_selector_exposes_every_confirmed_level(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")

        for ratio in (1, 5, 15, 30, 60, 300, 900, 1800, 3600):
            self.assertIn(f'<option value="{ratio}">{ratio}:1</option>', index_html)

    def test_global_mode_switch_can_update_curve_status_while_curve_page_is_detached(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function setCurveStatus", app_js)
        self.assertIn('state.pageSections?.curves?.querySelector("#curveStatus")', app_js)
        self.assertIn('setCurveStatus("已保存")', app_js)
        self.assertNotIn('$("curveStatus").textContent = "已保存"', app_js)

    def test_simulator_curve_mode_tabs_keep_one_line_on_narrow_screens(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".curve-toolbar > .curve-mode-control", styles)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", styles)
        self.assertIn("white-space: nowrap;", styles)


if __name__ == "__main__":
    unittest.main()
