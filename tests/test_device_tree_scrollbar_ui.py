from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeviceTreeScrollbarUiTest(unittest.TestCase):
    def test_device_trees_have_visible_vertical_scrollbars(self):
        surfaces = (
            ROOT / "simu" / "web" / "simulator" / "styles.css",
            ROOT / "simu" / "web" / "trainee" / "styles.css",
        )

        for css_path in surfaces:
            with self.subTest(surface=css_path.parent.name):
                styles = css_path.read_text(encoding="utf-8")
                device_tree_rule = self._rule_body(styles, ".device-tree")

                self.assertIn("overflow-x: hidden;", device_tree_rule)
                self.assertIn("overflow-y: auto;", device_tree_rule)
                self.assertIn("scrollbar-width: thin;", device_tree_rule)
                self.assertIn(".device-tree::-webkit-scrollbar", styles)

    def test_simulator_device_tree_is_not_in_hidden_scrollbar_rule(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        hidden_scrollbar_rule = self._rule_body(styles, ".page-nav")
        self.assertNotIn(".device-tree", hidden_scrollbar_rule)
        self.assertIsNone(
            re.search(r"\.device-tree::?-webkit-scrollbar,\s*", styles),
            "device tree scrollbar must not be part of the hidden scrollbar selector list",
        )

    @staticmethod
    def _rule_body(styles: str, selector: str) -> str:
        match = re.search(
            rf"{re.escape(selector)}(?P<selectors>[^{{]*)\{{(?P<body>.*?)\n\}}",
            styles,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError(f"{selector} rule not found")
        return f"{match.group('selectors')}\n{match.group('body')}"


if __name__ == "__main__":
    unittest.main()
