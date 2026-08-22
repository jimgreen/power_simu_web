from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CommandActiveOnlyFilterUiTest(unittest.TestCase):
    def test_simulator_command_page_can_show_only_active_commands(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="runtimeCommandOnlyActive"', html)
        self.assertIn('id="runtimeCommandOnlyActiveText"', html)
        self.assertIn('role="switch"', html)
        self.assertIn("只显示有效指令", html)
        self.assertIn("runtimeCommandOnlyActive: false", script)

        filter_block = script.split("function applyRuntimeCommandTableFilters", 1)[1].split(
            "function runtimeCommandRowsForDevices",
            1,
        )[0]
        self.assertIn("state.runtimeCommandOnlyActive && !row.active", filter_block)
        self.assertIn("function queuedCommandHistory", script)
        self.assertIn("function displayedCommandHistory", script)
        self.assertIn("displayedCommandHistory(snapshot).forEach", script)
        self.assertIn("处理状态", script)
        self.assertIn("已接收，模拟台排队", script)
        self.assertIn("已接收，立即生效", script)

        remote_control_block = script.split("function runtimeRemoteControlRows", 1)[1].split(
            "function runtimeRemoteAdjustmentRows",
            1,
        )[0]
        remote_adjustment_block = script.split("function runtimeRemoteAdjustmentRows", 1)[1].split(
            "function renderRuntimeCommandTabs",
            1,
        )[0]
        self.assertIn("active: commandTimeInfoAvailable(runStatTime)", remote_control_block)
        self.assertIn("active: commandTimeInfoAvailable(statusTime)", remote_control_block)
        self.assertIn("active: commandTimeInfoAvailable(commandTime)", remote_adjustment_block)

        structure_block = script.split("function runtimeCommandTableStructureKey", 1)[1].split(
            "function runtimeCommandLiveCellHtml",
            1,
        )[0]
        self.assertIn('state.runtimeCommandOnlyActive ? "active" : "all"', structure_block)
        self.assertIn("function syncRuntimeCommandOnlyActiveControl", script)
        self.assertIn('document.addEventListener("change"', script)
        self.assertIn('target.closest("#runtimeCommandOnlyActive")', script)
        self.assertIn(".command-active-only-toggle", styles)

    def test_trainee_command_page_can_show_only_active_commands(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="commandOnlyActive"', html)
        self.assertIn('id="commandOnlyActiveText"', html)
        self.assertIn('role="switch"', html)
        self.assertIn("只显示有效指令", html)
        self.assertIn("commandOnlyActive: false", script)

        filter_block = script.split("function applyCommandTableFilters", 1)[1].split(
            "function traineeCommandTraceKey",
            1,
        )[0]
        self.assertIn("state.commandOnlyActive && !row.active", filter_block)
        self.assertIn("function queuedCommandHistory", script)
        self.assertIn("function displayedCommandHistory", script)
        self.assertIn('origin === "display"', script)
        self.assertIn("处理状态", script)
        self.assertIn("下发完成，模拟台排队", script)
        self.assertIn("下发完成，立即生效", script)

        remote_control_block = script.split("function remoteControlCommandRows", 1)[1].split(
            "function commandTableTypeLabel",
            1,
        )[0]
        remote_adjustment_block = script.split("function remoteAdjustmentRows", 1)[1].split(
            "function formatRemoteAdjustmentValue",
            1,
        )[0]
        self.assertIn('active: issuedTime.wall_time !== "--"', remote_control_block)
        self.assertIn('active: issuedTime.wall_time !== "--"', remote_adjustment_block)
        self.assertIn('activeCommandCancelName(row.dev, row.commandType, "", snapshot, issuedTime, "manual")', remote_control_block)
        self.assertIn('activeCommandCancelName(dev, "set_value", setType, snapshot, issuedTime, "manual")', remote_adjustment_block)

        structure_block = script.split("function traineeCommandTableStructureKey", 1)[1].split(
            "function traineeCommandCancelButtonHtml",
            1,
        )[0]
        self.assertIn('state.commandOnlyActive ? "active" : "all"', structure_block)
        self.assertIn("function syncCommandOnlyActiveControl", script)
        self.assertIn('document.addEventListener("change"', script)
        self.assertIn('target.closest("#commandOnlyActive")', script)
        self.assertIn(".command-active-only-toggle", styles)


if __name__ == "__main__":
    unittest.main()
