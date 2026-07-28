from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ActivePageRenderingUiTest(unittest.TestCase):
    def test_simulator_uses_path_routes_and_detaches_inactive_pages(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('href="/styles.css"', html)
        self.assertIn('src="/app.js"', html)
        self.assertIn("const SIMULATOR_PAGE_ROUTES", script)
        for route in ('"/logs": "logs"', '"/modes": "modes"', '"/measurements": "measurements"'):
            self.assertIn(route, script)
        self.assertIn("function collectPageSections", script)
        self.assertIn("function mountPageSection", script)
        self.assertIn("section.remove();", script)
        self.assertIn("main.appendChild(section);", script)
        self.assertIn('history.pushState(null, "", nextPath)', script)
        self.assertNotIn("pageFromHash", script)

    def test_trainee_uses_path_routes_and_detaches_inactive_pages(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('href="/styles.css"', html)
        self.assertIn('src="/app.js"', html)
        self.assertIn("const TRAINEE_PAGE_ROUTES", script)
        for route in ('"/history": "history"', '"/commands": "commands"', '"/measurements": "measurements"'):
            self.assertIn(route, script)
        self.assertIn("function collectPageSections", script)
        self.assertIn("function mountPageSection", script)
        self.assertIn("section.remove();", script)
        self.assertIn("main.appendChild(section);", script)
        self.assertIn('history.pushState(null, "", nextPath)', script)
        self.assertNotIn("pageFromHash", script)

    def test_simulator_refresh_only_renders_active_heavy_page(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        render_snapshot = script.split("function renderSnapshot(snapshot) {", 1)[1].split("function appendRuntimeLog", 1)[0]

        self.assertIn("function renderActiveSimulatorPage", script)
        self.assertIn("currentPageName()", script)
        self.assertIn("renderActiveSimulatorPage(snapshot)", render_snapshot)
        for heavy_render in (
            "renderRuntimeLogs()",
            "renderMeasurementCompareTable()",
            "renderGridModelPage()",
            "renderRuntimeMonitor()",
            "renderCurveEditor()",
            "renderFaults()",
            "renderModes()",
        ):
            self.assertNotIn(heavy_render, render_snapshot)

    def test_trainee_refresh_only_renders_active_heavy_page(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        render_snapshot = script.split("function renderSnapshot(snapshot) {", 1)[1].split("function renderReceiveMode", 1)[0]

        self.assertIn("function renderActiveTraineePage", script)
        self.assertIn("currentPageName()", script)
        self.assertIn("renderActiveTraineePage(snapshot)", render_snapshot)
        for heavy_render in (
            "renderTraineeModelPage(snapshot)",
            "renderCurveDisplay(snapshot)",
            "renderMeasurements(snapshot)",
            "renderCombinedControlPage()",
            "renderRenewableControl(snapshot)",
            "renderHistory()",
        ):
            self.assertNotIn(heavy_render, render_snapshot)


if __name__ == "__main__":
    unittest.main()
