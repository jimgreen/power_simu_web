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


if __name__ == "__main__":
    unittest.main()
