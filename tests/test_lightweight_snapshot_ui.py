from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LightweightSnapshotUiTest(unittest.TestCase):
    def _merge_snapshot_static_field_results(self, script: str, next_function: str):
        merge_source = "function mergeSnapshot" + script.split("function mergeSnapshot", 1)[1].split(
            next_function,
            1,
        )[0]
        node_script = f"""
const STATIC_SNAPSHOT_KEYS = ["files", "source_files", "work_files", "definitions", "curves", "settings", "device_parameters", "diagram"];
function staticMetaSignature(meta) {{ return JSON.stringify(meta || null); }}
function staticMetaMatches(left, right) {{ return staticMetaSignature(left) === staticMetaSignature(right); }}
{merge_source}
const oldDiagram = {{ svg: "old-svg" }};
const changedModel = mergeSnapshot(
  {{ model: {{ id: "old" }}, static_meta: {{ diagram: {{ signature: "old" }} }}, diagram: oldDiagram }},
  {{ model: {{ id: "new" }}, static_meta: {{ diagram: {{ signature: "new" }} }} }},
);
const changedMeta = mergeSnapshot(
  {{ model: {{ id: "same" }}, static_meta: {{ diagram: {{ signature: "old" }} }}, diagram: oldDiagram }},
  {{ model: {{ id: "same" }}, static_meta: {{ diagram: {{ signature: "new" }} }} }},
);
const unchangedMeta = mergeSnapshot(
  {{ model: {{ id: "same" }}, static_meta: {{ diagram: {{ signature: "same" }} }}, diagram: oldDiagram }},
  {{ model: {{ id: "same" }}, static_meta: {{ diagram: {{ signature: "same" }} }} }},
);
process.stdout.write(JSON.stringify([
  Object.hasOwn(changedModel, "diagram"),
  Object.hasOwn(changedMeta, "diagram"),
  Object.hasOwn(unchangedMeta, "diagram"),
]));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

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
        self.assertIn('params.set("devices", "0");', script)
        self.assertIn("params.set(\"commands\", pageNeedsCommands(page) ? \"1\" : \"0\");", script)
        self.assertIn("function pageNeedsMeasurementDelta", script)
        self.assertIn("function pageNeedsRuntimeLogDelta", script)
        self.assertIn('params.set("lite", "1");', script)
        self.assertIn("function refreshRuntimeLogs", script)
        self.assertIn("function refreshMeasurementDelta", script)
        self.assertIn("const snapshot = await refreshSnapshotPayload(activePage)", script)
        self.assertIn("if (state.refreshRequestActive) return;", script)
        self.assertIn("snapshot.curve_boundary", script)

    def test_trainee_polling_uses_lite_remote_snapshot_with_initialized_local_definitions(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function mergeSnapshot", script)
        self.assertIn("function snapshotPollPath", script)
        self.assertIn("function teacherSnapshotPollAddress", script)
        self.assertIn("const STATIC_CACHE_STORAGE_KEY", script)
        self.assertIn("function staticSnapshotKeysForPage", script)
        self.assertIn("function restoreStaticSnapshotCache", script)
        self.assertIn("function persistStaticSnapshotCache", script)
        self.assertIn("function staticSnapshotMissingKeys", script)
        self.assertIn("function pageNeedsDevices", script)
        self.assertIn("function pageNeedsCommands", script)
        self.assertIn('"overview": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertIn('"measurements": ["files", "source_files", "work_files", "definitions"]', script)
        self.assertIn('"commands": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertIn('params.set("static", "0");', script)
        self.assertIn("params.set(\"devices\", pageNeedsDevices(page) ? \"1\" : \"0\");", script)
        self.assertIn("params.set(\"commands\", pageNeedsCommands(page) ? \"1\" : \"0\");", script)
        self.assertIn('params.set("lite", "1");', script)
        self.assertIn("function pageNeedsRuntimeLogs", script)
        self.assertIn('return ["overview", "history"].includes(page);', script)
        self.assertIn("teacherMeasurementDeltaAddress", script)
        self.assertIn("function refreshMeasurementDelta", script)
        self.assertIn("let snapshot = mergeSnapshot(state.snapshot, await api(snapshotPollPath(page)))", script)
        self.assertIn("ensureLocalDefinitionSnapshot", script)
        self.assertIn("mergeTeacherSnapshotWithLocalDefinitions", script)
        self.assertIn("const remoteSnapshot = await teacherSnapshotApi(page)", script)

    def test_static_snapshot_merge_drops_previous_model_or_changed_revision_fields(self):
        simulator_script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertEqual(
            self._merge_snapshot_static_field_results(simulator_script, "function snapshotPollPath"),
            [False, False, True],
        )
        self.assertEqual(
            self._merge_snapshot_static_field_results(trainee_script, "function pageNeedsRuntimeLogs"),
            [False, False, True],
        )

    def test_static_snapshot_cache_version_invalidates_pre_fix_cross_model_entries(self):
        simulator_script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('const STATIC_CACHE_STORAGE_KEY = "polarSimulatorStaticCacheV2";', simulator_script)
        self.assertIn('const STATIC_CACHE_STORAGE_KEY = "polarTraineeStaticCacheV2";', trainee_script)


if __name__ == "__main__":
    unittest.main()
