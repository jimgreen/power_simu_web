from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeTopbarLayoutUiTest(unittest.TestCase):
    def test_topbar_shows_model_management_selector_name_and_receive_toggle(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        topbar = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        toolbar = topbar.split('<div class="model-toolbar">', 1)[1].split("</div>", 1)[0]

        self.assertNotIn("显示模型", topbar)
        self.assertIn('class="model-switcher trainee-model-switcher"', topbar)
        self.assertIn('id="modelSelector"', topbar)
        self.assertIn('id="modelManagementButton"', toolbar)
        self.assertNotIn('id="importDefinitionsButton"', toolbar)
        self.assertLess(toolbar.index('id="modelManagementButton"'), toolbar.index('id="modelSelector"'))
        self.assertLess(toolbar.index('id="modelSelector"'), toolbar.index('id="activeModelName"'))
        self.assertLess(toolbar.index('id="activeModelName"'), toolbar.index('id="traineeRunToggle"'))

        topbar_rule = css.split(".topbar {", 1)[1].split("}", 1)[0]
        self.assertIn("justify-content: flex-start", topbar_rule)
        toolbar_rule = css.split(".model-toolbar {", 1)[1].split("}", 1)[0]
        self.assertIn("margin-left: 0", toolbar_rule)
        self.assertIn("flex: 0 1 auto", toolbar_rule)
        self.assertIn("justify-content: flex-start", toolbar_rule)
        self.assertIn("gap: 12px", toolbar_rule)
        model_switcher_rule = css.split(".model-switcher {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex", model_switcher_rule)
        self.assertIn("align-items: center", model_switcher_rule)
        model_switcher_select_rule = css.split(".model-switcher select {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 150px", model_switcher_select_rule)
        clock_rule = css.split(".clock-strip {", 1)[1].split("}", 1)[0]
        self.assertIn("margin-left: auto", clock_rule)
        self.assertIn(".active-model-name {", css)
        active_model_rule = css.split(".active-model-name {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex", active_model_rule)
        self.assertIn("min-width: 96px", active_model_rule)
        self.assertIn("text-overflow: ellipsis", active_model_rule)

        self.assertIn('const selector = $("modelSelector");', app_js)
        self.assertIn("selector.disabled = models.length <= 1;", app_js)
        self.assertNotIn("selector.disabled = state.receiveMode || models.length <= 1;", app_js)
        self.assertIn("if (selector) {", app_js)
        self.assertIn('$("modelManagementButton").addEventListener("click", openModelManagementDialog);', app_js)

    def test_model_management_dialog_supports_crud_actions(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="modelManagementDialog"', html)
        self.assertIn("<h2 id=\"modelManagementTitle\">模型管理</h2>", html)
        self.assertIn('id="modelManagementList"', html)
        self.assertIn('id="importDefinitionsButton"', html)
        self.assertIn('data-model-context-action="export"', html)
        self.assertIn('data-model-context-action="clone"', html)
        self.assertIn('data-model-context-action="update"', html)
        self.assertIn('data-model-context-action="delete"', html)
        self.assertIn('id="importModelDialog"', html)
        self.assertIn('id="updateModelDialog"', html)
        self.assertIn('id="cloneModelDialog"', html)

        self.assertIn("openModelManagementDialog", app_js)
        self.assertIn("renderModelManagementList", app_js)
        self.assertIn("handleModelContextMenuAction", app_js)
        self.assertIn("selectedManagementModelId", app_js)
        self.assertIn("openImportModelDialog", app_js)
        self.assertIn("openUpdateModelDialog", app_js)
        self.assertIn("cloneManagedModel", app_js)
        self.assertIn("deleteManagedModel", app_js)
        self.assertIn('api("/api/models/import-definitions"', app_js)
        self.assertIn("create_model: true", app_js)
        self.assertIn('api("/api/models/clone"', app_js)
        self.assertIn('api("/api/models/delete"', app_js)
        self.assertIn('api("/api/export-definitions?format=json', app_js)


if __name__ == "__main__":
    unittest.main()
