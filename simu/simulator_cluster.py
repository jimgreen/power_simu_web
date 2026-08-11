"""Process manager for the simulator proxy and per-model simulator services."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HealthResult = tuple[bool, Mapping[str, Any], str]
HealthChecker = Callable[[str, int, str, float], HealthResult]


def _safe_model_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Model id is required")
    if text in {".", ".."} or any(char in text for char in '<>:"/\\|?*'):
        raise ValueError(f"模型名称无效: {text}")
    return text


def _model_key(value: Any) -> str:
    return str(value or "").strip().casefold()


class SimulatorClusterManager:
    """Own one independently addressable simulator process per source model."""

    REGISTRY_VERSION = 1

    def __init__(
        self,
        *,
        sim_dir: str | Path,
        models_root: str | Path,
        runtime_root: str | Path,
        service_host: str = "127.0.0.1",
        first_service_port: int = 8711,
        compute_interval_seconds: float = 1.0,
        child_no_worker: bool = False,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        health_checker: Optional[HealthChecker] = None,
        port_checker: Optional[Callable[[str, int], bool]] = None,
        startup_timeout_seconds: float = 30.0,
        shutdown_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.sim_dir = Path(sim_dir).resolve()
        self.models_root = Path(models_root).resolve()
        self.runtime_root = Path(runtime_root).resolve()
        self.service_host = str(service_host or "127.0.0.1").strip()
        self.first_service_port = max(1, int(first_service_port))
        self.compute_interval_seconds = max(0.1, float(compute_interval_seconds or 1.0))
        self.child_no_worker = bool(child_no_worker)
        self.noise_std = noise_std
        self.random_seed = random_seed
        self.process_factory = process_factory
        self.health_checker = health_checker or self._default_health_checker
        self.port_checker = port_checker or self._port_is_open
        self.startup_timeout_seconds = max(0.01, float(startup_timeout_seconds))
        self.shutdown_timeout_seconds = max(0.01, float(shutdown_timeout_seconds))
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self.lock = threading.RLock()
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.cluster_runtime_dir = self.runtime_root / ".cluster"
        self.cluster_runtime_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.cluster_runtime_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.cluster_runtime_dir / "services.json"
        self._processes: dict[str, Any] = {}
        self._log_handles: dict[str, Any] = {}
        self._states: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._registry = self._load_registry()
        self.default_model_id = ""
        self._sync_models_locked()

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"version": self.REGISTRY_VERSION, "services": {}}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": self.REGISTRY_VERSION, "services": {}}
        services = payload.get("services", {}) if isinstance(payload, Mapping) else {}
        return {
            "version": self.REGISTRY_VERSION,
            "services": dict(services) if isinstance(services, Mapping) else {},
        }

    def _save_registry_locked(self) -> None:
        payload = {
            "version": self.REGISTRY_VERSION,
            "service_host": self.service_host,
            "first_service_port": self.first_service_port,
            "services": self._registry.get("services", {}),
        }
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.registry_path)

    def _model_dirs_locked(self) -> list[Path]:
        return [
            child
            for child in sorted(self.models_root.iterdir(), key=lambda path: path.name.casefold())
            if child.is_dir() and (child / "model.e").exists()
        ]

    @staticmethod
    def _preferred_default_model_id(model_ids: list[str]) -> str:
        for preferred in ("默认模型", "default"):
            for model_id in model_ids:
                if _model_key(model_id) == _model_key(preferred):
                    return model_id
        return model_ids[0] if model_ids else ""

    def _next_port_locked(self, used_ports: set[int]) -> int:
        port = self.first_service_port
        while port in used_ports:
            port += 1
        return port

    def _sync_models_locked(self) -> None:
        services = self._registry.setdefault("services", {})
        model_dirs = self._model_dirs_locked()
        model_ids = [path.name for path in model_dirs]
        used_ports: set[int] = set()
        for model_id in model_ids:
            entry = services.get(model_id)
            if not isinstance(entry, Mapping):
                continue
            try:
                port = int(entry.get("port", 0))
            except (TypeError, ValueError):
                continue
            if port > 0 and port not in used_ports:
                used_ports.add(port)

        changed = False
        normalized: dict[str, dict[str, Any]] = {}
        for model_dir in model_dirs:
            model_id = model_dir.name
            raw_entry = services.get(model_id)
            entry = dict(raw_entry) if isinstance(raw_entry, Mapping) else {}
            try:
                port = int(entry.get("port", 0))
            except (TypeError, ValueError):
                port = 0
            if port <= 0 or any(
                int(other.get("port", 0) or 0) == port
                for other_id, other in normalized.items()
                if other_id != model_id
            ):
                port = self._next_port_locked(used_ports)
                used_ports.add(port)
                changed = True
            host = str(entry.get("host") or self.service_host).strip() or self.service_host
            normalized[model_id] = {
                "host": host,
                "port": port,
                "pid": entry.get("pid"),
            }
            self._states.setdefault(model_id, "stopped")
            self._errors.setdefault(model_id, "")
        if set(services) != set(normalized):
            changed = True
        self._registry["services"] = normalized
        self.default_model_id = self._preferred_default_model_id(model_ids)
        if changed or not self.registry_path.exists():
            self._save_registry_locked()

    def _entry_locked(self, model_id: Any) -> tuple[str, dict[str, Any]]:
        self._sync_models_locked()
        target_id = _safe_model_id(model_id or self.default_model_id)
        entry = self._registry["services"].get(target_id)
        if not isinstance(entry, dict):
            raise KeyError(f"Unknown simulation model: {model_id}")
        return target_id, entry

    @staticmethod
    def _default_health_checker(host: str, port: int, model_id: str, timeout: float) -> HealthResult:
        request = Request(
            f"http://{host}:{port}/api/health",
            headers={"Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read().decode("utf-8")
        except (HTTPError, URLError, OSError) as exc:
            return False, {}, str(exc)
        try:
            payload = json.loads(data) if data else {}
        except json.JSONDecodeError:
            return False, {}, "health response is not valid JSON"
        if not isinstance(payload, Mapping):
            return False, {}, "health response is not an object"
        actual_model_id = str(payload.get("model_id") or "")
        healthy = bool(payload.get("ok")) and actual_model_id == model_id
        error = "" if healthy else f"unexpected service on {host}:{port}"
        return healthy, payload, error

    @staticmethod
    def _port_is_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.15):
                return True
        except OSError:
            return False

    def _probe_locked(self, model_id: str, entry: Mapping[str, Any]) -> HealthResult:
        return self.health_checker(
            str(entry["host"]),
            int(entry["port"]),
            model_id,
            min(1.0, self.startup_timeout_seconds),
        )

    def _close_log_handle_locked(self, model_id: str) -> None:
        handle = self._log_handles.pop(model_id, None)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def _reconcile_locked(self, model_id: str, entry: dict[str, Any]) -> HealthResult:
        process = self._processes.get(model_id)
        if process is not None and process.poll() is not None:
            self._processes.pop(model_id, None)
            self._close_log_handle_locked(model_id)
            self._states[model_id] = "failed" if process.returncode else "stopped"
            if process.returncode:
                self._errors[model_id] = f"模拟服务已退出，返回码 {process.returncode}"
            entry["pid"] = None
            self._save_registry_locked()
        healthy, payload, error = self._probe_locked(model_id, entry)
        if healthy:
            self._states[model_id] = "running"
            self._errors[model_id] = ""
            process_payload = payload.get("process", {}) if isinstance(payload, Mapping) else {}
            pid = process_payload.get("pid") if isinstance(process_payload, Mapping) else None
            next_pid = pid or entry.get("pid")
            if next_pid != entry.get("pid"):
                entry["pid"] = next_pid
                self._save_registry_locked()
        elif self._states.get(model_id) == "running":
            self._states[model_id] = "failed"
            self._errors[model_id] = error or "模拟服务健康检查失败"
        return healthy, payload, error

    def _service_payload_locked(self, model_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        healthy, _payload, error = self._reconcile_locked(model_id, entry)
        state = self._states.get(model_id, "stopped")
        if not healthy and state not in {"starting", "stopping", "failed"}:
            state = "stopped"
        host = str(entry["host"])
        port = int(entry["port"])
        return {
            "state": state,
            "host": host,
            "port": port,
            "base_url": f"http://{host}:{port}",
            "pid": entry.get("pid"),
            "healthy": healthy,
            "error": self._errors.get(model_id, "") or (error if state == "failed" else ""),
        }

    def model_info(self, model_id: Any) -> dict[str, Any]:
        with self.lock:
            target_id, entry = self._entry_locked(model_id)
            service = self._service_payload_locked(target_id, entry)
            return {
                "id": target_id,
                "name": target_id,
                "sim_dir": str(self.models_root / target_id),
                "runtime_dir": str(self.runtime_root / target_id),
                "clock_state": "running" if service["healthy"] else "stopped",
                "service": service,
            }

    def models(self) -> list[dict[str, Any]]:
        with self.lock:
            self._sync_models_locked()
            return [self.model_info(model_id) for model_id in self._registry["services"]]

    def catalog(self) -> dict[str, Any]:
        return {
            "models": self.models(),
            "active_model_id": self.default_model_id,
            "models_root": str(self.models_root),
            "data_plane": "direct",
        }

    def _command_locked(self, model_id: str, entry: Mapping[str, Any]) -> list[str]:
        command = [
            sys.executable,
            "-X",
            "utf8",
            "-u",
            "-m",
            "simu.server",
            "--role",
            "simulator-service",
            "--host",
            str(entry["host"]),
            "--port",
            str(entry["port"]),
            "--sim-dir",
            str(self.sim_dir),
            "--model-id",
            model_id,
            "--model-dir",
            str(self.models_root / model_id),
            "--runtime-dir",
            str(self.runtime_root / model_id),
            "--compute-interval-seconds",
            str(self.compute_interval_seconds),
        ]
        if self.noise_std is not None:
            command.extend(["--noise-std", str(self.noise_std)])
        if self.random_seed is not None:
            command.extend(["--seed", str(self.random_seed)])
        if self.child_no_worker:
            command.append("--no-worker")
        return command

    def start(self, model_id: Any) -> dict[str, Any]:
        with self.lock:
            target_id, entry = self._entry_locked(model_id)
            healthy, payload, _error = self._probe_locked(target_id, entry)
            if healthy:
                self._states[target_id] = "running"
                process_payload = payload.get("process", {}) if isinstance(payload, Mapping) else {}
                if isinstance(process_payload, Mapping) and process_payload.get("pid"):
                    entry["pid"] = process_payload["pid"]
                self._save_registry_locked()
                return self._service_payload_locked(target_id, entry)
            if self.port_checker(str(entry["host"]), int(entry["port"])):
                raise RuntimeError(
                    f"端口 {entry['host']}:{entry['port']} 已被非目标模拟服务占用"
                )

            previous = self._processes.get(target_id)
            if previous is not None and previous.poll() is None:
                self._states[target_id] = "starting"
            else:
                self._states[target_id] = "starting"
                self._errors[target_id] = ""
                log_path = self.log_dir / f"{target_id}.log"
                log_handle = log_path.open("ab", buffering=0)
                environment = os.environ.copy()
                environment.setdefault("PYTHONUTF8", "1")
                kwargs: dict[str, Any] = {
                    "cwd": str(self.sim_dir),
                    "env": environment,
                    "stdout": log_handle,
                    "stderr": subprocess.STDOUT,
                }
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                try:
                    process = self.process_factory(self._command_locked(target_id, entry), **kwargs)
                except Exception:
                    log_handle.close()
                    self._states[target_id] = "failed"
                    raise
                self._processes[target_id] = process
                self._log_handles[target_id] = log_handle
                entry["pid"] = getattr(process, "pid", None)
                self._save_registry_locked()

        deadline = time.monotonic() + self.startup_timeout_seconds
        last_error = "模拟服务启动超时"
        while time.monotonic() < deadline:
            with self.lock:
                process = self._processes.get(target_id)
                if process is not None and process.poll() is not None:
                    self._states[target_id] = "failed"
                    last_error = f"模拟服务启动失败，返回码 {process.returncode}"
                    self._errors[target_id] = last_error
                    break
                healthy, _payload, last_error = self._probe_locked(target_id, entry)
                if healthy:
                    self._states[target_id] = "running"
                    self._errors[target_id] = ""
                    self._save_registry_locked()
                    return self._service_payload_locked(target_id, entry)
            time.sleep(self.poll_interval_seconds)

        with self.lock:
            self._states[target_id] = "failed"
            self._errors[target_id] = last_error or "模拟服务启动失败"
            process = self._processes.pop(target_id, None)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.shutdown_timeout_seconds)
            self._close_log_handle_locked(target_id)
            entry["pid"] = None
            self._save_registry_locked()
            failure_message = self._errors[target_id]
        raise RuntimeError(failure_message)

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        if pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            return

    def stop(self, model_id: Any) -> dict[str, Any]:
        with self.lock:
            target_id, entry = self._entry_locked(model_id)
            process = self._processes.get(target_id)
            self._states[target_id] = "stopping"
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.shutdown_timeout_seconds)
            elif entry.get("pid"):
                healthy, payload, _error = self._probe_locked(target_id, entry)
                if healthy:
                    process_payload = payload.get("process", {}) if isinstance(payload, Mapping) else {}
                    verified_pid = process_payload.get("pid") if isinstance(process_payload, Mapping) else None
                    if verified_pid:
                        self._terminate_pid(int(verified_pid))
            self._processes.pop(target_id, None)
            self._close_log_handle_locked(target_id)
            entry["pid"] = None
            self._states[target_id] = "stopped"
            self._errors[target_id] = ""
            self._save_registry_locked()
            host = str(entry["host"])
            port = int(entry["port"])
            return {
                "state": "stopped",
                "host": host,
                "port": port,
                "base_url": f"http://{host}:{port}",
                "pid": None,
                "healthy": False,
                "error": "",
            }

    def require_stopped(self, model_id: Any) -> tuple[str, Path, Path]:
        with self.lock:
            target_id, entry = self._entry_locked(model_id)
            healthy, _payload, _error = self._probe_locked(target_id, entry)
            process = self._processes.get(target_id)
            if healthy or (process is not None and process.poll() is None):
                raise ValueError(f"模型模拟服务运行中，无法修改: {target_id}")
            return target_id, self.models_root / target_id, self.runtime_root / target_id

    def validate_new_model_name(self, new_model_id: Any) -> str:
        target_id = _safe_model_id(new_model_id)
        with self.lock:
            self._sync_models_locked()
            keys = {_model_key(model_id) for model_id in self._registry["services"]}
            if _model_key(target_id) in keys or (self.models_root / target_id).exists():
                raise ValueError(f"模型已存在: {target_id}")
        return target_id

    def register_model(self, model_id: Any) -> dict[str, Any]:
        target_id = _safe_model_id(model_id)
        with self.lock:
            if not (self.models_root / target_id / "model.e").exists():
                raise ValueError(f"模型定义不存在: {target_id}")
            self._sync_models_locked()
            return self.model_info(target_id)

    def model_source_dir(self, model_id: Any) -> tuple[str, Path]:
        with self.lock:
            target_id, _entry = self._entry_locked(model_id)
            return target_id, self.models_root / target_id

    def clone_model(self, source_model_id: Any, new_model_id: Any) -> dict[str, Any]:
        _source_id, source_dir = self.model_source_dir(source_model_id)
        target_id = self.validate_new_model_name(new_model_id)
        target_dir = self.models_root / target_id
        shutil.copytree(source_dir, target_dir)
        try:
            return self.register_model(target_id)
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    def delete_model(self, model_id: Any) -> dict[str, Any]:
        target_id, source_dir, runtime_dir = self.require_stopped(model_id)
        with self.lock:
            self._sync_models_locked()
            if len(self._registry["services"]) <= 1:
                raise ValueError("至少需要保留一个模型")
            removed = self.model_info(target_id)
            shutil.rmtree(source_dir)
            if runtime_dir.exists():
                shutil.rmtree(runtime_dir)
            self._registry["services"].pop(target_id, None)
            self._states.pop(target_id, None)
            self._errors.pop(target_id, None)
            self._save_registry_locked()
            self._sync_models_locked()
            return {**removed, "deleted": True, "active_model_id": self.default_model_id}

    def clear_model_runtime(self, model_id: Any) -> None:
        _target_id, _source_dir, runtime_dir = self.require_stopped(model_id)
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        with self.lock:
            model_ids = list(self._registry.get("services", {}))
        for model_id in model_ids:
            try:
                self.stop(model_id)
            except (KeyError, OSError, RuntimeError, ValueError):
                pass
