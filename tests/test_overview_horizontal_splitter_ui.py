from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewHorizontalSplitterUiTest(unittest.TestCase):
    def app_sources(self, app_name: str) -> tuple[str, str, str]:
        app_root = ROOT / "simu" / "web" / app_name
        return (
            (app_root / "index.html").read_text(encoding="utf-8"),
            (app_root / "app.js").read_text(encoding="utf-8"),
            (app_root / "styles.css").read_text(encoding="utf-8"),
        )

    def assert_horizontal_splitter(self, app_name: str, storage_key: str) -> None:
        html, script, styles = self.app_sources(app_name)

        self.assertIn('id="overviewBottomColumnSplitter"', html)
        self.assertIn('class="overview-bottom-column-splitter"', html)
        self.assertIn('aria-orientation="vertical"', html)
        self.assertIn("调整两个表格宽度", html)

        self.assertIn(".overview-bottom-column-splitter", styles)
        self.assertIn("cursor: col-resize;", styles)
        self.assertIn("is-overview-column-splitter-dragging", styles)
        self.assertIn("--overview-bottom-left-ratio", styles)
        self.assertIn("--overview-bottom-right-ratio", styles)
        self.assertIn("12px", styles)

        self.assertIn(storage_key, script)
        self.assertIn("const OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO = 50;", script)
        self.assertIn("const OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX = 260;", script)
        self.assertIn(
            "if (!Number.isFinite(storedRatio) || storedRatio <= 0) "
            "return OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO;",
            script,
        )
        self.assertIn("overviewBottomColumnRatio: overviewInitialBottomColumnRatio()", script)
        self.assertIn("overviewBottomColumnSplitDrag: null", script)
        for function_name in (
            "overviewInitialBottomColumnRatio",
            "overviewBottomColumnRatioBounds",
            "applyOverviewBottomColumnRatio",
            "beginOverviewBottomColumnSplitterDrag",
            "handleOverviewBottomColumnSplitterDrag",
            "finishOverviewBottomColumnSplitterDrag",
            "handleOverviewBottomColumnSplitterKeydown",
            "initOverviewBottomColumnSplitter",
        ):
            self.assertIn(f"function {function_name}", script)
        self.assertIn(
            "localStorage.setItem(OVERVIEW_BOTTOM_COLUMN_RATIO_KEY, String(nextRatio))",
            script,
        )
        self.assertIn('style.setProperty("--overview-bottom-left-ratio"', script)
        self.assertIn('style.setProperty("--overview-bottom-right-ratio"', script)
        self.assertIn('event.key === "ArrowLeft"', script)
        self.assertIn('event.key === "ArrowRight"', script)
        self.assertIn("initOverviewBottomColumnSplitter();", script)

    def test_simulator_home_bottom_tables_have_persistent_width_splitter(self):
        self.assert_horizontal_splitter(
            "simulator",
            "polarSimulatorOverviewBottomColumnRatio",
        )

    def test_trainee_home_bottom_tables_have_independent_persistent_width_splitter(self):
        self.assert_horizontal_splitter(
            "trainee",
            "polarTraineeOverviewBottomColumnRatio",
        )

    def test_simulator_and_trainee_width_ratios_use_different_storage_keys(self):
        _, simulator_script, _ = self.app_sources("simulator")
        _, trainee_script, _ = self.app_sources("trainee")

        self.assertIn("polarSimulatorOverviewBottomColumnRatio", simulator_script)
        self.assertNotIn("polarTraineeOverviewBottomColumnRatio", simulator_script)
        self.assertIn("polarTraineeOverviewBottomColumnRatio", trainee_script)
        self.assertNotIn("polarSimulatorOverviewBottomColumnRatio", trainee_script)


if __name__ == "__main__":
    unittest.main()
