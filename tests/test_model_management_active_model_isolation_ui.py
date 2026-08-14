import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_body(script: str, name: str) -> str:
    marker = f"function {name}("
    if marker not in script:
        marker = f"async function {name}("
    assert marker in script
    return script.split(marker, 1)[1].split("\nfunction ", 1)[0]


def test_simulator_model_management_operations_do_not_switch_display_model():
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

    for function_name in (
        "createNewModelFromFile",
        "importDefinitionModel",
        "updateModelFromFile",
        "cloneCurrentModel",
    ):
        assert "setActiveModel(" not in _function_body(script, function_name)

    delete_body = _function_body(script, "deleteManagedModel")
    assert "const deletedActiveModel =" in delete_body
    assert "if (deletedActiveModel)" in delete_body
    assert "setActiveModel(nextId, true)" in delete_body


def test_trainee_model_management_operations_do_not_switch_display_model():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    for function_name in (
        "createNewModelSlot",
        "cloneManagedModel",
        "initializeModelFromLink",
    ):
        assert "setActiveModel(" not in _function_body(script, function_name)

    delete_body = _function_body(script, "deleteManagedModel")
    assert "const deletedActiveModel =" in delete_body
    assert "if (deletedActiveModel)" in delete_body
    assert "setActiveModel(nextId, true)" in delete_body


def test_trainee_model_catalog_refresh_preserves_loaded_active_model_runtime_cursor():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
    load_models_source = "async function loadModels(" + script.split(
        "async function loadModels(",
        1,
    )[1].split("async function refreshLocalSnapshotPayload", 1)[0]
    node_script = f"""
const state = {{
  models: [],
  activeModelId: "active-model",
  snapshot: {{ model: {{ id: "active-model" }}, devices: [{{ dev_name: "device-1" }}] }},
  deviceRuntimeSignature: "runtime-signature-1",
}};
let switchCalls = 0;
let selectorRenderCalls = 0;
async function api(path) {{
  if (path === "/api/models") {{
    return {{ models: [{{ id: "active-model", name: "当前模型" }}], active_model_id: "active-model" }};
  }}
  return {{ items: {{}} }};
}}
function mergeReceiveStatesFromBackend() {{}}
async function setActiveModel(modelId) {{
  switchCalls += 1;
  state.activeModelId = modelId;
  state.deviceRuntimeSignature = "";
}}
function renderModelSelector() {{ selectorRenderCalls += 1; }}
function renderModelManagementList() {{}}
function $(id) {{ return id === "modelManagementDialog" ? {{ open: false }} : null; }}
{load_models_source}
loadModels().then(() => process.stdout.write(JSON.stringify({{
  activeModelId: state.activeModelId,
  deviceRuntimeSignature: state.deviceRuntimeSignature,
  switchCalls,
  selectorRenderCalls,
}})));
"""

    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "activeModelId": "active-model",
        "deviceRuntimeSignature": "runtime-signature-1",
        "switchCalls": 0,
        "selectorRenderCalls": 1,
    }
