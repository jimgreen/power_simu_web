# SVG Trend Cursor and Display Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a nearest-point trend cursor with a visible unit-bearing Y axis, plus independently persisted simulator/trainee SVG controls for measurements, device name/ID labels, and signed active-power flow arrows.

**Architecture:** Extend the existing duplicated simulator and trainee SVG interaction helpers rather than introducing a build system or changing imported diagrams. Keep numeric decisions in pure JavaScript helpers covered by Node-backed Python tests, keep DOM work in the existing delegated interaction lifecycle, and add runtime SVG elements that share the diagram `viewBox` so zoom and pan stay aligned. Persist three booleans in console-specific `localStorage` keys and continue collecting/updating hidden measurements without new server calls.

**Tech Stack:** Vanilla JavaScript, inline SVG and SVG animation APIs, HTML/CSS context menu, browser `localStorage` and `storage` events, Python `unittest`, Node.js helper harnesses, existing simulator/trainee snapshot and history flows.

---

## File Map

- Modify `simu/web/simulator/app.js`: simulator key, trend scale/cursor helpers, context-menu state, runtime labels, flow-arrow compilation/update, lifecycle wiring.
- Modify `simu/web/trainee/app.js`: mirror the same SVG behavior with the trainee persistence key and preserve trainee double-click command behavior.
- Modify `simu/web/simulator/styles.css`: trend axes/cursor, context menu, hidden layers, generated device ID, and flow-arrow styling.
- Modify `simu/web/trainee/styles.css`: mirror simulator SVG styles without changing unrelated trainee renewable-control layout.
- Modify `tests/test_svg_diagram_interactions_ui.py`: pure helper tests, wiring assertions, persistence-key separation, lifecycle assertions, and style coverage for both apps.

No server, model, imported SVG, or API file is modified.

### Task 1: Add Pure Trend Axis and Cursor Helpers

**Files:**
- Modify: `tests/test_svg_diagram_interactions_ui.py`
- Modify: `simu/web/simulator/app.js:2840-3030`
- Modify: `simu/web/trainee/app.js:1387-1585`

- [ ] **Step 1: Write failing helper tests for axis scaling and nearest-point selection**

Add tests that run against both scripts through `_run_helpers`:

```python
def test_trend_axis_uses_readable_ticks_and_expands_flat_values(self):
    body = """
const normal = diagramTrendAxisScale([-2.2, 7.6], 4);
const flat = diagramTrendAxisScale([5, 5, 5], 4);
process.stdout.write(JSON.stringify({ normal, flat }));
"""
    for path in self._scripts():
        payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
        self.assertLessEqual(payload["normal"]["min"], -2.2)
        self.assertGreaterEqual(payload["normal"]["max"], 7.6)
        self.assertGreaterEqual(len(payload["normal"]["ticks"]), 3)
        self.assertLess(payload["flat"]["min"], 5)
        self.assertGreater(payload["flat"]["max"], 5)

def test_trend_cursor_snaps_to_nearest_sampled_point(self):
    body = """
const points = [
  { minute: 10, time: "00:10", value: -2 },
  { minute: 20, time: "00:20", value: 4 },
  { minute: 35, time: "00:35", value: 9 },
];
process.stdout.write(JSON.stringify({
  before: diagramNearestTrendPoint(points, 0),
  middle: diagramNearestTrendPoint(points, 27),
  after: diagramNearestTrendPoint(points, 50),
  data: diagramTrendCursorData(points, 19, "kW"),
}));
"""
    for path in self._scripts():
        payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
        self.assertEqual(payload["before"]["minute"], 10)
        self.assertEqual(payload["middle"]["minute"], 20)
        self.assertEqual(payload["after"]["minute"], 35)
        self.assertEqual(payload["data"], {"minute": 20, "time": "00:20", "value": 4, "unit": "kW"})
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_svg_diagram_interactions_ui.SvgDiagramInteractionsUiTest.test_trend_axis_uses_readable_ticks_and_expands_flat_values tests.test_svg_diagram_interactions_ui.SvgDiagramInteractionsUiTest.test_trend_cursor_snaps_to_nearest_sampled_point
```

Expected: both tests fail because `diagramTrendAxisScale`, `diagramNearestTrendPoint`, and `diagramTrendCursorData` do not exist.

- [ ] **Step 3: Add minimal pure helpers to both app scripts**

Place these after `diagramSampleTrendPoints` dependencies and before `addDiagramControlAliases` so the existing Node harness can execute them:

```javascript
function diagramNiceStep(value) {
  const raw = Math.abs(Number(value));
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

function diagramTrendAxisScale(values, targetTickCount = 4) {
  const valid = (values || []).map(Number).filter(Number.isFinite);
  if (!valid.length) return { min: 0, max: 1, ticks: [0, 0.5, 1] };
  let dataMin = Math.min(...valid);
  let dataMax = Math.max(...valid);
  if (Math.abs(dataMax - dataMin) < 1e-9) {
    const padding = Math.max(1, Math.abs(dataMax) * 0.05);
    dataMin -= padding;
    dataMax += padding;
  }
  const step = diagramNiceStep((dataMax - dataMin) / Math.max(2, Number(targetTickCount) - 1));
  const min = Math.floor(dataMin / step) * step;
  const max = Math.ceil(dataMax / step) * step;
  const ticks = [];
  for (let value = min, guard = 0; value <= max + step * 1e-7 && guard < 12; value += step, guard += 1) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return { min, max: max > min ? max : min + step, ticks };
}

function diagramNearestTrendPoint(points, targetMinute) {
  const source = (points || []).filter((point) => Number.isFinite(Number(point?.minute)));
  if (!source.length) return null;
  const target = Number(targetMinute);
  if (!Number.isFinite(target) || target <= Number(source[0].minute)) return source[0];
  if (target >= Number(source[source.length - 1].minute)) return source[source.length - 1];
  let low = 0;
  let high = source.length - 1;
  while (low + 1 < high) {
    const middle = Math.floor((low + high) / 2);
    if (Number(source[middle].minute) <= target) low = middle;
    else high = middle;
  }
  return target - Number(source[low].minute) <= Number(source[high].minute) - target
    ? source[low]
    : source[high];
}

function diagramTrendCursorData(points, targetMinute, unit = "") {
  const point = diagramNearestTrendPoint(points, targetMinute);
  if (!point) return null;
  return { minute: Number(point.minute), time: point.time || "--", value: Number(point.value), unit: String(unit || "") };
}
```

- [ ] **Step 4: Run helper tests and verify they pass**

Run the command from Step 2.

Expected: both targeted tests report `OK`.

- [ ] **Step 5: Commit the pure trend helpers**

```powershell
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js
git commit -m "test: define SVG trend cursor math"
```

### Task 2: Render Y Axis, Unit, and Mouse-Following Cursor

**Files:**
- Modify: `tests/test_svg_diagram_interactions_ui.py`
- Modify: `simu/web/simulator/app.js:3730-3820, 4040-4125`
- Modify: `simu/web/trainee/app.js:2279-2370, 2590-2680`
- Modify: `simu/web/simulator/styles.css:2419-2460`
- Modify: `simu/web/trainee/styles.css:1862-1905`

- [ ] **Step 1: Write failing markup and event-wiring tests**

Assert both scripts contain the new SVG classes and delegated handlers:

```python
def test_trend_chart_renders_axis_unit_and_cursor_layers(self):
    for path in self._scripts():
        script = path.read_text(encoding="utf-8")
        for token in (
            "diagramTrendAxisScale(values, 4)",
            'class="diagram-trend-y-axis"',
            'class="diagram-trend-axis-unit"',
            'data-diagram-trend-cursor-line',
            'data-diagram-trend-cursor-point',
            'data-diagram-trend-cursor-label',
            "function updateDiagramTrendCursor",
            "function hideDiagramTrendCursor",
        ):
            self.assertIn(token, script)

def test_tooltip_delegates_pointer_motion_to_trend_cursor(self):
    for path in self._scripts():
        script = path.read_text(encoding="utf-8")
        tooltip_block = script.split('tooltip.addEventListener("pointerenter"', 1)[1].split("function updateDiagramRealtimeBindings", 1)[0]
        self.assertIn('tooltip.addEventListener("pointermove"', tooltip_block)
        self.assertIn("updateDiagramTrendCursor", tooltip_block)
        self.assertIn("hideDiagramTrendCursor", tooltip_block)
```

Extend the style test with `.diagram-trend-y-axis`, `.diagram-trend-axis-unit`, `.diagram-trend-cursor`, and `.diagram-trend-cursor-label`.

- [ ] **Step 2: Run the targeted tests and verify failure**

Run:

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_svg_diagram_interactions_ui.SvgDiagramInteractionsUiTest.test_trend_chart_renders_axis_unit_and_cursor_layers tests.test_svg_diagram_interactions_ui.SvgDiagramInteractionsUiTest.test_tooltip_delegates_pointer_motion_to_trend_cursor tests.test_svg_diagram_interactions_ui.SvgDiagramInteractionsUiTest.test_styles_include_tooltip_chart_selection_and_zoom_affordances
```

Expected: FAIL because the chart currently has one midpoint gridline and no cursor handlers or styles.

- [ ] **Step 3: Refactor chart rendering around a structured model**

Change `diagramTrendChartHtml` to receive `unit`, compute `axis = diagramTrendAxisScale(values, 4)`, use stable margins such as `{ left: 52, right: 10, top: 16, bottom: 10 }`, and store sampled points with their rendered `x` and `y`:

```javascript
const renderedPoints = sampled.map((point) => ({
  ...point,
  x: plot.left + ((Number(point.minute) - range.startMinute) / minuteSpan) * plotWidth,
  y: plot.top + ((axis.max - Number(point.value)) / Math.max(1e-9, axis.max - axis.min)) * plotHeight,
}));
interaction.trendChart = { width, height, plot, range, points: renderedPoints, unit };
```

Render one gridline and right-aligned tick label for every axis tick, a Y-axis line, one unit label, the polyline, and hidden cursor elements. Pass `unit` and `interaction` from `renderDiagramMetricTooltip`.

- [ ] **Step 4: Implement cursor DOM updates without rebuilding the tooltip**

Add:

```javascript
function hideDiagramTrendCursor(interaction) {
  interaction?.tooltip?.querySelectorAll("[data-diagram-trend-cursor]").forEach((element) => {
    element.setAttribute("visibility", "hidden");
  });
}

function updateDiagramTrendCursor(interaction, chart, event) {
  const model = interaction?.trendChart;
  const rect = chart?.getBoundingClientRect?.();
  if (!model?.points?.length || !rect?.width) return hideDiagramTrendCursor(interaction);
  const viewX = ((Number(event.clientX) - rect.left) / rect.width) * model.width;
  if (viewX < model.plot.left || viewX > model.width - model.plot.right) return hideDiagramTrendCursor(interaction);
  const targetMinute = model.range.startMinute
    + ((viewX - model.plot.left) / (model.width - model.plot.left - model.plot.right))
      * (model.range.endMinute - model.range.startMinute);
  const point = diagramNearestTrendPoint(model.points, targetMinute);
  if (!point) return hideDiagramTrendCursor(interaction);
  // Update line, circle, label group and text nodes; clamp the label to the chart viewBox.
}
```

Wire delegated `pointermove` on `.diagram-trend-chart`, hide on chart/tooltip leave, and hide during tooltip reset. Do not call `refreshDiagramTooltip` from pointer movement.

- [ ] **Step 5: Add the same chart-axis and cursor style selectors to both consoles**

Use small tabular tick labels, a solid Y axis, subtle horizontal gridlines, a high-contrast vertical cursor, and a compact two-line cursor label. Keep the chart width stable and increase its CSS height only enough to prevent axis clipping.

- [ ] **Step 6: Run syntax and targeted tests**

```powershell
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_svg_diagram_interactions_ui
```

Expected: Node checks pass and the complete SVG interaction test module passes.

- [ ] **Step 7: Commit the trend UI**

```powershell
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js simu/web/simulator/styles.css simu/web/trainee/styles.css
git commit -m "feat: add SVG trend axes and cursor"
```

### Task 3: Add Console-Specific Persistent Display Preferences

**Files:**
- Modify: `tests/test_svg_diagram_interactions_ui.py`
- Modify: `simu/web/simulator/app.js:1-20, 2840-2920`
- Modify: `simu/web/trainee/app.js:1-20, 1387-1470`

- [ ] **Step 1: Write failing tests for key separation and normalization**

```python
def test_svg_display_preferences_are_separate_and_normalized(self):
    expected_keys = {
        "simulator": "simulator.svgDisplayPreferences.v1",
        "trainee": "trainee.svgDisplayPreferences.v1",
    }
    body = """
process.stdout.write(JSON.stringify({
  defaults: normalizeDiagramDisplayPreferences(null),
  partial: normalizeDiagramDisplayPreferences({ measurements: false, labels: "bad", flowArrows: true }),
  labels: diagramDisplayPreferenceMenuItems({ measurements: false, labels: true, flowArrows: false }),
}));
"""
    for path in self._scripts():
        script = path.read_text(encoding="utf-8")
        self.assertIn(expected_keys[path.parent.name], script)
        payload = self._run_helpers(script, body)
        self.assertEqual(payload["defaults"], {"measurements": True, "labels": True, "flowArrows": True})
        self.assertEqual(payload["partial"], {"measurements": False, "labels": True, "flowArrows": True})
        self.assertEqual([item["label"] for item in payload["labels"]], ["显示量测", "不显示标识", "显示流动箭头"])
```

- [ ] **Step 2: Run and observe failure**

Run the new test directly. Expected: FAIL because the keys and helper functions do not exist.

- [ ] **Step 3: Add defaults, normalization, load, save, and menu metadata**

Use the exact keys approved in the spec:

```javascript
const DIAGRAM_DISPLAY_PREFERENCES_KEY = "simulator.svgDisplayPreferences.v1";
// trainee uses "trainee.svgDisplayPreferences.v1"
const DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS = Object.freeze({ measurements: true, labels: true, flowArrows: true });

function normalizeDiagramDisplayPreferences(value) {
  const source = value && typeof value === "object" ? value : {};
  return Object.fromEntries(Object.entries(DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS).map(([key, fallback]) => [
    key,
    typeof source[key] === "boolean" ? source[key] : fallback,
  ]));
}

function diagramDisplayPreferenceMenuItems(preferences) {
  const value = normalizeDiagramDisplayPreferences(preferences);
  return [
    { key: "measurements", label: value.measurements ? "不显示量测" : "显示量测" },
    { key: "labels", label: value.labels ? "不显示标识" : "显示标识" },
    { key: "flowArrows", label: value.flowArrows ? "不显示流动箭头" : "显示流动箭头" },
  ];
}
```

`loadDiagramDisplayPreferences` catches JSON and storage errors. `saveDiagramDisplayPreferences` returns normalized values even when `localStorage.setItem` throws. Initialize one mutable module-level preference object per console.

- [ ] **Step 4: Run helper test and syntax checks**

Expected: preference test and Node checks pass.

- [ ] **Step 5: Commit preference primitives**

```powershell
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js
git commit -m "feat: persist SVG display preferences per console"
```

### Task 4: Add Blank-Space Context Menu and Measurement/Label Layers

**Files:**
- Modify: `tests/test_svg_diagram_interactions_ui.py`
- Modify: `simu/web/simulator/app.js:3422-4140`
- Modify: `simu/web/trainee/app.js:1971-2685`
- Modify: `simu/web/simulator/styles.css:2210-2440`
- Modify: `simu/web/trainee/styles.css:1655-1875`

- [ ] **Step 1: Write failing tests for blank activation, viewport clamping, layer wiring, and generated IDs**

Add pure helper tests:

```javascript
diagramContextMenuAction("", true)        // "open"
diagramContextMenuAction("device", true)  // "ignore"
diagramContextMenuAction("metric", true)  // "ignore"
diagramContextMenuAction("", false)       // "ignore"
diagramFloatingPosition({ x: 790, y: 590 }, { width: 180, height: 140 }, { width: 800, height: 600 }, 8)
```

Assert script wiring contains `contextmenu`, `data-diagram-display-toggle`, `prepareDiagramDisplayLayers`, `applyDiagramDisplayPreferences`, `.diagram-device-label-id`, `window.addEventListener("storage"`, and both key-specific constants. Assert styles contain the three root hidden-state selectors and context-menu styles.

- [ ] **Step 2: Run targeted tests and verify failure**

Expected: FAIL because no context menu or display layers exist.

- [ ] **Step 3: Implement pure context-menu helpers**

```javascript
function diagramContextMenuAction(targetKind = "", insideCanvas = false) {
  return insideCanvas && !String(targetKind || "").trim() ? "open" : "ignore";
}

function diagramFloatingPosition(anchor, size, viewport, padding = 8) {
  return {
    left: Math.max(padding, Math.min(Number(anchor.x), Number(viewport.width) - Number(size.width) - padding)),
    top: Math.max(padding, Math.min(Number(anchor.y), Number(viewport.height) - Number(size.height) - padding)),
  };
}
```

- [ ] **Step 4: Build runtime measurement and label layers**

Add `prepareDiagramDisplayLayers(container)`:

1. Mark each `[dev]` group containing `[mt]` as `.diagram-measurement-layer`.
2. Mark standalone named measurement text or its nearest `text` as `.diagram-measurement-layer`.
3. Mark `text[id^="label_"][dev-id]` as `.diagram-device-label-name`.
4. Remove stale `.diagram-device-label-id[data-diagram-runtime-label]` elements.
5. Create one SVG `<text>` sibling per name with the same `x`, `text-anchor`, `transform`, and `dev-id`, a downward offset derived from the source font size, class `.diagram-device-label-id`, and text content equal to `dev-id`.

Add `applyDiagramDisplayPreferences(container, preferences)` to toggle root SVG classes:

```text
is-diagram-measurements-hidden
is-diagram-labels-hidden
is-diagram-flow-arrows-hidden
```

Hiding measurements must not remove DOM elements or stop `setDiagramElementValue` calls.

- [ ] **Step 5: Build and wire the body-level context menu**

Extend interaction state with `contextMenu`. Create one fixed-position menu with three buttons. On canvas `contextmenu`, resolve the genuine SVG target with `diagramInteractionEventTarget`, classify semantic devices/metrics/arrows, call `diagramContextMenuAction`, prevent the browser menu only for blank SVG space, and position the menu at the pointer with `diagramFloatingPosition`.

Button clicks toggle one preference, call save/apply immediately, then close. Close on outside pointerdown, `Escape`, model reset, and page/model switch.

- [ ] **Step 6: Synchronize same-console tabs**

Add a single `storage` listener per app. When `event.key` matches that console's preference key, normalize `event.newValue`, update the module-level preferences, and apply them to `#modelDiagramCanvas`. Ignore the other console's key.

- [ ] **Step 7: Add styles**

Add a compact fixed menu with 6px or smaller corner radius, hover/focus states, and no nested card styling. Add selectors that hide measurement and label layers. Style generated IDs smaller and muted while preserving device click selection.

- [ ] **Step 8: Run tests and commit**

```powershell
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_svg_diagram_interactions_ui
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js simu/web/simulator/styles.css simu/web/trainee/styles.css
git commit -m "feat: add persistent SVG display menu"
```

### Task 5: Add Signed and Magnitude-Scaled Flow Arrows

**Files:**
- Modify: `tests/test_svg_diagram_interactions_ui.py`
- Modify: `simu/web/simulator/app.js:3050-3570, 4127-4170`
- Modify: `simu/web/trainee/app.js:1387-1585, 1756-1810, 2085-2120, 2685-2725`
- Modify: `simu/web/simulator/styles.css`
- Modify: `simu/web/trainee/styles.css`

- [ ] **Step 1: Write failing tests for direction, size, threshold, and suppression**

```python
def test_flow_arrow_math_uses_signed_power_and_clamped_sqrt_size(self):
    body = """
process.stdout.write(JSON.stringify({
  positive: diagramFlowArrowDirection(12, 1),
  negative: diagramFlowArrowDirection(-12, 1),
  reversed: diagramFlowArrowDirection(12, -1),
  zero: diagramFlowArrowSize(0, 100),
  quarter: diagramFlowArrowSize(25, 100),
  full: diagramFlowArrowSize(100, 100),
  over: diagramFlowArrowSize(400, 100),
  visible: diagramFlowArrowVisibility({ power: 10, referencePower: 100, valid: true, offline: false }),
  nearZero: diagramFlowArrowVisibility({ power: 0.05, referencePower: 100, valid: true, offline: false }),
  offline: diagramFlowArrowVisibility({ power: 10, referencePower: 100, valid: true, offline: true }),
}));
"""
```

Expected assertions: directions `1`, `-1`, `-1`; sizes `6`, `11`, `16`, `16`; visibility `true`, `false`, `false`.

Also assert both scripts contain `.routable-line-device-glyph`, `source-dev-id`, `target-dev-id`, `createDiagramFlowArrow`, `compileDiagramFlowArrows`, `updateDiagramFlowArrows`, `animateMotion`, and no JavaScript animation interval.

- [ ] **Step 2: Run the tests and verify failure**

Expected: FAIL because flow-arrow helpers and runtime SVG generation do not exist.

- [ ] **Step 3: Implement pure flow helpers**

```javascript
function diagramFlowArrowDirection(power, orientation = 1) {
  const value = Number(power) * (Number(orientation) < 0 ? -1 : 1);
  return value < 0 ? -1 : value > 0 ? 1 : 0;
}

function diagramFlowArrowSize(power, referencePower) {
  const reference = Math.abs(Number(referencePower));
  const magnitude = Math.abs(Number(power));
  if (!Number.isFinite(magnitude) || magnitude <= 0) return 6;
  const ratio = reference > 0 ? Math.max(0, Math.min(1, magnitude / reference)) : 1;
  return 6 + 10 * Math.sqrt(ratio);
}

function diagramFlowArrowVisibility({ power, referencePower, valid = true, offline = false } = {}) {
  const magnitude = Math.abs(Number(power));
  if (!valid || offline || !Number.isFinite(magnitude)) return false;
  const reference = Math.abs(Number(referencePower));
  const threshold = reference > 0 ? reference * 0.001 : 0;
  return magnitude > threshold;
}
```

- [ ] **Step 4: Compile stable branch and explicit-edge geometry**

Add `compileDiagramFlowArrows(container)` that first removes runtime arrows, then creates records for:

1. `<use>` branch/zero-branch devices whose referenced symbol contains `.routable-line-device-glyph path`. Copy the route `d`, apply the symbol `viewBox` to `<use>` rectangle transform, and keep the record bound to that device's `activePower` measurement (`P_FROM` is already first in the existing mapping).
2. Explicit `path` or `line` elements with `source-dev-id` and `target-dev-id` only when one endpoint has a unique one-terminal `P_GEN` or `P_LOAD` binding. Derive orientation so positive generation points away from a generator and positive load points toward a load. Skip converter and ambiguous two-terminal endpoint bindings.

Each runtime record contains an invisible guide path and one `<g>` arrow with a centered `<polygon>` and SVG `<animateMotion repeatCount="indefinite">`. Insert the runtime group beside the source geometry so it inherits parent transforms. Use no `requestAnimationFrame`, interval, or per-arrow JavaScript timer.

- [ ] **Step 5: Resolve reference power and update arrows per snapshot**

Add `diagramFlowReferencePower` with this order:

1. Positive `rated_capacity`, `rated_power`, `p_max`, `max_power`, `max_charge_power`, or `max_discharge_power` from `diagramDeviceData(container, device, snapshot).raw`.
2. A per-model, per-device-type peak-hold fallback stored in interaction state.

`updateDiagramFlowArrows(container, snapshot, measurementMaps)` resolves the current row, checks `valid`, obtains the existing device operating state, suppresses retired/dead-island records, applies near-zero suppression, updates polygon points for `6..16`, updates `animateMotion` direction with `keyPoints="0;1"` or `"1;0"`, and leaves the original SVG untouched.

- [ ] **Step 6: Integrate with runtime binding and reset**

Compile arrows once after a new SVG is inserted. Call `updateDiagramFlowArrows` from `updateDiagramRealtimeBindings` using the measurement maps already created there. Reset arrow records and peak references only when the model/SVG key changes. Applying a display preference must only hide/show existing arrows.

- [ ] **Step 7: Add arrow styles and run tests**

Use `pointer-events: none`, a restrained high-contrast fill, and `[hidden] { display: none; }`. Ensure the root hidden preference overrides individual visibility.

Run:

```powershell
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_svg_diagram_interactions_ui
```

Expected: all pass.

- [ ] **Step 8: Commit flow arrows**

```powershell
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js simu/web/simulator/styles.css simu/web/trainee/styles.css
git commit -m "feat: animate signed SVG power flow"
```

### Task 6: Complete Lifecycle and Regression Coverage

**Files:**
- Modify: `tests/test_svg_diagram_interactions_ui.py`
- Modify: `simu/web/simulator/app.js`
- Modify: `simu/web/trainee/app.js`

- [ ] **Step 1: Add failing lifecycle assertions**

Assert `resetDiagramInteractions` closes/removes the context menu, hides the trend cursor, removes runtime labels/arrows, clears arrow peak state, and leaves preference values intact. Assert `renderModelDiagramPage` prepares layers/arrows only when `diagramKey` changes and applies preferences after every render.

- [ ] **Step 2: Run the lifecycle tests and verify failure**

Expected: FAIL until reset/render integration is complete.

- [ ] **Step 3: Finish reset and render integration**

On model/SVG replacement:

```text
close menu
hide tooltip/cursor
remove generated IDs and flow arrows
clear geometry/binding/peak caches
preserve module-level display preferences
sanitize and insert SVG
prepare measurement/name/ID layers
compile flow geometry
apply current preferences
initialize delegated events
update current realtime values and arrows
```

On ordinary snapshots, update values, device states, tooltip content, and arrows without replacing the SVG root or resetting the viewport.

- [ ] **Step 4: Run focused SVG and related model-diagram tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_svg_diagram_interactions_ui tests.test_svg_realtime_measurement_binding_ui tests.test_model_diagram_ui tests.test_svg_device_operating_state
```

Expected: all pass.

- [ ] **Step 5: Commit lifecycle completion**

```powershell
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js
git commit -m "fix: reset SVG runtime interaction layers"
```

### Task 7: Full Verification and Browser Acceptance

**Files:**
- Verify: `simu/web/simulator/app.js`
- Verify: `simu/web/trainee/app.js`
- Verify: `simu/web/simulator/styles.css`
- Verify: `simu/web/trainee/styles.css`
- Verify: `models/simulator/source/秦岭站/diagram.svg`
- Verify: current simulator and trainee model diagrams

- [ ] **Step 1: Run static checks**

```powershell
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
git diff --check
```

Expected: all exit `0`.

- [ ] **Step 2: Run the complete test suite with the local `simu` package preloaded**

The power-flow kernel adds another `simu` package path while importing `simu_loop`; preload this repository's package before discovery:

```powershell
D:\anaconda3\python.exe -X utf8 -c "import simu, unittest; suite=unittest.defaultTestLoader.discover('tests', top_level_dir='.'); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Expected: every test passes.

- [ ] **Step 3: Restart simulator and trainee WEB services**

Stop only listeners whose command line contains `simu.server` and the expected port, then start hidden processes:

```powershell
D:\anaconda3\python.exe -X utf8 -u -m simu.server --role simulator --host 127.0.0.1 --port 8710 --sim-dir D:\codex\power_simu_web
D:\anaconda3\python.exe -X utf8 -u -m simu.server --role trainee --host 127.0.0.1 --port 8720 --sim-dir D:\codex\power_simu_web
```

- [ ] **Step 4: Browser-verify simulator**

At `http://127.0.0.1:8710/diagram`:

1. Hover a dynamic value and verify hour/day charts show a Y axis, readable ticks, one unit, and a cursor that snaps to points with time/value/unit.
2. Verify the outer tooltip does not move while the cursor follows the pointer and the cursor disappears on chart leave.
3. Right-click SVG blank space, toggle all three display options, and verify right-clicking devices/measurements does not open the custom menu.
4. Verify generated device IDs appear with names and both hide together.
5. Run or step a model with active-power measurements and verify signed direction, magnitude-scaled size, and retired/dead-island/near-zero suppression.
6. Zoom, pan, and double-click fit; labels and arrows must remain aligned.
7. Refresh and switch models; preferences remain, old runtime elements do not.

- [ ] **Step 5: Browser-verify trainee**

Repeat at `http://127.0.0.1:8720/diagram`. Confirm trainee device double-click command behavior still works and all browser requests remain on the trainee origin. Set different display options than the simulator, refresh both, and verify each console restores its own values.

- [ ] **Step 6: Verify multiple tabs and narrow viewport**

Open two tabs for one console, toggle a preference, and verify the second tab updates through `storage`. Resize to a narrow viewport and verify chart labels, cursor label, and context menu stay inside their containers/viewport without horizontal page overflow.

- [ ] **Step 7: Final commit if verification required corrections**

If browser verification found and fixed an issue, rerun Steps 1 and 2, then commit only the correction files:

```powershell
git add tests/test_svg_diagram_interactions_ui.py simu/web/simulator/app.js simu/web/trainee/app.js simu/web/simulator/styles.css simu/web/trainee/styles.css
git commit -m "fix: polish SVG display interactions"
```

If no correction was needed, do not create an empty commit.
