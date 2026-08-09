from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChartSeriesInteractionUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulator_html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        cls.simulator_js = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        cls.trainee_html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.trainee_js = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def _axis_ticks(self, script: str):
        marker = "function curveYAxisTicks"
        if marker not in script:
            self.fail("curve y-axis tick helper is missing")
        source = marker + script.split(marker, 1)[1].split("function drawCurveYAxis", 1)[0]
        body = r"""
process.stdout.write(JSON.stringify({
  wind: curveYAxisTicks({ min: 0, max: 50, digits: 2 }, 5),
  temperature: curveYAxisTicks({ min: -60, max: 20, digits: 2 }, 5),
}));
"""
        result = subprocess.run(
            ["node"],
            input=f"{source}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _cursor_snapshot(self, script: str):
        marker = "function nearestChartPoint"
        if marker not in script:
            self.fail("nearest chart point helper is missing")
        source = marker + script.split(marker, 1)[1].split("function drawChartCursor", 1)[0]
        body = r"""
const series = [
  {
    key: "real",
    points: [
      { x: 20, y: 40, minute: 20, time: "00:20:00", value: 2 },
      { x: 30, y: 30, minute: 30, time: "00:30:00", value: 3 },
    ],
  },
  {
    key: "scada",
    points: [
      { x: 20, y: 42, minute: 20, time: "00:20:00", value: 200 },
      { x: 30, y: 32, minute: 30, time: "00:30:00", value: 300 },
    ],
  },
  {
    key: "missing",
    points: [
      { x: 19, y: 44, minute: 19, time: "00:19:00", value: 999 },
    ],
  },
];
const snapshot = chartCursorSnapshot(series, "real", 23);
process.stdout.write(JSON.stringify({
  anchor: snapshot.anchorPoint,
  samples: snapshot.samples.map(({ series: item, point }) => ({
    key: item.key,
    minute: point.minute,
    value: point.value,
  })),
}));
"""
        result = subprocess.run(
            ["node"],
            input=f"{source}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _trace_point_time_labels(
        self,
        script: str,
        helper_name: str,
        end_marker: str,
        axis_helper_name: str,
    ):
        marker = f"function {helper_name}"
        if marker not in script:
            self.fail(f"{helper_name} is missing")
        source = marker + script.split(marker, 1)[1].split(end_marker, 1)[0]
        body = f"""
function {axis_helper_name}(minute, range, index, lastIndex) {{
  return index === lastIndex ? "WRONG_WINDOW_END" : `M${{minute}}`;
}}
process.stdout.write(JSON.stringify([
  {helper_name}({{ minute: 20, time: "00:20:00", sim_time: "00:20:00" }}, {{}}),
  {helper_name}({{ minute: 20 }}, {{}}),
]));
"""
        result = subprocess.run(
            ["node"],
            input=f"{source}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_curve_pages_render_numeric_y_axis_ticks(self):
        expected_wind_labels = ["50", "40", "30", "20", "10", "0"]
        expected_temperature_labels = ["20", "4", "-12", "-28", "-44", "-60"]
        for script in (self.simulator_js, self.trainee_js):
            with self.subTest(app="simulator" if script is self.simulator_js else "trainee"):
                payload = self._axis_ticks(script)
                self.assertEqual([tick["label"] for tick in payload["wind"]], expected_wind_labels)
                self.assertEqual(
                    [tick["label"] for tick in payload["temperature"]],
                    expected_temperature_labels,
                )
                self.assertEqual([tick["ratio"] for tick in payload["wind"]], [0, 0.2, 0.4, 0.6, 0.8, 1])
                self.assertIn("drawCurveYAxis(ctx, canvas, plot, axisMeta)", script)

    def test_simulator_trace_legends_toggle_series_visibility(self):
        self.assertIn('data-chart-toggle="runtimeTrace"', self.simulator_html)
        self.assertIn('data-chart-toggle="measurementTrace"', self.simulator_html)
        self.assertIn("chartSeriesHidden", self.simulator_js)
        self.assertIn("chartSeriesSelected", self.simulator_js)
        self.assertIn("chartCursors", self.simulator_js)
        self.assertIn("function toggleChartSeriesVisibility", self.simulator_js)
        self.assertIn("function selectChartSeriesAtPointer", self.simulator_js)
        self.assertIn("function drawChartCursor", self.simulator_js)
        self.assertIn("initTraceChartInteractions", self.simulator_js)
        self.assertIn('initTraceChartInteractions("runtimeTrace"', self.simulator_js)
        self.assertIn('initTraceChartInteractions("measurementTrace"', self.simulator_js)

    def test_simulator_curve_editor_supports_legend_toggle_and_cursor(self):
        self.assertIn("hiddenCurveKeys", self.simulator_js)
        self.assertIn("curveLegendHitBoxes", self.simulator_js)
        self.assertIn("function toggleCurveSeriesVisibility", self.simulator_js)
        self.assertIn("function curveLegendKeyAtPointer", self.simulator_js)
        self.assertIn("function setCurveCursorFromEvent", self.simulator_js)
        self.assertIn("drawCurveCursor", self.simulator_js)

    def test_trainee_trace_legends_toggle_series_visibility(self):
        self.assertIn('data-chart-toggle="measurementTrace"', self.trainee_html)
        self.assertIn('data-chart-toggle="commandTrace"', self.trainee_html)
        self.assertIn("chartSeriesHidden", self.trainee_js)
        self.assertIn("chartSeriesSelected", self.trainee_js)
        self.assertIn("chartCursors", self.trainee_js)
        self.assertIn("function toggleChartSeriesVisibility", self.trainee_js)
        self.assertIn("function selectChartSeriesAtPointer", self.trainee_js)
        self.assertIn("function drawChartCursor", self.trainee_js)
        self.assertIn('initTraceChartInteractions("measurementTrace"', self.trainee_js)
        self.assertIn('initTraceChartInteractions("commandTrace"', self.trainee_js)

    def test_trainee_curve_display_supports_legend_toggle_and_cursor(self):
        self.assertIn("hiddenCurveDisplayKeys", self.trainee_js)
        self.assertIn("curveDisplayLegendHitBoxes", self.trainee_js)
        self.assertIn("function toggleCurveDisplaySeriesVisibility", self.trainee_js)
        self.assertIn("function curveDisplayLegendKeyAtPointer", self.trainee_js)
        self.assertIn("function setCurveDisplayCursorFromEvent", self.trainee_js)
        self.assertIn("drawCurveDisplayCursor", self.trainee_js)

    def test_trace_cursor_snaps_time_and_values_to_one_sample_in_both_consoles(self):
        for app, script in (
            ("simulator", self.simulator_js),
            ("trainee", self.trainee_js),
        ):
            with self.subTest(app=app):
                snapshot = self._cursor_snapshot(script)
                self.assertEqual(snapshot["anchor"]["minute"], 20)
                self.assertEqual(snapshot["anchor"]["x"], 20)
                self.assertEqual(
                    snapshot["samples"],
                    [
                        {"key": "real", "minute": 20, "value": 2},
                        {"key": "scada", "minute": 20, "value": 200},
                    ],
                )

    def test_measurement_trace_cursor_uses_sample_time_not_window_end(self):
        simulator_labels = self._trace_point_time_labels(
            self.simulator_js,
            "runtimeTracePointTimeLabel",
            "function runtimeTraceAxisTicks",
            "runtimeAxisTickLabel",
        )
        trainee_labels = self._trace_point_time_labels(
            self.trainee_js,
            "measurementTracePointTimeLabel",
            "function measurementTraceAxisTicks",
            "measurementTraceTimeLabel",
        )
        self.assertEqual(simulator_labels, ["00:20:00", "M20"])
        self.assertEqual(trainee_labels, ["00:20:00", "M20"])


if __name__ == "__main__":
    unittest.main()
