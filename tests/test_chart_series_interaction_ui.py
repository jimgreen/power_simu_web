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


if __name__ == "__main__":
    unittest.main()
