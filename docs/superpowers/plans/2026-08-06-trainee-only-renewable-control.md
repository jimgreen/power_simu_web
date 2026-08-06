# Trainee-Only Renewable Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this side conversation, subagents are prohibited, so execution must use `superpowers:executing-plans` inline.

**Goal:** Make the renewable-control module consume only learner-station snapshots and submit only to the learner-station command sink, while moving all external realtime communication into a shared learner-station exchange service.

**Architecture:** Add a model-scoped `TraineeRealtimeExchange` that owns background receiving, runtime caching, local-definition overlay, measurement deltas, and command forwarding. Inject its `control_snapshot`, `receive_status`, and `submit_commands` methods into `TraineeRenewableControlManager`, then remove all simulator URL parsing, HTTP requests, remote caching, and direct command dispatch from `simu/renewable_control.py`.

**Tech Stack:** Python 3 standard library (`dataclasses`, `threading`, `concurrent.futures`, `urllib`), existing `PolarMicrogridSimulator`/`MultiModelSimulator`, `ThreadingHTTPServer`, unittest/pytest, browser JavaScript regression assertions.

---

## File Map

- Create `simu/trainee_exchange.py`: learner-station realtime receiver, cache, local-definition overlay, measurement-delta state, status provider, and command sink.
- Modify `simu/server.py`: create and own the exchange service, route learner snapshot/delta/command APIs through it, and coordinate receive/model lifecycle.
- Modify `simu/renewable_control.py`: inject learner providers, remove all external connection and HTTP behavior, and update control status/log wording.
- Modify `tests/test_trainee_definition_renewable_sync.py`: verify local parameters through the exchange rather than through renewable-control remote fetches.
- Create `tests/test_trainee_realtime_exchange.py`: unit tests for cache publication, background receiving, local overlays, deltas, command forwarding, failures, and model isolation.
- Modify `tests/test_trainee_multi_simulator_receive.py`: verify learner API routes and no-browser background receive behavior.
- Modify `tests/test_trainee_renewable_backend_control.py`: inject fake learner providers/sinks and preserve control behavior tests.
- Modify `tests/test_trainee_renewable_receive_independence.py`: assert source-level removal of simulator dependencies from the renewable module.
- Modify `tests/test_trainee_receive_validation.py`: retain frontend route behavior while confirming the frontend reads learner APIs only.

Do not modify the renewable strategy mathematics, topology classification, SOC derating, deadbands, step sizes, or one-command-per-simulation-instant behavior.

Do not commit, push, restart WEB, delete `tmp_runtime_probe/`, or revert unrelated dirty-worktree changes during this plan unless the user explicitly asks.

---

### Task 1: Define the learner snapshot contract and local-definition overlay

**Files:**
- Create: `simu/trainee_exchange.py`
- Create: `tests/test_trainee_realtime_exchange.py`
- Modify: `simu/renewable_control.py` only after Task 6; do not move code yet in this task.

- [ ] **Step 1: Write failing tests for immutable learner snapshot views**

Add tests that use a real temporary `PolarMicrogridSimulator` and publish a deliberately conflicting runtime snapshot:

```python
from __future__ import annotations

import copy
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from simu.trainee_exchange import TraineeControlSnapshot, TraineeRealtimeExchange


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"


class TraineeRealtimeExchangeTest(unittest.TestCase):
    def make_service(self):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            model_id="trainee-local",
            kernel=lambda _config: None,
        )
        self.addCleanup(workspace.cleanup)
        return service

    def test_control_snapshot_uses_runtime_values_but_local_static_parameters(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=True,
        )
        runtime["device_parameters"]["ACWindGen"][0]["rated_power"] = 999.0
        runtime["devices"][0]["run_stat"] = 0
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)

        exchange.publish_runtime_snapshot("trainee-local", runtime, received_at=time.time())
        view = exchange.control_snapshot("trainee-local")

        self.assertIsInstance(view, TraineeControlSnapshot)
        self.assertTrue(view.ready)
        self.assertEqual(
            float(view.snapshot["device_parameters"]["ACWindGen"][0]["rated_power"]),
            10.0,
        )
        self.assertEqual(view.snapshot["devices"][0]["run_stat"], 0)

    def test_control_snapshot_applies_latest_local_manual_edit_without_republishing_runtime(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime, received_at=time.time())

        service.update_device_parameters({
            "block_name": "ACWindGen",
            "row_key": {"idx": "1"},
            "revision": service.definition_snapshot.revision,
            "changes": {"rated_power": 22},
        })
        view = exchange.control_snapshot("trainee-local")

        self.assertEqual(
            float(view.snapshot["device_parameters"]["ACWindGen"][0]["rated_power"]),
            22.0,
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -q
```

Expected: collection fails because `simu.trainee_exchange` does not exist.

- [ ] **Step 3: Implement the snapshot contract and cache publication**

Create `simu/trainee_exchange.py` with these exact public types and initial methods:

```python
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple


CONTROL_STATIC_FIELDS = ("definitions", "settings", "device_parameters")


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


@dataclass
class _ExchangeState:
    model_id: str
    runtime_snapshot: Optional[Dict[str, Any]] = None
    received_at: float = 0.0
    last_error: str = ""
    revision: int = 0
    connection_signature: Tuple[Any, ...] = ()
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    fetch_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class TraineeRealtimeExchange:
    def __init__(
        self,
        services: Any,
        *,
        request_json: Optional[Callable[..., Any]] = None,
        poll_interval_seconds: float = 1.0,
        start_worker: bool = True,
    ) -> None:
        self.services = services
        self.request_json = request_json
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._states: Dict[str, _ExchangeState] = {}
        self._states_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._worker = None
        if start_worker:
            self._start_worker()

    def _service_for(self, model_id: Optional[str]) -> Any:
        if hasattr(self.services, "service_for"):
            return self.services.service_for(model_id)
        return self.services

    def _state_for(self, model_id: Optional[str]) -> _ExchangeState:
        service = self._service_for(model_id)
        normalized = str(getattr(service, "model_id", model_id or "default"))
        with self._states_lock:
            return self._states.setdefault(normalized, _ExchangeState(normalized))

    def publish_runtime_snapshot(
        self,
        model_id: Optional[str],
        snapshot: Mapping[str, Any],
        *,
        received_at: Optional[float] = None,
        connection_signature: Optional[Tuple[Any, ...]] = None,
    ) -> int:
        state = self._state_for(model_id)
        with state.lock:
            state.runtime_snapshot = copy.deepcopy(dict(snapshot))
            state.received_at = float(received_at if received_at is not None else time.time())
            state.last_error = ""
            if connection_signature is not None:
                state.connection_signature = tuple(connection_signature)
            state.revision += 1
            return state.revision
```

Move the three pure merge helpers from `simu/renewable_control.py` into this new module without changing their behavior:

```python
_measurement_definition_identity(...)
_merge_remote_measurements_with_local_definitions(...)
_merge_remote_runtime_devices(...)
_merge_runtime_snapshot_with_local_definitions(...)
```

Implement `control_snapshot()` so it reads local static state every time:

```python
def control_snapshot(self, model_id: Optional[str]) -> TraineeControlSnapshot:
    service = self._service_for(model_id)
    state = self._state_for(model_id)
    receive_state = service.trainee_receive_state()
    active = bool(receive_state.get("active"))
    with state.lock:
        runtime = copy.deepcopy(state.runtime_snapshot)
        received_at = state.received_at
        error = state.last_error or None
        revision = state.revision
        signature = state.connection_signature
    if runtime is None:
        return TraineeControlSnapshot({}, "trainee-empty", 0.0, error, active, False, revision, signature)
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
    return TraineeControlSnapshot(merged, source, age, error, active, True, revision, signature)
```

Add an exact learner-facing status contract used by both the server and renewable manager:

```python
def receive_status(self, model_id: Optional[str]) -> Dict[str, Any]:
    view = self.control_snapshot(model_id)
    if not view.receive_active:
        message = "请先启动接收。"
    elif not view.ready:
        message = "学员台正在等待第一份实时数据。"
    else:
        message = ""
    return {
        "receiveActive": view.receive_active,
        "ready": view.ready,
        "canRun": view.receive_active and view.ready,
        "prerequisiteStatus": message,
        "revision": view.revision,
        "connectionSignature": list(view.connection_signature),
        "ageSeconds": view.age_seconds,
        "error": view.error or "",
    }
```

Implement a no-op-safe `close()` and worker placeholder so unit construction is valid:

```python
def _start_worker(self) -> None:
    return

def close(self) -> None:
    self._stop_event.set()
    self._wake_event.set()
```

- [ ] **Step 4: Run Task 1 tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -q
```

Expected: both snapshot tests pass.

- [ ] **Step 5: Run existing local-definition tests**

Run:

```powershell
python -m pytest tests/test_live_definition_editing_api.py tests/test_manual_definition_changes.py -q
```

Expected: all pass; learner cache work must not change definition editing or persistence.

---

### Task 2: Add background receive lifecycle and connection-race protection

**Files:**
- Modify: `simu/trainee_exchange.py`
- Modify: `tests/test_trainee_realtime_exchange.py`

- [ ] **Step 1: Write failing tests for dynamic-only fetch and no-browser receive**

Add tests using a fake request function and an active learner receive state:

```python
def configure_receive(service):
    service.set_trainee_receive_state({
        "initialized": True,
        "active": True,
        "teacher_api_base": "http://teacher.invalid",
        "snapshot_path": "/api/snapshot?model_id=teacher",
        "command_path": "/api/student/commands?model_id=teacher",
        "teacher_model_id": "teacher",
    })


def test_refresh_once_requests_dynamic_runtime_only(self):
    service = self.make_service()
    configure_receive(service)
    runtime = service.snapshot(include_static=True, include_runtime_logs=False)
    urls = []

    def request_json(url, **_kwargs):
        urls.append(url)
        return copy.deepcopy(runtime)

    exchange = TraineeRealtimeExchange(service, request_json=request_json, start_worker=False)
    self.addCleanup(exchange.close)
    view = exchange.refresh_once("trainee-local")

    self.assertTrue(view.ready)
    self.assertEqual(len(urls), 1)
    self.assertIn("static=0", urls[0])


def test_worker_receives_without_any_browser_request(self):
    service = self.make_service()
    configure_receive(service)
    runtime = service.snapshot(include_static=True, include_runtime_logs=False)
    calls = []

    def request_json(url, **_kwargs):
        calls.append(url)
        return copy.deepcopy(runtime)

    exchange = TraineeRealtimeExchange(
        service,
        request_json=request_json,
        poll_interval_seconds=0.05,
        start_worker=True,
    )
    self.addCleanup(exchange.close)

    deadline = time.time() + 2.0
    while time.time() < deadline and not exchange.control_snapshot("trainee-local").ready:
        time.sleep(0.02)

    self.assertTrue(exchange.control_snapshot("trainee-local").ready)
    self.assertGreaterEqual(len(calls), 1)
```

Add a race test in which `request_json` changes `teacher_model_id` before returning:

```python
def test_connection_change_during_fetch_discards_candidate(self):
    service = self.make_service()
    configure_receive(service)
    runtime = service.snapshot(include_static=True, include_runtime_logs=False)

    def request_json(_url, **_kwargs):
        service.set_trainee_receive_state({"teacher_model_id": "replacement"})
        return copy.deepcopy(runtime)

    exchange = TraineeRealtimeExchange(service, request_json=request_json, start_worker=False)
    self.addCleanup(exchange.close)
    view = exchange.refresh_once("trainee-local")

    self.assertFalse(view.ready)
    self.assertEqual(view.revision, 0)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -q
```

Expected: failures because `refresh_once()` and the worker are not implemented.

- [ ] **Step 3: Implement URL/query helpers and request transport in the exchange module**

Move or recreate the generic JSON request and URL query helpers in `simu/trainee_exchange.py`; they must not remain in renewable control after Task 6:

```python
def _url_with_query(path: str, **overrides: Any) -> str:
    parsed = urlparse(path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in overrides.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = [str(value)]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), parsed.fragment))
```

The exchange's connection helper is allowed to read learner-station receive configuration:

```python
def _connection(self, service: Any) -> Optional[Dict[str, str]]:
    receive = service.trainee_receive_state()
    if not bool(receive.get("active")):
        return None
    base = str(receive.get("teacher_api_base") or "").rstrip("/")
    snapshot_path = str(receive.get("snapshot_path") or "")
    command_path = str(receive.get("command_path") or "")
    if not base or not snapshot_path:
        return None
    return {"base": base, "snapshot_path": snapshot_path, "command_path": command_path}
```

Implement `_connection_signature()` using all fields that identify the active learner connection. This method belongs only to `trainee_exchange.py`.

- [ ] **Step 4: Implement `refresh_once()` with candidate publication**

Use the per-model `fetch_lock`; build one dynamic request with:

```python
snapshot_path = _url_with_query(
    connection["snapshot_path"],
    lite=1,
    logs=1,
    log_limit=20,
    commands=1,
    measurements=1,
    devices=1,
    device_states=1,
    static=0,
)
```

Capture the connection signature before the request and compare it after the response. If it changes, do not publish. On network failure, retain the last complete runtime snapshot and only set `last_error`.

Return `control_snapshot()` after each attempt so callers get one consistent contract.

- [ ] **Step 5: Implement the worker loop**

Use one daemon thread that enumerates `services.iter_services()` when available, refreshes each model whose learner receive state is active, and waits on `_wake_event` for the configured poll interval. A slow or failed model must not stop the loop for other models.

Use this control structure:

```python
def _start_worker(self) -> None:
    self._worker = threading.Thread(
        target=self._worker_loop,
        name="trainee-realtime-exchange",
        daemon=True,
    )
    self._worker.start()

def _worker_loop(self) -> None:
    while not self._stop_event.is_set():
        try:
            services = list(self.services.iter_services()) if hasattr(self.services, "iter_services") else [self.services]
        except Exception:
            services = []
        live_ids = set()
        for service in services:
            model_id = str(getattr(service, "model_id", "default"))
            live_ids.add(model_id)
            try:
                if bool(service.trainee_receive_state().get("active")):
                    self.refresh_once(model_id)
            except Exception:
                continue
        with self._states_lock:
            for stale_id in set(self._states) - live_ids:
                self._states.pop(stale_id, None)
        self._wake_event.wait(self.poll_interval_seconds)
        self._wake_event.clear()
```

Implement:

```python
def receive_state_changed(self, model_id: Optional[str]) -> Dict[str, Any]:
    service = self._service_for(model_id)
    state = self._state_for(model_id)
    signature = self._connection_signature(service)
    with state.lock:
        if state.connection_signature and state.connection_signature != signature:
            state.runtime_snapshot = None
            state.received_at = 0.0
            state.last_error = ""
            state.revision += 1
        state.connection_signature = signature
    self._wake_event.set()
    return self.receive_status(model_id)
```

Add model invalidation for initialization, deletion, and connection replacement:

```python
def invalidate_model(self, model_id: Optional[str]) -> None:
    state = self._state_for(model_id)
    with state.lock:
        state.runtime_snapshot = None
        state.received_at = 0.0
        state.last_error = ""
        state.measurement_delta_seq = 0
        state.measurement_delta_state = {}
        state.measurement_delta_history = []
        state.revision += 1
    self._wake_event.set()
```

If Task 2 is implemented before Task 3 adds the delta fields, initially clear only the runtime fields; extend the same method in Task 3 when the delta fields are introduced.

`close()` must join the worker with a bounded timeout.

- [ ] **Step 6: Run exchange tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -q
```

Expected: all Task 1 and Task 2 tests pass.

---

### Task 3: Generate learner-station measurement deltas from the shared cache

**Files:**
- Modify: `simu/trainee_exchange.py`
- Modify: `tests/test_trainee_realtime_exchange.py`

- [ ] **Step 1: Write failing cache-delta tests**

Add tests that publish two snapshots with one changed `scada_value`, then assert:

```python
initial = exchange.measurement_delta("trainee-local", after_seq=0)
self.assertTrue(initial["reset"])
self.assertGreater(initial["seq"], 0)

unchanged = exchange.measurement_delta("trainee-local", after_seq=initial["seq"])
self.assertEqual(unchanged["items"], [])

exchange.publish_runtime_snapshot("trainee-local", changed_runtime)
delta = exchange.measurement_delta("trainee-local", after_seq=initial["seq"])
self.assertFalse(delta["reset"])
self.assertEqual([item["name"] for item in delta["items"]], ["wind.p"])
```

Add an assertion that the delta's `value/real_value/scada_value` come from runtime, while `valid/weight` come from the learner definition.

- [ ] **Step 2: Run the delta tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -k measurement_delta -q
```

Expected: failure because `measurement_delta()` is missing.

- [ ] **Step 3: Extend `_ExchangeState` with delta state**

Add:

```python
measurement_delta_seq: int = 0
measurement_delta_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)
measurement_delta_history: list[Dict[str, Any]] = field(default_factory=list)
```

On every successful snapshot publication, derive current measurement items from the merged learner snapshot and append one history entry only when values change. Keep at most 200 history entries, matching the existing simulator delta behavior.

- [ ] **Step 4: Implement `measurement_delta()`**

Return the existing API shape:

```python
{
    "model_id": model_id,
    "seq": seq,
    "items": items,
    "reset": reset,
}
```

Use measurement name as the primary identity. Preserve deleted-item entries when a measurement disappears. Do not call the external measurement-delta API from this method.

Also implement the page-facing snapshot accessor so the server has one stable learner API:

```python
def snapshot(
    self,
    model_id: Optional[str],
    *,
    options: Optional[Mapping[str, Any]] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    view = self.control_snapshot(model_id)
    if (refresh or not view.ready) and view.receive_active:
        view = self.refresh_once(model_id)
    if not view.receive_active:
        raise RuntimeError("当前模型未启动接收")
    if not view.ready:
        raise RuntimeError(view.error or "学员台正在等待第一份实时数据")
    payload = copy.deepcopy(view.snapshot)
    requested = dict(options or {})
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
```

This method may trigger one immediate exchange-owned refresh only when the cache has no first frame or the caller explicitly asks for refresh. It must never create a second cache outside the exchange.

- [ ] **Step 5: Run delta and incremental UI tests**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py tests/test_incremental_runtime_data_ui.py -q
```

Expected: all pass.

---

### Task 4: Add the learner-station command sink

**Files:**
- Modify: `simu/trainee_exchange.py`
- Modify: `tests/test_trainee_realtime_exchange.py`

- [ ] **Step 1: Write failing command-sink tests**

Add tests for successful forwarding and inactive receive rejection:

```python
def test_submit_commands_uses_learner_connection_and_preserves_payload(self):
    service = self.make_service()
    configure_receive(service)
    calls = []

    def request_json(url, **kwargs):
        calls.append((url, kwargs))
        return {"set_values": 1}

    exchange = TraineeRealtimeExchange(service, request_json=request_json, start_worker=False)
    self.addCleanup(exchange.close)
    payload = {
        "source": "trainee-renewable-priority-backend",
        "set_values": [{"dev_type": "ACGenerator", "dev_name": "wind-1", "set_type": "p_set", "set_value": 8.0}],
    }

    result = exchange.submit_commands("trainee-local", payload)

    self.assertEqual(result["set_values"], 1)
    self.assertEqual(len(calls), 1)
    self.assertIn("/api/student/commands", calls[0][0])
    self.assertEqual(calls[0][1]["method"], "POST")
    self.assertEqual(calls[0][1]["payload"], payload)
```

When receive is inactive, assert `RuntimeError("当前模型未启动接收")` and zero transport calls.

- [ ] **Step 2: Run command tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -k submit_commands -q
```

Expected: failure because `submit_commands()` is missing.

- [ ] **Step 3: Implement `submit_commands()`**

The method resolves the active learner connection inside the exchange, removes only local routing keys (`model_id`, `model`) from a copied payload, sends one POST, and returns the response mapping. It must never mutate the caller's payload.

Use learner-oriented errors:

```text
当前模型未启动接收
学员台指令通道尚未配置
学员台指令入口返回内容不是对象
```

- [ ] **Step 4: Run all exchange tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py -q
```

Expected: all pass.

---

### Task 5: Route learner HTTP APIs through the exchange service

**Files:**
- Modify: `simu/server.py:1020-1037`
- Modify: `simu/server.py:1352-1365`
- Modify: `simu/server.py:1444-1475`
- Modify: `simu/server.py:1560-1575`
- Modify: `simu/server.py:1601-1611`
- Modify: `simu/server.py:1768-1779`
- Modify: `simu/server.py:1904-1916`
- Modify: `tests/test_trainee_multi_simulator_receive.py`
- Modify: `tests/test_trainee_model_initialization.py`

- [ ] **Step 1: Write failing learner-route integration tests**

Extend `make_http_server()` tests to assert:

1. Starting learner receive eventually produces a cached snapshot without any browser snapshot request.
2. `GET /api/trainee/snapshot` returns the exchange cache and local definitions.
3. `GET /api/trainee/measurements/delta` comes from exchange sequence state.
4. `POST /api/trainee/commands` delegates to `exchange.submit_commands()`.
5. `server.server_close()` closes both exchange and renewable manager exactly once.

Use a fake exchange injection for route delegation:

```python
class FakeExchange:
    def __init__(self):
        self.snapshot_calls = []
        self.command_calls = []
        self.closed = 0

    def snapshot(self, model_id, options=None, refresh=False):
        self.snapshot_calls.append((model_id, options, refresh))
        return {"model": {"id": model_id}, "clock": {"time": "cached"}}

    def control_snapshot(self, model_id):
        return TraineeControlSnapshot(
            snapshot={"model": {"id": model_id}, "clock": {"time": "cached"}},
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
            revision=1,
            connection_signature=("fake", model_id),
        )

    def receive_status(self, model_id):
        return {
            "receiveActive": True,
            "ready": True,
            "canRun": True,
            "prerequisiteStatus": "",
            "revision": 1,
            "connectionSignature": ["fake", model_id],
        }

    def measurement_delta(self, model_id, after_seq=0):
        return {"model_id": model_id, "seq": 1, "items": [], "reset": after_seq <= 0}

    def submit_commands(self, model_id, payload):
        self.command_calls.append((model_id, copy.deepcopy(payload)))
        return {"set_values": len(payload.get("set_values", []))}

    def receive_state_changed(self, model_id):
        return {"modelId": model_id}

    def invalidate_model(self, model_id):
        return None

    def close(self):
        self.closed += 1
```

- [ ] **Step 2: Run route tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_multi_simulator_receive.py tests/test_trainee_model_initialization.py -q
```

Expected: failures because `make_http_server()` cannot inject or delegate to an exchange.

- [ ] **Step 3: Add exchange construction and injection to `make_http_server()`**

Change the signature to include:

```python
trainee_exchange: Optional[TraineeRealtimeExchange] = None,
```

For `role == "trainee"`, create one exchange when none is supplied:

```python
exchange = trainee_exchange
if role == "trainee" and exchange is None:
    exchange = TraineeRealtimeExchange(service)
```

Do not create an exchange for simulator role.

- [ ] **Step 4: Delegate learner API routes**

Replace direct `_trainee_remote_url()` calls in these three routes:

```python
GET /api/trainee/snapshot
GET /api/trainee/measurements/delta
POST /api/trainee/commands
```

with exchange calls. Keep public paths and response JSON compatible with the current frontend.

`GET /api/trainee/snapshot` must pass parsed query options to `exchange.snapshot()` but must not build an external URL in the handler.

- [ ] **Step 5: Coordinate lifecycle**

After `POST /api/trainee/receive`, call:

```python
exchange.receive_state_changed(target.model_id)
renewable_manager.receive_state_changed(target.model_id)
```

After successful model initialization, call `exchange.invalidate_model(target.model_id)` before returning.

Extend `ManagedThreadingHTTPServer.server_close()` to close the exchange once, then close the renewable manager once. Expose it for tests:

```python
server.trainee_exchange = exchange
```

- [ ] **Step 6: Run learner server tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_trainee_multi_simulator_receive.py tests/test_trainee_model_initialization.py -q
```

Expected: all pass.

---

### Task 6: Decouple `TraineeRenewableControlManager` from simulator communication

**Files:**
- Modify: `simu/renewable_control.py:6747-7480`
- Modify: `simu/server.py:1020-1037`
- Modify: `tests/test_trainee_renewable_receive_independence.py`
- Modify: `tests/test_trainee_renewable_backend_control.py`
- Modify: `tests/test_trainee_definition_renewable_sync.py`
- Modify: `tests/test_trainee_multi_simulator_receive.py`

- [ ] **Step 1: Write a source-isolation failing test**

Update `tests/test_trainee_renewable_receive_independence.py` with a strict class-body check:

```python
def test_renewable_control_manager_has_no_simulator_transport_dependency():
    source = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
    manager_source = "class TraineeRenewableControlManager" + source.split(
        "class TraineeRenewableControlManager",
        1,
    )[1]

    for forbidden in (
        "teacher_api_base",
        "snapshot_path",
        "command_path",
        "urljoin(",
        "urlopen(",
        "request_json",
        "_fetch_remote_snapshot",
        "_connection(",
    ):
        assert forbidden not in manager_source
```

Add a constructor contract test:

```python
manager = TraineeRenewableControlManager(
    services,
    snapshot_provider=fake_snapshot_provider,
    receive_status_provider=fake_receive_status,
    command_sink=fake_command_sink,
    start_worker=False,
)
```

Before changing the constructor, add a server wiring assertion that the default learner server binds all three manager providers to its exchange instance:

```python
server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
try:
    exchange = server.trainee_exchange
    manager = server.renewable_control_manager
    self.assertEqual(manager.snapshot_provider, exchange.control_snapshot)
    self.assertEqual(manager.receive_status_provider, exchange.receive_status)
    self.assertEqual(manager.command_sink, exchange.submit_commands)
finally:
    server.server_close()
```

- [ ] **Step 2: Run isolation tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_renewable_receive_independence.py -q
```

Expected: failures showing the current manager still contains simulator fields, URL calls, and `request_json`.

- [ ] **Step 3: Change the manager constructor to learner providers**

Use this interface:

```python
def __init__(
    self,
    services: Any,
    *,
    snapshot_provider: Callable[[Optional[str]], TraineeControlSnapshot],
    receive_status_provider: Callable[[Optional[str]], Mapping[str, Any]],
    command_sink: Callable[[Optional[str], Mapping[str, Any]], Mapping[str, Any]],
    start_worker: bool = True,
) -> None:
    self.services = services
    self.snapshot_provider = snapshot_provider
    self.receive_status_provider = receive_status_provider
    self.command_sink = command_sink
```

No default network transport is allowed. `simu/server.py` must supply the exchange methods when it constructs the manager.

In the same production step, update the default learner-server construction so the repository never contains an intermediate state with an invalid constructor call:

```python
if role == "trainee" and renewable_manager is None:
    renewable_manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=exchange.control_snapshot,
        receive_status_provider=exchange.receive_status,
        command_sink=exchange.submit_commands,
    )
```

- [ ] **Step 4: Remove renewable-owned receive/cache code**

Delete from `simu/renewable_control.py`:

- `_request_json`
- `_url_with_query`
- `_measurement_definition_identity`
- `_merge_remote_measurements_with_local_definitions`
- `_merge_remote_runtime_devices`
- `_merge_runtime_snapshot_with_local_definitions`
- `_SnapshotCacheCandidate`
- `_ControllerState.cached_snapshot`
- `_ControllerState.cached_snapshot_at`
- `_ControllerState.cached_static_signature`
- `_connection()`
- `_receive_state_signature()` fields derived from external links
- `_static_signature()`
- `_fetch_remote_snapshot()`
- `_snapshot_for_calculation()`
- `_commit_snapshot_cache()`
- `_snapshot_result_parts()`

Remove unused `urllib` imports from this module after deletion.

- [ ] **Step 5: Implement learner-only prerequisites and snapshot acquisition**

`_receive_prerequisite()` must use `receive_status_provider(model_id)` and recognize three states:

```python
{
    "receiveActive": False,
    "ready": False,
    "canRun": False,
    "prerequisiteStatus": "请先启动接收。",
}
```

```python
{
    "receiveActive": True,
    "ready": False,
    "canRun": False,
    "prerequisiteStatus": "学员台正在等待第一份实时数据。",
}
```

```python
{
    "receiveActive": True,
    "ready": True,
    "canRun": True,
    "prerequisiteStatus": "",
}
```

Replace `_snapshot_for_calculation()` calls with one provider call:

```python
view = self.snapshot_provider(model_id)
if not view.ready:
    raise RuntimeError(view.error or "学员台尚未收到实时数据")
snapshot = view.snapshot
source = view.source
age = view.age_seconds
fetch_error = view.error
```

Before and after plan calculation, compare a learner-owned token composed only of `receiveActive`, `ready`, and exchange `revision/connectionSignature`. If it changes, discard the cycle exactly as the existing race-protection tests require.

- [ ] **Step 6: Submit closed-loop commands only to the learner sink**

Replace URL construction and `request_json()` with:

```python
result = self.command_sink(model_id, payload)
```

Preserve duplicate dispatch claiming before the sink call. Update messages:

```text
学员台指令入口提交失败：...
已向学员台指令入口提交 N 条遥调指令。
学员台指令入口接受遥调指令 N 条；策略时刻 ...
开环计算完成，生成 N 条遥调策略，未提交学员台指令入口。
```

Log type must be `学员台响应`, not `模拟台响应`.

- [ ] **Step 7: Update backend-control tests to inject providers**

Create shared test helpers:

```python
def ready_view(snapshot, *, revision=1, age=0.0, error=None):
    return TraineeControlSnapshot(
        snapshot=copy.deepcopy(snapshot),
        source="trainee-live" if error is None else "trainee-cache",
        age_seconds=age,
        error=error,
        receive_active=True,
        ready=True,
        revision=revision,
        connection_signature=("learner", revision),
    )


def ready_status(_model_id):
    return {
        "receiveActive": True,
        "ready": True,
        "canRun": True,
        "revision": 1,
        "connectionSignature": ["learner", 1],
        "prerequisiteStatus": "",
    }
```

Replace manager `request_json=` fixtures with `snapshot_provider=`, `receive_status_provider=`, and `command_sink=` fakes. Keep strategy assertions unchanged.

- [ ] **Step 8: Run manager tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_trainee_renewable_receive_independence.py tests/test_trainee_definition_renewable_sync.py tests/test_trainee_renewable_backend_control.py -q
```

Expected: all manager isolation and control behavior tests pass. If the four previously observed DC-transfer/uncontrolled-storage planner failures remain, report them separately and confirm no new manager failures.

---

### Task 7: Verify exchange-provider wiring and custom-manager lifecycle

**Files:**
- Modify: `simu/server.py:1020-1037`
- Modify: `tests/test_trainee_renewable_backend_control.py`
- Modify: `tests/test_trainee_multi_simulator_receive.py`

- [ ] **Step 1: Extend the server wiring test for custom ownership**

Keep the default binding assertion written in Task 6, then add ownership assertions for injected dependencies:

```python
exchange = FakeExchange()
manager = TraineeRenewableControlManager(
    trainee,
    snapshot_provider=exchange.control_snapshot,
    receive_status_provider=exchange.receive_status,
    command_sink=exchange.submit_commands,
    start_worker=False,
)
server = make_http_server(
    ("127.0.0.1", 0),
    trainee,
    role="trainee",
    trainee_exchange=exchange,
    renewable_control_manager=manager,
)
try:
    self.assertIs(server.trainee_exchange, exchange)
    self.assertIs(server.renewable_control_manager, manager)
finally:
    server.server_close()
self.assertEqual(exchange.closed, 1)
```

- [ ] **Step 2: Run the ownership test and verify RED if lifecycle support is incomplete**

Run:

```powershell
python -m pytest tests/test_trainee_multi_simulator_receive.py -k renewable -q
```

Expected: default provider binding already passes from Task 6; the new assertion fails only if the server does not retain and close the injected exchange exactly once.

- [ ] **Step 3: Complete ownership handling without changing providers**

If a custom manager is supplied, do not silently overwrite its providers. Retain the supplied exchange on `server.trainee_exchange`, close it once from `server_close()`, and close the supplied manager once using the existing manager lifecycle. Tests supplying a custom manager must construct it with compatible learner providers.

- [ ] **Step 4: Run learner server and renewable API tests**

Run:

```powershell
python -m pytest tests/test_trainee_multi_simulator_receive.py tests/test_trainee_renewable_backend_control.py -k "server or api or receive" -q
```

Expected: all selected tests pass except any explicitly documented pre-existing planner-only failures.

---

### Task 8: Preserve frontend behavior and learner-only wording

**Files:**
- Modify: `simu/web/trainee/app.js` only where backend status/data-source labels require it.
- Modify: `tests/test_trainee_receive_validation.py`
- Modify: `tests/test_trainee_renewable_receive_independence.py`

- [ ] **Step 1: Write failing source assertions for learner API usage**

Keep existing assertions that the browser uses:

```text
/api/trainee/snapshot
/api/trainee/measurements/delta
/api/trainee/commands
/api/trainee/renewable-control
```

Add assertions that renewable-control UI status handling recognizes `trainee-live`, `trainee-cache`, and the first-frame waiting message without requiring any simulator URL.

- [ ] **Step 2: Run frontend source tests and verify RED where wording is missing**

Run:

```powershell
python -m pytest tests/test_trainee_receive_validation.py tests/test_trainee_renewable_receive_independence.py -q
```

Expected: only wording/source-contract assertions fail; route assertions continue to pass.

- [ ] **Step 3: Apply minimal frontend wording changes**

Do not move receive logic into the browser. Only map backend statuses to visible learner-oriented text. Do not add polling beyond the existing page refresh because the backend worker owns reception.

- [ ] **Step 4: Verify JavaScript syntax and UI source tests**

Run:

```powershell
node --check simu/web/trainee/app.js
python -m pytest tests/test_trainee_receive_validation.py tests/test_incremental_runtime_data_ui.py -q
```

Expected: syntax check and all tests pass.

---

### Task 9: Verify restart, multi-model isolation, and no-browser operation

**Files:**
- Modify: `tests/test_trainee_realtime_exchange.py`
- Modify: `tests/test_trainee_multi_simulator_receive.py`

- [ ] **Step 1: Write restart and model-isolation tests**

Add tests that:

- Create two learner models with different active connections and different runtime snapshots.
- Verify exchange revisions and snapshots do not cross model IDs.
- Close and recreate the learner server while receive state remains active.
- Verify the new exchange worker repopulates the active model without a browser request.
- Verify an inactive model remains without a runtime snapshot.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py tests/test_trainee_multi_simulator_receive.py -k "restart or model_isolation or without_browser" -q
```

Expected: failures until worker startup enumeration and per-model state cleanup are complete.

- [ ] **Step 3: Complete worker startup and stale-model cleanup**

On worker start, enumerate existing services and wake immediately. During each loop, remove in-memory states for model IDs no longer returned by `iter_services()`. Do not persist runtime snapshots.

- [ ] **Step 4: Run restart and multi-model tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py tests/test_trainee_multi_simulator_receive.py -q
```

Expected: all pass.

---

### Task 10: Final regression and architectural verification

**Files:**
- Verify all files changed in Tasks 1-9.

- [ ] **Step 1: Run Python and JavaScript syntax checks**

```powershell
python -m py_compile simu/trainee_exchange.py simu/server.py simu/service.py simu/renewable_control.py
node --check simu/web/trainee/app.js
```

Expected: exit code 0.

- [ ] **Step 2: Run the focused feature suite**

```powershell
python -m pytest tests/test_trainee_realtime_exchange.py tests/test_trainee_definition_renewable_sync.py tests/test_trainee_renewable_receive_independence.py tests/test_trainee_multi_simulator_receive.py tests/test_trainee_model_initialization.py tests/test_trainee_receive_validation.py tests/test_incremental_runtime_data_ui.py tests/test_live_definition_editing_api.py tests/test_manual_definition_changes.py tests/test_manual_definition_changes_ui.py -q
```

Expected: all pass.

- [ ] **Step 3: Run renewable backend regressions**

```powershell
python -m pytest tests/test_trainee_renewable_backend_control.py tests/test_trainee_renewable_receive_independence.py tests/test_storage_soc_constraints.py tests/test_resource_parameter_snapshot.py -q
```

Expected: no new exchange/manager failures. Separately list any pre-existing planner-metric failures rather than hiding them.

- [ ] **Step 4: Prove the renewable module has no simulator transport**

```powershell
rg -n "teacher_api_base|snapshot_path|command_path|urlopen|urljoin|_fetch_remote_snapshot|request_json" simu/renewable_control.py
```

Expected: no matches in `simu/renewable_control.py`.

Also confirm the transport exists only in the learner exchange/server boundary:

```powershell
rg -n "teacher_api_base|snapshot_path|command_path|urlopen|urljoin" simu/trainee_exchange.py simu/server.py
```

Expected: matches are confined to learner connection initialization, exchange reception, and learner command forwarding.

- [ ] **Step 5: Inspect the scoped diff and whitespace**

```powershell
git diff --check -- simu/trainee_exchange.py simu/server.py simu/renewable_control.py simu/web/trainee/app.js tests/test_trainee_realtime_exchange.py tests/test_trainee_definition_renewable_sync.py tests/test_trainee_renewable_receive_independence.py tests/test_trainee_multi_simulator_receive.py tests/test_trainee_model_initialization.py tests/test_trainee_receive_validation.py tests/test_trainee_renewable_backend_control.py
```

Expected: no whitespace errors. CRLF conversion warnings may be reported separately.

- [ ] **Step 6: Final requirement checklist**

Confirm all statements with test evidence:

- Renewable control has no simulator URL, snapshot, or command dependency.
- Learner background receiving operates without a browser page.
- Learner pages and renewable control share one model-scoped cache.
- Runtime values come from the learner exchange; static parameters come from the learner model.
- Manual learner parameter edits affect the next control cycle.
- Closed-loop commands enter the learner command sink exactly once per simulation instant.
- Receive inactive, first-frame waiting, connection changes, stale data, restart, and multi-model cases are covered.

Do not claim completion until every verification command has been run and its output read.
