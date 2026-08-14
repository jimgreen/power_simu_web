from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelDiagramUiTest(unittest.TestCase):
    def test_simulator_and_trainee_have_model_diagram_pages(self):
        simulator_html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        simulator_js = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

        for label, html, script in (
            ("simulator", simulator_html, simulator_js),
            ("trainee", trainee_html, trainee_js),
        ):
            with self.subTest(app=label):
                self.assertIn('data-nav-page="diagram"', html)
                self.assertIn('data-page="diagram"', html)
                self.assertIn('id="modelDiagramCanvas"', html)
                self.assertIn('"/diagram": "diagram"', script)
                self.assertIn('"diagram"', script.split("const STATIC_SNAPSHOT_KEYS", 1)[1].split("];", 1)[0])
                self.assertIn("function renderModelDiagramPage", script)
                self.assertIn("function sanitizeDiagramSvg", script)
                self.assertIn("function updateDiagramRealtimeBindings", script)
                self.assertIn("data-meas-name", script)
                self.assertIn("data-real-name", script)
                self.assertIn("data-control-name", script)
                render_block = script.split("function renderModelDiagramPage", 1)[1].split("\n}", 1)[0]
                self.assertIn("const activeSnapshot = snapshot || {}", render_block)

    def test_model_diagram_page_uses_snapshot_measurements_for_realtime_binding(self):
        simulator_js = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

        for label, script in (("simulator", simulator_js), ("trainee", trainee_js)):
            with self.subTest(app=label):
                binding_block = script.split("function updateDiagramRealtimeBindings", 1)[1].split(
                    "function renderModelDiagramPage",
                    1,
                )[0]
                self.assertIn("diagramMeasurementMaps(snapshot)", binding_block)
                self.assertIn("diagramControlMap(snapshot)", binding_block)
                self.assertIn("diagramRealtimeBindings(container)", binding_block)
                helper_block = script.split("function diagramRealtimeBindings", 1)[1].split(
                    "function diagramBindingValue",
                    1,
                )[0]
                self.assertIn("querySelectorAll", helper_block)
                self.assertIn("diagramBindingValue", script)


if __name__ == "__main__":
    unittest.main()
