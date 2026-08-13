import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableVerticalLayoutUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_page_uses_one_shared_horizontal_split_for_both_columns(self):
        self.assertIn('class="renewable-page-layout vertical-split-workspace"', self.html)
        self.assertIn('class="renewable-side-column"', self.html)
        self.assertIn('class="renewable-right-layout"', self.html)
        self.assertNotIn('class="renewable-right-layout vertical-split-workspace"', self.html)
        self.assertIn('<h2>参数配置</h2>', self.html)
        self.assertIn('<h2>统计指标</h2>', self.html)
        self.assertEqual(self.html.count('data-vertical-split="trainee-renewable"'), 1)
        self.assertEqual(self.html.count('data-vertical-splitter="trainee-renewable"'), 1)
        self.assertIn('aria-label="同时调整上下两排区域高度"', self.html)
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
            "ac-wind": "交流风电",
            "dc-wind": "直流风电",
            "ac-pv": "交流光伏",
            "dc-pv": "直流光伏",
            "ac-grid-storage": "交流跟网储能",
            "dc-grid-storage": "直流跟网储能",
            "ac-balance-storage": "交流平衡储能",
            "dc-balance-storage": "直流平衡储能",
            "diesel": "柴发",
            "converter": "ACDC变流",
            "hydrogen": "氢能",
        }
        for key, label in expected_tabs.items():
            self.assertIn(f'data-renewable-strategy-tab="{key}"', self.html)
            self.assertIn(f">{label}</button>", self.html)
        for old_key in ("wind", "pv", "storage"):
            self.assertNotIn(f'data-renewable-strategy-tab="{old_key}"', self.html)
        self.assertNotIn('id="renewableStrategyPager"', self.html)
        self.assertIn('id="renewableControlLogPager"', self.html)
        self.assertIn('strategyTab: "ac-wind"', self.script)
        self.assertIn("function renewableStrategyRows", self.script)
        self.assertIn("function renderRenewableStrategyTabs", self.script)
        self.assertIn(
            'hydrogen: { label: "氢能", categories: new Set(["氢能"]) }',
            self.script,
        )
        self.assertNotIn('id="renewableStrategyDiagnostics"', self.html)
        self.assertNotIn("function renewableStrategyDiagnosticRows", self.script)
        self.assertNotIn("function renderRenewableStrategyDiagnostics", self.script)
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

    def test_metrics_use_single_row_ac_dc_system_and_hydrogen_tabs(self):
        self.assertIn('id="renewableMetricTabs"', self.html)
        for key, label in (("ac", "交流"), ("dc", "直流"), ("system", "系统"), ("hydrogen", "氢能")):
            with self.subTest(key=key):
                self.assertIn(f'data-renewable-metric-tab="{key}"', self.html)
                self.assertIn(f'>{label}</button>', self.html)
                self.assertIn(f'data-renewable-metric-pane="{key}"', self.html)
        metric_tabs = self.styles.split(".renewable-metric-tabs {", 1)[1].split("}", 1)[0]
        metric_buttons = self.styles.split(".renewable-metric-tabs button {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr));", metric_tabs)
        self.assertIn("white-space: nowrap;", metric_buttons)
        for group, label, current_id, target_id in (
            ("ac-renewable", "新能源", "renewableAcCurrentKw", "renewableAcTargetKw"),
            ("dc-renewable", "新能源", "renewableDcCurrentKw", "renewableDcTargetKw"),
            ("system-renewable", "新能源", "renewableTotalCurrentKw", "renewableTotalTargetKw"),
        ):
            with self.subTest(group=group):
                self.assertIn(
                    f'<tr data-renewable-metric-group="{group}"><th scope="row">{label}'
                    '<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{current_id}">--</td><td id="{target_id}">--</td></tr>',
                    self.html,
                )
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
        self.assertNotIn('>可用新能源</th>', self.html)
        self.assertNotIn('>计划消纳</th>', self.html)
        self.assertIn('metricTab: "ac"', self.script)
        self.assertIn("function renderRenewableMetricTabs", self.script)
        self.assertIn("renewableAcDieselCurrentKw", self.script)
        self.assertIn("renewableDcDieselCurrentKw", self.script)
        self.assertIn("renewableTotalCurrentKw", self.script)
        for label, node_id in (
            ("新能源最大可发", "renewableAcMaxAvailableKw"),
            ("风电最大可发", "renewableAcWindMaxAvailableKw"),
            ("光伏最大可发", "renewableAcPvMaxAvailableKw"),
            ("新能源最大可发", "renewableDcMaxAvailableKw"),
            ("风电最大可发", "renewableDcWindMaxAvailableKw"),
            ("光伏最大可发", "renewableDcPvMaxAvailableKw"),
            ("新能源最大可发", "renewableTotalMaxAvailableKw"),
            ("风电最大可发", "renewableTotalWindMaxAvailableKw"),
            ("光伏最大可发", "renewableTotalPvMaxAvailableKw"),
        ):
            with self.subTest(node_id=node_id):
                self.assertIn(
                    f'<th scope="row">{label}<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{node_id}">--</td>',
                    self.html,
                )

    def test_metric_row_labels_do_not_repeat_the_active_scope(self):
        expected_labels = {
            "ac": ("新能源", "风电", "光伏", "跟网储能", "构网储能", "柴发", "负荷"),
            "dc": ("新能源", "风电", "光伏", "跟网储能", "构网储能", "柴发", "负荷"),
            "system": ("新能源", "风电", "光伏", "跟网储能", "构网储能", "柴发", "负荷", "ACDC变流"),
        }
        for key, prefix in (("ac", "交流"), ("dc", "直流"), ("system", "总")):
            pane = self.html.split(f'data-renewable-metric-pane="{key}"', 1)[1].split(
                "</section>",
                1,
            )[0]
            with self.subTest(key=key):
                self.assertNotIn(f'<th scope="row">{prefix}', pane)
                for label in expected_labels[key]:
                    self.assertIn(f'<th scope="row">{label}', pane)

    def test_live_weather_values_are_shown_in_parameter_configuration(self):
        control_panel = self.html.split('<section class="panel renewable-control-panel">', 1)[1].split(
            '<section class="panel renewable-metrics-panel">',
            1,
        )[0]
        system_pane = self.html.split('data-renewable-metric-pane="system"', 1)[1].split(
            "</section>",
            1,
        )[0]
        self.assertIn("实时风速", control_panel)
        self.assertIn('id="renewableObservedWindSpeed"', control_panel)
        self.assertIn("实时太阳辐照度", control_panel)
        self.assertIn('id="renewableObservedSolarIrradiance"', control_panel)
        self.assertNotIn('id="renewableObservedWindSpeed"', system_pane)
        self.assertNotIn('id="renewableObservedSolarIrradiance"', system_pane)

    def test_each_metric_tab_uses_one_three_column_table_and_keeps_value_ids_unique(self):
        self.assertEqual(self.html.count('class="renewable-metric-table"'), 4)
        self.assertEqual(self.html.count('<th scope="col">值对象</th>'), 4)
        self.assertEqual(self.html.count('<th scope="col">实时值</th>'), 4)
        self.assertEqual(self.html.count('<th scope="col">目标值</th>'), 4)
        self.assertNotIn('class="renewable-metric-grid"', self.html)
        for node_id in (
            "renewableAcCurrentKw",
            "renewableAcTargetKw",
            "renewableDcCurrentKw",
            "renewableDcTargetKw",
            "renewableTotalCurrentKw",
            "renewableTotalTargetKw",
            "renewableAcdcCurrentKw",
            "renewableAcdcTargetKw",
        ):
            with self.subTest(node_id=node_id):
                self.assertEqual(self.html.count(f'id="{node_id}"'), 1)

    def test_main_panel_replaces_individual_parameters_with_one_dialog_button(self):
        main_panel = self.html.split('<section class="panel renewable-control-panel">', 1)[1].split(
            '<section class="panel renewable-metrics-panel">',
            1,
        )[0]
        self.assertIn('id="renewableControlParametersButton"', main_panel)
        self.assertIn('>控制参数</button>', main_panel)
        for input_id in (
            "renewableControlPeriod",
            "renewableCommandValidMinutes",
            "renewableStepRatio",
            "storageStepRatio",
            "storageSocCorrectionStepScale",
            "gridFormingStorageProtectionRatio",
            "dieselPowerProtectionRatio",
            "socDeadband",
            "storagePowerDeratingButton",
        ):
            with self.subTest(input_id=input_id):
                self.assertNotIn(f'id="{input_id}"', main_panel)
                self.assertEqual(self.html.count(f'id="{input_id}"'), 1)
        self.assertIn('id="renewableControlParametersDialog"', self.html)
        self.assertIn('<h2 id="renewableControlParametersTitle">控制参数</h2>', self.html)
        self.assertIn("function openRenewableControlParametersDialog", self.script)
        self.assertIn("function closeRenewableControlParametersDialog", self.script)

    def test_last_calculation_summary_belongs_to_the_parameter_panel(self):
        control_panel = self.html.split('<section class="panel renewable-control-panel">', 1)[1].split(
            '<section class="panel renewable-metrics-panel">',
            1,
        )[0]
        metric_panel = self.html.split('<section class="panel renewable-metrics-panel">', 1)[1].split(
            '</aside>',
            1,
        )[0]
        self.assertIn('class="renewable-last-action"', control_panel)
        self.assertIn('id="renewableLastActionLabel"', control_panel)
        self.assertIn('id="renewableLastSent"', control_panel)
        self.assertNotIn('id="renewableLastActionLabel"', metric_panel)
        self.assertNotIn('id="renewableLastSent"', metric_panel)
        last_action_block = self.styles.split(".renewable-last-action {", 1)[1].split("}", 1)[0]
        self.assertIn("margin-top: auto;", last_action_block)
        self.assertIn("border-top: 1px solid var(--line);", last_action_block)

    def test_control_logs_are_scoped_and_show_the_decision_chain(self):
        backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        self.assertIn('"logs": copy.deepcopy(logs)', backend)
        self.assertIn("entry.get(\"seq\")", backend)
        self.assertIn("self._append_log", backend)
        self.assertIn("function renewableControlLogs", self.script)
        self.assertIn("function renderRenewableControlLogs", self.script)
        self.assertIn("state.renewableControl.logs", self.script)
        for label in (
            "控制架构",
            "控制基准",
            "柴发分区",
            "SOC分区",
            "SOC运行约束",
            "环境策略",
            "ACDC策略",
            "ACDC独立预估",
            "新能源策略",
            "新能源目标",
            "负荷功率仅用于展示",
            "独立边界检查",
        ):
            self.assertIn(label, backend)
        self.assertNotIn("增量平衡", backend)

    def test_strategy_and_tabbed_detail_area_reuse_the_persisted_split_ratio_system(self):
        self.assertIn('"trainee-renewable": 44', self.script)
        self.assertNotIn('"trainee-renewable-lower": 55', self.script)
        self.assertIn(
            ".renewable-page-layout.vertical-split-workspace",
            self.styles,
        )
        unified_layout_block = self.styles.split(
            ".renewable-page-layout.vertical-split-workspace {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("grid-template-rows:", unified_layout_block)
        self.assertIn("var(--vertical-split-top, 44%)", unified_layout_block)
        self.assertIn("row-gap: 0;", unified_layout_block)
        flattened_columns_block = self.styles.split(
            ".renewable-page-layout > .renewable-side-column,",
            1,
        )[1].split("}", 1)[0]
        self.assertIn(".renewable-page-layout > .renewable-right-layout", flattened_columns_block)
        self.assertIn("display: contents;", flattened_columns_block)
        shared_splitter_block = self.styles.split(
            ".renewable-page-layout > .renewable-right-layout > .vertical-stack-splitter {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("grid-column: 1 / -1;", shared_splitter_block)
        self.assertIn("grid-row: 2;", shared_splitter_block)
        for selector, column, row in (
            (".renewable-control-panel", "1", "1"),
            (".renewable-plan-panel", "2", "1"),
            (".renewable-metrics-panel", "1", "3"),
            (".renewable-detail-panel", "2", "3"),
        ):
            with self.subTest(selector=selector):
                block = self.styles.split(f"{selector} {{", 1)[1].split("}", 1)[0]
                self.assertIn(f"grid-column: {column};", block)
                self.assertIn(f"grid-row: {row};", block)
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

    def test_control_log_uses_summary_rows_and_opens_full_decision_dialog(self):
        self.assertIn('id="renewableControlLogDetailDialog"', self.html)
        self.assertIn('id="renewableControlLogDetailMeta"', self.html)
        self.assertIn('id="renewableControlLogDetailBody"', self.html)
        self.assertIn('id="closeRenewableControlLogDetailDialog"', self.html)
        self.assertIn("function renewableControlLogSummaryText", self.script)
        self.assertIn("function renewableControlLogBySeq", self.script)
        self.assertIn("function openRenewableControlLogDetailDialog", self.script)
        self.assertIn("function closeRenewableControlLogDetailDialog", self.script)
        self.assertIn('data-renewable-log-seq="${escapeHtml(item.seq)}"', self.script)
        self.assertIn('tabindex="0"', self.script)
        self.assertIn('item.full_detail', self.script)
        self.assertIn('addEventListener("dblclick"', self.script)
        self.assertIn('addEventListener("keydown"', self.script)
        self.assertIn('event.key !== "Enter"', self.script)
        self.assertIn("closeRenewableControlLogDetailDialog();", self.script)
        self.assertIn("<th>决策摘要</th>", self.script)

        detail_cell = self.styles.split(
            ".renewable-control-log-table .runtime-log-row td:nth-child(5) {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("white-space: nowrap;", detail_cell)
        self.assertIn("overflow: hidden;", detail_cell)
        self.assertIn("text-overflow: ellipsis;", detail_cell)
        self.assertIn(".renewable-control-log-detail-dialog", self.styles)
        self.assertIn(".renewable-control-log-detail-steps", self.styles)


if __name__ == "__main__":
    unittest.main()
