"""Control-plane HTTP service for discovering and managing simulator services."""

from __future__ import annotations

import base64
import json
import mimetypes
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

try:
    from .simulator_cluster import SimulatorClusterManager
except ImportError:  # pragma: no cover - legacy direct-module compatibility.
    from simulator_cluster import SimulatorClusterManager


def make_simulator_proxy_server(
    server_address: tuple[str, int],
    manager: SimulatorClusterManager,
    *,
    static_root: str | Path,
) -> ThreadingHTTPServer:
    root = Path(static_root).resolve()

    class SimulatorProxyHandler(BaseHTTPRequestHandler):
        server_version = "PolarMicrogridProxy/0.1"
        control_plane_post_routes = {
            "/api/simulator-services/start",
            "/api/simulator-services/stop",
            "/api/models/create",
            "/api/models/update-definitions",
            "/api/models/clone",
            "/api/models/delete",
            "/api/models/import-definitions",
        }

        def log_message(self, _fmt: str, *_args: Any) -> None:
            return

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            try:
                path = urlparse(self.path).path
                if path == "/api/health":
                    self._send_json({"ok": True, "role": "simulator-proxy", **manager.catalog()})
                elif path in {"/api/models", "/api/simulator-services"}:
                    self._send_json(manager.catalog())
                elif path == "/api/simulator-services/suggestion":
                    self._send_json({"service_suggestion": manager.suggest_service_address()})
                elif path == "/api/trainee-link":
                    self._send_trainee_link()
                elif path in self.control_plane_post_routes:
                    self._send_json(
                        {"error": f"Control-plane API {path} only accepts POST requests."},
                        status=405,
                    )
                elif path.startswith("/api/"):
                    self._send_json(
                        {
                            "error": (
                                "Runtime APIs are not forwarded by the simulator proxy; "
                                "connect directly to the selected simulator service."
                            )
                        },
                        status=404,
                    )
                else:
                    self._serve_static()
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
            except (OSError, RuntimeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)

        def _send_trainee_link(self) -> None:
            values = parse_qs(urlparse(self.path).query)
            model_id = str((values.get("model_id") or values.get("model") or [""])[0]).strip()
            if not model_id:
                raise ValueError("model_id is required")
            model = manager.model_info(model_id)
            service = model.get("service", {}) if isinstance(model, Mapping) else {}
            service_base = str(service.get("base_url") or "").rstrip("/")
            if service.get("state") != "running" or service.get("healthy") is not True or not service_base:
                raise RuntimeError(f"模型 {model_id} 的模拟服务尚未启动或健康检查未通过")
            request = Request(
                f"{service_base}/api/trainee-link",
                headers={"Accept": "application/json"},
            )
            try:
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"模型 {model_id} 的模拟服务交互链接读取失败：{exc}") from exc
            if not isinstance(payload, Mapping):
                raise RuntimeError(f"模型 {model_id} 的模拟服务返回了无效交互链接")
            actual_model_id = str(payload.get("model_id") or "").strip()
            if actual_model_id != model_id:
                raise RuntimeError(
                    f"模型服务标识不一致：请求 {model_id}，实际 {actual_model_id or '空'}"
                )
            host = self.headers.get("Host")
            if not host:
                server_host, server_port = self.server.server_address[:2]
                host = f"{server_host}:{server_port}"
            scheme = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
            proxy_base = f"{scheme}://{host}".rstrip("/")
            result = dict(payload)
            result["link"] = f"{proxy_base}/api/trainee-link?model_id={quote(model_id, safe='')}"
            result["discovery_via_proxy"] = True
            self._send_json(result)

        def do_POST(self) -> None:
            try:
                path = urlparse(self.path).path
                payload = self._read_json()
                model_id = payload.get("model_id", payload.get("model"))
                if path == "/api/simulator-services/start":
                    service = manager.start(model_id)
                elif path == "/api/simulator-services/stop":
                    service = manager.stop(model_id)
                elif path == "/api/models/create":
                    self._create_model(payload)
                    return
                elif path == "/api/models/update-definitions":
                    self._update_model(payload)
                    return
                elif path == "/api/models/clone":
                    name = payload.get("name", payload.get("model_name", payload.get("new_model_id")))
                    model = manager.clone_model(model_id, name)
                    self._send_json({"model": model, **manager.catalog()})
                    return
                elif path == "/api/models/delete":
                    deleted = manager.delete_model(model_id)
                    self._send_json({"deleted": deleted, **manager.catalog()})
                    return
                elif path == "/api/models/import-definitions":
                    self._import_definitions(payload)
                    return
                else:
                    self._send_json({"error": f"Unknown proxy API route: {path}"}, status=404)
                    return
                self._send_json({"model_id": str(model_id or ""), "service": service, **manager.catalog()})
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
            except (OSError, RuntimeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)

        @staticmethod
        def _server_helpers():
            try:
                from . import server as server_module
            except ImportError:  # pragma: no cover - legacy direct-module compatibility.
                import server as server_module

            return server_module

        @staticmethod
        def _decode_base64(payload: Mapping[str, Any], field: str, description: str) -> bytes:
            raw = str(payload.get(field, ""))
            if not raw:
                raise ValueError(f"{description} is required")
            try:
                return base64.b64decode(raw, validate=True)
            except ValueError as exc:
                raise ValueError(f"Invalid {description}") from exc

        def _create_model(self, payload: Mapping[str, Any]) -> None:
            helpers = self._server_helpers()
            name = payload.get("name", payload.get("model_name"))
            address = manager.validate_service_address(
                payload.get("service_host"),
                payload.get("service_port"),
            )
            model_text = helpers._decode_uploaded_definition_text(
                self._decode_base64(payload, "data_base64", "model.e data")
            )
            artifacts = helpers._generated_model_artifacts(model_text)
            diagram_svg_text = helpers._decode_optional_svg_payload(payload)
            with manager.lock:
                recovered_dir = helpers._recover_incomplete_model_directory(manager, name)
                target_id = manager.validate_new_model_name(name)
                target_dir = manager.models_root / target_id
                try:
                    written = helpers._write_generated_model_artifacts(
                        target_dir,
                        artifacts,
                        diagram_svg_text=diagram_svg_text,
                    )
                    model = manager.register_model(
                        target_id,
                        service_host=address["host"],
                        service_port=address["port"],
                    )
                except Exception:
                    if target_dir.exists():
                        shutil.rmtree(target_dir)
                    raise
            self._send_json(
                {
                    "model": {
                        **model,
                        "created": {
                            "files": written,
                            "measurement_count": len(artifacts["meas_book"].data["Measurement"].data),
                            "curve_points": artifacts["curves_payload"]["point_count"],
                            "recovered_incomplete_directory": str(recovered_dir) if recovered_dir else "",
                        },
                    },
                    **manager.catalog(),
                }
            )

        def _update_model(self, payload: Mapping[str, Any]) -> None:
            requested_model_id = payload.get("model_id", payload.get("model"))
            model_data = str(payload.get("data_base64") or "")
            diagram_data = str(payload.get("diagram_svg_base64") or "")

            if not model_data and not diagram_data:
                current_model = manager.model_info(requested_model_id)
                current_service = current_model.get("service", {})
                model = manager.configure_model_service(
                    requested_model_id,
                    payload.get("service_host", current_service.get("host")),
                    payload.get("service_port", current_service.get("port")),
                )
                service = model.get("service", {})
                address = {
                    "host": service.get("host"),
                    "port": service.get("port"),
                    "access_link": service.get("access_link"),
                    "base_url": service.get("base_url"),
                }
                updated = {"service": address}
                self._send_json({"model": {**model, "updated": updated}, "updated": updated})
                return

            helpers = self._server_helpers()
            target_id, target_dir, _runtime_dir = manager.require_stopped(requested_model_id)
            current_model = manager.model_info(target_id)
            current_service = current_model.get("service", {})
            requested_host = payload.get("service_host", current_service.get("host"))
            requested_port = payload.get("service_port", current_service.get("port"))
            address = manager.validate_service_address(
                requested_host,
                requested_port,
                exclude_model_id=target_id,
            )
            service_changed = (
                address["host"] != str(current_service.get("host") or "")
                or address["port"] != int(current_service.get("port", 0) or 0)
            )
            updated: dict[str, Any] = {
                "service": address,
            }
            if model_data:
                model_text = helpers._decode_uploaded_definition_text(
                    self._decode_base64(payload, "data_base64", "model.e data")
                )
                artifacts = helpers._generated_model_artifacts(model_text)
                written = helpers._write_generated_model_artifacts(
                    target_dir,
                    artifacts,
                    diagram_svg_text=helpers._decode_optional_svg_payload(payload),
                    remove_diagram_when_absent=bool(payload.get("replace_diagram", False)),
                    preserve_existing_curves=True,
                )
                manager.clear_model_runtime(target_id)
                updated.update(
                    {
                        "files": written,
                        "measurement_count": len(artifacts["meas_book"].data["Measurement"].data),
                        "curve_points": artifacts["curves_payload"]["point_count"],
                    }
                )
            elif diagram_data:
                diagram_written = helpers._write_model_diagram(
                    target_dir,
                    helpers._decode_optional_svg_payload(payload),
                )
                updated["diagram"] = {
                    "updated": bool(diagram_written),
                    "filename": "diagram.svg" if diagram_written else "",
                }
            if service_changed:
                model = manager.configure_model_service(target_id, address["host"], address["port"])
            else:
                model = manager.model_info(target_id)
            self._send_json({"model": {**model, "updated": updated}, "updated": updated, **manager.catalog()})

        def _write_parsed_archive(self, target_dir: Path, parsed: Mapping[str, Any]) -> Mapping[str, Any]:
            helpers = self._server_helpers()
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "model.e").write_text(str(parsed["model_text"]), encoding="utf-8", newline="")
            helpers.simu_loop.clear_model_book_cache(target_dir / "model.e")
            (target_dir / "meas.e").write_text(str(parsed["meas_text"]), encoding="utf-8", newline="")
            (target_dir / "control.e").write_text(str(parsed["control_text"]), encoding="utf-8", newline="")
            (target_dir / "curves.e").write_text(str(parsed["curves_text"]), encoding="utf-8", newline="")
            helpers._merge_control_definition(
                target_dir / "stat.e",
                str(parsed["control_text"]),
                str(parsed["model_text"]),
            )
            helpers._write_json_file(target_dir / "curves.json", parsed["curves_payload"])
            definition_defaults = parsed.get("definition_defaults")
            definition_defaults_path = target_dir / helpers.DEFINITION_DEFAULTS_FILE
            if isinstance(definition_defaults, Mapping):
                helpers._write_json_file(definition_defaults_path, definition_defaults)
            else:
                definition_defaults_path.unlink(missing_ok=True)
            diagram = helpers._write_model_diagram(
                target_dir,
                parsed.get("diagram_text"),
                remove_when_absent=True,
            )
            return {
                "written": 7 + (1 if diagram else 0),
                "curve_mode": parsed["curves_payload"].get("mode"),
                "curve_points": parsed["curves_payload"].get("point_count"),
                "load_count": len(parsed["curves_payload"].get("loads", {})),
                "diagram": diagram,
            }

        def _import_definitions(self, payload: Mapping[str, Any]) -> None:
            helpers = self._server_helpers()
            archive_data = self._decode_base64(payload, "data_base64", "definition archive data")
            parsed = helpers._parse_definition_archive(archive_data)
            if payload.get("create_model"):
                name = payload.get("name", payload.get("model_name"))
                target_id = manager.validate_new_model_name(name)
                target_dir = manager.models_root / target_id
                try:
                    imported = self._write_parsed_archive(target_dir, parsed)
                    model = manager.register_model(target_id)
                except Exception:
                    if target_dir.exists():
                        shutil.rmtree(target_dir)
                    raise
                self._send_json({"model": {**model, "imported": imported}, "imported": imported, **manager.catalog()})
                return
            target_id, target_dir, _runtime_dir = manager.require_stopped(
                payload.get("model_id", payload.get("model"))
            )
            imported = self._write_parsed_archive(target_dir, parsed)
            manager.clear_model_runtime(target_id)
            self._send_json({"imported": imported, **manager.catalog()})

        def _read_json(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON payload: {exc}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError("JSON payload must be an object")
            return payload

        def _serve_static(self) -> None:
            path = urlparse(self.path).path
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                target = root / "index.html"
            if not target.exists() or not target.is_file():
                target = root / "index.html"
            if not target.exists():
                self._send_json({"error": f"Static file not found: {relative}"}, status=404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self._cors(cache_control="no-store")
            self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _cors(self, *, cache_control: str = "no-store") -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Cache-Control", cache_control)

    class ManagedSimulatorProxyServer(ThreadingHTTPServer):
        _manager_closed = False

        def server_close(self) -> None:
            if not self._manager_closed:
                self._manager_closed = True
                manager.close()
            super().server_close()

    server = ManagedSimulatorProxyServer(server_address, SimulatorProxyHandler)
    server.cluster_manager = manager  # type: ignore[attr-defined]
    return server
