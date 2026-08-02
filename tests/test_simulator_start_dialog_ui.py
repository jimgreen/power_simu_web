from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulatorStartDialogUiTest(unittest.TestCase):
    def test_start_button_opens_start_time_dialog_only_from_stopped_state(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="startSimulationDialog"', html)
        self.assertIn('id="startSimulationForm"', html)
        self.assertIn('id="startSimulationDay"', html)
        self.assertIn('id="startSimulationTime"', html)
        self.assertIn('type="time" step="1"', html)
        self.assertIn("启动仿真", html)
        self.assertIn("起始时刻", html)

        self.assertIn("function openStartSimulationDialog", script)
        self.assertIn("function startSimulationFromDialog", script)
        self.assertIn("function handleClockAction", script)
        self.assertIn('action === "start" && currentState === "stopped"', script)
        self.assertIn("function startSimulationDefaultAbsoluteSecond", script)
        self.assertIn("function startSimulationSecondFromDialog", script)
        self.assertIn('controlClock("start", { second })', script)
        self.assertIn("secondToTimeInput(absoluteSecond % 86400", script)

        self.assertIn(".start-simulation-fields", styles)
        self.assertIn(".modal-field input", styles)


if __name__ == "__main__":
    unittest.main()
