from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeCollectionPeriodAndTargetCurveUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(
            encoding="utf-8"
        )
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(
            encoding="utf-8"
        )
        cls.simulator_script = (ROOT / "simu/web/simulator/app.js").read_text(
            encoding="utf-8"
        )

    def test_parameter_page_exposes_backend_data_refresh_period(self):
        self.assertIn("后台数据刷新周期", self.html)
        self.assertIn('id="webRuntimeBackendRefresh"', self.html)
        self.assertIn('data-runtime-setting="backend_refresh_seconds"', self.html)
        self.assertIn("新能源趋势采样周期", self.html)

    def test_control_period_is_numeric_and_validated_against_collection_period(self):
        self.assertIn(
            'id="renewableControlPeriod" type="number"',
            self.html,
        )
        self.assertIn("function renewableControlIntervalError", self.script)
        self.assertIn("control <= collection", self.script)
        self.assertIn("Math.round(ratio)", self.script)
        self.assertIn(
            'activeRuntimeSetting("backend_refresh_seconds")',
            self.script,
        )
        self.assertIn(
            "state.receiveMode\n    ? backendDataRefreshIntervalMs()",
            self.script,
        )

    def test_target_series_are_rendered_as_horizontal_then_vertical_steps(self):
        self.assertIn('series.style === "target"', self.script)
        horizontal = self.script.index("ctx.lineTo(x, previousY);")
        vertical = self.script.index("ctx.lineTo(x, y);", horizontal)
        self.assertLess(horizontal, vertical)

    def test_trainee_control_value_curve_is_rendered_as_a_step(self):
        command_chart = self.script.split("function drawCommandTraceChart()", 1)[1]
        self.assertIn('series.key === "control"', command_chart)
        horizontal = command_chart.index("ctx.lineTo(x, previousY);")
        vertical = command_chart.index("ctx.lineTo(x, y);", horizontal)
        self.assertLess(horizontal, vertical)

    def test_simulator_control_command_curve_is_rendered_as_a_step(self):
        runtime_chart = self.simulator_script.split(
            "function drawRuntimeTraceChart()",
            1,
        )[1].split("function measurementDefinitionRows", 1)[0]
        self.assertIn('series.key === "control"', runtime_chart)
        horizontal = runtime_chart.index("ctx.lineTo(x, previousY);")
        vertical = runtime_chart.index("ctx.lineTo(x, y);", horizontal)
        self.assertLess(horizontal, vertical)


if __name__ == "__main__":
    unittest.main()
