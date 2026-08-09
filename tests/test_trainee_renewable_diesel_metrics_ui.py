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

    def test_metric_tabs_show_ac_dc_and_total_diesel_current_minimum_and_target(self):
        expected = (
            ("ac-diesel", "柴发", "renewableAcDieselCurrentKw", "renewableAcDieselTargetKw"),
            ("dc-diesel", "柴发", "renewableDcDieselCurrentKw", "renewableDcDieselTargetKw"),
            ("system-diesel", "柴发", "renewableTotalDieselCurrentKw", "renewableTotalDieselTargetKw"),
        )
        for group, label, current_id, target_id in expected:
            with self.subTest(group=group):
                self.assertIn(
                    f'<tr data-renewable-metric-group="{group}"><th scope="row">{label}'
                    '<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{current_id}">--</td><td id="{target_id}">--</td></tr>',
                    self.html,
                )
        for label, node_id in (
            ("柴发下限", "renewableAcDieselMinKw"),
            ("柴发下限", "renewableDcDieselMinKw"),
            ("柴发下限", "renewableTotalDieselMinKw"),
        ):
            with self.subTest(node_id=node_id):
                self.assertIn(
                    f'<th scope="row">{label}<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{node_id}">--</td>'
                    '<td class="renewable-metric-empty">--</td>',
                    self.html,
                )
        self.assertNotIn('>柴油缺额</th>', self.html)

    def test_backend_uses_live_diesel_power_and_model_limits(self):
        diesel_block = self.backend.split("def _diesel_rows", 1)[1].split("def _effective_step_minutes", 1)[0]
        planner_block = self.backend.split("def calculate_renewable_control_plan", 1)[1].split("def _request_json", 1)[0]
        self.assertIn('(\"P_GEN\", \"P\")', diesel_block)
        self.assertIn("p_min", diesel_block)
        self.assertIn("rated_capacity", diesel_block)
        for metric in (
            "acDieselCurrentKw",
            "acDieselMinKw",
            "acDieselTargetKw",
            "dcDieselCurrentKw",
            "dcDieselMinKw",
            "dcDieselTargetKw",
            "totalDieselCurrentKw",
            "totalDieselMinKw",
            "totalDieselTargetKw",
            "dieselDownMarginKw",
        ):
            self.assertIn(f'"{metric}"', self.backend)

    def test_acdc_feedback_uses_diesel_current_and_lower_limit_not_load(self):
        planner_block = self.backend.split("def calculate_renewable_control_plan", 1)[1].split("def _request_json", 1)[0]
        self.assertIn("diesel_down_margin = diesel_current_for_control - diesel_min", planner_block)
        self.assertIn("direct_grid_forming_plan = _plan_direct_grid_forming_dispatch(", planner_block)
        self.assertIn("component_dispatch_plan = _validate_dispatch_by_ac_component(", planner_block)
        self.assertIn('direct_grid_forming_plan.get("dieselEffectKw")', planner_block)
        self.assertIn('"acComponentDispatch": copy.deepcopy(', planner_block)
        self.assertIn("base_converter_effect_kw", planner_block)
        self.assertIn("direct_ac_storage_effect_kw", planner_block)
        self.assertIn("direct_acdc_effect_kw", planner_block)
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
        for node_id in (
            "renewableAcDieselCurrentKw",
            "renewableAcDieselMinKw",
            "renewableAcDieselTargetKw",
            "renewableDcDieselCurrentKw",
            "renewableDcDieselMinKw",
            "renewableDcDieselTargetKw",
            "renewableTotalDieselCurrentKw",
            "renewableTotalDieselMinKw",
            "renewableTotalDieselTargetKw",
        ):
            self.assertIn(node_id, render_block)

    def test_metric_tabs_show_signed_ac_dc_and_total_load_power(self):
        for label, node_id in (
            ("负荷", "renewableAcLoadKw"),
            ("负荷", "renewableDcLoadKw"),
            ("负荷", "renewableTotalLoadKw"),
        ):
            with self.subTest(node_id=node_id):
                self.assertIn(
                    f'<th scope="row">{label}<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{node_id}">--</td>'
                    '<td class="renewable-metric-empty">--</td>',
                    self.html,
                )
        self.assertNotIn('>弃风弃光</th>', self.html)
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("renewableAcLoadKw: renewableMetricPowerText(metrics.acLoadKw)", render_block)
        self.assertIn("renewableDcLoadKw: renewableMetricPowerText(metrics.dcLoadKw)", render_block)
        self.assertIn('renewableTotalLoadKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalLoadKw", ["loadKw"]))', render_block)
        self.assertNotIn("renewableCurtailKw", render_block)

    def test_metric_units_are_kept_in_the_object_column_and_values_are_unitless(self):
        self.assertIn('class="renewable-metric-unit">（kW）</span>', self.html)
        self.assertIn('class="renewable-metric-unit">（%）</span>', self.html)
        environment_block = self.html.split('class="renewable-environment-readings"', 1)[1].split(
            "</dl>",
            1,
        )[0]
        self.assertIn('<span>m/s</span>', environment_block)
        self.assertIn('<span>W/m²</span>', environment_block)
        self.assertIn(".renewable-metric-unit", self.styles)

        helper_block = "function renewableMetricPowerText" + self.script.split(
            "function renewableMetricPowerText",
            1,
        )[1].split("function renewableStorageUnavailableMetricText", 1)[0]
        self.assertIn("return Number.isFinite(value) ? formatNumber(value) : \"--\";", helper_block)
        self.assertIn("return Number.isFinite(value) ? formatOverviewNumber(value * 100) : \"--\";", helper_block)
        self.assertNotIn(" kW", helper_block)
        self.assertNotIn("}%", helper_block)

        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn(
            "renewableObservedWindSpeed: Number.isFinite(observedWindSpeed) ? formatNumber(observedWindSpeed) : \"--\"",
            render_block,
        )
        self.assertIn(
            "renewableObservedSolarIrradiance: Number.isFinite(observedSolarIrradiance) ? formatNumber(observedSolarIrradiance) : \"--\"",
            render_block,
        )

    def test_sidebar_summary_metrics_use_tabs_and_one_three_column_table_per_tab(self):
        metric_block = self.styles.split(".renewable-metric-table {", 1)[1].split("}", 1)[0]
        metric_panes_block = self.styles.split(".renewable-metric-panes {", 1)[1].split("}", 1)[0]
        metric_active_pane_block = self.styles.split(".renewable-metric-pane.is-active {", 1)[1].split("}", 1)[0]
        metric_wrap_block = self.styles.split(".renewable-metric-table-wrap {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%;", metric_block)
        self.assertIn("min-width: 0;", metric_block)
        self.assertIn("max-width: 100%;", metric_block)
        self.assertIn("height: 100%;", metric_block)
        self.assertIn("border-collapse: collapse;", metric_block)
        self.assertIn("table-layout: fixed;", metric_block)
        self.assertIn("display: flex;", metric_panes_block)
        self.assertIn("flex-direction: column;", metric_panes_block)
        self.assertIn("overflow-x: hidden;", metric_panes_block)
        self.assertIn("overflow-y: auto;", metric_panes_block)
        self.assertIn("display: flex;", metric_active_pane_block)
        self.assertIn("flex-direction: column;", metric_active_pane_block)
        self.assertIn("min-height: 100%;", metric_active_pane_block)
        self.assertIn("flex: 1 1 auto;", metric_wrap_block)
        self.assertIn("display: flex;", metric_wrap_block)
        self.assertIn("overflow-x: hidden;", metric_wrap_block)
        self.assertIn("overflow-y: auto;", metric_wrap_block)
        self.assertNotIn("overflow-x: auto;", metric_wrap_block)
        metric_cell_block = self.styles.split(
            ".renewable-metric-table th,",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("padding: 5px 8px;", metric_cell_block)
        self.assertIn(".renewable-metric-tabs", self.styles)
        self.assertIn(".renewable-metric-table-wrap", self.styles)
        self.assertNotIn(".renewable-metric-grid", self.styles)
        self.assertIn('class="renewable-side-column"', self.html)


if __name__ == "__main__":
    unittest.main()
