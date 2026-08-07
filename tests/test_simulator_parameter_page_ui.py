from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulatorParameterPageUiTest(unittest.TestCase):
    def test_simulator_has_system_parameter_configuration_page(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-nav-page="parameters"', html)
        self.assertIn('data-page="parameters"', html)
        self.assertIn('id="parameterClockSpeed"', html)
        self.assertIn('id="parameterComputeInterval"', html)
        self.assertIn('id="parameterStorageInitialSoc"', html)
        self.assertIn("时钟倍率", html)
        self.assertIn("每次触发推进量", html)
        self.assertIn("仿真周期", html)
        self.assertIn("后台计算触发间隔", html)
        self.assertIn("储能SOC初始值", html)
        for speed in (1, 5, 15, 30, 60, 300, 900, 1800, 3600):
            self.assertIn(f'<option value="{speed}">{speed}:1</option>', html)
        self.assertIn("function renderSystemParameters", script)
        self.assertIn('api("/api/config"', script)
        self.assertIn("compute_interval_seconds", script)
        self.assertIn("effective_step_seconds", script)
        self.assertIn("storage_initial_soc", script)
        self.assertIn(".parameter-page-layout", styles)
        self.assertIn(".system-parameter-table", styles)

    def test_storage_initial_soc_uses_percent_in_ui_and_decimal_in_payload(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="currentStorageInitialSoc" class="numeric-cell">50%</td>', html)
        soc_input = html.split('id="parameterStorageInitialSoc"', 1)[1].split("/>", 1)[0]
        self.assertIn('min="0"', soc_input)
        self.assertIn('max="100"', soc_input)
        self.assertIn('value="50"', soc_input)

        helper_source = "function parameterNumber" + script.split("function parameterNumber", 1)[1].split(
            "async function saveSystemParameters",
            1,
        )[0]
        harness = r"""
const inputValues = {
  parameterClockSpeed: "60",
  parameterComputeInterval: "1",
  parameterStorageInitialSoc: "65",
};
function $(id) { return { value: inputValues[id] }; }
const state = { systemParameters: { clock_speed: 60, compute_interval_seconds: 1, storage_initial_soc: 0.5 } };
process.stdout.write(JSON.stringify({
  display: parameterPercentText(0.99),
  input: parameterPercentInputText(0.5),
  payload: systemParameterPayload(),
}));
"""
        result = subprocess.run(
            ["node"],
            input=f"{helper_source}\n{harness}",
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["display"], "99%")
        self.assertEqual(payload["input"], "50")
        self.assertEqual(payload["payload"]["storage_initial_soc"], 0.65)


if __name__ == "__main__":
    unittest.main()
