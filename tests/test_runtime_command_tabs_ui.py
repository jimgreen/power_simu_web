from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeCommandTabsUiTest(unittest.TestCase):
    def test_remote_control_and_adjustment_use_separate_tab_tables(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("activeRuntimeCommandTab", app_js)
        self.assertIn('data-runtime-command-tab="remote_control"', app_js)
        self.assertIn('data-runtime-command-tab="remote_adjustment"', app_js)
        self.assertIn("function setRuntimeCommandTab", app_js)
        self.assertIn("runtime-command-tab-page", app_js)
        self.assertIn(".runtime-command-tabs", styles)


if __name__ == "__main__":
    unittest.main()
