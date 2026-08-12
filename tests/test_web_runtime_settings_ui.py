from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebRuntimeSettingsUiTest(unittest.TestCase):
    def test_simulator_parameter_page_contains_simulation_and_web_runtime_groups(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")

        self.assertIn("仿真运行参数", html)
        self.assertIn("WEB 运行参数", html)
        self.assertIn("后台数据刷新周期（仿真周期）", html)
        for element_id in (
            "webRuntimeFrontendRefresh",
            "webRuntimeFrontendRequestTimeout",
            "webRuntimeLogPageSize",
            "webRuntimeLogCacheLimit",
            "webRuntimeCurveRequestTimeout",
            "webRuntimeLogDeltaBatchSize",
            "webRuntimeLogHistoryBatchSize",
            "webRuntimeDiagramElectricFlowThreshold",
            "webRuntimeDiagramHydrogenFlowThreshold",
            "saveRuntimeParameters",
            "undoRuntimeParameters",
            "restoreRuntimeParameterDefaults",
            "runtimeParameterModelName",
            "runtimeParameterUpdatedAt",
        ):
            self.assertIn(f'id="{element_id}"', html)

    def test_trainee_parameter_page_separates_backend_and_web_runtime_groups(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")

        manual_index = html.index('data-nav-page="manual-changes"')
        parameter_index = html.index('data-nav-page="parameters"')
        history_index = html.index('data-nav-page="history"')
        self.assertLess(manual_index, parameter_index)
        self.assertLess(parameter_index, history_index)
        self.assertIn('data-page="parameters"', html)
        self.assertLess(html.index("后台运行参数"), html.index("WEB 运行参数"))
        for element_id in (
            "backendRuntimeParameterForm",
            "backendRuntimeRefresh",
            "backendRuntimeRequestTimeout",
            "backendRuntimeFrameAgeLimit",
            "backendRuntimeSameFrameLimit",
            "backendRuntimeReconnectAttempts",
            "backendRuntimeMeasurementDeltaHistoryLimit",
            "saveBackendRuntimeParameters",
            "undoBackendRuntimeParameters",
            "restoreBackendRuntimeParameterDefaults",
            "backendRuntimeParameterSummary",
            "webRuntimeParameterForm",
            "webRuntimeFrontendRefresh",
            "webRuntimeFrontendRequestTimeout",
            "webRuntimeLogPageSize",
            "webRuntimeLogCacheLimit",
            "webRuntimeReceiveStateSync",
            "webRuntimeDiagramElectricFlowThreshold",
            "webRuntimeDiagramHydrogenFlowThreshold",
            "saveRuntimeParameters",
            "undoRuntimeParameters",
            "restoreRuntimeParameterDefaults",
            "runtimeParameterModelName",
            "runtimeParameterUpdatedAt",
            "backendRuntimeParameterState",
            "webRuntimeParameterState",
        ):
            self.assertIn(f'id="{element_id}"', html)

        self.assertNotIn('id="webRuntimeBackendRefresh"', html)

    def test_both_frontends_load_save_reset_and_apply_model_scoped_settings(self):
        scripts = {
            "simulator": (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8"),
            "trainee": (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8"),
        }

        for role, script in scripts.items():
            self.assertIn('api("/api/runtime-settings"', script)
            self.assertIn("function loadWebRuntimeSettings", script)
            self.assertIn("function saveWebRuntimeSettings", script)
            self.assertIn("function undoWebRuntimeSettings", script)
            self.assertIn("function restoreWebRuntimeDefaults", script)
            self.assertIn("function resetWebRuntimeSettingsState", script)
            self.assertIn("restartRefreshScheduler();", script)
            self.assertIn("runtimeParameterUpdatedAt", script)
            self.assertIn("runtimeParameterModelName", script)
            self.assertNotIn("const API_REQUEST_TIMEOUT_MS = 30000", script)
            self.assertNotIn("const TRACE_HISTORY_LIMIT = 45000", script)
            self.assertNotIn("trace_history_limit", script)

        self.assertIn('activeRuntimeSetting("curve_request_timeout_seconds")', scripts["simulator"])
        self.assertIn('activeRuntimeSetting("runtime_log_delta_batch_size")', scripts["simulator"])
        self.assertIn('activeRuntimeSetting("runtime_log_history_batch_size")', scripts["simulator"])
        self.assertIn('activeRuntimeSetting("diagram_flow_electric_threshold_kw")', scripts["simulator"])
        self.assertIn('activeRuntimeSetting("diagram_flow_hydrogen_threshold_nm3_h")', scripts["simulator"])
        self.assertNotIn("const CURVE_REQUEST_TIMEOUT_MS = 8000", scripts["simulator"])

        self.assertIn('activeRuntimeSetting("receive_state_sync_seconds")', scripts["trainee"])
        self.assertIn('activeRuntimeSetting("receive_max_reconnect_attempts")', scripts["trainee"])
        self.assertIn('activeRuntimeSetting("diagram_flow_electric_threshold_kw")', scripts["trainee"])
        self.assertIn('activeRuntimeSetting("diagram_flow_hydrogen_threshold_nm3_h")', scripts["trainee"])
        self.assertIn("const RUNTIME_PARAMETER_GROUPS", scripts["trainee"])
        self.assertIn('async function saveWebRuntimeSettings(group = "web")', scripts["trainee"])
        self.assertIn("runtimeParameterGroupValues(pendingDraft, group)", scripts["trainee"])
        self.assertIn('saveWebRuntimeSettings("backend")', scripts["trainee"])
        self.assertIn('saveWebRuntimeSettings("web")', scripts["trainee"])
        self.assertNotIn("const RECEIVE_STATE_SYNC_INTERVAL_MS = 5000", scripts["trainee"])
        self.assertNotIn("const RECEIVE_MAX_RECONNECT_ATTEMPTS = 3", scripts["trainee"])


if __name__ == "__main__":
    unittest.main()
