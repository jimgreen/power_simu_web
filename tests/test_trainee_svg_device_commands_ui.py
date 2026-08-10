from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeSvgDeviceCommandsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_svg_double_click_routes_devices_to_commands_and_blank_space_to_fit(self):
        if "function diagramSvgDoubleClickAction" not in self.script:
            self.fail("diagram SVG double-click routing helper is missing")
        helper = "function diagramSvgDoubleClickAction" + self.script.split(
            "function diagramSvgDoubleClickAction",
            1,
        )[1].split("function diagramViewBoxValue", 1)[0]
        body = """
process.stdout.write(JSON.stringify({
  device: diagramSvgDoubleClickAction("device", true),
  metric: diagramSvgDoubleClickAction("metric", true),
  blank: diagramSvgDoubleClickAction("", true),
  outside: diagramSvgDoubleClickAction("device", false),
}));
"""
        result = subprocess.run(
            ["node", "-e", f"{helper}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "device": "command",
                "metric": "ignore",
                "blank": "fit",
                "outside": "ignore",
            },
        )

    def test_svg_device_command_dialog_reuses_existing_manual_command_flows(self):
        required = (
            "function diagramDeviceCommandContext",
            "function openDiagramDeviceCommandForSvgDevice",
            "function activateDiagramDeviceCommandOption",
            "remoteControlCommandRows([dev], snapshot)",
            "remoteAdjustmentRows([dev], snapshot)",
            "openRemoteControlDialog(option.row.dev, option.row.commandType)",
            "openRemoteAdjustmentDialog(option.row)",
            "当前设备未配置遥控或遥调点",
        )
        for token in required:
            self.assertIn(token, self.script)

        dblclick_block = self.script.split(
            'container.addEventListener("dblclick"',
            1,
        )[1].split('container.addEventListener("pointerleave"', 1)[0]
        self.assertIn("diagramInteractionEventTarget", dblclick_block)
        self.assertIn("diagramHoverTarget", dblclick_block)
        self.assertIn("diagramSvgDoubleClickAction", dblclick_block)
        self.assertIn("openDiagramDeviceCommandForSvgDevice", dblclick_block)
        self.assertIn("fitDiagramViewport", dblclick_block)

    def test_selecting_svg_device_command_keeps_parent_dialog_open(self):
        helper = "function activateDiagramDeviceCommandOption" + self.script.split(
            "function activateDiagramDeviceCommandOption",
            1,
        )[1].split("function openDiagramDeviceCommandForSvgDevice", 1)[0]
        body = """
let closeCalls = 0;
let remoteControlCalls = 0;
let remoteAdjustmentCalls = 0;
function closeDiagramDeviceCommandDialog() { closeCalls += 1; }
function openRemoteControlDialog() { remoteControlCalls += 1; }
function openRemoteAdjustmentDialog() { remoteAdjustmentCalls += 1; }
activateDiagramDeviceCommandOption({
  kind: "remote-control",
  row: { dev: { dev_name: "switch-1" }, commandType: "status" },
});
activateDiagramDeviceCommandOption({
  kind: "remote-adjustment",
  row: { dev: { dev_name: "converter-1" }, setType: "p_ac_set" },
});
process.stdout.write(JSON.stringify({ closeCalls, remoteControlCalls, remoteAdjustmentCalls }));
"""
        result = subprocess.run(
            ["node", "-e", f"{helper}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "closeCalls": 0,
                "remoteControlCalls": 1,
                "remoteAdjustmentCalls": 1,
            },
        )

    def test_successful_svg_device_command_keeps_parent_dialog_open(self):
        self.assertIn("function refreshDiagramDeviceCommandDialog", self.script)
        refresh_block = self.script.split(
            "function refreshDiagramDeviceCommandDialog",
            1,
        )[1].split("function activateDiagramDeviceCommandOption", 1)[0]
        self.assertIn('$("diagramDeviceCommandDialog")', refresh_block)
        self.assertIn("dialog?.open", refresh_block)
        self.assertIn("state.diagramDeviceCommandContext", refresh_block)
        self.assertIn("diagramDeviceCommandContext(context.container, context.devId, snapshot)", refresh_block)

        remote_control_block = self.script.split(
            "async function sendRemoteControlCommand()",
            1,
        )[1].split("function findRemoteAdjustmentByKey", 1)[0]
        remote_adjustment_block = self.script.split(
            "async function sendRemoteAdjustmentCommand()",
            1,
        )[1].split("function handleTreeClick", 1)[0]
        self.assertIn("closeRemoteControlDialog();", remote_control_block)
        self.assertIn("closeRemoteAdjustmentDialog();", remote_adjustment_block)
        for command_block in (remote_control_block, remote_adjustment_block):
            self.assertNotIn("closeDiagramDeviceCommandDialog();", command_block)

    def test_open_svg_device_command_dialog_tracks_realtime_snapshot(self):
        render_block = self.script.split("function renderSnapshot(snapshot)", 1)[1].split(
            "function renderReceiveMode",
            1,
        )[0]
        self.assertIn("refreshDiagramDeviceCommandDialog(snapshot)", render_block)

    def test_diagram_snapshot_includes_live_devices_and_commands(self):
        devices_block = self.script.split("function pageNeedsDevices", 1)[1].split(
            "function pageNeedsDeviceStates",
            1,
        )[0]
        commands_block = self.script.split("function pageNeedsCommands", 1)[1].split(
            "function snapshotPollPath",
            1,
        )[0]
        self.assertIn('"diagram"', devices_block)
        self.assertIn('"diagram"', commands_block)

    def test_device_command_selector_markup_and_styles_are_present(self):
        for element_id in (
            "diagramDeviceCommandDialog",
            "diagramDeviceCommandTitle",
            "diagramDeviceCommandDevice",
            "diagramDeviceCommandType",
            "diagramDeviceCommandList",
            "diagramDeviceCommandHint",
            "diagramDeviceCommandClose",
            "diagramDeviceCommandCancel",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

        for selector in (
            ".diagram-device-command-dialog",
            ".diagram-device-command-list",
            ".diagram-device-command-option",
            ".diagram-device-command-option-main",
        ):
            self.assertIn(selector, self.styles)


if __name__ == "__main__":
    unittest.main()
