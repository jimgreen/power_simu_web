from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeOverviewDashboardUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_trainee_home_uses_simulator_style_energy_flow(self):
        for text in ("电气能量流", "实时绿电占比", "教员数据", "最新交互事件", "当前有效指令"):
            self.assertIn(text, self.html)
        self.assertNotIn("接收质量", self.html)
        for element_id in (
            "overviewFlowWindPower",
            "overviewFlowSolarPower",
            "overviewFlowDieselPower",
            "overviewFlowStoragePower",
            "overviewFlowLoadPower",
            "overviewFlowBalance",
            "overviewFlowSoc",
            "overviewFlowGreenShare",
            "overviewReceiveDot",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
            self.assertIn(f'"{element_id}"', self.script)
        self.assertIn('data-flow-layout="single-line"', self.html)
        self.assertNotIn('class="one-line"', self.html)

    def test_trainee_home_removes_receive_quality_panel(self):
        overview = self.html.split('<section class="page-section is-active" data-page="overview">', 1)[1].split(
            '<section class="page-section" data-page="model">',
            1,
        )[0]
        for removed_text in ("接收质量", "量测有效率", "策略状态", "最近下发"):
            self.assertNotIn(removed_text, overview)
        for removed_id in (
            "overviewMeasurementQuality",
            "overviewMeasurementRate",
            "overviewRenewableState",
            "overviewLastCommand",
        ):
            self.assertNotIn(f'id="{removed_id}"', self.html)
            self.assertNotIn(f'"{removed_id}"', self.script)
        self.assertNotIn("overview-health-panel", self.html)
        self.assertNotIn("latestCommandIssuedAt", self.script)
        self.assertIn('id="pendingSummary"', overview)

    def test_trainee_home_shows_current_active_remote_commands(self):
        self.assertIn("function activeCommandPreviewRows", self.script)
        self.assertIn("function renderActiveCommandPreview", self.script)
        self.assertIn("activeCommandHistory(snapshot)", self.script)
        self.assertIn("遥控 · ${remoteControlLabel(commandType)}", self.script)
        self.assertIn("遥调 · ${remoteAdjustmentTypeLabel(item.set_type || \"\")}", self.script)
        self.assertIn('class="active-command-preview-wrap"', self.html)
        self.assertIn('class="active-command-preview-table"', self.script)
        for column in ("设备", "指令", "值", "仿真时刻"):
            self.assertIn(f"<th>{column}</th>", self.script)
        self.assertNotIn('<div class="log-item">\\n      <strong>${escapeHtml(item.name)}</strong>', self.script)
        self.assertIn("暂无当前有效指令", self.script)
        self.assertIn("renderActiveCommandPreview();", self.script)

    def test_trainee_home_renders_received_power_flow_and_status(self):
        for helper in (
            "renderTraineeOverviewDashboard",
            "parsePowerFlowOverview",
            "renderEnergyFlowVisuals",
            "overviewLoadFlowColor",
            "renderTraineeOverviewEvents",
        ):
            self.assertIn(helper, self.script)
        self.assertIn("(1.0 - power.diesel / power.load) * 100.0", self.script)
        for element_id in (
            "receiveStateText",
            "teacherSourceText",
            "measureCount",
            "validCount",
            "pendingCount",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("renderTraineeOverviewDashboard(snapshot);", self.script)

    def test_trainee_home_status_strip_hides_redundant_model_refresh_and_solver_items(self):
        status_strip = self.html.split('<dl class="overview-status-metrics trainee-status-metrics">', 1)[1].split("</dl>", 1)[0]

        for label in ("模型", "刷新时刻", "计算状态"):
            self.assertNotIn(f"<dt>{label}</dt>", status_strip)
        for element_id in ("overviewModel", "overviewRefresh", "topologyState"):
            self.assertNotIn(f'id="{element_id}"', status_strip)
            self.assertNotIn(f'"{element_id}"', self.script)

    def test_trainee_home_has_dynamic_flow_styles(self):
        for css_hook in (
            ".overview-dashboard",
            ".overview-status-panel",
            ".overview-energy-board",
            ".energy-flow-map",
            ".energy-flow-stream",
            ".energy-green-share",
            ".boundary-list",
            ".overview-event-list",
        ):
            self.assertIn(css_hook, self.styles)
        self.assertNotIn(".quality-list", self.styles)
        self.assertIn("@keyframes energyFlowForward", self.styles)
        self.assertIn("@keyframes energyFlowReverse", self.styles)
        self.assertIn("@keyframes energyFlowUp", self.styles)
        self.assertIn("--flow-thickness", self.styles)

    def test_trainee_home_bottom_tables_have_draggable_height_splitter(self):
        self.assertIn('id="overviewBottomSplitter"', self.html)
        self.assertIn('role="separator"', self.html)
        self.assertIn('aria-orientation="horizontal"', self.html)
        self.assertIn("调整下方表格高度", self.html)
        self.assertIn("--overview-bottom-height", self.styles)
        self.assertIn("grid-template-rows: auto minmax(390px, 1fr) 10px minmax(96px, var(--overview-bottom-height));", self.styles)
        self.assertIn(".overview-bottom-splitter", self.styles)
        self.assertIn("cursor: row-resize;", self.styles)
        self.assertIn("is-overview-splitter-dragging", self.styles)
        self.assertIn("polarTraineeOverviewBottomHeight", self.script)
        self.assertIn("function initOverviewBottomSplitter", self.script)
        self.assertIn("function applyOverviewBottomHeight", self.script)
        self.assertIn("beginOverviewBottomSplitterDrag", self.script)
        self.assertIn("handleOverviewBottomSplitterKeydown", self.script)

    def test_trainee_topbar_removes_send_command_button(self):
        self.assertNotIn("发送指令", self.html)
        self.assertNotIn('id="sendCommands"', self.html)
        self.assertNotIn("sendCommands", self.script)
        self.assertNotIn("#sendCommands", self.styles)


if __name__ == "__main__":
    unittest.main()
