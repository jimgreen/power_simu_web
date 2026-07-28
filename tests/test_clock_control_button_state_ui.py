from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClockControlButtonStateUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

    def test_initial_stopped_markup_disables_stop_pause_and_step_buttons(self):
        pause_button = self.html.split('data-clock="pause"', 1)[1].split("</button>", 1)[0]
        stop_button = self.html.split('data-clock="stop"', 1)[1].split("</button>", 1)[0]
        step_button = self.html.split('data-clock="step"', 1)[1].split("</button>", 1)[0]

        self.assertIn("disabled", pause_button)
        self.assertIn('aria-disabled="true"', pause_button)
        self.assertIn("disabled", stop_button)
        self.assertIn('aria-disabled="true"', stop_button)
        self.assertIn("disabled", step_button)
        self.assertIn('aria-disabled="true"', step_button)

    def test_clock_buttons_are_disabled_by_simulation_state(self):
        self.assertIn("function clockControlButtonDisabled(action, clockState)", self.script)
        self.assertIn('clockState === "running" && ["start", "step"].includes(action)', self.script)
        self.assertIn('clockState === "paused" && action === "pause"', self.script)
        self.assertIn('clockState === "stopped" && ["stop", "pause", "step"].includes(action)', self.script)
        self.assertIn('button.disabled = clockControlButtonDisabled(action, clock.state || "stopped")', self.script)
        self.assertIn('button.setAttribute("aria-disabled", button.disabled ? "true" : "false")', self.script)

    def test_disabled_clock_buttons_have_muted_visual_state(self):
        self.assertIn(".overview-clock-controls .icon-button:disabled", self.styles)
        self.assertIn("cursor: not-allowed", self.styles)


if __name__ == "__main__":
    unittest.main()
