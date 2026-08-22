import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRemoteControlDialogUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_remote_control_dialog_is_available(self):
        self.assertIn('id="remoteControlDialog"', self.html)
        self.assertIn('id="remoteControlConfirm"', self.html)
        self.assertIn('name="remoteControlState"', self.html)

    def test_current_status_supports_double_click_remote_control(self):
        self.assertIn("data-run-status-command", self.script)
        self.assertIn('document.addEventListener("dblclick"', self.script)
        self.assertIn("openRemoteControlDialog", self.script)

    def test_confirm_sends_one_remote_control_command_immediately(self):
        self.assertIn("sendRemoteControlCommand", self.script)
        self.assertIn('source: "trainee-ui"', self.script)
        self.assertIn('run_status: [command]', self.script)

    def test_remote_control_response_requires_an_accepted_command(self):
        self.assertIn("function remoteControlCommandAcceptance", self.script)
        helper = "function remoteControlCommandAcceptance" + self.script.split(
            "function remoteControlCommandAcceptance",
            1,
        )[1].split("function remoteControlFeedbackSnapshotPath", 1)[0]
        body = """
const rejected = remoteControlCommandAcceptance({ run_status: 0, ignored: 1 });
const accepted = remoteControlCommandAcceptance({ run_status: 1, ignored: 0 });
const wrapped = remoteControlCommandAcceptance({ accepted: { remote_controls: 1, ignored: 0 } });
const queued = remoteControlCommandAcceptance({
  run_status: 1,
  ignored: 0,
  queued: 1,
  blocked: [{ reason: "simulator_manual_override", message: "模拟台人工修改已固定开关状态" }],
});
process.stdout.write(JSON.stringify({ rejected, accepted, wrapped, queued }));
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
                "rejected": {"accepted": 0, "ignored": 1, "ok": False},
                "accepted": {"accepted": 1, "ignored": 0, "ok": True},
                "wrapped": {"accepted": 1, "ignored": 0, "ok": True},
                "queued": {
                    "accepted": 1,
                    "ignored": 0,
                    "queued": 1,
                    "blocked": [
                        {
                            "reason": "simulator_manual_override",
                            "message": "模拟台人工修改已固定开关状态",
                        }
                    ],
                    "ok": True,
                    "ready": False,
                },
            },
        )

    def test_remote_control_target_comparison_prefers_live_feedback(self):
        self.assertIn("function remoteControlFeedbackValue", self.script)
        helper = "function remoteControlMeasuredValue" + self.script.split(
            "function remoteControlMeasuredValue",
            1,
        )[1].split("function controlDeviceFromRow", 1)[0]
        body = """
const state = { snapshot: {} };
function deviceType(dev) { return dev.dev_type; }
function deviceName(dev) { return dev.dev_name; }
function snapshotDevice(devType, devName, snapshot) {
  return (snapshot.devices || []).find((dev) => dev.dev_type === devType && dev.dev_name === devName) || null;
}
const dev = { dev_type: "ACBreak", dev_name: "盒型开关-4", status: 0, run_stat: 1 };
const measuredSnapshot = {
  devices: [{ dev_type: "ACBreak", dev_name: "盒型开关-4", status: 0, run_stat: 1 }],
  measurements: {
    scada: [{ dev_type: "ACBreak", dev_name: "盒型开关-4", meas_type: "STATUS", valid: 1, value: 1 }],
    real: [],
  },
};
const runtimeSnapshot = {
  devices: [{ dev_type: "ACBreak", dev_name: "盒型开关-4", status: 0, run_stat: 1 }],
  measurements: { scada: [], real: [] },
};
const realOnlySnapshot = {
  devices: [],
  measurements: {
    scada: [],
    real: [{ dev_type: "ACBreak", dev_name: "盒型开关-4", meas_type: "STATUS", valid: 1, value: 1 }],
  },
};
process.stdout.write(JSON.stringify({
  measured: remoteControlFeedbackValue(dev, "status", measuredSnapshot),
  runtime: remoteControlFeedbackValue(dev, "status", runtimeSnapshot),
  realOnly: remoteControlFeedbackValue(dev, "status", realOnlySnapshot),
  realMeasured: remoteControlMeasuredValue("ACBreak", "盒型开关-4", "status", realOnlySnapshot),
  alreadyClosed: remoteControlTargetAlreadyReached(dev, "status", 1, measuredSnapshot),
  alreadyOpen: remoteControlTargetAlreadyReached(dev, "status", 0, measuredSnapshot),
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
                    "measured": 1,
                    "runtime": 0,
                    "realOnly": 0,
                    "realMeasured": None,
                    "alreadyClosed": True,
                    "alreadyOpen": False,
                },
        )

    def test_remote_control_send_checks_noop_acceptance_and_feedback(self):
        send_block = self.script.split("async function sendRemoteControlCommand()", 1)[1].split(
            "function findRemoteAdjustmentByKey",
            1,
        )[0]
        self.assertIn("remoteControlTargetAlreadyReached", send_block)
        self.assertIn("remoteControlCommandAcceptance(result)", send_block)
        self.assertIn("if (!acceptance.ok)", send_block)
        self.assertIn("await waitForRemoteControlFeedback", send_block)
        self.assertIn("if (acceptance.queued > 0)", send_block)
        self.assertIn("已记录，排队等待", send_block)
        self.assertIn("feedback.confirmed", send_block)
        self.assertIn("当前已经是", send_block)
        self.assertIn("未重复下发", send_block)

    def test_successful_remote_control_closes_only_top_operation_dialog(self):
        success_block = self.script.split("async function sendRemoteControlCommand()", 1)[1].split(
            "} catch (error)",
            1,
        )[0]
        self.assertIn("closeRemoteControlDialog();", success_block)
        self.assertNotIn("closeDiagramDeviceCommandDialog();", success_block)
        self.assertNotIn('feedback.confirmed ? "继续下发" : "检查后重试"', success_block)

    def test_failed_remote_control_keeps_dialog_open_for_retry(self):
        failure_block = self.script.split("async function sendRemoteControlCommand()", 1)[1].split(
            "} catch (error)",
            1,
        )[1].split("function findRemoteAdjustmentByKey", 1)[0]
        self.assertNotIn("closeRemoteControlDialog();", failure_block)
        self.assertIn('$("remoteControlConfirm").textContent = "重新下发";', failure_block)

    def test_remote_control_current_state_prefers_live_signal_measurement(self):
        self.assertIn("function remoteControlMeasuredValue", self.script)
        helper = "function remoteControlMeasuredValue" + self.script.split(
            "function remoteControlMeasuredValue",
            1,
        )[1].split("function controlDefinitionDevices", 1)[0]
        body = """
const state = { snapshot: {} };
function snapshotDevice(devType, devName, snapshot) {
  return (snapshot.devices || []).find((dev) => dev.dev_type === devType && dev.dev_name === devName) || null;
}
const snapshot = {
  devices: [{
    dev_type: "ACBreak",
    dev_name: "盒型开关-4",
    run_stat: 1,
    status: 1,
    raw: { idx: "4", status: "1", run_stat: "1" },
  }],
  measurements: {
    scada: [
      { dev_type: "ACBreak", dev_name: "盒型开关-4", meas_type: "RUN_STAT", valid: 1, value: 1 },
      { dev_type: "ACBreak", dev_name: "盒型开关-4", meas_type: "STATUS", valid: 1, value: 0 },
    ],
    real: [],
  },
};
const measured = controlDeviceFromRow({
  dev_type: "ACBreak",
  dev_name: "盒型开关-4",
  idx: 4,
  run_stat: 1,
  status: 1,
}, snapshot);
const fallback = controlDeviceFromRow({
  dev_type: "ACBreak",
  dev_name: "盒型开关-5",
  idx: 5,
  run_stat: 1,
  status: 1,
}, { measurements: { scada: [], real: [] }, devices: [] });
process.stdout.write(JSON.stringify({
  measuredStatus: measured.status,
  measuredRunStat: measured.run_stat,
  fallbackStatus: fallback.status,
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
                "measuredStatus": 0,
                "measuredRunStat": 1,
                "fallbackStatus": 1,
            },
        )

    def test_open_remote_control_dialog_refreshes_live_state_without_resetting_choice(self):
        self.assertIn("function updateRemoteControlDialogSummary", self.script)
        self.assertIn("function refreshRemoteControlDialog", self.script)
        refresh_block = self.script.split("function refreshRemoteControlDialog", 1)[1].split(
            "function openRemoteControlDialog",
            1,
        )[0]
        self.assertIn("updateRemoteControlDialogSummary", refresh_block)
        self.assertNotIn('input.checked =', refresh_block)

        render_block = self.script.split("function renderSnapshot(snapshot)", 1)[1].split(
            "function renderReceiveMode",
            1,
        )[0]
        self.assertIn("refreshRemoteControlDialog(snapshot);", render_block)

    def test_active_command_preview_uses_the_same_live_signal_state(self):
        block = self.script.split("function activeCommandPreviewRows", 1)[1].split(
            "function renderActiveCommandPreview",
            1,
        )[0]
        self.assertIn("remoteControlMeasuredValue(devType, devName, commandType, snapshot)", block)

    def test_active_command_history_prefers_server_effective_commands(self):
        helper = "function manualCommandHoldsAcrossClockLifecycle" + self.script.split(
            "function manualCommandHoldsAcrossClockLifecycle",
            1,
        )[1].split("function addRuntimeLog", 1)[0]
        body = """
const snapshot = {
  clock: { absolute_minute: 0, run_id: 0 },
  commands: {
    history: [{
      source: "trainee-renewable-priority",
      eligible_source: true,
      manual_hold: false,
      run_id: 0,
      issued_absolute_minute: 0,
      expires_at_absolute_minute: 120,
      accepted: { run_status: 0, set_values: 1 },
    }],
    effective: [{
      source: "trainee-ui",
      eligible_source: true,
      manual_hold: true,
      accepted: { run_status: 1, set_values: 0 },
    }],
  },
};
process.stdout.write(JSON.stringify(activeCommandHistory(snapshot).map((entry) => entry.source)));
"""
        result = subprocess.run(
            ["node", "-e", f"{helper}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), ["trainee-ui"])

    def test_remote_control_table_shows_latest_command_time(self):
        self.assertIn("function remoteControlIssuedTimeInfo", self.script)
        self.assertIn("function remoteControlIssuedAt", self.script)
        self.assertIn("function withCommandSendTime", self.script)
        self.assertIn("sent_wall_time", self.script)
        self.assertIn("sent_simu_time", self.script)
        self.assertIn("normalized?.run_status", self.script)
        self.assertIn("下发本机时刻", self.script)
        self.assertIn("下发仿真时刻", self.script)
        self.assertIn("command-issued-at-cell", self.script)
        self.assertIn(".command-issued-at-cell", self.styles)


if __name__ == "__main__":
    unittest.main()
