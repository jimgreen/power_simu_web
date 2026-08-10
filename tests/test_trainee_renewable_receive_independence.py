import unittest
from pathlib import Path

from simu.renewable_control import TraineeRenewableControlManager
from simu.trainee_exchange import TraineeControlSnapshot


ROOT = Path(__file__).resolve().parents[1]


def test_receive_stop_no_longer_claims_renewable_control_keeps_running():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    persistent_issue = script.split("function stopReceiveAfterPersistentIssue", 1)[1].split(
        "function recordReceiveIssue",
        1,
    )[0]
    receive_toggle = script.split("async function toggleReceiveMode()", 1)[1].split(
        '$("modelManagementButton")',
        1,
    )[0]

    assert "noteRenewableReceiveInterruption(" in persistent_issue
    assert "noteRenewableReceiveInterruption(" in receive_toggle
    assert "新能源优先策略保持运行" not in persistent_issue
    assert "新能源优先策略保持运行" not in receive_toggle


def test_model_switch_only_changes_the_browser_view_not_another_models_controller():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("function setActiveModel", 1)[1].split("async function loadModels", 1)[0]

    assert "resetRenewableControlView(nextId)" in block
    assert "stopRenewableControl" not in block
    assert "runRenewableControlAction" not in block


def test_browser_only_refreshes_shared_backend_state_during_receive_changes():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    refresh_block = script.split("async function refresh()", 1)[1].split(
        "async function refreshFromTeacher",
        1,
    )[0]
    note_block = script.split("function noteRenewableReceiveInterruption", 1)[1].split(
        "function renderRenewablePager",
        1,
    )[0]

    assert "refreshRenewableControlState" in refresh_block
    assert "refreshRenewableControlState" in note_block
    assert "calculateRenewableControlPlan" not in script
    assert "maybeRunRenewableControl" not in script


def test_renewable_control_manager_has_no_simulator_transport_dependency():
    source = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
    manager_source = "class TraineeRenewableControlManager" + source.split(
        "class TraineeRenewableControlManager",
        1,
    )[1]

    for forbidden in (
        "teacher_api_base",
        "snapshot_path",
        "command_path",
        "urljoin(",
        "urlopen(",
        "request_json",
        "_fetch_remote_snapshot",
        "_connection(",
    ):
        assert forbidden not in manager_source


def test_renewable_control_manager_accepts_only_learner_exchange_providers():
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
    snapshot_provider = lambda _model_id: snapshot
    receive_status_provider = lambda _model_id: {
        "receiveActive": True,
        "ready": True,
        "canRun": True,
    }
    command_sink = lambda _model_id, _payload: {"set_values": 0}

    manager = TraineeRenewableControlManager(
        object(),
        snapshot_provider=snapshot_provider,
        receive_status_provider=receive_status_provider,
        command_sink=command_sink,
        start_worker=False,
    )
    try:
        assert manager.snapshot_provider is snapshot_provider
        assert manager.receive_status_provider is receive_status_provider
        assert manager.command_sink is command_sink
    finally:
        manager.close()


def test_renewable_control_buttons_require_active_receive_mode():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    render_block = script.split("function renderRenewableControl(snapshot", 1)[1].split(
        "async function toggleRenewableAuto",
        1,
    )[0]
    state_block = script.split("function applyRenewableControlState", 1)[1].split(
        "async function refreshRenewableControlState",
        1,
    )[0]
    reset_block = script.split("function resetRenewableControlView", 1)[1].split(
        "function renewableTrendLifecycleChanged",
        1,
    )[0]

    assert "const receiveReady" in render_block
    assert "control.receiveActive" in render_block
    assert "!receiveReady" in render_block
    assert "receiveActive: Boolean(payload.receiveActive)" in state_block
    assert "canRun: Boolean(payload.canRun)" in state_block
    assert "receiveActive: false" in reset_block
    assert "canRun: false" in reset_block


def test_renewable_ui_distinguishes_running_waiting_and_explicit_stop_states():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
    state_block = script.split("renewableControl: {", 1)[1].split(
        "overviewBottomHeight",
        1,
    )[0]
    apply_block = script.split("function applyRenewableControlState", 1)[1].split(
        "async function refreshRenewableControlState",
        1,
    )[0]
    render_block = script.split("function renderRenewableControl(snapshot", 1)[1].split(
        "async function toggleRenewableAuto",
        1,
    )[0]
    toggle_block = script.split("async function toggleRenewableAuto", 1)[1].split(
        "async function runRenewableControlOnce",
        1,
    )[0]

    assert "desiredEnabled: false" in state_block
    assert "resumePending: false" in state_block
    assert 'class="renewable-backend-state"' in html
    assert "后台运行状态" in html
    assert 'id="renewableControlState"' in html
    assert "desiredEnabled: Boolean(payload.desiredEnabled)" in apply_block
    assert "resumePending: Boolean(payload.resumePending)" in apply_block
    assert 'button.textContent = control.desiredEnabled ? "停止实时控制" : "启动实时控制"' in render_block
    assert '"等待接收后恢复"' in render_block
    assert '"已停止"' in render_block
    assert 'const action = state.renewableControl.desiredEnabled ? "stop" : "start"' in toggle_block


def test_receive_api_immediately_notifies_the_backend_controller():
    server = (ROOT / "simu/server.py").read_text(encoding="utf-8")
    receive_block = server.split("def _handle_trainee_receive", 1)[1].split(
        "def _handle_api_get",
        1,
    )[0]

    assert '"receive_state_changed_for_service"' in receive_block
    assert "notify_renewable(target)" in receive_block


def test_renewable_ui_uses_learner_exchange_source_labels_and_first_frame_status():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function renewableDataSourceLabel" in script
    assert '"trainee-live": "学员台实时数据"' in script
    assert '"trainee-cache": "学员台缓存数据"' in script
    assert "学员台正在等待第一份实时数据。" in script


class TraineeRenewableReceiveRecoveryUiContractTest(unittest.TestCase):
    def test_status_text_uses_backend_status_after_receive_is_ready(self):
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        status_block = script.split('const status = $("renewableControlStatus");', 1)[1].split(
            "if (summary)",
            1,
        )[0]

        self.assertIn("!receiveReady", status_block)
        self.assertIn("control.resumePending", status_block)
        self.assertIn("control.lastStatus", status_block)
        self.assertIn("renewablePrerequisiteStatus(control)", status_block)
        self.assertIn('status.classList.toggle("is-ok", control.enabled)', status_block)
        self.assertIn('status.classList.toggle("is-warning", control.resumePending)', status_block)
