# Converter SOC Power Limit Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a model-scoped, persistent ten-band SOC configuration that limits automatic ACDC converter export power and can be edited from a trainee renewable-control dialog.

**Architecture:** Extend `RenewableControlSettings` with a validated tuple of ten ratios, use the active settings during converter target calculation, and persist the tuple through the existing trainee renewable-control manager. The trainee page edits a fixed ten-row dialog and saves through the existing `update_settings` action, so all pages connected to one model share the same backend state.

**Tech Stack:** Python dataclasses and `unittest`; vanilla HTML, CSS, and JavaScript; existing `/api/trainee/renewable-control` endpoint; native HTML `dialog`.

**Git note:** The worktree already contains related uncommitted control-strategy changes. Do not commit or push until the user explicitly requests Git operations.

---

### Task 1: Backend setting contract

**Files:**
- Modify: `simu/renewable_control.py`
- Test: `tests/test_trainee_renewable_backend_control.py`

- [ ] **Step 1: Write failing default and validation tests**

Assert the default payload contains:

```python
"converterSocPowerLimits": [0.0, 0.0, 0.2, 0.4, 0.4, 0.5, 0.6, 0.8, 0.8, 1.0]
```

Assert `ValueError` for a list with nine items, a value such as `0.25`, an out-of-range value, and a decreasing pair.

- [ ] **Step 2: Run those tests and confirm they fail because the field does not exist**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest.test_converter_soc_power_limits_default_and_payload tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest.test_converter_soc_power_limits_reject_invalid_configurations
```

- [ ] **Step 3: Implement the setting and strict validator**

Define:

```python
DEFAULT_CONVERTER_SOC_POWER_LIMITS = (
    0.0, 0.0, 0.2, 0.4, 0.4, 0.5, 0.6, 0.8, 0.8, 1.0,
)
```

Add `converter_soc_power_limits: Tuple[float, ...]` to `RenewableControlSettings`. Accept `converterSocPowerLimits` and `converter_soc_power_limits`, require exactly ten finite values in `0.1` increments, require `[0, 1]`, require monotonic non-decrease, store a tuple, and expose a copied JSON list from `payload()`.

- [ ] **Step 4: Run the focused tests and confirm they pass**

### Task 2: Settings-driven planning and regression cleanup

**Files:**
- Modify: `simu/renewable_control.py`
- Modify: `tests/test_trainee_renewable_backend_control.py`

- [ ] **Step 1: Add a failing custom-schedule planner test**

Use `(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)` and assert SOC `0.35` selects ratio `0.3`, a 15 kW limit for a 50 kW converter, and target range `[-15, 0]`.

- [ ] **Step 2: Run the test and confirm the hard-coded mapping fails it**

- [ ] **Step 3: Replace the hard-coded lookup**

Implement:

```python
def _converter_soc_limit_ratio(
    soc: Optional[float],
    limits: Sequence[float],
) -> Tuple[float, Optional[int]]:
```

Use `floor(soc * 10)`, clamped to `0..9`, so exact 10% boundaries enter the next band. Return the first band below 0%, the last band at or above 100%, and `(1.0, None)` for unknown SOC so existing quality checks remain authoritative.

Expose `converterSocBandIndex`, `converterSocBandLowerPercent`, and `converterSocBandUpperPercent`, and include the matched interval in decision logs.

- [ ] **Step 4: Finish obsolete test updates**

Use zero or negative converter realtime values for ordinary hold/step tests, replace old positive charging expectations with nonpositive targets, and set SOC to `0.95` where a test intends to exercise full original converter capacity rather than SOC derating.

- [ ] **Step 5: Run the complete backend-control module**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control
```

Expected: all tests pass.

### Task 3: Persistence and shared state

**Files:**
- Modify: `tests/test_trainee_renewable_backend_control.py`
- Modify if a failing test requires it: `simu/renewable_control.py`

- [ ] **Step 1: Extend the reload test to save and reload a non-default schedule**
- [ ] **Step 2: Add an atomicity test proving invalid input changes neither memory nor `renewable_control.json`**
- [ ] **Step 3: Extend the two-client HTTP test so the second client reads the first client's saved schedule**
- [ ] **Step 4: Add two-model isolation coverage with different valid schedules**
- [ ] **Step 5: Run the focused API tests and then the full backend-control module**

### Task 4: Dialog markup and styling

**Files:**
- Modify: `simu/web/trainee/index.html`
- Modify: `simu/web/trainee/styles.css`
- Create: `tests/test_trainee_renewable_soc_limit_ui.py`

- [ ] **Step 1: Write failing static UI tests**

Assert the page contains `converterSocLimitButton`, `converterSocLimitDialog`, `converterSocLimitRows`, `converterSocLimitSave`, and `converterSocLimitMessage`. Assert CSS provides a bounded dialog, an internally scrollable rows container, and stable two-column rows.

- [ ] **Step 2: Run the UI test and confirm it fails**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_soc_limit_ui
```

- [ ] **Step 3: Add the button and native dialog using existing trainee dialog patterns**
- [ ] **Step 4: Add responsive CSS with internal vertical scrolling and a narrow-screen fallback**
- [ ] **Step 5: Run the static UI test and confirm markup/styles pass**

### Task 5: Frontend state, validation, and save flow

**Files:**
- Modify: `simu/web/trainee/app.js`
- Modify: `tests/test_trainee_renewable_soc_limit_ui.py`

- [ ] **Step 1: Add failing source-contract tests**

Assert JavaScript defines the default ten-value schedule, applies `settings.converterSocPowerLimits`, renders ten rows with options `0..100` in 10% steps, validates monotonic order, and calls `runRenewableControlAction("update_settings", ...)` with the complete list.

- [ ] **Step 2: Run the UI test and confirm the JavaScript assertions fail**
- [ ] **Step 3: Add copied array state and backend synchronization per active model**
- [ ] **Step 4: Implement open, render, validate, save, cancel, close-button, and backdrop-click behavior**
- [ ] **Step 5: Disable save while a backend action is active and close only after a successful response**
- [ ] **Step 6: Run UI and related renewable-control tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_soc_limit_ui tests.test_trainee_renewable_loop_mode_ui tests.test_trainee_renewable_diesel_metrics_ui tests.test_trainee_renewable_storage_acdc_metrics_ui tests.test_trainee_renewable_vertical_layout_ui
```

### Task 6: Final verification

**Files:**
- Verify: all modified files

- [ ] **Step 1: Compile and check whitespace**

```powershell
D:\anaconda3\python.exe -X utf8 -m py_compile simu\renewable_control.py
git diff --check
```

- [ ] **Step 2: Run `D:\anaconda3\python.exe -X utf8 -m unittest discover -s tests`**
- [ ] **Step 3: Restart the trainee service and verify `http://127.0.0.1:8720/renewable` returns HTTP 200**
- [ ] **Step 4: Verify ten rows, monotonic rejection, successful persistence, refresh reload, narrow layout, and internal scrolling in the browser**
- [ ] **Step 5: Inspect the final diff and report results without staging, committing, or pushing**
