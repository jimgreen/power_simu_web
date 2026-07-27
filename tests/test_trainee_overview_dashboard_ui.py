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
        for text in ("实时绿电占比", "教员数据", "最新交互事件", "当前有效指令"):
            self.assertIn(text, self.html)
        self.assertNotIn("电气能量流", self.html)
        self.assertNotIn("尚无接收结果", self.html)
        self.assertNotIn("功率差额", self.html)
        self.assertNotIn("energy-board-head", self.html)
        self.assertNotIn("energy-board-meta", self.html)
        self.assertNotIn("接收质量", self.html)
        for element_id in (
            "overviewFlowWindPower",
            "overviewFlowSolarPower",
            "overviewFlowDieselPower",
            "overviewFlowStoragePower",
            "overviewFlowLoadPower",
            "overviewFlowSoc",
            "overviewFlowGreenShare",
            "overviewReceiveDot",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
            self.assertIn(f'"{element_id}"', self.script)
        for removed_id in ("overviewFlowBalance", "overviewFlowResultTime"):
            self.assertNotIn(f'id="{removed_id}"', self.html)
            self.assertNotIn(f'"{removed_id}"', self.script)
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
        self.assertIn("actual_value", self.script)
        self.assertIn("snapshotDevice(item.dev_type || \"\", item.dev_name || \"\", snapshot)", self.script)
        self.assertIn("remoteAdjustmentMeasurement(liveDev, item.set_type || \"\", snapshot)", self.script)
        self.assertIn('class="active-command-preview-wrap"', self.html)
        self.assertIn('class="active-command-preview-table"', self.script)
        for column in ("设备", "指令", "指令值", "实时值", "仿真时刻"):
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

    def test_trainee_home_data_source_uses_detailed_receive_address(self):
        self.assertIn('teacherSnapshotPath: localStorage.getItem("polarTeacherSnapshotPath")', self.script)
        self.assertIn("function teacherSnapshotPath()", self.script)
        self.assertIn("function teacherReceiveAddress()", self.script)
        self.assertIn("function displayReceiveAddress", self.script)
        self.assertIn("state.teacherSnapshotPath = connection.snapshotPath", self.script)
        self.assertIn('localStorage.setItem("polarTeacherSnapshotPath", state.teacherSnapshotPath)', self.script)

        receive_mode_block = self.script.split("function renderReceiveMode", 1)[1].split("function curveMinute", 1)[0]
        self.assertIn("const receiveAddress = teacherReceiveAddress();", receive_mode_block)
        self.assertIn("const receiveAddressText = displayReceiveAddress(receiveAddress);", receive_mode_block)
        self.assertIn("sourceText.title = receiveAddress;", receive_mode_block)
        self.assertIn("sourceText.textContent = receiveAddressText", receive_mode_block)
        self.assertNotIn(": teacherApiBase;", receive_mode_block)

        self.assertIn("#teacherSourceText", self.styles)
        self.assertIn("overflow-wrap: anywhere;", self.styles)

    def test_trainee_home_has_dynamic_flow_styles(self):
        green_share_start = self.styles.index(".energy-green-share {")
        green_share_block = self.styles[green_share_start : self.styles.index("\n}", green_share_start) + 2]

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
        self.assertIn("top: 50%;", green_share_block)
        self.assertIn("transform: translate(-50%, calc(-100% - 8px));", green_share_block)
        self.assertNotIn("top: 54px;", green_share_block)

    def test_trainee_home_bottom_tables_have_draggable_height_splitter(self):
        self.assertIn('id="overviewBottomSplitter"', self.html)
        self.assertIn('role="separator"', self.html)
        self.assertIn('aria-orientation="horizontal"', self.html)
        self.assertIn("调整下方表格高度", self.html)
        self.assertIn("--overview-bottom-height", self.styles)
        self.assertIn("grid-template-rows: auto minmax(180px, 1fr) 10px minmax(96px, var(--overview-bottom-height));", self.styles)
        self.assertIn("const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;", self.script)
        self.assertIn(".overview-bottom-splitter", self.styles)
        self.assertIn("cursor: row-resize;", self.styles)
        self.assertIn("is-overview-splitter-dragging", self.styles)
        self.assertIn("polarTraineeOverviewBottomHeight", self.script)
        self.assertIn("function initOverviewBottomSplitter", self.script)
        self.assertIn("function applyOverviewBottomHeight", self.script)
        self.assertIn("beginOverviewBottomSplitterDrag", self.script)
        self.assertIn("handleOverviewBottomSplitterKeydown", self.script)

    def test_trainee_home_energy_flow_stays_centered_when_bottom_height_changes(self):
        self.assertIn(".overview-energy-board", self.styles)
        self.assertIn("grid-template-rows: minmax(0, 1fr);", self.styles)
        self.assertIn("place-items: center;", self.styles)
        self.assertIn("padding: 0;", self.styles)
        self.assertIn("border: 0;", self.styles)
        self.assertIn("background: transparent;", self.styles)
        self.assertIn("height: min(100%, 390px);", self.styles)
        self.assertIn("align-self: center;", self.styles)
        self.assertIn("padding-bottom: 72px;", self.styles)
        self.assertIn("bottom: 178px;", self.styles)
        self.assertNotIn("grid-template-rows: auto minmax(340px, 1fr);", self.styles)
        self.assertNotIn(".energy-board-head", self.styles)
        self.assertNotIn(".energy-board-meta", self.styles)
        self.assertNotIn("min-height: 340px;", self.styles)

    def test_trainee_topbar_removes_send_command_button(self):
        self.assertNotIn("发送指令", self.html)
        self.assertNotIn('id="sendCommands"', self.html)
        self.assertNotIn("sendCommands", self.script)
        self.assertNotIn("#sendCommands", self.styles)


if __name__ == "__main__":
    unittest.main()
