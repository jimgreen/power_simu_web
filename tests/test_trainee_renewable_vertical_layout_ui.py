import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableVerticalLayoutUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_page_uses_left_sidebar_and_right_strategy_plus_tabbed_detail_workspace(self):
        self.assertIn('class="renewable-page-layout"', self.html)
        self.assertIn('class="renewable-side-column"', self.html)
        self.assertIn('<h2>参数配置</h2>', self.html)
        self.assertIn('<h2>统计指标</h2>', self.html)
        self.assertIn('class="renewable-right-layout vertical-split-workspace"', self.html)
        self.assertIn('data-vertical-split="trainee-renewable"', self.html)
        self.assertIn('data-vertical-splitter="trainee-renewable"', self.html)
        self.assertNotIn('data-vertical-split="trainee-renewable-lower"', self.html)
        self.assertNotIn('data-vertical-splitter="trainee-renewable-lower"', self.html)
        self.assertIn('<h2>控制策略</h2>', self.html)
        self.assertIn('id="renewableCommandTable"', self.html)
        self.assertIn('<h2>综合功率趋势</h2>', self.html)
        self.assertIn('<h2>控制日志</h2>', self.html)
        self.assertIn('id="renewableControlLogTable"', self.html)
        self.assertIn('id="renewableControlLogSummary"', self.html)

        parameter_pos = self.html.index('<h2>参数配置</h2>')
        metric_pos = self.html.index('<h2>统计指标</h2>')
        strategy_pos = self.html.index('<h2>控制策略</h2>')
        chart_pos = self.html.index('<h2>综合功率趋势</h2>')
        log_pos = self.html.index('<h2>控制日志</h2>')
        self.assertLess(parameter_pos, strategy_pos)
        self.assertLess(metric_pos, strategy_pos)
        self.assertLess(strategy_pos, chart_pos)
        self.assertLess(chart_pos, log_pos)

    def test_strategy_uses_device_category_tabs_and_control_logs_remain_paginated(self):
        self.assertIn('id="renewableStrategyTabs"', self.html)
        expected_tabs = {
            "wind": "风电",
            "pv": "光伏",
            "storage": "储能",
            "diesel": "柴发",
            "converter": "变流",
        }
        for key, label in expected_tabs.items():
            self.assertIn(f'data-renewable-strategy-tab="{key}"', self.html)
            self.assertIn(f">{label}</button>", self.html)
        self.assertNotIn('id="renewableStrategyPager"', self.html)
        self.assertIn('id="renewableControlLogPager"', self.html)
        self.assertIn('strategyTab: "wind"', self.script)
        self.assertIn("function renewableStrategyRows", self.script)
        self.assertIn("function renderRenewableStrategyTabs", self.script)
        self.assertIn("RENEWABLE_CONTROL_LOG_PAGE_SIZE", self.script)
        self.assertIn("function renderRenewablePager", self.script)
        self.assertIn('data-renewable-pager="logs"', self.script)
        backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        plan_block = backend.split("def calculate_renewable_control_plan", 1)[1].split(
            "def _request_json",
            1,
        )[0]
        self.assertIn("command_rows.extend", plan_block)
        self.assertIn("for row in diesel_rows", plan_block)

    def test_current_and_target_metrics_use_requested_labels(self):
        self.assertIn('<dt>新能源当前值</dt><dd id="renewableCurrentKw">--</dd>', self.html)
        self.assertIn('<dt>新能源目标值</dt><dd id="renewableTargetKw">--</dd>', self.html)
        self.assertNotIn('<dt>可用新能源</dt>', self.html)
        self.assertNotIn('<dt>计划消纳</dt>', self.html)
        self.assertIn("renewableCurrentKw", self.script)
        self.assertIn("renewableTargetKw", self.script)

    def test_control_logs_are_scoped_and_show_the_decision_chain(self):
        backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        self.assertIn('"logs": copy.deepcopy(state.logs)', backend)
        self.assertIn("self._append_log", backend)
        self.assertIn("function renewableControlLogs", self.script)
        self.assertIn("function renderRenewableControlLogs", self.script)
        self.assertIn("state.renewableControl.logs", self.script)
        for label in (
            "控制基准",
            "环境策略",
            "新能源上调边界",
            "增量平衡",
            "负荷功率仅用于展示",
            "恢复策略",
            "预期结果",
        ):
            self.assertIn(label, backend)

    def test_strategy_and_tabbed_detail_area_reuse_the_persisted_split_ratio_system(self):
        self.assertIn('"trainee-renewable": 44', self.script)
        self.assertNotIn('"trainee-renewable-lower": 55', self.script)
        self.assertIn(
            ".renewable-right-layout.vertical-split-workspace",
            self.styles,
        )
        self.assertIn('data-renewable-detail-tab="trend"', self.html)
        self.assertIn('data-renewable-detail-tab="logs"', self.html)
        self.assertIn('data-renewable-detail-pane="trend"', self.html)
        self.assertIn('data-renewable-detail-pane="logs"', self.html)
        self.assertNotIn('data-vertical-splitter="trainee-renewable-lower"', self.html)
        self.assertIn("function renderRenewableDetailTabs", self.script)
        self.assertIn(".renewable-side-column", self.styles)
        self.assertIn("grid-template-columns: clamp(", self.styles)
        self.assertIn("renewable-control-toolbar", self.styles)
        self.assertIn("renewable-control-log-panel", self.styles)

    def test_strategy_table_displays_the_definition_driven_remote_adjustment_point_name(self):
        render_block = self.script.split("function renderRenewableControl(snapshot", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("<th>遥调点名称</th>", render_block)
        self.assertIn("renewableRemoteAdjustmentPointName(row)", render_block)
        self.assertIn("function renewableRemoteAdjustmentPointName", self.script)
        self.assertIn("`${row.dev_type}.${row.dev_name}.${row.set_type}`", self.script)

    def test_strategy_table_headers_and_cells_are_right_aligned(self):
        alignment_block = self.styles.split(
            ".runtime-device-table.renewable-command-table th,",
            1,
        )[1].split("}", 1)[0]
        self.assertIn(".runtime-device-table.renewable-command-table td", alignment_block)
        self.assertIn("text-align: right;", alignment_block)

    def test_control_log_reserves_most_width_for_decision_detail(self):
        self.assertIn(
            ".runtime-log-table.renewable-control-log-table",
            self.styles,
        )
        for column, width in ((1, "84px"), (2, "96px"), (3, "88px"), (4, "96px")):
            selector = f".runtime-log-table.renewable-control-log-table th:nth-child({column}),"
            block = self.styles.split(selector, 1)[1].split("}", 1)[0]
            self.assertIn(f"width: {width};", block)
        detail_block = self.styles.split(
            ".runtime-log-table.renewable-control-log-table th:nth-child(5),",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("width: auto;", detail_block)


if __name__ == "__main__":
    unittest.main()
