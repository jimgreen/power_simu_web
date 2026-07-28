from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rule_body(styles: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", styles, re.S)
    return match.group("body") if match else ""


def exact_rule_body(styles: str, selector: str) -> str:
    matches = re.finditer(rf"(?m)^{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", styles, re.S)
    return "\n".join(match.group("body") for match in matches)


class RuntimeLogScrollbarUiTest(unittest.TestCase):
    def test_simulator_runtime_log_wrap_has_visible_vertical_scrollbar(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        hidden_block = rule_body(
            styles,
            ".page-nav,\n.curve-tree,\n.curve-table-wrap,\n.fault-table-wrap,\n.mode-table-wrap,\n.data-table,\n.model-param-wrap,\n.runtime-device-wrap,\n.measurement-compare-wrap,\n.fault-list,\n.log-list,\n.mode-table",
        )
        log_block = exact_rule_body(styles, ".runtime-log-wrap")

        self.assertNotIn(".runtime-log-wrap", hidden_block)
        self.assertIn("overflow-y: auto;", log_block)
        self.assertIn("scrollbar-width: thin;", log_block)
        self.assertIn(".runtime-log-wrap::-webkit-scrollbar", styles)

    def test_trainee_runtime_log_wrap_has_visible_vertical_scrollbar(self):
        styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")
        log_block = exact_rule_body(styles, ".runtime-log-wrap")

        self.assertIn("overflow-y: auto;", log_block)
        self.assertIn("scrollbar-width: thin;", log_block)
        self.assertIn(".runtime-log-wrap::-webkit-scrollbar", styles)


if __name__ == "__main__":
    unittest.main()
