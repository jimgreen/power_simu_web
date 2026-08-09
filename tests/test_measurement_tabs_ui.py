from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MeasurementTabsUiTest(unittest.TestCase):
    def test_realtime_measurements_are_split_into_telemetry_and_signal_tabs(self):
        surfaces = (
            (
                ROOT / "simu/web/simulator/index.html",
                ROOT / "simu/web/simulator/app.js",
                "measurementCompareTable",
                "data-measurement-compare-tab",
            ),
            (
                ROOT / "simu/web/trainee/index.html",
                ROOT / "simu/web/trainee/app.js",
                "measurementTable",
                "data-measurement-tab",
            ),
        )
        for html_path, script_path, table_id, tab_attr in surfaces:
            with self.subTest(surface=html_path.parent.name):
                html = html_path.read_text(encoding="utf-8")
                script = script_path.read_text(encoding="utf-8")

                self.assertIn(f'id="{table_id}"', html)
                self.assertIn("量测值与真值", html)
                self.assertIn('role="tablist" aria-label="量测类型"', script)
                self.assertIn(tab_attr, script)
                self.assertIn("遥测", script)
                self.assertIn("遥信", script)
                self.assertIn("function measurementTelemetryRows", script)
                self.assertIn("function measurementSignalRows", script)
                self.assertIn("function setMeasurement", script)
                self.assertIn("isSignalMeasurement(row)", script)
                self.assertIn('RUN_STAT', script)
                self.assertIn('STATUS', script)

    def test_signal_values_use_integer_display_without_changing_telemetry_precision(self):
        surfaces = (
            (ROOT / "simu/web/simulator/app.js", "formatMeasurementValue", "0.12500"),
            (ROOT / "simu/web/trainee/app.js", "formatNumber", "0.125"),
        )
        for script_path, analog_formatter, expected_analog in surfaces:
            with self.subTest(surface=script_path.parent.name):
                script = script_path.read_text(encoding="utf-8")
                function_names = (
                    analog_formatter,
                    "isSignalMeasurement",
                    "formatMeasurementDisplayValue",
                )
                sources = []
                for function_name in function_names:
                    match = re.search(
                        rf"function {function_name}\([^)]*\) \{{.*?^\}}",
                        script,
                        flags=re.MULTILINE | re.DOTALL,
                    )
                    self.assertIsNotNone(match, function_name)
                    sources.append(match.group(0))

                node_script = f"""
const SIGNAL_MEASUREMENT_LABELS = Object.freeze({{
  RUN_STAT: Object.freeze({{ label: "运行状态" }}),
  STATUS: Object.freeze({{ label: "开关状态" }}),
}});
{chr(10).join(sources)}
console.log(JSON.stringify({{
  signalOne: formatMeasurementDisplayValue(1.0, {{ meas_type: "RUN_STAT" }}),
  signalZero: formatMeasurementDisplayValue(0.0, {{ meas_type: "STATUS" }}),
  signalNegativeDeviation: formatMeasurementDisplayValue(-1.0, {{ meas_type: "STATUS" }}),
  signalRounded: formatMeasurementDisplayValue(0.76, {{ meas_type: "STATUS" }}),
  telemetry: formatMeasurementDisplayValue(0.125, {{ meas_type: "P_GEN" }}),
  customTelemetry: formatMeasurementDisplayValue(0.125, {{ meas_type: "P_GEN" }}, (value) => value.toFixed(2)),
  invalid: formatMeasurementDisplayValue(null, {{ meas_type: "STATUS" }}),
}}));
"""
                completed = subprocess.run(
                    ["node", "-e", node_script],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                result = json.loads(completed.stdout)

                self.assertEqual(result["signalOne"], "1")
                self.assertEqual(result["signalZero"], "0")
                self.assertEqual(result["signalNegativeDeviation"], "-1")
                self.assertEqual(result["signalRounded"], "1")
                self.assertEqual(result["telemetry"], expected_analog)
                self.assertEqual(result["customTelemetry"], "0.13")
                self.assertEqual(result["invalid"], "--")

    def test_both_measurement_tables_and_svg_tooltips_use_type_aware_value_formatting(self):
        for role in ("simulator", "trainee"):
            with self.subTest(surface=role):
                script = (ROOT / f"simu/web/{role}/app.js").read_text(encoding="utf-8")

                self.assertIn("<th>真值</th>", script)
                self.assertIn("<th>量测值</th>", script)
                self.assertIn("<th>偏差</th>", script)
                self.assertIn('data-measurement-live-field="real"', script)
                self.assertIn('data-measurement-live-field="scada"', script)
                self.assertIn('data-measurement-live-field="diff"', script)
                self.assertIn("formatMeasurementDisplayValue(row.real_value, row)", script)
                self.assertIn("formatMeasurementDisplayValue(row.scada_value, row)", script)
                self.assertIn("formatMeasurementDisplayValue(row.diff, row)", script)
                self.assertIn("formatMeasurementDisplayValue(scadaValue, pair.row, diagramNumberText)", script)
                self.assertIn("formatMeasurementDisplayValue(realValue, pair.row, diagramNumberText)", script)
                self.assertIn("formatMeasurementDisplayValue(deviation, pair.row, diagramNumberText)", script)


if __name__ == "__main__":
    unittest.main()
