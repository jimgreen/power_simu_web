from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from simu.renewable_control import TraineeRenewableControlManager
from simu.trainee_exchange import TraineeControlSnapshot


ROOT = Path(__file__).resolve().parents[1]


def _manager_for(service_instance_id: str) -> TraineeRenewableControlManager:
    service = SimpleNamespace(
        model_id="model-a",
        service_instance_id=service_instance_id,
        lock=threading.RLock(),
    )
    snapshot = TraineeControlSnapshot(
        snapshot={},
        source="trainee-live",
        age_seconds=0.0,
        error=None,
        receive_active=True,
        ready=True,
        revision=1,
        connection_signature=("learner", 1),
    )
    return TraineeRenewableControlManager(
        service,
        snapshot_provider=lambda _model_id: snapshot,
        receive_status_provider=lambda _model_id: {
            "receiveActive": True,
            "ready": True,
            "canRun": True,
            "canCalculate": True,
            "canDispatch": True,
        },
        command_sink=lambda _model_id, _payload: {"set_values": 0},
        start_worker=False,
    )


def test_backend_exposes_controller_instance_for_browser_restart_detection():
    manager = _manager_for("service-generation-a")
    try:
        payload = manager.state("model-a")
    finally:
        manager.close()

    assert payload["controllerInstanceId"] == "service-generation-a"


def test_browser_accepts_lower_revision_after_controller_lifecycle_changes():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    state_block = script.split("renewableControl: {", 1)[1].split("overviewBottomHeight", 1)[0]
    reset_block = script.split("function resetRenewableControlView", 1)[1].split(
        "function renewableDataSourceLabel",
        1,
    )[0]
    apply_block = script.split("function applyRenewableControlState", 1)[1].split(
        "async function refreshRenewableControlState",
        1,
    )[0]

    assert 'controllerInstanceId: ""' in state_block
    assert 'controllerInstanceId: ""' in reset_block
    assert "const controllerLifecycleChanged" in apply_block
    assert "!controllerLifecycleChanged" in apply_block
    assert "incomingRevision < Number(control.revision" in apply_block
    assert "resetRenewableControlHistoryForLifecycle(control)" in apply_block
    assert "controllerInstanceId: incomingControllerInstanceId" in apply_block


def test_controller_lifecycle_reset_clears_stale_logs_and_trend_cursors():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    reset_block = script.split(
        "function resetRenewableControlHistoryForLifecycle",
        1,
    )[1].split("function applyRenewableControlState", 1)[0]

    assert "control.logs = []" in reset_block
    assert "control.revision = -1" in reset_block
    assert "resetRenewableTrendHistoryHydration({ clearHistory: true })" in reset_block
    assert 'control.latestTrendSampleKey = ""' in reset_block
    assert "control.lastControlLogRenderKey = \"\"" in reset_block


def test_browser_uses_cached_renewable_state_and_plan_revision_cursor():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    state_block = script.split("renewableControl: {", 1)[1].split("overviewBottomHeight", 1)[0]
    path_block = script.split("function renewableControlApiPath", 1)[1].split(
        "function renewableTrendHistoryApiPath",
        1,
    )[0]
    apply_block = script.split("function applyRenewableControlState", 1)[1].split(
        "async function refreshRenewableControlState",
        1,
    )[0]

    assert "planRevision: -1" in state_block
    assert 'params.set("after_plan_revision"' in path_block
    assert 'params.set("after_controller_instance_id"' in path_block
    assert 'params.set("trend", "0")' in path_block
    assert "after_trend_sample_key" not in path_block
    assert 'Object.prototype.hasOwnProperty.call(payload, "lastPlan")' in apply_block
    assert "control.lastPlan = payload.lastPlan || null" in apply_block
    assert "renewableTrendDeltaItems(payload)" in apply_block
    assert "refreshRenewableControlState({ preview: true })" not in script


def test_browser_decodes_versioned_trend_rows_without_changing_legacy_points():
    node = shutil.which("node")
    if not node:
        return
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    decoder = "function renewableTrendDeltaItems" + script.split(
        "function renewableTrendDeltaItems",
        1,
    )[1].split("function mergeRenewableTrendDelta", 1)[0]
    payloads = {
        "legacy": {"trend": [{"sampleKey": "legacy", "value": None}]},
        "encoded": {
            "trendEncoding": "arrays-v1",
            "trendFields": ["sampleKey", "value", "optional"],
            "trendRows": [["sample-1", None, None], ["sample-2", 2, 3]],
            "trendMissing": [[0, [2]]],
        },
        "delta": {
            "trendEncoding": "arrays-v1",
            "trendRows": [["sample-2", 4, 5]],
        },
    }
    node_script = (
        f"{decoder}\n"
        f"const payloads = {json.dumps(payloads)};\n"
        "console.log(JSON.stringify({"
        "legacy: renewableTrendDeltaItems(payloads.legacy),"
        "encoded: renewableTrendDeltaItems(payloads.encoded),"
        "delta: renewableTrendDeltaItems(payloads.delta)"
        "}));"
    )
    completed = subprocess.run(
        [node, "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    decoded = json.loads(completed.stdout)

    assert decoded["legacy"] == [{"sampleKey": "legacy", "value": None}]
    assert decoded["encoded"] == [
        {"sampleKey": "sample-1", "value": None},
        {"sampleKey": "sample-2", "value": 2, "optional": 3},
    ]
    assert decoded["delta"] == [
        {"sampleKey": "sample-2", "value": 4, "optional": 5},
    ]


def test_browser_lazy_loads_only_missing_visible_renewable_trend_fields():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    history_path_block = script.split(
        "function renewableTrendHistoryApiPath",
        1,
    )[1].split("function renewableTrendLifecycleChanged", 1)[0]
    ensure_block = script.split(
        "async function ensureRenewableTrendHistoryForVisibleSeries",
        1,
    )[1].split("async function refreshRenewableControlState", 1)[0]

    assert '"/api/trainee/renewable-control/trend"' in history_path_block
    assert 'params.set("fields", requestedFields.join(","))' in history_path_block
    assert 'params.set("after_trend_sample_key", cursor)' in history_path_block
    assert "renewableTrendRequestedFields()" in ensure_block
    assert "renewableTrendFieldCursors" in ensure_block
    assert "latestTrendSampleKey" in ensure_block


def test_partial_renewable_trend_field_merge_preserves_already_loaded_curves():
    node = shutil.which("node")
    if not node:
        return
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    merger = "function mergeRenewableTrendFieldDelta" + script.split(
        "function mergeRenewableTrendFieldDelta",
        1,
    )[1].split("function mergeRenewableTrendDelta", 1)[0]
    node_script = f"""
{merger}
const merged = mergeRenewableTrendFieldDelta(
  [
    {{sampleKey: "sample-1", runId: 1, stepCount: 1, minute: 1, fieldA: 10}},
    {{sampleKey: "sample-2", runId: 1, stepCount: 2, minute: 2, fieldA: 11}},
  ],
  [
    {{sampleKey: "sample-1", runId: 1, stepCount: 1, minute: 1, fieldB: 20}},
    {{sampleKey: "sample-2", runId: 1, stepCount: 2, minute: 2, fieldB: 21}},
  ],
);
console.log(JSON.stringify(merged));
"""
    completed = subprocess.run(
        [node, "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(completed.stdout) == [
        {
            "sampleKey": "sample-1",
            "runId": 1,
            "stepCount": 1,
            "minute": 1,
            "fieldA": 10,
            "fieldB": 20,
        },
        {
            "sampleKey": "sample-2",
            "runId": 1,
            "stepCount": 2,
            "minute": 2,
            "fieldA": 11,
            "fieldB": 21,
        },
    ]
