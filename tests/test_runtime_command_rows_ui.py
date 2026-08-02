from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeCommandRowsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

    def test_runtime_commands_are_split_into_remote_control_and_adjustment_rows(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function runtimeRemoteControlRows", app_js)
        self.assertIn("function runtimeRemoteAdjustmentRows", app_js)
        self.assertIn("遥控指令", app_js)
        self.assertIn("遥调指令", app_js)
        self.assertIn("指令项", app_js)
        self.assertIn("接收本机时刻", app_js)
        self.assertIn("接收仿真时刻", app_js)
        self.assertIn("refresh_time", app_js)
        self.assertIn("receive_time", app_js)
        self.assertIn("function runtimeCommandRefreshInfo", app_js)
        self.assertIn("function runtimeCommandRefreshTime", app_js)
        self.assertIn("received_wall_time", app_js)
        self.assertIn("received_absolute_minute", app_js)
        self.assertIn("issued_absolute_minute", app_js)
        self.assertIn("expires_at_absolute_minute", app_js)
        self.assertIn("function manualCommandHoldsAcrossClockLifecycle", app_js)
        self.assertIn("renderRuntimeCommandTable", app_js)

    def test_manual_runtime_commands_are_not_filtered_out_by_run_id(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        active_block = app_js.split("function activeCommandHistory", 1)[1].split("function runtimeCommandRefreshInfo", 1)[0]

        self.assertIn("if (entry.cancelled) return false;", active_block)
        self.assertIn("const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);", active_block)
        self.assertIn("if (!manualHold) {", active_block)
        self.assertIn("entryRunId !== currentRunId", active_block)
        self.assertIn("if (manualHold) return acceptedCount > 0;", active_block)
        self.assertIn("currentMinute < expires && issued <= currentMinute", active_block)

    def test_runtime_command_tables_keep_each_command_on_one_line(self):
        self.assertIn(".runtime-command-table th,\n.runtime-command-table td", self.styles)
        self.assertIn("white-space: nowrap;", self.styles)
        self.assertIn(".command-set-type {\n  display: inline;", self.styles)
        self.assertIn(".command-set-type:not(:empty)::before", self.styles)
        self.assertNotIn(".command-set-type {\n  display: block;", self.styles)

    def test_runtime_command_table_aligns_headers_and_values_right(self):
        selector = ".runtime-command-table th,\n.runtime-command-table td {"
        table_cell_block = self.styles.split(selector, 1)[1].split("}", 1)[0]

        self.assertIn("text-align: right;", table_cell_block)

    def test_runtime_command_table_values_hide_units_only_in_the_table(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function runtimeCommandTableValueText", app_js)
        value_helper = app_js.split("function runtimeCommandTableValueText", 1)[1].split(
            "function runtimeCommandLiveCellHtml",
            1,
        )[0]
        live_helper = app_js.split("function runtimeCommandLiveCellHtml", 1)[1].split(
            "function updateRuntimeCommandTableLiveCells",
            1,
        )[0]
        row_renderer = app_js.split("function renderRuntimeCommandRows", 1)[1].split(
            "function renderRuntimeCommandTable",
            1,
        )[0]

        self.assertIn('const unit = String(row?.unit || "").trim();', value_helper)
        self.assertIn("const suffix = ` ${unit}`;", value_helper)
        self.assertIn("return text.endsWith(suffix) ? text.slice(0, -suffix.length) : text;", value_helper)
        for field in ("control", "real", "scada"):
            self.assertIn(f'runtimeCommandTableValueText(row, "{field}")', live_helper)
            self.assertIn(f'runtimeCommandLiveCellHtml(row, "{field}")', row_renderer)
        self.assertIn("command_text: formatRuntimeSignal(meta.value, meta.unit)", app_js)

    def test_runtime_command_rows_select_trace_on_click_or_double_click(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("selectedRuntimeCommandKey", app_js)
        self.assertIn("function runtimeCommandTraceKey", app_js)
        self.assertIn("function selectRuntimeCommandTrace", app_js)
        self.assertIn("data-runtime-command-row-key", app_js)
        self.assertIn("data-runtime-command-row-label", app_js)
        self.assertIn('event.target.closest("[data-runtime-command-row-key]")', app_js)
        self.assertIn('document.addEventListener("dblclick"', app_js)
        self.assertIn("selectedRuntimeCommandTraceSeries", app_js)
        self.assertIn("point.commands", app_js)

    def test_remote_control_rows_use_signal_measurements_for_real_and_scada_values(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function runtimeSignalMeasurementPair", app_js)
        helper_block = app_js.split("function runtimeSignalMeasurementPair", 1)[1].split(
            "function runtimeDeviceTraceSignal",
            1,
        )[0]
        remote_control_block = app_js.split("function runtimeRemoteControlRows", 1)[1].split(
            "function runtimeRemoteAdjustmentRows",
            1,
        )[0]

        self.assertIn("function formatRuntimeRemoteSignal", helper_block)
        self.assertIn('if (numeric === null) return "--";', helper_block)
        self.assertIn('commandType === "status"', helper_block)
        self.assertIn('runtimeSignalMeasurementPair(dev, "RUN_STAT"', remote_control_block)
        self.assertIn('runtimeSignalMeasurementPair(dev, "STATUS"', remote_control_block)
        self.assertIn('real_text: formatRuntimeRemoteSignal(runPair.real ?? value, "run_stat")', remote_control_block)
        self.assertIn('scada_text: formatRuntimeRemoteSignal(runPair.scada, "run_stat")', remote_control_block)
        self.assertIn('real_text: formatRuntimeRemoteSignal(statusPair.real ?? value, "status")', remote_control_block)
        self.assertIn('scada_text: formatRuntimeRemoteSignal(statusPair.scada, "status")', remote_control_block)
        self.assertNotIn('scada_text: "--"', remote_control_block)

    def test_remote_adjustment_rows_match_the_exact_converter_side(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function runtimeMeasurementTypeCandidates", app_js)
        helper = "function runtimeMeasurementTypeCandidates" + app_js.split(
            "function runtimeMeasurementTypeCandidates",
            1,
        )[1].split("function runtimeSignalMeasurementPair", 1)[0]
        body = r"""
const state = { snapshot: {} };
function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function measurementCompareRows() {
  return [
    { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V", real_value: 111, scada_value: 112 },
    { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V_AC", real_value: 380, scada_value: 381 },
    { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "V_DC", real_value: 750, scada_value: 751 },
    { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P", real_value: 123, scada_value: 124 },
    { dev_type: "DCACConverter", dev_name: "ACDC变流器-1", meas_type: "P_AC", real_value: -42.5, scada_value: -42 },
  ];
}
const dev = { dev_type: "DCACConverter", dev_name: "ACDC变流器-1" };
process.stdout.write(JSON.stringify({
  acVoltage: runtimeMeasurementPair(dev, { key: "v_ac_set" }),
  dcVoltage: runtimeMeasurementPair(dev, { key: "v_dc_set" }),
  acPower: runtimeMeasurementPair(dev, { key: "p_ac_set" }),
  generatorCandidates: runtimeMeasurementTypeCandidates({ dev_type: "ACGenerator" }, "p_set"),
}));
"""
        result = subprocess.run(
            ["node", "-e", f"{helper}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["acVoltage"]["meas_type"], "V_AC")
        self.assertEqual(payload["dcVoltage"]["meas_type"], "V_DC")
        self.assertEqual(payload["acPower"]["real"], -42.5)
        self.assertEqual(payload["generatorCandidates"][0], "P_GEN")


if __name__ == "__main__":
    unittest.main()
