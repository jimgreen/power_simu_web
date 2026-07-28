from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VerticalSplitterUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        cls.simulator_styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        cls.simulator_script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        cls.trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        cls.trainee_styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")
        cls.trainee_script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

    def test_simulator_table_chart_pages_have_horizontal_splitters(self):
        for split_id in ("simulator-curves", "simulator-runtime", "simulator-measurements"):
            with self.subTest(split_id=split_id):
                self.assertIn(f'data-vertical-split="{split_id}"', self.simulator_html)
                self.assertIn(f'data-vertical-splitter="{split_id}"', self.simulator_html)

        self.assertGreaterEqual(self.simulator_html.count('class="vertical-stack-splitter"'), 3)
        self.assertGreaterEqual(self.simulator_html.count('role="separator"'), 4)
        self.assertIn('aria-orientation="horizontal"', self.simulator_html)

    def test_trainee_table_chart_pages_have_horizontal_splitters(self):
        for split_id in ("trainee-curves", "trainee-measurements", "trainee-commands"):
            with self.subTest(split_id=split_id):
                self.assertIn(f'data-vertical-split="{split_id}"', self.trainee_html)
                self.assertIn(f'data-vertical-splitter="{split_id}"', self.trainee_html)

        self.assertGreaterEqual(self.trainee_html.count('class="vertical-stack-splitter"'), 3)
        self.assertIn('aria-orientation="horizontal"', self.trainee_html)

    def test_trainee_trace_panels_reserve_space_for_axis_and_legend(self):
        self.assertRegex(
            self.trainee_html,
            r'data-vertical-split="trainee-measurements"\s+'
            r'data-vertical-split-min-bottom="380"',
        )
        self.assertRegex(
            self.trainee_html,
            r'data-vertical-split="trainee-commands"\s+'
            r'data-vertical-split-min-bottom="330"',
        )
        self.assertIn("container.dataset.verticalSplitMinBottom", self.trainee_script)

    def test_splitter_styles_are_shared_by_simulator_and_trainee(self):
        for styles in (self.simulator_styles, self.trainee_styles):
            with self.subTest(styles_hash=hash(styles)):
                self.assertIn(".vertical-split-workspace", styles)
                self.assertIn(".vertical-stack-splitter", styles)
                self.assertIn("grid-template-rows: minmax(120px, var(--vertical-split-top", styles)
                self.assertIn("body.is-vertical-splitter-dragging", styles)
                self.assertIn("cursor: row-resize;", styles)
                self.assertIn(".command-split-workspace", styles)

    def test_splitter_interaction_code_is_initialized_in_both_apps(self):
        for script in (self.simulator_script, self.trainee_script):
            with self.subTest(script_hash=hash(script)):
                self.assertIn("function initVerticalSplitters", script)
                self.assertIn("function applyVerticalSplit", script)
                self.assertIn("function beginVerticalSplitterDrag", script)
                self.assertIn("function handleVerticalSplitterKeydown", script)
                self.assertIn("is-vertical-splitter-dragging", script)
                self.assertIn("initVerticalSplitters();", script)

    def test_trainee_splitter_prioritizes_chart_when_minimums_nearly_collide(self):
        bounds = self.trainee_script.split("function verticalSplitBounds(container) {", 1)[1].split(
            "function applyVerticalSplit",
            1,
        )[0]

        self.assertIn('if (container.hasAttribute("data-vertical-split-min-bottom")) {', bounds)
        self.assertIn("const bottomPriorityRatio = clamp(maxRatio, 8, 92);", bounds)
        self.assertIn("return { min: bottomPriorityRatio, max: bottomPriorityRatio };", bounds)
        self.assertIn("const centerRatio = clamp(50, 8, 92);", bounds)


if __name__ == "__main__":
    unittest.main()
