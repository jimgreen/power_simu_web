from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LightweightSnapshotUiTest(unittest.TestCase):
    def test_simulator_polling_uses_lite_snapshot_after_static_payload_is_cached(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function mergeSnapshot", script)
        self.assertIn("function snapshotPollPath", script)
        self.assertIn("function staticSnapshotKeysForPage", script)
        self.assertIn("const STATIC_CACHE_STORAGE_KEY", script)
        self.assertIn("function restoreStaticSnapshotCache", script)
        self.assertIn("function persistStaticSnapshotCache", script)
        self.assertIn("function pageNeedsDevices", script)
        self.assertIn("function pageNeedsCommands", script)
        self.assertIn('"model": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertIn('"overview": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertIn('"faults": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertNotIn('"overview": ["files", "source_files", "work_files", "definitions", "curves"', script)
        self.assertNotIn('"faults": ["files", "source_files", "work_files", "definitions", "curves"', script)
        self.assertIn("params.set(\"static\", requiredStaticKeys.join(\",\"));", script)
        self.assertIn("params.set(\"devices\", pageNeedsDevices(page) ? \"1\" : \"0\");", script)
        self.assertIn("params.set(\"commands\", pageNeedsCommands(page) ? \"1\" : \"0\");", script)
        self.assertIn("function pageNeedsMeasurementDelta", script)
        self.assertIn("function pageNeedsRuntimeLogDelta", script)
        self.assertIn('params.set("lite", "1");', script)
        self.assertIn("function refreshRuntimeLogs", script)
        self.assertIn("function refreshMeasurementDelta", script)
        self.assertIn("const snapshot = await refreshSnapshotPayload(activePage)", script)
        self.assertIn("if (state.refreshRequestActive) return;", script)
        self.assertIn("snapshot.curve_boundary", script)

    def test_trainee_polling_uses_lite_snapshot_without_breaking_teacher_definition_check(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function mergeSnapshot", script)
        self.assertIn("function snapshotPollPath", script)
        self.assertIn("function teacherSnapshotPollAddress", script)
        self.assertIn("function pageNeedsRuntimeLogs", script)
        self.assertIn('return ["overview", "history"].includes(page);', script)
        self.assertIn('return appendUrlQuery("/api/snapshot", { lite: 1, ...logParams, measurements: 0 });', script)
        self.assertIn("teacherMeasurementDeltaAddress", script)
        self.assertIn("function refreshMeasurementDelta", script)
        self.assertIn("const snapshot = mergeSnapshot(state.snapshot, await api(snapshotPollPath()))", script)
        self.assertIn("const snapshot = mergeSnapshot(state.snapshot, await teacherSnapshotApi())", script)
        self.assertIn("fetchTeacherSnapshot(connection)", script)


if __name__ == "__main__":
    unittest.main()
