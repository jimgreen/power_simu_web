from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trainee_receive_start_validates_link_snapshot_and_local_definition():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "fetchTeacherSnapshot(connection)" in script
    assert "fetchLocalDefinitionSnapshot" in script
    assert "state.localDefinitionSnapshot = localSnapshot" in script
    assert "state.receiveMode = true" in script
    assert "acceptTeacherSnapshot(teacherSnapshot, state.receiveEpoch)" in script
    start_block = script.split("async function startReceiveModeFromLink()", 1)[1].split("function runtimeLogTime", 1)[0]
    assert "openReceiveWarningDialog" not in start_block
    assert "addRuntimeLog(\"接收模式\", \"模拟台交互链接\", \"启动接收失败\"" in script


def test_trainee_receive_runtime_logs_each_issue_and_stops_after_consecutive_failures():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "RECEIVE_MAX_RECONNECT_ATTEMPTS = 3" in script
    assert "function recordReceiveIssue" in script
    assert "连续告警 ${attempt}/${RECEIVE_MAX_RECONNECT_ATTEMPTS}" in script
    assert "function stopReceiveAfterPersistentIssue" in script
    assert "attemptTeacherReconnect(epoch)" in script
    assert "resolveTeacherInteractionLink(state.interactionLink)" in script
    assert "通讯失败" in script
    assert "数据接收失败" in script
    assert "模拟台未启动仿真" in script
    assert "已停止接收" in script


def test_trainee_receive_runtime_definition_mismatch_warning_dialog():
    html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    assert 'id="receiveWarningDialog"' in html
    assert 'id="receiveWarningList"' in html
    assert "validateTeacherSnapshotDefinitions" in script
    assert "handleReceiveDefinitionMismatch" in script
    assert "recordReceiveIssue(\"实时交互\", \"定义一致性校验\", result, detail, simTime)" in script
    assert "openReceiveWarningDialog" in script
    assert ".receive-warning-list" in styles
    mismatch_block = script.split("function handleReceiveDefinitionMismatch", 1)[1].split("function validateTeacherSnapshotDefinitions", 1)[0]
    assert "state.receiveMode = false" not in mismatch_block
    assert "openReceiveWarningDialog" not in mismatch_block


def test_trainee_commands_are_sent_through_interaction_link_command_path():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "teacherCommandPath: localStorage.getItem(\"polarTeacherCommandPath\")" in script
    assert "state.teacherCommandPath = connection.commandPath" in script
    assert "localStorage.setItem(\"polarTeacherCommandPath\", state.teacherCommandPath)" in script
    assert "function teacherCommandPath()" in script
    assert "async function teacherCommandApi" in script
    assert "connectionApiUrl({ teacherApiBase }, teacherCommandPath())" in script
    assert "await teacherCommandApi({ method: \"POST\", body: JSON.stringify(payload) })" in script
    assert "await teacherCommandApi({ method: \"POST\", body: JSON.stringify(body) })" in script


def test_manual_telecontrol_and_teleadjust_commands_require_teacher_link():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function hasTeacherCommandConnection()" in script
    assert "async function postTeacherCommand(body)" in script
    assert "请先点击顶部“启动接收”，输入模拟台交互链接后再下发指令。" in script
    assert script.count("const useInteractionLink = hasTeacherCommandConnection();") >= 2
    assert "await postTeacherCommand(body)" in script
    assert "await api(\"/api/student/commands\", { method: \"POST\", body: JSON.stringify(body) })" not in script


def test_trainee_accepts_legacy_teacher_link_when_link_route_is_missing():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function legacyTeacherInteractionConnection" in script
    assert "\"/api/trainee-link\"" in script
    assert "\"/api/client-link\"" in script
    assert "Unknown API route" in script
    assert "response.status === 404" in script
    assert "snapshotPath: `/api/snapshot?model_id=${encodedModelId}`" in script
    assert "commandPath: `/api/student/commands?model_id=${encodedModelId}`" in script
