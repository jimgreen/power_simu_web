"""HTTP server for the polar microgrid simulator and trainee consoles."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import threading
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urljoin, urlparse
from urllib.request import Request, urlopen

try:
    from hybrid_power_system_analysis.efile_read import EBlock, EBook
except ImportError:  # The migrated web repo can run outside the original package tree.
    import sys

    ROOT_DIR = Path(__file__).resolve().parents[1]
    LEGACY_PACKAGE_DIR = (
        ROOT_DIR.parent
        / "elec_power_flow"
        / "hybrid_power_system_analysis"
        / "src"
        / "hybrid_power_system_analysis"
    )
    for package_dir in (ROOT_DIR / "src" / "hybrid_power_system_analysis", LEGACY_PACKAGE_DIR):
        if (package_dir / "efile_read.py").exists() and str(package_dir) not in sys.path:
            sys.path.insert(0, str(package_dir))
    from efile_read import EBlock, EBook

try:
    from .service import MultiModelSimulator, PolarMicrogridSimulator
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.polar_microgrid_sim.service import MultiModelSimulator, PolarMicrogridSimulator

try:
    import simu_loop  # type: ignore
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.simu import simu_loop


PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
CLOCK_BASE_INTERVAL_SECONDS = 1.0
ROLE_MODEL_DIRS = {
    "simulator": ("models", "simulator"),
    "trainee": ("models", "trainee"),
}
CONTROL_DEFINITION_BLOCKS = {"RunStat", "CbOpenStat", "SetValue"}


def _clock_int_value(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(round(float(value))))
    except (TypeError, ValueError):
        return default


def _role_models_base_dir(sim_dir: Path, role: str) -> Path:
    parts = ROLE_MODEL_DIRS.get(role.lower(), ("models", role.lower()))
    return sim_dir.joinpath(*parts)


def _default_models_dir(sim_dir: Path, role: str) -> Path:
    """Keep simulator and trainee model sources physically separate by default."""
    return _role_models_base_dir(sim_dir, role) / "source"


def _default_runtime_dir(sim_dir: Path, role: str) -> Path:
    return _role_models_base_dir(sim_dir, role) / "runtime"


def _definition_file_path(service: PolarMicrogridSimulator, file_key: str, file_name: str) -> Path:
    runtime_path = Path(service.files.get(file_key, service.runtime_dir / file_name))
    if runtime_path.exists():
        return runtime_path
    return service.sim_dir / file_name


def _book_from_text(text: str) -> EBook:
    book = EBook({})
    block: Optional[EBlock] = None
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("<") and line.endswith(">"):
            if line.startswith("</"):
                if block is not None:
                    book.data[block.name] = block
                block = None
            else:
                block = EBlock(line[1:-1])
            continue
        if block is None:
            raise ValueError(f"Invalid E file row before block at line {line_no}")
        if line.startswith("@"):
            block.header_list = line[1:].split()
        elif line.startswith("#"):
            block.AddRow(line[1:].split())
        else:
            raise ValueError(f"Invalid E file row at line {line_no}: {line}")
    return book


def _merge_control_definition(stat_path: Path, control_text: str) -> None:
    stat_book = EBook(stat_path) if stat_path.exists() else EBook({})
    control_book = _book_from_text(control_text)
    found = False
    for block_name in CONTROL_DEFINITION_BLOCKS:
        block = control_book.data.get(block_name)
        if block is not None:
            stat_book.data[block_name] = block
            found = True
    if not found:
        raise ValueError("control.e must contain at least one control block")
    simu_loop.write_ebook_aligned(stat_book, stat_path)


def _extract_efile_blocks(text: str, names: set[str]) -> str:
    parts: list[str] = []
    capturing = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("<") and stripped.endswith(">") and not stripped.startswith("</"):
            block_name = stripped[1:-1]
            capturing = block_name in names
        if capturing:
            parts.append(line)
        if stripped.startswith("</") and stripped.endswith(">"):
            capturing = False
    return "".join(parts)


def _definition_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _definition_number(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def _aligned_efile_text(blocks: Mapping[str, tuple[list[str], list[Mapping[str, Any]]]]) -> str:
    parts: list[str] = []
    for block_name, (headers, rows) in blocks.items():
        widths = [len(header) for header in headers]
        normalized_rows = []
        for row in rows:
            normalized = [_definition_cell(row.get(header, "")) for header in headers]
            normalized_rows.append(normalized)
            widths = [max(width, len(value)) for width, value in zip(widths, normalized)]
        parts.append(f"<{block_name}>\n")
        parts.append("@ " + "  ".join(f"{header:<{widths[idx]}}" for idx, header in enumerate(headers)).rstrip() + "\n")
        for row in normalized_rows:
            parts.append("# " + "  ".join(f"{value:<{widths[idx]}}" for idx, value in enumerate(row)).rstrip() + "\n")
        parts.append(f"</{block_name}>\n")
    return "".join(parts)


def _curve_definition_text(curves: Mapping[str, Any]) -> str:
    mode = str(curves.get("mode", "day") or "day")
    time_step_minutes = curves.get("time_step_minutes", "")
    weather = curves.get("weather", [])
    loads = curves.get("loads", {})
    point_count = curves.get("point_count", len(weather) if isinstance(weather, list) else "")

    info_rows = [
        {
            "mode": mode,
            "time_step_minutes": time_step_minutes,
            "point_count": point_count,
        }
    ]
    env_rows: list[Mapping[str, Any]] = []
    if isinstance(weather, list):
        for idx, point in enumerate(weather, start=1):
            if isinstance(point, Mapping):
                env_rows.append(
                    {
                        "idx": idx,
                        "minute": point.get("minute", idx - 1),
                        "wind_speed_mps": point.get("wind_speed_mps", ""),
                        "air_temp_c": point.get("air_temp_c", ""),
                        "air_pressure_hpa": point.get("air_pressure_hpa", ""),
                        "solar_irradiance_w_m2": point.get("solar_irradiance_w_m2", ""),
                        "humidity_pct": point.get("humidity_pct", ""),
                    }
                )

    load_rows: list[Mapping[str, Any]] = []
    if isinstance(loads, Mapping):
        for load_name, points in loads.items():
            if not isinstance(points, list):
                continue
            for idx, point in enumerate(points, start=1):
                if isinstance(point, Mapping):
                    load_rows.append(
                        {
                            "idx": idx,
                            "load_name": load_name,
                            "minute": point.get("minute", idx - 1),
                            "p_kw": point.get("p_kw", ""),
                        }
                    )

    return _aligned_efile_text(
        {
            "CurveInfo": (["mode", "time_step_minutes", "point_count"], info_rows),
            "EnvironmentCurve": (
                [
                    "idx",
                    "minute",
                    "wind_speed_mps",
                    "air_temp_c",
                    "air_pressure_hpa",
                    "solar_irradiance_w_m2",
                    "humidity_pct",
                ],
                env_rows,
            ),
            "LoadCurve": (["idx", "load_name", "minute", "p_kw"], load_rows),
        }
    )


def _curves_from_definition_text(text: str) -> Mapping[str, Any]:
    book = _book_from_text(text)
    info_block = book.data.get("CurveInfo")
    info = info_block.data[0] if info_block is not None and info_block.data else {}
    payload: dict[str, Any] = {
        "mode": str(info.get("mode", "day") or "day"),
        "time_step_minutes": _definition_number(info.get("time_step_minutes", 1)),
        "point_count": _definition_number(info.get("point_count", 0)),
        "weather": [],
        "loads": {},
    }

    env_block = book.data.get("EnvironmentCurve")
    if env_block is not None:
        weather_rows = []
        for row in env_block.data:
            weather_rows.append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "wind_speed_mps": _definition_number(row.get("wind_speed_mps", "")),
                    "air_temp_c": _definition_number(row.get("air_temp_c", "")),
                    "air_pressure_hpa": _definition_number(row.get("air_pressure_hpa", "")),
                    "solar_irradiance_w_m2": _definition_number(row.get("solar_irradiance_w_m2", "")),
                    "humidity_pct": _definition_number(row.get("humidity_pct", "")),
                }
            )
        payload["weather"] = weather_rows

    load_block = book.data.get("LoadCurve")
    loads: dict[str, list[Mapping[str, Any]]] = {}
    if load_block is not None:
        for row in load_block.data:
            load_name = str(row.get("load_name", "")).strip()
            if not load_name:
                continue
            loads.setdefault(load_name, []).append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "p_kw": _definition_number(row.get("p_kw", "")),
                }
            )
    payload["loads"] = loads
    if not payload["point_count"]:
        payload["point_count"] = len(payload["weather"])
    return payload


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_zip_text(archive: zipfile.ZipFile, entry_name: str, required: bool = True) -> Optional[str]:
    try:
        data = archive.read(entry_name)
    except KeyError:
        if required:
            raise ValueError(f"Definition archive is missing {entry_name}") from None
        return None
    return data.decode("utf-8-sig")


def import_definition_archive(service: PolarMicrogridSimulator, data: bytes) -> Mapping[str, Any]:
    try:
        archive = zipfile.ZipFile(BytesIO(data), mode="r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid definition archive") from exc

    with archive:
        model_text = _read_zip_text(archive, "model.e")
        meas_text = _read_zip_text(archive, "meas.e")
        control_text = _read_zip_text(archive, "control.e")
        curves_text = _read_zip_text(archive, "curves.e")

    assert model_text is not None and meas_text is not None and control_text is not None and curves_text is not None
    curves_payload = _curves_from_definition_text(curves_text)
    written_files: list[str] = []
    for root in (service.sim_dir, service.runtime_dir):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        (root / "model.e").write_text(model_text, encoding="utf-8")
        (root / "meas.e").write_text(meas_text, encoding="utf-8")
        (root / "control.e").write_text(control_text, encoding="utf-8")
        (root / "curves.e").write_text(curves_text, encoding="utf-8")
        _merge_control_definition(root / "stat.e", control_text)
        _write_json_file(root / "curves.json", curves_payload)
        written_files.extend(str(root / name) for name in ("model.e", "meas.e", "control.e", "curves.e", "stat.e", "curves.json"))

    service.curves = dict(curves_payload)
    service.latest_measurements = {"real": [], "scada": [], "definitions": []}
    return {
        "written": len(written_files),
        "files": written_files,
        "curve_mode": curves_payload.get("mode"),
        "curve_points": curves_payload.get("point_count"),
        "load_count": len(curves_payload.get("loads", {})),
    }


def make_definition_archive(service: PolarMicrogridSimulator) -> tuple[str, bytes]:
    model_path = _definition_file_path(service, "model", "model.e")
    meas_path = _definition_file_path(service, "meas", "meas.e")
    stat_path = _definition_file_path(service, "stat", "stat.e")
    missing = [str(path) for path in (model_path, meas_path, stat_path) if not path.exists()]
    if missing:
        raise JsonApiError(404, f"Definition file not found: {', '.join(missing)}")

    control_text = stat_path.read_text(encoding="utf-8")
    control_text = _extract_efile_blocks(control_text, CONTROL_DEFINITION_BLOCKS) or control_text
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_id = getattr(service, "model_id", "model") or "model"
    archive_name = f"{model_id}_definitions_{timestamp}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(model_path, "model.e")
        archive.write(meas_path, "meas.e")
        archive.writestr("control.e", control_text.encode("utf-8"))
        archive.writestr("curves.e", _curve_definition_text(service.curves).encode("utf-8"))
    return archive_name, buffer.getvalue()


class JsonApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def make_http_server(
    server_address: tuple[str, int],
    service: PolarMicrogridSimulator | MultiModelSimulator,
    *,
    role: str = "simulator",
    static_root: Optional[str | Path] = None,
    sim_url: Optional[str] = None,
) -> ThreadingHTTPServer:
    role = role.lower()
    if static_root is None:
        static_root = WEB_DIR / ("trainee" if role == "trainee" else "simulator")
    static_root = Path(static_root).resolve()
    sim_url = sim_url.rstrip("/") if sim_url else None

    class PolarMicrogridHandler(BaseHTTPRequestHandler):
        server_version = "PolarMicrogridHTTP/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            try:
                if self.path.startswith("/api/") and role == "trainee" and sim_url:
                    self._proxy_to_simulator("GET", sim_url)
                    return
                if self.path.startswith("/api/"):
                    self._handle_api_get()
                    return
                self._serve_static(static_root)
            except JsonApiError as exc:
                self._send_json({"error": exc.message}, status=exc.status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            try:
                if self.path.startswith("/api/") and role == "trainee" and sim_url:
                    self._proxy_to_simulator("POST", sim_url)
                    return
                self._handle_api_post()
            except JsonApiError as exc:
                self._send_json({"error": exc.message}, status=exc.status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def do_PUT(self) -> None:
            self.do_POST()

        def _request_model_id(self, payload: Optional[Mapping[str, Any]] = None) -> Optional[str]:
            parsed = urlparse(self.path)
            query_values = parse_qs(parsed.query).get("model_id") or parse_qs(parsed.query).get("model")
            if query_values and query_values[0]:
                return query_values[0]
            if payload:
                value = payload.get("model_id", payload.get("model"))
                return str(value) if value not in (None, "") else None
            return None

        def _target_service(self, payload: Optional[Mapping[str, Any]] = None) -> PolarMicrogridSimulator:
            if hasattr(service, "service_for"):
                try:
                    return service.service_for(self._request_model_id(payload))  # type: ignore[union-attr]
                except KeyError as exc:
                    raise JsonApiError(404, str(exc)) from exc
            return service  # type: ignore[return-value]

        def _model_catalog(self) -> Mapping[str, Any]:
            if hasattr(service, "models"):
                return {
                    "models": service.models(),  # type: ignore[union-attr]
                    "active_model_id": service.default_model_id,  # type: ignore[union-attr]
                    "models_root": str(service.models_root),  # type: ignore[union-attr]
                }
            return {
                "models": [service.model_info()],  # type: ignore[union-attr]
                "active_model_id": service.model_id,  # type: ignore[union-attr]
                "models_root": str(service.sim_dir),  # type: ignore[union-attr]
            }

        def _handle_api_get(self) -> None:
            path = urlparse(self.path).path
            target = self._target_service()
            if path == "/api/health":
                self._send_json({"ok": True, "role": role})
            elif path == "/api/models":
                self._send_json(self._model_catalog())
            elif path == "/api/snapshot":
                self._send_json(target.snapshot())
            elif path == "/api/measurements":
                self._send_json(target.measurements())
            elif path == "/api/devices":
                self._send_json({"devices": target.devices()})
            elif path == "/api/curves":
                self._send_json(target.curves)
            elif path == "/api/settings":
                self._send_json(target.local_settings)
            elif path == "/api/config":
                self._send_json({"role": role, "sim_url": sim_url, "poll_ms": 2000, **self._model_catalog()})
            elif path == "/api/export-definitions":
                parsed = urlparse(self.path)
                response_format = (parse_qs(parsed.query).get("format") or ["zip"])[0]
                if response_format == "json":
                    self._send_definition_archive_json(target)
                else:
                    self._send_definition_archive(target)
            else:
                raise JsonApiError(404, f"Unknown API route: {path}")

        def _handle_api_post(self) -> None:
            path = urlparse(self.path).path
            payload = self._read_json_body()
            if path == "/api/models/clone":
                if not hasattr(service, "clone_model"):
                    raise JsonApiError(400, "Current simulator does not support multiple model folders")
                model_name = payload.get("name", payload.get("model_name", payload.get("new_model_id", "")))
                if not str(model_name or "").strip():
                    raise JsonApiError(400, "New model name is required")
                try:
                    model = service.clone_model(self._request_model_id(payload), model_name)  # type: ignore[union-attr]
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = model["id"]
                self._send_json({"model": model, **catalog})
                return
            if path == "/api/models/import-definitions":
                data_base64 = str(payload.get("data_base64", ""))
                if not data_base64:
                    raise JsonApiError(400, "Definition archive data is required")
                try:
                    archive_data = base64.b64decode(data_base64, validate=True)
                    imported = import_definition_archive(self._target_service(payload), archive_data)
                except (ValueError, OSError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json({"imported": imported, **self._model_catalog()})
                return

            target = self._target_service(payload)
            if path == "/api/student/commands":
                self._send_json(target.apply_student_commands(payload, source=str(payload.get("source", ""))))
            elif path == "/api/clock":
                self._send_json(target.control_clock(payload))
            elif path == "/api/step":
                self._send_json(target.step())
            elif path == "/api/curves":
                self._send_json(target.set_curves(payload))
            elif path == "/api/settings":
                self._send_json(target.set_local_settings(payload))
            elif path == "/api/device-faults":
                self._send_json(target.set_local_settings({"device_faults": payload.get("items", payload)}))
            elif path == "/api/measurement-faults":
                self._send_json(target.set_local_settings({"measurement_faults": payload.get("items", payload)}))
            elif path == "/api/modes":
                self._send_json(target.set_local_settings({"modes": payload.get("items", payload)}))
            else:
                raise JsonApiError(404, f"Unknown API route: {path}")

        def _read_json_body(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise JsonApiError(400, f"Invalid JSON payload: {exc}") from exc
            if not isinstance(payload, Mapping):
                raise JsonApiError(400, "JSON payload must be an object")
            return payload

        def _serve_static(self, root: Path) -> None:
            path = urlparse(self.path).path
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)) or not target.exists() or not target.is_file():
                target = root / "index.html"
            if not target.exists():
                raise JsonApiError(404, f"Static file not found: {rel}")
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _proxy_to_simulator(self, method: str, base_url: str) -> None:
            path = self.path
            body = None
            headers = {"Accept": "application/json"}
            if method in ("POST", "PUT"):
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b"{}"
                headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
            request = Request(urljoin(base_url + "/", path.lstrip("/")), data=body, headers=headers, method=method)
            try:
                with urlopen(request, timeout=10) as response:
                    data = response.read()
                    status = response.status
                    content_type = response.headers.get("Content-Type", "application/json")
            except HTTPError as exc:
                data = exc.read()
                status = exc.code
                content_type = exc.headers.get("Content-Type", "application/json")
            except URLError as exc:
                raise JsonApiError(502, f"Simulator is unreachable: {exc}") from exc
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_definition_archive(self, target: PolarMicrogridSimulator) -> None:
            filename, data = make_definition_archive(target)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/zip")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"model_definitions.zip\"; filename*=UTF-8''{quote(filename)}",
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_definition_archive_json(self, target: PolarMicrogridSimulator) -> None:
            filename, data = make_definition_archive(target)
            self._send_json(
                {
                    "filename": filename,
                    "content_type": "application/zip",
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }
            )

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Cache-Control", "no-store")

    server = ThreadingHTTPServer(server_address, PolarMicrogridHandler)
    server.service = service  # type: ignore[attr-defined]
    return server


def _advance_clock_if_due(service: PolarMicrogridSimulator, last_step: float) -> float:
    clock = service.snapshot()["clock"]
    now = time.monotonic()
    if clock["state"] != "running":
        return now
    if now - last_step < CLOCK_BASE_INTERVAL_SECONDS:
        return last_step
    speed_minutes = _clock_int_value(clock.get("speed"), 1)
    step_minutes = _clock_int_value(clock.get("step_minutes"), 1)
    # Do not catch up by elapsed wall time: one completed solve advances one logical simulation step.
    advance_minutes = speed_minutes * step_minutes
    try:
        service.step(advance_minutes=advance_minutes)
    except Exception:
        service.control_clock({"action": "pause"})
    return time.monotonic()


def start_clock_worker(service: PolarMicrogridSimulator, stop_event: threading.Event) -> threading.Thread:
    def worker() -> None:
        last_step = time.monotonic()
        while not stop_event.is_set():
            last_step = _advance_clock_if_due(service, last_step)
            stop_event.wait(0.05)

    thread = threading.Thread(target=worker, name=f"polar-microgrid-clock-{service.model_id}", daemon=True)
    thread.start()
    return thread


def start_multi_model_clock_worker(service: MultiModelSimulator, stop_event: threading.Event) -> threading.Thread:
    def worker() -> None:
        last_steps: dict[str, float] = {}
        while not stop_event.is_set():
            current_ids = set()
            for item in service.iter_services():
                current_ids.add(item.model_id)
                last_steps[item.model_id] = _advance_clock_if_due(
                    item,
                    last_steps.get(item.model_id, time.monotonic()),
                )
            for stale_id in set(last_steps) - current_ids:
                last_steps.pop(stale_id, None)
            stop_event.wait(0.05)

    thread = threading.Thread(target=worker, name="polar-microgrid-clock-models", daemon=True)
    thread.start()
    return thread


def start_clock_workers(
    service: PolarMicrogridSimulator | MultiModelSimulator,
    stop_event: threading.Event,
) -> list[threading.Thread]:
    if hasattr(service, "iter_services"):
        return [start_multi_model_clock_worker(service, stop_event)]  # type: ignore[arg-type]
    return [start_clock_worker(service, stop_event)]  # type: ignore[arg-type]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve polar microgrid simulator or trainee console.")
    parser.add_argument("--role", choices=("simulator", "trainee"), default="simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--sim-dir", default=str(simu_loop.SIMU_DIR))
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Directory whose direct subfolders are simulation models. Defaults to models/<role>/source.",
    )
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--sim-url", default=None, help="Simulator API base URL for trainee proxy mode.")
    parser.add_argument("--static-root", default=None)
    parser.add_argument("--no-worker", action="store_true", help="Do not start automatic clock worker.")
    parser.add_argument("--noise-std", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    port = args.port if args.port is not None else (8720 if args.role == "trainee" else 8710)
    sim_dir = Path(args.sim_dir).resolve()
    runtime_dir = Path(args.runtime_dir).resolve() if args.runtime_dir else _default_runtime_dir(sim_dir, args.role)
    models_dir = Path(args.models_dir).resolve() if args.models_dir else _default_models_dir(sim_dir, args.role)
    service = MultiModelSimulator.discover(
        sim_dir=sim_dir,
        runtime_dir=runtime_dir,
        noise_std=args.noise_std,
        random_seed=args.seed,
        models_dir=models_dir,
    )
    server = make_http_server(
        (args.host, port),
        service,
        role=args.role,
        static_root=args.static_root,
        sim_url=args.sim_url,
    )
    stop_event = threading.Event()
    workers = [] if args.no_worker else start_clock_workers(service, stop_event)
    print(f"{args.role} console: http://{args.host}:{port}/")
    print(f"runtime dir: {runtime_dir}")
    print(f"models dir: {service.models_root}")
    print(f"models: {', '.join(item['id'] for item in service.models())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=2)
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
