from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trainee_receive_start_validates_link_snapshot_and_local_definition():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert 'api("/api/trainee/connect"' in script
    assert "fetchTeacherSnapshot(connection)" in script
    assert "fetchLocalDefinitionSnapshot" in script
    assert "selectLocalDefinitionSnapshotForTeacher(connection, teacherSnapshot, activeModelIdBeforeReceive)" in script
    assert "state.localDefinitionSnapshot = definitionSnapshot" in script
    assert "state.receiveMode = true" in script
    assert "acceptTeacherSnapshot(teacherSnapshot, state.receiveEpoch)" in script
    start_block = script.split("async function startReceiveModeFromLink()", 1)[1].split("function runtimeLogTime", 1)[0]
    assert "openReceiveWarningDialog" not in start_block
    assert "addRuntimeLog(\"接收模式\", \"模拟台交互链接\", \"启动接收失败\"" in script


def test_trainee_receive_start_does_not_switch_current_display_model():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    apply_block = script.split("function applyTeacherConnection(connection)", 1)[1].split("function sortedUnique", 1)[0]
    assert "state.activeModelId = connection.modelId" not in apply_block
    assert 'localStorage.setItem("polarTraineeModelId"' not in apply_block
    assert "renderModelSelector()" not in apply_block

    start_block = script.split("async function startReceiveModeFromLink()", 1)[1].split("function runtimeLogTime", 1)[0]
    assert "const activeModelIdBeforeReceive = state.activeModelId" in start_block
    assert "selectLocalDefinitionSnapshotForTeacher(connection, teacherSnapshot, activeModelIdBeforeReceive)" in start_block
    assert "saveTraineeReceiveState(activeModelIdBeforeReceive, { active: true, frozen: false })" in start_block

    render_block = script.split("function renderSnapshot(snapshot)", 1)[1].split("function renderReceiveMode", 1)[0]
    assert 'state.snapshotSource !== "teacher"' in render_block


def test_trainee_receive_uses_teacher_definition_baseline_when_local_model_is_missing():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function hasLocalDefinitionModel" in script
    assert "function selectLocalDefinitionSnapshotForTeacher" in script
    assert "usingTeacherBaseline" in script
    assert "本地无同名模型" in script
    assert "state.localDefinitionSnapshot = definitionSnapshot" in script


def test_trainee_receive_does_not_compare_current_model_when_teacher_model_is_missing_locally():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("async function selectLocalDefinitionSnapshotForTeacher", 1)[1].split(
        "function applyTeacherConnection",
        1,
    )[0]

    assert "if (teacherModelId && hasLocalDefinitionModel(teacherModelId))" in block
    assert "if (!teacherModelId && hasLocalDefinitionModel(localModelId))" in block
    assert block.index("if (teacherModelId && hasLocalDefinitionModel(teacherModelId))") < block.index(
        "if (!teacherModelId && hasLocalDefinitionModel(localModelId))"
    )
    assert "usingTeacherBaseline: true" in block


def test_trainee_receive_poll_urls_remain_relative_before_api_prefixing():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("function appendUrlQuery", 1)[1].split("function teacherSnapshotPath", 1)[0]

    assert "const isAbsoluteUrl = /^https?:\\/\\//i.test(String(url || \"\"));" in block
    assert "return isAbsoluteUrl ? target.href : `${target.pathname}${target.search}${target.hash}`;" in block
    assert 'return `/api/trainee/snapshot?${params.toString()}`;' in script
    assert 'return appendUrlQuery("/api/trainee/measurements/delta", { after_seq: state.measurementDeltaSeq });' in script


def test_trainee_receive_fetches_static_snapshot_when_restored_receive_has_no_static_payload():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("function teacherSnapshotPollAddress(page = currentPageName(), forceStaticKeys = null)", 1)[1].split(
        "function measurementDeltaPathFromSnapshotPath",
        1,
    )[0]

    assert "const expectedTeacherModelId = String(state.teacherModelId || \"\");" in block
    assert "const requiredStaticKeys = Array.isArray(forceStaticKeys)" in block
    assert "staticSnapshotMissingKeys(state.snapshot, staticSnapshotKeysForPage(page))" in block
    assert "currentModelId !== expectedTeacherModelId" in block
    assert 'params.set("static", requiredStaticKeys.join(","));' in block
    assert 'params.set("lite", "1");' in block


def test_trainee_receive_overview_keeps_teacher_runtime_logs_for_power_flow():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("function teacherSnapshotPollAddress(page = currentPageName(), forceStaticKeys = null)", 1)[1].split(
        "function measurementDeltaPathFromSnapshotPath",
        1,
    )[0]

    assert "function pageNeedsRuntimeLogs" in script
    assert 'return ["overview", "history"].includes(page);' in script
    assert "if (pageNeedsRuntimeLogs(page)) params.set(\"log_limit\", String(snapshotLogLimit(page)));" in block
    assert 'else params.set("logs", "0");' in block
    assert 'params.set("measurements", "0");' in block
    assert 'return `/api/trainee/snapshot?${params.toString()}`;' in block


def test_trainee_receive_runtime_logs_each_issue_and_stops_after_consecutive_failures():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "RECEIVE_MAX_RECONNECT_ATTEMPTS = 3" in script
    assert "function recordReceiveIssue" in script
    assert "连续告警 ${attempt}/${RECEIVE_MAX_RECONNECT_ATTEMPTS}" in script
    assert "function stopReceiveAfterPersistentIssue" in script
    assert "attemptTeacherReconnect(epoch)" in script
    assert "resolveTeacherInteractionLink(state.interactionLink)" in script
    assert "/api/trainee/snapshot" in script
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

    assert "modelContexts:" in script
    assert "state.teacherCommandPath = connection.commandPath" in script
    assert "localStorage.setItem(\"polarTeacherCommandPath\", state.teacherCommandPath)" not in script
    assert "function teacherCommandPath()" in script
    assert "async function teacherCommandApi" in script
    assert 'api("/api/trainee/commands", options)' in script
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
    assert "fetch(connectionApiUrl(connection" not in script


def test_trainee_accepts_legacy_teacher_link_when_link_route_is_missing():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    server = (ROOT / "simu/server.py").read_text(encoding="utf-8")

    assert "function legacyTeacherInteractionConnection" in script
    assert "\"/api/trainee-link\"" in script
    assert "\"/api/client-link\"" in script
    assert "Unknown API route" not in script
    assert "response.status === 404" not in script
    assert "def _legacy_trainee_connection_from_link" in server
    assert "exc.status == 404" in server
    assert "snapshotPath: `/api/snapshot?model_id=${encodedModelId}`" in script
    assert "commandPath: `/api/student/commands?model_id=${encodedModelId}`" in script
