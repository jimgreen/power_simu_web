from __future__ import annotations

import base64
import json
import shutil
import socket
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from simu.simulator_cluster import SimulatorClusterManager
from simu.simulator_proxy import make_simulator_proxy_server
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


def _make_model(root: Path, model_id: str) -> Path:
    model_dir = root / model_id
    model_dir.mkdir(parents=True)
    (model_dir / "model.e").write_text("<Bus::1>\n@id\n1\n", encoding="utf-8")
    return model_dir


class FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_cluster_assigns_stable_unique_ports_and_builds_one_model_child_command(tmp_path: Path):
    models_root = tmp_path / "models"
    _make_model(models_root, "model_a")
    _make_model(models_root, "model_b")
    running: set[str] = set()
    commands: list[list[str]] = []

    def process_factory(command, **_kwargs):
        commands.append(list(command))
        model_id = command[command.index("--model-id") + 1]
        running.add(model_id)
        return FakeProcess(pid=4300 + len(commands))

    manager = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        service_host="127.0.0.1",
        first_service_port=9101,
        process_factory=process_factory,
        health_checker=lambda _host, _port, model_id, _timeout: (
            model_id in running,
            {"role": "simulator", "model_id": model_id},
            "" if model_id in running else "not running",
        ),
        port_checker=lambda *_args: False,
        startup_timeout_seconds=0.2,
        poll_interval_seconds=0.001,
    )

    first_catalog = manager.models()
    assert [item["service"]["port"] for item in first_catalog] == [9101, 9102]

    started = manager.start("model_b")
    assert started["state"] == "running"
    assert started["healthy"] is True
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("--role") + 1] == "simulator-service"
    assert command[command.index("--model-id") + 1] == "model_b"
    assert Path(command[command.index("--model-dir") + 1]) == models_root / "model_b"
    assert command[command.index("--port") + 1] == "9102"

    manager_reloaded = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        service_host="127.0.0.1",
        first_service_port=9201,
        health_checker=lambda *_args: (False, {}, "not running"),
    )
    assert [item["service"]["port"] for item in manager_reloaded.models()] == [9101, 9102]


def test_cluster_suggests_unused_port_and_persists_custom_model_access_address(tmp_path: Path):
    models_root = tmp_path / "models"
    _make_model(models_root, "model_a")
    _make_model(models_root, "model_b")
    occupied = {9103}
    manager = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        service_host="127.0.0.1",
        first_service_port=9101,
        health_checker=lambda *_args: (False, {}, "not running"),
        port_checker=lambda _host, port: port in occupied,
    )

    assert manager.suggest_service_address() == {
        "host": "127.0.0.1",
        "port": 9104,
        "access_link": "127.0.0.1:9104",
        "base_url": "http://127.0.0.1:9104",
    }

    configured = manager.configure_model_service("model_b", "192.168.10.25", 9202)
    assert configured["service"]["host"] == "192.168.10.25"
    assert configured["service"]["port"] == 9202
    assert configured["service"]["access_link"] == "192.168.10.25:9202"

    reloaded = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        service_host="127.0.0.1",
        first_service_port=9301,
        health_checker=lambda *_args: (False, {}, "not running"),
        port_checker=lambda *_args: False,
    )
    reloaded_model = reloaded.model_info("model_b")
    assert reloaded_model["service"]["host"] == "192.168.10.25"
    assert reloaded_model["service"]["port"] == 9202


def test_stopped_service_catalog_skips_health_probes_and_keeps_port_edit_responsive(tmp_path: Path):
    models_root = tmp_path / "models"
    _make_model(models_root, "model_a")
    _make_model(models_root, "model_b")
    health_checks: list[str] = []
    port_checks: list[int] = []

    def health_checker(_host, _port, model_id, _timeout):
        health_checks.append(model_id)
        return False, {}, "not running"

    manager = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        first_service_port=9101,
        health_checker=health_checker,
        port_checker=lambda _host, port: port_checks.append(port) or False,
    )
    port_checks.clear()

    catalog = manager.catalog()
    assert [item["service"]["port"] for item in catalog["models"]] == [9101, 9102]
    assert health_checks == []
    assert port_checks == [9103]

    assert manager.catalog()["service_suggestion"]["port"] == 9103
    assert port_checks == [9103]

    save_calls = 0
    original_save_registry = manager._save_registry_locked

    def count_registry_save():
        nonlocal save_calls
        save_calls += 1
        original_save_registry()

    manager._save_registry_locked = count_registry_save
    updated = manager.configure_model_service("model_b", "127.0.0.1", 9202)
    assert updated["service"]["port"] == 9202
    assert health_checks == []
    assert save_calls == 1

    assert manager.catalog()["models"][1]["service"]["port"] == 9202
    assert health_checks == []
    assert port_checks == [9103, 9202, 9102]

    unchanged = manager.configure_model_service("model_b", "127.0.0.1", 9202)
    assert unchanged["service"]["port"] == 9202
    assert save_calls == 1


def test_cluster_rejects_duplicate_occupied_or_invalid_model_access_address(tmp_path: Path):
    models_root = tmp_path / "models"
    _make_model(models_root, "model_a")
    _make_model(models_root, "model_b")
    manager = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        first_service_port=9101,
        health_checker=lambda *_args: (False, {}, "not running"),
        port_checker=lambda _host, port: port == 9300,
    )

    with pytest.raises(ValueError, match="服务地址 127.0.0.1:9101 已分配给模型“model_a”.*不同模型不能共用同一 IP 和端口"):
        manager.configure_model_service("model_b", "127.0.0.1", 9101)
    different_host = manager.configure_model_service("model_b", "127.0.0.2", 9101)
    assert different_host["service"]["access_link"] == "127.0.0.2:9101"
    with pytest.raises(ValueError, match="已被占用"):
        manager.configure_model_service("model_b", "127.0.0.1", 9300)
    with pytest.raises(ValueError, match="地址"):
        manager.configure_model_service("model_b", "http://127.0.0.1", 9301)
    with pytest.raises(ValueError, match="1-65535"):
        manager.configure_model_service("model_b", "127.0.0.1", 70000)


def test_cluster_start_and_stop_are_idempotent(tmp_path: Path):
    models_root = tmp_path / "models"
    _make_model(models_root, "only")
    running = False
    process = FakeProcess()
    launches = 0

    def process_factory(_command, **_kwargs):
        nonlocal running, launches
        launches += 1
        running = True
        process.returncode = None
        return process

    def health_checker(_host, _port, model_id, _timeout):
        return running, {"role": "simulator", "model_id": model_id}, "" if running else "not running"

    manager = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        process_factory=process_factory,
        health_checker=health_checker,
        port_checker=lambda *_args: False,
        startup_timeout_seconds=0.2,
        poll_interval_seconds=0.001,
    )

    assert manager.start("only")["state"] == "running"
    assert manager.start("only")["state"] == "running"
    assert launches == 1

    running = False
    assert manager.stop("only")["state"] == "stopped"
    assert manager.stop("only")["state"] == "stopped"
    assert process.terminated is True


def test_cluster_does_not_terminate_unverified_stale_pid(tmp_path: Path, monkeypatch):
    models_root = tmp_path / "models"
    _make_model(models_root, "only")
    runtime_root = tmp_path / "runtime"
    manager = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=runtime_root,
        health_checker=lambda *_args: (False, {}, "not running"),
    )
    registry = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    registry["services"]["only"]["pid"] = 999999
    manager.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    killed: list[int] = []
    monkeypatch.setattr(SimulatorClusterManager, "_terminate_pid", staticmethod(killed.append))
    reloaded = SimulatorClusterManager(
        sim_dir=tmp_path,
        models_root=models_root,
        runtime_root=runtime_root,
        health_checker=lambda *_args: (False, {}, "not running"),
    )

    assert reloaded.stop("only")["state"] == "stopped"
    assert killed == []


def _free_port_pair() -> int:
    for _attempt in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            first = int(listener.getsockname()[1])
        if first >= 65534:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as next_listener:
                next_listener.bind(("127.0.0.1", first + 1))
            return first
        except OSError:
            continue
    raise RuntimeError("Could not reserve two consecutive local ports")


def test_modified_service_address_is_used_by_direct_interaction_link(tmp_path: Path):
    models_root = tmp_path / "models"
    shutil.copytree(SIMPLE_MODEL_SOURCE, models_root / "model_a")
    first_port = _free_port_pair()
    manager = SimulatorClusterManager(
        sim_dir=Path(__file__).resolve().parents[1],
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        first_service_port=first_port,
        startup_timeout_seconds=20,
    )
    proxy_server = None
    try:
        manager.configure_model_service("model_a", "127.0.0.1", first_port + 1)
        service = manager.start("model_a")
        assert service["base_url"] == f"http://127.0.0.1:{first_port + 1}"
        with urlopen(f"{service['base_url']}/api/trainee-link", timeout=5) as response:
            interaction = json.loads(response.read().decode("utf-8"))
        assert interaction["teacher_api_base"] == service["base_url"]
        assert interaction["link"] == f"{service['base_url']}/api/trainee-link"

        static_root = tmp_path / "static"
        static_root.mkdir()
        (static_root / "index.html").write_text("proxy-ui", encoding="utf-8")
        proxy_server = make_simulator_proxy_server(
            ("127.0.0.1", 0),
            manager,
            static_root=static_root,
        )
        threading.Thread(target=proxy_server.serve_forever, daemon=True).start()
        proxy_base = f"http://127.0.0.1:{proxy_server.server_address[1]}"
        with urlopen(f"{proxy_base}/api/trainee-link?model_id=model_a", timeout=5) as response:
            discovered = json.loads(response.read().decode("utf-8"))
        assert discovered["teacher_api_base"] == service["base_url"]
        assert discovered["link"] == f"{proxy_base}/api/trainee-link?model_id=model_a"
    finally:
        if proxy_server is not None:
            proxy_server.shutdown()
            proxy_server.server_close()
        manager.close()


def test_real_per_model_services_run_on_distinct_ports_and_remain_independent(tmp_path: Path):
    models_root = tmp_path / "models"
    shutil.copytree(SIMPLE_MODEL_SOURCE, models_root / "model_a")
    shutil.copytree(SIMPLE_MODEL_SOURCE, models_root / "model_b")
    port = _free_port_pair()
    manager = SimulatorClusterManager(
        sim_dir=Path(__file__).resolve().parents[1],
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        first_service_port=port,
        startup_timeout_seconds=20,
    )
    proxy_server = None
    try:
        service_a = manager.start("model_a")
        service_b = manager.start("model_b")
        assert service_a["port"] == port
        assert service_b["port"] == port + 1
        assert service_a["pid"] != service_b["pid"]

        for model_id, service in (("model_a", service_a), ("model_b", service_b)):
            with urlopen(service["base_url"], timeout=5) as response:
                direct_ui_url = response.geturl()
                direct_ui_html = response.read().decode("utf-8")
            with urlopen(f"{service['base_url']}/api/health", timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            with urlopen(
                f"{service['base_url']}/api/snapshot?model_id={model_id}&lite=1",
                timeout=10,
            ) as response:
                snapshot = json.loads(response.read().decode("utf-8"))
            assert health["ok"] is True
            assert health["model_id"] == model_id
            assert snapshot["model"]["id"] == model_id
            assert direct_ui_url == f"{service['base_url']}/?ui=direct"
            assert 'id="modelSelector"' in direct_ui_html

        static_root = tmp_path / "proxy-static"
        static_root.mkdir()
        (static_root / "index.html").write_text("proxy-ui", encoding="utf-8")
        proxy_server = make_simulator_proxy_server(
            ("127.0.0.1", 0),
            manager,
            static_root=static_root,
        )
        proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
        proxy_thread.start()
        proxy_base = f"http://127.0.0.1:{proxy_server.server_address[1]}"
        with urlopen(f"{proxy_base}/api/trainee-link?model_id=model_b", timeout=5) as response:
            interaction = json.loads(response.read().decode("utf-8"))
        assert interaction["model_id"] == "model_b"
        assert interaction["link"] == f"{proxy_base}/api/trainee-link?model_id=model_b"
        assert interaction["teacher_api_base"] == service_b["base_url"]

        manager.stop("model_a")
        with urlopen(f"{service_b['base_url']}/api/health", timeout=5) as response:
            remaining_health = json.loads(response.read().decode("utf-8"))
        assert remaining_health["ok"] is True
        assert remaining_health["model_id"] == "model_b"
    finally:
        if proxy_server is not None:
            proxy_server.shutdown()
            proxy_server.server_close()
        manager.close()


class StubClusterManager:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self._state = "stopped"

    def catalog(self):
        return {
            "models": [
                {
                    "id": "model_a",
                    "name": "model_a",
                    "service": {
                        "state": self._state,
                        "host": "127.0.0.1",
                        "port": 9101,
                        "base_url": "http://127.0.0.1:9101",
                        "healthy": self._state == "running",
                        "pid": 4321 if self._state == "running" else None,
                        "error": "",
                    },
                }
            ],
            "active_model_id": "model_a",
        }

    def start(self, model_id):
        self.started.append(model_id)
        self._state = "running"
        return self.catalog()["models"][0]["service"]

    def stop(self, model_id):
        self.stopped.append(model_id)
        self._state = "stopped"
        return self.catalog()["models"][0]["service"]

    def close(self):
        return None


def _json_request(url: str, method: str = "GET", payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_proxy_exposes_only_catalog_and_lifecycle_control_without_data_forwarding(tmp_path: Path):
    manager = StubClusterManager()
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text("proxy-ui", encoding="utf-8")
    server = make_simulator_proxy_server(("127.0.0.1", 0), manager, static_root=static_root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, catalog = _json_request(f"{base}/api/models")
        assert status == 200
        assert catalog["models"][0]["service"]["base_url"] == "http://127.0.0.1:9101"

        _, started = _json_request(
            f"{base}/api/simulator-services/start",
            method="POST",
            payload={"model_id": "model_a"},
        )
        assert started["service"]["state"] == "running"
        assert manager.started == ["model_a"]

        _, stopped = _json_request(
            f"{base}/api/simulator-services/stop",
            method="POST",
            payload={"model_id": "model_a"},
        )
        assert stopped["service"]["state"] == "stopped"
        assert manager.stopped == ["model_a"]

        with pytest.raises(HTTPError) as error:
            _json_request(f"{base}/api/snapshot?model_id=model_a")
        assert error.value.code == 404
        assert "directly" in error.value.read().decode("utf-8").lower()
    finally:
        server.shutdown()
        server.server_close()


def test_proxy_keeps_low_frequency_model_management_on_control_plane(tmp_path: Path):
    models_root = tmp_path / "models"
    shutil.copytree(SIMPLE_MODEL_SOURCE, models_root / "source")
    health_checks: list[str] = []

    def health_checker(_host, _port, model_id, _timeout):
        health_checks.append(model_id)
        return False, {}, "not running"

    manager = SimulatorClusterManager(
        sim_dir=Path(__file__).resolve().parents[1],
        models_root=models_root,
        runtime_root=tmp_path / "runtime",
        health_checker=health_checker,
        port_checker=lambda *_args: False,
    )
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text("proxy-ui", encoding="utf-8")
    server = make_simulator_proxy_server(("127.0.0.1", 0), manager, static_root=static_root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, suggestion = _json_request(f"{base}/api/simulator-services/suggestion")
        assert suggestion["service_suggestion"]["host"] == "127.0.0.1"
        assert suggestion["service_suggestion"]["port"] == 8712

        _, cloned = _json_request(
            f"{base}/api/models/clone",
            method="POST",
            payload={"model_id": "source", "name": "copy"},
        )
        assert cloned["model"]["id"] == "copy"
        assert {item["id"] for item in cloned["models"]} == {"source", "copy"}

        _, deleted = _json_request(
            f"{base}/api/models/delete",
            method="POST",
            payload={"model_id": "copy"},
        )
        assert deleted["deleted"]["id"] == "copy"
        assert [item["id"] for item in deleted["models"]] == ["source"]

        model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_bytes()
        _, created = _json_request(
            f"{base}/api/models/create",
            method="POST",
            payload={
                "name": "created",
                "data_base64": base64.b64encode(model_text).decode("ascii"),
                "service_host": "127.0.0.1",
                "service_port": 9551,
            },
        )
        assert created["model"]["id"] == "created"
        assert created["model"]["service"]["access_link"] == "127.0.0.1:9551"
        assert (models_root / "created" / "meas.e").exists()
        generated_names = ("model.e", "control.e", "curves.json", "meas.e", "stat.e", "weather.e", "curves.e")
        generated_before_link_update = {
            name: (models_root / "created" / name).read_bytes()
            for name in generated_names
        }
        health_checks.clear()

        _, updated = _json_request(
            f"{base}/api/models/update-definitions",
            method="POST",
            payload={
                "model_id": "created",
                "service_host": "127.0.0.1",
                "service_port": 9552,
            },
        )
        assert updated["model"]["service"]["access_link"] == "127.0.0.1:9552"
        assert updated["updated"]["service"]["port"] == 9552
        assert "models" not in updated
        assert health_checks == []
        assert (models_root / "created" / "model.e").exists()
        assert {
            name: (models_root / "created" / name).read_bytes()
            for name in generated_names
        } == generated_before_link_update

        _, unchanged = _json_request(
            f"{base}/api/models/update-definitions",
            method="POST",
            payload={
                "model_id": "created",
                "service_host": "127.0.0.1",
                "service_port": 9552,
            },
        )
        assert unchanged["model"]["service"]["access_link"] == "127.0.0.1:9552"
        assert unchanged["updated"]["service"]["port"] == 9552

        diagram_text = '<svg xmlns="http://www.w3.org/2000/svg"><text>updated</text></svg>'
        _, diagram_only = _json_request(
            f"{base}/api/models/update-definitions",
            method="POST",
            payload={
                "model_id": "created",
                "service_host": "127.0.0.1",
                "service_port": 9552,
                "diagram_svg_base64": base64.b64encode(diagram_text.encode("utf-8")).decode("ascii"),
            },
        )
        assert diagram_only["updated"]["diagram"]["updated"] is True
        assert (models_root / "created" / "diagram.svg").read_text(encoding="utf-8") == diagram_text
        assert {
            name: (models_root / "created" / name).read_bytes()
            for name in generated_names
        } == generated_before_link_update
    finally:
        server.shutdown()
        server.server_close()
