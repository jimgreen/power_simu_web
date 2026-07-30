import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableDieselMetricsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_metric_strip_shows_diesel_current_minimum_and_target(self):
        self.assertIn('<dt>柴油发电当前值</dt><dd id="renewableDieselCurrentKw">--</dd>', self.html)
        self.assertIn('<dt>柴油发电下限值</dt><dd id="renewableDieselMinKw">--</dd>', self.html)
        self.assertIn('<dt>柴油发电目标值</dt><dd id="renewableDieselTargetKw">--</dd>', self.html)
        self.assertNotIn('<dt>柴油缺额</dt>', self.html)

    def test_backend_uses_live_diesel_power_and_model_limits(self):
        diesel_block = self.backend.split("def _diesel_rows", 1)[1].split("def _effective_step_minutes", 1)[0]
        planner_block = self.backend.split("def calculate_renewable_control_plan", 1)[1].split("def _request_json", 1)[0]
        self.assertIn('(\"P_GEN\", \"P\")', diesel_block)
        self.assertIn("p_min", diesel_block)
        self.assertIn("rated_capacity", diesel_block)
        for metric in ("dieselCurrentKw", "dieselMinKw", "dieselTargetKw", "dieselDownMarginKw"):
            self.assertIn(f'"{metric}"', planner_block)

    def test_acdc_feedback_uses_diesel_current_and_lower_limit_not_load(self):
        planner_block = self.backend.split("def calculate_renewable_control_plan", 1)[1].split("def _request_json", 1)[0]
        self.assertIn("diesel_down_margin = diesel_current_for_control - diesel_min", planner_block)
        self.assertIn("candidate_effect = storage_delta", planner_block)
        self.assertNotIn("candidate_effect = renewable_delta + storage_delta", planner_block)
        self.assertIn("predicted_diesel = diesel_current_for_control - candidate_effect", planner_block)
        self.assertIn("_diesel_boundary_violation", planner_block)
        self.assertIn("ACDC与新能源两条策略相互独立", planner_block)
        self.assertIn("负荷功率仅用于展示", planner_block)
        self.assertNotIn("load_kw + total_charge", planner_block)

    def test_rendering_uses_the_three_backend_diesel_values(self):
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("const plan = control.lastPlan", render_block)
        self.assertIn("renewableDieselCurrentKw", render_block)
        self.assertIn("renewableDieselMinKw", render_block)
        self.assertIn("renewableDieselTargetKw", render_block)

    def test_metric_strip_shows_load_power_instead_of_renewable_curtailment(self):
        self.assertIn('<dt>负荷功率</dt><dd id="renewableLoadKw">--</dd>', self.html)
        self.assertNotIn('<dt>弃风弃光</dt>', self.html)
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("renewableLoadKw: metricPowerText(metrics.loadKw)", render_block)
        self.assertNotIn("renewableCurtailKw", render_block)

    def test_sidebar_summary_metrics_use_a_compact_two_column_layout(self):
        metric_block = self.styles.split(".renewable-metric-grid {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", metric_block)
        self.assertIn("overflow-y: auto;", metric_block)
        self.assertIn('class="renewable-side-column"', self.html)


if __name__ == "__main__":
    unittest.main()
