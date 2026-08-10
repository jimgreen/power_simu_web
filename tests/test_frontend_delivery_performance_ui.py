from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendDeliveryPerformanceUiTest(unittest.TestCase):
    def _script(self, role: str) -> str:
        return (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")

    def test_hidden_pages_back_off_and_resume_immediately_when_visible(self):
        for role in ("simulator", "trainee"):
            script = self._script(role)
            self.assertIn("const HIDDEN_REFRESH_INTERVAL_MS = 10000;", script)
            self.assertIn("function pageIsHidden()", script)
            self.assertIn("function refreshSchedulerIntervalMs()", script)
            self.assertIn('document.addEventListener("visibilitychange"', script)
            self.assertIn("scheduleNextRefresh(pageIsHidden() ? HIDDEN_REFRESH_INTERVAL_MS : 0);", script)

    def test_frontends_use_compact_device_runtime_frames_with_full_frame_recovery(self):
        for role in ("simulator", "trainee"):
            script = self._script(role)
            self.assertIn("function applyDeviceRuntimePayload", script)
            self.assertIn("function canUseCompactDeviceRuntime", script)
            self.assertIn('params.set("device_runtime_compact", "1");', script)
            self.assertIn(
                'params.set("after_device_runtime_signature", state.deviceRuntimeSignature);',
                script,
            )
            self.assertIn("state.deviceRuntimeNeedsFullRefresh = true;", script)
            self.assertIn("state.deviceRuntimeNeedsFullRefresh = false;", script)

    def test_compact_device_runtime_frame_is_applied_by_canonical_device_order(self):
        script = self._script("simulator")
        helper_source = "const DEVICE_RUNTIME_ENCODING" + script.split(
            "const DEVICE_RUNTIME_ENCODING",
            1,
        )[1].split("function mergeSnapshot", 1)[0]
        node_script = f"""
const state = {{ deviceRuntimeSignature: "", deviceRuntimeNeedsFullRefresh: false, deviceRuntimeWarning: "" }};
function currentPageName() {{ return "overview"; }}
function pageNeedsDevices() {{ return true; }}
function pageNeedsDeviceStates() {{ return true; }}
{helper_source}
const devices = [
  {{ dev_type: "B", dev_name: "二号", run_stat: 1, set_values: {{ p_set: 1 }} }},
  {{ dev_type: "A", dev_name: "一号", run_stat: 1, set_values: {{ p_set: 2 }} }},
];
const states = [{{ dev_type: "A", dev_name: "一号", run_stat: 1, dead_island: false }}];
const frame = {{
  encoding: DEVICE_RUNTIME_ENCODING,
  device_count: 2,
  device_signature: deviceRuntimeOrderSignature(devices, "devices"),
  device_run_stats: [0, 1],
  device_statuses: [1, 0],
  device_modes: ["PQ", "V"],
  device_set_values: [{{ p_set: 8 }}, {{ p_set: 9 }}],
  device_soc_present: [true, false],
  device_soc_values: [0.45, null],
  state_count: 1,
  state_signature: deviceRuntimeOrderSignature(states, "device_states"),
  state_run_stats: [0],
  state_dead_islands: [true],
  runtime_signature: "runtime-ok",
}};
const applied = applyDeviceRuntimePayload(
  {{ devices, device_states: states }},
  {{ device_runtime_signature: "runtime-ok", device_runtime: frame }},
);
const broken = {{ ...frame, runtime_signature: "runtime-bad", device_run_stats: [0] }};
applyDeviceRuntimePayload(applied, {{ device_runtime_signature: "runtime-bad", device_runtime: broken }});
process.stdout.write(JSON.stringify({{
  runStats: applied.devices.map((row) => row.run_stat),
  setValues: applied.devices.map((row) => row.set_values.p_set),
  soc: applied.devices.find((row) => row.dev_type === "A").soc_curr,
  deadIsland: applied.device_states[0].dead_island,
  needsFullRefresh: state.deviceRuntimeNeedsFullRefresh,
}}));
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["runStats"], [1, 0])
        self.assertEqual(payload["setValues"], [9, 8])
        self.assertEqual(payload["soc"], 0.45)
        self.assertTrue(payload["deadIsland"])
        self.assertTrue(payload["needsFullRefresh"])

    def test_static_snapshot_cache_is_memory_backed_and_skips_unchanged_writes(self):
        for role in ("simulator", "trainee"):
            script = self._script(role)
            self.assertIn("let staticCacheStoreMemory = null;", script)
            self.assertIn("function staticCacheEntryMatchesSnapshot", script)
            self.assertIn("if (!changed) return;", script)

    def test_frontends_publish_request_byte_and_render_diagnostics(self):
        for role in ("simulator", "trainee"):
            script = self._script(role)
            self.assertIn("frontendDiagnostics:", script)
            self.assertIn("function recordFrontendRequestDiagnostics", script)
            self.assertIn("window.__polarFrontendDiagnostics = state.frontendDiagnostics;", script)

    def test_trainee_renewable_refresh_updates_control_state_before_the_single_render(self):
        script = self._script("trainee")
        refresh_source = "async function refresh()" + script.split("async function refresh()", 1)[1].split(
            "async function refreshFromTeacher",
            1,
        )[0]
        teacher_source = "async function refreshFromTeacher" + script.split(
            "async function refreshFromTeacher",
            1,
        )[1].split("function renderSnapshot", 1)[0]

        self.assertIn(
            "await refreshRenewableControlState({ preview: false, render: false });",
            refresh_source,
        )
        self.assertIn(
            "await refreshRenewableControlState({ preview: false, render: false });",
            teacher_source,
        )
        self.assertNotIn(
            "finally {\n    state.refreshRequestActive = false;\n    if (currentPageName()",
            refresh_source,
        )


if __name__ == "__main__":
    unittest.main()
