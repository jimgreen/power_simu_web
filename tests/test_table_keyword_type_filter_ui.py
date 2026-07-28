from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TableKeywordTypeFilterUiTest(unittest.TestCase):
    def test_simulator_measurement_and_command_tables_have_keyword_and_type_filters(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        for element_id in (
            "measurementCompareKeywordFilter",
            "measurementCompareTypeFilter",
            "runtimeCommandKeywordFilter",
            "runtimeCommandTypeFilter",
        ):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', script)

        self.assertIn("applyMeasurementCompareTableFilters", script)
        self.assertIn("applyRuntimeCommandTableFilters", script)
        self.assertIn("syncMeasurementCompareTypeFilter", script)
        self.assertIn("syncRuntimeCommandTypeFilter", script)
        self.assertIn("data-table-filter-scope", script)
        self.assertIn(".table-filter-bar", styles)

    def test_trainee_measurement_and_command_tables_have_keyword_and_type_filters(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

        for element_id in (
            "measurementKeywordFilter",
            "measurementTypeFilter",
            "commandKeywordFilter",
            "commandTypeFilter",
        ):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', script)

        self.assertIn("applyMeasurementTableFilters", script)
        self.assertIn("applyCommandTableFilters", script)
        self.assertIn("syncMeasurementTypeFilter", script)
        self.assertIn("syncCommandTypeFilter", script)
        self.assertIn("data-table-filter-scope", script)
        self.assertIn(".table-filter-bar", styles)


if __name__ == "__main__":
    unittest.main()
