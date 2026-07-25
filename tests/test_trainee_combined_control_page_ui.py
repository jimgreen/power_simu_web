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


if __name__ == "__main__":
    unittest.main()
