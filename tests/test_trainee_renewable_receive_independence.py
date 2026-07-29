from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_receive_failures_do_not_stop_backend_renewable_control():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    persistent_issue = script.split("function stopReceiveAfterPersistentIssue", 1)[1].split(
        "function recordReceiveIssue",
        1,
    )[0]
    receive_toggle = script.split("async function toggleReceiveMode()", 1)[1].split(
        '$("modelManagementButton")',
        1,
    )[0]

    assert "stopRenewableControl(" not in persistent_issue
    assert "stopRenewableControl(" not in receive_toggle
    assert "noteRenewableReceiveInterruption(" in persistent_issue
    assert "noteRenewableReceiveInterruption(" in receive_toggle
    assert 'runRenewableControlAction("stop")' not in persistent_issue
    assert 'runRenewableControlAction("stop")' not in receive_toggle


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


def test_backend_connection_is_independent_of_the_browser_receive_active_flag():
    backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
    connection_block = backend.split("def _connection", 1)[1].split("def _static_signature", 1)[0]

    assert 'receive_state.get("teacher_api_base")' in connection_block
    assert 'receive_state.get("snapshot_path")' in connection_block
    assert 'receive_state.get("active")' not in connection_block

