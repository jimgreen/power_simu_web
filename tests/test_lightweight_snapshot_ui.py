from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LightweightSnapshotUiTest(unittest.TestCase):
    def test_simulator_polling_uses_lite_snapshot_after_static_payload_is_cached(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function mergeSnapshot", script)
        self.assertIn("function snapshotPollPath", script)
        self.assertIn('return "/api/snapshot?lite=1&logs=0&measurements=0";', script)
        self.assertIn("function refreshRuntimeLogs", script)
        self.assertIn("function refreshMeasurementDelta", script)
        self.assertIn("const snapshot = mergeSnapshot(state.snapshot, await api(snapshotPollPath()))", script)
        self.assertIn("if (state.refreshRequestActive) return;", script)

    def test_trainee_polling_uses_lite_snapshot_without_breaking_teacher_definition_check(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function mergeSnapshot", script)
        self.assertIn("function snapshotPollPath", script)
        self.assertIn("function teacherSnapshotPollAddress", script)
        self.assertIn('return "/api/snapshot?lite=1&logs=0&measurements=0";', script)
        self.assertIn("teacherMeasurementDeltaAddress", script)
        self.assertIn("function refreshMeasurementDelta", script)
        self.assertIn("const snapshot = mergeSnapshot(state.snapshot, await api(snapshotPollPath()))", script)
        self.assertIn("const snapshot = mergeSnapshot(state.snapshot, await teacherSnapshotApi())", script)
        self.assertIn("fetchTeacherSnapshot(connection)", script)


if __name__ == "__main__":
    unittest.main()
