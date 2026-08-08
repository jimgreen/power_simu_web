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

    def test_metric_panel_splits_storage_by_side_and_grid_role(self):
        self.assertIn('id="renewableMetricTabs"', self.html)
        expected = {
            "renewableAcGridFollowingStorageCurrentKw": "交流跟网储能当前值",
            "renewableAcGridFollowingStorageTargetKw": "交流跟网储能目标值",
            "renewableAcGridFollowingStorageSoc": "交流跟网储能SOC",
            "renewableDcGridFollowingStorageCurrentKw": "直流跟网储能当前值",
            "renewableDcGridFollowingStorageTargetKw": "直流跟网储能目标值",
            "renewableDcGridFollowingStorageSoc": "直流跟网储能SOC",
            "renewableAcGridFormingStorageCurrentKw": "交流构网储能当前值",
            "renewableAcGridFormingStorageTargetKw": "交流构网储能目标值",
            "renewableAcGridFormingStorageSoc": "交流构网储能SOC",
            "renewableDcGridFormingStorageCurrentKw": "直流构网储能当前值",
            "renewableDcGridFormingStorageTargetKw": "直流构网储能目标值",
            "renewableDcGridFormingStorageSoc": "直流构网储能SOC",
            "renewableTotalGridFollowingStorageCurrentKw": "总跟网储能当前值",
            "renewableTotalGridFollowingStorageTargetKw": "总跟网储能目标值",
            "renewableTotalGridFollowingStorageSoc": "总跟网储能SOC",
            "renewableTotalGridFormingStorageCurrentKw": "总构网储能当前值",
            "renewableTotalGridFormingStorageTargetKw": "总构网储能目标值",
            "renewableTotalGridFormingStorageSoc": "总构网储能SOC",
        }
        for node_id, label in expected.items():
            with self.subTest(node_id=node_id):
                self.assertIn(f'<dt>{label}</dt><dd id="{node_id}">--</dd>', self.html)
        self.assertIn('<dt>ACDC变流当前值</dt><dd id="renewableAcdcCurrentKw">--</dd>', self.html)
        self.assertIn('<dt>ACDC变流目标值</dt><dd id="renewableAcdcTargetKw">--</dd>', self.html)
        self.assertNotIn('id="renewableStorageCurrentKw"', self.html)
        self.assertNotIn('id="renewableStorageSoc"', self.html)

    def test_metric_panel_adds_wind_pv_and_requested_storage_breakdowns(self):
        expected = {
            "renewableAcWindCurrentKw": "交流风电当前值",
            "renewableAcWindTargetKw": "交流风电目标值",
            "renewableAcPvCurrentKw": "交流光伏当前值",
            "renewableAcPvTargetKw": "交流光伏目标值",
            "renewableDcWindCurrentKw": "直流风电当前值",
            "renewableDcWindTargetKw": "直流风电目标值",
            "renewableDcPvCurrentKw": "直流光伏当前值",
            "renewableDcPvTargetKw": "直流光伏目标值",
            "renewableTotalWindCurrentKw": "总风电当前值",
            "renewableTotalWindTargetKw": "总风电目标值",
            "renewableTotalPvCurrentKw": "总光伏当前值",
            "renewableTotalPvTargetKw": "总光伏目标值",
        }
        for node_id, label in expected.items():
            with self.subTest(node_id=node_id):
                self.assertIn(f'<dt>{label}</dt><dd id="{node_id}">--</dd>', self.html)

        for group_name in (
            "ac-wind",
            "ac-pv",
            "ac-grid-following-storage",
            "ac-grid-forming-storage",
            "dc-wind",
            "dc-pv",
            "dc-grid-following-storage",
            "system-wind",
            "system-pv",
            "system-grid-following-storage",
        ):
            with self.subTest(group_name=group_name):
                self.assertRegex(
                    self.html,
                    rf'data-renewable-metric-group="{group_name}"[^>]*data-renewable-metric-always="true"',
                )

    def test_backend_exposes_wind_pv_counts_and_system_totals(self):
        for metric_key in (
            "onlineAcWindCount",
            "onlineDcWindCount",
            "onlineAcPvCount",
            "onlineDcPvCount",
            "totalWindCurrentKw",
            "totalWindTargetKw",
            "totalPvCurrentKw",
            "totalPvTargetKw",
        ):
            with self.subTest(metric_key=metric_key):
                self.assertIn(f'"{metric_key}"', self.backend)

    def test_rendering_populates_wind_pv_breakdowns_and_labels_empty_storage(self):
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        for node_id in (
            "renewableAcWindCurrentKw",
            "renewableAcWindTargetKw",
            "renewableAcPvCurrentKw",
            "renewableAcPvTargetKw",
            "renewableDcWindCurrentKw",
            "renewableDcWindTargetKw",
            "renewableDcPvCurrentKw",
            "renewableDcPvTargetKw",
            "renewableTotalWindCurrentKw",
            "renewableTotalWindTargetKw",
            "renewableTotalPvCurrentKw",
            "renewableTotalPvTargetKw",
        ):
            with self.subTest(node_id=node_id):
                self.assertIn(node_id, render_block)
        self.assertIn("renewableStorageSocMetricText", render_block)
        self.assertIn("card.dataset.renewableMetricAlways", self.script)

    def test_metric_panel_hides_whole_device_groups_without_online_members(self):
        for group_name, expected_card_count in (
            ("ac-grid-following-storage", 3),
            ("dc-grid-following-storage", 3),
            ("ac-grid-forming-storage", 3),
            ("dc-grid-forming-storage", 3),
            ("system-grid-following-storage", 3),
            ("system-grid-forming-storage", 3),
        ):
            with self.subTest(group_name=group_name):
                self.assertEqual(
                    self.html.count(f'data-renewable-metric-group="{group_name}"'),
                    expected_card_count,
                )

        self.assertIn("function renderRenewableMetricAvailability", self.script)
        self.assertIn("renewableMetricGroupCount", self.script)
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("renderRenewableMetricAvailability(metrics)", render_block)

    def test_backend_exposes_side_counts_used_to_suppress_empty_metrics(self):
        for metric_key in (
            "acGridFollowingStorageCount",
            "dcGridFollowingStorageCount",
            "acGridFormingStorageCount",
            "dcGridFormingStorageCount",
            "onlineAcRenewableCount",
            "onlineDcRenewableCount",
            "onlineAcGridFormingStorageCount",
            "onlineDcGridFormingStorageCount",
            "onlineAcGridFollowingStorageCount",
            "onlineDcGridFollowingStorageCount",
            "onlineAcDieselCount",
            "onlineDcDieselCount",
            "onlineAcLoadCount",
            "onlineDcLoadCount",
            "onlineAcdcConverterCount",
        ):
            with self.subTest(metric_key=metric_key):
                self.assertIn(f'"{metric_key}"', self.backend)

    def test_storage_metric_text_distinguishes_absent_offline_and_running_devices(self):
        helpers = "function renewableMetricCount" + self.script.split(
            "function renewableMetricCount",
            1,
        )[1].split("function openRenewableControlParametersDialog", 1)[0]
        node_script = f"""
function formatNumber(value) {{ return String(value); }}
function formatOverviewNumber(value) {{ return String(value); }}
{helpers}
const group = "ac-grid-following-storage";
process.stdout.write(JSON.stringify({{
  absentPower: renewableStoragePowerMetricText(0, {{
    acGridFollowingStorageCount: 0,
    onlineAcGridFollowingStorageCount: 0,
  }}, group),
  offlineSoc: renewableStorageSocMetricText(0.5, {{
    acGridFollowingStorageCount: 1,
    onlineAcGridFollowingStorageCount: 0,
  }}, group),
  runningZeroPower: renewableStoragePowerMetricText(0, {{
    acGridFollowingStorageCount: 1,
    onlineAcGridFollowingStorageCount: 1,
  }}, group),
  legacyAbsentSoc: renewableStorageSocMetricText(null, {{
    onlineAcGridFollowingStorageCount: 0,
  }}, group),
}}));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "absentPower": "无此类设备",
                "offlineSoc": "无运行设备",
                "runningZeroPower": "0 kW",
                "legacyAbsentSoc": "无设备",
            },
        )

    def test_metric_group_availability_uses_side_counts_instead_of_zero_power_values(self):
        helpers = "function renewableMetricCount" + self.script.split(
            "function renewableMetricCount",
            1,
        )[1].split("function renderRenewableMetricAvailability", 1)[0]
        node_script = f"""
{helpers}
const metrics = {{
  onlineAcGridFollowingStorageCount: 0,
  onlineDcGridFollowingStorageCount: 0,
  onlineAcGridFormingStorageCount: 0,
  onlineDcGridFormingStorageCount: 1,
}};
process.stdout.write(JSON.stringify({{
  acGridFollowing: renewableMetricGroupCount(metrics, "ac-grid-following-storage"),
  systemGridFollowing: renewableMetricGroupCount(metrics, "system-grid-following-storage"),
  systemGridForming: renewableMetricGroupCount(metrics, "system-grid-forming-storage"),
  emptyAvailable: renewableMetricGroupAvailable(metrics, "system-grid-following-storage"),
  populatedAvailable: renewableMetricGroupAvailable(metrics, "system-grid-forming-storage"),
}}));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "acGridFollowing": 0,
                "systemGridFollowing": 0,
                "systemGridForming": 1,
                "emptyAvailable": False,
                "populatedAvailable": True,
            },
        )

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
            "renewableAcGridFollowingStorageCurrentKw",
            "renewableAcGridFollowingStorageTargetKw",
            "renewableAcGridFollowingStorageSoc",
            "renewableDcGridFollowingStorageCurrentKw",
            "renewableDcGridFollowingStorageTargetKw",
            "renewableDcGridFollowingStorageSoc",
            "renewableAcGridFormingStorageCurrentKw",
            "renewableAcGridFormingStorageTargetKw",
            "renewableAcGridFormingStorageSoc",
            "renewableDcGridFormingStorageCurrentKw",
            "renewableDcGridFormingStorageTargetKw",
            "renewableDcGridFormingStorageSoc",
            "renewableTotalGridFollowingStorageCurrentKw",
            "renewableTotalGridFollowingStorageTargetKw",
            "renewableTotalGridFollowingStorageSoc",
            "renewableTotalGridFormingStorageCurrentKw",
            "renewableTotalGridFormingStorageTargetKw",
            "renewableTotalGridFormingStorageSoc",
            "renewableAcdcCurrentKw",
            "renewableAcdcTargetKw",
        ):
            self.assertIn(node_id, render_block)
        for metric_key in (
            "acGridFollowingStorageCurrentKw",
            "acGridFollowingStorageTargetKw",
            "acGridFollowingStorageSoc",
            "dcGridFollowingStorageCurrentKw",
            "dcGridFollowingStorageTargetKw",
            "dcGridFollowingStorageSoc",
            "acGridFormingStorageCurrentKw",
            "acGridFormingStorageTargetKw",
            "acGridFormingStorageSoc",
            "dcGridFormingStorageCurrentKw",
            "dcGridFormingStorageTargetKw",
            "dcGridFormingStorageSoc",
            "totalGridFollowingStorageCurrentKw",
            "totalGridFollowingStorageTargetKw",
            "totalGridFollowingStorageSoc",
            "totalGridFormingStorageCurrentKw",
            "totalGridFormingStorageTargetKw",
            "totalGridFormingStorageSoc",
        ):
            self.assertIn(metric_key, render_block)
        self.assertNotIn("calculateRenewableControlPlan", render_block)

    def test_side_totals_keep_missing_metrics_empty_instead_of_coercing_them_to_zero(self):
        match = re.search(r"function renewableMetricTotal\([^)]*\) \{.*?\n\}", self.script, re.DOTALL)
        self.assertIsNotNone(match)
        node_script = f"""
{match.group(0)}
process.stdout.write(JSON.stringify([
  renewableMetricTotal({{ a: null, b: undefined }}, ["a", "b"]),
  renewableMetricTotal({{ a: "", b: null }}, ["a", "b"]),
  renewableMetricTotal({{ a: 0, b: null }}, ["a", "b"]),
  renewableMetricTotal({{ a: "2.5", b: 3 }}, ["a", "b"]),
]));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [None, None, 0, 5.5])

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
        self.assertIn("renewableMetricSocText", render_block)
        self.assertIn("def _live_soc_ratio", self.backend)
        self.assertNotIn("number /= 100.0", self.backend.split("def _live_soc_ratio", 1)[1].split("def _command_number", 1)[0])


if __name__ == "__main__":
    unittest.main()
