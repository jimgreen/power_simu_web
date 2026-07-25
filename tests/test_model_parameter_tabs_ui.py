from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelParameterTabsUiTest(unittest.TestCase):
    def test_each_model_parameter_table_is_rendered_as_a_tab_page(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("activeModelParamTab", app_js)
        self.assertIn("data-model-param-tab", app_js)
        self.assertIn("model-param-tab-page", app_js)
        self.assertIn("function setModelParamTab", app_js)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", styles)
        self.assertIn(".model-param-tab-page", styles)


if __name__ == "__main__":
    unittest.main()
