import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRemoteAdjustmentUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_each_remote_adjustment_is_rendered_as_one_row(self):
        self.assertIn("function remoteAdjustmentRows", self.script)
        self.assertIn("遥调名称", self.script)
        self.assertIn("量测值", self.script)
        self.assertIn("控制值", self.script)
        self.assertIn("下发本机时刻", self.script)
        self.assertIn("下发仿真时刻", self.script)
        self.assertIn("function remoteAdjustmentIssuedTimeInfo", self.script)

    def test_remote_adjustment_rows_keep_name_and_type_on_one_line(self):
        self.assertIn("class=\"remote-adjustment-name-cell\"", self.script)
        self.assertIn(".remote-adjustment-name-cell {\n  display: flex;", self.styles)
        self.assertIn("align-items: center;", self.styles)
        self.assertIn("white-space: nowrap;", self.styles)
        first_cell_rule = self.styles.split(".remote-adjustment-table td:first-child {", 1)[1].split("}", 1)[0]
        self.assertNotIn("display: flex", first_cell_rule)
        self.assertNotIn("display: grid", first_cell_rule)

    def test_remote_adjustment_table_uses_fixed_columns_for_same_row_alignment(self):
        self.assertIn("<colgroup>", self.script)
        self.assertIn('class="remote-adjustment-name-col"', self.script)
        self.assertIn('class="remote-adjustment-value-col"', self.script)
        self.assertIn('class="remote-adjustment-origin-col"', self.script)
        self.assertIn('class="remote-adjustment-time-col"', self.script)
        self.assertIn('class="remote-adjustment-action-col"', self.script)
        self.assertIn(".remote-adjustment-table {\n  table-layout: fixed;", self.styles)
        self.assertIn(".remote-adjustment-name-col { width: 28%; }", self.styles)
        self.assertIn(".remote-adjustment-value-col { width: 9%; }", self.styles)
        self.assertIn(".remote-adjustment-origin-col { width: 9%; }", self.styles)
        self.assertIn(".remote-adjustment-time-col { width: 12%; }", self.styles)
        self.assertIn(".remote-adjustment-action-col { width: 8%; }", self.styles)
        self.assertIn(".remote-adjustment-table th,\n.remote-adjustment-table td {\n  vertical-align: middle;", self.styles)
        self.assertIn(".remote-adjustment-table th:nth-child(2),\n.remote-adjustment-table th:nth-child(3),", self.styles)

    def test_remote_adjustment_dialog_is_available(self):
        self.assertIn('id="remoteAdjustmentDialog"', self.html)
        self.assertIn('id="remoteAdjustmentValue"', self.html)
        self.assertIn('id="remoteAdjustmentConfirm"', self.html)

    def test_converter_terminal_power_points_use_acp_and_dcp_labels(self):
        self.assertIn('p_ac_set: "ACP有功设定"', self.script)
        self.assertIn('p_dc_set: "DCP有功设定"', self.script)

    def test_command_split_keeps_remote_adjustment_rows_clickable_in_compact_viewport(self):
        command_split = self.html.split('data-vertical-split="trainee-commands"', 1)[1].split(">", 1)[0]
        self.assertIn('data-vertical-split-min-top="210"', command_split)
        self.assertIn('data-vertical-split-min-bottom="240"', command_split)

    def test_double_click_sends_one_adjustment_command(self):
        self.assertIn("data-remote-adjustment-key", self.script)
        self.assertIn("openRemoteAdjustmentDialog", self.script)
        self.assertIn("sendRemoteAdjustmentCommand", self.script)
        self.assertIn("set_values: [command]", self.script)

    def test_blocked_remote_adjustment_is_reported_as_queued(self):
        send_block = self.script.split("async function sendRemoteAdjustmentCommand()", 1)[1].split(
            "function handleTreeClick",
            1,
        )[0]
        self.assertIn("commandSubmissionQueueState(result, \"set_values\")", send_block)
        self.assertIn("下发完成", send_block)
        self.assertIn("接收完成，模拟台排队", send_block)
        self.assertIn("接收完成，遥调生效", send_block)
        self.assertIn("模拟台已接管", self.script)
        self.assertIn("学员台不保存等待任务", self.script)
        self.assertNotIn("已记录，排队等待", send_block)
        self.assertLess(
            send_block.index("pending.set_values.delete(row.key)"),
            send_block.index("await refresh();"),
        )

    def test_successful_remote_adjustment_closes_only_top_operation_dialog(self):
        success_block = self.script.split("async function sendRemoteAdjustmentCommand()", 1)[1].split(
            "} catch (error)",
            1,
        )[0]
        self.assertIn("closeRemoteAdjustmentDialog();", success_block)
        self.assertNotIn("closeDiagramDeviceCommandDialog();", success_block)
        self.assertNotIn('$("remoteAdjustmentConfirm").textContent = "继续下发";', success_block)

    def test_failed_remote_adjustment_keeps_dialog_open_for_retry(self):
        failure_block = self.script.split("async function sendRemoteAdjustmentCommand()", 1)[1].split(
            "} catch (error)",
            1,
        )[1].split("function handleTreeClick", 1)[0]
        self.assertNotIn("closeRemoteAdjustmentDialog();", failure_block)
        self.assertIn('$("remoteAdjustmentConfirm").textContent = "重新下发";', failure_block)

    def test_manual_commands_are_marked_hold_until_cancelled_without_expiry(self):
        self.assertIn("function manualCommandHoldPayload", self.script)
        remote_control_block = self.script.split("async function sendRemoteControlCommand()", 1)[1].split("function findRemoteAdjustmentByKey", 1)[0]
        remote_adjustment_block = self.script.split("async function sendRemoteAdjustmentCommand()", 1)[1].split("function handleTreeClick", 1)[0]

        self.assertIn("...manualCommandHoldPayload()", remote_control_block)
        self.assertIn("...manualCommandHoldPayload()", remote_adjustment_block)
        self.assertIn("withCommandSendTime({", remote_control_block)
        self.assertIn("withCommandSendTime({", remote_adjustment_block)
        self.assertNotIn("expires_at_absolute_minute", remote_control_block)
        self.assertNotIn("expires_at_absolute_minute", remote_adjustment_block)
        self.assertNotIn("valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES", remote_control_block)
        self.assertNotIn("valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES", remote_adjustment_block)
        self.assertNotIn("calculateRenewableControlPlan", self.script)

        backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        self.assertIn('"valid_for_minutes": cycle_settings.command_valid_minutes', backend)
        self.assertNotIn("manual_hold", backend)

    def test_displayed_command_times_use_shared_active_command_filter(self):
        self.assertIn("function activeCommandHistory", self.script)
        self.assertIn("function manualCommandHoldsAcrossClockLifecycle", self.script)
        remote_control_time_block = self.script.split("function remoteControlIssuedTimeInfo", 1)[1].split("function remoteControlIssuedAt", 1)[0]
        remote_adjustment_time_block = self.script.split("function remoteAdjustmentIssuedTimeInfo", 1)[1].split("function remoteAdjustmentIssuedAt", 1)[0]
        self.assertIn("activeCommandEntryForControl", remote_control_time_block)
        self.assertIn("activeCommandEntryForControl", remote_adjustment_time_block)

    def test_manual_commands_are_not_filtered_out_by_simulator_run_id(self):
        active_block = self.script.split("function activeCommandHistory", 1)[1].split("function addRuntimeLog", 1)[0]

        self.assertIn("if (entry.cancelled) return false;", active_block)
        self.assertIn("const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);", active_block)
        self.assertIn("if (!manualHold) {", active_block)
        self.assertIn("entryRunId !== currentRunId", active_block)
        self.assertIn("if (manualHold) return acceptedCount > 0;", active_block)
        self.assertIn("currentMinute < expires && issued <= currentMinute", active_block)

    def test_remote_adjustment_measurement_uses_exact_side_and_valid_scada_only(self):
        self.assertIn("function remoteAdjustmentMeasurementTypeCandidates", self.script)
        helper = "function remoteAdjustmentMeasurementTypeCandidates" + self.script.split(
            "function remoteAdjustmentMeasurementTypeCandidates",
            1,
        )[1].split("function remoteAdjustmentIssuedTimeInfo", 1)[0]
        body = r"""
const state = { snapshot: {} };
function deviceType(dev) { return dev.dev_type || ""; }
function deviceName(dev) { return dev.dev_name || ""; }
const dev = { dev_type: "DCACConverter", dev_name: "ACDC变流器-1" };
const acdcDev = { dev_type: "ACDCConverter", dev_name: "ACDC变流器-2" };
const snapshot = {
  measurements: {
    scada: [
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V_AC", valid: 1, value: 380 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V_DC", valid: 0, value: 999 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P_AC", valid: 0, value: 88 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-2", meas_type: "P_DC", valid: 1, value: 9.0 },
    ],
    real: [
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V_DC", valid: 1, value: 750 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P_AC", valid: 1, value: -42.5 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P_DC", valid: 1, value: 42.5 },
      { dev_type: "ACDCConverter", dev_name: "ACDC变流器-2", meas_type: "P_DC", valid: 1, value: 9.0 },
    ],
  },
};
process.stdout.write(JSON.stringify({
  acVoltage: remoteAdjustmentMeasurement(dev, "v_ac_set", snapshot),
  dcVoltage: remoteAdjustmentMeasurement(dev, "v_dc_set", snapshot),
  acPower: remoteAdjustmentMeasurement(dev, "p_ac_set", snapshot),
  dcPower: remoteAdjustmentMeasurement(dev, "p_dc_set", snapshot),
  acdcDcPower: remoteAdjustmentMeasurement(acdcDev, "p_dc_set", snapshot),
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
                "acVoltage": 380,
                "dcVoltage": None,
                "acPower": None,
                "dcPower": None,
                "acdcDcPower": 9.0,
            },
        )

    def test_current_set_value_reads_exact_dc_terminal_field_from_model(self):
        value_helpers = "function effectiveRemoteAdjustmentValue" + self.script.split(
            "function effectiveRemoteAdjustmentValue",
            1,
        )[1].split("function remoteAdjustmentTypeLabel", 1)[0]
        body = r"""
const state = { snapshot: {} };
const pending = { set_values: new Map() };
function deviceType(dev) { return dev.dev_type || ""; }
function deviceName(dev) { return dev.dev_name || ""; }
function deviceKey(dev) { return `${deviceType(dev)}|${deviceName(dev)}`; }
function activeCommandEntryForControl() { return null; }
const dev = {
  dev_type: "DCACConverter",
  dev_name: "grid-link",
  set_values: {},
  mode: "PQ",
  raw: {
    ac_control_type: "PQ",
    dc_control_type: "P",
    p_set: 99,
    p_ac_set: -12.5,
    p_dc_set: 12.5,
  },
};
const explicitDcDisabled = {
  dev_type: "DCACConverter",
  dev_name: "ac-grid-link",
  set_values: {},
  mode: "DCP",
  raw: {
    ac_control_type: "PQ",
    dc_control_type: "NONE",
    p_ac_set: -8,
    p_dc_set: 8,
  },
};
const doubleNone = {
  dev_type: "DCACConverter",
  dev_name: "fallback-grid-link",
  set_values: {},
  mode: "P",
  raw: {
    ac_control_type: "NONE",
    dc_control_type: "NONE",
    p_ac_set: -6,
    p_dc_set: 6,
  },
};
const opaqueConverter = {
  dev_type: "opaque-equipment-class",
  dev_name: "opaque-grid-link",
  set_values: {},
  mode: "P",
  raw: {
    ac_node: 1,
    dc_node: 2,
    ac_control_type: "PQ",
    dc_control_type: "P",
    p_ac_set: -4,
    p_dc_set: 4,
  },
};
process.stdout.write(JSON.stringify({
  pAc: currentSetValue(dev, "p_ac_set", state.snapshot),
  pDc: currentSetValue(dev, "p_dc_set", state.snapshot),
  generic: currentSetValue(dev, "p_set", state.snapshot),
  explicitDcDisabled: currentSetValue(explicitDcDisabled, "p_set", state.snapshot),
  doubleNone: currentSetValue(doubleNone, "p_set", state.snapshot),
  opaque: currentSetValue(opaqueConverter, "p_set", state.snapshot),
}));
"""
        result = subprocess.run(
            ["node", "-e", f"{value_helpers}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "pAc": -12.5,
                "pDc": 12.5,
                "generic": 12.5,
                "explicitDcDisabled": -8,
                "doubleNone": 6,
                "opaque": 4,
            },
        )

    def test_remote_adjustment_measurement_prefers_exact_candidate_over_generic_quantity(self):
        helper = "function remoteAdjustmentMeasurementTypeCandidates" + self.script.split(
            "function remoteAdjustmentMeasurementTypeCandidates",
            1,
        )[1].split("function remoteAdjustmentIssuedTimeInfo", 1)[0]
        body = r"""
const state = { snapshot: {} };
function deviceType(dev) { return dev.dev_type || ""; }
function deviceName(dev) { return dev.dev_name || ""; }
const dev = { dev_type: "DCACConverter", dev_name: "ACDC变流器-1" };
const snapshot = {
  measurements: {
    scada: [
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V", valid: 1, value: 111 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V_DC", valid: 1, value: 750 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P", valid: 1, value: 123 },
      { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P_AC", valid: 1, value: -42.5 },
    ],
    real: [],
  },
};
process.stdout.write(JSON.stringify({
  dcVoltage: remoteAdjustmentMeasurement(dev, "v_dc_set", snapshot),
  acPower: remoteAdjustmentMeasurement(dev, "p_ac_set", snapshot),
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
            {"dcVoltage": 750, "acPower": -42.5},
        )

    def test_generic_remote_adjustment_measurement_matches_device_semantics(self):
        self.assertIn("function remoteAdjustmentMeasurementTypeCandidates", self.script)
        helper = "function remoteAdjustmentMeasurementTypeCandidates" + self.script.split(
            "function remoteAdjustmentMeasurementTypeCandidates",
            1,
        )[1].split("function remoteAdjustmentIssuedTimeInfo", 1)[0]
        body = r"""
const state = { snapshot: {} };
function deviceType(dev) { return dev.dev_type || ""; }
function deviceName(dev) { return dev.dev_name || ""; }
const snapshot = {
  measurements: {
    scada: [
      { dev_type: "ACGenerator", dev_name: "柴油发电机-1", meas_type: "P_GEN", valid: 1, value: -16.25 },
      { dev_type: "ACLoad", dev_name: "交流负荷-1", meas_type: "P_LOAD", valid: 1, value: 21.5 },
      { dev_type: "DCDCConverter", dev_name: "储能变流器-1", meas_type: "P_TO", valid: 1, value: 8 },
      { dev_type: "DCDCConverter", dev_name: "储能变流器-1", meas_type: "P_FROM", valid: 1, value: -7.5 },
    ],
    real: [],
  },
};
process.stdout.write(JSON.stringify({
  generator: remoteAdjustmentMeasurement(
    { dev_type: "ACGenerator", dev_name: "柴油发电机-1" },
    "p_set",
    snapshot,
  ),
  load: remoteAdjustmentMeasurement(
    { dev_type: "ACLoad", dev_name: "交流负荷-1" },
    "p_set",
    snapshot,
  ),
  dcdc: remoteAdjustmentMeasurement(
    { dev_type: "DCDCConverter", dev_name: "储能变流器-1" },
    "p_set",
    snapshot,
  ),
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
            {"generator": -16.25, "load": 21.5, "dcdc": -7.5},
        )

    def test_open_remote_adjustment_dialog_refreshes_summary_without_overwriting_input(self):
        self.assertIn("function updateRemoteAdjustmentDialogSummary", self.script)
        self.assertIn("function refreshRemoteAdjustmentDialog", self.script)
        helper = "function updateRemoteAdjustmentDialogSummary" + self.script.split(
            "function updateRemoteAdjustmentDialogSummary",
            1,
        )[1].split("function openRemoteAdjustmentDialog", 1)[0]
        body = r"""
const elements = {
  remoteAdjustmentDialog: { open: true },
  remoteAdjustmentName: { textContent: "旧名称" },
  remoteAdjustmentDevice: { textContent: "旧设备" },
  remoteAdjustmentMeasurement: { textContent: "1" },
  remoteAdjustmentCurrent: { textContent: "2" },
  remoteAdjustmentIssuedAt: { textContent: "旧本机时刻" },
  remoteAdjustmentIssuedSimAt: { textContent: "旧仿真时刻" },
  remoteAdjustmentValue: { value: "123.456" },
};
const state = {
  snapshot: {},
  remoteAdjustment: { key: "DCACConverter|ACDC变流器-1|p_ac_set" },
};
function $(id) { return elements[id] || null; }
function deviceType(dev) { return dev.dev_type || ""; }
function deviceName(dev) { return dev.dev_name || ""; }
function formatRemoteAdjustmentValue(value) { return value == null ? "--" : String(value); }
function findRemoteAdjustmentByKey(_key, _snapshot) {
  return {
    key: "DCACConverter|ACDC变流器-1|p_ac_set",
    name: "ACDC变流器-1.p_ac_set",
    dev: { dev_type: "DCACConverter", dev_name: "ACDC变流器-1" },
    measurement: -12.5,
    controlValue: 18,
    issuedAt: "12:00:00",
    issuedTime: { wall_time: "12:00:01", simu_time: "08:30:00" },
  };
}
function closeRemoteAdjustmentDialog() { throw new Error("dialog should remain open"); }
refreshRemoteAdjustmentDialog({ clock: { step_count: 5 } });
process.stdout.write(JSON.stringify({
  name: elements.remoteAdjustmentName.textContent,
  device: elements.remoteAdjustmentDevice.textContent,
  measurement: elements.remoteAdjustmentMeasurement.textContent,
  current: elements.remoteAdjustmentCurrent.textContent,
  wallTime: elements.remoteAdjustmentIssuedAt.textContent,
  simuTime: elements.remoteAdjustmentIssuedSimAt.textContent,
  input: elements.remoteAdjustmentValue.value,
  stateMeasurement: state.remoteAdjustment.measurement,
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
                "name": "ACDC变流器-1.p_ac_set",
                "device": "DCACConverter / ACDC变流器-1",
                "measurement": "-12.5",
                "current": "18",
                "wallTime": "12:00:01",
                "simuTime": "08:30:00",
                "input": "123.456",
                "stateMeasurement": -12.5,
            },
        )

    def test_render_snapshot_refreshes_open_remote_adjustment_dialog(self):
        render_block = self.script.split("function renderSnapshot(snapshot)", 1)[1].split(
            "function renderReceiveMode",
            1,
        )[0]
        self.assertIn("refreshRemoteAdjustmentDialog(snapshot);", render_block)

    def _evaluate_current_set_value(self, snapshot):
        lifecycle_helpers = "function manualCommandHoldsAcrossClockLifecycle" + self.script.split(
            "function manualCommandHoldsAcrossClockLifecycle",
            1,
        )[1].split("function addRuntimeLog", 1)[0]
        command_helpers = "function commandEntryMatchesControl" + self.script.split(
            "function commandEntryMatchesControl",
            1,
        )[1].split("function emptyIssuedCommandInfo", 1)[0]
        value_helpers = "function effectiveRemoteAdjustmentValue" + self.script.split(
            "function effectiveRemoteAdjustmentValue",
            1,
        )[1].split("function remoteAdjustmentTypeLabel", 1)[0]
        body = f"""
const snapshot = {json.dumps(snapshot, ensure_ascii=False)};
const state = {{ snapshot }};
const pending = {{ set_values: new Map() }};
function deviceType(dev) {{ return dev.dev_type || ""; }}
function deviceName(dev) {{ return dev.dev_name || ""; }}
function deviceKey(dev) {{ return `${{deviceType(dev)}}|${{deviceName(dev)}}`; }}
const dev = {{
  dev_type: "ACGenerator",
  dev_name: "交流电化学储能-23",
  set_values: {{ p_set: 10 }},
  raw: {{ p_set: 10 }},
}};
process.stdout.write(JSON.stringify({{ value: currentSetValue(dev, "p_set", snapshot) }}));
"""
        result = subprocess.run(
            ["node", "-e", f"{lifecycle_helpers}\n{command_helpers}\n{value_helpers}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)["value"]

    @staticmethod
    def _set_value_command(value, *, origin="manual", cancelled=False):
        manual = origin == "manual"
        return {
            "eligible_source": True,
            "cancelled": cancelled,
            "manual_hold": manual,
            "command_origin": origin,
            "run_id": 1,
            "issued_absolute_minute": 5,
            "expires_at_absolute_minute": None if manual else 120,
            "accepted": {"run_status": 0, "set_values": 1},
            "normalized": {
                "run_status": [],
                "set_values": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "交流电化学储能-23",
                        "set_type": "p_set",
                        "set_value": value,
                    }
                ],
            },
            "payload": {"source": "trainee-ui" if manual else "trainee-automatic-control"},
        }

    def test_current_control_value_prefers_active_manual_command_over_static_definition(self):
        manual = self._set_value_command(60)
        snapshot = {
            "clock": {"absolute_minute": 10, "run_id": 1},
            "commands": {"history": [manual], "effective": [manual]},
        }

        self.assertEqual(self._evaluate_current_set_value(snapshot), 60)

    def test_current_control_value_prefers_effective_automatic_command_over_manual_command(self):
        manual = self._set_value_command(60)
        automatic = self._set_value_command(35, origin="automatic")
        snapshot = {
            "clock": {"absolute_minute": 10, "run_id": 1},
            "commands": {
                "history": [manual, automatic],
                "effective": [automatic],
            },
        }

        self.assertEqual(self._evaluate_current_set_value(snapshot), 35)

    def test_current_control_value_falls_back_to_static_definition_after_command_cancel(self):
        cancelled = self._set_value_command(60, cancelled=True)
        snapshot = {
            "clock": {"absolute_minute": 10, "run_id": 1},
            "commands": {"history": [cancelled], "effective": []},
        }

        self.assertEqual(self._evaluate_current_set_value(snapshot), 10)


if __name__ == "__main__":
    unittest.main()
