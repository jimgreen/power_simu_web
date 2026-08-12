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
        for label in ("电源曲线", "氢源曲线", "热源曲线"):
            self.assertIn(label, script)
        self.assertIn("function curveSourceCatalog", script)
        self.assertIn("...allSourceCurveKeys()", script)
        self.assertIn('String(key).startsWith("source:")', script)
        self.assertIn('data-curve-tree-type="source"', script)
        self.assertIn("state.curveSeries[source.key]", script)
        self.assertIn("keysToSave", script)

    def test_trainee_source_curves_are_read_only_series(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        tree_body = javascript_function_body(
            script,
            "renderCurveDisplayTree",
            "renderCurveDisplayModeControls",
        )
        diagnostics_body = javascript_function_body(
            script,
            "renderRenewableStrategyDiagnostics",
            "renewableControlLogs",
        )
        for label in ("电源曲线", "氢源曲线", "热源曲线"):
            self.assertIn(label, script)
        self.assertIn("function curveDisplaySourceCatalog", script)
        self.assertIn("...curveDisplaySourceKeys(snapshot)", script)
        self.assertIn('String(key).startsWith("source:")', script)
        self.assertIn("sourceGroups.map", tree_body)
        self.assertIn('data-curve-display-tree-type="source"', tree_body)
        self.assertNotIn("sourceGroups.map", diagnostics_body)

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
        self.assertIn("data-curve-tree-toggle", simulator_tree)
        self.assertIn("curveTreeGroupCollapsed", simulator_tree)
        self.assertIn("aria-expanded", simulator_tree)
        self.assertIn("function toggleCurveDisplayTreeGroup", trainee)
        self.assertIn("data-curve-display-tree-toggle", trainee_tree)
        self.assertIn("curveDisplayTreeGroupCollapsed", trainee_tree)
        self.assertIn("aria-expanded", trainee_tree)
        self.assertIn("localStorage.setItem(CURVE_TREE_COLLAPSE_KEY", simulator)
        self.assertIn("localStorage.setItem(CURVE_DISPLAY_TREE_COLLAPSE_KEY", trainee)
        self.assertIn('const groupKey = `load:${group.key}`', simulator_tree)
        self.assertIn('const groupKey = `load:${group.key}`', trainee_tree)
        self.assertIn('data-curve-family="${escapeHtml(groupKey)}"', simulator_tree)
        self.assertIn('data-curve-display-family="${escapeHtml(groupKey)}"', trainee_tree)


if __name__ == "__main__":
    unittest.main()
