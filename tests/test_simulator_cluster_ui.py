from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_simulator_header_has_selected_model_service_start_stop_control():
    html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

    assert 'id="modelServiceToggle"' in html
    assert 'id="modelServiceState"' in html
    assert "toggleActiveModelService" in script
    assert '"/api/simulator-services/start"' in script
    assert '"/api/simulator-services/stop"' in script


def test_model_management_context_menu_tracks_selected_model_service_state():
    html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

    assert 'data-model-context-action="service-toggle"' in html
    menu_state_block = script.split("function updateModelContextMenuActions", 1)[1].split(
        "\n}", 1
    )[0]
    assert 'serviceState === "running"' in menu_state_block
    assert 'running ? "停止" : "启动"' in menu_state_block
    assert 'serviceState === "starting" || serviceState === "stopping"' in menu_state_block
    assert "state.modelServiceOperationActive" in menu_state_block

    action_block = script.split("function handleModelContextMenuAction", 1)[1].split(
        "\n}", 1
    )[0]
    assert 'case "service-toggle"' in action_block
    assert "toggleSelectedManagementModelService()" in action_block

    service_block = script.split("async function setModelServiceRunning", 1)[1].split(
        "\n}", 1
    )[0]
    assert 'body: JSON.stringify({ model_id: targetModelId })' in service_block
    assert 'shouldRun ? "/api/simulator-services/start"' in service_block
    assert 'targetModelId === state.activeModelId' in service_block


def test_interaction_link_sits_between_service_control_and_simulation_mode():
    html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
    styles = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")

    service_position = html.index('class="model-service-control"')
    service_toggle_position = html.index('id="modelServiceToggle"')
    service_state_position = html.index('id="modelServiceState"')
    interaction_link_position = html.index('id="traineeLinkButton"')
    simulation_mode_position = html.index('class="simulation-mode-switcher"')

    assert service_position < service_toggle_position < service_state_position
    assert service_position < interaction_link_position < simulation_mode_position
    interaction_link_styles = styles.split(".trainee-link-button {", 1)[1].split("}", 1)[0]
    assert "margin-right: 12px;" in interaction_link_styles


def test_stopped_model_service_disables_and_grays_dependent_header_controls():
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")

    assert "function modelServiceDependentControlsDisabled()" in script
    availability_block = script.split(
        "function renderModelServiceDependentControls", 1
    )[1].split("\n}", 1)[0]
    assert 'classList.toggle("is-model-service-stopped", controlsDisabled)' in availability_block
    assert "traineeLinkButton.disabled = controlsDisabled" in availability_block
    assert 'traineeLinkButton.setAttribute("aria-disabled"' in availability_block
    assert "modelServiceToggle" not in availability_block

    clock_block = script.split("function clockControlButtonUnavailable", 1)[1].split("\n}", 1)[0]
    assert "state.clockControlOperationActive" in clock_block
    assert "modelServiceDependentControlsDisabled()" in clock_block
    assert "clockControlButtonDisabled(action, clockState)" in clock_block

    mode_block = script.split("function renderCurveModeControls", 1)[1].split("\n}", 1)[0]
    assert "const controlsDisabled = modelServiceDependentControlsDisabled();" in mode_block
    assert "selector.disabled = modeLocked || controlsDisabled" in mode_block

    assert ".topbar.is-model-service-stopped .trainee-link-button" in styles
    assert ".topbar.is-model-service-stopped .simulation-mode-switcher" in styles
    assert ".topbar.is-model-service-stopped .top-clock-strip" in styles


def test_simulator_frontend_uses_proxy_for_control_plane_and_child_for_model_data():
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

    assert "controlPlaneApiBase" in script
    assert "activeModelServiceBase" in script
    assert "const requestBase = controlPlane ? controlPlaneApiBase : activeModelServiceBase()" in script
    assert 'api("/api/models", { modelScoped: false, controlPlane: true })' in script
    assert "generatedTraineeLink" in script
    assert "activeModelServiceBase()" in script.split("function generatedTraineeLink", 1)[1].split("\n}", 1)[0]


def test_direct_simulator_service_ui_uses_only_its_own_model_service():
    html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")

    assert 'data-simulator-ui-mode="proxy"' in html
    assert 'searchParams.get("ui") === "direct"' in html
    assert "directSimulatorServiceMode" in script
    assert "directSimulatorServiceApiBase" in script
    assert "if (directSimulatorServiceMode && controlPlane)" in script
    assert "loadDirectSimulatorServiceModel" in script
    assert "if (directSimulatorServiceMode) return state.models;" in script
    assert 'html[data-simulator-ui-mode="direct"] .model-management-button' in styles
    assert 'html[data-simulator-ui-mode="direct"] .model-switcher select' in styles
    assert 'html[data-simulator-ui-mode="direct"] .model-service-control' in styles
    assert "display: block !important;" in styles.split(
        'html[data-simulator-ui-mode="direct"] .model-switcher span', 1
    )[1].split("}", 1)[0]
