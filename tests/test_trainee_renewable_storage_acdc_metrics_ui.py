import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableStorageAcdcMetricsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")

    def test_metric_strip_shows_storage_current_soc_and_acdc_current_target(self):
        self.assertIn('<dt>储能当前值</dt><dd id="renewableStorageCurrentKw">--</dd>', self.html)
        self.assertIn('<dt>储能SOC值</dt><dd id="renewableStorageSoc">--</dd>', self.html)
        self.assertIn('<dt>ACDC变流当前值</dt><dd id="renewableAcdcCurrentKw">--</dd>', self.html)
        self.assertIn('<dt>ACDC变流目标值</dt><dd id="renewableAcdcTargetKw">--</dd>', self.html)
        self.assertNotIn('<dt>储能功率</dt>', self.html)

    def test_backend_reads_signed_storage_power_soc_efficiency_and_boundaries(self):
        storage_block = self.backend.split("def _storage_rows", 1)[1].split("def _converter_rows", 1)[0]
        self.assertIn('(\"P_GEN\", \"P\", \"P_AC\", \"P_DC\")', storage_block)
        self.assertIn("_live_soc_ratio", storage_block)
        self.assertIn("charge_discharge_efficiency", storage_block)
        self.assertIn("charge_by_energy", storage_block)
        self.assertIn("discharge_by_energy", storage_block)
        self.assertIn('"currentKw"', storage_block)
        self.assertIn('"soc"', storage_block)

    def test_backend_converts_storage_target_to_exact_parallel_acdc_target(self):
        converter_block = self.backend.split("def _converter_rows", 1)[1].split("def _allocate", 1)[0]
        planner_block = self.backend.split("def calculate_renewable_control_plan", 1)[1].split("def _request_json", 1)[0]
        self.assertIn('(\"P_AC\", \"P_DC\", \"P\")', converter_block)
        self.assertIn("POWER_CONTROL_MODES", converter_block)
        self.assertIn("converter_allocations", planner_block)
        self.assertIn("converter_target", planner_block)
        self.assertIn('"acdcCurrentKw"', planner_block)
        self.assertIn('"acdcTargetKw"', planner_block)

    def test_rendering_uses_backend_plan_metrics(self):
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("const plan = control.lastPlan", render_block)
        for node_id in (
            "renewableStorageCurrentKw",
            "renewableStorageSoc",
            "renewableAcdcCurrentKw",
            "renewableAcdcTargetKw",
        ):
            self.assertIn(node_id, render_block)
        self.assertNotIn("calculateRenewableControlPlan", render_block)

    def test_live_storage_soc_keeps_unbounded_runtime_ratio(self):
        match = re.search(r"function liveStorageSocRatio\([^)]*\) \{.*?\n\}", self.script, re.DOTALL)
        self.assertIsNotNone(match)
        node_script = f"""
function parameterNumber(value, defaultValue = null) {{
  if (value === null || value === undefined || String(value).trim() === "") return defaultValue;
  const direct = Number(value);
  if (Number.isFinite(direct)) return direct;
  const parsed = Number(String(value).replace(/[^0-9.+-]/g, ""));
  return Number.isFinite(parsed) ? parsed : defaultValue;
}}
{match.group(0)}
process.stdout.write(JSON.stringify([
  liveStorageSocRatio(0.5, null),
  liveStorageSocRatio(3.358, null),
  liveStorageSocRatio("50%", null),
  liveStorageSocRatio(null, 0.5),
]));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [0.5, 3.358, 0.5, 0.5])

    def test_homepage_and_backend_metric_share_live_soc_semantics(self):
        overview_block = self.script.split("function parsePowerFlowOverview", 1)[1].split(
            "function formatOverviewNumber",
            1,
        )[0]
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("averageStorageSocRatio(snapshot)", overview_block)
        self.assertIn("formatOverviewNumber(metrics.storageSoc * 100)", render_block)
        self.assertIn("def _live_soc_ratio", self.backend)
        self.assertNotIn("number /= 100.0", self.backend.split("def _live_soc_ratio", 1)[1].split("def _command_number", 1)[0])


if __name__ == "__main__":
    unittest.main()
