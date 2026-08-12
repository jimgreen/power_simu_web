from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CommandOriginFilterUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator_html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        cls.simulator_script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        cls.trainee_html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.trainee_script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def test_simulator_command_page_filters_manual_and_automatic_origins(self):
        self.assertIn('id="runtimeCommandOriginFilter"', self.simulator_html)
        self.assertIn('<option value="manual">人工指令</option>', self.simulator_html)
        self.assertIn('<option value="automatic">自动指令</option>', self.simulator_html)
        self.assertIn('runtimeCommandOriginFilter: "all"', self.simulator_script)

        filter_block = self.simulator_script.split(
            "function applyRuntimeCommandTableFilters", 1
        )[1].split("function syncRuntimeCommandOnlyActiveControl", 1)[0]
        self.assertIn("runtimeCommandRowOrigin(row)", filter_block)
        self.assertIn("state.runtimeCommandOriginFilter", filter_block)

        structure_block = self.simulator_script.split(
            "function runtimeCommandTableStructureKey", 1
        )[1].split("function runtimeCommandTableValueText", 1)[0]
        self.assertIn('state.runtimeCommandOriginFilter || "all"', structure_block)
        self.assertIn('field === "origin"', self.simulator_script)

    def test_trainee_command_page_filters_manual_and_automatic_origins(self):
        self.assertIn('id="commandOriginFilter"', self.trainee_html)
        self.assertIn('<option value="manual">人工指令</option>', self.trainee_html)
        self.assertIn('<option value="automatic">自动指令</option>', self.trainee_html)
        self.assertIn('commandOriginFilter: "all"', self.trainee_script)

        filter_block = self.trainee_script.split(
            "function applyCommandTableFilters", 1
        )[1].split("function syncCommandOnlyActiveControl", 1)[0]
        self.assertIn("commandTableRowOrigin(row)", filter_block)
        self.assertIn("state.commandOriginFilter", filter_block)

        structure_block = self.trainee_script.split(
            "function traineeCommandTableStructureKey", 1
        )[1].split("function traineeCommandCancelButtonHtml", 1)[0]
        self.assertIn('state.commandOriginFilter || "all"', structure_block)
        self.assertIn('field === "origin"', self.trainee_script)

    def test_effective_manual_command_remains_cancellable_without_history_payload(self):
        history_helpers = "function manualCommandHoldsAcrossClockLifecycle" + self.trainee_script.split(
            "function manualCommandHoldsAcrossClockLifecycle", 1
        )[1].split("function addRuntimeLog", 1)[0]
        match_helpers = "function commandEntryMatchesControl" + self.trainee_script.split(
            "function commandEntryMatchesControl", 1
        )[1].split("async function sendCommandCancel", 1)[0]
        body = r"""
const state = { snapshot: {} };
function deviceType(dev) { return dev.dev_type || ""; }
function deviceName(dev) { return dev.dev_name || ""; }
const manualEntry = {
  eligible_source: true,
  manual_hold: true,
  command_origin: "manual",
  accepted: { run_status: 0, set_values: 1 },
  normalized: {
    run_status: [],
    set_values: [{
      dev_type: "ACGenerator",
      dev_name: "交流风电-2",
      set_type: "p_set",
      set_value: "2",
    }],
  },
};
const snapshot = {
  clock: { absolute_minute: 17, run_id: 1 },
  commands: { history: [], effective: [manualEntry] },
};
const entry = activeCommandEntryForControl(
  { dev_type: "ACGenerator", dev_name: "交流风电-2" },
  "set_value",
  "p_set",
  snapshot,
  "manual",
);
const cancelName = activeCommandCancelName(
  { dev_type: "ACGenerator", dev_name: "交流风电-2" },
  "set_value",
  "p_set",
  snapshot,
  null,
  "manual",
);
process.stdout.write(JSON.stringify({
  found: Boolean(entry),
  origin: entry ? commandOrigin(entry) : "",
  cancelName,
}));
"""
        result = subprocess.run(
            ["node", "-e", f"{history_helpers}\n{match_helpers}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "found": True,
                "origin": "manual",
                "cancelName": "ACGenerator.交流风电-2.p_set",
            },
        )


if __name__ == "__main__":
    unittest.main()
