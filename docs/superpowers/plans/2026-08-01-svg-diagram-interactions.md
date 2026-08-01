# SVG Diagram Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add device parameter tooltips, persistent click selection, hour/day realtime measurement trend tooltips, and pointer-centered wheel zoom to simulator and trainee SVG diagram pages.

**Architecture:** Extend the existing semantic SVG binding cache with a reusable device index and per-container interaction state. Reuse the current snapshot, model definitions, live devices, and `measurementTraceHistory`; create one body-level tooltip and modify only the inline SVG `viewBox`, so no backend API, additional polling, or SVG replacement is required.

**Tech Stack:** Vanilla JavaScript, inline SVG and SVG coordinate APIs, HTML/CSS tooltips, Python `unittest`, Node.js helper harnesses, existing simulator and trainee snapshot/history flows.

---

## File Structure

- Create `tests/test_svg_diagram_interactions_ui.py` for shared pure behavior and source integration tests.
- Modify `simu/web/simulator/app.js` for the simulator device index, tooltips, selection, trend data, and zoom.
- Modify `simu/web/trainee/app.js` with the same UI behavior using only trainee-local state.
- Modify `simu/web/simulator/styles.css` and `simu/web/trainee/styles.css` for hover, selection, tooltip, tabs, and chart styling.
- Keep both `index.html` files unchanged; JavaScript creates the single reusable tooltip lazily.

### Task 1: Add Failing Pure and Integration Tests

**Files:**
- Create: `tests/test_svg_diagram_interactions_ui.py`
- Read: `simu/web/simulator/app.js`
- Read: `simu/web/trainee/app.js`
- Read: `simu/web/simulator/styles.css`
- Read: `simu/web/trainee/styles.css`

- [ ] **Step 1: Add a shared Node helper harness**

Extract source from `const DIAGRAM_TREND_WINDOWS` through the line before `function addDiagramControlAliases`, execute it with `node -e`, and parse JSON output. Run every behavior assertion against both application scripts.

```python
def _helper_source(self, script: str) -> str:
    if "const DIAGRAM_TREND_WINDOWS" not in script:
        self.fail("diagram interaction helpers are missing")
    return "const DIAGRAM_TREND_WINDOWS" + script.split(
        "const DIAGRAM_TREND_WINDOWS", 1
    )[1].split("function addDiagramControlAliases", 1)[0]
```

- [ ] **Step 2: Add hour/day window tests**

Use points at minutes `0, 30, 60, 1380, 1440`. Assert `diagramTrendWindowPoints(points, "hour", 1440)` returns only minutes `1380, 1440`, the day page returns all five points, and `diagramTrendWindowMinutes` returns `60` and `1440`.

- [ ] **Step 3: Add adaptive sampling and SOC tests**

Assert `diagramSampleTrendPoints` keeps the first/last point and bucket extrema including positive and negative spikes. Assert `diagramTrendDisplayValue(1.08, {meas_type: "SOC"}, "level")` returns `108` and `-0.03` returns `-3`.

- [ ] **Step 4: Add zoom geometry tests**

For original `{x:0,y:0,width:1000,height:500}`, focus `{x:250,y:125}`, and factor `0.5`, assert `diagramZoomViewBox` returns `{x:125,y:62.5,width:500,height:250}`. Assert zoom cannot exceed `8x` and zoom-out resets to the original bounds.

- [ ] **Step 5: Add source and CSS assertions**

Assert both scripts contain:

```text
compileDiagramDeviceIndex
initDiagramInteractions
setDiagramSelectedDevice
data-diagram-trend-period
addEventListener("wheel"
{ passive: false }
refreshDiagramTooltip
resetDiagramInteractions
```

Assert both stylesheets contain `.diagram-tooltip`, `.diagram-trend-tabs`, `.diagram-trend-chart`, `.is-diagram-selected`, and SVG hover/zoom cursor rules.

- [ ] **Step 6: Verify RED**

Run:

```powershell
python -m unittest tests.test_svg_diagram_interactions_ui
```

Expected: FAIL because the new helper, tooltip, selection, zoom, and style contracts are absent.

### Task 2: Implement Trend and Zoom Pure Helpers

**Files:**
- Modify: `simu/web/simulator/app.js` near `DIAGRAM_METRIC_MEASUREMENT_TYPES`
- Modify: `simu/web/trainee/app.js` at the matching location
- Test: `tests/test_svg_diagram_interactions_ui.py`

- [ ] **Step 1: Add constants and rolling-window helpers**

```javascript
const DIAGRAM_TREND_WINDOWS = Object.freeze({ hour: 60, day: 24 * 60 });
const DIAGRAM_MAX_ZOOM = 8;

function diagramTrendWindowMinutes(period = "hour") {
  return DIAGRAM_TREND_WINDOWS[period] || DIAGRAM_TREND_WINDOWS.hour;
}

function diagramTrendWindowPoints(points, period = "hour", endMinute = null) {
  const valid = (points || []).filter((point) => (
    Number.isFinite(Number(point?.minute)) && Number.isFinite(Number(point?.value))
  ));
  if (!valid.length) return [];
  const end = Number.isFinite(Number(endMinute))
    ? Number(endMinute)
    : Number(valid[valid.length - 1].minute);
  const start = end - diagramTrendWindowMinutes(period);
  return valid.filter((point) => Number(point.minute) >= start && Number(point.minute) <= end);
}
```

- [ ] **Step 2: Add extrema-preserving sampling**

Implement `diagramSampleTrendPoints(points, targetCount)` with at most `floor(targetCount / 4)` ordered buckets. For each bucket retain its first, minimum, maximum, and last source point; de-duplicate by original index and return chronological order. Return the original array when it already fits.

- [ ] **Step 3: Add SOC-aware value conversion**

Implement `diagramTrendDisplayValue` by wrapping the value in a row and passing it through the existing `diagramDisplayRow`; return `null` for non-finite values.

- [ ] **Step 4: Add pure bounded viewBox zoom**

Implement `diagramZoomViewBox(current, original, focus, factor)`. Clamp width and height between original size and `original / DIAGRAM_MAX_ZOOM`, keep the focus point at the same relative location, and clamp `x/y` within the original rectangle.

- [ ] **Step 5: Run helper tests**

```powershell
python -m unittest tests.test_svg_diagram_interactions_ui
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
```

Expected: pure helper cases pass; DOM/CSS integration cases remain red.

### Task 3: Add Cached Device Identity and Click Selection

**Files:**
- Modify: `simu/web/simulator/app.js` around `compileDiagramMetricBindings`
- Modify: `simu/web/trainee/app.js` around `compileDiagramMetricBindings`
- Modify: both stylesheets near `.model-diagram-svg`
- Test: `tests/test_svg_diagram_interactions_ui.py`

- [ ] **Step 1: Extract and cache the SVG device index**

Create `compileDiagramDeviceIndex(container)` and `diagramDeviceIndex(container)`. Records contain `{devId, devType, devName}`. Refactor `compileDiagramMetricBindings` to use this cache and include `devId` in every metric binding.

- [ ] **Step 2: Add selection state and class synchronization**

Store `selectedDevId` in the per-container interaction state. `setDiagramSelectedDevice(container, devId)` must remove `.is-diagram-selected` from old elements, then add it to all elements whose `dev-id` or `dev` equals the selected id. Use attribute filtering in JavaScript rather than interpolating an unescaped id into a selector.

- [ ] **Step 3: Delegate clicks**

Clicking a metric uses its owning `[dev]`; clicking a device or label uses `[dev-id]`; clicking the SVG background clears selection. Selection must survive text refresh and viewBox zoom, but `resetDiagramInteractions` must clear it before a new SVG is inserted.

- [ ] **Step 4: Add selection styling**

Use `filter: drop-shadow(...)`, a stable accent color, and stronger bound text weight. Do not alter SVG dimensions, transforms, or stroke widths in a way that shifts layout.

- [ ] **Step 5: Run targeted tests**

```powershell
python -m unittest tests.test_svg_diagram_interactions_ui tests.test_svg_realtime_measurement_binding_ui
```

Expected: selection and existing binding contracts pass.

### Task 4: Add Device and Measurement Tooltips

**Files:**
- Modify: both `app.js` files around diagram rendering
- Modify: both `styles.css` files around diagram styling
- Test: `tests/test_svg_diagram_interactions_ui.py`

- [ ] **Step 1: Build current device data**

Match the SVG device against `definedModelDevices(snapshot)` and `snapshot.devices` by normalized type and exact name. Build escaped rows for identity, `idx`, run/status/mode, `set_values`, non-duplicate `raw` fields, and current measurements with SCADA priority and realtime fallback.

- [ ] **Step 2: Normalize metric history**

Resolve the active row with `diagramMetricBindingValue`, derive its existing `measurementKey(row)`, and convert simulator history `{scada, real}` or trainee history `{value}` into common `{minute,time,value}` points. Apply SOC conversion only through `diagramTrendDisplayValue`.

- [ ] **Step 3: Render the hour/day chart**

Render two tab buttons and an inline chart with a fixed `viewBox`. Use the rolling-window and adaptive-sampling helpers, show signed values, start/end simulation times, minimum, maximum, and latest value. For equal values render a centered horizontal line; for empty pages show `当前分页暂无历史曲线`.

- [ ] **Step 4: Create one reusable tooltip and event delegation**

`initDiagramInteractions(container)` lazily appends one tooltip to `document.body` and binds container `pointermove/pointerleave`, tooltip `pointerenter/pointerleave/click`, and container `click` once. Metric targets take priority over device targets. Device tips ignore pointer input; metric tips remain open while the pointer moves into the hour/day tabs.

- [ ] **Step 5: Refresh and clear tooltip state correctly**

Call `refreshDiagramTooltip` at the end of `updateDiagramRealtimeBindings`. Call `resetDiagramInteractions` when no diagram exists and before replacing SVG HTML. Hide the tooltip whenever the active page is not `diagram`.

- [ ] **Step 6: Add tooltip CSS**

Add viewport-fixed positioning, compact key/value rows, a scrollable device parameter body, hour/day segmented tabs, fixed chart height, statistics, and viewport-safe maximum dimensions. Use existing color variables and radius no greater than `8px`.

- [ ] **Step 7: Run targeted tests and syntax checks**

```powershell
python -m unittest tests.test_svg_diagram_interactions_ui tests.test_svg_realtime_measurement_binding_ui tests.test_model_diagram_ui
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
```

Expected: all interaction and existing diagram tests pass.

### Task 5: Add Pointer-Centered Wheel Zoom

**Files:**
- Modify: both `app.js` files
- Modify: both `styles.css` files
- Test: `tests/test_svg_diagram_interactions_ui.py`

- [ ] **Step 1: Cache valid original/current viewBoxes**

Create `diagramViewportCache`. Parse the active SVG `viewBox`; reject missing, non-finite, or non-positive dimensions.

- [ ] **Step 2: Transform the pointer into SVG coordinates**

Use `svg.createSVGPoint()` and `svg.getScreenCTM().inverse()` with `event.clientX/clientY`. If conversion is unavailable, do not prevent normal page scrolling.

- [ ] **Step 3: Apply bounded zoom**

Use factor `0.88` for zoom-in and `1.12` for zoom-out. Call `diagramZoomViewBox`, set the resulting SVG `viewBox`, update the cache, and call `preventDefault()` only after a valid application. Register the listener with `{ passive: false }`.

- [ ] **Step 4: Verify persistence and reset rules**

Realtime binding and tooltip refreshes must preserve the current viewBox and selected device. Replacing the SVG must restore `1x` and clear selection.

- [ ] **Step 5: Run interaction tests**

```powershell
python -m unittest tests.test_svg_diagram_interactions_ui
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
```

Expected: all zoom tests pass.

### Task 6: Full Regression and Browser Verification

**Files:**
- Verify all modified application, style, and test files.

- [ ] **Step 1: Run targeted and complete suites**

```powershell
python -m unittest tests.test_svg_diagram_interactions_ui tests.test_svg_realtime_measurement_binding_ui tests.test_model_diagram_ui tests.test_measurement_incremental_refresh_ui tests.test_active_page_rendering_ui tests.test_snapshot_performance
python -m unittest
```

Expected: zero failures.

- [ ] **Step 2: Browser-verify simulator**

At `http://127.0.0.1:8710/diagram`, verify device parameter hover, dynamic-value hour/day tabs, click selection and blank-click clearing, pointer-centered `1x` to `8x` zoom, persistence across realtime refresh, reset after model switch, unchanged SVG root during refresh, and no console errors.

- [ ] **Step 3: Browser-verify trainee**

At `http://127.0.0.1:8720/diagram`, verify the same behaviors and confirm requests remain on the trainee service origin.

- [ ] **Step 4: Run hygiene checks**

```powershell
git diff --check -- simu/web/simulator/app.js simu/web/trainee/app.js simu/web/simulator/styles.css simu/web/trainee/styles.css tests/test_svg_realtime_measurement_binding_ui.py tests/test_svg_diagram_interactions_ui.py
git status --short --branch
```

Expected: no whitespace errors and only intentional implementation/test changes. Do not push, restart services, or create an implementation commit unless explicitly requested.
