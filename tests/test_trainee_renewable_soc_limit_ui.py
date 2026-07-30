import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableSocLimitUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_parameter_panel_has_converter_soc_limit_dialog(self):
        for element_id in (
            "converterSocLimitButton",
            "converterSocLimitDialog",
            "converterSocLimitRows",
            "converterSocLimitMessage",
            "converterSocLimitCancel",
            "converterSocLimitSave",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("变流器 SOC 限额", self.html)

    def test_converter_soc_limit_dialog_is_bounded_and_scrollable(self):
        self.assertIn(".converter-soc-limit-dialog", self.styles)
        rows_block = self.styles.split(".converter-soc-limit-rows {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto;", rows_block)
        row_block = self.styles.split(".converter-soc-limit-row {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns:", row_block)

    def test_browser_state_uses_backend_converter_soc_limits(self):
        self.assertIn("DEFAULT_CONVERTER_SOC_POWER_LIMITS", self.script)
        self.assertIn("converterSocPowerLimits: [...DEFAULT_CONVERTER_SOC_POWER_LIMITS]", self.script)
        self.assertIn("settings.converterSocPowerLimits", self.script)
        self.assertIn("function normalizeConverterSocPowerLimits", self.script)

    def test_dialog_renders_ten_bands_and_rejects_decreasing_limits(self):
        self.assertIn("function renderConverterSocLimitRows", self.script)
        self.assertIn("function readConverterSocLimitDraft", self.script)
        self.assertIn("Array.from({ length: 10 }", self.script)
        self.assertIn("Array.from({ length: 11 }", self.script)
        self.assertIn("limits[index] < limits[index - 1]", self.script)

    def test_dialog_saves_the_complete_schedule_through_backend_action(self):
        self.assertIn("async function saveConverterSocLimits", self.script)
        save_block = self.script.split("async function saveConverterSocLimits", 1)[1].split(
            "function renderClock",
            1,
        )[0]
        self.assertIn('runRenewableControlAction("update_settings"', save_block)
        self.assertIn("converterSocPowerLimits: limits", save_block)


if __name__ == "__main__":
    unittest.main()
