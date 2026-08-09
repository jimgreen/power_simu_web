from __future__ import annotations

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
    assert "state.renewableTrendHistory = []" in reset_block
    assert "control.lastControlLogRenderKey = \"\"" in reset_block
