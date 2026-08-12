from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SvgRealtimeMeasurementBindingUiTest(unittest.TestCase):
    def _scripts(self):
        return (
            ROOT / "simu/web/simulator/app.js",
            ROOT / "simu/web/trainee/app.js",
        )

    def _helper_source(self, script: str) -> str:
        if "const DIAGRAM_METRIC_MEASUREMENT_TYPES" not in script:
            self.fail("semantic SVG measurement helper table is missing")
        return "const DIAGRAM_METRIC_MEASUREMENT_TYPES" + script.split(
            "const DIAGRAM_METRIC_MEASUREMENT_TYPES",
            1,
        )[1].split("function addDiagramControlAliases", 1)[0]

    def _run_helpers(self, script: str, body: str):
        harness = """
function measurementKey(row) {
  return String(row?.name || `${row?.dev_type || ""}.${row?.dev_name || ""}.${row?.meas_type || ""}`);
}
"""
        result = subprocess.run(
            ["node", "-e", f"{harness}\n{self._helper_source(script)}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_metric_candidates_are_device_specific(self):
        body = """
process.stdout.write(JSON.stringify({
  generator: diagramMetricMeasurementTypes("ACGenerator", "activePower"),
  converter: diagramMetricMeasurementTypes("DCACConverter", "activePower"),
  storage: diagramMetricMeasurementTypes("DCGenerator", "level"),
  storageSocAlias: diagramMetricMeasurementTypes("DCGenerator", "soc"),
  switchStatus: diagramMetricMeasurementTypes("ACBreak", "status"),
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(payload["generator"][0], "P_GEN")
                self.assertEqual(payload["converter"][:2], ["P_AC", "P_DC"])
                self.assertEqual(payload["storage"][:2], ["SOC", "LEVEL"])
                self.assertEqual(payload["storageSocAlias"][:2], ["SOC", "LEVEL"])
                self.assertEqual(payload["switchStatus"][:2], ["STATUS", "RUN_STAT"])

    def test_semantic_binding_uses_role_appropriate_measurement_channels(self):
        body = """
const scadaRow = { dev_type: "ACGenerator", dev_name: "wind-1", meas_type: "P_GEN", value: 12.5 };
const realRow = { dev_type: "ACGenerator", dev_name: "wind-1", meas_type: "P_GEN", value: 13.5 };
const maps = diagramMeasurementMaps({ measurements: { scada: [scadaRow], real: [realRow] } });
const binding = { devType: "ACGenerator", devName: "wind-1", metricType: "activePower" };
const preferred = diagramMetricBindingValue(binding, maps);
const fallbackMaps = diagramMeasurementMaps({ measurements: { scada: [], real: [realRow] } });
const fallback = diagramMetricBindingValue(binding, fallbackMaps);
process.stdout.write(JSON.stringify([preferred?.value ?? null, fallback?.value ?? null]));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    [12.5, 13.5 if path.parent.name == "simulator" else None],
                )

    def test_soc_display_is_percent_without_clamping(self):
        body = """
process.stdout.write(JSON.stringify([
  diagramDisplayRow({ meas_type: "SOC", value: 1.08 }, "level").value,
  diagramDisplayRow({ meas_type: "SOC", value: -0.03 }, "level").value,
  diagramDisplayRow({ meas_type: "SOC", value: 0.5 }, "soc").value,
]));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    [108, -3, 50],
                )

    def test_exported_soc_metric_alias_resolves_live_measurement(self):
        body = """
const socRow = {
  dev_type: "DCGenerator",
  dev_name: "storage-1",
  meas_type: "SOC",
  value: 0.5,
};
const maps = diagramMeasurementMaps({ measurements: { scada: [socRow], real: [] } });
const binding = { devType: "DCGenerator", devName: "storage-1", metricType: "soc" };
const resolved = diagramMetricBindingValue(binding, maps);
process.stdout.write(JSON.stringify({ value: resolved?.value, display: diagramDisplayRow(resolved, binding.metricType)?.value }));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    {"value": 0.5, "display": 50},
                )

    def test_exported_gas_quantity_camel_case_alias_resolves_live_measurement(self):
        body = """
const quantityRow = {
  dev_type: "HydroStorage",
  dev_name: "tank-1",
  meas_type: "gas_quantity",
  value: 999.5,
};
const maps = diagramMeasurementMaps({ measurements: { scada: [quantityRow], real: [] } });
const binding = { devType: "HydroStorage", devName: "tank-1", metricType: "gasQuantity" };
const resolved = diagramMetricBindingValue(binding, maps);
process.stdout.write(JSON.stringify({
  candidates: diagramMetricMeasurementTypes(binding.devType, binding.metricType),
  value: resolved?.value ?? null,
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    {"candidates": ["GAS_QUANTITY"], "value": 999.5},
                )

    def test_exported_svg_semantic_placeholders_are_compiled_and_cached(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertTrue(
                    'querySelectorAll("[dev] [mt]")' in script,
                    "exported SVG metric placeholders are not queried",
                )
                self.assertTrue(
                    "function compileDiagramMetricBindings" in script,
                    "semantic SVG bindings are not compiled",
                )
                self.assertTrue(
                    "diagramMetricBindingCache" in script,
                    "compiled SVG bindings are not cached",
                )
                self.assertTrue(
                    (
                        "diagramMetricBindingValue(binding, maps, diagramDisplayPreferences.measurementSource)" in script
                        if path.parent.name == "simulator"
                        else "diagramMetricBindingValue(binding, maps)" in script
                    ),
                    "semantic bindings are not resolved during refresh",
                )

    def test_offline_state_covers_retired_and_dead_island_devices(self):
        body = """
process.stdout.write(JSON.stringify([
  diagramDeviceIsOffline({ run_stat: 0, dead_island: false }),
  diagramDeviceIsOffline({ run_stat: 1, dead_island: true }),
  diagramDeviceIsOffline({ run_stat: 1, dead_island: false }),
]));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    [True, True, False],
                )

    def test_svg_refresh_applies_compact_device_operating_states(self):
        styles = (
            ROOT / "simu/web/simulator/styles.css",
            ROOT / "simu/web/trainee/styles.css",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertIn("function updateDiagramDeviceVisualStates", script)
                self.assertIn("snapshot.device_states", script)
                self.assertIn('classList.toggle("is-diagram-offline"', script)
                self.assertIn('params.set("device_states", pageNeedsDeviceStates(page) ? "1" : "0");', script)
        for path in styles:
            with self.subTest(styles=path.parent.name):
                css = path.read_text(encoding="utf-8")
                self.assertIn(".is-diagram-offline", css)
                self.assertIn("grayscale(1)", css)
                self.assertIn(".is-diagram-offline.is-diagram-selected", css)


if __name__ == "__main__":
    unittest.main()
