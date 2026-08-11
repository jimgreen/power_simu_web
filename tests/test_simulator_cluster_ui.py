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
