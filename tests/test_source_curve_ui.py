from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def javascript_function_body(script: str, name: str, next_name: str) -> str:
    start_marker = f"function {name}"
    end_marker = f"function {next_name}"
    start = script.index(start_marker)
    end = script.index(end_marker, start)
    return script[start:end]


class SourceCurveUiTest(unittest.TestCase):
    def test_load_curves_are_grouped_by_explicit_model_blocks(self):
        simulator = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        for script in (simulator, trainee):
            for label in ("电负荷曲线", "氢负荷曲线", "热负荷曲线"):
                self.assertIn(label, script)
            self.assertIn('["ACLoad", "DCLoad"]', script)
            self.assertIn('["HydroLoad"]', script)
            self.assertIn('["HeatLoad"]', script)

        self.assertIn("semanticDeviceModelBlock", simulator)
        self.assertIn("loadCurveFamilyForBlock", simulator)
        self.assertIn("model_block", trainee)
        self.assertIn("curveDisplayLoadFamilyForBlock", trainee)

    def test_load_curve_units_and_values_follow_the_energy_medium(self):
        simulator = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        for script in (simulator, trainee):
            self.assertIn('unit: "Nm³/h"', script)
            self.assertIn('valueKey: "flow_set"', script)
            self.assertIn('valueKey: "heat_power"', script)
        self.assertIn("curveFallbackValue(loadCurveKey(dev.dev_name))", simulator)
        self.assertIn('dev.family === "electric"', simulator)

    def test_simulator_source_curves_are_structured_editable_series(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        tree_body = javascript_function_body(script, "renderCurveTree", "renderCurveTreeLoading")
        self.assertIn('"供能曲线"', tree_body)
        for label in ("电源曲线", "氢源曲线", "热源曲线"):
            self.assertIn(label, script)
        self.assertIn("function curveSourceCatalog", script)
        self.assertIn("...allSourceCurveKeys()", script)
        self.assertIn('String(key).startsWith("source:")', script)
        self.assertIn('data-curve-tree-type="${escapeHtml(type)}"', script)
        self.assertIn('data-curve-family="${escapeHtml(group.key)}"', tree_body)
        self.assertIn("curveSourceCatalog().map", tree_body)
        self.assertIn("group.visibleItems.map", tree_body)
        self.assertIn('data-curve-medium="${escapeHtml(item.family)}"', script)
        self.assertNotIn("tree-subgroup", tree_body)
        self.assertNotIn("tree-grandchildren", tree_body)
        self.assertIn("state.curveSeries[source.key]", script)
        self.assertIn("keysToSave", script)

    def test_trainee_source_curves_are_read_only_series(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        tree_body = javascript_function_body(
            script,
            "renderCurveDisplayTree",
            "renderCurveDisplayModeControls",
        )
        self.assertIn('"供能曲线"', tree_body)
        for label in ("电源曲线", "氢源曲线", "热源曲线"):
            self.assertIn(label, script)
        self.assertIn("function curveDisplaySourceCatalog", script)
        self.assertIn("...curveDisplaySourceKeys(snapshot)", script)
        self.assertIn('String(key).startsWith("source:")', script)
        self.assertIn("curveDisplaySourceCatalog(snapshot).map", tree_body)
        self.assertIn("group.visibleItems.map", tree_body)
        self.assertIn('data-curve-display-tree-type="${escapeHtml(type)}"', script)
        self.assertIn('data-curve-display-family="${escapeHtml(group.key)}"', tree_body)
        self.assertIn('data-curve-medium="${escapeHtml(item.family)}"', script)
        self.assertNotIn("tree-subgroup", tree_body)
        self.assertNotIn("tree-grandchildren", tree_body)

    def test_trainee_static_snapshot_retains_initialized_curves(self):
        exchange = (ROOT / "simu" / "trainee_exchange.py").read_text(encoding="utf-8")
        self.assertIn(
            'CONTROL_STATIC_FIELDS = ("definitions", "settings", "device_parameters", "curves")',
            exchange,
        )

    def test_curve_tree_groups_can_be_expanded_and_collapsed_without_changing_selection(self):
        simulator = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        simulator_tree = javascript_function_body(simulator, "renderCurveTree", "renderCurveTreeLoading")
        trainee_tree = javascript_function_body(
            trainee,
            "renderCurveDisplayTree",
            "renderCurveDisplayModeControls",
        )

        self.assertIn("function toggleCurveTreeGroup", simulator)
        self.assertIn("data-curve-tree-toggle", simulator)
        self.assertIn("curveTreeGroupCollapsed", simulator_tree)
        self.assertIn("aria-expanded", simulator)
        self.assertIn("function toggleCurveDisplayTreeGroup", trainee)
        self.assertIn("data-curve-display-tree-toggle", trainee)
        self.assertIn("curveDisplayTreeGroupCollapsed", trainee_tree)
        self.assertIn("aria-expanded", trainee)
        self.assertIn("localStorage.setItem(CURVE_TREE_COLLAPSE_KEY", simulator)
        self.assertIn("localStorage.setItem(CURVE_DISPLAY_TREE_COLLAPSE_KEY", trainee)
        self.assertIn('{ key: "environment", label: "环境曲线"', simulator_tree)
        self.assertIn('{ key: "load", label: "负荷曲线"', simulator_tree)
        self.assertIn('{ key: "source", label: "供能曲线"', simulator_tree)
        self.assertIn('{ key: "environment", label: "环境曲线"', trainee_tree)
        self.assertIn('{ key: "load", label: "负荷曲线"', trainee_tree)
        self.assertIn('{ key: "source", label: "供能曲线"', trainee_tree)
        self.assertNotIn('`load:${group.key}`', simulator_tree)
        self.assertNotIn('`load:${group.key}`', trainee_tree)
        self.assertNotIn('`source:${group.key}`', simulator_tree)
        self.assertNotIn('`source:${group.key}`', trainee_tree)

    def test_curve_lists_match_the_two_level_device_tree_interaction(self):
        simulator_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        simulator = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        simulator_tree = javascript_function_body(simulator, "renderCurveTree", "renderCurveTreeLoading")
        trainee_tree = javascript_function_body(trainee, "renderCurveDisplayTree", "renderCurveDisplayModeControls")

        self.assertIn('id="curveTreeFilter"', simulator_html)
        self.assertIn('id="curveDisplayTreeFilter"', trainee_html)
        self.assertIn('placeholder="过滤曲线"', simulator_html)
        self.assertIn('placeholder="过滤曲线"', trainee_html)
        self.assertIn("curveTreeItemMatches", simulator_tree)
        self.assertIn("curveDisplayTreeItemMatches", trainee_tree)
        self.assertIn('class="tree-node tree-type', simulator)
        self.assertIn('class="tree-node tree-type', trainee)
        self.assertIn('class="tree-node tree-child', simulator)
        self.assertIn('class="tree-node tree-child', trainee)
        self.assertNotIn("tree-subgroup", simulator_tree)
        self.assertNotIn("tree-subgroup", trainee_tree)
        self.assertNotIn("tree-grandchildren", simulator_tree)
        self.assertNotIn("tree-grandchildren", trainee_tree)

    def test_curve_items_use_plain_click_for_single_selection_and_modified_click_for_multi_selection(self):
        simulator = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        simulator_select = javascript_function_body(simulator, "selectCurveTreeButton", "resetCurveTreePointerSelection")
        trainee_select = javascript_function_body(trainee, "selectCurveDisplayButton", "curveDisplaySelectedLabel")
        simulator_selected = javascript_function_body(simulator, "selectedCurveKeys", "curveHiddenSet")
        trainee_selected = javascript_function_body(trainee, "selectedCurveDisplayKeys", "curveDisplayHiddenSet")

        for body in (simulator_select, trainee_select):
            self.assertIn("const selectedSet = new Set(selected)", body)
            self.assertIn("event?.ctrlKey || event?.metaKey || event?.shiftKey", body)
            self.assertIn("multiSelect", body)
            self.assertIn("selected.filter", body)
            self.assertIn("[...selected", body)
            self.assertIn("[key]", body)
        self.assertIn("selectCurveTreeButton(curveTreeButton, event)", simulator)
        self.assertIn("selectCurveDisplayButton(curveDisplayButton, selectionEvent)", trainee)
        self.assertIn("event.button !== 0 || !(event.ctrlKey || event.metaKey || event.shiftKey)", simulator)
        self.assertNotIn("selectCurveTreeButton(curveTreeButton);", simulator)
        self.assertNotIn("selectCurveDisplayButton(curveDisplayTreeToggle)", trainee)
        self.assertNotIn('selected.push("wind_speed_mps")', simulator_selected)
        self.assertNotIn('selected.push("wind_speed_mps")', trainee_selected)
        self.assertIn('ctx.fillText("未选择曲线"', simulator)
        self.assertIn('ctx.fillText("未选择曲线"', trainee)


if __name__ == "__main__":
    unittest.main()
