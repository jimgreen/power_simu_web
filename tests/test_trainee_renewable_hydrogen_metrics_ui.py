from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableHydrogenMetricsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_hydrogen_statistic_tab_has_unique_aggregate_metrics(self):
        self.assertIn('data-renewable-metric-tab="hydrogen"', self.html)
        self.assertIn('data-renewable-metric-pane="hydrogen"', self.html)
        expected_ids = (
            "renewableElectrolyzerCurrentKw",
            "renewableElectrolyzerTargetKw",
            "renewableElectrolyzerFlowCurrentNm3h",
            "renewableElectrolyzerFlowTargetNm3h",
            "renewableFuelCellCurrentKw",
            "renewableFuelCellTargetKw",
            "renewableFuelCellFlowCurrentNm3h",
            "renewableFuelCellFlowTargetNm3h",
            "renewableHydrogenStoragePressureMpa",
            "renewableHydrogenStoragePressureLowGuardMpa",
            "renewableHydrogenStoragePressureHighGuardMpa",
            "renewableHydrogenStorageGasQuantityNm3",
            "renewableHydrogenStorageSoc",
            "renewableHydrogenStorageFlowNm3h",
        )
        for metric_id in expected_ids:
            with self.subTest(metric_id=metric_id):
                self.assertEqual(self.html.count(f'id="{metric_id}"'), 1)
                self.assertIn(metric_id, self.script)

    def test_curve_tree_has_independent_hydrogen_scope_and_device_groups(self):
        self.assertIn('{ key: "hydrogen", label: "氢能" }', self.script)
        for device_label in ("电制氢", "燃料电池", "储氢罐"):
            self.assertIn(f'deviceLabel: "{device_label}"', self.script)
        for group in ("hydrogen-electrolyzer", "hydrogen-fuel-cell", "hydrogen-storage"):
            self.assertIn(f'group: "{group}"', self.script)
        default_block = self.script.split(
            "const RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES = new Set([",
            1,
        )[1].split("]);", 1)[0]
        self.assertNotRegex(default_block, r"electrolyzer|fuelCell|hydrogenStorage")

    def test_parameter_dialog_is_four_accessible_pages_and_keeps_all_inputs_once(self):
        expected_tabs = {
            "runtime": "运行与步长",
            "protection": "储能与保护",
            "hydrogen": "氢能与控制",
            "optimization": "优化与求解",
        }
        for key, label in expected_tabs.items():
            with self.subTest(key=key):
                self.assertRegex(
                    self.html,
                    rf'role="tab"[^>]+data-renewable-parameter-tab="{key}"[^>]*>{label}</button>',
                )
                self.assertIn(f'data-renewable-parameter-pane="{key}"', self.html)
        dialog = self.html.split('id="renewableControlParametersDialog"', 1)[1].split(
            'id="storagePowerDeratingDialog"',
            1,
        )[0]
        input_ids = re.findall(r'<input id="([^"]+)"', dialog)
        self.assertEqual(len(input_ids), len(set(input_ids)))
        self.assertIn("function renderRenewableControlParameterTabs", self.script)
        self.assertIn("renderRenewableControlParameterTabs(\"runtime\")", self.script)
        self.assertIn(".renewable-control-parameter-pane[hidden]", self.styles)
        self.assertIn("overflow-y: auto;", self.styles)

    def test_hydrogen_parameter_page_uses_balanced_controls_and_one_scroll_region(self):
        self.assertIn(
            'class="renewable-hydrogen-overview-field renewable-control-toggle-field"',
            self.html,
        )
        self.assertIn('class="renewable-control-parameter-footer"', self.html)
        dialog_style = re.search(
            r"\.renewable-control-parameters-dialog\s*\{(?P<body>[^}]*)\}",
            self.styles,
        )
        self.assertIsNotNone(dialog_style)
        dialog_body = dialog_style.group("body")
        self.assertRegex(dialog_body, r"(?m)^\s*height:\s*auto;")
        self.assertRegex(dialog_body, r"(?m)^\s*overflow:\s*hidden;")
        self.assertNotRegex(dialog_body, r"(?m)^\s*height:\s*min\(")
        self.assertRegex(
            self.styles,
            r"\.renewable-hydrogen-power-settings\s*\{[^}]*"
            r"grid-column:\s*auto;[^}]*"
            r"grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);",
        )
        self.assertRegex(
            self.styles,
            r'input\[type="checkbox"\]\s*\{[^}]*width:\s*42px;[^}]*height:\s*22px;',
        )


if __name__ == "__main__":
    unittest.main()
