from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeCurveDisplayUiTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        self.script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        self.styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

    def test_trainee_has_readonly_curve_display_page(self):
        self.assertIn('data-nav-page="curves"', self.html)
        self.assertIn("曲线显示", self.html)
        self.assertIn('data-page="curves"', self.html)
        self.assertIn('id="curveDisplayTree"', self.html)
        self.assertIn('id="curveDisplayTreeFilter"', self.html)
        self.assertIn('id="curveDisplayChart"', self.html)
        self.assertIn('id="curveDisplayTable"', self.html)
        self.assertIn("只读", self.html)

    def test_curve_display_reuses_simulator_curve_layout_without_edit_controls(self):
        self.assertIn(".curve-page-layout", self.styles)
        self.assertIn(".curve-workspace", self.styles)
        self.assertIn(".curve-table-wrap", self.styles)
        self.assertIn("function renderCurveDisplay", self.script)
        self.assertIn("function renderCurveDisplayTree", self.script)
        self.assertIn("function curveDisplayTreeItemMatches", self.script)
        self.assertIn('data-curve-medium="${escapeHtml(item.family)}"', self.script)
        self.assertIn("function drawCurveDisplay", self.script)
        self.assertIn("function renderCurveDisplayTable", self.script)
        self.assertIn("data-curve-display-tree-type", self.script)
        self.assertIn("供能曲线", self.script)
        self.assertIn("电源曲线", self.script)
        self.assertIn("氢源曲线", self.script)
        self.assertIn("热源曲线", self.script)
        self.assertIn('family === "electric"', self.script)
        self.assertIn('family === "hydrogen"', self.script)
        self.assertIn('family === "heat"', self.script)
        self.assertNotIn('id="saveCurves"', self.html)
        self.assertNotIn('id="randomCurves"', self.html)
        self.assertNotIn('id="generateDenseCurves"', self.html)
        self.assertNotIn('contenteditable="true"', self.script)

    def test_curve_switching_reuses_linear_resampling_results(self):
        self.assertIn("curveDisplaySeriesCache: new WeakMap()", self.script)
        self.assertIn("function curveDisplayPointPairs", self.script)
        self.assertIn("let pairIndex = 0", self.script)
        self.assertIn("while (pairIndex < pairs.length - 2", self.script)
        self.assertIn("function curveDisplaySeriesMap", self.script)
        self.assertIn("drawCurveDisplay(snapshot, seriesByKey)", self.script)
        self.assertIn("renderCurveDisplayTable(snapshot, false, seriesByKey)", self.script)
        self.assertNotIn("function interpolateCurveDisplay", self.script)


if __name__ == "__main__":
    unittest.main()
