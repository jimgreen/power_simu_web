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
        expected = (
            ("跟网储能", "renewableAcGridFollowingStorageCurrentKw", "renewableAcGridFollowingStorageTargetKw", "renewableAcGridFollowingStorageSoc"),
            ("跟网储能", "renewableDcGridFollowingStorageCurrentKw", "renewableDcGridFollowingStorageTargetKw", "renewableDcGridFollowingStorageSoc"),
            ("构网储能", "renewableAcGridFormingStorageCurrentKw", "renewableAcGridFormingStorageTargetKw", "renewableAcGridFormingStorageSoc"),
            ("构网储能", "renewableDcGridFormingStorageCurrentKw", "renewableDcGridFormingStorageTargetKw", "renewableDcGridFormingStorageSoc"),
            ("跟网储能", "renewableTotalGridFollowingStorageCurrentKw", "renewableTotalGridFollowingStorageTargetKw", "renewableTotalGridFollowingStorageSoc"),
            ("构网储能", "renewableTotalGridFormingStorageCurrentKw", "renewableTotalGridFormingStorageTargetKw", "renewableTotalGridFormingStorageSoc"),
        )
        for label, current_id, target_id, soc_id in expected:
            with self.subTest(label=label):
                self.assertIn(
                    f'<th scope="row">{label}<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{current_id}">--</td>'
                    f'<td id="{target_id}">--</td>',
                    self.html,
                )
                self.assertIn(
                    f'<th scope="row">{label}SOC<span class="renewable-metric-unit">（%）</span></th>'
                    f'<td id="{soc_id}">--</td>'
                    '<td class="renewable-metric-empty">--</td>',
                    self.html,
                )
        self.assertIn(
            '<th scope="row">ACDC变流<span class="renewable-metric-unit">（kW）</span></th>'
            '<td id="renewableAcdcCurrentKw">--</td>'
            '<td id="renewableAcdcTargetKw">--</td>',
            self.html,
        )
        self.assertNotIn('id="renewableStorageCurrentKw"', self.html)
        self.assertNotIn('id="renewableStorageSoc"', self.html)

    def test_metric_panel_adds_wind_pv_and_requested_storage_breakdowns(self):
        expected = (
            ("风电", "renewableAcWindCurrentKw", "renewableAcWindTargetKw"),
            ("光伏", "renewableAcPvCurrentKw", "renewableAcPvTargetKw"),
            ("风电", "renewableDcWindCurrentKw", "renewableDcWindTargetKw"),
            ("光伏", "renewableDcPvCurrentKw", "renewableDcPvTargetKw"),
            ("风电", "renewableTotalWindCurrentKw", "renewableTotalWindTargetKw"),
            ("光伏", "renewableTotalPvCurrentKw", "renewableTotalPvTargetKw"),
        )
        for label, current_id, target_id in expected:
            with self.subTest(current_id=current_id):
                self.assertIn(
                    f'<th scope="row">{label}<span class="renewable-metric-unit">（kW）</span></th>'
                    f'<td id="{current_id}">--</td>'
                    f'<td id="{target_id}">--</td>',
                    self.html,
                )

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

    def test_converter_strategy_rows_display_the_selected_terminal_sign(self):
        match = re.search(
            r"function renewableRowControlPointPower\([^)]*\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        node_script = f"""
function optionalNumber(value) {{
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}}
{match.group(0)}
process.stdout.write(JSON.stringify([
  renewableRowControlPointPower({{ set_type: "p_ac_set" }}, -12),
  renewableRowControlPointPower({{ set_type: "p_dc_set" }}, -12),
  renewableRowControlPointPower({{ set_type: "p_set" }}, 8),
]));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), [-12, 12, 8])

        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn(
            "const currentValue = renewableRowControlPointPower(row, row.currentKw);",
            render_block,
        )
        self.assertIn(
            "const targetValue = renewableRowControlPointPower(row, balanceStorage",
            render_block,
        )
        self.assertIn("renewableStorageSocMetricText", render_block)
        self.assertIn("card.dataset.renewableMetricAlways", self.script)

    def test_metric_panel_hides_whole_device_groups_without_online_members(self):
        for group_name, expected_row_count in (
            ("ac-grid-following-storage", 2),
            ("dc-grid-following-storage", 2),
            ("ac-grid-forming-storage", 2),
            ("dc-grid-forming-storage", 2),
            ("system-grid-following-storage", 2),
            ("system-grid-forming-storage", 2),
        ):
            with self.subTest(group_name=group_name):
                self.assertEqual(
                    self.html.count(f'data-renewable-metric-group="{group_name}"'),
                    expected_row_count,
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
                "runningZeroPower": "0",
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
        efficiency_block = self.backend.split("def _storage_efficiency", 1)[1].split("def _live_soc_ratio", 1)[0]
        self.assertIn('(\"P_GEN\", \"P\", \"P_AC\", \"P_DC\")', storage_block)
        self.assertIn("_live_soc_ratio", storage_block)
        self.assertIn("_storage_efficiency(parameter)", storage_block)
        self.assertIn("charge_discharge_efficiency", efficiency_block)
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
