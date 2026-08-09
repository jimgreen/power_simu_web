from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChartPeriodNavigationUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulator_html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        cls.simulator_js = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        cls.simulator_css = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")
        cls.trainee_html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.trainee_js = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.trainee_css = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    @staticmethod
    def _range_payload(script: str, end_marker: str) -> dict:
        marker = "function traceAxisStepMinutes"
        if marker not in script or end_marker not in script:
            raise AssertionError("trace window helpers are missing")
        source = marker + script.split(marker, 1)[1].split(end_marker, 1)[0]
        body = r"""
const crossingHistory = [{ minute: 595 }, { minute: 605 }];
const containedHistory = [{ minute: 600 }, { minute: 605 }];
const deepHistory = [{ minute: 480 }, { minute: 605 }];
const current = alignedTraceWindowRange(crossingHistory, 60, 605, 0);
const previous = alignedTraceWindowRange(crossingHistory, 60, 605, -1);
const clampedFuture = alignedTraceWindowRange(crossingHistory, 60, 605, 1);
const clampedPast = alignedTraceWindowRange(crossingHistory, 60, 605, -99);
const contained = alignedTraceWindowRange(containedHistory, 60, 605, 0);
const deepPast = alignedTraceWindowRange(deepHistory, 60, 605, -2);
const fullCycle = alignedTraceWindowRange(crossingHistory, 60, 605, -1, 60);
process.stdout.write(JSON.stringify({
  current,
  previous,
  clampedFuture,
  clampedPast,
  contained,
  deepPast,
  fullCycle,
  currentNavigation: tracePeriodNavigationState(current),
  previousNavigation: tracePeriodNavigationState(previous),
  containedNavigation: tracePeriodNavigationState(contained),
  fullCycleNavigation: tracePeriodNavigationState(fullCycle),
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

    @staticmethod
    def _diagram_range_payload(script: str) -> dict:
        marker = "const DIAGRAM_TREND_WINDOWS"
        end_marker = "function addDiagramControlAliases"
        if marker not in script or end_marker not in script:
            raise AssertionError("diagram trend helpers are missing")
        source = marker + script.split(marker, 1)[1].split(end_marker, 1)[0]
        navigation_marker = "function diagramTrendNavigationState"
        navigation_end = "function diagramTrendNavigationHtml"
        if navigation_marker not in script or navigation_end not in script:
            raise AssertionError("diagram trend navigation state helper is missing")
        source += "\n" + navigation_marker + script.split(navigation_marker, 1)[1].split(navigation_end, 1)[0]
        body = r"""
const points = [
  { minute: 595, value: 1 },
  { minute: 605, value: 2 },
];
const current = diagramTrendNavigationRange(points, "hour", 605, 0);
const previous = diagramTrendNavigationRange(points, "hour", 605, -1);
const fullCycle = diagramTrendNavigationRange(points, "hour", 605, -1, 60);
process.stdout.write(JSON.stringify({
  current,
  previous,
  fullCycle,
  currentPoints: diagramTrendWindowPoints(points, "hour", 605, 0).map((point) => point.minute),
  previousPoints: diagramTrendWindowPoints(points, "hour", 605, -1).map((point) => point.minute),
  currentNavigation: diagramTrendNavigationState(current),
  previousNavigation: diagramTrendNavigationState(previous),
  fullCycleNavigation: diagramTrendNavigationState(fullCycle),
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

    def test_partial_history_charts_expose_three_button_navigation(self):
        simulator_keys = ("runtimeTrace", "measurementTrace")
        trainee_keys = ("measurementTrace", "commandTrace", "renewableTrend")
        for chart_key in simulator_keys:
            with self.subTest(app="simulator", chart=chart_key):
                self.assertIn(f'data-chart-period-nav="{chart_key}"', self.simulator_html)
        for chart_key in trainee_keys:
            with self.subTest(app="trainee", chart=chart_key):
                self.assertIn(f'data-chart-period-nav="{chart_key}"', self.trainee_html)
        for html in (self.simulator_html, self.trainee_html):
            self.assertGreaterEqual(html.count('data-chart-period-action="previous"'), 2)
            self.assertGreaterEqual(html.count('data-chart-period-action="current"'), 2)
            self.assertGreaterEqual(html.count('data-chart-period-action="next"'), 2)

    def test_full_profile_curves_do_not_receive_period_navigation(self):
        for html in (self.simulator_html, self.trainee_html):
            self.assertNotIn('data-chart-period-nav="curveEditor"', html)
            self.assertNotIn('data-chart-period-nav="curveDisplay"', html)

    def test_window_offsets_move_by_one_complete_period_and_clamp_to_history(self):
        for app, script, end_marker in (
            ("simulator", self.simulator_js, "function runtimeTraceWindowRange"),
            ("trainee", self.trainee_js, "function measurementTraceWindowRange"),
        ):
            with self.subTest(app=app):
                payload = self._range_payload(script, end_marker)
                self.assertEqual(payload["current"]["startMinute"], 600)
                self.assertEqual(payload["current"]["endMinute"], 660)
                self.assertEqual(payload["current"]["windowOffset"], 0)
                self.assertEqual(payload["current"]["minWindowOffset"], -1)
                self.assertEqual(payload["previous"]["startMinute"], 540)
                self.assertEqual(payload["previous"]["endMinute"], 600)
                self.assertEqual(payload["previous"]["windowOffset"], -1)
                self.assertEqual(payload["clampedFuture"]["windowOffset"], 0)
                self.assertEqual(payload["clampedPast"]["windowOffset"], -1)
                self.assertEqual(payload["deepPast"]["startMinute"], 480)
                self.assertEqual(payload["deepPast"]["windowOffset"], -2)

                self.assertTrue(payload["currentNavigation"]["visible"])
                self.assertFalse(payload["currentNavigation"]["previousDisabled"])
                self.assertTrue(payload["currentNavigation"]["currentDisabled"])
                self.assertTrue(payload["currentNavigation"]["nextDisabled"])
                self.assertTrue(payload["previousNavigation"]["previousDisabled"])
                self.assertFalse(payload["previousNavigation"]["currentDisabled"])
                self.assertFalse(payload["previousNavigation"]["nextDisabled"])
                self.assertFalse(payload["containedNavigation"]["visible"])
                self.assertFalse(payload["fullCycle"]["periodNavigationAllowed"])
                self.assertEqual(payload["fullCycle"]["windowOffset"], 0)
                self.assertEqual(payload["fullCycle"]["minWindowOffset"], 0)
                self.assertFalse(payload["fullCycleNavigation"]["visible"])
                self.assertTrue(payload["fullCycleNavigation"]["previousDisabled"])
                self.assertTrue(payload["fullCycleNavigation"]["currentDisabled"])
                self.assertTrue(payload["fullCycleNavigation"]["nextDisabled"])

    def test_navigation_is_wired_to_draws_window_changes_and_lifecycle_resets(self):
        for app, script, chart_keys in (
            ("simulator", self.simulator_js, ("runtimeTrace", "measurementTrace")),
            ("trainee", self.trainee_js, ("measurementTrace", "commandTrace", "renewableTrend")),
        ):
            with self.subTest(app=app):
                self.assertIn("chartPeriodOffsets", script)
                self.assertIn("function syncChartPeriodNavigation", script)
                self.assertIn("function initChartPeriodNavigation", script)
                self.assertIn("function resetChartPeriodOffsets", script)
                for chart_key in chart_keys:
                    self.assertIn(f'syncChartPeriodNavigation("{chart_key}"', script)
                    self.assertIn(f'initChartPeriodNavigation("{chart_key}"', script)
                    self.assertIn(f'resetChartPeriodOffsets("{chart_key}")', script)

    def test_svg_hour_and_day_tooltips_have_independent_period_navigation(self):
        for app, script in (("simulator", self.simulator_js), ("trainee", self.trainee_js)):
            with self.subTest(app=app):
                self.assertIn('trendPeriodOffsets: { hour: 0, day: 0 }', script)
                self.assertIn("function diagramTrendNavigationRange", script)
                self.assertIn("function syncDiagramTrendNavigation", script)
                self.assertIn('data-diagram-trend-action="previous"', script)
                self.assertIn('data-diagram-trend-action="current"', script)
                self.assertIn('data-diagram-trend-action="next"', script)
                self.assertIn('target.closest("[data-diagram-trend-action]")', script)

                payload = self._diagram_range_payload(script)
                self.assertEqual(payload["current"]["startMinute"], 600)
                self.assertEqual(payload["current"]["minWindowOffset"], -1)
                self.assertEqual(payload["previous"]["startMinute"], 540)
                self.assertEqual(payload["currentPoints"], [605])
                self.assertEqual(payload["previousPoints"], [595])
                self.assertTrue(payload["currentNavigation"]["visible"])
                self.assertTrue(payload["previousNavigation"]["previousDisabled"])
                self.assertFalse(payload["previousNavigation"]["nextDisabled"])
                self.assertFalse(payload["fullCycle"]["periodNavigationAllowed"])
                self.assertEqual(payload["fullCycle"]["windowOffset"], 0)
                self.assertFalse(payload["fullCycleNavigation"]["visible"])

    def test_navigation_uses_the_active_simulation_cycle_as_its_upper_bound(self):
        self.assertIn("function simulationModeDurationMinutes", self.simulator_js)
        self.assertIn("function curveDisplayModeDurationMinutes", self.trainee_js)
        self.assertGreaterEqual(self.simulator_js.count("simulationModeDurationMinutes()"), 3)
        self.assertGreaterEqual(self.trainee_js.count("curveDisplayModeDurationMinutes()"), 4)

    def test_navigation_controls_have_compact_stable_styles(self):
        for app, styles in (("simulator", self.simulator_css), ("trainee", self.trainee_css)):
            with self.subTest(app=app):
                self.assertIn(".chart-period-navigation", styles)
                self.assertIn(".chart-period-navigation[hidden]", styles)
                self.assertIn(".chart-period-navigation button", styles)
                self.assertIn("width: 28px", styles)
                self.assertIn("height: 28px", styles)
                self.assertIn(".diagram-trend-period-navigation", styles)


if __name__ == "__main__":
    unittest.main()
