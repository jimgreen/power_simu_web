from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewDashboardUiTest(unittest.TestCase):
    def test_overview_merges_realtime_results_into_energy_flow(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for text in ("仿真流程", "输入边界", "电气能量流", "最新运行事件"):
            self.assertIn(text, html)
        self.assertNotIn("功率平衡与仿真结果", html)
        self.assertNotIn("overview-result-panel", html)
        for element_id in (
            "overviewFlowWindPower",
            "overviewFlowSolarPower",
            "overviewFlowDieselPower",
            "overviewFlowStoragePower",
            "overviewFlowLoadPower",
            "overviewFlowBalance",
            "overviewFlowSoc",
            "overviewFlowResultTime",
        ):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', app_js)
        for removed_id in (
            "overviewWindPower",
            "overviewSolarPower",
            "overviewDieselPower",
            "overviewStoragePower",
            "overviewLoadPower",
            "overviewPowerBalance",
            "overviewSoc",
            "overviewResultTime",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
        self.assertIn("renderOverviewDashboard", app_js)
        self.assertIn("parsePowerFlowOverview", app_js)

    def test_overview_middle_uses_operational_stages_and_energy_flow(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for text in ("数据输入", "指令处理", "能力校核", "网络求解", "结果发布"):
            self.assertIn(text, html)
        for element_id in (
            "overviewFlowInput",
            "overviewFlowControl",
            "overviewFlowConstraint",
            "overviewFlowSolver",
            "overviewFlowOutput",
            "overviewFlowWindPower",
            "overviewFlowLoadPower",
        ):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', app_js)
        self.assertIn("overview-energy-board", html)
        self.assertNotIn("overview-network-strip", html)

    def test_overview_energy_flow_uses_reference_single_line_topology(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('data-flow-layout="single-line"', html)
        for element_id in (
            "overviewEnergyLeftBus",
            "overviewEnergyMainTrunk",
            "overviewEnergyRightBus",
            "overviewStorageFlowLink",
        ):
            self.assertIn(f'id="{element_id}"', html)
        for css_hook in (
            ".energy-source-stack",
            ".energy-terminal-stack",
            ".energy-bus-rail.left",
            ".energy-bus-rail.right",
            ".energy-main-trunk",
            ".energy-storage-branch",
        ):
            self.assertIn(css_hook, styles)
        self.assertNotIn("energy-network-core", html)
        self.assertIn('"overviewStorageFlowLink"', app_js)

    def test_overview_energy_flow_is_horizontally_compact_and_vertically_open(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("width: min(100%, 1060px);", styles)
        self.assertIn("justify-self: center;", styles)
        self.assertIn("min-height: 238px;", styles)
        self.assertIn("height: 164px;", styles)
        self.assertIn("bottom: 70px;", styles)

    def test_overview_soc_falls_back_to_control_response_storage_soc(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("storageSocPercentFromText", app_js)
        self.assertIn('latestRuntimeLog(snapshot, "控制响应")', app_js)
        self.assertIn("ESS\\.", app_js)

    def test_mobile_topbar_does_not_keep_desktop_toolbar_height(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(
            ".model-toolbar {\n"
            "    width: 100%;\n"
            "    min-width: 0;\n"
            "    max-width: none;\n"
            "    flex: 0 0 auto;\n"
            "    flex-wrap: wrap;",
            styles,
        )


if __name__ == "__main__":
    unittest.main()
