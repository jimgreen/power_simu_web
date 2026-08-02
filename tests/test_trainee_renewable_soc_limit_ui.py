import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableSocLimitUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_converter_soc_segmented_limit_ui_is_removed(self):
        for removed_text in (
            "converterSocLimitButton",
            "converterSocLimitDialog",
            "converterSocLimitRows",
            "converterSocPowerLimits",
            "DEFAULT_CONVERTER_SOC_POWER_LIMITS",
            "变流器 SOC 限额",
            "SOC分档限额",
        ):
            with self.subTest(removed_text=removed_text):
                self.assertNotIn(removed_text, self.html)
                self.assertNotIn(removed_text, self.script)

    def test_converter_soc_segmented_limit_styles_are_removed(self):
        self.assertNotIn(".converter-soc-limit", self.styles)
        self.assertNotIn(".renewable-soc-limit-entry", self.styles)

    def test_storage_charge_discharge_derating_curve_editor_is_available(self):
        for required_text in (
            'id="storagePowerDeratingButton"',
            'id="storagePowerDeratingDialog"',
            'id="storageChargeDeratingRows"',
            'id="storageDischargeDeratingRows"',
            'id="storagePowerDeratingMessage"',
            'id="saveStoragePowerDerating"',
            "储能充放电降额",
            "充电功率上限",
            "放电功率上限",
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.html)

    def test_storage_derating_curves_are_loaded_validated_and_persisted_as_ratios(self):
        for required_text in (
            "DEFAULT_STORAGE_CHARGE_DERATING_CURVE",
            "DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE",
            "storageChargeDeratingCurve",
            "storageDischargeDeratingCurve",
            "renderStoragePowerDeratingRows",
            "validateStoragePowerDeratingCurves",
            "readStoragePowerDeratingCurve",
            'runRenewableControlAction("update_settings"',
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, self.script)

    def test_storage_derating_editor_uses_two_semantic_tables(self):
        self.assertEqual(
            self.html.count('<table class="storage-power-derating-table">'),
            2,
        )
        self.assertIn(
            '<tbody id="storageChargeDeratingRows" class="storage-power-derating-rows"></tbody>',
            self.html,
        )
        self.assertIn(
            '<tbody id="storageDischargeDeratingRows" class="storage-power-derating-rows"></tbody>',
            self.html,
        )
        self.assertIn('<tr class="storage-power-derating-row"', self.script)
        self.assertIn("<td>", self.script)
        self.assertNotIn('<div class="storage-power-derating-row"', self.script)

    def test_storage_derating_editor_has_scoped_responsive_styles(self):
        for selector in (
            ".storage-power-derating-dialog",
            ".storage-power-derating-grid",
            ".storage-power-derating-table-wrap",
            ".storage-power-derating-table",
            ".storage-power-derating-rows",
            ".storage-power-derating-row",
            ".storage-power-derating-input",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.styles)


if __name__ == "__main__":
    unittest.main()
