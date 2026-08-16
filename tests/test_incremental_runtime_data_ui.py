from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IncrementalRuntimeDataUiTest(unittest.TestCase):
    def _script(self, console: str) -> str:
        return (ROOT / "simu" / "web" / console / "app.js").read_text(encoding="utf-8")

    def test_simulator_fast_poll_uses_incremental_logs_and_measurements(self):
        script = self._script("simulator")

        self.assertIn('params.set("logs", "1")', script)
        self.assertIn('params.set("runtime_log_after_seq", String(state.runtimeLogBackendSeq || 0))', script)
        self.assertIn("embeddedRuntimeLogDeltaReceived", script)
        self.assertIn("applyEmbeddedRuntimeLogDelta", script)
        self.assertIn('params.set("measurements", "0")', script)
        self.assertIn("refreshRuntimeLogs", script)
        self.assertIn("fetchRuntimeLogHistoryPage", script)
        self.assertIn("before_seq=${oldestSeq}", script)
        self.assertIn('api(`/api/runtime-logs?after_seq=${state.runtimeLogBackendSeq}', script)
        self.assertIn("state.runtimeLogBackendSeq = reset ? nextBackendSeq", script)
        self.assertIn("refreshMeasurementDelta", script)
        self.assertIn('api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}', script)
        self.assertIn("applyMeasurementDelta", script)
        self.assertIn("if (payload.reset) {", script)
        self.assertIn("measurements.real = [];", script)
        self.assertIn("measurements.scada = [];", script)
        self.assertIn("state.measurementDeltaSeq = Number(payload.seq) || 0;", script)
        self.assertIn('params.set("device_runtime_supplement", "1")', script)
        self.assertIn('const DEVICE_RUNTIME_SUPPLEMENT_ENCODING = "device-runtime-supplement-arrays-v1";', script)
        self.assertIn("hydrateMeasurementBackedDeviceRuntime", script)
        self.assertIn("sampleCurvePointsForCanvas", script)
        self.assertIn("compactTraceHistory", script)

    def test_trainee_fast_poll_uses_incremental_measurements_and_live_cells(self):
        script = self._script("trainee")

        self.assertIn('params.set("measurements", "0");', script)
        self.assertIn("function receiveStateSyncIntervalMs", script)
        self.assertIn('activeRuntimeSetting("receive_state_sync_seconds")', script)
        self.assertIn("lastReceiveStateSyncAtMs", script)
        self.assertIn("Date.now() - state.lastReceiveStateSyncAtMs < receiveStateSyncIntervalMs()", script)
        self.assertIn('return `/api/trainee/ui-frame?', script)
        self.assertIn('payload.encoding !== "trainee-ui-frame-v1"', script)
        self.assertIn("applyTraineeUiFrame", script)
        self.assertIn('params.set("device_runtime_supplement", "1")', script)
        self.assertIn('const DEVICE_RUNTIME_SUPPLEMENT_ENCODING = "device-runtime-supplement-arrays-v1";', script)
        self.assertIn("hydrateMeasurementBackedDeviceRuntime", script)
        self.assertIn("teacherMeasurementDeltaAddress", script)
        self.assertIn("refreshMeasurementDelta", script)
        self.assertIn("applyMeasurementDelta", script)
        self.assertIn("if (payload.reset) {", script)
        self.assertIn("delete measurements.real;", script)
        self.assertIn("measurements.scada = [];", script)
        self.assertIn("state.measurementDeltaSeq = Number(payload.seq) || 0;", script)
        self.assertIn("updateMeasurementTableLiveCells", script)
        self.assertIn("sampleCurvePointsForCanvas", script)
        self.assertIn("compactTraceHistory", script)


if __name__ == "__main__":
    unittest.main()
