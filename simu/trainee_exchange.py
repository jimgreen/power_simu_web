from __future__ import annotations

import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, ContextManager, Dict, Iterator, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


CONTROL_STATIC_FIELDS = ("definitions", "settings", "device_parameters")


class TraineeExchangeLifecycleError(RuntimeError):
    """Raised when an exchange request outlives its captured service generation."""


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Mapping[str, Any]] = None,
    timeout: float = 8.0,
) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if method in {"POST", "PUT"}:
        body = json.dumps(payload or {}, ensure_ascii=False, default=str).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail or str(exc.reason)) from exc
    except URLError as exc:
        raise RuntimeError(f"学员台实时数据源不可达：{exc.reason}") from exc
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("学员台实时数据源返回内容不是有效 JSON") from exc


def _url_with_query(path: str, **overrides: Any) -> str:
    parsed = urlparse(path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in overrides.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = [str(value)]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )


@dataclass(frozen=True)
class TraineeControlGeneration:
    model_id: str
    service_instance_id: str
    receive_epoch: int
    connection_signature: Tuple[Any, ...]
    definition_revision: int


@dataclass(frozen=True)
class TraineeControlDispatchPermit:
    generation: TraineeControlGeneration
    submitter: Callable[[], Mapping[str, Any]] = field(
        repr=False,
        compare=False,
    )

    def submit(self) -> Dict[str, Any]:
        result = self.submitter()
        return copy.deepcopy(dict(result))


@dataclass(frozen=True)
class TraineeControlDispatchTicket:
    generation: TraineeControlGeneration
    preparer: Callable[
        [Mapping[str, Any], Optional[Callable[[], None]]],
        TraineeControlDispatchPermit,
    ] = field(
        repr=False,
        compare=False,
    )
    guard_factory: Callable[
        [TraineeControlGeneration],
        ContextManager["TraineeControlGenerationValidation"],
    ] = field(repr=False, compare=False)

    def prepare(
        self,
        payload: Mapping[str, Any],
        *,
        on_transport_start: Optional[Callable[[], None]] = None,
    ) -> TraineeControlDispatchPermit:
        return self.preparer(payload, on_transport_start)

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        return self.prepare(payload).submit()

    def guard(self) -> ContextManager["TraineeControlGenerationValidation"]:
        return self.guard_factory(self.generation)


@dataclass(frozen=True)
class TraineeControlGenerationValidation:
    valid: bool
    dispatch_ticket: Optional[TraineeControlDispatchTicket] = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __bool__(self) -> bool:
        return self.valid


@dataclass(frozen=True)
class TraineeControlLease:
    generation: TraineeControlGeneration
    guard_factory: Callable[
        [TraineeControlGeneration],
        ContextManager[TraineeControlGenerationValidation],
    ] = field(
        repr=False,
        compare=False,
    )

    def guard(self) -> ContextManager[TraineeControlGenerationValidation]:
        return self.guard_factory(self.generation)


@dataclass(frozen=True)
class TraineeControlSnapshot:
    snapshot: Dict[str, Any]
    source: str
    age_seconds: float
    error: Optional[str]
    receive_active: bool
    ready: bool
    revision: int
    connection_signature: Tuple[Any, ...]
    receive_epoch: int = 0
    control_lease: Optional[TraineeControlLease] = field(default=None, repr=False, compare=False)


@dataclass
class _ExchangeState:
    model_id: str
    service_instance_id: str = ""
    runtime_snapshot: Optional[Dict[str, Any]] = None
    received_at: float = 0.0
    last_error: str = ""
    revision: int = 0
    receive_epoch: int = 0
    connection_signature: Tuple[Any, ...] = ()
    measurement_delta_seq: int = 0
    measurement_delta_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    measurement_delta_history: list[Dict[str, Any]] = field(default_factory=list)
    frame_identity: Tuple[Tuple[str, str], ...] = ()
    frame_changed_at: float = 0.0
    last_attempt_at: float = 0.0
    last_success_at: float = 0.0
    consecutive_failures: int = 0
    last_request_duration_seconds: float = 0.0
    last_response_size_bytes: int = 0
    command_attempt_count: int = 0
    command_success_count: int = 0
    command_failure_count: int = 0
    command_accepted_count: int = 0
    command_rejected_count: int = 0
    command_ambiguous_failure_count: int = 0
    last_command_attempt_at: float = 0.0
    last_command_success_at: float = 0.0
    last_command_duration_seconds: float = 0.0
    last_command_error: str = ""
    next_refresh_at_monotonic: float = 0.0
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    fetch_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass(frozen=True)
class _RefreshRequestToken:
    model_id: str
    service_instance_id: str
    connection_signature: Tuple[Any, ...]
    receive_epoch: int


def _device_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return (
        str(device.get("dev_type", device.get("type", ""))),
        str(device.get("dev_name", device.get("name", ""))),
    )


def _measurement_definition_identity(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(row.get("dev_type", "")),
        str(row.get("dev_name", "")),
        str(row.get("meas_type", "")).upper(),
    )


def _merge_remote_measurements_with_local_definitions(
    remote_measurements: Any,
    local_snapshot: Mapping[str, Any],
) -> Any:
    if not isinstance(remote_measurements, Mapping):
        return copy.deepcopy(remote_measurements)
    definitions = local_snapshot.get("definitions")
    local_rows = definitions.get("measurement") if isinstance(definitions, Mapping) else None
    if not isinstance(local_rows, Sequence) or isinstance(local_rows, (str, bytes)):
        local_measurements = local_snapshot.get("measurements")
        local_rows = local_measurements.get("definitions") if isinstance(local_measurements, Mapping) else None
    if not isinstance(local_rows, Sequence) or isinstance(local_rows, (str, bytes)):
        return copy.deepcopy(remote_measurements)

    normalized_rows = [dict(row) for row in local_rows if isinstance(row, Mapping)]
    by_name = {
        str(row.get("name", "")): row
        for row in normalized_rows
        if str(row.get("name", ""))
    }
    by_identity = {
        _measurement_definition_identity(row): row
        for row in normalized_rows
        if all(_measurement_definition_identity(row))
    }
    merged = copy.deepcopy(dict(remote_measurements))
    merged["definitions"] = normalized_rows
    for channel in ("real", "scada"):
        rows = merged.get(channel)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        updated_rows = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                updated_rows.append(copy.deepcopy(raw_row))
                continue
            row = dict(raw_row)
            definition = by_name.get(str(row.get("name", ""))) or by_identity.get(
                _measurement_definition_identity(row)
            )
            if definition is not None:
                for field_name in ("weight", "valid"):
                    if field_name in definition:
                        row[field_name] = copy.deepcopy(definition[field_name])
            updated_rows.append(row)
        merged[channel] = updated_rows
    return merged


def _merge_remote_runtime_devices(local_devices: Any, remote_devices: Any) -> Any:
    if not isinstance(local_devices, Sequence) or isinstance(local_devices, (str, bytes)):
        return copy.deepcopy(remote_devices)
    remote_by_key = {
        _device_key(device): device
        for device in remote_devices or []
        if isinstance(device, Mapping)
    }
    runtime_fields = ("run_stat", "status", "mode", "set_values", "soc_curr")
    merged_devices = []
    for raw_local in local_devices:
        if not isinstance(raw_local, Mapping):
            merged_devices.append(copy.deepcopy(raw_local))
            continue
        local_device = copy.deepcopy(dict(raw_local))
        remote_device = remote_by_key.get(_device_key(local_device))
        if remote_device is not None:
            for field_name in runtime_fields:
                if field_name in remote_device:
                    local_device[field_name] = copy.deepcopy(remote_device[field_name])
        merged_devices.append(local_device)
    return merged_devices


def _merge_runtime_snapshot_with_local_definitions(
    runtime_snapshot: Mapping[str, Any],
    local_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    merged = copy.deepcopy(dict(runtime_snapshot))
    for key in CONTROL_STATIC_FIELDS:
        if key in local_snapshot:
            merged[key] = copy.deepcopy(local_snapshot[key])
    if "model" in local_snapshot:
        merged["model"] = copy.deepcopy(local_snapshot["model"])
    if "devices" in local_snapshot:
        merged["devices"] = _merge_remote_runtime_devices(
            local_snapshot.get("devices"),
            runtime_snapshot.get("devices"),
        )
    if "measurements" in runtime_snapshot:
        merged["measurements"] = _merge_remote_measurements_with_local_definitions(
            runtime_snapshot.get("measurements"),
            local_snapshot,
        )
    if "static_meta" in local_snapshot:
        merged["static_meta"] = copy.deepcopy(local_snapshot["static_meta"])
    return merged


def _measurement_delta_signature(item: Mapping[str, Any]) -> str:
    comparable = {
        "value": item.get("value"),
        "real_value": item.get("real_value"),
        "scada_value": item.get("scada_value"),
        "valid": item.get("valid"),
        "weight": item.get("weight"),
    }
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _measurement_delta_items(
    snapshot: Mapping[str, Any],
    *,
    received_at: float,
) -> Dict[str, Dict[str, Any]]:
    measurements = snapshot.get("measurements")
    if not isinstance(measurements, Mapping):
        return {}
    definitions = measurements.get("definitions") or []
    if not isinstance(definitions, Sequence) or isinstance(definitions, (str, bytes)):
        definitions = []
    real_rows = measurements.get("real") or []
    scada_rows = measurements.get("scada") or []
    real_by_name = {
        str(row.get("name", "")): row
        for row in real_rows
        if isinstance(row, Mapping) and str(row.get("name", ""))
    }
    scada_by_name = {
        str(row.get("name", "")): row
        for row in scada_rows
        if isinstance(row, Mapping) and str(row.get("name", ""))
    }
    clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
    simu_time = str(clock.get("time") or "--")
    absolute_minute = clock.get("absolute_minute")
    wall_time = (
        datetime.fromtimestamp(received_at).strftime("%H:%M:%S")
        if received_at
        else "--"
    )
    items: Dict[str, Dict[str, Any]] = {}
    for definition in definitions:
        if not isinstance(definition, Mapping):
            continue
        name = str(definition.get("name", "")).strip()
        if not name:
            continue
        real = real_by_name.get(name)
        scada = scada_by_name.get(name)
        real_value = copy.deepcopy(real.get("value")) if real is not None else None
        scada_value = copy.deepcopy(scada.get("value")) if scada is not None else None
        try:
            valid = int(float(definition.get("valid", 0) or 0))
        except (TypeError, ValueError):
            valid = 0
        items[name] = {
            "name": name,
            "value": copy.deepcopy(scada_value if scada is not None else real_value),
            "real_value": real_value,
            "scada_value": scada_value,
            "valid": valid,
            "weight": copy.deepcopy(definition.get("weight", "")),
            "updated_wall_time": wall_time,
            "updated_simu_time": simu_time,
            "updated_absolute_minute": absolute_minute,
        }
    return items


def _runtime_frame_identity(snapshot: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
    identity: list[Tuple[str, str]] = []
    for field_name in ("run_id", "step_count", "absolute_minute", "minute", "time"):
        value = clock.get(field_name, snapshot.get(field_name))
        if value is None or str(value).strip() == "":
            continue
        identity.append((field_name, str(value)))
    return tuple(identity)


def _wall_time_text(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if timestamp else ""


class TraineeRealtimeExchange:
    def __init__(
        self,
        services: Any,
        *,
        request_json: Optional[Callable[..., Any]] = None,
        poll_interval_seconds: Optional[float] = None,
        frame_age_limit_seconds: Optional[float] = None,
        same_frame_limit_seconds: Optional[float] = None,
        measurement_delta_history_limit: Optional[int] = None,
        refresh_worker_count: int = 4,
        start_worker: bool = True,
    ) -> None:
        self.services = services
        self.request_json = request_json or _request_json
        self._poll_interval_override = (
            max(0.1, float(poll_interval_seconds))
            if poll_interval_seconds is not None
            else None
        )
        self._frame_age_limit_override = (
            max(0.0, float(frame_age_limit_seconds))
            if frame_age_limit_seconds is not None
            else None
        )
        self._same_frame_limit_override = (
            max(0.0, float(same_frame_limit_seconds))
            if same_frame_limit_seconds is not None
            else None
        )
        self._measurement_delta_history_override = (
            max(1, int(measurement_delta_history_limit))
            if measurement_delta_history_limit is not None
            else None
        )
        self.poll_interval_seconds = self._poll_interval_override or 1.0
        self.frame_age_limit_seconds = self._frame_age_limit_override if self._frame_age_limit_override is not None else 15.0
        self.same_frame_limit_seconds = self._same_frame_limit_override if self._same_frame_limit_override is not None else 30.0
        self.measurement_delta_history_limit = self._measurement_delta_history_override or 200
        self._states: Dict[str, _ExchangeState] = {}
        self._states_lock = threading.RLock()
        self._last_registry_error = ""
        self._last_registry_success_at = 0.0
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._refresh_pending: set[Tuple[str, str]] = set()
        self._refresh_pending_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._refresh_executor = ThreadPoolExecutor(
            max_workers=max(1, int(refresh_worker_count)),
            thread_name_prefix="trainee-exchange",
        )
        self._worker: Optional[threading.Thread] = None
        if start_worker:
            self._start_worker()

    def _runtime_settings_for_service(self, service: Any) -> Dict[str, Any]:
        settings = {
            "backend_refresh_seconds": self.poll_interval_seconds,
            "backend_request_timeout_seconds": 8.0,
            "frame_age_limit_seconds": self.frame_age_limit_seconds,
            "same_frame_limit_seconds": self.same_frame_limit_seconds,
            "runtime_log_page_size": 20,
            "measurement_delta_history_limit": self.measurement_delta_history_limit,
        }
        getter = getattr(service, "web_runtime_settings", None)
        if callable(getter):
            try:
                payload = getter("trainee")
                saved = payload.get("effectiveSettings", payload.get("settings", {}))
                if isinstance(saved, Mapping):
                    settings.update(saved)
            except (TypeError, ValueError):
                pass
        if self._poll_interval_override is not None:
            settings["backend_refresh_seconds"] = self._poll_interval_override
        if self._frame_age_limit_override is not None:
            settings["frame_age_limit_seconds"] = self._frame_age_limit_override
        if self._same_frame_limit_override is not None:
            settings["same_frame_limit_seconds"] = self._same_frame_limit_override
        if self._measurement_delta_history_override is not None:
            settings["measurement_delta_history_limit"] = self._measurement_delta_history_override
        return settings

    def _service_for(self, model_id: Optional[str]) -> Any:
        if hasattr(self.services, "service_for"):
            return self.services.service_for(model_id)
        return self.services

    def _service_is_current_registry_instance(self, service: Any) -> bool:
        if hasattr(self.services, "service_for"):
            try:
                current = self.services.service_for(str(getattr(service, "model_id", "default")))
            except KeyError:
                return False
            return current is service
        return self.services is service

    @staticmethod
    def _service_instance_id(service: Any) -> str:
        value = str(getattr(service, "service_instance_id", "") or "").strip()
        return value or f"object:{id(service)}"

    @staticmethod
    def _service_instance_active_locked(service: Any) -> bool:
        checker = getattr(service, "_service_instance_active_locked", None)
        if callable(checker):
            return bool(checker())
        return not bool(getattr(service, "_service_instance_retired", False))

    def _state_for_service(self, service: Any) -> _ExchangeState:
        normalized = str(getattr(service, "model_id", "default"))
        service_instance_id = self._service_instance_id(service)
        with self._states_lock:
            state = self._states.get(normalized)
            if state is None or state.service_instance_id != service_instance_id:
                state = _ExchangeState(normalized, service_instance_id)
                self._states[normalized] = state
            return state

    def _state_for_live_service(self, service: Any) -> _ExchangeState:
        service_lock = getattr(service, "lock", None)
        with (service_lock if service_lock is not None else nullcontext()):
            if not self._service_instance_active_locked(service):
                raise RuntimeError("学员台实时交换请求所属模型生命周期已失效或已退休。")
            # Service -> exchange-state-map matches the refresh publication order.
            return self._state_for_service(service)

    def _state_for_request_service(self, service: Any) -> _ExchangeState:
        if not self._service_is_current_registry_instance(service):
            raise TraineeExchangeLifecycleError(
                "学员台实时交换请求所属模型生命周期已失效或已退休。"
            )
        try:
            return self._state_for_live_service(service)
        except RuntimeError as exc:
            raise TraineeExchangeLifecycleError(str(exc)) from exc

    def _state_for(self, model_id: Optional[str]) -> _ExchangeState:
        return self._state_for_service(self._service_for(model_id))

    @staticmethod
    def _definition_revision(service: Any) -> int:
        try:
            return int(getattr(service.definition_snapshot, "revision", 0))
        except (AttributeError, TypeError, ValueError):
            return 0

    def _control_generation_locked(
        self,
        service: Any,
        state: _ExchangeState,
    ) -> TraineeControlGeneration:
        return TraineeControlGeneration(
            model_id=state.model_id,
            service_instance_id=state.service_instance_id,
            receive_epoch=state.receive_epoch,
            connection_signature=self._connection_signature(service),
            definition_revision=self._definition_revision(service),
        )

    @staticmethod
    def _enter_unique_lock(stack: ExitStack, lock: Any, entered: set[int]) -> None:
        if lock is None or id(lock) in entered:
            return
        stack.enter_context(lock)
        entered.add(id(lock))

    def _capture_refresh_request(
        self,
        service: Any,
        state: _ExchangeState,
        *,
        attempted_at: float,
    ) -> Tuple[Optional[Dict[str, str]], _RefreshRequestToken]:
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            receive = service.trainee_receive_state()
            if not isinstance(receive, Mapping):
                receive = {}
            connection = self._connection_from_receive(receive)
            signature = self._connection_signature_from_receive(service, receive)
            self._enter_unique_lock(stack, state.lock, entered)
            token = _RefreshRequestToken(
                model_id=state.model_id,
                service_instance_id=state.service_instance_id,
                connection_signature=signature,
                receive_epoch=state.receive_epoch,
            )
            if connection is not None:
                state.last_attempt_at = attempted_at
            return connection, token

    @contextmanager
    def _refresh_commit_scope(
        self,
        service: Any,
        state: _ExchangeState,
        token: Optional[_RefreshRequestToken],
    ) -> Iterator[bool]:
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            active_instance = self._service_instance_active_locked(service)
            self._enter_unique_lock(stack, self._states_lock, entered)
            map_matches = self._states.get(state.model_id) is state
            self._enter_unique_lock(stack, state.lock, entered)
            valid = bool(
                active_instance
                and map_matches
                and state.service_instance_id == self._service_instance_id(service)
            )
            if valid and token is not None:
                live_signature = self._connection_signature(service)
                valid = bool(
                    token.model_id == state.model_id
                    and token.service_instance_id == state.service_instance_id
                    and token.receive_epoch == state.receive_epoch
                    and token.connection_signature == live_signature
                    and bool(live_signature and live_signature[0])
                )
            # Service retirement, receive retarget and state publication all
            # linearize while these three locks are held in this order.
            yield valid

    def control_generation(self, model_id: Optional[str]) -> TraineeControlGeneration:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._control_generation_for_service(service, state)

    def _control_generation_for_service(
        self,
        service: Any,
        state: _ExchangeState,
    ) -> TraineeControlGeneration:
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "definition_update_lock", None), entered)
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            self._enter_unique_lock(stack, self._states_lock, entered)
            self._enter_unique_lock(stack, state.lock, entered)
            if (
                not self._service_instance_active_locked(service)
                or self._states.get(state.model_id) is not state
                or state.service_instance_id != self._service_instance_id(service)
            ):
                raise RuntimeError("学员台实时交换请求所属模型生命周期已失效或已退休。")
            return self._control_generation_locked(service, state)

    @contextmanager
    def _control_generation_scope_for_service(
        self,
        service: Any,
        state: _ExchangeState,
        expected: TraineeControlGeneration,
    ) -> Iterator[bool]:
        if self._service_instance_id(service) != expected.service_instance_id:
            yield False
            return
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "definition_update_lock", None), entered)
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            self._enter_unique_lock(stack, self._states_lock, entered)
            self._enter_unique_lock(stack, state.lock, entered)
            valid = bool(
                self._service_instance_active_locked(service)
                and self._states.get(state.model_id) is state
                and state.service_instance_id == expected.service_instance_id
                and self._control_generation_locked(service, state) == expected
            )
            yield valid

    @contextmanager
    def _control_generation_scope(
        self,
        model_id: Optional[str],
        expected: TraineeControlGeneration,
    ) -> Iterator[Tuple[Any, _ExchangeState, bool]]:
        try:
            service = self._service_for(model_id)
        except KeyError:
            yield None, None, False  # type: ignore[misc]
            return
        if self._service_instance_id(service) != expected.service_instance_id:
            yield service, None, False  # type: ignore[misc]
            return
        state = self._state_for_service(service)
        with self._control_generation_scope_for_service(service, state, expected) as valid:
            yield service, state, valid

    def _dispatch_ticket_locked(
        self,
        service: Any,
        state: _ExchangeState,
        expected: TraineeControlGeneration,
    ) -> TraineeControlDispatchTicket:
        try:
            command_url = self._command_url(service)
            dispatch_error = ""
        except RuntimeError as exc:
            command_url = ""
            dispatch_error = str(exc)

        def prepare(
            payload: Mapping[str, Any],
            on_transport_start: Optional[Callable[[], None]] = None,
        ) -> TraineeControlDispatchPermit:
            runtime_settings = self._runtime_settings_for_service(service)
            submitted_payload = copy.deepcopy(dict(payload))
            # Commit the transport permit while the original generation remains
            # guarded. The permit performs network I/O only after all locks release.
            with self._control_generation_scope_for_service(service, state, expected) as valid:
                if not valid:
                    raise RuntimeError("控制周期接收或模型代次已失效，未提交学员台指令。")
                dispatch_status = self._receive_status_for_service(service, state)
                if not dispatch_status["canDispatch"]:
                    raise RuntimeError(
                        str(dispatch_status.get("dispatchStatus") or "实时数据状态不允许闭环下发。")
                    )
                if dispatch_error:
                    raise RuntimeError(dispatch_error)
                if on_transport_start is not None:
                    on_transport_start()
            return TraineeControlDispatchPermit(
                generation=expected,
                submitter=lambda: self._submit_commands_to_url(
                    command_url,
                    submitted_payload,
                    state=state,
                    timeout_seconds=float(
                        runtime_settings["backend_request_timeout_seconds"]
                    ),
                ),
            )

        return TraineeControlDispatchTicket(
            generation=expected,
            preparer=prepare,
            guard_factory=lambda generation: self.control_generation_guard_for_service(
                service,
                state,
                generation,
            ),
        )

    @contextmanager
    def control_generation_guard_for_service(
        self,
        service: Any,
        state: _ExchangeState,
        expected: TraineeControlGeneration,
    ) -> Iterator[TraineeControlGenerationValidation]:
        with self._control_generation_scope_for_service(service, state, expected) as valid:
            ticket = self._dispatch_ticket_locked(service, state, expected) if valid else None
            yield TraineeControlGenerationValidation(valid, ticket)

    @contextmanager
    def control_generation_guard(
        self,
        model_id: Optional[str],
        expected: TraineeControlGeneration,
    ) -> Iterator[TraineeControlGenerationValidation]:
        with self._control_generation_scope(model_id, expected) as (service, state, valid):
            # Definition -> service -> exchange is the shared mutation order. The
            # caller may commit controller state while this generation is leased.
            ticket = self._dispatch_ticket_locked(service, state, expected) if valid else None
            yield TraineeControlGenerationValidation(valid, ticket)

    def publish_runtime_snapshot(
        self,
        model_id: Optional[str],
        snapshot: Mapping[str, Any],
        *,
        received_at: Optional[float] = None,
        connection_signature: Optional[Tuple[Any, ...]] = None,
    ) -> int:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        revision = self._publish_runtime_snapshot_for_service(
            service,
            state,
            snapshot,
            received_at=received_at,
            connection_signature=connection_signature,
        )
        if revision is None:
            raise RuntimeError("学员台模型生命周期已失效，实时快照未发布。")
        return revision

    def _publish_runtime_snapshot_for_service(
        self,
        service: Any,
        state: _ExchangeState,
        snapshot: Mapping[str, Any],
        *,
        received_at: Optional[float] = None,
        connection_signature: Optional[Tuple[Any, ...]] = None,
        refresh_token: Optional[_RefreshRequestToken] = None,
        attempted_at: Optional[float] = None,
        request_duration_seconds: Optional[float] = None,
        response_size_bytes: Optional[int] = None,
    ) -> Optional[int]:
        runtime_settings = self._runtime_settings_for_service(service)
        history_limit = max(1, int(runtime_settings["measurement_delta_history_limit"]))
        published_at = float(received_at if received_at is not None else time.time())
        runtime = copy.deepcopy(dict(snapshot))
        local = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=True,
            include_device_states=False,
            include_commands=False,
            static_fields=list(CONTROL_STATIC_FIELDS),
        )
        merged = _merge_runtime_snapshot_with_local_definitions(runtime, local)
        current_measurements = _measurement_delta_items(merged, received_at=published_at)
        frame_identity = _runtime_frame_identity(runtime)
        frame_observed_at = time.time()
        with self._refresh_commit_scope(service, state, refresh_token) as valid:
            if not valid:
                return None
            previous_measurements = state.measurement_delta_state
            changed_names = [
                name
                for name, item in current_measurements.items()
                if name not in previous_measurements
                or _measurement_delta_signature(previous_measurements[name])
                != _measurement_delta_signature(item)
            ]
            removed_names = [name for name in previous_measurements if name not in current_measurements]
            if changed_names or removed_names:
                state.measurement_delta_seq += 1
                changed_items = [current_measurements[name] for name in changed_names]
                changed_items.extend(
                    {
                        "name": name,
                        "deleted": True,
                        "updated_wall_time": datetime.fromtimestamp(published_at).strftime("%H:%M:%S"),
                        "updated_simu_time": str(
                            (runtime.get("clock") or {}).get("time", "--")
                            if isinstance(runtime.get("clock"), Mapping)
                            else "--"
                        ),
                    }
                    for name in removed_names
                )
                state.measurement_delta_history.append(
                    {
                        "seq": state.measurement_delta_seq,
                        "items": copy.deepcopy(changed_items),
                    }
                )
                state.measurement_delta_history = state.measurement_delta_history[
                    -history_limit:
                ]
                state.measurement_delta_state = copy.deepcopy(current_measurements)
            state.runtime_snapshot = runtime
            state.received_at = published_at
            state.last_success_at = published_at
            state.last_error = ""
            state.consecutive_failures = 0
            if frame_identity:
                if frame_identity != state.frame_identity or state.frame_changed_at <= 0.0:
                    state.frame_changed_at = frame_observed_at
                state.frame_identity = frame_identity
            else:
                state.frame_identity = ()
                state.frame_changed_at = frame_observed_at
            if connection_signature is not None:
                state.connection_signature = tuple(connection_signature)
            if attempted_at is not None:
                state.last_attempt_at = float(attempted_at)
            if request_duration_seconds is not None:
                state.last_request_duration_seconds = max(
                    0.0,
                    float(request_duration_seconds),
                )
            if response_size_bytes is not None:
                state.last_response_size_bytes = max(0, int(response_size_bytes))
            state.revision += 1
            return state.revision

    def _commit_refresh_failure_for_service(
        self,
        service: Any,
        state: _ExchangeState,
        token: _RefreshRequestToken,
        error: Exception,
        *,
        attempted_at: float,
        request_duration_seconds: float,
    ) -> bool:
        with self._refresh_commit_scope(service, state, token) as valid:
            if not valid:
                return False
            state.last_error = str(error)
            state.consecutive_failures += 1
            state.last_attempt_at = float(attempted_at)
            state.last_request_duration_seconds = max(
                0.0,
                float(request_duration_seconds),
            )
            return True

    def control_snapshot(self, model_id: Optional[str]) -> TraineeControlSnapshot:
        service = self._service_for(model_id)
        return self.control_snapshot_for_service(service)

    def control_snapshot_for_service(self, service: Any) -> TraineeControlSnapshot:
        """Read one control view bound to a previously resolved service lifecycle."""
        state = self._state_for_request_service(service)
        generation = self._control_generation_for_service(service, state)
        lease = TraineeControlLease(
            generation,
            lambda expected: self.control_generation_guard_for_service(
                service,
                state,
                expected,
            ),
        )
        receive_state = service.trainee_receive_state()
        active = bool(receive_state.get("active"))
        with state.lock:
            runtime = copy.deepcopy(state.runtime_snapshot)
            received_at = state.received_at
            error = state.last_error or None
            revision = state.revision
            signature = state.connection_signature
            receive_epoch = state.receive_epoch
        if runtime is None:
            return TraineeControlSnapshot(
                {},
                "trainee-empty",
                0.0,
                error,
                active,
                False,
                revision,
                signature,
                receive_epoch,
                lease,
            )
        local = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=True,
            include_device_states=False,
            include_commands=False,
            static_fields=list(CONTROL_STATIC_FIELDS),
        )
        merged = _merge_runtime_snapshot_with_local_definitions(runtime, local)
        age = max(0.0, time.time() - received_at) if received_at else 0.0
        source = "trainee-live" if not error else "trainee-cache"
        return TraineeControlSnapshot(
            merged,
            source,
            age,
            error,
            active,
            True,
            revision,
            signature,
            receive_epoch,
            lease,
        )

    def _receive_status_for_service(self, service: Any, state: _ExchangeState) -> Dict[str, Any]:
        receive_state = service.trainee_receive_state()
        runtime_settings = self._runtime_settings_for_service(service)
        frame_age_limit = max(0.0, float(runtime_settings["frame_age_limit_seconds"]))
        same_frame_limit = max(0.0, float(runtime_settings["same_frame_limit_seconds"]))
        active = bool(receive_state.get("active")) if isinstance(receive_state, Mapping) else False
        now = time.time()
        with state.lock:
            ready = state.runtime_snapshot is not None
            received_at = state.received_at
            error = state.last_error
            revision = state.revision
            signature = state.connection_signature
            receive_epoch = state.receive_epoch
            frame_identity = state.frame_identity
            frame_changed_at = state.frame_changed_at
            last_attempt_at = state.last_attempt_at
            last_success_at = state.last_success_at
            consecutive_failures = state.consecutive_failures
            request_duration = state.last_request_duration_seconds
            response_size = state.last_response_size_bytes
            command_attempt_count = state.command_attempt_count
            command_success_count = state.command_success_count
            command_failure_count = state.command_failure_count
            command_accepted_count = state.command_accepted_count
            command_rejected_count = state.command_rejected_count
            command_ambiguous_failure_count = state.command_ambiguous_failure_count
            last_command_attempt_at = state.last_command_attempt_at
            last_command_success_at = state.last_command_success_at
            last_command_duration = state.last_command_duration_seconds
            last_command_error = state.last_command_error
        age = max(0.0, now - received_at) if received_at else 0.0
        same_frame_duration = max(0.0, now - frame_changed_at) if frame_changed_at else 0.0
        frame_too_old = bool(
            ready
            and frame_age_limit > 0.0
            and age > frame_age_limit
        )
        frame_frozen = bool(
            ready
            and frame_identity
            and same_frame_limit > 0.0
            and same_frame_duration > same_frame_limit
        )
        can_calculate = active and ready
        can_dispatch = can_calculate and not error and not frame_too_old and not frame_frozen
        if not active:
            message = "请先启动接收。"
        elif not ready:
            message = "学员台正在等待第一份实时数据。"
        else:
            message = ""
        if not can_calculate:
            dispatch_status = message
        elif error:
            dispatch_status = f"实时数据接收异常，闭环下发已阻断：{error}"
        elif frame_too_old:
            dispatch_status = "实时数据帧已超时，闭环下发已阻断。"
        elif frame_frozen:
            dispatch_status = "实时数据帧已冻结，闭环下发已阻断。"
        else:
            dispatch_status = ""
        return {
            "receiveActive": active,
            "ready": ready,
            "canRun": can_calculate,
            "canCalculate": can_calculate,
            "canDispatch": can_dispatch,
            "prerequisiteStatus": message,
            "dispatchStatus": dispatch_status,
            "revision": revision,
            "receiveEpoch": receive_epoch,
            "connectionSignature": list(signature),
            "ageSeconds": age,
            "frameAgeSeconds": age,
            "sameFrameDurationSeconds": same_frame_duration,
            "frameTooOld": frame_too_old,
            "frameFrozen": frame_frozen,
            "frameIdentity": [list(item) for item in frame_identity],
            "error": error,
            "lastAttemptAt": _wall_time_text(last_attempt_at),
            "lastSuccessAt": _wall_time_text(last_success_at),
            "consecutiveFailures": consecutive_failures,
            "requestDurationSeconds": request_duration,
            "responseSizeBytes": response_size,
            "commandAttemptCount": command_attempt_count,
            "commandSuccessCount": command_success_count,
            "commandFailureCount": command_failure_count,
            "commandAcceptedCount": command_accepted_count,
            "commandRejectedCount": command_rejected_count,
            "commandAmbiguousFailureCount": command_ambiguous_failure_count,
            "lastCommandAttemptAt": _wall_time_text(last_command_attempt_at),
            "lastCommandSuccessAt": _wall_time_text(last_command_success_at),
            "lastCommandDurationSeconds": last_command_duration,
            "lastCommandError": last_command_error,
            "registryError": self._last_registry_error,
            "registryLastSuccessAt": _wall_time_text(self._last_registry_success_at),
            "runtimeSettings": runtime_settings,
        }

    def receive_status(self, model_id: Optional[str]) -> Dict[str, Any]:
        service = self._service_for(model_id)
        return self.receive_status_for_service(service)

    def receive_status_for_service(self, service: Any) -> Dict[str, Any]:
        """Read receive state without resolving the model registry again."""
        return self._receive_status_for_service(
            service,
            self._state_for_request_service(service),
        )

    def snapshot(
        self,
        model_id: Optional[str],
        *,
        options: Optional[Mapping[str, Any]] = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        return self.snapshot_for_service(
            self._service_for(model_id),
            options=options,
            refresh=refresh,
        )

    def snapshot_for_service(
        self,
        service: Any,
        *,
        options: Optional[Mapping[str, Any]] = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        state = self._state_for_request_service(service)
        requested = dict(options or {})
        has_filters = any(
            (
                str(requested.get("measurements", "1")) == "0",
                str(requested.get("devices", "1")) == "0",
                str(requested.get("device_states", "1")) == "0",
                str(requested.get("commands", "1")) == "0",
                str(requested.get("logs", requested.get("runtime_logs", "1"))) == "0",
                str(requested.get("static", "1")) == "0",
            )
        )
        if has_filters:
            receive_state = service.trainee_receive_state()
            active = bool(receive_state.get("active"))
            with state.lock:
                ready = state.runtime_snapshot is not None
                error = state.last_error
            if (refresh or not ready) and active:
                self.refresh_once_for_service(service)
                state = self._state_for_request_service(service)
                receive_state = service.trainee_receive_state()
                active = bool(receive_state.get("active"))
                with state.lock:
                    ready = state.runtime_snapshot is not None
                    error = state.last_error
            if not active:
                raise RuntimeError("当前模型未启动接收")
            if not ready:
                raise RuntimeError(error or "学员台正在等待第一份实时数据")
            with state.lock:
                # Published snapshots are replaced atomically and never mutated afterward.
                runtime = state.runtime_snapshot
            if runtime is None:
                raise RuntimeError(error or "学员台正在等待第一份实时数据")
            return self._project_filtered_snapshot(service, runtime, requested)

        view = self.control_snapshot_for_service(service)
        if (refresh or not view.ready) and view.receive_active:
            view = self.refresh_once_for_service(service)
            self._state_for_request_service(service)
        if not view.receive_active:
            raise RuntimeError("当前模型未启动接收")
        if not view.ready:
            raise RuntimeError(view.error or "学员台正在等待第一份实时数据")
        payload = copy.deepcopy(view.snapshot)
        if str(requested.get("measurements", "1")) == "0":
            payload.pop("measurements", None)
        if str(requested.get("devices", "1")) == "0":
            payload.pop("devices", None)
        if str(requested.get("device_states", "1")) == "0":
            payload.pop("device_states", None)
        if str(requested.get("commands", "1")) == "0":
            payload.pop("commands", None)
        if str(requested.get("logs", requested.get("runtime_logs", "1"))) == "0":
            payload.pop("runtime_logs", None)
        if str(requested.get("static", "1")) == "0":
            for key in CONTROL_STATIC_FIELDS:
                payload.pop(key, None)
        return payload

    @staticmethod
    def _project_filtered_snapshot(
        service: Any,
        runtime: Mapping[str, Any],
        requested: Mapping[str, Any],
    ) -> Dict[str, Any]:
        include_measurements = str(requested.get("measurements", "1")) != "0"
        include_devices = str(requested.get("devices", "1")) != "0"
        include_device_states = str(requested.get("device_states", "1")) != "0"
        include_commands = str(requested.get("commands", "1")) != "0"
        include_logs = (
            str(requested.get("logs", requested.get("runtime_logs", "1"))) != "0"
        )
        include_static = str(requested.get("static", "1")) != "0"
        excluded = set()
        if not include_measurements:
            excluded.add("measurements")
        if not include_devices:
            excluded.add("devices")
        if not include_device_states:
            excluded.add("device_states")
        if not include_commands:
            excluded.add("commands")
        if not include_logs:
            excluded.add("runtime_logs")
        if not include_static:
            excluded.update(CONTROL_STATIC_FIELDS)

        static_fields: list[str] = []
        if include_static:
            static_fields.extend(CONTROL_STATIC_FIELDS)
        elif include_measurements:
            static_fields.append("definitions")
        local = service.snapshot(
            include_static=bool(static_fields),
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=include_devices,
            include_device_states=False,
            include_commands=False,
            static_fields=static_fields,
        )

        deferred = {"model", "static_meta", "measurements", "devices", *CONTROL_STATIC_FIELDS}
        payload = {
            key: copy.deepcopy(value)
            for key, value in runtime.items()
            if key not in excluded and key not in deferred
        }
        if "model" in local:
            payload["model"] = copy.deepcopy(local["model"])
        if "static_meta" in local:
            payload["static_meta"] = copy.deepcopy(local["static_meta"])
        if include_static:
            for key in CONTROL_STATIC_FIELDS:
                if key in local:
                    payload[key] = copy.deepcopy(local[key])
        if include_devices and "devices" in local:
            payload["devices"] = _merge_remote_runtime_devices(
                local.get("devices"),
                runtime.get("devices"),
            )
        if include_measurements and "measurements" in runtime:
            payload["measurements"] = _merge_remote_measurements_with_local_definitions(
                runtime.get("measurements"),
                local,
            )
        return payload

    def measurement_delta(
        self,
        model_id: Optional[str],
        after_seq: int | float = 0,
    ) -> Dict[str, Any]:
        return self.measurement_delta_for_service(
            self._service_for(model_id),
            after_seq=after_seq,
        )

    def measurement_delta_for_service(
        self,
        service: Any,
        after_seq: int | float = 0,
    ) -> Dict[str, Any]:
        state = self._state_for_request_service(service)
        try:
            after = int(after_seq)
        except (TypeError, ValueError):
            after = 0
        with state.lock:
            seq = state.measurement_delta_seq
            history = state.measurement_delta_history
            oldest_seq = int(history[0].get("seq", seq)) if history else seq
            reset = False
            reset_reason = ""
            if after <= 0 or after > seq:
                item_refs = list(state.measurement_delta_state.values())
                reset = True
                reset_reason = "initial" if after <= 0 else "sequence_ahead"
            elif after == seq:
                item_refs = []
            elif history and after < oldest_seq - 1:
                item_refs = list(state.measurement_delta_state.values())
                reset = True
                reset_reason = "history_expired"
            else:
                newer = [entry for entry in history if int(entry.get("seq", 0)) > after]
                if not newer:
                    item_refs = list(state.measurement_delta_state.values())
                    reset = True
                    reset_reason = "history_unavailable"
                else:
                    by_name: Dict[str, Mapping[str, Any]] = {}
                    for entry in newer:
                        for item in entry.get("items", []):
                            if isinstance(item, Mapping):
                                by_name[str(item.get("name", ""))] = item
                    item_refs = list(by_name.values())
            runtime = state.runtime_snapshot or {}
            clock = runtime.get("clock") if isinstance(runtime.get("clock"), Mapping) else {}
            clock_time = str(clock.get("time") or "--")
            absolute_minute = copy.deepcopy(clock.get("absolute_minute"))
            received_at = state.received_at
            receive_epoch = state.receive_epoch
        items = copy.deepcopy(item_refs)
        wall_time = (
            datetime.fromtimestamp(received_at).strftime("%H:%M:%S")
            if received_at
            else "--"
        )
        return {
            "model_id": str(getattr(service, "model_id", "default")),
            "model_name": str(getattr(service, "model_name", "")),
            "time": clock_time,
            "simu_time": clock_time,
            "absolute_minute": absolute_minute,
            "wall_time": wall_time,
            "seq": seq,
            "oldestSeq": oldest_seq,
            "receiveEpoch": receive_epoch,
            "items": items,
            "reset": reset,
            "resetReason": reset_reason,
        }

    def submit_commands(
        self,
        model_id: Optional[str],
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        service = self._service_for(model_id)
        return self.submit_commands_for_service(service, payload)

    def submit_commands_for_service(
        self,
        service: Any,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Submit using the service lifecycle and endpoint captured by the caller."""
        try:
            state = self._state_for_live_service(service)
        except RuntimeError as exc:
            raise TraineeExchangeLifecycleError(str(exc)) from exc
        runtime_settings = self._runtime_settings_for_service(service)
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            if not self._service_instance_active_locked(service):
                raise TraineeExchangeLifecycleError(
                    "学员台指令请求所属模型生命周期已失效或已退休。"
                )
            receive = service.trainee_receive_state()
            if not isinstance(receive, Mapping):
                receive = {}
            command_url = self._command_url_from_receive(receive)
            signature = self._connection_signature_from_receive(service, receive)
            self._enter_unique_lock(stack, self._states_lock, entered)
            self._enter_unique_lock(stack, state.lock, entered)
            if (
                self._states.get(state.model_id) is not state
                or state.service_instance_id != self._service_instance_id(service)
            ):
                raise TraineeExchangeLifecycleError(
                    "学员台指令请求所属模型生命周期已失效或已退休。"
                )
            token = _RefreshRequestToken(
                model_id=state.model_id,
                service_instance_id=state.service_instance_id,
                connection_signature=signature,
                receive_epoch=state.receive_epoch,
            )
        with self._refresh_commit_scope(service, state, token) as valid:
            if not valid:
                raise TraineeExchangeLifecycleError(
                    "学员台指令请求所属接收或模型生命周期已失效，未执行下发。"
                )
        return self._submit_commands_to_url(
            command_url,
            payload,
            state=state,
            timeout_seconds=float(runtime_settings["backend_request_timeout_seconds"]),
        )

    @staticmethod
    def _command_url(service: Any) -> str:
        receive = service.trainee_receive_state()
        return TraineeRealtimeExchange._command_url_from_receive(receive)

    @staticmethod
    def _command_url_from_receive(receive: Mapping[str, Any]) -> str:
        if not bool(receive.get("active")):
            raise RuntimeError("当前模型未启动接收")
        base = str(receive.get("teacher_api_base") or "").strip().rstrip("/")
        command_path = str(receive.get("command_path") or "").strip()
        if not base or not command_path:
            raise RuntimeError("学员台指令通道尚未配置")
        return urljoin(base + "/", command_path.lstrip("/"))

    def _submit_commands_to_url(
        self,
        command_url: str,
        payload: Mapping[str, Any],
        *,
        state: Optional[_ExchangeState] = None,
        timeout_seconds: float = 8.0,
    ) -> Dict[str, Any]:
        forwarded = {
            key: copy.deepcopy(value)
            for key, value in payload.items()
            if key not in {"model_id", "model"}
        }
        attempted_at = time.time()
        command_started = time.monotonic()
        if state is not None:
            with state.lock:
                state.command_attempt_count += 1
                state.last_command_attempt_at = attempted_at
        try:
            result = self.request_json(
                command_url,
                method="POST",
                payload=forwarded,
                timeout=max(1.0, float(timeout_seconds)),
            )
            if not isinstance(result, Mapping):
                raise RuntimeError("学员台指令入口返回内容不是对象")
        except Exception as exc:
            if state is not None:
                error_text = str(exc)
                lowered = error_text.casefold()
                with state.lock:
                    state.command_failure_count += 1
                    if "timeout" in lowered or "timed out" in lowered or "超时" in error_text:
                        state.command_ambiguous_failure_count += 1
                    state.last_command_duration_seconds = max(0.0, time.monotonic() - command_started)
                    state.last_command_error = error_text
            raise
        if state is not None:
            try:
                accepted = int(float(result.get("accepted", result.get("set_values", 0)) or 0))
            except (TypeError, ValueError):
                accepted = 0
            try:
                rejected = int(float(result.get("rejected", 0) or 0))
            except (TypeError, ValueError):
                rejected = 0
            with state.lock:
                state.command_success_count += 1
                state.command_accepted_count += max(0, accepted)
                state.command_rejected_count += max(0, rejected)
                state.last_command_success_at = time.time()
                state.last_command_duration_seconds = max(0.0, time.monotonic() - command_started)
                state.last_command_error = ""
        return copy.deepcopy(dict(result))

    @staticmethod
    def _connection_from_receive(receive: Mapping[str, Any]) -> Optional[Dict[str, str]]:
        if not bool(receive.get("active")):
            return None
        base = str(receive.get("teacher_api_base") or "").rstrip("/")
        snapshot_path = str(receive.get("snapshot_path") or "")
        command_path = str(receive.get("command_path") or "")
        if not base or not snapshot_path:
            return None
        return {
            "base": base,
            "snapshot_path": snapshot_path,
            "command_path": command_path,
        }

    @staticmethod
    def _connection(service: Any) -> Optional[Dict[str, str]]:
        receive = service.trainee_receive_state()
        if not isinstance(receive, Mapping):
            receive = {}
        return TraineeRealtimeExchange._connection_from_receive(receive)

    @staticmethod
    def _connection_signature_from_receive(
        service: Any,
        receive: Mapping[str, Any],
    ) -> Tuple[Any, ...]:
        base = str(receive.get("teacher_api_base") or "").strip().rstrip("/")
        snapshot_path = str(receive.get("snapshot_path") or "").strip()
        command_path = str(receive.get("command_path") or "").strip()
        return (
            bool(receive.get("active")),
            bool(base and snapshot_path),
            str(getattr(service, "model_id", "")),
            str(receive.get("model_id") or ""),
            str(receive.get("interaction_link") or "").strip(),
            base,
            snapshot_path,
            command_path,
            str(receive.get("teacher_model_id") or "").strip(),
            str(receive.get("teacher_model_name") or "").strip(),
            str(receive.get("measurement_delta_path") or "").strip(),
            str(receive.get("definition_archive_path") or "").strip(),
        )

    @staticmethod
    def _connection_signature(service: Any) -> Tuple[Any, ...]:
        try:
            receive = service.trainee_receive_state()
        except Exception:
            receive = {}
        if not isinstance(receive, Mapping):
            receive = {}
        return TraineeRealtimeExchange._connection_signature_from_receive(service, receive)

    @staticmethod
    def _discard_connection_cache(
        state: _ExchangeState,
        signature: Tuple[Any, ...],
    ) -> None:
        with state.lock:
            had_cached_state = bool(
                state.runtime_snapshot is not None
                or state.measurement_delta_state
                or state.connection_signature
            )
            state.runtime_snapshot = None
            state.received_at = 0.0
            state.last_error = ""
            state.measurement_delta_seq = 0
            state.measurement_delta_state = {}
            state.measurement_delta_history = []
            state.frame_identity = ()
            state.frame_changed_at = 0.0
            state.last_attempt_at = 0.0
            state.last_success_at = 0.0
            state.consecutive_failures = 0
            state.last_request_duration_seconds = 0.0
            state.last_response_size_bytes = 0
            state.connection_signature = tuple(signature)
            if had_cached_state:
                state.revision += 1
                state.receive_epoch += 1

    @staticmethod
    def _cancelled_refresh_view(state: _ExchangeState) -> TraineeControlSnapshot:
        with state.lock:
            revision = state.revision
            signature = state.connection_signature
            receive_epoch = state.receive_epoch
        return TraineeControlSnapshot(
            {},
            "trainee-empty",
            0.0,
            None,
            False,
            False,
            revision,
            signature,
            receive_epoch,
            None,
        )

    def _refresh_result_for_service(
        self,
        service: Any,
        state: _ExchangeState,
    ) -> TraineeControlSnapshot:
        try:
            return self.control_snapshot_for_service(service)
        except RuntimeError:
            with ExitStack() as stack:
                entered: set[int] = set()
                self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
                active = self._service_instance_active_locked(service)
                self._enter_unique_lock(stack, self._states_lock, entered)
                map_matches = self._states.get(state.model_id) is state
            if active and map_matches:
                raise
            return self._cancelled_refresh_view(state)

    def refresh_once(self, model_id: Optional[str]) -> TraineeControlSnapshot:
        return self.refresh_once_for_service(self._service_for(model_id))

    def refresh_once_for_service(self, service: Any) -> TraineeControlSnapshot:
        state = self._state_for_live_service(service)
        runtime_settings = self._runtime_settings_for_service(service)
        with state.fetch_lock:
            attempted_at = time.time()
            connection, token = self._capture_refresh_request(
                service,
                state,
                attempted_at=attempted_at,
            )
            signature = token.connection_signature
            if connection is None:
                self._commit_refresh_failure_for_service(
                    service,
                    state,
                    token,
                    RuntimeError("学员台实时数据连接尚未配置或未启动"),
                    attempted_at=attempted_at,
                    request_duration_seconds=0.0,
                )
                return self._refresh_result_for_service(service, state)
            snapshot_path = _url_with_query(
                connection["snapshot_path"],
                lite=1,
                logs=1,
                log_limit=max(5, int(runtime_settings["runtime_log_page_size"])),
                commands=1,
                measurements=1,
                devices=1,
                device_states=1,
                static=0,
            )
            snapshot_url = urljoin(connection["base"] + "/", snapshot_path.lstrip("/"))
            request_started = time.monotonic()
            try:
                current = self.request_json(
                    snapshot_url,
                    timeout=max(1.0, float(runtime_settings["backend_request_timeout_seconds"])),
                )
                if not isinstance(current, Mapping):
                    raise RuntimeError("学员台实时快照不是 JSON 对象")
            except Exception as exc:
                request_duration = max(0.0, time.monotonic() - request_started)
                current_signature = self._connection_signature(service)
                if current_signature != signature:
                    self.notify_receive_state_changed_for_service(service)
                    return self._refresh_result_for_service(service, state)
                self._commit_refresh_failure_for_service(
                    service,
                    state,
                    token,
                    exc,
                    attempted_at=attempted_at,
                    request_duration_seconds=request_duration,
                )
                return self._refresh_result_for_service(service, state)
            current_signature = self._connection_signature(service)
            if current_signature != signature:
                self.notify_receive_state_changed_for_service(service)
                return self._refresh_result_for_service(service, state)
            request_duration = max(0.0, time.monotonic() - request_started)
            try:
                response_size = len(
                    json.dumps(current, ensure_ascii=False, default=str).encode("utf-8")
                )
            except (TypeError, ValueError):
                response_size = 0
            published_revision = self._publish_runtime_snapshot_for_service(
                service,
                state,
                current,
                received_at=time.time(),
                connection_signature=signature,
                refresh_token=token,
                attempted_at=attempted_at,
                request_duration_seconds=request_duration,
                response_size_bytes=response_size,
            )
            if published_revision is None:
                return self._refresh_result_for_service(service, state)
            return self._refresh_result_for_service(service, state)

    def notify_receive_state_changed_for_service(self, service: Any) -> None:
        """Synchronize a resolved service without acquiring the model registry lock."""
        try:
            state = self._state_for_live_service(service)
        except RuntimeError:
            return
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            if not self._service_instance_active_locked(service):
                return
            self._enter_unique_lock(stack, self._states_lock, entered)
            if self._states.get(state.model_id) is not state:
                return
            signature = self._connection_signature(service)
            self._enter_unique_lock(stack, state.lock, entered)
            if state.connection_signature and state.connection_signature != signature:
                self._discard_connection_cache(state, signature)
            else:
                state.connection_signature = signature
        self._wake_event.set()

    def runtime_settings_changed(self, model_id: Optional[str]) -> None:
        service = self._service_for(model_id)
        self.runtime_settings_changed_for_service(service)

    def runtime_settings_changed_for_service(self, service: Any) -> bool:
        try:
            state = self._state_for_live_service(service)
        except RuntimeError:
            return False
        runtime_settings = self._runtime_settings_for_service(service)
        history_limit = max(1, int(runtime_settings["measurement_delta_history_limit"]))
        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            if not self._service_instance_active_locked(service):
                return False
            self._enter_unique_lock(stack, self._states_lock, entered)
            if (
                self._states.get(state.model_id) is not state
                or state.service_instance_id != self._service_instance_id(service)
            ):
                return False
            self._enter_unique_lock(stack, state.lock, entered)
            state.next_refresh_at_monotonic = 0.0
            state.measurement_delta_history = state.measurement_delta_history[-history_limit:]
        self._wake_event.set()
        return True

    def notify_receive_state_changed(self, model_id: Optional[str]) -> None:
        self.notify_receive_state_changed_for_service(self._service_for(model_id))

    def receive_state_changed(self, model_id: Optional[str]) -> Dict[str, Any]:
        self.notify_receive_state_changed(model_id)
        return self.receive_status(model_id)

    def invalidate_model_for_service(self, service: Any) -> None:
        state = self._state_for_service(service)
        with state.lock:
            state.runtime_snapshot = None
            state.received_at = 0.0
            state.last_error = ""
            state.measurement_delta_seq = 0
            state.measurement_delta_state = {}
            state.measurement_delta_history = []
            state.frame_identity = ()
            state.frame_changed_at = 0.0
            state.last_attempt_at = 0.0
            state.last_success_at = 0.0
            state.consecutive_failures = 0
            state.last_request_duration_seconds = 0.0
            state.last_response_size_bytes = 0
            state.revision += 1
            state.receive_epoch += 1
        self._wake_event.set()

    def invalidate_model(self, model_id: Optional[str]) -> None:
        self.invalidate_model_for_service(self._service_for(model_id))

    def remove_model_for_service(self, service: Any) -> bool:
        """Invalidate and remove only the state owned by this service instance."""
        normalized = str(getattr(service, "model_id", "default"))
        service_instance_id = self._service_instance_id(service)
        with self._states_lock:
            state = self._states.get(normalized)
        if state is None or state.service_instance_id != service_instance_id:
            return False
        with state.lock:
            state.runtime_snapshot = None
            state.received_at = 0.0
            state.last_error = ""
            state.measurement_delta_seq = 0
            state.measurement_delta_state = {}
            state.measurement_delta_history = []
            state.frame_identity = ()
            state.frame_changed_at = 0.0
            state.revision += 1
            state.receive_epoch += 1
        with self._states_lock:
            if self._states.get(normalized) is state:
                self._states.pop(normalized, None)
        self._wake_event.set()
        return True

    def _start_worker(self) -> None:
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="trainee-realtime-exchange",
            daemon=True,
        )
        self._worker.start()

    def _submit_refresh(self, model_id: str) -> bool:
        try:
            service = self._service_for(model_id)
        except KeyError:
            return False
        return self._submit_refresh_for_service(service)

    def _submit_refresh_for_service(self, service: Any) -> bool:
        if not self._service_is_current_registry_instance(service):
            return False
        try:
            state = self._state_for_live_service(service)
        except RuntimeError:
            return False
        pending_key = (
            str(getattr(service, "model_id", "default")),
            self._service_instance_id(service),
        )

        def refresh_pending() -> None:
            try:
                self.refresh_once_for_service(service)
            except Exception:
                pass
            finally:
                with self._refresh_pending_lock:
                    self._refresh_pending.discard(pending_key)

        with ExitStack() as stack:
            entered: set[int] = set()
            self._enter_unique_lock(stack, getattr(service, "lock", None), entered)
            if not self._service_instance_active_locked(service):
                return False
            self._enter_unique_lock(stack, self._states_lock, entered)
            if (
                self._states.get(state.model_id) is not state
                or state.service_instance_id != self._service_instance_id(service)
            ):
                return False
            with self._refresh_pending_lock:
                if self._closed or self._stop_event.is_set():
                    return False
                if pending_key in self._refresh_pending:
                    return False
                self._refresh_pending.add(pending_key)
                try:
                    self._refresh_executor.submit(refresh_pending)
                except Exception:
                    self._refresh_pending.discard(pending_key)
                    raise
        return True

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            enumeration_succeeded = True
            try:
                services = (
                    list(self.services.iter_services())
                    if hasattr(self.services, "iter_services")
                    else [self.services]
                )
                self._last_registry_error = ""
                self._last_registry_success_at = time.time()
            except Exception as exc:
                services = []
                enumeration_succeeded = False
                self._last_registry_error = str(exc)
            now_monotonic = time.monotonic()
            next_delays = []
            for service in services:
                if not self._service_is_current_registry_instance(service):
                    continue
                try:
                    state = self._state_for_live_service(service)
                    with self._refresh_commit_scope(service, state, None) as valid:
                        if not valid:
                            continue
                        active = bool(service.trainee_receive_state().get("active"))
                        interval = max(
                            0.1,
                            float(
                                self._runtime_settings_for_service(service)[
                                    "backend_refresh_seconds"
                                ]
                            ),
                        )
                        if not active:
                            state.next_refresh_at_monotonic = 0.0
                            continue
                        due = state.next_refresh_at_monotonic <= now_monotonic
                        if due:
                            state.next_refresh_at_monotonic = now_monotonic + interval
                        next_delays.append(max(0.0, state.next_refresh_at_monotonic - now_monotonic))
                    if due:
                        self._submit_refresh_for_service(service)
                except Exception:
                    continue
            if enumeration_succeeded:
                with self._states_lock:
                    states = list(self._states.values())
                for state in states:
                    try:
                        current = self._service_for(state.model_id)
                    except KeyError:
                        current = None
                    if (
                        current is not None
                        and self._service_instance_id(current) == state.service_instance_id
                    ):
                        continue
                    with self._states_lock:
                        if self._states.get(state.model_id) is state:
                            self._states.pop(state.model_id, None)
            wait_seconds = min(next_delays) if next_delays else 1.0
            self._wake_event.wait(max(0.01, min(wait_seconds, 1.0)))
            self._wake_event.clear()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            with self._refresh_pending_lock:
                self._closed = True
            self._stop_event.set()
            self._wake_event.set()
            if self._worker and self._worker.is_alive():
                self._worker.join()
            # No exchange task may outlive close. Normal HTTP refreshes have a
            # finite request timeout, and no service/exchange lock is held here.
            self._refresh_executor.shutdown(wait=True, cancel_futures=True)
            with self._refresh_pending_lock:
                self._refresh_pending.clear()
