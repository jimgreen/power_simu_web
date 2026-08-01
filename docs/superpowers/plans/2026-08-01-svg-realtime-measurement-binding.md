# SVG Realtime Measurement Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make simulator and trainee SVG diagrams display current model measurement values through the semantic `dev` and `mt` placeholders already present in exported diagrams.

**Architecture:** Keep the existing explicit `data-*` binding path, then add a semantic binding compiler that resolves SVG device ids to model device names and maps metric names such as `activePower` to device-specific measurement types. Compile DOM bindings only when the SVG changes; each realtime refresh rebuilds small measurement indexes and updates the cached elements without additional HTTP calls.

**Tech Stack:** Vanilla JavaScript, SVG DOM APIs, Python `unittest`, Node.js syntax and pure-function execution tests, existing lightweight snapshot and measurement-delta APIs.

---

## File Structure

- Create `tests/test_svg_realtime_measurement_binding_ui.py`: executable regression tests for metric mapping, channel priority, SOC formatting, and required semantic DOM hooks in both applications.
- Modify `simu/web/simulator/app.js`: add semantic SVG binding compilation and realtime updates to the simulator diagram page.
- Modify `simu/web/trainee/app.js`: mirror the simulator binding behavior while preserving the trainee service proxy data flow.
- Modify `tests/test_model_diagram_ui.py`: retain broad page-level assertions and add cache/semantic-selector integration checks if needed after implementation.

### Task 1: Add Failing Pure-Behavior Regression Tests

**Files:**
- Create: `tests/test_svg_realtime_measurement_binding_ui.py`
- Read: `simu/web/simulator/app.js`
- Read: `simu/web/trainee/app.js`

- [ ] **Step 1: Write a source extraction helper and failing mapping test**

Create a test that extracts the new pure helper block from each application and executes it with Node:

```python
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SvgRealtimeMeasurementBindingUiTest(unittest.TestCase):
    def _scripts(self):
        return (
            ROOT / "simu/web/simulator/app.js",
            ROOT / "simu/web/trainee/app.js",
        )

    def _helper_source(self, script: str) -> str:
        self.assertIn("const DIAGRAM_METRIC_MEASUREMENT_TYPES", script)
        return "const DIAGRAM_METRIC_MEASUREMENT_TYPES" + script.split(
            "const DIAGRAM_METRIC_MEASUREMENT_TYPES", 1
        )[1].split("function addDiagramControlAliases", 1)[0]

    def _run_helpers(self, script: str, body: str):
        harness = """
function measurementKey(row) {
  return String(row?.name || `${row?.dev_type || ""}.${row?.dev_name || ""}.${row?.meas_type || ""}`);
}
"""
        result = subprocess.run(
            ["node", "-e", f"{harness}\n{self._helper_source(script)}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_metric_candidates_are_device_specific(self):
        body = """
process.stdout.write(JSON.stringify({
  generator: diagramMetricMeasurementTypes("ACGenerator", "activePower"),
  converter: diagramMetricMeasurementTypes("DCACConverter", "activePower"),
  storage: diagramMetricMeasurementTypes("DCGenerator", "level"),
  switchStatus: diagramMetricMeasurementTypes("ACBreak", "status"),
}));
"""
        for path in self._scripts():
            payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
            self.assertEqual(payload["generator"][0], "P_GEN")
            self.assertEqual(payload["converter"][:2], ["P_AC", "P_DC"])
            self.assertEqual(payload["storage"][:2], ["SOC", "LEVEL"])
            self.assertEqual(payload["switchStatus"][:2], ["STATUS", "RUN_STAT"])
```

- [ ] **Step 2: Add failing channel-priority and SOC formatting tests**

Append tests that use real row-shaped objects:

```python
    def test_semantic_binding_prefers_scada_and_falls_back_to_real(self):
        body = """
const scadaRow = { dev_type: "ACGenerator", dev_name: "wind-1", meas_type: "P_GEN", value: 12.5 };
const realRow = { dev_type: "ACGenerator", dev_name: "wind-1", meas_type: "P_GEN", value: 13.5 };
const maps = diagramMeasurementMaps({ measurements: { scada: [scadaRow], real: [realRow] } });
const binding = { devType: "ACGenerator", devName: "wind-1", metricType: "activePower" };
const preferred = diagramMetricBindingValue(binding, maps);
const fallbackMaps = diagramMeasurementMaps({ measurements: { scada: [], real: [realRow] } });
const fallback = diagramMetricBindingValue(binding, fallbackMaps);
process.stdout.write(JSON.stringify([preferred.value, fallback.value]));
"""
        for path in self._scripts():
            self.assertEqual(self._run_helpers(path.read_text(encoding="utf-8"), body), [12.5, 13.5])

    def test_soc_display_is_percent_without_clamping(self):
        body = """
process.stdout.write(JSON.stringify([
  diagramDisplayRow({ meas_type: "SOC", value: 1.08 }, "level").value,
  diagramDisplayRow({ meas_type: "SOC", value: -0.03 }, "level").value,
]));
"""
        for path in self._scripts():
            self.assertEqual(self._run_helpers(path.read_text(encoding="utf-8"), body), [108, -3])
```

- [ ] **Step 3: Add failing semantic DOM integration assertions**

```python
    def test_exported_svg_semantic_placeholders_are_compiled_and_cached(self):
        for path in self._scripts():
            script = path.read_text(encoding="utf-8")
            self.assertIn('querySelectorAll("[dev] [mt]")', script)
            self.assertIn("function compileDiagramMetricBindings", script)
            self.assertIn("diagramMetricBindingCache", script)
            self.assertIn("diagramMetricBindingValue(binding, maps)", script)
```

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```powershell
python -m unittest tests.test_svg_realtime_measurement_binding_ui
```

Expected: FAIL because `DIAGRAM_METRIC_MEASUREMENT_TYPES`, semantic helper functions, and `[dev] [mt]` compilation do not exist.

- [ ] **Step 5: Keep the failing test uncommitted and proceed to implementation**

Do not commit a known-red state on `main`. Preserve the failing output as TDD evidence, then continue directly to Task 2 and commit the test together with the first green implementation.

### Task 2: Implement Device-Specific Measurement Resolution

**Files:**
- Modify: `simu/web/simulator/app.js:2833-2920`
- Modify: `simu/web/trainee/app.js:1378-1465`
- Test: `tests/test_svg_realtime_measurement_binding_ui.py`

- [ ] **Step 1: Add the metric candidate table to both applications**

Insert immediately before `diagramNumberText`:

```javascript
const DIAGRAM_METRIC_MEASUREMENT_TYPES = Object.freeze({
  activePower: Object.freeze({
    ACGENERATOR: ["P_GEN"],
    DCGENERATOR: ["P_GEN"],
    ACLOAD: ["P_LOAD"],
    DCACCONVERTER: ["P_AC", "P_DC"],
    DCDCCONVERTER: ["P_TO", "P_FROM"],
    ACBRANCH: ["P_FROM", "P_TO"],
    DCBRANCH: ["P_FROM", "P_TO"],
    ACBREAK: ["P_FROM", "P_TO"],
    DCBREAK: ["P_FROM", "P_TO"],
    ACZEROBRANCH: ["P_FROM", "P_TO"],
    "*": ["P", "P_GEN", "P_LOAD", "P_AC", "P_DC", "P_TO", "P_FROM"],
  }),
  reactivePower: Object.freeze({
    ACGENERATOR: ["Q_GEN"],
    ACLOAD: ["Q_LOAD"],
    DCACCONVERTER: ["Q_AC"],
    ACBRANCH: ["Q_FROM", "Q_TO"],
    ACBREAK: ["Q_FROM", "Q_TO"],
    ACZEROBRANCH: ["Q_FROM", "Q_TO"],
    "*": ["Q", "Q_GEN", "Q_LOAD", "Q_AC", "Q_FROM", "Q_TO"],
  }),
  voltage: Object.freeze({
    ACGENERATOR: ["V_GEN"],
    DCGENERATOR: ["V_GEN"],
    ACLOAD: ["V_LOAD"],
    DCACCONVERTER: ["V_AC", "V_DC"],
    DCDCCONVERTER: ["V_TO", "V_FROM"],
    "*": ["V", "V_GEN", "V_LOAD", "V_AC", "V_DC", "V_TO", "V_FROM"],
  }),
  current: Object.freeze({
    ACGENERATOR: ["I_GEN"],
    DCGENERATOR: ["I_GEN"],
    ACLOAD: ["I_LOAD"],
    DCACCONVERTER: ["I_AC", "I_DC"],
    DCDCCONVERTER: ["I_TO", "I_FROM"],
    "*": ["I", "I_GEN", "I_LOAD", "I_AC", "I_DC", "I_TO", "I_FROM"],
  }),
  status: Object.freeze({ "*": ["STATUS", "RUN_STAT"] }),
  level: Object.freeze({ "*": ["SOC", "LEVEL"] }),
  frequency: Object.freeze({ "*": ["FREQUENCY", "FREQ", "F"] }),
  flow: Object.freeze({ "*": ["FLOW"] }),
  pressure: Object.freeze({ "*": ["PRESSURE"] }),
  temperature: Object.freeze({ "*": ["TEMPERATURE"] }),
});
```

- [ ] **Step 2: Add pure normalization, indexing, resolution, and display helpers**

Add the same helpers in both applications:

```javascript
function normalizeDiagramMeasurementToken(value) {
  return String(value || "").trim().toUpperCase();
}

function diagramMetricMeasurementTypes(devType, metricType) {
  const metricMap = DIAGRAM_METRIC_MEASUREMENT_TYPES[String(metricType || "").trim()] || {};
  const specific = metricMap[normalizeDiagramMeasurementToken(devType)] || [];
  return [...new Set([...specific, ...(metricMap["*"] || [])])];
}

function diagramDeviceMeasurementKey(devType, devName, measType) {
  return [
    normalizeDiagramMeasurementToken(devType),
    String(devName || "").trim(),
    normalizeDiagramMeasurementToken(measType),
  ].join("\u0000");
}

function addDiagramDeviceMeasurement(map, row) {
  if (!row?.dev_type || !row?.dev_name || !row?.meas_type) return;
  map.set(diagramDeviceMeasurementKey(row.dev_type, row.dev_name, row.meas_type), row);
}

function diagramMetricBindingValue(binding, maps) {
  const candidates = diagramMetricMeasurementTypes(binding?.devType, binding?.metricType);
  for (const measType of candidates) {
    const key = diagramDeviceMeasurementKey(binding.devType, binding.devName, measType);
    if (maps.scadaByDevice.has(key)) return maps.scadaByDevice.get(key);
  }
  for (const measType of candidates) {
    const key = diagramDeviceMeasurementKey(binding.devType, binding.devName, measType);
    if (maps.realByDevice.has(key)) return maps.realByDevice.get(key);
  }
  return null;
}

function diagramDisplayRow(row, metricType = "") {
  if (!row) return row;
  if (
    String(metricType || "").trim() === "level"
    && normalizeDiagramMeasurementToken(row.meas_type) === "SOC"
    && Number.isFinite(Number(row.value))
  ) {
    return { ...row, value: Number(row.value) * 100 };
  }
  return row;
}
```

- [ ] **Step 3: Extend `diagramMeasurementMaps` with per-device indexes**

Replace the function body in both applications:

```javascript
function diagramMeasurementMaps(snapshot = state.snapshot || {}) {
  const measurements = snapshot.measurements || {};
  const scada = new Map();
  const real = new Map();
  const scadaByDevice = new Map();
  const realByDevice = new Map();
  (measurements.scada || []).forEach((row) => {
    addDiagramMeasurementAliases(scada, row);
    addDiagramDeviceMeasurement(scadaByDevice, row);
  });
  (measurements.real || []).forEach((row) => {
    addDiagramMeasurementAliases(real, row);
    addDiagramDeviceMeasurement(realByDevice, row);
  });
  return { scada, real, scadaByDevice, realByDevice };
}
```

- [ ] **Step 4: Make null values and SOC display formatting correct**

Change `setDiagramElementValue` to accept the semantic metric type:

```javascript
function setDiagramElementValue(element, row, metricType = "") {
  const displayRow = diagramDisplayRow(row, metricType);
  const missing = displayRow?.value === undefined || displayRow?.value === null;
  const text = missing
    ? "--"
    : (displayRow.unit !== undefined ? diagramRowText(displayRow) : diagramNumberText(displayRow.value));
  const tag = String(element.tagName || "").toLowerCase();
  if (["text", "tspan", "title", "desc"].includes(tag) || element instanceof HTMLElement) {
    element.textContent = text;
  } else {
    element.setAttribute("data-current-value", text);
  }
  element.classList.toggle("is-diagram-bound", Boolean(displayRow) && !missing);
  element.setAttribute("data-bound-value", text);
  const updated = displayRow?.updated_simu_time || displayRow?.updated_wall_time || displayRow?.updated;
  if (updated) element.setAttribute("data-bound-time", updated);
  else element.removeAttribute("data-bound-time");
}
```

- [ ] **Step 5: Run pure tests and verify GREEN for resolution helpers**

Run:

```powershell
python -m unittest tests.test_svg_realtime_measurement_binding_ui
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
```

Expected: mapping, channel-priority, and SOC tests pass; semantic DOM integration assertion may still fail until Task 3.

- [ ] **Step 6: Commit the resolution layer**

```powershell
git add simu/web/simulator/app.js simu/web/trainee/app.js tests/test_svg_realtime_measurement_binding_ui.py
git commit -m "feat: resolve SVG semantic measurements"
```

### Task 3: Compile and Cache SVG Semantic Bindings

**Files:**
- Modify: `simu/web/simulator/app.js:2920-2959`
- Modify: `simu/web/trainee/app.js:1465-1504`
- Test: `tests/test_svg_realtime_measurement_binding_ui.py`
- Test: `tests/test_model_diagram_ui.py`

- [ ] **Step 1: Add a per-container binding cache**

Immediately before the SVG binding compiler in each application:

```javascript
const diagramMetricBindingCache = new WeakMap();
```

- [ ] **Step 2: Compile exported SVG device and metric metadata**

```javascript
function compileDiagramMetricBindings(container) {
  const devices = new Map();
  container.querySelectorAll("[dev-id][name], [id][name]").forEach((element) => {
    const devId = element.getAttribute("dev-id") || element.getAttribute("id") || "";
    const devName = element.getAttribute("name") || "";
    if (!devId || !devName || devices.has(devId)) return;
    const layerType = element.closest("[device-type]")?.getAttribute("device-type") || "";
    devices.set(devId, {
      devType: layerType || devId.split("-", 1)[0],
      devName,
    });
  });
  return [...container.querySelectorAll("[dev] [mt]")].map((element) => {
    if (element.matches("[data-meas-name], [data-scada-name], [data-real-name], [data-control-name]")) {
      return null;
    }
    const owner = element.closest("[dev]");
    const device = devices.get(owner?.getAttribute("dev") || "");
    const metricType = element.getAttribute("mt") || "";
    if (!device || !metricType) return null;
    return { element, ...device, metricType };
  }).filter(Boolean);
}

function diagramMetricBindings(container) {
  let bindings = diagramMetricBindingCache.get(container);
  if (!bindings) {
    bindings = compileDiagramMetricBindings(container);
    diagramMetricBindingCache.set(container, bindings);
  }
  return bindings;
}
```

- [ ] **Step 3: Update semantic placeholders after explicit bindings**

Append to `updateDiagramRealtimeBindings` in both applications:

```javascript
  diagramMetricBindings(container).forEach((binding) => {
    setDiagramElementValue(
      binding.element,
      diagramMetricBindingValue(binding, maps),
      binding.metricType,
    );
  });
```

- [ ] **Step 4: Invalidate cached bindings whenever the SVG DOM is replaced**

Inside the `canvas.dataset.diagramKey !== key` branch, before assigning `innerHTML`:

```javascript
diagramMetricBindingCache.delete(canvas);
```

Also delete the cache when no diagram is configured:

```javascript
diagramMetricBindingCache.delete(canvas);
```

- [ ] **Step 5: Run diagram tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_svg_realtime_measurement_binding_ui tests.test_model_diagram_ui tests.test_lightweight_snapshot_ui tests.test_measurement_incremental_refresh_ui
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
```

Expected: all tests pass and both scripts parse successfully.

- [ ] **Step 6: Commit the DOM binding integration**

```powershell
git add simu/web/simulator/app.js simu/web/trainee/app.js tests/test_svg_realtime_measurement_binding_ui.py tests/test_model_diagram_ui.py
git commit -m "feat: update realtime values in SVG diagrams"
```

### Task 4: Full Verification With Real Model SVGs

**Files:**
- Verify: `models/simulator/source/IEEE118/diagram.svg`
- Verify: `models/simulator/source/秦岭站/diagram.svg`
- Verify: `models/trainee/source/默认模型/diagram.svg`
- Verify: `simu/web/simulator/app.js`
- Verify: `simu/web/trainee/app.js`

- [ ] **Step 1: Run targeted and complete test suites**

```powershell
python -m unittest tests.test_svg_realtime_measurement_binding_ui tests.test_model_diagram_ui tests.test_lightweight_snapshot_ui tests.test_measurement_incremental_refresh_ui tests.test_active_page_rendering_ui tests.test_snapshot_performance
python -m unittest
```

Expected: targeted tests and the complete suite pass with zero failures.

- [ ] **Step 2: Verify the actual SVG metadata remains intact**

```powershell
$paths = @(
  'models/simulator/source/IEEE118/diagram.svg',
  'models/simulator/source/秦岭站/diagram.svg',
  'models/trainee/source/默认模型/diagram.svg'
)
foreach ($path in $paths) {
  $text = Get-Content -Raw -LiteralPath $path
  [pscustomobject]@{
    Path = $path
    Devices = ([regex]::Matches($text, ' dev="')).Count
    Metrics = ([regex]::Matches($text, ' mt="')).Count
  }
}
```

Expected: IEEE118 and Qinling/trainee diagrams retain their existing device and metric placeholders; the implementation does not rewrite these files.

- [ ] **Step 3: Browser-verify the simulator diagram**

Open `http://127.0.0.1:8710/diagram`, select Qinling, run or single-step the stopped model, and verify:

- `.mv[mt="activePower"]` values change from `--` to signed numeric values.
- `.mv[mt="level"]` displays SOC as percent.
- A second realtime refresh changes text without replacing the SVG root element.
- Model switching clears old values and binds the new diagram.
- Browser console has no errors.

- [ ] **Step 4: Browser-verify the trainee diagram**

Open `http://127.0.0.1:8720/diagram`, choose a model with the imported Qinling diagram, start receive mode if needed, and verify the same active-power and SOC values match the simulator while the trainee page only calls trainee service URLs.

- [ ] **Step 5: Check repository hygiene**

```powershell
git diff --check -- simu/web/simulator/app.js simu/web/trainee/app.js tests/test_svg_realtime_measurement_binding_ui.py tests/test_model_diagram_ui.py
git status --short --branch
```

Expected: no whitespace errors in implementation files and only intentional source/test changes remain.

- [ ] **Step 6: Commit any final verification adjustment**

Only when browser verification required a source or test correction:

```powershell
git add simu/web/simulator/app.js simu/web/trainee/app.js tests/test_svg_realtime_measurement_binding_ui.py tests/test_model_diagram_ui.py
git commit -m "fix: finalize SVG realtime measurement updates"
```
