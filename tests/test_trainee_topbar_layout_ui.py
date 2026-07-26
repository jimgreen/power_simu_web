from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeTopbarLayoutUiTest(unittest.TestCase):
    def test_topbar_shows_import_before_model_name_without_selector(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        topbar = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        toolbar = topbar.split('<div class="model-toolbar">', 1)[1].split("</div>", 1)[0]

        self.assertNotIn("显示模型", topbar)
        self.assertNotIn('id="modelSelector"', topbar)
        self.assertNotIn('class="model-switcher"', topbar)
        self.assertLess(toolbar.index('id="importDefinitionsButton"'), toolbar.index('id="activeModelName"'))
        self.assertLess(toolbar.index('id="activeModelName"'), toolbar.index('id="traineeRunToggle"'))

        topbar_rule = css.split(".topbar {", 1)[1].split("}", 1)[0]
        self.assertIn("justify-content: flex-start", topbar_rule)
        toolbar_rule = css.split(".model-toolbar {", 1)[1].split("}", 1)[0]
        self.assertIn("margin-left: 0", toolbar_rule)
        self.assertIn("flex: 0 1 auto", toolbar_rule)
        self.assertIn("justify-content: flex-start", toolbar_rule)
        self.assertIn("gap: 12px", toolbar_rule)
        clock_rule = css.split(".clock-strip {", 1)[1].split("}", 1)[0]
        self.assertIn("margin-left: auto", clock_rule)
        self.assertIn(".active-model-name {", css)
        active_model_rule = css.split(".active-model-name {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex", active_model_rule)
        self.assertIn("min-width: 96px", active_model_rule)
        self.assertIn("text-overflow: ellipsis", active_model_rule)

        self.assertIn('const selector = $("modelSelector");', app_js)
        self.assertIn("if (selector) {", app_js)


if __name__ == "__main__":
    unittest.main()
