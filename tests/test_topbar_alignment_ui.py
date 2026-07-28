from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TopbarAlignmentUiTest(unittest.TestCase):
    def test_topbar_switchers_share_the_same_horizontal_center_line(self):
        css = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        topbar_rule = css.split(".topbar {", 1)[1].split("}", 1)[0]
        toolbar_rule = css.split(".model-toolbar {", 1)[1].split("}", 1)[0]
        topbar_clock_controls_rule = css.split(".topbar-clock-controls {", 1)[1].split("}", 1)[0]
        clock_rule = css.split(".top-clock-strip {", 1)[1].split("}", 1)[0]
        self.assertIn("justify-content: flex-start", topbar_rule)
        self.assertIn("flex: 0 1 auto", toolbar_rule)
        self.assertIn("margin-left: 0", topbar_clock_controls_rule)
        self.assertIn("margin-left: auto", clock_rule)
        self.assertIn(".simulation-mode-switcher {", css)
        simulation_rule = css.split(".simulation-mode-switcher {", 1)[1].split("}", 1)[0]
        self.assertIn("margin: 0", simulation_rule)
        self.assertIn("height: 32px", simulation_rule)

    def test_clock_readout_is_before_topbar_clock_controls(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        topbar = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        overview_status = html.split('<section class="panel overview-status-panel">', 1)[1].split("</section>", 1)[0]
        self.assertLess(
            topbar.index('<div class="clock-strip top-clock-strip"'),
            topbar.index('<div class="overview-clock-controls topbar-clock-controls"'),
        )
        topbar_clock = topbar.split('<div class="clock-strip top-clock-strip"', 1)[1].split(
            '<div class="overview-clock-controls topbar-clock-controls"',
            1,
        )[0]
        topbar_controls = topbar.split('<div class="overview-clock-controls topbar-clock-controls"', 1)[1]
        for action in ("start", "pause", "stop", "step", "slower", "faster"):
            self.assertIn(f'data-clock="{action}"', topbar_controls)
            self.assertNotIn(f'data-clock="{action}"', overview_status)
            self.assertNotIn(f'data-clock="{action}"', topbar_clock)
        self.assertIn("时钟控制", topbar_controls)
        self.assertIn('id="overviewClockSpeed"', topbar_controls)
        self.assertIn('id="simTime"', topbar_clock)
        self.assertIn('id="simState" hidden', topbar_clock)
        self.assertIn('id="simSpeed" hidden', topbar_clock)
        self.assertNotIn("当前仿真时刻", html)
        self.assertNotIn('id="overviewRefresh"', html)
        self.assertIn('class="overview-clock-controls topbar-clock-controls"', html)
        self.assertNotIn('setOverviewText("overviewRefresh"', app_js)
        self.assertIn('"overviewClockSpeed"', app_js)
        self.assertIn(".top-clock-readout", css)
        self.assertIn(".overview-clock-controls", css)
        self.assertIn(".topbar-clock-controls", css)
        self.assertIn(".overview-clock-control-label", css)
        self.assertIn("height: 42px", css)

    def test_topbar_model_selector_has_no_extra_caption(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        topbar = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        selector_rule = css.split(".model-switcher select {", 1)[1].split("}", 1)[0]
        self.assertNotIn("显示模型", topbar)
        self.assertIn('class="model-switcher"', topbar)
        self.assertIn('id="modelSelector"', topbar)
        self.assertIn('id="activeModelName"', topbar)
        self.assertIn("flex: 0 0 180px", selector_rule)
        self.assertNotIn("flex: 0 0 240px", selector_rule)


if __name__ == "__main__":
    unittest.main()
