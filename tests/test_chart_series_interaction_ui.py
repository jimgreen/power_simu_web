from __future__ import annotations

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
