from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeTopbarLayoutUiTest(unittest.TestCase):
    def test_overview_status_keeps_simulator_model_metric_on_one_desktop_row(self):
        css = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

        metric_rule = css.split(".trainee-status-metrics {", 1)[1].split("}", 1)[0]
        source_rule = css.split(".trainee-status-metrics div:first-child {", 1)[1].split("}", 1)[0]

        self.assertIn("grid-template-columns: repeat(7, minmax(78px, 1fr))", metric_rule)
        self.assertIn("grid-column: span 2", source_rule)

    def test_topbar_shows_model_management_selector_initialization_and_receive_controls(self):
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
        self.assertLess(toolbar.index('id="activeModelName"'), toolbar.index('id="modelInitializeButton"'))
        self.assertLess(toolbar.index('id="modelInitializeButton"'), toolbar.index('id="traineeRunToggle"'))
        self.assertIn('>模型初始化</button>', toolbar)
        self.assertIn('>启动接收</button>', toolbar)

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
        self.assertIn('$("modelInitializeButton").addEventListener("click", openReceiveLinkDialog);', app_js)

    def test_model_management_uses_name_only_model_slots_without_manual_definition_import(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="modelManagementDialog"', html)
        self.assertIn("<h2 id=\"modelManagementTitle\">模型管理</h2>", html)
        self.assertIn('id="modelManagementList"', html)
        self.assertIn('id="newModelButton"', html)
        self.assertNotIn('id="importDefinitionsButton"', html)
        self.assertNotIn('id="definitionArchiveInput"', html)
        self.assertIn('data-model-context-action="lifecycle"', html)
        self.assertIn('data-model-context-action="export"', html)
        self.assertIn('data-model-context-action="clone"', html)
        self.assertNotIn('data-model-context-action="update"', html)
        self.assertIn('data-model-context-action="delete"', html)
        self.assertIn('id="newModelDialog"', html)
        self.assertIn("<h2 id=\"newModelTitle\">新建模型</h2>", html)
        self.assertIn('id="newModelName"', html)
        self.assertNotIn('id="newModelFileInput"', html)
        self.assertNotIn('id="selectNewModelFile"', html)
        self.assertNotIn("选择定义包", html)
        self.assertNotIn('id="newModelSvgInput"', html)
        self.assertNotIn('id="importModelDialog"', html)
        self.assertNotIn('id="updateModelDialog"', html)
        self.assertNotIn('id="updateModelSvgInput"', html)
        self.assertIn("模型定义将在模型初始化时自动从模拟台获取", html)
        self.assertIn('id="cloneModelDialog"', html)

        self.assertIn("openModelManagementDialog", app_js)
        self.assertIn("renderModelManagementList", app_js)
        self.assertIn("handleModelContextMenuAction", app_js)
        self.assertIn("handleSelectedManagementModelLifecycle", app_js)
        self.assertIn("selectedManagementModelId", app_js)
        self.assertIn("openNewModelDialog", app_js)
        self.assertIn("createNewModelSlot", app_js)
        self.assertIn('api("/api/trainee/models/create"', app_js)
        self.assertNotIn("pendingNewModelFile", app_js)
        self.assertNotIn("openImportModelDialog", app_js)
        self.assertNotIn("openUpdateModelDialog", app_js)
        self.assertIn("cloneManagedModel", app_js)
        self.assertIn("deleteManagedModel", app_js)
        self.assertNotIn('api("/api/models/import-definitions"', app_js)
        self.assertIn('api("/api/models/clone"', app_js)
        self.assertIn('api("/api/models/delete"', app_js)
        self.assertIn('api("/api/export-definitions?format=json', app_js)

    def test_model_management_lifecycle_state_drives_context_action(self):
        app_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

        state_block = app_js.split("function modelManagementState(model)", 1)[1].split("\n}", 1)[0]
        self.assertIn('if (!context.modelInitialized) return "uninitialized"', state_block)
        self.assertIn('if (context.receiveMode) return "received"', state_block)
        self.assertIn('return "stopped"', state_block)

        text_block = app_js.split("function modelManagementStateText(value)", 1)[1].split("\n}", 1)[0]
        self.assertIn('received: "已接收"', text_block)
        self.assertIn('uninitialized: "未初始化"', text_block)
        self.assertIn('stopped: "已停止"', text_block)

        menu_block = app_js.split("function updateModelContextMenuActions()", 1)[1].split("\n}", 1)[0]
        self.assertIn('? "初始化"', menu_block)
        self.assertIn('lifecycleState === "received" ? "停止接收" : "启动接收"', menu_block)
        self.assertIn("state.modelLifecycleOperationActive", menu_block)
        self.assertIn('.model-state-pill[data-state="uninitialized"]', css)

        receive_block = app_js.split("async function setManagedModelReceiveActive", 1)[1].split("\n}", 1)[0]
        self.assertIn("await setTraineeReceiveActive(target.id, active)", receive_block)
        self.assertIn("target.id === state.activeModelId", receive_block)


if __name__ == "__main__":
    unittest.main()
