from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ActivePageRenderingUiTest(unittest.TestCase):
    def test_simulator_navigation_omits_fault_and_mode_tabs(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        navigation = html.split('<nav class="page-nav"', 1)[1].split("</nav>", 1)[0]

        self.assertNotIn('data-nav-page="faults"', navigation)
        self.assertNotIn('data-nav-page="modes"', navigation)
        self.assertNotIn("故障设置", navigation)
        self.assertNotIn("运行模式", navigation)

    def test_simulator_uses_path_routes_and_detaches_inactive_pages(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('href="/styles.css', html)
        self.assertIn('src="/app.js', html)
        self.assertIn("const SIMULATOR_PAGE_ROUTES", script)
        for route in ('"/logs": "logs"', '"/modes": "modes"', '"/measurements": "measurements"', '"/diagram": "diagram"'):
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

        self.assertIn('href="/styles.css', html)
        self.assertIn('src="/app.js', html)
        self.assertIn("const TRAINEE_PAGE_ROUTES", script)
        for route in ('"/history": "history"', '"/commands": "commands"', '"/measurements": "measurements"', '"/diagram": "diagram"'):
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
            "renderModelDiagramPage()",
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
            "renderModelDiagramPage(snapshot)",
            "renderCombinedControlPage()",
            "renderRenewableControl(snapshot)",
            "renderHistory()",
        ):
            self.assertNotIn(heavy_render, render_snapshot)

    def test_trainee_runtime_logs_do_not_render_detached_history_page(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        add_log_block = script.split("function addRuntimeLog", 1)[1].split("function runtimeLogDetailText", 1)[0]
        render_history_block = script.split("function renderHistory()", 1)[1].split("function traineeRuntimeLogTypes", 1)[0]

        self.assertIn("function renderHistoryIfMounted", script)
        self.assertIn("renderHistoryIfMounted();", add_log_block)
        self.assertIn('const historyCount = $("historyCount");', render_history_block)
        self.assertIn('const commandHistory = $("commandHistory");', render_history_block)
        self.assertIn("if (!historyCount || !commandHistory) return;", render_history_block)

    def test_trainee_pending_command_refresh_tolerates_detached_pages(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        preview_block = script.split("function renderActiveCommandPreview", 1)[1].split("function updatePendingCount", 1)[0]
        update_block = script.split("function updatePendingCount", 1)[1].split("function formatNumber", 1)[0]

        self.assertIn('const pendingSummary = $("pendingSummary");', preview_block)
        self.assertIn('const pendingPreview = $("pendingPreview");', preview_block)
        self.assertIn("if (!pendingSummary || !pendingPreview) return;", preview_block)
        self.assertIn('setOptionalText("pendingCount"', update_block)
        self.assertIn('setOptionalText("runPendingCount"', update_block)
        self.assertIn('setOptionalText("setpointPendingCount"', update_block)
        self.assertIn('setOptionalText("commandPendingCount"', update_block)
        self.assertIn('setOptionalText("commandState"', update_block)


if __name__ == "__main__":
    unittest.main()
