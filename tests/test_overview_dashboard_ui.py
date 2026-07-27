from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewDashboardUiTest(unittest.TestCase):
    def test_overview_status_strip_keeps_content_vertically_centered(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        generic_panel_index = styles.index(".panel {")
        override_selector = ".panel.overview-status-panel {"
        self.assertIn(override_selector, styles)
        self.assertGreater(styles.index(override_selector), generic_panel_index)
        status_block = styles.split(override_selector, 1)[1].split("}", 1)[0]
        self.assertIn("padding: 0", status_block)
        self.assertIn("align-items: stretch", status_block)

    def test_overview_merges_realtime_results_into_energy_flow(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for text in ("输入边界", "当前控制指令", "最新运行事件"):
            self.assertIn(text, html)
        self.assertNotIn("电气能量流", html)
        self.assertNotIn("尚无计算结果", html)
        self.assertNotIn("功率差额", html)
        self.assertNotIn("energy-board-head", html)
        self.assertNotIn("energy-board-meta", html)
        self.assertNotIn("仿真流程", html)
        self.assertNotIn("功率平衡与仿真结果", html)
        self.assertNotIn("计算质量", html)
        self.assertNotIn("overview-result-panel", html)
        self.assertIn('id="overviewActiveCommandTable"', html)
        self.assertIn("renderOverviewActiveCommands", app_js)
        self.assertIn("overviewActiveRuntimeCommandRows", app_js)
        self.assertIn("activeRuntimeCommandKeySet", app_js)
        self.assertIn("commandTimeInfoAvailable(row.receive_time)", app_js)
        self.assertIn("接收本机时刻", app_js)
        self.assertIn("接收仿真时刻", app_js)
        for element_id in (
            "overviewFlowWindPower",
            "overviewFlowSolarPower",
            "overviewFlowDieselPower",
            "overviewFlowStoragePower",
            "overviewFlowLoadPower",
            "overviewFlowSoc",
            "overviewFlowGreenShare",
        ):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', app_js)
        for removed_id in ("overviewFlowBalance", "overviewFlowResultTime"):
            self.assertNotIn(f'id="{removed_id}"', html)
            self.assertNotIn(f'"{removed_id}"', app_js)
        for removed_id in (
            "overviewMeasurementQuality",
            "overviewSolverDetail",
            "overviewUpdatedMeasurements",
            "overviewMissingMeasurements",
            "overviewOverlayUpdates",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
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

    def test_overview_middle_uses_large_energy_flow_without_process_strip(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for text in ("数据输入", "指令处理", "能力校核", "网络求解", "结果发布"):
            self.assertNotIn(text, html)
        for removed_id in (
            "overviewProcessSummary",
            "overviewSimulationFlow",
            "overviewFlowInput",
            "overviewFlowControl",
            "overviewFlowConstraint",
            "overviewFlowSolver",
            "overviewFlowOutput",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
            self.assertNotIn(f'"{removed_id}"', app_js)
        for element_id in (
            "overviewFlowWindPower",
            "overviewFlowLoadPower",
        ):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', app_js)
        self.assertIn("overview-energy-board", html)
        self.assertIn("overview-energy-panel", html)
        self.assertIn("实时绿电占比", html)
        self.assertNotIn("1 - 柴发/负荷", html)
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
            "overviewFlowWindNode",
            "overviewFlowSolarNode",
            "overviewFlowLoadNode",
            "overviewFlowDieselNode",
        ):
            self.assertIn(f'id="{element_id}"', html)
        for css_hook in (
            ".energy-source-stack",
            ".energy-terminal-stack",
            ".energy-bus-rail.left",
            ".energy-bus-rail.right",
            ".energy-main-trunk",
            ".energy-storage-branch",
            ".energy-green-share",
            ".energy-flow-stream",
        ):
            self.assertIn(css_hook, styles)
        self.assertNotIn("energy-network-core", html)
        self.assertIn('"overviewStorageFlowLink"', app_js)

    def test_overview_green_power_share_uses_diesel_over_load_formula(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        green_share_start = styles.index(".energy-green-share {")
        green_share_block = styles[green_share_start : styles.index("\n}", green_share_start) + 2]

        self.assertIn("overviewPercentText", app_js)
        self.assertIn("(1.0 - power.diesel / power.load) * 100.0", app_js)
        self.assertIn('setOverviewText("overviewFlowGreenShare"', app_js)
        self.assertIn("return number.toFixed(2);", app_js)
        self.assertIn("top: 50%;", green_share_block)
        self.assertIn("transform: translate(-50%, calc(-100% - 8px));", green_share_block)
        self.assertNotIn("top: 54px;", green_share_block)
        self.assertIn("border-left: 3px solid var(--green);", green_share_block)

    def test_overview_energy_flow_has_dynamic_power_arrows(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("energy-flow-main-stream", html)
        self.assertIn("data-flow-active", html)
        for helper in (
            "renderEnergyFlowVisuals",
            "overviewFlowStyle",
            "overviewLoadFlowColor",
            "setOverviewFlowVisual",
        ):
            self.assertIn(helper, app_js)
        self.assertIn('setOverviewFlowVisual("overviewFlowLoadNode"', app_js)
        self.assertIn('setOverviewFlowVisual("overviewFlowDieselNode"', app_js)
        self.assertIn('setOverviewFlowVisual("overviewStorageFlowLink"', app_js)
        self.assertIn('setOverviewFlowVisual("overviewEnergyMainTrunk"', app_js)
        self.assertIn("@keyframes energyFlowForward", styles)
        self.assertIn("@keyframes energyFlowReverse", styles)
        self.assertIn("@keyframes energyFlowUp", styles)
        self.assertIn("--flow-thickness", styles)
        self.assertIn("prefers-reduced-motion", styles)

    def test_overview_energy_flow_is_horizontally_compact_and_vertically_open(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        def css_block(selector: str, text: str = styles) -> str:
            marker = f"{selector} {{"
            start = text.index(marker)
            end = text.index("\n}", start)
            return text[start : end + 2]

        energy_board_block = css_block(".overview-energy-board")
        energy_flow_block = css_block(".energy-flow-map")
        low_height_start = styles.index("@media (max-height: 780px)")
        mobile_start = styles.index("@media (max-width: 820px)", low_height_start)
        low_height_styles = styles[low_height_start:mobile_start]
        low_height_board_block = css_block(".overview-energy-board", low_height_styles)
        low_height_flow_block = css_block(".energy-flow-map", low_height_styles)

        self.assertIn("width: min(100%, 1360px);", styles)
        self.assertIn("justify-self: center;", energy_flow_block)
        self.assertIn("align-self: center;", energy_flow_block)
        self.assertIn("height: min(100%, 390px);", energy_flow_block)
        self.assertIn("min-height: 0;", energy_board_block)
        self.assertIn("place-items: center;", energy_board_block)
        self.assertIn("min-height: 0;", energy_flow_block)
        self.assertIn("grid-template-rows: minmax(0, 1fr);", energy_board_block)
        self.assertIn("padding: 0;", energy_board_block)
        self.assertIn("border: 0;", energy_board_block)
        self.assertIn("background: transparent;", energy_board_block)
        self.assertNotIn("background: #f7fafb;", energy_board_block)
        self.assertNotIn("border: 1px solid var(--line);", energy_board_block)
        self.assertNotIn("grid-template-rows: auto minmax(340px, 1fr);", energy_board_block)
        self.assertNotIn("grid-template-rows: auto minmax(0, 1fr);", energy_board_block)
        self.assertNotIn("min-height: 390px;", energy_board_block)
        self.assertNotIn("min-height: 340px;", energy_flow_block)
        self.assertIn("height: min(100%, 320px);", low_height_flow_block)
        self.assertIn("min-height: 0;", low_height_board_block)
        self.assertIn("min-height: 0;", low_height_flow_block)
        self.assertIn("grid-template-rows: minmax(0, 1fr);", low_height_board_block)
        self.assertNotIn("grid-template-rows: auto minmax(240px, 1fr);", low_height_board_block)
        self.assertNotIn("min-height: 276px;", low_height_board_block)
        self.assertNotIn("min-height: 240px;", low_height_flow_block)
        self.assertIn("height: 230px;", styles)
        self.assertIn("padding-bottom: 72px;", styles)
        self.assertIn("bottom: 178px;", styles)
        self.assertIn("padding-bottom: 4px;", low_height_styles)
        self.assertIn("min-height: 96px;", styles)
        self.assertIn(".energy-device.storage small", styles)
        self.assertNotIn(".simulation-flow", styles)

    def test_overview_bottom_tables_have_draggable_height_splitter(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="overviewBottomSplitter"', html)
        self.assertIn('role="separator"', html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn("调整下方表格高度", html)
        self.assertIn("--overview-bottom-height", styles)
        self.assertIn("grid-template-rows: auto minmax(180px, 1fr) 10px minmax(96px, var(--overview-bottom-height));", styles)
        self.assertIn("const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;", app_js)
        self.assertIn(".overview-bottom-splitter", styles)
        self.assertIn("cursor: row-resize;", styles)
        self.assertIn("is-overview-splitter-dragging", styles)
        self.assertIn("polarOverviewBottomHeight", app_js)
        self.assertIn("function initOverviewBottomSplitter", app_js)
        self.assertIn("function applyOverviewBottomHeight", app_js)
        self.assertIn("beginOverviewBottomSplitterDrag", app_js)
        self.assertIn("handleOverviewBottomSplitterKeydown", app_js)

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
