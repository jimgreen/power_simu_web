import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trainee_model_initialization_downloads_definitions_before_receive_start():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert 'api("/api/trainee/model-initialize"' in script
    assert "async function initializeModelFromLink()" in script
    assert "const activeModelIdBeforeInitialize = state.activeModelId" in script
    assert "model_id: activeModelIdBeforeInitialize" in script
    assert "mergeBackendReceiveState(activeModelIdBeforeInitialize" in script
    assert "state.activeModelId = activeModelIdBeforeInitialize" in script
    assert "state.localDefinitionSnapshot = null" in script
    assert "await refreshLocalSnapshotPayload" in script
    initialize_block = script.split("async function initializeModelFromLink()", 1)[1].split(
        "function runtimeLogTime",
        1,
    )[0]
    assert "state.receiveMode = true" not in initialize_block
    assert "启动接收" not in initialize_block


def test_trainee_receive_start_does_not_switch_current_display_model():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    start_block = script.split("async function startReceiveMode()", 1)[1].split("async function initializeModelFromLink", 1)[0]
    assert "const activeModelIdBeforeReceive = state.activeModelId" in start_block
    assert "ensureLocalDefinitionSnapshot(activeModelIdBeforeReceive)" in start_block
    assert "setTraineeReceiveActive(activeModelIdBeforeReceive, true)" in start_block
    assert "openReceiveLinkDialog" not in start_block
    assert "resolveTeacherInteractionLink" not in start_block
    assert "state.activeModelId =" not in start_block

    render_block = script.split("function renderSnapshot(snapshot)", 1)[1].split("function renderReceiveMode", 1)[0]
    assert 'state.snapshotSource !== "teacher"' in render_block


def test_trainee_receive_uses_initialized_local_definition_baseline():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "async function ensureLocalDefinitionSnapshot" in script
    assert "function mergeTeacherSnapshotWithLocalDefinitions" in script
    assert "state.localDefinitionSnapshot = local.snapshot" in script
    assert "STATIC_SNAPSHOT_KEYS.forEach" in script
    assert "merged[key] = localDefinitions[key]" in script
    assert "merged.model = localDefinitions.model" in script


def test_trainee_receive_keeps_local_device_definitions_but_applies_teacher_runtime_state():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function mergeTeacherRuntimeDevices" in script
    helper = "function mergeTeacherRuntimeDevices" + script.split(
        "function mergeTeacherRuntimeDevices",
        1,
    )[1].split("function mergeTeacherSnapshotWithLocalDefinitions", 1)[0]
    body = """
const localDevices = [
  {
    dev_type: "ACBreak",
    dev_name: "盒型开关-4",
    status: 1,
    run_stat: 1,
    set_values: {},
    raw: { idx: "4", status: "1", definition_only: "local" },
  },
  { dev_type: "ACBreak", dev_name: "仅本地开关", status: 1, run_stat: 1 },
];
const remoteDevices = [
  {
    dev_type: "ACBreak",
    dev_name: "盒型开关-4",
    status: 0,
    run_stat: 1,
    set_values: { p_set: 12.5 },
    raw: { idx: "4", status: "1", remote_only: "ignored" },
  },
  { dev_type: "ACBreak", dev_name: "仅远端开关", status: 0, run_stat: 1 },
];
process.stdout.write(JSON.stringify(mergeTeacherRuntimeDevices(localDevices, remoteDevices)));
"""
    result = subprocess.run(
        ["node", "-e", f"{helper}\n{body}"],
        check=True,
        capture_output=True,
        text=True,
    )
    merged = json.loads(result.stdout)
    assert len(merged) == 2
    assert merged[0]["status"] == 0
    assert merged[0]["run_stat"] == 1
    assert merged[0]["set_values"] == {"p_set": 12.5}
    assert merged[0]["raw"] == {"idx": "4", "status": "1", "definition_only": "local"}
    assert merged[1]["dev_name"] == "仅本地开关"
    assert all(device["dev_name"] != "仅远端开关" for device in merged)

    merge_block = script.split("function mergeTeacherSnapshotWithLocalDefinitions", 1)[1].split(
        "function applyTeacherConnection",
        1,
    )[0]
    assert "mergeTeacherRuntimeDevices(localDefinitions.devices, merged.devices)" in merge_block


def test_trainee_receive_start_uses_saved_backend_link_without_resolving_or_importing_again():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("async function startReceiveMode()", 1)[1].split("async function initializeModelFromLink", 1)[0]

    assert 'api("/api/trainee/receive"' in script
    assert "state.modelInitialized" in block
    assert "setTraineeReceiveActive(activeModelIdBeforeReceive, true)" in block
    assert "receiveLinkInput" not in block
    assert "/api/trainee/model-initialize" not in block
    assert "/api/trainee/connect" not in block


def test_trainee_receive_buttons_follow_initialized_and_receiving_state():
    html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert 'id="modelInitializeButton"' in html
    assert 'id="traineeRunToggle"' in html
    block = script.split("function renderReceiveMode(extraText = \"\")", 1)[1].split(
        "function curveMinute",
        1,
    )[0]
    assert "initializeButton.disabled = state.receiveMode" in block
    assert "button.disabled = !state.receiveMode && !state.modelInitialized" in block
    assert 'button.textContent = state.receiveMode ? "停止接收" : "启动接收"' in block


def test_trainee_overview_displays_the_initialized_simulator_model_name():
    html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "模拟台模型" in html
    assert 'id="teacherModelDisplayName"' in html
    render_block = script.split("function renderReceiveMode(extraText = \"\")", 1)[1].split(
        "function curveMinute",
        1,
    )[0]
    assert 'const teacherModelDisplayName = $("teacherModelDisplayName");' in render_block
    assert 'teacherModelDisplayName.textContent = state.teacherModelName || state.teacherModelId || "--";' in render_block


def test_trainee_migrates_legacy_saved_links_to_initialized_frontend_contexts():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function storedContextInitialized" in script
    context_block = script.split("function activeModelContext", 1)[1].split(
        "function serializableModelContext",
        1,
    )[0]
    assert "storedContextInitialized(stored)" in context_block
    assert 'Object.prototype.hasOwnProperty.call(context, "modelInitialized")' in script
    assert "context.interactionLink" in script


def test_trainee_does_not_display_the_local_model_name_as_the_simulator_model():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    context_block = script.split("function receiveContextFromBackend", 1)[1].split(
        "function receiveStatePayloadFromContext",
        1,
    )[0]

    assert "payload.teacher_model_name || payload.teacherModelName" in context_block
    assert "payload.model_name" not in context_block


def test_teacher_refresh_does_not_overwrite_simulator_name_with_local_definition_name():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    render_block = script.split("function renderSnapshot(snapshot)", 1)[1].split(
        "function renderReceiveMode",
        1,
    )[0]

    assert "state.teacherModelName = snapshot.model.name" not in render_block


def test_trainee_receive_poll_urls_remain_relative_before_api_prefixing():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("function appendUrlQuery", 1)[1].split("function teacherSnapshotPath", 1)[0]

    assert "const isAbsoluteUrl = /^https?:\\/\\//i.test(String(url || \"\"));" in block
    assert "return isAbsoluteUrl ? target.href : `${target.pathname}${target.search}${target.hash}`;" in block
    assert 'return `/api/trainee/snapshot?${params.toString()}`;' in script
    assert 'return appendUrlQuery("/api/trainee/measurements/delta", { after_seq: state.measurementDeltaSeq });' in script


def test_trainee_receive_never_requests_remote_static_definitions():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    block = script.split("function teacherSnapshotPollAddress(page = currentPageName(), forceStaticKeys = null)", 1)[1].split(
        "function measurementDeltaPathFromSnapshotPath",
        1,
    )[0]

    assert 'params.set("static", "0");' in block
    assert 'params.set("lite", "1");' in block
    assert "requiredStaticKeys" not in block
    assert "staticSnapshotMissingKeys" not in block


def test_frozen_trainee_bootstraps_missing_page_snapshot_before_short_circuit():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    refresh_block = script.split("async function refresh()", 1)[1].split(
        "async function refreshFromTeacher",
        1,
    )[0]

    assert "function frozenSnapshotNeedsBootstrap" in script
    assert "async function refreshLocalSnapshotPayload" in script
    assert "const bootstrapFrozenSnapshot = frozenSnapshotNeedsBootstrap(state.snapshot, page);" in refresh_block
    assert "if (state.frozen && !bootstrapFrozenSnapshot)" in refresh_block
    assert "const snapshot = await refreshLocalSnapshotPayload(page);" in refresh_block
    assert refresh_block.index("const snapshot = await refreshLocalSnapshotPayload(page);") > refresh_block.index(
        "if (state.frozen && !bootstrapFrozenSnapshot)"
    )


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
    reconnect_block = script.split("async function attemptTeacherReconnect(epoch)", 1)[1].split(
        "async function startReceiveMode",
        1,
    )[0]
    assert "teacherSnapshotApi" in reconnect_block
    assert "resolveTeacherInteractionLink" not in reconnect_block
    assert "/api/trainee/model-initialize" not in reconnect_block
    assert "/api/trainee/snapshot" in script
    assert "通讯失败" in script
    assert "数据接收失败" in script
    assert "模拟台未启动仿真" in script
    assert "已停止接收" in script


def test_trainee_receive_runtime_warning_dialog_remains_available_for_connection_failures():
    html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    assert 'id="receiveWarningDialog"' in html
    assert 'id="receiveWarningList"' in html
    assert "openReceiveWarningDialog" in script
    assert ".receive-warning-list" in styles


def test_trainee_commands_are_sent_through_interaction_link_command_path():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "modelContexts:" in script
    assert "state.teacherCommandPath = connection.commandPath" in script
    assert "localStorage.setItem(\"polarTeacherCommandPath\", state.teacherCommandPath)" not in script
    assert "function teacherCommandPath()" in script
    assert "async function teacherCommandApi" in script
    assert 'api("/api/trainee/commands", options)' in script
    assert "await teacherCommandApi({ method: \"POST\", body: JSON.stringify(body) })" in script
    backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
    assert 'connection["command_path"]' in backend
    assert 'self.request_json(command_url, method="POST", payload=payload)' in backend


def test_manual_telecontrol_and_teleadjust_commands_require_teacher_link():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "function hasTeacherCommandConnection()" in script
    assert "async function postTeacherCommand(body)" in script
    assert "请先完成顶部“模型初始化”并启动接收后再下发指令。" in script
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
