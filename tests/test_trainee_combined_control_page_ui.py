import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeCombinedControlPageUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def test_controls_and_commands_share_one_navigation_page(self):
        self.assertNotIn('data-nav-page="controls"', self.html)
        self.assertEqual(self.html.count('data-nav-page="commands"'), 1)
        self.assertEqual(self.html.count('data-page="commands"'), 1)

    def test_right_workspace_has_remote_control_and_adjustment_tabs(self):
        self.assertIn('data-command-tab="remote-control"', self.html)
        self.assertIn('data-command-tab="remote-adjustment"', self.html)
        self.assertIn('id="runControlTable"', self.html)
        self.assertIn('id="setpointControlTable"', self.html)

    def test_both_tables_use_the_same_device_tree_filter(self):
        self.assertIn("controlFilter:", self.script)
        self.assertIn("renderCombinedControlPage", self.script)
        self.assertIn("data-control-tree-type", self.script)
        self.assertIn("activeControlTab", self.script)

    def test_selected_command_has_trace_chart_with_window_selector(self):
        self.assertIn('id="commandTraceChart"', self.html)
        self.assertIn('id="commandTraceWindow"', self.html)
        self.assertIn("控制值", self.html)
        self.assertIn("实时值", self.html)
        self.assertIn('<option value="1440">1日</option>', self.html)
        self.assertIn("function appendCommandTrace", self.script)
        self.assertIn("function drawCommandTraceChart", self.script)
        self.assertIn("selectedCommandTraceKey", self.script)
        self.assertIn("selectedCommandTraceLabel", self.script)
        self.assertIn("data-command-trace-key", self.script)
        self.assertIn("data-command-trace-label", self.script)

    def test_adjustment_trace_key_does_not_replace_command_key(self):
        self.assertIn("traceKey: commandTraceAdjustmentKey(dev, setType)", self.script)
        self.assertIn("data-command-trace-key=\"${escapeHtml(row.traceKey)}\"", self.script)
        self.assertIn("data-remote-adjustment-key=\"${escapeHtml(row.key)}\"", self.script)

    def test_command_trace_single_click_does_not_rerender_rows_before_double_click(self):
        self.assertIn("function selectCommandTraceRow(commandTraceRow)", self.script)
        self.assertIn("selectCommandTraceRow(commandTraceRow);", self.script)
        click_block = self.script.split(
            'const commandTraceRow = target?.closest("[data-command-trace-key]");',
            1,
        )[1]
        click_block = click_block.split("const measurementRow = target?.closest", 1)[0]
        self.assertNotIn("renderCombinedControlPage", click_block)

    def test_remote_control_double_click_uses_whole_row(self):
        run_control_row = self.script.split('return `<tr class="${classes}"', 1)[1].split(">", 1)[0]
        self.assertIn('data-run-status-command="${escapeHtml(key)}"', run_control_row)
        self.assertIn("双击进行遥控操作", run_control_row)
        self.assertIn('target?.closest("[data-run-status-command]")', self.script)
        self.assertIn("findDeviceByKey(statusCell.dataset.runStatusCommand || \"\")", self.script)
        self.assertIn("openRemoteControlDialog(dev)", self.script)


if __name__ == "__main__":
    unittest.main()
