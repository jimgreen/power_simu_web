# Simulator Live Definition Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagent-driven execution is unavailable in this side conversation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the simulator SVG device and measurement popups to edit static model and measurement definitions while simulation continues, using copy-on-write memory snapshots followed by atomic source E-file persistence.

**Architecture:** `PolarMicrogridSimulator` owns one immutable definition snapshot captured once per simulation step. Edit requests serialize only against other edit requests, clone and validate the affected definition, atomically publish a new snapshot, then persist that accepted snapshot with sibling temporary files and `os.replace`; the simulation thread never reloads files or takes the edit lock. The simulator frontend patches returned records locally, preserves active form DOM during realtime refresh, and uses a definition revision in `static_meta` to synchronize other pages.

**Tech Stack:** Python 3, `unittest`/pytest, `ThreadingHTTPServer`, EBook/EBlock model definitions, vanilla JavaScript, SVG DOM, CSS, Node.js helper tests, browser interaction verification.

**Repository handling:** The worktree already contains unrelated model, plan, and temporary-file changes. Every implementation step must stage or inspect only the exact paths listed below. Do not commit, reset, delete, or rewrite unrelated changes unless the user separately requests Git operations.

---

## File Structure

- Create `simu/definition_editing.py`: immutable snapshot type, field policy, measurement sigma/weight normalization, EBook rendering, and atomic text persistence.
- Modify `simu/service.py`: snapshot ownership, hot-swap service methods, revision metadata, per-step snapshot capture, and measurement-definition projection.
- Modify `simu/server.py`: simulator-only definition-edit API routes and JSON error translation.
- Modify `simu/web/simulator/app.js`: definition record lookup, editable popup state, API calls, local snapshot patching, and non-destructive realtime refresh.
- Modify `simu/web/simulator/styles.css`: compact editor controls, save status, and pinned popup states.
- Create `tests/test_definition_editing_helpers.py`: pure validation, conversion, rendering, and atomic-write tests.
- Create `tests/test_live_definition_hot_swap.py`: service snapshot, concurrency, persistence failure, and runtime-isolation tests.
- Create `tests/test_live_definition_editing_api.py`: HTTP route, model scoping, and simulator-role tests.
- Create `tests/test_svg_live_definition_editing_ui.py`: Node helper and frontend contract tests.
- Reference `docs/superpowers/specs/2026-08-03-simulator-live-definition-editing-design.md`: approved behavioral specification.

## Task 1: Pure Definition Editing Helpers

**Files:**
- Create: `tests/test_definition_editing_helpers.py`
- Create: `simu/definition_editing.py`

- [ ] **Step 1: Write failing tests for protected fields, numeric coercion, and bound validation**

Create tests that express the backend policy without involving the service:

```python
from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simu.definition_editing import (
    atomic_write_text,
    editable_device_field,
    normalize_device_changes,
    normalize_measurement_changes,
    render_ebook_aligned,
)


class DefinitionEditingHelpersTest(unittest.TestCase):
    def test_identity_topology_runtime_and_setpoint_fields_are_protected(self):
        protected = {
            "idx", "name", "dev_type", "node", "i_node", "j_node",
            "ac_node", "dc_node", "idx_acgenerator", "idx_dcgenerator",
            "run_stat", "status", "isl", "p_set", "q_set", "v_set",
            "p_ac_set", "q_ac_set", "v_ac_set", "v_dc_set",
        }
        for field in protected:
            with self.subTest(field=field):
                self.assertFalse(editable_device_field(field))
        for field in ("p_max", "p_min", "rated_capacity", "r", "x", "soc_upper_limit"):
            with self.subTest(field=field):
                self.assertTrue(editable_device_field(field))

    def test_device_changes_preserve_string_fields_and_require_finite_numbers(self):
        current = {
            "p_min": "20",
            "p_max": "100",
            "rated_capacity": "120",
            "wind_turbine_model": "WT-A",
        }
        normalized = normalize_device_changes(
            current,
            {"p_min": 25, "p_max": "110.5", "wind_turbine_model": "WT-B"},
        )
        self.assertEqual(normalized["p_min"], "25")
        self.assertEqual(normalized["p_max"], "110.5")
        self.assertEqual(normalized["wind_turbine_model"], "WT-B")
        with self.assertRaisesRegex(ValueError, "finite"):
            normalize_device_changes(current, {"p_max": math.inf})

    def test_device_changes_reject_inverted_bounds(self):
        current = {"p_min": "20", "p_max": "100"}
        with self.assertRaisesRegex(ValueError, "p_min.*p_max"):
            normalize_device_changes(current, {"p_min": 120})
```

- [ ] **Step 2: Write failing tests for measurement sigma/weight semantics**

Append:

```python
    def test_measurement_sigma_and_weight_are_bidirectionally_normalized(self):
        from_sigma = normalize_measurement_changes({"weight": "25", "valid": "1"}, {"error_sigma": 0.1})
        self.assertAlmostEqual(float(from_sigma["weight"]), 100.0)
        self.assertAlmostEqual(from_sigma["error_sigma"], 0.1)

        from_weight = normalize_measurement_changes({"weight": "25", "valid": "1"}, {"weight": 400})
        self.assertEqual(from_weight["weight"], "400")
        self.assertAlmostEqual(from_weight["error_sigma"], 0.05)

    def test_measurement_changes_reject_nonpositive_weight_and_invalid_status(self):
        with self.assertRaisesRegex(ValueError, "weight"):
            normalize_measurement_changes({"weight": "25", "valid": "1"}, {"weight": 0})
        with self.assertRaisesRegex(ValueError, "valid"):
            normalize_measurement_changes({"weight": "25", "valid": "1"}, {"valid": 2})

    def test_measurement_changes_reject_inconsistent_sigma_and_weight(self):
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            normalize_measurement_changes(
                {"weight": "25", "valid": "1"},
                {"weight": 100, "error_sigma": 0.2},
            )
```

- [ ] **Step 3: Write failing tests for aligned rendering and sibling atomic replacement**

Append a minimal EBook fixture using the project EBook implementation and verify that `os.replace` observes the complete temporary file before replacement:

```python
    def test_atomic_write_text_replaces_complete_sibling_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "model.e"
            target.write_text("old", encoding="utf-8")
            observed = {}

            import os
            real_replace = os.replace

            def inspect_replace(source, destination):
                source_path = Path(source)
                observed["parent"] = source_path.parent
                observed["text"] = source_path.read_text(encoding="utf-8")
                observed["old"] = Path(destination).read_text(encoding="utf-8")
                real_replace(source, destination)

            with patch("simu.definition_editing.os.replace", side_effect=inspect_replace):
                atomic_write_text(target, "new complete text\n")

            self.assertEqual(observed["parent"], root)
            self.assertEqual(observed["text"], "new complete text\n")
            self.assertEqual(observed["old"], "old")
            self.assertEqual(target.read_text(encoding="utf-8"), "new complete text\n")
            self.assertEqual(list(root.glob(".model.e.*.tmp")), [])
```

- [ ] **Step 4: Run the helper tests and verify RED**

Run:

```powershell
python -m pytest tests/test_definition_editing_helpers.py -q
```

Expected: collection fails because `simu.definition_editing` does not exist.

- [ ] **Step 5: Implement the focused helper module**

Create `simu/definition_editing.py` with these public boundaries:

```python
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class DefinitionSnapshot:
    revision: int
    model_book: Any
    dev_define_book: Any
    measurement_before: Tuple[str, ...]
    measurement_rows: Tuple[Tuple[str, ...], ...]
    measurement_after: Tuple[str, ...]


PROTECTED_DEVICE_FIELDS = {
    "idx", "name", "dev_name", "dev_type", "path",
    "node", "i_node", "j_node", "ac_node", "dc_node",
    "run_stat", "status", "isl",
    "p_set", "q_set", "v_set", "i_set",
    "p_ac_set", "q_ac_set", "v_ac_set", "v_dc_set",
}

NONNEGATIVE_DEVICE_FIELD_TOKENS = (
    "capacity", "efficiency", "count", "area", "diameter", "height",
    "rated_power", "rated_voltage", "wind_speed",
)


def editable_device_field(field: str) -> bool:
    name = str(field or "").strip()
    return bool(name) and name not in PROTECTED_DEVICE_FIELDS and not name.startswith("idx_")


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _number_text(value: float) -> str:
    text = format(float(value), ".15g")
    return "0" if text in {"-0", "-0.0"} else text


def _numeric_cell(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _bound_pairs(fields: Sequence[str]) -> set[tuple[str, str]]:
    available = set(fields)
    pairs: set[tuple[str, str]] = set()
    for field in available:
        if field.endswith("_min"):
            counterpart = f"{field[:-4]}_max"
            if counterpart in available:
                pairs.add((field, counterpart))
        if field.endswith("_lower_limit"):
            counterpart = f"{field[:-12]}_upper_limit"
            if counterpart in available:
                pairs.add((field, counterpart))
    return pairs


def normalize_device_changes(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("At least one device parameter change is required")
    unknown = [field for field in changes if field not in current]
    if unknown:
        raise ValueError(f"Unknown device parameter: {unknown[0]}")
    protected = [field for field in changes if not editable_device_field(field)]
    if protected:
        raise ValueError(f"Device parameter is not editable: {protected[0]}")

    normalized: dict[str, str] = {}
    for field, value in changes.items():
        if _numeric_cell(current.get(field)):
            number = _finite_number(value, field)
            if any(token in field for token in NONNEGATIVE_DEVICE_FIELD_TOKENS) and number < 0:
                raise ValueError(f"{field} must not be negative")
            normalized[field] = _number_text(number)
        else:
            normalized[field] = str(value).strip()

    merged = {key: str(value) for key, value in current.items()}
    merged.update(normalized)
    for lower, upper in _bound_pairs(tuple(merged)):
        if _finite_number(merged[lower], lower) > _finite_number(merged[upper], upper):
            raise ValueError(f"{lower} must not exceed {upper}")
    return normalized


def normalize_measurement_changes(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"weight", "error_sigma", "valid"}
    unknown = [field for field in changes if field not in allowed]
    if unknown:
        raise ValueError(f"Unknown measurement parameter: {unknown[0]}")

    current_weight = _finite_number(current.get("weight"), "weight")
    weight = _finite_number(changes.get("weight", current_weight), "weight")
    if weight <= 0:
        raise ValueError("weight must be greater than zero")

    sigma_value = changes.get("error_sigma")
    if sigma_value is not None:
        sigma = _finite_number(sigma_value, "error_sigma")
        if sigma <= 0:
            raise ValueError("error_sigma must be greater than zero")
        sigma_weight = 1.0 / (sigma * sigma)
        if "weight" in changes and not math.isclose(weight, sigma_weight, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("weight and error_sigma are inconsistent")
        weight = sigma_weight
    else:
        sigma = 1.0 / math.sqrt(weight)

    valid_number = _finite_number(changes.get("valid", current.get("valid", 1)), "valid")
    if valid_number not in (0.0, 1.0):
        raise ValueError("valid must be 0 or 1")
    valid = int(valid_number)
    return {
        "weight": _number_text(weight),
        "valid": str(valid),
        "error_sigma": sigma,
    }


def render_ebook_aligned(book: Any) -> str:
    parts: list[str] = []
    for block in book.data.values():
        header = list(block.header_list)
        widths = [len(name) for name in header]
        for row in block.data:
            for index, name in enumerate(header):
                widths[index] = max(widths[index], len(str(row.get(name, ""))))
        parts.append(f"<{block.name}>\n")
        parts.append(
            "@ "
            + "  ".join(f"{header[index]:<{widths[index]}}" for index in range(len(header))).rstrip()
            + "\n"
        )
        for row in block.data:
            parts.append(
                "# "
                + "  ".join(
                    f"{str(row.get(name, '')):<{widths[index]}}"
                    for index, name in enumerate(header)
                ).rstrip()
                + "\n"
            )
        parts.append(f"</{block.name}>\n")
    return "".join(parts)


def atomic_write_text(path: Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
```

Do not add runtime-directory behavior or file locks beyond this implementation.

- [ ] **Step 6: Run helper tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_definition_editing_helpers.py -q
```

Expected: all helper tests pass.

- [ ] **Step 7: Inspect only Task 1 paths**

Run:

```powershell
git diff --check -- simu/definition_editing.py tests/test_definition_editing_helpers.py
git diff -- simu/definition_editing.py tests/test_definition_editing_helpers.py
```

Expected: no whitespace errors; no unrelated paths appear.

## Task 2: Service-Owned Immutable Snapshot

**Files:**
- Create: `tests/test_live_definition_hot_swap.py`
- Modify: `simu/service.py`

- [ ] **Step 1: Write a temporary source-model fixture and failing copy-on-write test**

Copy `tests/fixtures/simple_model` into a temporary source directory before constructing the service so the test never edits shared fixtures:

```python
from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from simu.service import EBook, PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/simple_model"


class LiveDefinitionHotSwapTest(unittest.TestCase):
    def _make_service(self, kernel=None):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            model_id="hot-swap",
            kernel=kernel or (lambda _config: None),
        )
        self.addCleanup(workspace.cleanup)
        return source, runtime, service

    def test_device_update_publishes_new_snapshot_without_mutating_old_book(self):
        source, _runtime, service = self._make_service()
        before = service.definition_snapshot
        old_row = next(row for row in before.model_book.data["ACBranch"].data if row["name"] == "diesel_line")

        result = service.update_device_parameters({
            "block_name": "ACBranch",
            "row_key": {"name": "diesel_line", "idx": "2"},
            "changes": {"r": 0.0025},
        })

        after = service.definition_snapshot
        new_row = next(row for row in after.model_book.data["ACBranch"].data if row["name"] == "diesel_line")
        persisted = next(row for row in EBook(source / "model.e").data["ACBranch"].data if row["name"] == "diesel_line")
        self.assertIsNot(before, after)
        self.assertIsNot(before.model_book, after.model_book)
        self.assertEqual(old_row["r"], "0.001")
        self.assertEqual(new_row["r"], "0.0025")
        self.assertEqual(persisted["r"], "0.0025")
        self.assertEqual(after.revision, before.revision + 1)
        self.assertTrue(result["memory_updated"])
        self.assertTrue(result["persisted"])
```

- [ ] **Step 2: Write failing tests for protected fields and measurement projection**

Append:

```python
    def test_device_update_rejects_topology_and_runtime_fields(self):
        _source, _runtime, service = self._make_service()
        for changes in ({"i_node": 99}, {"run_stat": 0}, {"p_set": 12}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.update_device_parameters({
                    "block_name": "ACBranch" if "i_node" in changes else "ACGenerator",
                    "row_key": {"name": "diesel_line" if "i_node" in changes else "diesel_300kw"},
                    "changes": changes,
                })

    def test_measurement_update_changes_definition_and_next_noise_weight(self):
        source, _runtime, service = self._make_service()
        name = "p_gen_diesel_300kw"
        result = service.update_measurement_definition({
            "name": name,
            "changes": {"error_sigma": 0.02, "valid": 0},
        })
        definition = next(row for row in service.measurements()["definitions"] if row["name"] == name)
        persisted = next(row for row in EBook(source / "meas.e").data["Measurement"].data if row["name"] == name)
        self.assertAlmostEqual(float(definition["weight"]), 2500.0)
        self.assertEqual(definition["valid"], 0)
        self.assertAlmostEqual(float(persisted["weight"]), 2500.0)
        self.assertEqual(int(float(persisted["valid"])), 0)
        self.assertAlmostEqual(result["record"]["error_sigma"], 0.02)
```

The copied fixture defines `p_gen_diesel_300kw`; use that exact name so a missing or renamed definition fails visibly.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_live_definition_hot_swap.py -q
```

Expected: failures because `definition_snapshot`, `update_device_parameters`, and `update_measurement_definition` do not exist.

- [ ] **Step 4: Add snapshot ownership and publication to the service**

In `simu/service.py`:

1. Import `DefinitionSnapshot`, `atomic_write_text`, `normalize_device_changes`, `normalize_measurement_changes`, and `render_ebook_aligned`.
2. Add `self.definition_update_lock = threading.Lock()` in `PolarMicrogridSimulator.__init__`; do not reuse `self.lock`.
3. After loading model and measurement definitions, publish a `DefinitionSnapshot` containing immutable tuples for measurement lines and rows.
4. Add a read-only property:

```python
    @property
    def definition_snapshot(self) -> DefinitionSnapshot:
        return self._definition_snapshot
```

5. Add one publication helper that assigns `_definition_snapshot` first and then updates compatibility aliases without mutating the old snapshot:

```python
    def _publish_definition_snapshot(self, snapshot: DefinitionSnapshot) -> None:
        self._definition_snapshot = snapshot
        self.source_model_book = snapshot.model_book
        self.dev_define_book = snapshot.dev_define_book
        self.measurement_before = list(snapshot.measurement_before)
        self.measurement_rows = [list(row) for row in snapshot.measurement_rows]
        self.measurement_after = list(snapshot.measurement_after)
```

6. Update `_make_config()` to capture `definition_snapshot = self.definition_snapshot` once, then populate all model and measurement config fields from that local reference.

- [ ] **Step 5: Implement device and measurement hot-swap methods minimally**

Add methods near `definitions()`:

```python
    def update_device_parameters(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.definition_update_lock:
            current = self.definition_snapshot
            model_book = simu_loop._clone_ebook(current.model_book)
            block_name = str(payload.get("block_name", "")).strip()
            block = model_book.data.get(block_name)
            if block is None:
                raise ValueError(f"Unknown model block: {block_name}")
            row = self._definition_row(block, payload.get("row_key", {}))
            normalized = normalize_device_changes(row, payload.get("changes", {}))
            row.update(normalized)
            dev_define_book = simu_loop._capability_define_book(model_book, self._legacy_dev_define_file())
            next_snapshot = DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=model_book,
                dev_define_book=dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
            )
            self._publish_definition_snapshot(next_snapshot)
            return self._persist_device_definition(next_snapshot, block_name, row)

    def update_measurement_definition(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.definition_update_lock:
            current = self.definition_snapshot
            rows = [list(row) for row in current.measurement_rows]
            index, current_item = self._measurement_definition_row(rows, payload)
            normalized = normalize_measurement_changes(current_item, payload.get("changes", {}))
            rows[index][5] = normalized["weight"]
            rows[index][6] = normalized["valid"]
            next_snapshot = DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=current.model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=tuple(tuple(row) for row in rows),
                measurement_after=current.measurement_after,
            )
            self._publish_definition_snapshot(next_snapshot)
            return self._persist_measurement_definition(next_snapshot, normalized["error_sigma"], rows[index])
```

The persistence helpers must publish before calling `atomic_write_text`, catch `OSError`, keep the snapshot active, and return `persisted: False` with the warning text from the spec. They must not call `reload_definition_state`, `_append_runtime_log`, `reset_runtime_for_model_change`, or any method that writes runtime definitions.

- [ ] **Step 6: Project the active snapshot consistently to readers**

Update these functions to capture `definition_snapshot = self.definition_snapshot` once and use it:

- `_make_config`
- `measurements`
- `_measurement_delta_current_items`
- `devices`
- `device_states`
- `device_parameters`
- `_definition_book_for_path`
- `definitions`

For `measurements()`, overlay definition `weight` and `valid` onto copied `real` and `scada` response rows by measurement name. Keep realtime `value` unchanged. For `_measurement_delta_current_items()`, take `weight` and `valid` from the active definition rather than stale realtime rows.

- [ ] **Step 7: Run focused service tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_live_definition_hot_swap.py -q
```

Expected: all current hot-swap tests pass.

## Task 3: Prove Non-Blocking Simulation and Runtime Isolation

**Files:**
- Modify: `tests/test_live_definition_hot_swap.py`
- Modify: `simu/service.py`
- Modify: `simu/definition_editing.py`

- [ ] **Step 1: Write the failing blocked-kernel test**

Append:

```python
    def test_definition_update_does_not_wait_for_running_kernel_and_applies_next_step(self):
        entered = threading.Event()
        release = threading.Event()
        captured = []

        def blocking_kernel(config):
            captured.append(config)
            entered.set()
            release.wait(5)
            return None

        _source, _runtime, service = self._make_service(kernel=blocking_kernel)
        worker = threading.Thread(target=service.step, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(2))

        started = time.monotonic()
        result = service.update_device_parameters({
            "block_name": "ACBranch",
            "row_key": {"name": "diesel_line"},
            "changes": {"r": 0.003},
        })
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertTrue(result["memory_updated"])

        first_row = next(row for row in captured[0].model_book.data["ACBranch"].data if row["name"] == "diesel_line")
        self.assertEqual(first_row["r"], "0.001")
        release.set()
        worker.join(2)

        service.kernel = lambda config: captured.append(config) or None
        service.step()
        second_row = next(row for row in captured[1].model_book.data["ACBranch"].data if row["name"] == "diesel_line")
        self.assertEqual(second_row["r"], "0.003")
```

- [ ] **Step 2: Write runtime tree fingerprint and persistence-failure tests**

Append:

```python
    def _tree_fingerprint(self, root: Path):
        result = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def test_edit_does_not_create_or_change_runtime_files(self):
        _source, runtime, service = self._make_service()
        before = self._tree_fingerprint(runtime)
        service.update_device_parameters({
            "block_name": "ACBranch",
            "row_key": {"name": "diesel_line"},
            "changes": {"r": 0.004},
        })
        self.assertEqual(self._tree_fingerprint(runtime), before)

    def test_persistence_failure_keeps_new_memory_snapshot_and_old_source_file(self):
        source, _runtime, service = self._make_service()
        old_text = (source / "model.e").read_text(encoding="utf-8")
        with patch("simu.service.atomic_write_text", side_effect=OSError("disk full")):
            result = service.update_device_parameters({
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line"},
                "changes": {"r": 0.005},
            })
        active = next(row for row in service.definition_snapshot.model_book.data["ACBranch"].data if row["name"] == "diesel_line")
        self.assertEqual(active["r"], "0.005")
        self.assertEqual((source / "model.e").read_text(encoding="utf-8"), old_text)
        self.assertTrue(result["memory_updated"])
        self.assertFalse(result["persisted"])
        self.assertIn("E 文件保存失败", result["warning"])
```

- [ ] **Step 3: Run tests and verify RED for any lock or persistence ordering defect**

Run:

```powershell
python -m pytest tests/test_live_definition_hot_swap.py -q
```

Expected before corrections: at least one new assertion fails if the edit path takes `self.lock`, publishes after persistence, or writes runtime files.

- [ ] **Step 4: Make the minimal service corrections**

Ensure:

- The only lock in both update methods is `definition_update_lock`.
- `_publish_definition_snapshot(next_snapshot)` occurs before `atomic_write_text`.
- E-file text is rendered entirely from `next_snapshot`.
- No runtime log or runtime definition writer is called.
- `_make_config()` captures the old or new snapshot by one reference read.

- [ ] **Step 5: Run concurrency and isolation tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_live_definition_hot_swap.py -q
```

Expected: all tests pass; blocked kernel test completes without releasing the kernel before the edit returns.

## Task 4: Simulator-Only HTTP APIs

**Files:**
- Create: `tests/test_live_definition_editing_api.py`
- Modify: `simu/server.py`

- [ ] **Step 1: Write failing simulator API tests**

Create a copied temporary model, start `make_http_server(..., role="simulator")`, and POST:

```python
def post_json(url: str, payload: dict):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_device_parameter_endpoint_updates_selected_model(self):
    status, payload = post_json(
        f"{base}/api/definitions/device-parameters?model_id=hot-swap",
        {
            "block_name": "ACBranch",
            "row_key": {"name": "diesel_line"},
            "changes": {"r": 0.006},
        },
    )
    assert status == 200
    assert payload["model_id"] == "hot-swap"
    assert payload["memory_updated"] is True
    assert payload["persisted"] is True
    assert payload["record"]["r"] == 0.006


def test_measurement_endpoint_returns_weight_sigma_and_revision():
    status, payload = post_json(
        f"{base}/api/definitions/measurement?model_id=hot-swap",
        {"name": measurement_name, "changes": {"weight": 100, "valid": 1}},
    )
    assert status == 200
    assert payload["record"]["weight"] == 100.0
    assert payload["record"]["error_sigma"] == 0.1
    assert payload["revision"] >= 1
    assert payload["static_meta"]["definitions"]["revision"] == payload["revision"]
```

- [ ] **Step 2: Write failing trainee-role and validation tests**

Start another server with `role="trainee"` and assert both endpoints return HTTP 404. On the simulator server, assert a protected-field request returns HTTP 400 and leaves the source file unchanged.

- [ ] **Step 3: Run API tests and verify RED**

Run:

```powershell
python -m pytest tests/test_live_definition_editing_api.py -q
```

Expected: HTTP 404 for missing routes on the simulator server.

- [ ] **Step 4: Add the two routes to `_handle_api_post`**

In `simu/server.py`, before general runtime control routes:

```python
            if path in (
                "/api/definitions/device-parameters",
                "/api/definitions/measurement",
            ):
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                target = self._target_service(payload)
                try:
                    result = (
                        target.update_device_parameters(payload)
                        if path.endswith("device-parameters")
                        else target.update_measurement_definition(payload)
                    )
                except (KeyError, ValueError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json(result)
                return
```

Do not reject edits based on `target.clock.state`; running and paused models must use the same route.

- [ ] **Step 5: Include revision in static metadata**

Modify `PolarMicrogridSimulator.static_meta()` so `definitions` and `device_parameters` each include the active snapshot revision in addition to the existing file signature:

```python
        definition_revision = self.definition_snapshot.revision
        definitions_meta = self._path_static_signature(definition_paths)
        definitions_meta["revision"] = definition_revision
        device_parameters_meta = self._path_static_signature([self.source_files.get("model")])
        device_parameters_meta["revision"] = definition_revision
```

Return `self.static_meta()` in both edit responses.

- [ ] **Step 6: Run API and snapshot-cache tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_live_definition_editing_api.py tests/test_snapshot_performance.py -q
```

Expected: both files pass.

## Task 5: Frontend Pure Helpers and Local Snapshot Patching

**Files:**
- Create: `tests/test_svg_live_definition_editing_ui.py`
- Modify: `simu/web/simulator/app.js`

- [ ] **Step 1: Write failing Node helper tests for editable fields and linked records**

Extract a self-contained helper section from `app.js` and verify:

```javascript
const snapshot = {
  definitions: {
    model: {
      ACGenerator: {
        headers: ["idx", "name", "node", "p_min", "p_max", "run_stat"],
        rows: [{ idx: 1, name: "wind-1", node: 3, p_min: 0, p_max: 10, run_stat: 1 }],
      },
      ACWindGen: {
        headers: ["idx", "idx_acgenerator", "cut_in_wind_speed", "rated_wind_speed"],
        rows: [{ idx: 7, idx_acgenerator: 1, cut_in_wind_speed: 4, rated_wind_speed: 12 }],
      },
    },
  },
};
const records = diagramDeviceDefinitionRecords(
  { devType: "ACGenerator", devName: "wind-1" },
  snapshot,
);
process.stdout.write(JSON.stringify({
  blocks: records.map((record) => record.blockName),
  editable: [
    diagramDeviceParameterEditable("p_max"),
    diagramDeviceParameterEditable("r"),
    diagramDeviceParameterEditable("node"),
    diagramDeviceParameterEditable("run_stat"),
    diagramDeviceParameterEditable("p_set"),
  ],
}));
```

Expected result after implementation:

```json
{"blocks":["ACGenerator","ACWindGen"],"editable":[true,true,false,false,false]}
```

- [ ] **Step 2: Write failing tests for measurement pair and sigma/weight conversion**

Test pure helpers with a definition weight of 100, real value 9.5, SCADA value 10.0, and `valid=1`. Assert:

- measured value is `10.0`
- true value is `9.5`
- deviation is `0.5` without `abs`, `min`, or `max`
- sigma is `0.1`
- `diagramDefinitionWeightFromSigma(0.02)` is `2500`
- `diagramDefinitionSigmaFromWeight(400)` is `0.05`

- [ ] **Step 3: Write frontend contract assertions**

Assert `app.js` contains:

- `/api/definitions/device-parameters`
- `/api/definitions/measurement`
- `data-diagram-definition-editor`
- `data-diagram-definition-save`
- `data-diagram-measurement-real`
- `data-diagram-measurement-scada`
- `data-diagram-measurement-deviation`
- `function applyDefinitionEditResult`

Assert the trainee app does not contain either edit endpoint.

- [ ] **Step 4: Run UI helper tests and verify RED**

Run:

```powershell
python -m pytest tests/test_svg_live_definition_editing_ui.py -q
```

Expected: missing helper and endpoint assertions fail.

- [ ] **Step 5: Add pure frontend helpers near existing diagram helper constants**

Add:

```javascript
const DIAGRAM_DEFINITION_PROTECTED_FIELDS = new Set([
  "idx", "name", "dev_name", "dev_type", "path",
  "node", "i_node", "j_node", "ac_node", "dc_node",
  "run_stat", "status", "isl",
  "p_set", "q_set", "v_set", "i_set",
  "p_ac_set", "q_ac_set", "v_ac_set", "v_dc_set",
]);

const DIAGRAM_LINKED_DEFINITION_BLOCKS = {
  ACGENERATOR: [{ blockName: "ACWindGen", referenceField: "idx_acgenerator" }],
  DCGENERATOR: [
    { blockName: "DCPVGen", referenceField: "idx_dcgenerator" },
    { blockName: "DCStorageGen", referenceField: "idx_dcgenerator" },
  ],
};

function diagramDeviceParameterEditable(field) {
  const name = String(field || "").trim();
  return Boolean(name)
    && !DIAGRAM_DEFINITION_PROTECTED_FIELDS.has(name)
    && !name.startsWith("idx_");
}

function diagramDefinitionSigmaFromWeight(weight) {
  const number = Number(weight);
  return Number.isFinite(number) && number > 0 ? 1 / Math.sqrt(number) : null;
}

function diagramDefinitionWeightFromSigma(sigma) {
  const number = Number(sigma);
  return Number.isFinite(number) && number > 0 ? 1 / (number * number) : null;
}
```

Implement `diagramDeviceDefinitionRecords`, `diagramMetricMeasurementPair`, and `applyDefinitionEditResult` as pure or mostly pure helpers. `applyDefinitionEditResult` must patch only the returned model block row or measurement definition row, merge returned `static_meta`, and persist the updated static cache without reloading the SVG.

- [ ] **Step 6: Run helper tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_svg_live_definition_editing_ui.py -q
node --check simu/web/simulator/app.js
```

Expected: tests pass and Node syntax check exits 0.

## Task 6: Editable Device Popup Without Rebuilds

**Files:**
- Modify: `tests/test_svg_live_definition_editing_ui.py`
- Modify: `simu/web/simulator/app.js`
- Modify: `simu/web/simulator/styles.css`

- [ ] **Step 1: Write failing contract tests for editor lifecycle**

Assert the simulator script implements these named boundaries:

```text
beginDiagramDeviceDefinitionEdit
cancelDiagramDefinitionEdit
saveDiagramDeviceDefinitionEdit
renderDiagramDeviceDefinitionEditor
updateDiagramDeviceDynamicSections
diagramDefinitionEditPinned
```

Assert `scheduleDiagramTooltipHide` checks the pinned editor state before starting a timer. Assert `updateDiagramDeviceTooltip` calls `updateDiagramDeviceDynamicSections` while an editor is active instead of replacing editor HTML.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_svg_live_definition_editing_ui.py -q
```

Expected: editor lifecycle assertions fail.

- [ ] **Step 3: Extend diagram interaction state minimally**

Add these fields to the existing interaction object:

```javascript
definitionEditor: null,
definitionSaving: false,
definitionMessage: "",
```

The editor record must identify one block at a time:

```javascript
{
  kind: "device",
  blockName,
  rowKey: { idx, name },
  original: { ...row },
  draft: { ...row },
  dirtyFields: new Set(),
}
```

Editing one block at a time avoids partial multi-block transactions. Linked blocks remain visible and each exposes its own edit command.

- [ ] **Step 4: Render static records with per-block edit controls**

Refactor `diagramDeviceTooltipData()` so dynamic sections and static definition records are separate. Render each definition record with:

- block title
- read-only identity fields
- editable static fields
- one edit button for that block
- save/cancel controls while that block is active
- inline status text for saved, saving, and persistence warning states

Use `<input type="number">` for numeric current values and `<input type="text">` for string values. Do not render controls for protected fields.

- [ ] **Step 5: Implement save and local patching**

`saveDiagramDeviceDefinitionEdit` must:

1. Collect only fields in `dirtyFields`.
2. POST to `/api/definitions/device-parameters` through the existing model-scoped `api()` helper.
3. Call `applyDefinitionEditResult(result)` even when `persisted` is false.
4. Keep the warning visible if persistence failed.
5. Exit edit mode only after the backend accepted the memory update.
6. Refresh the current tooltip in place.

- [ ] **Step 6: Preserve form DOM during realtime refresh**

When `interaction.definitionEditor?.kind === "device"`:

- update title, status, set values, and realtime measurement text by data attributes
- do not call `syncDiagramTooltipSections` on the static editor subtree
- do not replace `tooltip.innerHTML`
- do not overwrite inputs in `dirtyFields`

`scheduleDiagramTooltipHide` must return without scheduling while the editor is active. Cancel, successful save, Escape, or explicit tooltip close releases the pin.

- [ ] **Step 7: Add compact CSS**

Add selectors scoped under `.diagram-tooltip`:

```css
.diagram-definition-section-head
.diagram-definition-edit-button
.diagram-definition-editor
.diagram-definition-input
.diagram-definition-actions
.diagram-definition-message
.diagram-definition-message.is-warning
.diagram-tooltip.is-editing-definition
```

Keep the tooltip within the existing width and height constraints. Inputs must not resize rows during value changes.

- [ ] **Step 8: Run UI tests and syntax check**

Run:

```powershell
python -m pytest tests/test_svg_live_definition_editing_ui.py tests/test_svg_diagram_interactions_ui.py -q
node --check simu/web/simulator/app.js
```

Expected: all pass.

## Task 7: Measurement Popup Values and Definition Editor

**Files:**
- Modify: `tests/test_svg_live_definition_editing_ui.py`
- Modify: `simu/web/simulator/app.js`
- Modify: `simu/web/simulator/styles.css`

- [ ] **Step 1: Write failing tests for simultaneous measured and true values**

Assert `diagramMetricTooltipData()` or its pure helper returns separate fields:

```json
{
  "scadaValue": 10.0,
  "realValue": 9.5,
  "deviation": 0.5,
  "valid": 1,
  "weight": 100.0,
  "errorSigma": 0.1
}
```

Assert the tooltip HTML contains dedicated data attributes for all six values and does not collapse real and SCADA into one fallback field.

- [ ] **Step 2: Write failing tests for non-destructive measurement editor refresh**

Assert the script defines:

```text
beginDiagramMeasurementDefinitionEdit
saveDiagramMeasurementDefinitionEdit
syncDiagramMeasurementDefinitionFields
updateDiagramMetricDynamicValues
```

Assert the update path calls `updateDiagramMetricDynamicValues` while the editor is active and does not replace the editor subtree.

- [ ] **Step 3: Run UI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_svg_live_definition_editing_ui.py -q
```

Expected: measurement editor assertions fail.

- [ ] **Step 4: Render the measurement summary and editor**

Replace the single current-value display with a compact summary grid:

```text
量测值      SCADA current value
真值        real current value
当前偏差    SCADA - real
状态        valid/invalid
误差 σ      1 / sqrt(weight)
权重        definition weight
```

Keep the existing hour/day trend tabs and chart below the summary. The trend may continue to plot the existing selected measurement series; this task does not change trend retention or sampling semantics.

- [ ] **Step 5: Implement linked sigma/weight inputs**

While editing:

- changing sigma computes weight with `diagramDefinitionWeightFromSigma`
- changing weight computes sigma with `diagramDefinitionSigmaFromWeight`
- invalid or nonpositive input disables Save and shows inline validation
- the validity selector sends integer `0` or `1`
- Save sends `{ name, dev_type, dev_name, meas_type, changes }`

Send both sigma and weight only after frontend synchronization has made them consistent.

- [ ] **Step 6: Preserve dynamic updates and chart interaction**

`updateDiagramMetricTooltip()` must continue updating:

- measured value
- true value
- deviation
- validity display
- trend chart and cursor data

It must not replace focused inputs or dirty drafts. Trend tab clicks must continue to work while the definition editor is open.

- [ ] **Step 7: Run UI regressions and syntax check**

Run:

```powershell
python -m pytest tests/test_svg_live_definition_editing_ui.py tests/test_svg_realtime_measurement_binding_ui.py tests/test_svg_diagram_interactions_ui.py -q
node --check simu/web/simulator/app.js
```

Expected: all pass.

## Task 8: Cross-Page Revision Synchronization

**Files:**
- Modify: `tests/test_live_definition_hot_swap.py`
- Modify: `tests/test_svg_live_definition_editing_ui.py`
- Modify: `simu/service.py`
- Modify: `simu/web/simulator/app.js`

- [ ] **Step 1: Write failing backend revision tests**

Verify:

- device update increments revision once
- measurement update increments revision once
- persistence failure still increments revision because memory changed
- both `static_meta.definitions.revision` and `static_meta.device_parameters.revision` equal the active revision

- [ ] **Step 2: Write failing frontend cache tests**

Use the existing static metadata helpers and assert that two metadata objects with identical file signatures but different revisions do not match:

```javascript
const left = { signature: "same", revision: 4 };
const right = { signature: "same", revision: 5 };
process.stdout.write(JSON.stringify(staticMetaMatches(left, right)));
```

Expected: `false`.

Assert `applyDefinitionEditResult` updates current metadata and cache while preserving `state.snapshot.diagram`.

- [ ] **Step 3: Run tests and verify RED where revision is absent**

Run:

```powershell
python -m pytest tests/test_live_definition_hot_swap.py tests/test_svg_live_definition_editing_ui.py -q
```

Expected before final wiring: revision assertions fail.

- [ ] **Step 4: Complete revision wiring minimally**

Ensure every edit response includes:

```python
{
    "model_id": self.model_id,
    "model_name": self.model_name,
    "revision": next_snapshot.revision,
    "memory_updated": True,
    "persisted": persisted,
    "record": record,
    "static_meta": self.static_meta(),
}
```

The next lite snapshot must expose the same revision. Existing `mergeSnapshot()` behavior will remove stale static fields when metadata differs, and the following request will fetch only missing fields for the current page.

- [ ] **Step 5: Run revision and snapshot tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_live_definition_hot_swap.py tests/test_live_definition_editing_api.py tests/test_svg_live_definition_editing_ui.py tests/test_snapshot_performance.py -q
```

Expected: all pass.

## Task 9: Focused Regression and Source/Runtime Separation

**Files:**
- Modify only if a regression is found: files already listed above

- [ ] **Step 1: Run all definition, in-memory runtime, and SVG tests**

Run:

```powershell
python -m pytest \
  tests/test_definition_editing_helpers.py \
  tests/test_live_definition_hot_swap.py \
  tests/test_live_definition_editing_api.py \
  tests/test_in_memory_kernel_runtime.py \
  tests/test_model_source_runtime_separation.py \
  tests/test_incremental_runtime_data_api.py \
  tests/test_incremental_runtime_data_ui.py \
  tests/test_svg_live_definition_editing_ui.py \
  tests/test_svg_realtime_measurement_binding_ui.py \
  tests/test_svg_diagram_interactions_ui.py \
  -q
```

Expected: all listed tests pass.

- [ ] **Step 2: Run Python and JavaScript static checks**

Run:

```powershell
python -m ruff check simu/definition_editing.py simu/service.py simu/server.py tests/test_definition_editing_helpers.py tests/test_live_definition_hot_swap.py tests/test_live_definition_editing_api.py tests/test_svg_live_definition_editing_ui.py
node --check simu/web/simulator/app.js
git diff --check -- simu/definition_editing.py simu/service.py simu/server.py simu/web/simulator/app.js simu/web/simulator/styles.css tests/test_definition_editing_helpers.py tests/test_live_definition_hot_swap.py tests/test_live_definition_editing_api.py tests/test_svg_live_definition_editing_ui.py
```

Expected: all commands exit 0.

- [ ] **Step 3: Run the full Python test suite**

Run:

```powershell
python -m pytest -q
```

Expected: zero failures. Record the exact pass/skip counts before reporting completion.

- [ ] **Step 4: Inspect the final scoped diff**

Run:

```powershell
git status --short
git diff --stat -- simu/definition_editing.py simu/service.py simu/server.py simu/web/simulator/app.js simu/web/simulator/styles.css tests/test_definition_editing_helpers.py tests/test_live_definition_hot_swap.py tests/test_live_definition_editing_api.py tests/test_svg_live_definition_editing_ui.py docs/superpowers/specs/2026-08-03-simulator-live-definition-editing-design.md docs/superpowers/plans/2026-08-03-simulator-live-definition-editing.md
```

Expected: scoped files are identifiable; unrelated pre-existing changes remain untouched.

## Task 10: Browser Interaction Verification

**Files:**
- No source changes unless a browser-reproduced defect receives a failing automated test first.

- [ ] **Step 1: Read the in-app browser control skill before browser actions**

Read `browser:control-in-app-browser` and use its supported browser tools rather than ad hoc GUI automation.

- [ ] **Step 2: Start the simulator WEB server on an unused local port**

Use the repository's existing startup command discovered from `simu/server.py --help`. Do not overwrite or stop another server already using the default port. Record the chosen URL.

- [ ] **Step 3: Verify device editing while the simulation clock advances**

In the simulator browser:

1. Start simulation and record the current simulation time.
2. Open the SVG diagram and hover a branch or generator.
3. Enter edit mode for a static parameter block.
4. Change an allowed field such as branch resistance or generator upper limit.
5. Keep the editor open through at least two realtime refreshes and confirm the input is not overwritten.
6. Save and confirm the simulation time continued advancing.
7. Confirm the popup shows the accepted value without reloading the SVG.
8. Confirm the source `model.e` contains the value and runtime contains no new `model.e` or `meas.e`.

- [ ] **Step 4: Verify measurement editing and realtime values**

1. Hover an SVG dynamic measurement.
2. Confirm measured value, true value, signed deviation, status, sigma, and weight are all visible.
3. Enter edit mode and change sigma; confirm weight changes immediately.
4. Change weight; confirm sigma changes immediately.
5. Change validity, save, and confirm the backend definition and `meas.e` update.
6. Keep the popup open and confirm realtime values and the trend continue refreshing without rebuilding the editor.

- [ ] **Step 5: Verify two-page synchronization**

Open two simulator pages on the same model. Save a parameter in the first page and wait for normal polling in the second. Confirm the second page receives the new definition without switching models, reloading the SVG, or restarting simulation.

- [ ] **Step 6: Verify persistence-failure presentation with an automated test or controlled writable-copy setup**

Do not change permissions on the user's real model directory. Use a temporary copied model served by a test instance, inject a persistence failure through the tested backend seam, and confirm the page displays the warning while retaining the memory value.

- [ ] **Step 7: Stop only the server started for this verification**

Leave unrelated WEB servers, terminal processes, model files, and runtime directories untouched.

## Completion Evidence

Before claiming completion, collect fresh evidence for all of the following:

- Focused RED failures were observed before each production implementation.
- Focused GREEN tests pass.
- Full test suite reports zero failures.
- Ruff and Node syntax checks exit 0.
- Browser verification confirms editing during a running simulation.
- Source E files update atomically.
- Runtime directory fingerprints remain unchanged by edits.
- Current simulation step uses the old snapshot and the next step uses the new snapshot.
- Persistence failure keeps memory updated and exposes a visible warning.
- `git status --short` shows unrelated pre-existing changes were not reverted or deleted.
