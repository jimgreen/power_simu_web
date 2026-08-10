from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraceWindowOptionsUiTest(unittest.TestCase):
    def test_simulator_and_trainee_offer_week_and_month_trace_windows(self):
        simulator_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for html in (simulator_html, trainee_html):
            self.assertIn('<option value="1440">1日</option>', html)
            self.assertNotIn('<option value="1440">24小时</option>', html)
            self.assertIn('<option value="10080">1周</option>', html)
            self.assertIn('<option value="43200">1月</option>', html)
            self.assertIn('<option value="525600">1年</option>', html)
        self.assertIn("第${day + 1}天", simulator_js)
        self.assertIn("formatYearTraceTickLabel", simulator_js)
        self.assertNotIn("function traceHistoryLimit", simulator_js)
        self.assertNotIn('activeRuntimeSetting("trace_history_limit")', simulator_js)

    def test_trainee_measurement_trace_uses_manual_window_range_for_x_axis(self):
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function measurementTraceWindowRange()", trainee_js)
        self.assertIn(
            'alignedTraceWindowRange(\n    history,\n    windowMinutes,\n    fallbackMinute,\n    chartPeriodOffset("measurementTrace"),\n    curveDisplayModeDurationMinutes(),\n  )',
            trainee_js,
        )
        self.assertIn("traceWindowPointsWithBoundaryAnchors(points, range)", trainee_js)
        self.assertIn("((point.minute - range.startMinute) / range.windowMinutes) * plotWidth", trainee_js)
        self.assertNotIn("const minMinute = points[0].minute", trainee_js)
        self.assertNotIn("maxMinute - minMinute", trainee_js)

    def test_measurement_traces_reset_when_service_restart_reuses_the_same_run_id(self):
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        for script in (simulator_js, trainee_js):
            self.assertIn("traceStepCount: null", script)
            self.assertIn("stepCount < state.traceStepCount", script)
            self.assertIn("state.traceStepCount = stepCount", script)

    def test_measurement_traces_do_not_connect_duplicate_or_rewound_clock_points(self):
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        simulator_chart = simulator_js.split("function drawMeasurementTraceChart()", 1)[1].split(
            "function measurementCompareDevices", 1
        )[0]
        trainee_chart = trainee_js.split("function drawMeasurementTraceChart()", 1)[1].split(
            "function commandTraceRunKey", 1
        )[0]

        for chart in (simulator_chart, trainee_chart):
            self.assertIn("point.minute <= previousMinute", chart)


if __name__ == "__main__":
    unittest.main()
