const apiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const OVERVIEW_BOTTOM_HEIGHT_KEY = "polarOverviewBottomHeight";
const OVERVIEW_BOTTOM_DEFAULT_HEIGHT = 156;
const OVERVIEW_BOTTOM_MIN_HEIGHT = 96;
const OVERVIEW_BOTTOM_MAX_HEIGHT = 380;
const state = {
  snapshot: null,
  models: [],
  activeModelId: localStorage.getItem("polarSimulatorModelId") || "",
  deviceFaults: [],
  measurementFaults: [],
  modes: [],
  weatherPoints: [],
  loadPoints: [],
  loadPointsByName: {},
  curveSeries: {},
  curveSeriesByMode: {},
  curveMode: localStorage.getItem("polarSimulatorCurveMode") || "year",
  curvesLoadedModelId: "",
  activeCurveKey: "wind_speed_mps",
  selectedCurveKeys: ["wind_speed_mps"],
  hiddenCurveKeys: [],
  curveEditKey: "",
  isCurveDragging: false,
  isCurveTreePointerDown: false,
  isCurveTreeMultiSelecting: false,
  curveTreeDragStartKeys: [],
  curveTreeDragKeys: [],
  curveTreeDragStartButton: null,
  suppressNextCurveTreeClick: false,
  curveCursor: { visible: false, x: 0, y: 0, index: 0 },
  curveLegendHitBoxes: [],
  settingsLoaded: false,
  activeFaultTab: "devices",
  faultDeviceFilter: { dev_type: "all", dev_name: "" },
  faultMeasurementFilter: { dev_type: "all", dev_name: "", key: "" },
  modelDeviceFilter: { dev_type: "all", dev_name: "" },
  activeModelParamTab: "",
  runtimeDeviceFilter: { dev_type: "all", dev_name: "" },
  activeRuntimeCommandTab: "remote_control",
  selectedRuntimeCommandKey: "",
  selectedRuntimeCommandLabel: "",
  chartSeriesHidden: {},
  chartSeriesSelected: {},
  chartCursors: {},
  chartSeriesHitData: {},
  chartPlotInfo: {},
  runtimeTraceHistory: [],
  runtimeTraceWindowMinutes: 60,
  lastRuntimeTraceKey: "",
  measurementCompareFilter: { dev_type: "all", dev_name: "" },
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
  traceRunId: null,
  modeFilter: { dev_type: "all", dev_name: "" },
  collapsedDeviceTreeGroups: {},
  runtimeLogs: [],
  runtimeLogTypeFilter: "all",
  runtimeLogPage: 1,
  runtimeLogPageSize: 20,
  runtimeLogSeq: 0,
  lastRuntimeLogKey: "",
  systemParameters: { clock_speed: 1, compute_interval_seconds: 1 },
  systemParametersDirty: false,
  systemParametersSaving: false,
  overviewBottomHeight: overviewInitialBottomHeight(),
  overviewBottomSplitDrag: null,
};

const $ = (id) => document.getElementById(id);
const MODE_OPTIONS = ["PQ", "PV", "PH", "V"];

function overviewInitialBottomHeight() {
  const storedHeight = Number(localStorage.getItem(OVERVIEW_BOTTOM_HEIGHT_KEY));
  if (!Number.isFinite(storedHeight) || storedHeight <= 0) return OVERVIEW_BOTTOM_DEFAULT_HEIGHT;
  return Math.max(OVERVIEW_BOTTOM_MIN_HEIGHT, Math.min(OVERVIEW_BOTTOM_MAX_HEIGHT, storedHeight));
}

const CURVE_MODES = {
  year: { key: "year", label: "年曲线", pointCount: 8760, stepMinutes: 60, durationMinutes: 365 * 24 * 60, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 可编辑" },
  day: { key: "day", label: "日曲线", pointCount: 1440, stepMinutes: 1, durationMinutes: 24 * 60, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 可编辑" },
};
const CURVE_META = [
  { key: "wind_speed_mps", label: "风速", color: "#008c8c", min: 0, max: 50, digits: 2, unit: "m/s" },
  { key: "solar_irradiance_w_m2", label: "太阳辐照", color: "#b87500", min: 0, max: 1100, digits: 1, unit: "W/m2" },
  { key: "air_temp_c", label: "气温", color: "#2b6b7f", min: -50, max: 10, digits: 2, unit: "℃" },
  { key: "load_kw", label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" },
];
const ENV_CURVE_KEYS = ["wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"];
const LOAD_CURVE_META = { label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" };
const LOAD_CURVE_COLORS = ["#c93a3a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_PLOT = { left: 58, right: 24, top: 46, bottom: 34 };
const TRACE_HISTORY_LIMIT = 45000;
const WEATHER_MEASUREMENT_LABELS = {
  WIND_SPEED: { label: "风速", unit: "m/s", order: 0 },
  SOLAR_IRRADIANCE: { label: "太阳辐照", unit: "W/m2", order: 1 },
  AIR_TEMP: { label: "气温", unit: "℃", order: 2 },
  HUMIDITY: { label: "湿度", unit: "%", order: 3 },
  AIR_PRESSURE: { label: "气压", unit: "hPa", order: 4 },
};
let pendingImportDefinitionFile = null;

function chartHiddenSet(chartKey) {
  const hidden = state.chartSeriesHidden?.[chartKey] || [];
  return new Set(hidden);
}

function isChartSeriesHidden(chartKey, seriesKey) {
  return chartHiddenSet(chartKey).has(seriesKey);
}

function visibleChartSeries(chartKey, seriesDefs) {
  return (seriesDefs || []).filter((series) => !isChartSeriesHidden(chartKey, series.key));
}

function selectedChartSeriesKey(chartKey, fallback = "") {
  const selected = state.chartSeriesSelected?.[chartKey];
  if (selected) return selected;
  return fallback || "";
}

function setChartSeriesSelected(chartKey, seriesKey, drawFn) {
  if (!chartKey || !seriesKey) return;
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function toggleChartSeriesVisibility(chartKey, seriesKey, drawFn) {
  if (!chartKey || !seriesKey) return;
  const hidden = chartHiddenSet(chartKey);
  if (hidden.has(seriesKey)) hidden.delete(seriesKey);
  else hidden.add(seriesKey);
  state.chartSeriesHidden = { ...(state.chartSeriesHidden || {}), [chartKey]: Array.from(hidden) };
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function syncChartLegendButtons(chartKey) {
  document.querySelectorAll(`[data-chart-toggle="${chartKey}"]`).forEach((button) => {
    const seriesKey = button.dataset.chartSeries || "";
    button.classList.toggle("is-hidden", isChartSeriesHidden(chartKey, seriesKey));
    button.classList.toggle("is-selected", selectedChartSeriesKey(chartKey) === seriesKey);
    button.setAttribute("aria-pressed", isChartSeriesHidden(chartKey, seriesKey) ? "false" : "true");
  });
}

function canvasPointerPosition(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function setChartCursorFromEvent(chartKey, canvas, plot, event, drawFn) {
  if (!canvas || !plot) return;
  const pos = canvasPointerPosition(canvas, event);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const visible = pos.x >= left && pos.x <= right && pos.y >= top && pos.y <= bottom;
  state.chartCursors = {
    ...(state.chartCursors || {}),
    [chartKey]: {
      visible,
      x: clamp(pos.x, left, right),
      y: clamp(pos.y, top, bottom),
    },
  };
  if (typeof drawFn === "function") drawFn();
}

function hideChartCursor(chartKey, drawFn) {
  const cursor = state.chartCursors?.[chartKey];
  if (!cursor?.visible) return;
  state.chartCursors = {
    ...(state.chartCursors || {}),
    [chartKey]: { ...cursor, visible: false },
  };
  if (typeof drawFn === "function") drawFn();
}

function chartSeriesAtPointer(chartKey, canvas, event, threshold = 10) {
  const seriesData = state.chartSeriesHitData?.[chartKey] || [];
  if (!seriesData.length) return "";
  const pos = canvasPointerPosition(canvas, event);
  let best = { key: "", distance: Number.POSITIVE_INFINITY };
  seriesData.forEach((series) => {
    (series.points || []).forEach((point) => {
      const distance = Math.hypot(point.x - pos.x, point.y - pos.y);
      if (distance < best.distance) best = { key: series.key, distance };
    });
  });
  return best.distance <= threshold ? best.key : "";
}

function selectChartSeriesAtPointer(chartKey, canvas, event, drawFn) {
  const seriesKey = chartSeriesAtPointer(chartKey, canvas, event);
  if (!seriesKey) return false;
  setChartSeriesSelected(chartKey, seriesKey, drawFn);
  return true;
}

function nearestChartPoint(points, x) {
  let best = null;
  let distance = Number.POSITIVE_INFINITY;
  (points || []).forEach((point) => {
    const nextDistance = Math.abs(point.x - x);
    if (nextDistance < distance) {
      best = point;
      distance = nextDistance;
    }
  });
  return best;
}

function drawChartCursor(ctx, chartKey, canvas, plot, seriesData, options = {}) {
  const cursor = state.chartCursors?.[chartKey];
  const visibleSeries = (seriesData || []).filter((series) => !isChartSeriesHidden(chartKey, series.key));
  if (!cursor?.visible || !visibleSeries.length) return;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const x = clamp(cursor.x, left, right);
  const y = clamp(cursor.y, top, bottom);
  const selectedKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const samples = visibleSeries
    .map((series) => ({ series, point: nearestChartPoint(series.points, x) }))
    .filter((item) => item.point);
  if (!samples.length) return;
  const mainPoint = samples.find((item) => item.series.key === selectedKey)?.point || samples[0].point;
  const timeLabel = options.timeLabel ? options.timeLabel(mainPoint) : (mainPoint.time || "");

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = options.ratio || 1;
  ctx.setLineDash([5 * (options.ratio || 1), 4 * (options.ratio || 1)]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  samples.forEach(({ series, point }) => {
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = series.color;
    ctx.lineWidth = 2 * (options.ratio || 1);
    ctx.beginPath();
    ctx.arc(point.x, point.y, 4.5 * (options.ratio || 1), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  const ratio = options.ratio || 1;
  ctx.font = `${12 * ratio}px Microsoft YaHei, Arial`;
  const valueFormatter = options.valueFormatter || ((value) => formatMeasurementValue(value));
  const lines = [
    timeLabel ? `时刻: ${timeLabel}` : "",
    ...samples.slice(0, 6).map(({ series, point }) => `${series.label}: ${valueFormatter(point.value)}${series.unit ? ` ${series.unit}` : ""}`),
    samples.length > 6 ? `另有 ${samples.length - 6} 条曲线` : "",
  ].filter(Boolean);
  const tooltipWidth = Math.max(150 * ratio, ...lines.map((line) => ctx.measureText(line).width + 24 * ratio));
  const tooltipHeight = 14 * ratio + lines.length * 18 * ratio;
  let tooltipX = x + 14 * ratio;
  let tooltipY = y + 14 * ratio;
  if (tooltipX + tooltipWidth > right - 6 * ratio) tooltipX = x - tooltipWidth - 14 * ratio;
  if (tooltipY + tooltipHeight > bottom - 6 * ratio) tooltipY = y - tooltipHeight - 14 * ratio;
  tooltipX = clamp(tooltipX, left + 6 * ratio, right - tooltipWidth - 6 * ratio);
  tooltipY = clamp(tooltipY, top + 6 * ratio, bottom - tooltipHeight - 6 * ratio);
  ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
  ctx.strokeStyle = "rgba(171, 190, 198, 0.9)";
  ctx.beginPath();
  ctx.roundRect(tooltipX, tooltipY, tooltipWidth, tooltipHeight, 8 * ratio);
  ctx.fill();
  ctx.stroke();
  lines.forEach((line, lineIndex) => {
    ctx.fillStyle = lineIndex === 0 ? "#1f3037" : "#314850";
    ctx.fillText(line, tooltipX + 10 * ratio, tooltipY + 18 * ratio + lineIndex * 18 * ratio);
  });
  ctx.restore();
}

function initTraceChartInteractions(chartKey, canvasId, drawFn) {
  const canvas = $(canvasId);
  if (!canvas) return;
  const handleMove = (event) => {
    setChartCursorFromEvent(chartKey, canvas, state.chartPlotInfo?.[chartKey], event, drawFn);
  };
  canvas.addEventListener("pointermove", handleMove);
  canvas.addEventListener("mousemove", handleMove);
  canvas.addEventListener("pointerleave", () => hideChartCursor(chartKey, drawFn));
  canvas.addEventListener("mouseleave", () => hideChartCursor(chartKey, drawFn));
  canvas.addEventListener("click", (event) => {
    if (selectChartSeriesAtPointer(chartKey, canvas, event, drawFn)) event.preventDefault();
  });
}

function isDeviceTreeGroupCollapsed(scope, groupKey) {
  return Boolean(state.collapsedDeviceTreeGroups?.[scope]?.[groupKey]);
}

function toggleDeviceTreeGroup(scope, groupKey) {
  if (!scope || !groupKey || groupKey === "all") return;
  if (!state.collapsedDeviceTreeGroups[scope]) {
    state.collapsedDeviceTreeGroups[scope] = {};
  }
  if (state.collapsedDeviceTreeGroups[scope][groupKey]) {
    delete state.collapsedDeviceTreeGroups[scope][groupKey];
  } else {
    state.collapsedDeviceTreeGroups[scope][groupKey] = true;
  }
}

function deviceTreeTypeAttrs(scope, groupKey, isCollapsed) {
  return `
          data-tree-toggle-scope="${escapeHtml(scope)}"
          data-tree-toggle-group="${escapeHtml(groupKey)}"
          aria-expanded="${isCollapsed ? "false" : "true"}"`;
}

function deviceTreeTypeLabel(label) {
  const text = label === "Environment" ? "气象环境" : label;
  return `
          <span class="tree-title">
            <i class="tree-toggle" aria-hidden="true"></i>
            <span class="tree-title-text">${escapeHtml(text)}</span>
          </span>`;
}

function deviceTreeChildren(isCollapsed, childrenHtml) {
  if (isCollapsed) return "";
  return `
        <div class="tree-children">
          ${childrenHtml}
        </div>`;
}

function simulationModeLocked(clock = state.snapshot?.clock) {
  return Boolean(clock) && clock.state !== "stopped";
}

function formatSimulationClock(clock) {
  const timeText = clock?.time || "00:00:00";
  if (state.curveMode !== "year") return timeText;
  const absoluteMinute = Math.max(0, Number(clock?.absolute_minute ?? clock?.minute ?? 0) || 0);
  let dayOfYear = Math.floor(absoluteMinute / 1440) % 365;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfYear >= monthDays[month]) {
    dayOfYear -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(dayOfYear + 1).padStart(2, "0")} ${timeText}`;
}

function renderClock(clock) {
  if (!clock) return;
  $("simState").textContent = clock.state || "stopped";
  $("simTime").textContent = formatSimulationClock(clock);
  $("simSpeed").textContent = `x${clock.speed ?? 1}`;
  const overviewClockSpeed = $("overviewClockSpeed");
  if (overviewClockSpeed) overviewClockSpeed.textContent = `x${clock.speed ?? 1}`;
  const readout = document.querySelector(".clock-readout");
  if (readout) {
    readout.dataset.clockState = clock.state || "stopped";
    readout.classList.toggle("is-year-mode", state.curveMode === "year");
  }
  document.querySelectorAll("[data-clock]").forEach((button) => {
    const action = button.dataset.clock;
    const isActive =
      (action === "start" && clock.state === "running") ||
      (action === "pause" && clock.state === "paused") ||
      (action === "stop" && clock.state === "stopped");
    button.classList.toggle("is-active", isActive);
    if (["start", "pause", "stop"].includes(action)) {
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    }
  });
  renderCurveModeControls();
}

function parameterNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function parameterText(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toFixed(digits).replace(/\.?0+$/, "");
}

function snapshotSystemParameters(snapshot = state.snapshot || {}) {
  const params = snapshot.system_parameters || {};
  const clock = snapshot.clock || {};
  return {
    clock_speed: parameterNumber(params.clock_speed ?? clock.speed, 1),
    compute_interval_seconds: parameterNumber(params.compute_interval_seconds, 1),
    clock_step_minutes: parameterNumber(params.clock_step_minutes ?? clock.step_minutes, 1),
    effective_step_minutes: parameterNumber(
      params.effective_step_minutes,
      parameterNumber(params.clock_step_minutes ?? clock.step_minutes, 1) * parameterNumber(params.clock_speed ?? clock.speed, 1),
    ),
  };
}

function renderSystemParameters(snapshot = state.snapshot) {
  const params = snapshotSystemParameters(snapshot || {});
  state.systemParameters = params;
  const currentSpeed = $("currentClockSpeed");
  const currentInterval = $("currentComputeInterval");
  if (currentSpeed) currentSpeed.textContent = `x${parameterText(params.clock_speed, 1)}`;
  if (currentInterval) currentInterval.textContent = `${parameterText(params.compute_interval_seconds, 2)} s`;

  const form = $("systemParameterForm");
  const isEditing = Boolean(form?.contains(document.activeElement));
  if (!state.systemParametersDirty && !isEditing) {
    const speedInput = $("parameterClockSpeed");
    const intervalInput = $("parameterComputeInterval");
    if (speedInput) speedInput.value = String(params.clock_speed);
    if (intervalInput) intervalInput.value = parameterText(params.compute_interval_seconds, 2);
  }

  const summary = $("systemParameterSummary");
  if (summary) {
    summary.textContent = state.systemParametersSaving
      ? "保存中"
      : state.systemParametersDirty
        ? "有未保存修改"
        : `x${parameterText(params.clock_speed, 1)} · ${parameterText(params.compute_interval_seconds, 2)} s`;
  }

  const modelName = snapshot?.model?.name || snapshot?.model?.id || state.activeModelId || "--";
  const clock = snapshot?.clock || {};
  const modeLabel = state.curveMode === "year" ? "年仿真" : "日仿真";
  const stateText = clock.state || "--";
  const stateMap = { running: "运行中", paused: "已暂停", stopped: "已停止" };
  const values = {
    systemParameterState: state.systemParametersDirty ? "待保存" : "已同步",
    parameterModelName: modelName,
    parameterSimulationMode: modeLabel,
    parameterClockState: stateMap[stateText] || stateText,
    parameterClockTime: snapshot?.clock ? formatSimulationClock(clock) : "--",
    parameterEffectiveStep: `${parameterText(params.effective_step_minutes, 1)} min`,
    parameterComputePeriod: `${parameterText(params.compute_interval_seconds, 2)} s`,
  };
  Object.entries(values).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
}

function markSystemParametersDirty() {
  state.systemParametersDirty = true;
  renderSystemParameters(state.snapshot);
}

function systemParameterPayload() {
  return {
    clock_speed: parameterNumber($("parameterClockSpeed")?.value, state.systemParameters.clock_speed || 1),
    compute_interval_seconds: parameterNumber(
      $("parameterComputeInterval")?.value,
      state.systemParameters.compute_interval_seconds || 1,
    ),
  };
}

async function saveSystemParameters() {
  const saveButton = $("saveSystemParameters");
  const resetButton = $("resetSystemParameters");
  state.systemParametersSaving = true;
  if (saveButton) saveButton.disabled = true;
  if (resetButton) resetButton.disabled = true;
  renderSystemParameters(state.snapshot);
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: JSON.stringify(systemParameterPayload()),
    });
    if (state.snapshot && result.clock) {
      state.snapshot.clock = result.clock;
      renderClock(result.clock);
    }
    if (result.system_parameters) {
      state.systemParameters = result.system_parameters;
    }
    state.systemParametersDirty = false;
    await refresh();
  } catch (error) {
    const summary = $("systemParameterSummary");
    if (summary) summary.textContent = "保存失败";
    throw error;
  } finally {
    state.systemParametersSaving = false;
    if (saveButton) saveButton.disabled = false;
    if (resetButton) resetButton.disabled = false;
    renderSystemParameters(state.snapshot);
  }
}

function resetSystemParameterForm() {
  state.systemParametersDirty = false;
  renderSystemParameters(state.snapshot);
}

function setClockButtonsBusy(isBusy) {
  document.querySelectorAll("[data-clock]").forEach((button) => {
    button.disabled = isBusy;
    button.classList.toggle("is-busy", isBusy);
  });
}

async function controlClock(action, payload = {}) {
  setClockButtonsBusy(true);
  try {
    const clock = await api("/api/clock", { method: "POST", body: JSON.stringify({ ...payload, action }) });
    renderClock(clock);
    await refresh();
    return clock;
  } catch (error) {
    $("simState").textContent = "error";
    $("solverInfo").textContent = "时钟控制失败";
    throw error;
  } finally {
    setClockButtonsBusy(false);
  }
}

function startSimulationMode() {
  return state.curveMode === "year" ? "year" : "day";
}

function startSimulationDefaultAbsoluteMinute() {
  const clock = state.snapshot?.clock || {};
  const minute = Number(clock.absolute_minute ?? clock.minute ?? 0);
  return Number.isFinite(minute) ? Math.max(0, Math.floor(minute)) : 0;
}

function setStartSimulationMessage(text, kind = "") {
  const message = $("startSimulationMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setStartSimulationBusy(isBusy) {
  const confirm = $("confirmStartSimulation");
  const cancel = $("cancelStartSimulation");
  const close = $("closeStartSimulationDialog");
  const day = $("startSimulationDay");
  const time = $("startSimulationTime");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "启动中" : "启动";
  }
  [cancel, close, day, time].forEach((element) => {
    if (element) element.disabled = isBusy;
  });
}

function updateStartSimulationFields() {
  const isYearMode = startSimulationMode() === "year";
  const dayField = $("startSimulationDayField");
  const dayInput = $("startSimulationDay");
  const hint = $("startSimulationHint");
  if (dayField) dayField.hidden = !isYearMode;
  if (dayInput) dayInput.disabled = !isYearMode;
  if (hint) {
    hint.textContent = isYearMode
      ? "年仿真按起始日和时刻启动；后台会按当前仿真步长向上对齐。"
      : "日仿真按起始时刻启动；后台会按当前仿真步长向上对齐。";
  }
}

function openStartSimulationDialog() {
  const dialog = $("startSimulationDialog");
  const dayInput = $("startSimulationDay");
  const timeInput = $("startSimulationTime");
  if (!dialog || !timeInput) return;
  const absoluteMinute = startSimulationDefaultAbsoluteMinute();
  const day = Math.floor(absoluteMinute / 1440) % 365 + 1;
  if (dayInput) dayInput.value = String(day);
  timeInput.value = minuteToTimeInput(absoluteMinute % 1440, 0);
  updateStartSimulationFields();
  setStartSimulationBusy(false);
  setStartSimulationMessage("");
  dialog.hidden = false;
  requestAnimationFrame(() => {
    if (startSimulationMode() === "year" && dayInput) {
      dayInput.focus();
      dayInput.select();
      return;
    }
    timeInput.focus();
  });
}

function closeStartSimulationDialog() {
  const dialog = $("startSimulationDialog");
  if (dialog) dialog.hidden = true;
  setStartSimulationMessage("");
  setStartSimulationBusy(false);
}

function startSimulationMinuteFromDialog() {
  const timeMinute = timeInputToMinute($("startSimulationTime")?.value, 0);
  if (startSimulationMode() !== "year") return timeMinute;
  const rawDay = Number($("startSimulationDay")?.value);
  const day = clamp(Math.round(Number.isFinite(rawDay) ? rawDay : 1), 1, 365);
  return (day - 1) * 1440 + timeMinute;
}

async function startSimulationFromDialog() {
  const minute = startSimulationMinuteFromDialog();
  setStartSimulationBusy(true);
  setStartSimulationMessage("正在启动仿真...");
  try {
    await controlClock("start", { minute });
    closeStartSimulationDialog();
  } catch (error) {
    setStartSimulationMessage(apiErrorText(error), "error");
    setStartSimulationBusy(false);
  }
}

function handleClockAction(action) {
  const currentState = state.snapshot?.clock?.state || $("simState")?.textContent || "stopped";
  if (action === "start" && currentState === "stopped") {
    openStartSimulationDialog();
    return;
  }
  controlClock(action);
}

function setCloneModelMessage(text, kind = "") {
  const message = $("cloneModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setCloneConfirmEnabled(isEnabled) {
  const confirm = $("confirmCloneModel");
  if (confirm) confirm.disabled = !isEnabled;
}

function validateCloneModelName(showBlank = false) {
  const input = $("cloneModelName");
  const name = String(input?.value || "").trim();
  if (!name) {
    setCloneConfirmEnabled(false);
    setCloneModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    setCloneConfirmEnabled(false);
    setCloneModelMessage(`模型已存在：${name}`, "error");
    return false;
  }
  setCloneConfirmEnabled(true);
  setCloneModelMessage("");
  return true;
}

function openCloneModelDialog() {
  const dialog = $("cloneModelDialog");
  const input = $("cloneModelName");
  if (!dialog || !input) return;
  input.value = modelCloneDefaultName();
  validateCloneModelName();
  dialog.hidden = false;
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeCloneModelDialog() {
  const dialog = $("cloneModelDialog");
  if (dialog) dialog.hidden = true;
}

function apiErrorText(error) {
  try {
    return JSON.parse(error.message)?.error || error.message;
  } catch (_parseError) {
    return error.message || "操作失败";
  }
}

function modelKey(value) {
  const text = String(value ?? "").trim();
  const cleaned = Array.from(text).map((char) => (
    /[\p{L}\p{N}_-]/u.test(char) ? char : "_"
  )).join("").replace(/^_+|_+$/g, "");
  return (cleaned || "default").toLocaleLowerCase();
}

function normalizeModels(models) {
  const seen = new Set();
  const unique = [];
  (models || []).forEach((model) => {
    const keys = [modelKey(model.id), modelKey(model.name || model.id)];
    if (keys.some((key) => seen.has(key))) return;
    keys.forEach((key) => seen.add(key));
    unique.push(model);
  });
  return unique;
}

function isModelNameTaken(name) {
  const key = modelKey(name);
  return normalizeModels(state.models).some((model) => (
    modelKey(model.id) === key || modelKey(model.name || model.id) === key
  ));
}

function uniqueCloneName(baseName) {
  const base = String(baseName || "model").trim().replace(/\s+/g, "_") || "model";
  const taken = new Set();
  normalizeModels(state.models).forEach((model) => {
    taken.add(modelKey(model.id));
    taken.add(modelKey(model.name || model.id));
  });
  const first = `${base}_copy`;
  if (!taken.has(modelKey(first))) return first;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${base}_copy_${index}`;
    if (!taken.has(modelKey(candidate))) return candidate;
  }
  return `${base}_copy_${Date.now()}`;
}

function modelCloneDefaultName() {
  const active = state.models.find((model) => model.id === state.activeModelId) || state.models[0] || {};
  const base = String(active.name || active.id || "model").replace(/\s+/g, "_");
  return uniqueCloneName(base);
}

function setCloneModelBusy(isBusy) {
  const confirm = $("confirmCloneModel");
  const button = $("cloneModelButton");
  const input = $("cloneModelName");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "复制中" : "复制";
  }
  if (button) button.disabled = isBusy;
  if (input) input.disabled = isBusy;
}

async function cloneCurrentModel() {
  const input = $("cloneModelName");
  const name = String(input?.value || "").trim();
  if (!validateCloneModelName(true)) {
    input?.focus();
    return;
  }
  setCloneModelBusy(true);
  setCloneModelMessage("正在复制模型文件夹...");
  try {
    const result = await api("/api/models/clone", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    closeCloneModelDialog();
    setActiveModel(newModelId, true);
  } catch (error) {
    setCloneModelMessage(apiErrorText(error), "error");
  } finally {
    setCloneModelBusy(false);
    if (!$("cloneModelDialog").hidden) validateCloneModelName();
  }
}

function setImportModelMessage(text, kind = "") {
  const message = $("importModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function suggestedImportModelName(filename) {
  return String(filename || "导入模型")
    .replace(/\.zip$/i, "")
    .replace(/_definitions_\d{8}_\d{6}$/i, "")
    .replace(/_definitions$/i, "")
    .trim() || "导入模型";
}

function validateImportModelName(showBlank = false) {
  const input = $("importModelName");
  const confirm = $("confirmImportModel");
  const name = String(input?.value || "").trim();
  if (!name) {
    if (confirm) confirm.disabled = true;
    setImportModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    if (confirm) confirm.disabled = true;
    setImportModelMessage(`模型已存在：${name}，请输入新的模型名称。`, "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setImportModelMessage("");
  return true;
}

function openImportModelDialog(file) {
  const dialog = $("importModelDialog");
  const input = $("importModelName");
  if (!dialog || !input || !file) return;
  pendingImportDefinitionFile = file;
  const active = state.models.find((model) => model.id === state.activeModelId) || state.models[0] || {};
  $("importModelFilename").textContent = file.name;
  $("importTemplateModelName").textContent = active.name || active.id || "当前模型";
  input.value = suggestedImportModelName(file.name);
  dialog.hidden = false;
  validateImportModelName();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeImportModelDialog() {
  const dialog = $("importModelDialog");
  if (dialog) dialog.hidden = true;
  pendingImportDefinitionFile = null;
  const fileInput = $("importDefinitionsInput");
  if (fileInput) fileInput.value = "";
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 32768;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function setImportModelBusy(isBusy) {
  const confirm = $("confirmImportModel");
  const input = $("importModelName");
  const button = $("importDefinitionsButton");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "导入中" : "导入";
  }
  if (input) input.disabled = isBusy;
  if (button) button.disabled = isBusy;
}

async function importDefinitionModel() {
  const file = pendingImportDefinitionFile;
  const input = $("importModelName");
  const name = String(input?.value || "").trim();
  if (!file || !validateImportModelName(true)) {
    input?.focus();
    return;
  }
  setImportModelBusy(true);
  setImportModelMessage("正在创建模型文件夹并导入定义数据...");
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/models/import-definitions", {
      method: "POST",
      body: JSON.stringify({
        create_model: true,
        name,
        filename: file.name,
        data_base64: dataBase64,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    closeImportModelDialog();
    setActiveModel(newModelId, true);
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setImportModelMessage(
      message.includes("已存在") ? `${message}，请输入新的模型名称。` : message,
      "error",
    );
  } finally {
    setImportModelBusy(false);
  }
}

function pageFromHash() {
  const fallback = document.querySelector(".app-shell")?.dataset.defaultPage || "overview";
  return (location.hash || "").replace("#", "") || fallback;
}

function showPage(page, updateHash = true) {
  const sections = Array.from(document.querySelectorAll("[data-page]"));
  const target = sections.some((section) => section.dataset.page === page) ? page : "overview";
  sections.forEach((section) => section.classList.toggle("is-active", section.dataset.page === target));
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.navPage === target);
  });
  if (updateHash && location.hash !== `#${target}`) {
    history.replaceState(null, "", `#${target}`);
  }
  if (target === "curves" && Object.keys(state.curveSeries).length) {
    requestAnimationFrame(() => {
      resizeCurveCanvas();
      renderCurveEditor(true);
    });
  }
  if (target === "model") {
    requestAnimationFrame(() => renderGridModelPage());
  }
  if (target === "parameters") {
    requestAnimationFrame(() => renderSystemParameters(state.snapshot));
  }
  if (target === "runtime") {
    requestAnimationFrame(() => drawRuntimeTraceChart());
  }
  if (target === "measurements") {
    requestAnimationFrame(() => drawMeasurementTraceChart());
  }
}

function initPageNavigation() {
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.navPage));
  });
  window.addEventListener("hashchange", () => showPage(pageFromHash(), false));
  showPage(pageFromHash(), false);
}

function modelScopedPath(path) {
  if (!state.activeModelId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}model_id=${encodeURIComponent(state.activeModelId)}`;
}

async function api(path, options = {}) {
  const { modelScoped = true, ...fetchOptions } = options;
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  const response = await fetch(`${apiBase}${targetPath}`, {
    ...fetchOptions,
    headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function apiUrl(path, modelScoped = true) {
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  return `${apiBase}${targetPath}`;
}

function filenameFromDisposition(disposition, fallback) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || "");
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch (_error) {
      return fallback;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition || "");
  return plain?.[1] || fallback;
}

function blobFromBase64(dataBase64, contentType) {
  const binary = atob(dataBase64 || "");
  const chunkSize = 65536;
  const chunks = [];
  for (let offset = 0; offset < binary.length; offset += chunkSize) {
    const slice = binary.slice(offset, offset + chunkSize);
    const bytes = new Uint8Array(slice.length);
    for (let idx = 0; idx < slice.length; idx += 1) {
      bytes[idx] = slice.charCodeAt(idx);
    }
    chunks.push(bytes);
  }
  return new Blob(chunks, { type: contentType || "application/zip" });
}

function downloadBlob(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

function safeExportFilename(filename) {
  const cleaned = String(filename || "model_definitions.zip").replace(/[\\/:*?"<>|]/g, "_");
  return cleaned.toLowerCase().endsWith(".zip") ? cleaned : `${cleaned}.zip`;
}

async function exportDefinitionsArchive() {
  const button = $("exportDefinitionsButton");
  if (!button) return;
  const originalText = button.textContent;
  button.disabled = true;
  try {
    let directoryHandle = null;
    if (typeof window.showDirectoryPicker === "function") {
      button.textContent = "选择目录";
      directoryHandle = await window.showDirectoryPicker({
        id: "simu-definition-export",
        mode: "readwrite",
        startIn: "downloads",
      });
    }
    button.textContent = "导出中";
    const payload = await api("/api/export-definitions?format=json");
    const blob = blobFromBase64(payload.data_base64, payload.content_type);
    const filename = safeExportFilename(filenameFromDisposition("", payload.filename || "model_definitions.zip"));
    if (directoryHandle) {
      const fileHandle = await directoryHandle.getFileHandle(filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      button.textContent = "已导出";
    } else {
      downloadBlob(blob, filename);
    }
  } catch (error) {
    if (error?.name === "AbortError") return;
    alert(apiErrorText(error));
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function setTraineeLinkMessage(text, kind = "") {
  const message = $("traineeLinkMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function closeTraineeLinkDialog() {
  const dialog = $("traineeLinkDialog");
  if (dialog) dialog.hidden = true;
}

function activeModelInfo() {
  const selector = $("modelSelector");
  const selectedId = selector?.value || state.activeModelId || state.snapshot?.model?.id || state.models[0]?.id || "";
  return state.models.find((model) => model.id === selectedId)
    || (state.snapshot?.model?.id === selectedId ? state.snapshot.model : null)
    || { id: selectedId, name: selectedId || "默认模型" };
}

function generatedTraineeLink(modelId) {
  const id = String(modelId || state.activeModelId || "").trim();
  return id
    ? `${apiBase}/api/trainee-link?model_id=${encodeURIComponent(id)}`
    : `${apiBase}/api/trainee-link`;
}

function setTraineeLinkCopyEnabled(enabled) {
  const copyButton = $("copyTraineeLink");
  if (copyButton) copyButton.disabled = !enabled;
}

async function openTraineeLinkDialog() {
  const dialog = $("traineeLinkDialog");
  const input = $("traineeLinkValue");
  const modelName = $("traineeLinkModelName");
  const button = $("traineeLinkButton");
  if (!dialog || !input || !modelName) return;
  const currentModel = activeModelInfo();
  dialog.hidden = false;
  input.value = generatedTraineeLink(currentModel.id);
  modelName.textContent = currentModel.name || currentModel.id || "--";
  setTraineeLinkCopyEnabled(Boolean(input.value));
  setTraineeLinkMessage("交互链接已自动生成，正在与模拟台服务校验。", input.value ? "ok" : "");
  input.focus();
  input.select();
  if (button) button.disabled = true;
  try {
    const payload = await api("/api/trainee-link");
    input.value = payload.link || input.value;
    modelName.textContent = payload.model_name || payload.model_id || "--";
    setTraineeLinkCopyEnabled(Boolean(input.value));
    setTraineeLinkMessage("将此链接发给学员台，学员点击“启动接收”后输入该链接即可接入当前模型。", "ok");
    input.focus();
    input.select();
  } catch (error) {
    setTraineeLinkCopyEnabled(Boolean(input.value));
    setTraineeLinkMessage(`已按当前模型生成链接，但服务校验失败：${apiErrorText(error)}`, input.value ? "error" : "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function copyTraineeLink() {
  const input = $("traineeLinkValue");
  if (!input?.value) {
    setTraineeLinkMessage("暂无可复制的交互链接。", "error");
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(input.value);
    } else {
      input.focus();
      input.select();
      document.execCommand("copy");
    }
    setTraineeLinkMessage("交互链接已复制。", "ok");
  } catch (_error) {
    input.focus();
    input.select();
    setTraineeLinkMessage("复制失败，请手动复制输入框中的链接。", "error");
  }
}

function renderModelSelector() {
  const selector = $("modelSelector");
  if (!selector) return;
  state.models = normalizeModels(state.models);
  const models = state.models.length ? state.models : [{ id: state.activeModelId || "", name: "默认模型" }];
  selector.innerHTML = models.map((model) => `
    <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
  `).join("");
  selector.value = state.activeModelId || models[0]?.id || "";
  selector.disabled = models.length <= 1;
  const active = models.find((model) => model.id === selector.value) || models[0] || {};
  $("activeModelName").textContent = active.name || active.id || "默认模型";
}

function setActiveModel(modelId, shouldRefresh = true) {
  const nextId = modelId || state.models[0]?.id || "";
  if (state.activeModelId === nextId && shouldRefresh) {
    refresh();
    return;
  }
  state.activeModelId = nextId;
  localStorage.setItem("polarSimulatorModelId", nextId);
  state.snapshot = null;
  state.settingsLoaded = false;
  state.deviceFaults = [];
  state.measurementFaults = [];
  state.modes = [];
  state.runtimeLogs = [];
  state.runtimeLogTypeFilter = "all";
  state.runtimeLogSeq = 0;
  state.lastRuntimeLogKey = "";
  state.systemParameters = { clock_speed: 1, compute_interval_seconds: 1 };
  state.systemParametersDirty = false;
  state.systemParametersSaving = false;
  state.runtimeTraceHistory = [];
  state.lastRuntimeTraceKey = "";
  state.measurementTraceHistory = [];
  state.lastMeasurementTraceKey = "";
  state.traceRunId = null;
  state.selectedMeasurementKey = "";
  state.modeFilter = { dev_type: "all", dev_name: "" };
  state.faultDeviceFilter = { dev_type: "all", dev_name: "" };
  state.faultMeasurementFilter = { dev_type: "all", dev_name: "", key: "" };
  state.modelDeviceFilter = { dev_type: "all", dev_name: "" };
  state.activeModelParamTab = "";
  state.runtimeDeviceFilter = { dev_type: "all", dev_name: "" };
  state.activeRuntimeCommandTab = "remote_control";
  state.measurementCompareFilter = { dev_type: "all", dev_name: "" };
  state.activeCurveKey = "wind_speed_mps";
  state.selectedCurveKeys = ["wind_speed_mps"];
  state.curveEditKey = "";
  state.curveSeries = {};
  state.curveSeriesByMode = {};
  state.curvesLoadedModelId = "";
  renderModelSelector();
  if (shouldRefresh) refresh();
}

async function loadModels() {
  try {
    const catalog = await api("/api/models", { modelScoped: false });
    state.models = normalizeModels(Array.isArray(catalog.models) ? catalog.models : []);
    const preferred = state.activeModelId || catalog.active_model_id || state.models[0]?.id || "";
    const exists = state.models.some((model) => model.id === preferred);
    setActiveModel(exists ? preferred : state.models[0]?.id || "", false);
  } catch (_error) {
    state.models = [];
    renderModelSelector();
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

function runtimeLogTime() {
  return runtimeLogWallTimeText(new Date());
}

function runtimeLogWallTimeText(value) {
  if (!value) return "--";
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toLocaleTimeString("zh-CN", { hour12: false });
  }
  const text = String(value || "").trim();
  if (!text) return "--";
  const isoMatch = text.match(/(?:T|\s)(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/);
  if (isoMatch) return isoMatch[1];
  const plainTimeMatch = text.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (plainTimeMatch) {
    return `${plainTimeMatch[1].padStart(2, "0")}:${plainTimeMatch[2]}:${plainTimeMatch[3] || "00"}`;
  }
  const parsed = new Date(text);
  if (Number.isFinite(parsed.getTime())) {
    return parsed.toLocaleTimeString("zh-CN", { hour12: false });
  }
  return text;
}

function runtimeLogDetailText(detail) {
  if (Array.isArray(detail)) return detail.filter(Boolean).join("\n");
  if (detail && typeof detail === "object") {
    return Object.entries(detail)
      .map(([key, value]) => `${key}: ${value}`)
      .join("；");
  }
  return String(detail || "");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function minuteToTimeInput(value, fallback = 0) {
  const numeric = Number(value);
  const fallbackNumeric = Number(fallback);
  const minute = clamp(
    Math.round(Number.isFinite(numeric) ? numeric : (Number.isFinite(fallbackNumeric) ? fallbackNumeric : 0)),
    0,
    1439,
  );
  const hourText = String(Math.floor(minute / 60)).padStart(2, "0");
  const minuteText = String(minute % 60).padStart(2, "0");
  return `${hourText}:${minuteText}`;
}

function timeInputToMinute(value, fallback = 0) {
  const match = /^(\d{2}):(\d{2})$/.exec(String(value || ""));
  if (!match) return clamp(Number(fallback) || 0, 0, 1439);
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return clamp(Number(fallback) || 0, 0, 1439);
  return hour * 60 + minute;
}

function curveModeConfig(mode = state.curveMode) {
  return CURVE_MODES[mode] || CURVE_MODES.year;
}

function curvePointCount(mode = state.curveMode) {
  return curveModeConfig(mode).pointCount;
}

function curveDurationMinutes(mode = state.curveMode) {
  return curveModeConfig(mode).durationMinutes;
}

function curveStepMinutes(mode = state.curveMode) {
  return curveModeConfig(mode).stepMinutes;
}

function pointMinute(index) {
  return index * curveStepMinutes();
}

function pointIndexFromMinute(minute) {
  const config = curveModeConfig();
  const boundedMinute = clamp(Number(minute) || 0, 0, Math.max(0, config.durationMinutes - config.stepMinutes));
  return clamp(Math.round(boundedMinute / config.stepMinutes), 0, config.pointCount - 1);
}

function curveValueAtMinute(key, minute) {
  const series = state.curveSeries[key] || [];
  return series[clamp(pointIndexFromMinute(minute), 0, series.length - 1)] || 0;
}

function loadCurveKey(devName) {
  return `load:${devName || "load_ac_1"}`;
}

function loadNameFromCurveKey(key) {
  return String(key || "").replace(/^load:/, "") || "load_ac_1";
}

function activeCurveKey() {
  return state.activeCurveKey || $("activeCurve")?.value || "wind_speed_mps";
}

function allLoadCurveKeys() {
  return curveLoadDevices().map((dev) => loadCurveKey(dev.dev_name));
}

function allCurveKeys() {
  return [...ENV_CURVE_KEYS, ...allLoadCurveKeys()];
}

function curveLoadDevices() {
  const devices = (state.snapshot?.devices || [])
    .filter((dev) => ["ACLoad", "DCLoad"].includes(dev.dev_type) && dev.dev_name)
    .map((dev) => ({ dev_type: dev.dev_type, dev_name: dev.dev_name }));
  const unique = new Map();
  devices.forEach((dev) => unique.set(`${dev.dev_type}|${dev.dev_name}`, dev));
  const loads = Array.from(unique.values()).sort((left, right) => left.dev_name.localeCompare(right.dev_name));
  return loads.length ? loads : [{ dev_type: "ACLoad", dev_name: "load_ac_1" }];
}

function curveMetaForKey(key) {
  const meta = CURVE_META.find((item) => item.key === key);
  if (meta) return meta;
  if (String(key).startsWith("load:")) {
    const devName = loadNameFromCurveKey(key);
    const loadIndex = Math.max(0, allLoadCurveKeys().indexOf(key));
    const color = LOAD_CURVE_COLORS[loadIndex % LOAD_CURVE_COLORS.length];
    return { ...LOAD_CURVE_META, key, label: devName, color };
  }
  return CURVE_META[0];
}

function activeLoadCurveKey() {
  const key = activeCurveKey();
  if (key.startsWith("load:")) return key;
  return loadCurveKey(curveLoadDevices()[0]?.dev_name);
}

function selectedCurveKeys() {
  const available = new Set(allCurveKeys());
  const selected = Array.from(new Set(state.selectedCurveKeys || []))
    .filter((key) => available.has(key));
  const activeKey = activeCurveKey();
  if (!selected.length && available.has(activeKey)) selected.push(activeKey);
  if (!selected.length) selected.push("wind_speed_mps");
  state.selectedCurveKeys = selected;
  if (!selected.includes(activeKey)) {
    state.activeCurveKey = selected[selected.length - 1];
  }
  return selected;
}

function curveHiddenSet() {
  return new Set(state.hiddenCurveKeys || []);
}

function isCurveSeriesHidden(key) {
  return curveHiddenSet().has(key);
}

function visibleCurveKeys() {
  return selectedCurveKeys().filter((key) => !isCurveSeriesHidden(key));
}

function visibleCurveMetas() {
  return visibleCurveKeys().map(curveMetaForKey);
}

function toggleCurveSeriesVisibility(key, shouldRender = true) {
  if (!key) return;
  const hidden = curveHiddenSet();
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  state.hiddenCurveKeys = Array.from(hidden);
  state.curveEditKey = key;
  if (shouldRender) {
    renderCurveTree();
    drawCurves();
    renderHourlyTable(true);
  }
}

function resampleSeries(values, nextLength, fallbackValue) {
  if (values?.length === nextLength) return values;
  if (!values?.length) return new Array(nextLength).fill(fallbackValue);
  if (nextLength <= 1) return [values[0] ?? fallbackValue];
  const lastSource = Math.max(1, values.length - 1);
  return Array.from({ length: nextLength }, (_unused, index) => {
    const sourceIndex = Math.round((index / Math.max(1, nextLength - 1)) * lastSource);
    return values[sourceIndex] ?? fallbackValue;
  });
}

function normalizeCurveSeriesLength(key, fallbackValue) {
  const nextLength = curvePointCount();
  const changed = state.curveSeries[key]?.length !== nextLength;
  state.curveSeries[key] = resampleSeries(state.curveSeries[key], nextLength, fallbackValue);
  return changed;
}

function loadCurveSeriesTemplate() {
  const firstLoadKey = loadCurveKey(curveLoadDevices()[0]?.dev_name);
  return resampleSeries(state.curveSeries.load_kw || state.curveSeries[firstLoadKey], curvePointCount(), 120);
}

function ensureCurveLoadSeries() {
  const template = loadCurveSeriesTemplate();
  let changed = false;
  curveLoadDevices().forEach((dev) => {
    const key = loadCurveKey(dev.dev_name);
    if (!state.curveSeries[key]) {
      state.curveSeries[key] = [...template];
      changed = true;
    } else if (state.curveSeries[key].length !== curvePointCount()) {
      state.curveSeries[key] = resampleSeries(state.curveSeries[key], curvePointCount(), 120);
      changed = true;
    }
  });
  const activeKey = activeCurveKey();
  if (activeKey.startsWith("load:") && !state.curveSeries[activeKey]) {
    setActiveCurve(loadCurveKey(curveLoadDevices()[0]?.dev_name), false);
    changed = true;
  }
  return changed;
}

function ensureCurveSeries() {
  let changed = false;
  ENV_CURVE_KEYS.forEach((key) => {
    changed = normalizeCurveSeriesLength(key, curveMetaForKey(key).min) || changed;
  });
  changed = ensureCurveLoadSeries() || changed;
  return changed;
}

function saveCurrentCurveModeSeries() {
  if (!state.curveMode || !Object.keys(state.curveSeries || {}).length) return;
  state.curveSeriesByMode[state.curveMode] = state.curveSeries;
}

function setCurveMode(mode, shouldRender = true) {
  const nextMode = CURVE_MODES[mode] ? mode : "year";
  saveCurrentCurveModeSeries();
  state.curveMode = nextMode;
  localStorage.setItem("polarSimulatorCurveMode", nextMode);
  state.curveEditKey = "";
  if (state.curveSeriesByMode[nextMode]) {
    state.curveSeries = state.curveSeriesByMode[nextMode];
    ensureCurveSeries();
    syncCurvePayload(false);
  } else {
    generateCurves(0, nextMode, false);
  }
  if (shouldRender) {
    renderCurveEditor(true);
    renderFaults(true);
  }
}

function loadCurvesFromSnapshot(curves, modelId = state.activeModelId) {
  if (!curves || typeof curves !== "object") return;
  const mode = CURVE_MODES[curves.mode] ? curves.mode : "day";
  const config = curveModeConfig(mode);
  const weather = Array.isArray(curves.weather) ? curves.weather : [];
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  state.curveMode = mode;
  localStorage.setItem("polarSimulatorCurveMode", mode);
  state.curveSeries = {
    wind_speed_mps: resampleSeries(weather.map((point) => Number(point.wind_speed_mps) || 0), config.pointCount, 0),
    solar_irradiance_w_m2: resampleSeries(weather.map((point) => Number(point.solar_irradiance_w_m2) || 0), config.pointCount, 0),
    air_temp_c: resampleSeries(weather.map((point) => Number(point.air_temp_c) || 0), config.pointCount, -18),
  };
  curveLoadDevices().forEach((dev) => {
    const points = Array.isArray(loads[dev.dev_name]) ? loads[dev.dev_name] : [];
    state.curveSeries[loadCurveKey(dev.dev_name)] = resampleSeries(
      points.map((point) => Number(point.p_kw ?? point.value ?? point.load_kw) || 0),
      config.pointCount,
      120,
    );
  });
  ensureCurveSeries();
  state.curveSeriesByMode[mode] = state.curveSeries;
  syncCurvePayload(false);
  state.curvesLoadedModelId = modelId || "loaded";
}

async function switchSimulationMode(mode) {
  if (simulationModeLocked()) return;
  const selector = $("simulationModeSelector");
  if (selector) selector.disabled = true;
  try {
    setCurveMode(mode, true);
    await saveCurves();
    await refresh();
  } catch (error) {
    alert(apiErrorText(error));
  } finally {
    renderCurveModeControls();
  }
}

function renderCurveModeControls() {
  const modeLocked = simulationModeLocked();
  document.querySelectorAll("[data-curve-mode]").forEach((button) => {
    const active = button.dataset.curveMode === state.curveMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = modeLocked;
    button.title = modeLocked ? "请先停止仿真，再切换仿真模式" : "";
  });
  const selector = $("simulationModeSelector");
  if (selector) {
    selector.value = state.curveMode;
    selector.disabled = modeLocked;
    selector.title = modeLocked ? "请先停止仿真，再切换仿真模式" : "选择年仿真或日仿真";
  }
  if (state.snapshot?.clock) renderClockTextOnly(state.snapshot.clock);
}

function renderClockTextOnly(clock) {
  const time = $("simTime");
  const simSpeed = $("simSpeed");
  const overviewClockSpeed = $("overviewClockSpeed");
  const readout = document.querySelector(".clock-readout");
  if (time) time.textContent = formatSimulationClock(clock);
  if (simSpeed) simSpeed.textContent = `x${clock.speed ?? 1}`;
  if (overviewClockSpeed) overviewClockSpeed.textContent = `x${clock.speed ?? 1}`;
  if (readout) readout.classList.toggle("is-year-mode", state.curveMode === "year");
}

function updateCurveModeLabels() {
  const config = curveModeConfig();
  const pointCount = $("curvePointCount");
  const tableTitle = $("curveTableTitle");
  const tableSummary = $("curveTableSummary");
  if (pointCount) pointCount.textContent = `${config.pointCount}点`;
  if (tableTitle) tableTitle.textContent = config.tableTitle;
  if (tableSummary) tableSummary.textContent = config.tableSummary;
}

function curveFamilyKeys(family) {
  if (family === "environment") return [...ENV_CURVE_KEYS];
  if (family === "load") return allLoadCurveKeys();
  return [];
}

function selectedCurveLabel() {
  const selected = selectedCurveKeys();
  const editKey = curveEditKey(selected);
  const selectedLabel = selected.length <= 1 ? curveMetaForKey(selected[0]).label : `已选${selected.length}条`;
  return editKey && selected.length > 1 ? `${selectedLabel} · ${curveMetaForKey(editKey).label}` : selectedLabel;
}

function setSelectedCurves(keys, activeKey = keys?.[keys.length - 1], shouldRender = true) {
  const available = new Set(allCurveKeys());
  const selected = Array.from(new Set(keys || [])).filter((key) => available.has(key));
  if (!selected.length) selected.push("wind_speed_mps");
  const nextActiveKey = selected.includes(activeKey) ? activeKey : selected[selected.length - 1];
  state.selectedCurveKeys = selected;
  state.activeCurveKey = nextActiveKey || "wind_speed_mps";
  if (state.curveEditKey && !selected.includes(state.curveEditKey)) {
    state.curveEditKey = "";
  }
  const activeInput = $("activeCurve");
  if (activeInput) activeInput.value = state.activeCurveKey;
  if (shouldRender) {
    renderCurveTree();
    drawCurves();
    renderHourlyTable();
  }
}

function toggleCurveSelection(key, shouldRender = true) {
  const selected = selectedCurveKeys();
  const next = selected.includes(key)
    ? selected.filter((item) => item !== key)
    : [...selected, key];
  setSelectedCurves(next.length ? next : selected, key, shouldRender);
}

function selectCurveFamily(family, shouldRender = true) {
  const familyKeys = curveFamilyKeys(family);
  setSelectedCurves(familyKeys, familyKeys[0], shouldRender);
}

function curveTreeButtonKeys(button) {
  if (!button) return [];
  if (button.dataset.curveFamily) return curveFamilyKeys(button.dataset.curveFamily);
  return button.dataset.curveKey ? [button.dataset.curveKey] : [];
}

function selectCurveTreeButton(button, shouldRender = true) {
  const keys = curveTreeButtonKeys(button);
  if (!keys.length) return;
  const activeKey = button.dataset.curveKey || keys[0];
  setSelectedCurves(keys, activeKey, shouldRender);
}

function resetCurveTreePointerSelection() {
  state.isCurveTreePointerDown = false;
  state.isCurveTreeMultiSelecting = false;
  state.curveTreeDragStartKeys = [];
  state.curveTreeDragKeys = [];
  state.curveTreeDragStartButton = null;
}

function beginCurveTreePointerSelection(event) {
  if (event.button !== 0) return;
  const button = event.target.closest("[data-curve-tree-type]");
  if (!button || !$("curveTree")?.contains(button)) return;
  state.isCurveTreePointerDown = true;
  state.isCurveTreeMultiSelecting = false;
  state.curveTreeDragStartButton = button;
  state.curveTreeDragStartKeys = curveTreeButtonKeys(button);
  state.curveTreeDragKeys = [...state.curveTreeDragStartKeys];
}

function extendCurveTreePointerSelection(event) {
  if (!state.isCurveTreePointerDown || (event.buttons & 1) !== 1) return;
  const button = event.target.closest("[data-curve-tree-type]");
  if (!button || !$("curveTree")?.contains(button)) return;
  if (!state.isCurveTreeMultiSelecting && button === state.curveTreeDragStartButton) return;
  const keys = curveTreeButtonKeys(button);
  if (!keys.length) return;
  if (!state.isCurveTreeMultiSelecting) {
    state.isCurveTreeMultiSelecting = true;
    state.curveTreeDragKeys = [...state.curveTreeDragStartKeys];
  }
  const before = state.curveTreeDragKeys.length;
  keys.forEach((key) => {
    if (!state.curveTreeDragKeys.includes(key)) state.curveTreeDragKeys.push(key);
  });
  if (state.curveTreeDragKeys.length !== before || !selectedCurveKeys().every((key) => state.curveTreeDragKeys.includes(key))) {
    setSelectedCurves(state.curveTreeDragKeys, keys[keys.length - 1], true);
  }
}

function finishCurveTreePointerSelection() {
  if (state.isCurveTreeMultiSelecting) {
    state.suppressNextCurveTreeClick = true;
  }
  resetCurveTreePointerSelection();
}

function curveEditKey(selectedKeys = selectedCurveKeys()) {
  const editKey = state.curveEditKey || "";
  if (editKey && selectedKeys.includes(editKey) && (state.curveSeries[editKey] || []).length) {
    return editKey;
  }
  if (editKey) state.curveEditKey = "";
  return "";
}

function setCurveEditKey(key, shouldRender = true) {
  const selected = selectedCurveKeys();
  const nextKey = selected.includes(key) ? key : "";
  state.curveEditKey = nextKey;
  if (nextKey) {
    state.activeCurveKey = nextKey;
    const activeInput = $("activeCurve");
    if (activeInput) activeInput.value = nextKey;
  }
  if (shouldRender) {
    renderCurveTree();
    drawCurves();
  }
}

function cancelCurveEditSelection() {
  state.curveEditKey = "";
  state.isCurveDragging = false;
  renderCurveTree();
  drawCurves();
}

function renderCurveTree() {
  const container = $("curveTree");
  if (!container) return;
  const activeKey = activeCurveKey();
  const selectedKeys = selectedCurveKeys();
  const editKey = curveEditKey(selectedKeys);
  const selectedSet = new Set(selectedKeys);
  const loadDevices = curveLoadDevices();
  const loadKeys = allLoadCurveKeys();
  const envSelected = ENV_CURVE_KEYS.every((key) => selectedSet.has(key))
    && selectedKeys.every((key) => ENV_CURVE_KEYS.includes(key));
  const loadSelected = loadKeys.every((key) => selectedSet.has(key))
    && selectedKeys.every((key) => loadKeys.includes(key));
  const envPartial = ENV_CURVE_KEYS.some((key) => selectedSet.has(key));
  const loadPartial = loadKeys.some((key) => selectedSet.has(key));
  $("curveTreeSummary").textContent = `${ENV_CURVE_KEYS.length + loadDevices.length} 条`;
  $("activeCurve").value = activeKey;
  $("activeCurveLabel").textContent = selectedCurveLabel();
  container.innerHTML = `
    <div class="tree-group">
      <button
        type="button"
        class="tree-node tree-type ${envSelected ? "is-active" : envPartial ? "is-parent-active" : ""}"
        data-curve-tree-type="environment"
        data-curve-family="environment"
        aria-pressed="${envSelected ? "true" : "false"}"
      >
        <span>环境曲线</span>
        <strong>${ENV_CURVE_KEYS.length}</strong>
      </button>
      <div class="tree-children">
        ${ENV_CURVE_KEYS.map((key) => {
          const meta = curveMetaForKey(key);
          const shortLabel = key === "wind_speed_mps" ? "风" : key === "solar_irradiance_w_m2" ? "光" : "温";
          return `
            <button
              type="button"
              class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""} ${editKey === key ? "is-edit-target" : ""} ${isCurveSeriesHidden(key) ? "is-hidden-series" : ""}"
              data-curve-tree-type="environment"
              data-curve-key="${escapeHtml(key)}"
              aria-pressed="${selectedSet.has(key) ? "true" : "false"}"
            >
              <span>${shortLabel}</span>
              <small>${escapeHtml(meta.unit)}</small>
            </button>
          `;
        }).join("")}
      </div>
    </div>
    <div class="tree-group">
      <button
        type="button"
        class="tree-node tree-type ${loadSelected ? "is-active" : loadPartial ? "is-parent-active" : ""}"
        data-curve-tree-type="load"
        data-curve-family="load"
        aria-pressed="${loadSelected ? "true" : "false"}"
      >
        <span>负荷曲线</span>
        <strong>${loadDevices.length}</strong>
      </button>
      <div id="curveLoadTree" class="tree-children">
        ${loadDevices.map((dev) => {
          const key = loadCurveKey(dev.dev_name);
          return `
            <button
              type="button"
              class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""} ${editKey === key ? "is-edit-target" : ""} ${isCurveSeriesHidden(key) ? "is-hidden-series" : ""}"
              data-curve-tree-type="load"
              data-curve-key="${escapeHtml(key)}"
              aria-pressed="${selectedSet.has(key) ? "true" : "false"}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(dev.dev_type)}</small>
            </button>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function setActiveCurve(key, shouldRender = true) {
  const nextKey = key || "wind_speed_mps";
  setSelectedCurves([nextKey], nextKey, shouldRender);
}

function renderCurveEditor(force = false) {
  const seriesChanged = ensureCurveSeries();
  if (seriesChanged) syncCurvePayload(false);
  renderCurveTree();
  renderCurveModeControls();
  updateCurveModeLabels();
  const activeEditor = document.activeElement?.closest?.("#hourlyCurveTable");
  if (!force && activeEditor) return;
  drawCurves();
  renderHourlyTable();
}

function generateCurves(jitter = 0, mode = state.curveMode, shouldRender = true) {
  state.curveMode = CURVE_MODES[mode] ? mode : "year";
  const config = curveModeConfig();
  const pointCount = curvePointCount();
  state.curveSeries = Object.fromEntries(ENV_CURVE_KEYS.map((key) => [key, new Array(pointCount)]));
  const windPeak = 38 + jitter;
  const solarPeak = 720;
  const tempMean = -18;
  const loadBase = 180;
  const loadDevices = curveLoadDevices();
  loadDevices.forEach((dev) => {
    state.curveSeries[loadCurveKey(dev.dev_name)] = new Array(pointCount);
  });
  for (let i = 0; i < pointCount; i += 1) {
    const minute = pointMinute(i);
    const day = (minute % (24 * 60)) / (24 * 60);
    const year = minute / config.durationMinutes;
    const season = state.curveMode === "year" ? Math.sin((year - 0.18) * Math.PI * 2) : 0;
    const gust = Math.sin(day * Math.PI * 2 * 5 + 0.8) * 4 + Math.sin(day * Math.PI * 2 * 11 + year * 9) * 2;
    const wind = clamp(windPeak * (0.58 + 0.28 * Math.sin(day * Math.PI * 2 - 0.7) + 0.10 * season) + gust, 0, 50);
    const daylight = Math.max(0, Math.sin((day - 0.25) * Math.PI * 2));
    const solarSeason = state.curveMode === "year" ? clamp(0.58 + 0.42 * season, 0.05, 1.0) : 1.0;
    const tempSeason = state.curveMode === "year" ? 9 * season : 0;
    const sunShape = daylight * solarSeason;
    const temp = tempMean + tempSeason + 6 * Math.sin((day - 0.33) * Math.PI * 2);
    const load = loadBase * (0.84 + 0.18 * Math.sin((day - 0.18) * Math.PI * 2) + 0.08 * Math.sin(day * Math.PI * 8));
    state.curveSeries.wind_speed_mps[i] = Number(wind.toFixed(2));
    state.curveSeries.solar_irradiance_w_m2[i] = Number((solarPeak * sunShape).toFixed(1));
    state.curveSeries.air_temp_c[i] = Number(temp.toFixed(2));
    loadDevices.forEach((dev, loadIndex) => {
      const offset = 1 + loadIndex * 0.035;
      state.curveSeries[loadCurveKey(dev.dev_name)][i] = Number(Math.max(20, load * offset).toFixed(2));
    });
  }
  state.curveSeries.load_kw = [...state.curveSeries[loadCurveKey(loadDevices[0]?.dev_name)]];
  state.curveSeriesByMode[state.curveMode] = state.curveSeries;
  syncCurvePayload(false);
  if (shouldRender) renderCurveEditor(true);
}

function syncCurvePayload(shouldStoreSeries = true) {
  ensureCurveSeries();
  const config = curveModeConfig();
  state.weatherPoints = [];
  state.loadPoints = [];
  state.loadPointsByName = {};
  curveLoadDevices().forEach((dev) => {
    state.loadPointsByName[dev.dev_name] = [];
  });
  for (let i = 0; i < config.pointCount; i += 1) {
    const minute = Number(pointMinute(i).toFixed(4));
    const year = minute / config.durationMinutes;
    state.weatherPoints.push({
      minute,
      wind_speed_mps: roundCurveValue("wind_speed_mps", state.curveSeries.wind_speed_mps[i]),
      air_temp_c: roundCurveValue("air_temp_c", state.curveSeries.air_temp_c[i]),
      air_pressure_hpa: Number((955 + 10 * Math.sin(year * Math.PI * 2 + 0.4)).toFixed(2)),
      solar_irradiance_w_m2: roundCurveValue("solar_irradiance_w_m2", state.curveSeries.solar_irradiance_w_m2[i]),
      humidity_pct: Number((68 + 9 * Math.sin(year * Math.PI * 2 + 2.2)).toFixed(2)),
    });
    curveLoadDevices().forEach((dev, loadIndex) => {
      const key = loadCurveKey(dev.dev_name);
      const point = { minute, p_kw: roundCurveValue(key, state.curveSeries[key]?.[i] ?? 0) };
      state.loadPointsByName[dev.dev_name].push(point);
      if (loadIndex === 0) state.loadPoints.push(point);
    });
  }
  if (shouldStoreSeries) state.curveSeriesByMode[state.curveMode] = state.curveSeries;
}

function roundCurveValue(key, value) {
  const meta = curveMetaForKey(key);
  return Number(clamp(Number(value), meta.min, meta.max).toFixed(meta.digits));
}

function resizeCurveCanvas() {
  const canvas = $("curveEditorChart");
  if (!canvas) return false;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.round(rect.width || canvas.clientWidth || canvas.width));
  const height = Math.max(240, Math.round(rect.height || canvas.clientHeight || canvas.height));
  if (canvas.width === width && canvas.height === height) return false;
  canvas.width = width;
  canvas.height = height;
  return true;
}

function curvePlot(canvas) {
  if (canvas.width < 640) {
    return { left: 34, right: 12, top: 58, bottom: 30 };
  }
  return CURVE_PLOT;
}

function valueToY(value, meta, canvas) {
  const plot = curvePlot(canvas);
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const ratio = (clamp(value, meta.min, meta.max) - meta.min) / (meta.max - meta.min);
  return bottom - ratio * (bottom - top);
}

function yToValue(y, meta, canvas) {
  const plot = curvePlot(canvas);
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const ratio = (bottom - clamp(y, top, bottom)) / (bottom - top);
  return roundCurveValue(meta.key, meta.min + ratio * (meta.max - meta.min));
}

function drawCurveXAxis(ctx, canvas, plot) {
  const width = canvas.width;
  const height = canvas.height;
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (state.curveMode === "year") {
    const monthStarts = [
      ["01月", 0],
      ["02月", 31],
      ["03月", 59],
      ["04月", 90],
      ["05月", 120],
      ["06月", 151],
      ["07月", 181],
      ["08月", 212],
      ["09月", 243],
      ["10月", 273],
      ["11月", 304],
      ["12月", 334],
    ];
    const monthStep = width < 560 ? 3 : width < 900 ? 2 : 1;
    monthStarts.forEach(([label, day], index) => {
      if (index % monthStep !== 0) return;
      const x = left + (day / 365) * (right - left);
      ctx.strokeStyle = index % 3 === 0 ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      ctx.fillText(label, x - 12, height - 12);
    });
    ctx.strokeStyle = "#c9d6dc";
    ctx.beginPath();
    ctx.moveTo(right, top);
    ctx.lineTo(right, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "right";
    ctx.fillText("年末", right, height - 12);
    ctx.textAlign = "left";
    return;
  }
  const hourStep = width < 480 ? 4 : width < 820 ? 3 : 2;
  for (let hour = 0; hour <= 24; hour += hourStep) {
    const x = left + (hour / 24) * (right - left);
    ctx.strokeStyle = hour % 6 === 0 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.fillText(`${String(hour).padStart(2, "0")}:00`, x - 14, height - 12);
  }
}

function drawCurves() {
  const canvas = $("curveEditorChart");
  if (!canvas) return;
  resizeCurveCanvas();
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const plot = curvePlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const allMetas = selectedCurveKeys().map(curveMetaForKey);
  const metas = allMetas.filter((meta) => !isCurveSeriesHidden(meta.key));
  const editKey = curveEditKey(metas.map((meta) => meta.key));
  const legendColumns = width < 560 ? 2 : Math.max(1, allMetas.length);
  const legendColumnWidth = (right - left) / legendColumns;
  state.curveLegendHitBoxes = [];
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = "#63717a";
  for (let i = 0; i <= 5; i += 1) {
    const y = top + i * ((bottom - top) / 5);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  drawCurveXAxis(ctx, canvas, plot);
  metas.forEach((meta) => {
    const values = state.curveSeries[meta.key] || [];
    const stride = Math.max(1, Math.floor(values.length / Math.max(1, (right - left) * 1.4)));
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = editKey && meta.key === editKey ? 3.5 : 2;
    ctx.beginPath();
    for (let i = 0; i < values.length; i += stride) {
      const x = left + (i / Math.max(1, values.length - 1)) * (right - left);
      const y = valueToY(values[i], meta, canvas);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    const lastX = right;
    const lastY = valueToY(values[values.length - 1] || 0, meta, canvas);
    ctx.lineTo(lastX, lastY);
    ctx.stroke();
  });
  allMetas.forEach((meta, metaIndex) => {
    const legendX = left + (metaIndex % legendColumns) * legendColumnWidth;
    const legendY = 20 + Math.floor(metaIndex / legendColumns) * 16;
    const hidden = isCurveSeriesHidden(meta.key);
    const labelText = `${meta.label} (${meta.unit})${hidden ? " 隐藏" : ""}`;
    state.curveLegendHitBoxes.push({
      key: meta.key,
      x: legendX - 6,
      y: legendY - 9,
      width: Math.min(legendColumnWidth - 8, ctx.measureText(labelText).width + 42),
      height: 16,
    });
    ctx.fillStyle = hidden ? "#9aa9af" : meta.color;
    ctx.fillRect(legendX, legendY, 18, 3);
    ctx.fillStyle = hidden ? "#9aa9af" : editKey === meta.key ? "#1f3037" : "#63717a";
    ctx.fillText(labelText, legendX + 26, legendY + 4);
  });
  drawCurveCursor(ctx, canvas, plot, metas);
}

function curveLegendKeyAtPointer(event) {
  const canvas = $("curveEditorChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCanvas(event);
  const hit = (state.curveLegendHitBoxes || []).find((box) => (
    pos.x >= box.x && pos.x <= box.x + box.width && pos.y >= box.y && pos.y <= box.y + box.height
  ));
  return hit?.key || "";
}

function pointerPositionOnCanvas(event) {
  const canvas = $("curveEditorChart");
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function curvePointIndexFromX(x, canvas) {
  const plot = curvePlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const pointCount = curvePointCount();
  return clamp(Math.round(((x - left) / (right - left)) * (pointCount - 1)), 0, pointCount - 1);
}

function curveXFromPointIndex(index, canvas) {
  const plot = curvePlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  return left + (clamp(index, 0, curvePointCount() - 1) / Math.max(1, curvePointCount() - 1)) * (right - left);
}

function setCurveCursorFromEvent(event, shouldDraw = true) {
  const canvas = $("curveEditorChart");
  if (!canvas) return;
  const pos = pointerPositionOnCanvas(event);
  const plot = curvePlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) {
    state.curveCursor = { visible: false, x: pos.x, y: pos.y, index: state.curveCursor.index || 0 };
    if (shouldDraw) drawCurves();
    return;
  }
  state.curveCursor = {
    visible: true,
    x: clamp(pos.x, left, right),
    y: clamp(pos.y, top, bottom),
    index: curvePointIndexFromX(pos.x, canvas),
  };
  if (shouldDraw) drawCurves();
}

function hideCurveCursor() {
  if (!state.curveCursor.visible) return;
  state.curveCursor.visible = false;
  drawCurves();
}

function drawCurveTooltipBox(ctx, x, y, width, height, radius = 8) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

function drawCurveCursor(ctx, canvas, plot, metas) {
  const cursor = state.curveCursor;
  if (!cursor.visible || !metas.length) return;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const index = clamp(cursor.index, 0, curvePointCount() - 1);
  const x = curveXFromPointIndex(index, canvas);
  const y = clamp(cursor.y, top, bottom);
  const tooltipMetas = metas.slice(0, 6);
  const extraCount = Math.max(0, metas.length - tooltipMetas.length);
  const timeLabel = formatCurveTableTime(pointMinute(index));
  const valueLines = tooltipMetas.map((meta) => {
    const value = roundCurveValue(meta.key, state.curveSeries[meta.key]?.[index] ?? 0);
    return { meta, text: `${meta.label}: ${value} ${meta.unit}` };
  });

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  tooltipMetas.forEach((meta) => {
    const values = state.curveSeries[meta.key] || [];
    if (!values.length) return;
    const markerY = valueToY(values[index], meta, canvas);
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, markerY, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = "12px Microsoft YaHei, Arial";
  const title = `时刻: ${timeLabel}`;
  const point = `点号: ${index + 1}`;
  const lineTexts = [title, point, ...valueLines.map((line) => line.text), extraCount ? `另有 ${extraCount} 条曲线` : ""].filter(Boolean);
  const tooltipWidth = Math.max(154, ...lineTexts.map((line) => ctx.measureText(line).width + 28));
  const lineHeight = 18;
  const tooltipHeight = 16 + lineTexts.length * lineHeight;
  let tooltipX = x + 14;
  let tooltipY = y + 14;
  if (tooltipX + tooltipWidth > right - 6) tooltipX = x - tooltipWidth - 14;
  if (tooltipY + tooltipHeight > bottom - 6) tooltipY = y - tooltipHeight - 14;
  tooltipX = clamp(tooltipX, left + 6, right - tooltipWidth - 6);
  tooltipY = clamp(tooltipY, top + 6, bottom - tooltipHeight - 6);

  ctx.shadowColor = "rgba(28, 45, 52, 0.18)";
  ctx.shadowBlur = 12;
  ctx.shadowOffsetY = 3;
  ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
  drawCurveTooltipBox(ctx, tooltipX, tooltipY, tooltipWidth, tooltipHeight);
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.strokeStyle = "rgba(171, 190, 198, 0.9)";
  ctx.stroke();

  ctx.fillStyle = "#1f3037";
  ctx.font = "700 12px Microsoft YaHei, Arial";
  ctx.fillText(title, tooltipX + 10, tooltipY + 18);
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = "#63717a";
  ctx.fillText(point, tooltipX + 10, tooltipY + 36);
  valueLines.forEach((line, lineIndex) => {
    const textY = tooltipY + 54 + lineIndex * lineHeight;
    ctx.fillStyle = line.meta.color;
    ctx.fillRect(tooltipX + 10, textY - 7, 10, 3);
    ctx.fillStyle = "#314850";
    ctx.fillText(line.text, tooltipX + 26, textY);
  });
  if (extraCount) {
    ctx.fillStyle = "#63717a";
    ctx.fillText(`另有 ${extraCount} 条曲线`, tooltipX + 10, tooltipY + 54 + valueLines.length * lineHeight);
  }
  ctx.restore();
}

function curveKeyAtPointer(event) {
  const canvas = $("curveEditorChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCanvas(event);
  const plot = curvePlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) return "";
  const index = curvePointIndexFromX(pos.x, canvas);
  const tolerance = canvas.width < 640 ? 18 : 14;
  let bestKey = "";
  let bestDistance = Infinity;
  visibleCurveMetas().forEach((meta) => {
    const values = state.curveSeries[meta.key] || [];
    if (!values.length) return;
    const distance = Math.abs(valueToY(values[index], meta, canvas) - pos.y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestKey = meta.key;
    }
  });
  return bestDistance <= tolerance ? bestKey : "";
}

function applyCurveDrag(event) {
  const canvas = $("curveEditorChart");
  const editKey = curveEditKey();
  const meta = curveMetaForKey(editKey);
  const values = state.curveSeries[editKey] || [];
  if (!canvas || !meta || !values.length) return;
  const pos = pointerPositionOnCanvas(event);
  const index = curvePointIndexFromX(pos.x, canvas);
  const targetValue = yToValue(pos.y, meta, canvas);
  const brush = Math.max(12, Math.round(curvePointCount() / 300));
  for (let offset = -brush; offset <= brush; offset += 1) {
    const point = index + offset;
    if (point < 0 || point >= values.length) continue;
    const weight = 1 - Math.abs(offset) / (brush + 1);
    values[point] = roundCurveValue(editKey, values[point] * (1 - weight) + targetValue * weight);
  }
  syncCurvePayload();
  drawCurves();
  $("curveStatus").textContent = "已修改";
}

function formatCurveTableTime(minute) {
  if (state.curveMode === "year") {
    const dayOfYear = Math.floor(minute / (24 * 60));
    const hour = Math.floor((minute % (24 * 60)) / 60);
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let month = 0;
    let day = dayOfYear;
    while (month < monthDays.length - 1 && day >= monthDays[month]) {
      day -= monthDays[month];
      month += 1;
    }
    return `${String(month + 1).padStart(2, "0")}-${String(day + 1).padStart(2, "0")} ${String(hour).padStart(2, "0")}:00`;
  }
  const total = Math.round(minute);
  const hour = Math.floor(total / 60);
  const minutePart = total % 60;
  return `${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`;
}

function renderHourlyTable() {
  const container = $("hourlyCurveTable");
  if (!container) return;
  const metas = visibleCurveMetas();
  const pointCount = curvePointCount();
  container.innerHTML = `
    <table class="curve-table">
      <thead>
        <tr>
          <th>时刻</th>
          ${metas.map((meta) => `<th>${escapeHtml(meta.label)}<small>${escapeHtml(meta.unit)}</small></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${Array.from({ length: pointCount }, (_unused, index) => `
          <tr>
            <td>${formatCurveTableTime(pointMinute(index))}</td>
            ${metas.map((meta) => `
              <td
                contenteditable="true"
                data-index="${index}"
                data-key="${escapeHtml(meta.key)}"
              >${roundCurveValue(meta.key, state.curveSeries[meta.key]?.[index] ?? 0)}</td>
            `).join("")}
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function applyHourlyTableEdit(cell) {
  const index = Number(cell.dataset.index);
  const key = cell.dataset.key;
  const meta = curveMetaForKey(key);
  const rawValue = Number(cell.textContent);
  if (!meta || !Number.isFinite(rawValue) || !Number.isInteger(index)) {
    renderHourlyTable();
    return;
  }
  const value = roundCurveValue(key, rawValue);
  const values = state.curveSeries[key] || [];
  if (index >= 0 && index < values.length) values[index] = value;
  syncCurvePayload();
  drawCurves();
  renderHourlyTable();
  $("curveStatus").textContent = "已修改";
}

function initCurveEditor() {
  const canvas = $("curveEditorChart");
  const table = $("hourlyCurveTable");
  if (!canvas || !table) return;
  let lastPointerDownAt = 0;
  const handleCurvePointerDown = (event) => {
    if (event.type === "pointerdown") {
      lastPointerDownAt = Date.now();
    } else if (Date.now() - lastPointerDownAt < 80) {
      return;
    }
    setCurveCursorFromEvent(event, false);
    if (event.button === 2) {
      event.preventDefault();
      cancelCurveEditSelection();
      return;
    }
    if (event.button !== 0) return;
    const legendKey = curveLegendKeyAtPointer(event);
    if (legendKey) {
      event.preventDefault();
      toggleCurveSeriesVisibility(legendKey, true);
      return;
    }
    const hitKey = curveKeyAtPointer(event);
    if (!hitKey) return;
    event.preventDefault();
    setCurveEditKey(hitKey);
    state.isCurveDragging = true;
    if (event.pointerId !== undefined && canvas.setPointerCapture) {
      canvas.setPointerCapture(event.pointerId);
    }
  };
  const handleCurvePointerMove = (event) => {
    setCurveCursorFromEvent(event, !state.isCurveDragging);
    if (state.isCurveDragging) {
      event.preventDefault();
      applyCurveDrag(event);
    }
  };
  canvas.addEventListener("pointerdown", handleCurvePointerDown);
  canvas.addEventListener("mousedown", handleCurvePointerDown);
  canvas.addEventListener("pointermove", handleCurvePointerMove);
  canvas.addEventListener("mousemove", handleCurvePointerMove);
  canvas.addEventListener("pointerleave", () => {
    if (!state.isCurveDragging) hideCurveCursor();
  });
  canvas.addEventListener("mouseleave", () => {
    if (!state.isCurveDragging) hideCurveCursor();
  });
  canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    cancelCurveEditSelection();
  });
  canvas.addEventListener("pointercancel", cancelCurveEditSelection);
  const handleCurvePointerUp = () => {
    const wasDragging = state.isCurveDragging;
    state.isCurveDragging = false;
    if (wasDragging) renderHourlyTable();
  };
  window.addEventListener("pointerup", handleCurvePointerUp);
  window.addEventListener("mouseup", handleCurvePointerUp);
  $("activeCurve").addEventListener("change", (event) => setActiveCurve(event.target.value));
  window.addEventListener("resize", drawCurves);
  table.addEventListener("blur", (event) => {
    if (event.target.matches("[data-index][data-key]")) {
      applyHourlyTableEdit(event.target);
    }
  }, true);
  table.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("[data-index][data-key]")) {
      event.preventDefault();
      event.target.blur();
    }
  });
}

function initRuntimeMonitor() {
  const windowSelect = $("runtimeTraceWindow");
  if (windowSelect) {
    state.runtimeTraceWindowMinutes = Number(windowSelect.value) || state.runtimeTraceWindowMinutes;
    windowSelect.addEventListener("change", (event) => {
      state.runtimeTraceWindowMinutes = Number(event.target.value) || 60;
      drawRuntimeTraceChart();
    });
  }
  initTraceChartInteractions("runtimeTrace", "runtimeTraceChart", drawRuntimeTraceChart);
  window.addEventListener("resize", drawRuntimeTraceChart);
}

function initMeasurementMonitor() {
  const windowSelect = $("measurementTraceWindow");
  if (windowSelect) {
    state.measurementTraceWindowMinutes = Number(windowSelect.value) || state.measurementTraceWindowMinutes;
    windowSelect.addEventListener("change", (event) => {
      state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
      drawMeasurementTraceChart();
    });
  }
  initTraceChartInteractions("measurementTrace", "measurementTraceChart", drawMeasurementTraceChart);
  window.addEventListener("resize", drawMeasurementTraceChart);
}

async function refresh() {
  try {
    const snapshot = await api("/api/snapshot");
    state.snapshot = snapshot;
    renderSnapshot(snapshot);
  } catch (error) {
    console.error("模拟台快照刷新失败", error);
    $("simState").textContent = "offline";
    $("solverInfo").textContent = "连接失败";
  }
}

function latestRuntimeLog(snapshot, type) {
  return [...(snapshot.runtime_logs || [])].reverse().find((item) => item?.type === type) || null;
}

function logDetailText(log) {
  return Array.isArray(log?.detail) ? log.detail.join(" ") : String(log?.detail || "");
}

function matchedNumber(text, pattern) {
  const match = pattern.exec(text || "");
  return match ? Number(match[1]) : null;
}

function storageSocPercentFromText(text) {
  const directSoc = matchedNumber(text, /储能SOC\s*平均\s*([-+\d.]+)%/);
  if (Number.isFinite(directSoc)) return directSoc;
  const values = [...String(text || "").matchAll(/ESS\.[^=，,\s]+=\s*([-+\d.]+)/g)]
    .map((match) => Number(match[1]))
    .filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  const average = values.reduce((total, value) => total + value, 0) / values.length;
  return average <= 1 ? average * 100 : average;
}

function parsePowerFlowOverview(snapshot) {
  const log = latestRuntimeLog(snapshot, "潮流计算");
  const text = logDetailText(log);
  const controlText = logDetailText(latestRuntimeLog(snapshot, "控制响应"));
  const soc = storageSocPercentFromText(text);
  return {
    log,
    wind: matchedNumber(text, /风力发电总功率\s*([-+\d.]+)/),
    solar: matchedNumber(text, /光伏发电总功率\s*([-+\d.]+)/),
    diesel: matchedNumber(text, /柴油发电总功率\s*([-+\d.]+)/),
    load: matchedNumber(text, /负荷用电总功率\s*([-+\d.]+)/),
    storageDischarge: matchedNumber(text, /储能发电总功率\s*([-+\d.]+)/),
    storageCharge: matchedNumber(text, /储能充电总功率\s*([-+\d.]+)/),
    soc: Number.isFinite(soc) ? soc : storageSocPercentFromText(controlText),
    generation: matchedNumber(text, /电源发电总功率\s*([-+\d.]+)/),
    consumption: matchedNumber(text, /用电及充电总功率\s*([-+\d.]+)/),
    balance: matchedNumber(text, /功率差额\s*([-+\d.]+)/),
  };
}

function overviewCurveBoundary(snapshot) {
  const curves = snapshot.curves || {};
  const weather = Array.isArray(curves.weather) ? curves.weather : [];
  const step = Math.max(1, Number(curves.time_step_minutes) || 1);
  const targetMinute = curves.mode === "year"
    ? Number(snapshot.clock?.absolute_minute || 0)
    : Number(snapshot.clock?.minute || 0);
  const index = weather.length ? Math.round(targetMinute / step) % weather.length : 0;
  const point = weather[index] || {};
  const loadTotal = Object.values(curves.loads || {}).reduce((total, points) => {
    if (!Array.isArray(points) || !points.length) return total;
    const loadPoint = points[index % points.length] || {};
    return total + (Number(loadPoint.p_kw ?? loadPoint.value ?? loadPoint.load_kw) || 0);
  }, 0);
  return { point, loadTotal, index };
}

function formatOverviewNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toFixed(2);
}

function overviewPowerText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} kW` : "--";
}

function overviewPercentText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)}%` : "--";
}

function overviewFlowPowerValue(value) {
  const number = Math.abs(Number(value));
  return Number.isFinite(number) ? number : 0;
}

function overviewClamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function overviewLoadFlowColor(greenPowerShare) {
  const percent = overviewClamp(Number(greenPowerShare), 0, 100);
  if (!Number.isFinite(percent)) return "#4978c4";
  const hue = 2 + percent * 1.18;
  return `hsl(${hue.toFixed(1)}, 62%, 42%)`;
}

function overviewFlowStyle(powerValue, maxPower) {
  const power = overviewFlowPowerValue(powerValue);
  const base = Math.max(1, overviewFlowPowerValue(maxPower));
  const active = power > 1e-6;
  const ratio = active ? overviewClamp(Math.sqrt(power / base), 0, 1) : 0;
  const thickness = active ? 2 + ratio * 6 : 2;
  const headSize = active ? 8 + ratio * 9 : 8;
  const headHalf = active ? 5 + ratio * 5 : 5;
  const opacity = active ? 0.58 + ratio * 0.34 : 0.24;
  const duration = active ? 1.4 - ratio * 0.42 : 1.4;
  return {
    active,
    thickness: `${thickness.toFixed(2)}px`,
    headSize: `${headSize.toFixed(2)}px`,
    headHalf: `${headHalf.toFixed(2)}px`,
    opacity: opacity.toFixed(2),
    duration: `${duration.toFixed(2)}s`,
  };
}

function setOverviewFlowVisual(id, powerValue, maxPower, color) {
  const element = $(id);
  if (!element) return;
  const visual = overviewFlowStyle(powerValue, maxPower);
  element.dataset.flowActive = visual.active ? "true" : "false";
  element.style.setProperty("--flow-color", color);
  element.style.setProperty("--flow-thickness", visual.thickness);
  element.style.setProperty("--flow-head-size", visual.headSize);
  element.style.setProperty("--flow-head-half", visual.headHalf);
  element.style.setProperty("--flow-opacity", visual.opacity);
  element.style.setProperty("--flow-duration", visual.duration);
}

function renderEnergyFlowVisuals(power, storagePower, greenPowerShare) {
  const windPower = overviewFlowPowerValue(power.wind);
  const solarPower = overviewFlowPowerValue(power.solar);
  const dieselPower = overviewFlowPowerValue(power.diesel);
  const loadPower = overviewFlowPowerValue(power.load);
  const storageMagnitude = overviewFlowPowerValue(storagePower);
  const renewablePower = windPower + solarPower + Math.max(0, Number(storagePower) || 0);
  const maxPower = Math.max(1, windPower, solarPower, dieselPower, loadPower, storageMagnitude, renewablePower);
  const greenColor = "#2f9e62";
  const dieselColor = "#c84f4f";
  const loadColor = overviewLoadFlowColor(greenPowerShare);
  setOverviewFlowVisual("overviewFlowWindNode", windPower, maxPower, greenColor);
  setOverviewFlowVisual("overviewFlowSolarNode", solarPower, maxPower, greenColor);
  setOverviewFlowVisual("overviewFlowDieselNode", dieselPower, maxPower, dieselColor);
  setOverviewFlowVisual("overviewFlowLoadNode", loadPower, maxPower, loadColor);
  setOverviewFlowVisual("overviewStorageFlowLink", storageMagnitude, maxPower, greenColor);
  setOverviewFlowVisual("overviewEnergyMainTrunk", renewablePower, maxPower, greenColor);
}

function setOverviewText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function overviewBottomHeightBounds() {
  const dashboard = document.querySelector(".overview-dashboard");
  const dashboardHeight = dashboard?.getBoundingClientRect().height || 0;
  const dashboardStyle = dashboard ? getComputedStyle(dashboard) : null;
  const mainGrid = document.querySelector(".overview-main-grid");
  const statusHeight = document.querySelector(".overview-status-panel")?.getBoundingClientRect().height || 68;
  const splitterHeight = $("overviewBottomSplitter")?.getBoundingClientRect().height || 10;
  const mainMinHeight = Number.parseFloat(mainGrid ? getComputedStyle(mainGrid).minHeight : "") || 390;
  const rowGap = Number.parseFloat(dashboardStyle?.rowGap || dashboardStyle?.gap || "") || 12;
  const reservedHeight = statusHeight + mainMinHeight + splitterHeight + rowGap * 3;
  const dynamicMax = dashboardHeight > 0 ? dashboardHeight - reservedHeight : OVERVIEW_BOTTOM_MAX_HEIGHT;
  const maxHeight = Math.max(
    OVERVIEW_BOTTOM_MIN_HEIGHT,
    Math.min(OVERVIEW_BOTTOM_MAX_HEIGHT, dynamicMax),
  );
  return { min: OVERVIEW_BOTTOM_MIN_HEIGHT, max: maxHeight };
}

function applyOverviewBottomHeight(value, persist = false) {
  const bounds = overviewBottomHeightBounds();
  const numericValue = Number(value);
  const nextHeight = Math.round(clamp(
    Number.isFinite(numericValue) ? numericValue : OVERVIEW_BOTTOM_DEFAULT_HEIGHT,
    bounds.min,
    bounds.max,
  ));
  state.overviewBottomHeight = nextHeight;
  const dashboard = document.querySelector(".overview-dashboard");
  if (dashboard) dashboard.style.setProperty("--overview-bottom-height", `${nextHeight}px`);
  const splitter = $("overviewBottomSplitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    splitter.setAttribute("aria-valuenow", String(nextHeight));
    splitter.setAttribute("aria-valuetext", `${nextHeight}px`);
  }
  if (persist) localStorage.setItem(OVERVIEW_BOTTOM_HEIGHT_KEY, String(nextHeight));
}

function beginOverviewBottomSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = $("overviewBottomSplitter");
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (!splitter || !bottomGrid) return;
  event.preventDefault();
  const currentHeight = bottomGrid.getBoundingClientRect().height || state.overviewBottomHeight;
  state.overviewBottomSplitDrag = {
    pointerId: event.pointerId,
    startY: event.clientY,
    startHeight: currentHeight,
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-overview-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or cancelled pointer events do not always have capturable pointers.
    }
  }
}

function handleOverviewBottomSplitterDrag(event) {
  const drag = state.overviewBottomSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  applyOverviewBottomHeight(drag.startHeight - (event.clientY - drag.startY));
}

function finishOverviewBottomSplitterDrag(event) {
  const drag = state.overviewBottomSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = $("overviewBottomSplitter");
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be gone if the pointer left the window.
      }
    }
  }
  document.body.classList.remove("is-overview-splitter-dragging");
  state.overviewBottomSplitDrag = null;
  applyOverviewBottomHeight(state.overviewBottomHeight, true);
}

function handleOverviewBottomSplitterKeydown(event) {
  let nextHeight = null;
  if (event.key === "ArrowUp") nextHeight = state.overviewBottomHeight + 16;
  if (event.key === "ArrowDown") nextHeight = state.overviewBottomHeight - 16;
  if (event.key === "PageUp") nextHeight = state.overviewBottomHeight + 48;
  if (event.key === "PageDown") nextHeight = state.overviewBottomHeight - 48;
  if (event.key === "Home") nextHeight = OVERVIEW_BOTTOM_MIN_HEIGHT;
  if (event.key === "End") nextHeight = overviewBottomHeightBounds().max;
  if (nextHeight === null) return;
  event.preventDefault();
  applyOverviewBottomHeight(nextHeight, true);
}

function initOverviewBottomSplitter() {
  const splitter = $("overviewBottomSplitter");
  if (!splitter) return;
  applyOverviewBottomHeight(state.overviewBottomHeight);
  if (splitter.dataset.splitterReady === "true") return;
  splitter.dataset.splitterReady = "true";
  splitter.addEventListener("pointerdown", beginOverviewBottomSplitterDrag);
  splitter.addEventListener("keydown", handleOverviewBottomSplitterKeydown);
  window.addEventListener("pointermove", handleOverviewBottomSplitterDrag);
  window.addEventListener("pointerup", finishOverviewBottomSplitterDrag);
  window.addEventListener("pointercancel", finishOverviewBottomSplitterDrag);
  window.addEventListener("resize", () => applyOverviewBottomHeight(state.overviewBottomHeight, true));
}

function renderOverviewEvents(snapshot) {
  const container = $("commandInbox");
  if (!container) return;
  const logs = [...(snapshot.runtime_logs || [])].slice(-3).reverse();
  if (logs.length) {
    container.innerHTML = logs.map((item) => `
      <div class="overview-event-item">
        <time>${escapeHtml(item.simu_time || item.sim_time || "--")}</time>
        <strong>${escapeHtml(item.type || "运行")}</strong>
        <span title="${escapeHtml(logDetailText(item))}">${escapeHtml(item.result || logDetailText(item) || "完成")}</span>
      </div>
    `).join("");
    return;
  }
  container.innerHTML = '<div class="overview-event-item"><time>--</time><strong>系统</strong><span>等待启动仿真</span></div>';
}

function activeRuntimeCommandKeySet(snapshot = state.snapshot || {}) {
  const keys = new Set();
  activeCommandHistory(snapshot).forEach((entry) => {
    const normalized = entry.normalized || {};
    const payload = entry.payload || {};
    const runItems = normalized.run_status || payload.run_status || payload.runStatus || [];
    const setItems = normalized.set_values || payload.set_values || payload.setValues || payload.setpoints || [];
    if (Array.isArray(runItems)) {
      runItems.forEach((item) => {
        if (!item?.dev_type || !item?.dev_name) return;
        if (item.run_stat !== undefined && item.run_stat !== "") {
          keys.add(["remote_control", item.dev_type, item.dev_name, "run_stat"].join("|"));
        }
        if (Object.prototype.hasOwnProperty.call(item, "status")) {
          keys.add(["remote_control", item.dev_type, item.dev_name, "status"].join("|"));
        }
      });
    }
    if (Array.isArray(setItems)) {
      setItems.forEach((item) => {
        if (!item?.dev_type || !item?.dev_name || !item?.set_type) return;
        keys.add(["remote_adjustment", item.dev_type, item.dev_name, item.set_type].join("|"));
      });
    }
  });
  return keys;
}

function overviewActiveRuntimeCommandRows(snapshot = state.snapshot || {}) {
  const activeKeys = activeRuntimeCommandKeySet(snapshot);
  if (!activeKeys.size) return [];
  return runtimeCommandRowsForDevices(controlDefinitionDevices(snapshot), snapshot.measurements || {})
    .filter((row) => {
      return activeKeys.has(runtimeCommandTraceKey(row)) && commandTimeInfoAvailable(row.receive_time);
    });
}

function renderOverviewActiveCommands(snapshot) {
  const container = $("overviewActiveCommandTable");
  const summary = $("overviewActiveCommandSummary");
  if (!container) return [];
  const rows = overviewActiveRuntimeCommandRows(snapshot);
  if (summary) summary.textContent = `${rows.length} 条有效指令`;
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前无有效遥控/遥调指令</div>';
    return rows;
  }
  container.innerHTML = `
    <table class="overview-command-table">
      <thead>
        <tr>
          <th>类型</th>
          <th>设备</th>
          <th>指令项</th>
          <th>控制指令</th>
          <th>接收本机时刻</th>
          <th>接收仿真时刻</th>
          <th>实时值</th>
          <th>量测值</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr title="${escapeHtml(runtimeCommandTraceLabel(row))}">
            <td>${escapeHtml(row.category || "--")}</td>
            <td>${escapeHtml(row.device?.dev_name || "--")}</td>
            <td>${escapeHtml(row.command || "--")} <small class="command-set-type">${escapeHtml(row.set_type || "")}</small></td>
            <td class="numeric-cell">${escapeHtml(row.command_text || "--")}</td>
            <td class="mono-cell">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
            <td class="mono-cell">${escapeHtml(row.receive_time?.simu_time || "--")}</td>
            <td class="numeric-cell">${escapeHtml(row.real_text || "--")}</td>
            <td class="numeric-cell">${escapeHtml(row.scada_text || "--")}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  return rows;
}

function renderOverviewDashboard(snapshot) {
  const clock = snapshot.clock || {};
  const stateLabels = { running: "运行中", paused: "已暂停", stopped: "已停止" };
  const boundary = overviewCurveBoundary(snapshot);
  const power = parsePowerFlowOverview(snapshot);
  const devices = snapshot.devices || [];
  const onlineDevices = devices.filter((device) => Number(device.run_stat ?? 1) !== 0).length;
  const totalMeasurements = Number(snapshot.summary?.scada_count || 0);
  const validMeasurements = Number(snapshot.summary?.valid_scada_count || 0);
  const result = snapshot.result || {};
  const activeOverviewCommands = renderOverviewActiveCommands(snapshot);
  const stateDot = $("overviewStateDot");
  setOverviewText("overviewState", stateLabels[clock.state] || clock.state || "未知");
  if (stateDot) {
    stateDot.classList.toggle("is-running", clock.state === "running");
    stateDot.classList.toggle("is-paused", clock.state === "paused");
  }
  setOverviewText("overviewModel", snapshot.model?.name || snapshot.model?.id || "--");
  setOverviewText("overviewMode", snapshot.curves?.mode === "year" ? "年仿真" : "日仿真");
  setOverviewText("overviewStep", `${formatOverviewNumber(clock.step_minutes || 1)} min`);
  setOverviewText("metricScada", validMeasurements);
  setOverviewText("overviewMeasurementTotal", totalMeasurements);
  setOverviewText("metricCommands", snapshot.summary?.command_count || 0);
  setOverviewText("metricAlarms", snapshot.summary?.alarm_count || 0);
  setOverviewText("overviewBoundaryTime", formatSimulationClock(clock));
  setOverviewText("overviewWindSpeed", Number.isFinite(Number(boundary.point.wind_speed_mps)) ? `${formatOverviewNumber(boundary.point.wind_speed_mps)} m/s` : "--");
  setOverviewText("overviewIrradiance", Number.isFinite(Number(boundary.point.solar_irradiance_w_m2)) ? `${formatOverviewNumber(boundary.point.solar_irradiance_w_m2)} W/m²` : "--");
  setOverviewText("overviewTemperature", Number.isFinite(Number(boundary.point.air_temp_c)) ? `${formatOverviewNumber(boundary.point.air_temp_c)} ℃` : "--");
  setOverviewText("overviewLoadBoundary", overviewPowerText(boundary.loadTotal));
  setOverviewText("overviewOnlineDevices", `${onlineDevices}/${devices.length} 台`);
  setOverviewText("overviewActiveCommands", `${activeOverviewCommands.length} 条`);
  const storagePower = Number.isFinite(power.storageDischarge) && Number.isFinite(power.storageCharge)
    ? power.storageDischarge - power.storageCharge
    : null;
  const storageFlow = storagePower === null ? "idle" : storagePower > 0 ? "discharge" : storagePower < 0 ? "charge" : "idle";
  const storageNode = $("overviewStorageFlowNode");
  if (storageNode) storageNode.dataset.storageFlow = storageFlow;
  const storageLink = $("overviewStorageFlowLink");
  if (storageLink) storageLink.dataset.storageFlow = storageFlow;
  setOverviewText("overviewFlowWindPower", overviewPowerText(power.wind));
  setOverviewText("overviewFlowWindMeta", Number.isFinite(Number(boundary.point.wind_speed_mps)) ? `风速 ${formatOverviewNumber(boundary.point.wind_speed_mps)} m/s` : "风速 --");
  setOverviewText("overviewFlowSolarPower", overviewPowerText(power.solar));
  setOverviewText("overviewFlowSolarMeta", Number.isFinite(Number(boundary.point.solar_irradiance_w_m2)) ? `辐照 ${formatOverviewNumber(boundary.point.solar_irradiance_w_m2)} W/m²` : "辐照 --");
  setOverviewText("overviewFlowDieselPower", overviewPowerText(power.diesel));
  setOverviewText("overviewFlowStoragePower", overviewPowerText(storagePower));
  setOverviewText("overviewFlowStorageDirection", storagePower === null ? "待计算" : storagePower > 0 ? "放电" : storagePower < 0 ? "充电" : "静置");
  setOverviewText("overviewFlowSoc", Number.isFinite(power.soc) ? `${formatOverviewNumber(power.soc)}%` : "--");
  setOverviewText("overviewFlowLoadPower", overviewPowerText(power.load));
  setOverviewText("overviewFlowLoadMeta", Number.isFinite(boundary.loadTotal) ? `需求 ${overviewPowerText(boundary.loadTotal)}` : "需求 --");
  const greenPowerShare = Number.isFinite(power.diesel) && Number.isFinite(power.load) && Math.abs(power.load) > 1e-9
    ? (1.0 - power.diesel / power.load) * 100.0
    : null;
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderEnergyFlowVisuals(power, storagePower, greenPowerShare);
  setOverviewText("overviewCommandCount", `${activeOverviewCommands.length} 条控制指令`);
  renderOverviewEvents(snapshot);
}

function renderSnapshot(snapshot) {
  if (snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock);
  renderSystemParameters(snapshot);
  const runId = Number(snapshot.clock?.run_id ?? 0);
  if (state.traceRunId !== null && runId !== state.traceRunId) {
    state.runtimeTraceHistory = [];
    state.lastRuntimeTraceKey = "";
    state.measurementTraceHistory = [];
    state.lastMeasurementTraceKey = "";
  }
  state.traceRunId = runId;
  if (state.curvesLoadedModelId !== state.activeModelId) {
    loadCurvesFromSnapshot(snapshot.curves, state.activeModelId);
  }
  $("solverInfo").textContent = snapshot.result.solver_info || "待运行";
  renderOverviewDashboard(snapshot);
  appendRuntimeLog(snapshot);
  appendRuntimeTrace(snapshot);
  appendMeasurementTrace(snapshot);
  renderRuntimeLogs();
  renderMeasurementCompareTable();
  renderGridModelPage();
  if (!state.settingsLoaded) {
    state.deviceFaults = [...(snapshot.settings?.device_faults || [])];
    state.measurementFaults = [...(snapshot.settings?.measurement_faults || [])];
    state.settingsLoaded = true;
  }
  renderRuntimeMonitor();
  renderCurveEditor();
  renderFaults();
  state.modes = syncModesFromDevices(snapshot.devices || [], [
    ...(snapshot.settings?.modes || []),
    ...state.modes,
  ]);
  renderModes();
}

function appendRuntimeLog(snapshot) {
  const backendLogs = snapshot.runtime_logs;
  if (Array.isArray(backendLogs)) {
    state.runtimeLogs = backendLogs
      .map((item, index) => normalizeRuntimeLog(item, index + 1))
      .sort((left, right) => Number(right.seq || 0) - Number(left.seq || 0))
      .slice(0, 300);
    state.runtimeLogSeq = state.runtimeLogs.reduce((maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0), state.runtimeLogSeq);
    return;
  }
  const clock = snapshot.clock || {};
  const result = snapshot.result || {};
  const summary = snapshot.summary || {};
  const signature = [
    clock.state,
    clock.time,
    clock.speed,
    result.solver_info,
    result.updated,
    result.missing,
    result.overlay_updates,
    summary.scada_count,
    summary.command_count,
    summary.alarm_count,
  ].join("|");
  if (signature === state.lastRuntimeLogKey) return;
  state.lastRuntimeLogKey = signature;
  state.runtimeLogSeq += 1;
  state.runtimeLogs.unshift(normalizeRuntimeLog({
    seq: state.runtimeLogSeq,
    wall_time: runtimeLogTime(),
    simu_time: clock.time || "--",
    type: "仿真状态",
    target: "潮流计算 / SCADA",
    result: clock.state || "--",
    level: result.missing ? "warn" : "info",
    detail: [
      `速度 x${clock.speed ?? "--"}`,
      `求解器 ${result.solver_info || "待运行"}`,
      `量测 ${summary.scada_count ?? 0} 条，命令 ${summary.command_count ?? 0} 条，告警 ${summary.alarm_count ?? 0} 条`,
      `更新 ${result.updated ?? 0} 条，缺失 ${result.missing ?? 0} 条，叠加修正 ${result.overlay_updates ?? 0} 条`,
    ],
  }));
  state.runtimeLogs = state.runtimeLogs.slice(0, 300);
}

function normalizeRuntimeLog(item, fallbackSeq = 0) {
  const detail = item.detail ?? [
    item.solver_info ? `求解器 ${item.solver_info}` : "",
    item.scada_count !== undefined ? `量测 ${item.scada_count}` : "",
    item.command_count !== undefined ? `命令 ${item.command_count}` : "",
    item.alarm_count !== undefined ? `告警 ${item.alarm_count}` : "",
    item.updated !== undefined || item.missing !== undefined ? `更新/缺失 ${item.updated ?? 0}/${item.missing ?? 0}` : "",
  ].filter(Boolean);
  return {
    seq: item.seq ?? fallbackSeq,
    wall_time: item.wall_time || item.record_time || "",
    simu_time: item.simu_time || item.sim_time || item.time || "--",
    type: item.type || (item.state ? "仿真状态" : ""),
    target: item.target || (item.solver_info ? "潮流计算 / SCADA" : ""),
    result: item.result || item.state || "",
    detail,
    level: item.level || (item.missing ? "warn" : "info"),
  };
}

function renderRuntimeLogs() {
  const container = $("runtimeLogTable");
  if (!container) return;
  syncRuntimeLogTypeFilter();
  const allLogs = filteredRuntimeLogs();
  const logs = pagedRuntimeLogs(allLogs);
  renderRuntimeLogPager(allLogs);
  $("runtimeLogSummary").textContent = state.runtimeLogTypeFilter === "all"
    ? `最近 ${state.runtimeLogs.length} 条`
    : `${allLogs.length}/${state.runtimeLogs.length} 条`;
  if (!allLogs.length) {
    container.innerHTML = '<div class="empty-state">暂无运行日志</div>';
    return;
  }
  container.innerHTML = `
    <table class="runtime-log-table">
      <thead>
        <tr>
          <th>本机时刻</th>
          <th>仿真时刻</th>
          <th>类型</th>
          <th>对象</th>
          <th>结果</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        ${logs.map((item) => `
          <tr class="runtime-log-row is-${escapeHtml(item.level || "info")}">
            <td class="mono-cell">${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time)}</td>
            <td>${escapeHtml(item.type)}</td>
            <td>${escapeHtml(item.target)}</td>
            <td>${escapeHtml(item.result)}</td>
            <td class="runtime-log-detail">${escapeHtml(runtimeLogDetailText(item.detail))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function definitionBlocks(kind, snapshot = state.snapshot || {}) {
  return snapshot.definitions?.[kind] || {};
}

function definedModelDevices(snapshot = state.snapshot || {}) {
  const blocks = definitionBlocks("model", snapshot);
  return Object.entries(blocks).flatMap(([blockName, block]) => {
    const headers = Array.isArray(block.headers) ? block.headers : [];
    return (block.rows || []).map((row, index) => {
      const raw = {};
      headers.forEach((header) => {
        raw[header] = row?.[header] ?? "";
      });
      const idx = raw.idx ?? row?.idx ?? index + 1;
      const definedName = raw.name || raw.dev_name || "";
      const name = definedName || (idx !== "" ? `${blockName}_${idx}` : `${blockName}_${index + 1}`);
      return {
        dev_type: blockName,
        dev_name: String(name || `${blockName}_${index + 1}`),
        idx,
        raw,
        __headers: headers,
        __definition_index: index,
      };
    });
  });
}

function gridModelDevices() {
  return definedModelDevices();
}

function gridModelFilterMatches(dev, filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" }) {
  if (filter.dev_type && filter.dev_type !== "all" && dev.dev_type !== filter.dev_type) return false;
  if (filter.dev_name && dev.dev_name !== filter.dev_name) return false;
  return true;
}

function filteredGridModelDevices(devices = gridModelDevices()) {
  return devices.filter((dev) => gridModelFilterMatches(dev));
}

function gridModelFilterLabel(filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" }) {
  if (filter.dev_type === "all") return "全部设备";
  if (filter.dev_name) return filter.dev_name;
  return filter.dev_type;
}

function formatModelParamValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function modelDeviceIndexValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.POSITIVE_INFINITY;
}

function compareModelRowsByIndex(left, right) {
  const indexCompare = modelDeviceIndexValue(left.idx ?? left.raw?.idx) - modelDeviceIndexValue(right.idx ?? right.raw?.idx);
  if (indexCompare) return indexCompare;
  return String(left.name || left.dev_name || "").localeCompare(String(right.name || right.dev_name || ""));
}

function modelAttributeRecordForDevice(dev) {
  const raw = dev.raw || {};
  const headers = Array.isArray(dev.__headers) ? dev.__headers : Object.keys(raw);
  const record = {
    dev_type: dev.dev_type || "--",
    dev_name: dev.dev_name || "--",
    idx: formatModelParamValue(raw.idx ?? dev.idx),
    name: formatModelParamValue(raw.name || dev.dev_name),
    __headers: headers,
  };
  headers.forEach((key) => {
    if (["idx", "name", "dev_name", "dev_type"].includes(key)) return;
    record[key] = formatModelParamValue(raw[key]);
  });
  return record;
}

function modelAttributeLabel(key) {
  const labels = {
    idx: "idx",
    name: "名称",
  };
  return labels[key] || key;
}

function modelAttributeColumns(records) {
  const fixed = ["idx", "name"];
  const seen = new Set([...fixed, "dev_type", "dev_name", "__headers"]);
  const keys = [];
  const appendKey = (key) => {
    if (!key || seen.has(key)) return;
    if (!records.some((record) => record[key] !== undefined && record[key] !== "--")) return;
    seen.add(key);
    keys.push(key);
  };
  records.forEach((record) => {
    (record.__headers || Object.keys(record)).forEach(appendKey);
  });
  return [...fixed, ...keys].map((key) => ({ key, label: modelAttributeLabel(key) }));
}

function groupedModelAttributeRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const devType = record.dev_type || "未分类";
    const rows = groups.get(devType) || [];
    rows.push(record);
    groups.set(devType, rows);
  });
  return Array.from(groups.entries())
    .map(([devType, rows]) => [
      devType,
      rows.sort(compareModelRowsByIndex),
    ])
    .sort(([left], [right]) => String(left).localeCompare(String(right)));
}

function renderModelAttributeTable(rows) {
  const columns = modelAttributeColumns(rows);
  return `
    <table class="model-param-table">
      <thead>
        <tr>
          ${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            ${columns.map((column) => `<td class="attr-value">${escapeHtml(row[column.key] ?? "--")}</td>`).join("")}
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renderGridModelDeviceTree() {
  const container = $("modelDeviceTree");
  if (!container) return;
  const devices = gridModelDevices();
  const filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices).map(([devType, items]) => [
    devType,
    [...items].sort(compareModelRowsByIndex),
  ]);
  $("modelTreeSummary").textContent = `${groupEntries.length} 类 · ${devices.length} 台`;
  container.innerHTML = `
    <button
      type="button"
      class="tree-node tree-root ${filter.dev_type === "all" ? "is-active" : ""}"
      data-model-tree-type="all"
      data-model-tree-name=""
    >
      <span>全部设备</span>
      <strong>${devices.length}</strong>
    </button>
    ${groupEntries.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("model", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${filter.dev_type === devType && !filter.dev_name ? "is-active" : filter.dev_type === devType ? "is-parent-active" : ""}"
          data-model-tree-type="${escapeHtml(devType)}"
          data-model-tree-name=""
          ${deviceTreeTypeAttrs("model", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => {
            const idx = formatModelParamValue(dev.idx ?? dev.raw?.idx);
            return `
            <button
              type="button"
              class="tree-node tree-child model-tree-child ${filter.dev_type === dev.dev_type && filter.dev_name === dev.dev_name ? "is-active" : ""}"
              data-model-tree-type="${escapeHtml(dev.dev_type)}"
              data-model-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span class="model-tree-idx">${escapeHtml(idx)}</span>
              <span class="model-tree-name">${escapeHtml(dev.dev_name)}</span>
            </button>
          `;
          }).join(""))}
      </div>
    `;
    }).join("")}
  `;
}

function runtimeLogTypes() {
  return Array.from(new Set(state.runtimeLogs.map((item) => String(item.type || "")).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncRuntimeLogTypeFilter() {
  const select = $("runtimeLogTypeFilter");
  if (!select) return;
  const types = runtimeLogTypes();
  if (state.runtimeLogTypeFilter !== "all" && !types.includes(state.runtimeLogTypeFilter)) {
    state.runtimeLogTypeFilter = "all";
  }
  select.innerHTML = ["<option value=\"all\">全部类型</option>", ...types.map((type) => (
    `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`
  ))].join("");
  select.value = state.runtimeLogTypeFilter;
}

function filteredRuntimeLogs() {
  if (state.runtimeLogTypeFilter === "all") return state.runtimeLogs;
  return state.runtimeLogs.filter((item) => item.type === state.runtimeLogTypeFilter);
}

function runtimeLogPageCount(logs = filteredRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  return Math.max(1, Math.ceil((logs || []).length / pageSize));
}

function pagedRuntimeLogs(logs = filteredRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const pageCount = runtimeLogPageCount(logs);
  state.runtimeLogPage = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (state.runtimeLogPage - 1) * pageSize;
  return logs.slice(start, start + pageSize);
}

function renderRuntimeLogPager(logs = filteredRuntimeLogs()) {
  const pager = $("runtimeLogPager");
  if (!pager) return;
  if (!logs.length) {
    pager.innerHTML = "";
    return;
  }
  const pageCount = runtimeLogPageCount(logs);
  const page = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (page - 1) * state.runtimeLogPageSize + 1;
  const end = Math.min(logs.length, page * state.runtimeLogPageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${logs.length} 条</span>
    <button type="button" data-runtime-log-page="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <strong>第 ${page} / ${pageCount} 页</strong>
    <button type="button" data-runtime-log-page="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

async function clearRuntimeLogs() {
  const button = $("clearRuntimeLogs");
  if (button) button.disabled = true;
  try {
    await api("/api/runtime-logs/clear", { method: "POST", body: "{}" });
    state.runtimeLogs = [];
    state.runtimeLogSeq = 0;
    state.runtimeLogPage = 1;
    state.runtimeLogTypeFilter = "all";
    renderRuntimeLogs();
  } finally {
    if (button) button.disabled = false;
  }
}

function renderGridModelParamTable() {
  const container = $("modelParamTable");
  if (!container) return;
  const devices = gridModelDevices();
  const rows = filteredGridModelDevices(devices).map(modelAttributeRecordForDevice);
  const groups = groupedModelAttributeRecords(rows);
  const availableTabs = groups.map(([devType]) => devType);
  if (!availableTabs.includes(state.activeModelParamTab)) {
    state.activeModelParamTab = availableTabs[0] || "";
  }
  const activeGroup = groups.find(([devType]) => devType === state.activeModelParamTab) || groups[0];
  const activeColumnCount = activeGroup ? modelAttributeColumns(activeGroup[1]).length : 0;
  $("modelParamSummary").textContent = groups.length > 1
    ? `${gridModelFilterLabel()} · ${rows.length}/${devices.length} 台 · ${groups.length} 个分页`
    : `${gridModelFilterLabel()} · ${rows.length}/${devices.length} 台 · ${activeColumnCount} 列属性`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无电网模型数据</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无模型参数</div>';
    return;
  }
  const [activeType, activeRows] = activeGroup;
  container.innerHTML = `
    <div class="model-param-tabs" role="tablist" aria-label="设备类型参数表">
      ${groups.map(([devType, groupRows]) => `
        <button
          type="button"
          role="tab"
          class="model-param-tab ${devType === activeType ? "is-active" : ""}"
          data-model-param-tab="${escapeHtml(devType)}"
          aria-selected="${devType === activeType ? "true" : "false"}"
        >
          <span>${escapeHtml(devType)}</span>
          <strong>${groupRows.length}</strong>
        </button>
      `).join("")}
    </div>
    <section class="model-param-tab-page" role="tabpanel" data-model-param-page="${escapeHtml(activeType)}">
      ${renderModelAttributeTable(activeRows)}
    </section>
  `;
}

function renderGridModelPage() {
  renderGridModelDeviceTree();
  renderGridModelParamTable();
}

function setGridModelFilter(devType, devName = "") {
  state.modelDeviceFilter = { dev_type: devType || "all", dev_name: devName || "" };
  if (devType && devType !== "all") state.activeModelParamTab = devType;
  renderGridModelPage();
}

function setModelParamTab(devType) {
  if (!devType || state.activeModelParamTab === devType) return;
  state.activeModelParamTab = devType;
  renderGridModelParamTable();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function definedControlRows(blockName, snapshot = state.snapshot || {}) {
  const block = definitionBlocks("control", snapshot)?.[blockName];
  const headers = Array.isArray(block?.headers) ? block.headers : [];
  return (block?.rows || []).map((row, index) => {
    const raw = {};
    headers.forEach((header) => {
      raw[header] = row?.[header] ?? "";
    });
    return {
      ...raw,
      dev_type: raw.dev_type ?? row?.dev_type ?? "",
      dev_name: raw.dev_name ?? raw.name ?? row?.dev_name ?? row?.name ?? "",
      idx: raw.idx ?? row?.idx ?? index + 1,
      __headers: headers,
      __control_block: blockName,
      __definition_index: index,
    };
  }).filter((row) => row.dev_type && row.dev_name);
}

function runtimeSnapshotDevice(devType, devName, snapshot = state.snapshot || {}) {
  return (snapshot.devices || []).find((dev) => dev.dev_type === devType && dev.dev_name === devName) || null;
}

function runtimeControlDeviceFromRow(row, snapshot = state.snapshot || {}) {
  const live = runtimeSnapshotDevice(row.dev_type, row.dev_name, snapshot) || {};
  return {
    ...live,
    dev_type: row.dev_type,
    dev_name: row.dev_name,
    idx: live.idx ?? live.raw?.idx ?? row.idx ?? "",
    run_stat: live.run_stat ?? row.run_stat ?? 1,
    status: live.status ?? row.status ?? 1,
    mode: live.mode ?? live.raw?.control_type ?? live.raw?.ctrl_mode ?? "",
    set_values: live.set_values || {},
    raw: live.raw || {},
  };
}

function controlDefinitionDevices(snapshot = state.snapshot || {}) {
  const rows = [
    ...definedControlRows("RunStat", snapshot),
    ...definedControlRows("CbOpenStat", snapshot),
    ...definedControlRows("SetValue", snapshot),
  ];
  const devices = new Map();
  rows.forEach((row) => {
    const key = `${row.dev_type}|${row.dev_name}`;
    const existing = devices.get(key) || runtimeControlDeviceFromRow(row, snapshot);
    existing.__control_rows = existing.__control_rows || [];
    existing.__control_rows.push(row);
    if (row.__control_block === "RunStat") existing.run_stat = existing.run_stat ?? row.run_stat;
    if (row.__control_block === "CbOpenStat") existing.status = existing.status ?? row.status;
    if (row.__control_block === "SetValue" && row.set_type) {
      existing.set_values = { ...(existing.set_values || {}) };
      if (existing.set_values[row.set_type] === undefined) existing.set_values[row.set_type] = row.set_value;
    }
    devices.set(key, existing);
  });
  return Array.from(devices.values());
}

function runtimeDevices() {
  return controlDefinitionDevices();
}

function runtimeFilterMatches(dev, filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" }) {
  if (filter.dev_type && filter.dev_type !== "all" && dev.dev_type !== filter.dev_type) return false;
  if (filter.dev_name && dev.dev_name !== filter.dev_name) return false;
  return true;
}

function filteredRuntimeDevices(devices = runtimeDevices()) {
  return devices.filter((dev) => runtimeFilterMatches(dev));
}

function runtimeControlMeta(dev) {
  const setValues = dev?.set_values || {};
  const raw = dev?.raw || {};
  const mode = String(dev?.mode || raw.control_type || raw.ctrl_mode || "").toUpperCase();
  const preferred = [];
  if (mode.includes("V")) preferred.push("v_set", "v_ac_set", "v_dc_set");
  if (mode.includes("Q")) preferred.push("q_set", "q_ac_set");
  if (mode.includes("P") || mode.includes("H")) preferred.push("p_ac_set", "p_dc_set", "p_set", "pv0");
  preferred.push(
    "p_ac_set",
    "p_dc_set",
    "p_set",
    "pv0",
    "q_ac_set",
    "q_set",
    "qv0",
    "v_ac_set",
    "v_dc_set",
    "v_set",
    "i_set",
  );
  const candidates = Array.from(new Set(preferred));
  for (const key of candidates) {
    const value = numberOrNull(setValues[key] ?? raw[key]);
    if (value !== null) return runtimeMetaFromSetKey(key, value);
  }
  const soc = numberOrNull(dev?.soc_curr ?? raw.soc_curr ?? raw.soc);
  if (soc !== null) {
    return { key: "soc_curr", label: "soc_curr", kind: "SOC", unit: "%", value: soc };
  }
  return { key: "run_stat", label: "run_stat", kind: "STAT", unit: "", value: numberOrNull(dev?.run_stat) ?? 0 };
}

function runtimeMetaFromSetKey(key, value) {
  const lowerKey = String(key).toLowerCase();
  if (lowerKey.includes("soc")) return { key, label: key, kind: "SOC", unit: "%", value };
  if (lowerKey.startsWith("q") || lowerKey.includes("_q")) return { key, label: key, kind: "Q", unit: "kvar", value };
  if (lowerKey.startsWith("v") || lowerKey.includes("_v")) return { key, label: key, kind: "V", unit: "V", value };
  if (lowerKey.startsWith("i") || lowerKey.includes("_i")) return { key, label: key, kind: "I", unit: "A", value };
  if (lowerKey === "run_stat") return { key, label: key, kind: "STAT", unit: "", value };
  return { key, label: key, kind: "P", unit: "kW", value };
}

function runtimeMeasTypeMatchesSetKey(measType, setKey) {
  const type = String(measType || "").toUpperCase();
  const key = String(setKey || "").toLowerCase();
  if (!type || !key) return false;
  if (key.startsWith("p") || key.includes("_p")) return type === "P" || type.startsWith("P_");
  if (key.startsWith("q") || key.includes("_q")) return type === "Q" || type.startsWith("Q_");
  if (key.startsWith("v") || key.includes("_v")) return type === "V" || type.startsWith("V_");
  if (key.startsWith("i") || key.includes("_i")) return type === "I" || type.startsWith("I_");
  if (key.includes("soc")) return type === "SOC";
  return type === key.toUpperCase();
}

function runtimeMeasurementPair(dev, meta, measurements = state.snapshot?.measurements || {}) {
  const best = measurementCompareRows(measurements).find((row) => (
    row.dev_type === dev.dev_type
    && row.dev_name === dev.dev_name
    && runtimeMeasTypeMatchesSetKey(row.meas_type, meta.key || meta.kind)
  )) || {};
  return {
    name: best.name || "",
    meas_type: best.meas_type || "",
    real: numberOrNull(best.real_value),
    scada: numberOrNull(best.scada_value),
  };
}

function runtimeDeviceTraceSignal(dev, measurements = state.snapshot?.measurements || {}) {
  const control = runtimeControlMeta(dev);
  const pair = runtimeMeasurementPair(dev, control, measurements);
  return {
    control: control.value,
    real: pair.real,
    scada: pair.scada,
    set_type: control.key,
    signal_kind: control.kind,
    unit: control.unit,
    meas_name: pair.name,
    meas_type: pair.meas_type,
  };
}

function runtimeCommandTraceKey(row) {
  const dev = row.device || {};
  return [
    row.command_kind || "runtime_command",
    dev.dev_type || "",
    dev.dev_name || "",
    row.set_type || "",
  ].join("|");
}

function runtimeCommandTraceLabel(row) {
  const dev = row.device || {};
  return row.trace_label || `${dev.dev_name || "--"} · ${row.command || "--"} ${row.set_type || ""}`.trim();
}

function runtimeCommandRowsForDevices(devices, measurements = state.snapshot?.measurements || {}) {
  return [
    ...runtimeRemoteControlRows(devices),
    ...runtimeRemoteAdjustmentRows(devices, measurements),
  ];
}

function appendRuntimeTrace(snapshot) {
  const clock = snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return;
  const result = snapshot.result || {};
  const summary = snapshot.summary || {};
  const signature = [
    snapshot.model?.id || state.activeModelId,
    clock.absolute_minute ?? clock.minute ?? "",
    clock.time || "",
    result.updated ?? "",
    result.solver_info || "",
    summary.scada_count ?? 0,
  ].join("|");
  if (signature === state.lastRuntimeTraceKey) return;
  state.lastRuntimeTraceKey = signature;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.runtimeTraceHistory.length) || 0,
    sim_time: clock.time || "--",
    record_time: Date.now(),
    devices: {},
    commands: {},
  };
  controlDefinitionDevices(snapshot).forEach((dev) => {
    point.devices[deviceKey(dev)] = runtimeDeviceTraceSignal(dev, snapshot.measurements || {});
  });
  runtimeCommandRowsForDevices(controlDefinitionDevices(snapshot), snapshot.measurements || {}).forEach((row) => {
    point.commands[runtimeCommandTraceKey(row)] = {
      control: numberOrNull(row.control_value),
      real: numberOrNull(row.real_value),
      scada: numberOrNull(row.scada_value),
      unit: row.unit || "",
      signal_kind: row.signal_kind || "",
      label: runtimeCommandTraceLabel(row),
    };
  });
  state.runtimeTraceHistory.push(point);
  state.runtimeTraceHistory = state.runtimeTraceHistory.slice(-TRACE_HISTORY_LIMIT);
}

function renderRuntimeDeviceTree() {
  const container = $("runtimeDeviceTree");
  if (!container) return;
  const devices = runtimeDevices();
  const filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  $("runtimeTreeSummary").textContent = `${groupEntries.length} 类 · ${devices.length} 台`;
  container.innerHTML = `
    <button
      type="button"
      class="tree-node tree-root ${filter.dev_type === "all" ? "is-active" : ""}"
      data-runtime-tree-type="all"
      data-runtime-tree-name=""
    >
      <span>全部设备</span>
      <strong>${devices.length}</strong>
    </button>
    ${groupEntries.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("runtime", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${filter.dev_type === devType && !filter.dev_name ? "is-active" : filter.dev_type === devType ? "is-parent-active" : ""}"
          data-runtime-tree-type="${escapeHtml(devType)}"
          data-runtime-tree-name=""
          ${deviceTreeTypeAttrs("runtime", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
            <button
              type="button"
              class="tree-node tree-child ${filter.dev_type === dev.dev_type && filter.dev_name === dev.dev_name ? "is-active" : ""}"
              data-runtime-tree-type="${escapeHtml(dev.dev_type)}"
              data-runtime-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("")}
  `;
}

function setRuntimeDeviceFilter(devType, devName = "") {
  state.runtimeDeviceFilter = { dev_type: devType || "all", dev_name: devName || "" };
  renderRuntimeMonitor(true);
}

function runtimeFilterLabel(filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" }) {
  if (filter.dev_type === "all") return "全部设备";
  if (filter.dev_name) return filter.dev_name;
  return filter.dev_type;
}

function formatRuntimeSignal(value, unit) {
  const formatted = formatMeasurementValue(value);
  return formatted === "--" || !unit ? formatted : `${formatted} ${unit}`;
}

function commandRefreshTimeFromMinute(minute) {
  const numericMinute = numberOrNull(minute);
  if (numericMinute === null) return "--";
  return formatSimulationClock({
    time: runtimeFormatClockMinute(numericMinute),
    minute: numericMinute,
    absolute_minute: numericMinute,
  });
}

function emptyCommandTimeInfo() {
  return { wall_time: "--", simu_time: "--" };
}

function commandTimeInfoAvailable(info = {}) {
  return [info.wall_time, info.simu_time].some((value) => {
    const text = String(value || "").trim();
    return text && text !== "--";
  });
}

function commandReceiveTimeInfo(entry = {}) {
  const wallTime = runtimeLogWallTimeText(entry.received_wall_time || entry.time || entry.wall_time || entry.record_time || "");
  const minute = entry.received_absolute_minute ?? entry.issued_absolute_minute;
  return {
    wall_time: wallTime,
    simu_time: commandRefreshTimeFromMinute(minute),
  };
}

function manualCommandHoldsAcrossClockLifecycle(entry = {}) {
  const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
  if (entry.manual_hold || entry.hold_until_cancelled || payload.manual_hold || payload.hold_until_cancelled) return true;
  if (payload.strategy && typeof payload.strategy === "object") return false;
  const source = String(entry.source || payload.source || "").trim().toLowerCase();
  if (source.includes("renewable") || source.includes("strategy")) return false;
  return source === "trainee-ui"
    || source === "student-ui"
    || source.startsWith("trainee-ui-")
    || source.startsWith("student-ui-")
    || source.includes("人工");
}

function activeCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  return [...(snapshot.commands?.history || [])].filter((entry) => {
    if (!entry?.eligible_source) return false;
    if (entry.cancelled) return false;
    const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);
    if (!manualHold) {
      const entryRunId = numberOrNull(entry.run_id);
      if (entryRunId === null || entryRunId !== currentRunId) return false;
    }
    const issued = numberOrNull(entry.issued_absolute_minute);
    const expires = numberOrNull(entry.expires_at_absolute_minute);
    if (issued === null || expires === null) return false;
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    return acceptedCount > 0 && currentMinute < expires && (manualHold || issued <= currentMinute);
  });
}

function runtimeCommandRefreshInfo(dev, commandType, setType = "", snapshot = state.snapshot || {}) {
  const history = activeCommandHistory(snapshot).reverse();
  for (const entry of history) {
    const normalized = entry.normalized || {};
    if (commandType === "set_value") {
      const items = normalized.set_values || entry.payload?.set_values || [];
      const match = items.find((item) => (
        item.dev_type === dev.dev_type
        && item.dev_name === dev.dev_name
        && item.set_type === setType
      ));
      if (match) return commandReceiveTimeInfo(entry);
      continue;
    }
    const items = normalized.run_status || entry.payload?.run_status || [];
    const match = items.find((item) => {
      if (item.dev_type !== dev.dev_type || item.dev_name !== dev.dev_name) return false;
      if (commandType === "status") return Object.prototype.hasOwnProperty.call(item, "status");
      return item.run_stat !== undefined && item.run_stat !== "";
    });
    if (match) return commandReceiveTimeInfo(entry);
  }
  return emptyCommandTimeInfo();
}

function runtimeCommandRefreshTime(dev, commandType, setType = "", snapshot = state.snapshot || {}) {
  return runtimeCommandRefreshInfo(dev, commandType, setType, snapshot).simu_time;
}

function selectedRuntimeDeviceKeys(devices) {
  return new Set((devices || []).map((dev) => deviceKey(dev)));
}

function runtimeRemoteControlRows(devices) {
  const selectedKeys = selectedRuntimeDeviceKeys(devices);
  const runRows = definedControlRows("RunStat").filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
  const cbRows = definedControlRows("CbOpenStat").filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
  return [
    ...runRows.map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow);
      const runStatTime = runtimeCommandRefreshInfo(dev, "run_stat");
      const value = Number(dev.run_stat ?? definitionRow.run_stat ?? 0);
      return {
        category: "遥控指令",
        command_kind: "remote_control",
        device: dev,
        command: "设备投退",
        set_type: "run_stat",
        command_text: value !== 0 ? "投入" : "退出",
        real_text: value !== 0 ? "投入" : "退出",
        scada_text: "--",
        refresh_time: runStatTime.simu_time,
        receive_time: runStatTime,
        control_value: value,
        real_value: value,
        scada_value: null,
        signal_kind: "STAT",
        unit: "",
        trace_label: `${dev.dev_name}.设备投退`,
      };
    }),
    ...cbRows.map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow);
      const statusTime = runtimeCommandRefreshInfo(dev, "status");
      const value = Number(dev.status ?? definitionRow.status ?? 0);
      return {
        category: "遥控指令",
        command_kind: "remote_control",
        device: dev,
        command: "开关开合",
        set_type: "status",
        command_text: value !== 0 ? "闭合" : "断开",
        real_text: value !== 0 ? "闭合" : "断开",
        scada_text: "--",
        refresh_time: statusTime.simu_time,
        receive_time: statusTime,
        control_value: value,
        real_value: value,
        scada_value: null,
        signal_kind: "STAT",
        unit: "",
        trace_label: `${dev.dev_name}.开关开合`,
      };
    }),
  ];
}

function runtimeRemoteAdjustmentRows(devices, measurements = state.snapshot?.measurements || {}) {
  const selectedKeys = selectedRuntimeDeviceKeys(devices);
  return definedControlRows("SetValue")
    .filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`))
    .map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow);
      const key = definitionRow.set_type || "";
      const value = dev.set_values?.[key] ?? definitionRow.set_value;
      const meta = runtimeMetaFromSetKey(key, Number(value));
      const pair = runtimeMeasurementPair(dev, meta, measurements);
      const commandTime = runtimeCommandRefreshInfo(dev, "set_value", key);
      return {
        category: "遥调指令",
        command_kind: "remote_adjustment",
        device: dev,
        command: `${meta.kind}设定值`,
        set_type: key,
        command_text: formatRuntimeSignal(meta.value, meta.unit),
        real_text: formatRuntimeSignal(pair.real, meta.unit),
        scada_text: formatRuntimeSignal(pair.scada, meta.unit),
        refresh_time: commandTime.simu_time,
        receive_time: commandTime,
        control_value: meta.value,
        real_value: pair.real,
        scada_value: pair.scada,
        signal_kind: meta.kind,
        unit: meta.unit,
        trace_label: `${dev.dev_name}.${key}`,
      };
    });
}

function renderRuntimeCommandRows(rows) {
  return rows.map((row) => {
    const traceKey = runtimeCommandTraceKey(row);
    const traceLabel = runtimeCommandTraceLabel(row);
    return `
    <tr
      class="${traceKey === state.selectedRuntimeCommandKey ? "is-selected" : ""}"
      data-runtime-command-row-key="${escapeHtml(traceKey)}"
      data-runtime-command-row-label="${escapeHtml(traceLabel)}"
      title="单击或双击刷新控制跟踪曲线"
    >
      <td>${escapeHtml(row.device.dev_name)}</td>
      <td>${escapeHtml(row.device.dev_type)}</td>
      <td>${escapeHtml(row.device.mode || "--")}</td>
      <td>${escapeHtml(row.command)} <small class="command-set-type">${escapeHtml(row.set_type)}</small></td>
      <td class="numeric-cell">${escapeHtml(row.command_text)}</td>
      <td class="mono-cell">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
      <td class="mono-cell">${escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--")}</td>
      <td class="numeric-cell">${escapeHtml(row.real_text)}</td>
      <td class="numeric-cell">${escapeHtml(row.scada_text)}</td>
    </tr>
  `;
  }).join("");
}

function renderRuntimeCommandTable(rows, emptyText) {
  if (!rows.length) return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  return `
    <table class="runtime-device-table runtime-command-table">
      <thead>
        <tr>
          <th>设备</th>
          <th>设备类型</th>
          <th>模式</th>
          <th>指令项</th>
          <th>控制指令</th>
          <th>接收本机时刻</th>
          <th>接收仿真时刻</th>
          <th>实时值</th>
          <th>量测值</th>
        </tr>
      </thead>
      <tbody>${renderRuntimeCommandRows(rows)}</tbody>
    </table>
  `;
}

function renderRuntimeDeviceTable() {
  const container = $("deviceTable");
  if (!container) return;
  const devices = runtimeDevices();
  const selectedDevices = filteredRuntimeDevices(devices);
  const remoteControlRows = runtimeRemoteControlRows(selectedDevices);
  const remoteAdjustmentRows = runtimeRemoteAdjustmentRows(selectedDevices);
  const commandCount = remoteControlRows.length + remoteAdjustmentRows.length;
  const visibleCommandKeys = new Set([...remoteControlRows, ...remoteAdjustmentRows].map(runtimeCommandTraceKey));
  if (state.selectedRuntimeCommandKey && !visibleCommandKeys.has(state.selectedRuntimeCommandKey)) {
    state.selectedRuntimeCommandKey = "";
    state.selectedRuntimeCommandLabel = "";
  }
  $("runtimeDeviceSummary").textContent = `${runtimeFilterLabel()} · ${commandCount} 条指令`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无设备数据</div>';
    return;
  }
  if (!selectedDevices.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  if (!commandCount) {
    container.innerHTML = '<div class="empty-state">当前筛选无控制指令</div>';
    return;
  }
  const activeTab = state.activeRuntimeCommandTab === "remote_adjustment" ? "remote_adjustment" : "remote_control";
  container.innerHTML = `
    <div class="runtime-command-tabs" role="tablist" aria-label="控制指令类型">
      <button type="button" role="tab" class="runtime-command-tab ${activeTab === "remote_control" ? "is-active" : ""}" data-runtime-command-tab="remote_control" aria-selected="${activeTab === "remote_control"}">
        <span>遥控指令</span><strong>${remoteControlRows.length}</strong>
      </button>
      <button type="button" role="tab" class="runtime-command-tab ${activeTab === "remote_adjustment" ? "is-active" : ""}" data-runtime-command-tab="remote_adjustment" aria-selected="${activeTab === "remote_adjustment"}">
        <span>遥调指令</span><strong>${remoteAdjustmentRows.length}</strong>
      </button>
    </div>
    <section class="runtime-command-tab-page ${activeTab === "remote_control" ? "is-active" : ""}" data-runtime-command-page="remote_control" role="tabpanel">
      ${renderRuntimeCommandTable(remoteControlRows, "当前筛选无遥控指令")}
    </section>
    <section class="runtime-command-tab-page ${activeTab === "remote_adjustment" ? "is-active" : ""}" data-runtime-command-page="remote_adjustment" role="tabpanel">
      ${renderRuntimeCommandTable(remoteAdjustmentRows, "当前筛选无遥调指令")}
    </section>
  `;
}

function setRuntimeCommandTab(tabName) {
  if (!["remote_control", "remote_adjustment"].includes(tabName)) return;
  if (state.activeRuntimeCommandTab === tabName) return;
  state.activeRuntimeCommandTab = tabName;
  state.selectedRuntimeCommandKey = "";
  state.selectedRuntimeCommandLabel = "";
  renderRuntimeDeviceTable();
  drawRuntimeTraceChart();
}

function selectRuntimeCommandTrace(key, label = "") {
  state.selectedRuntimeCommandKey = key || "";
  state.selectedRuntimeCommandLabel = label || "";
  document.querySelectorAll("[data-runtime-command-row-key]").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.runtimeCommandRowKey === state.selectedRuntimeCommandKey);
  });
  drawRuntimeTraceChart();
}

function selectedRuntimeCommandTraceRows() {
  const devices = filteredRuntimeDevices(runtimeDevices());
  return runtimeCommandRowsForDevices(devices, state.snapshot?.measurements || {});
}

function selectedRuntimeCommandTraceSeries() {
  const key = state.selectedRuntimeCommandKey;
  if (!key) return null;
  const rows = selectedRuntimeCommandTraceRows();
  const row = rows.find((item) => runtimeCommandTraceKey(item) === key);
  if (!row) return null;
  const points = runtimeTraceWindowPoints()
    .map((point) => {
      const signal = point.commands?.[key];
      if (!signal) return null;
      return {
        minute: point.minute,
        sim_time: point.sim_time,
        control: numberOrNull(signal.control),
        real: numberOrNull(signal.real),
        scada: numberOrNull(signal.scada),
        unit: signal.unit || row.unit || "",
        signal_kind: signal.signal_kind || row.signal_kind || "",
      };
    })
    .filter(Boolean);
  return {
    label: state.selectedRuntimeCommandLabel || runtimeCommandTraceLabel(row),
    points,
  };
}

function runtimeTraceDevicesForChart() {
  const rows = filteredRuntimeDevices();
  if (rows.length <= 1) return rows;
  const firstMeta = runtimeControlMeta(rows[0]);
  return rows.filter((dev) => {
    const meta = runtimeControlMeta(dev);
    return meta.kind === firstMeta.kind && meta.unit === firstMeta.unit;
  });
}

function runtimeTraceWindowPoints() {
  const history = state.runtimeTraceHistory || [];
  if (!history.length) return [];
  const range = runtimeTraceWindowRange();
  return history.filter((point) => point.minute >= range.startMinute && point.minute <= range.endMinute);
}

function traceAxisStepMinutes(windowMinutes) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  if (minutes <= 15) return 5;
  if (minutes <= 60) return 15;
  if (minutes <= 180) return 30;
  if (minutes <= 360) return 60;
  if (minutes <= 1440) return 240;
  if (minutes <= 10080) return 1440;
  if (minutes <= 43200) return 5 * 1440;
  if (minutes <= 525600) return 60 * 1440;
  return Math.max(60, Math.round(minutes / 6 / 60) * 60);
}

function traceWindowAlignmentMinutes(windowMinutes) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  if (minutes <= 15) return 15;
  if (minutes <= 1440) return minutes;
  if (minutes >= 525600) return 525600;
  return 1440;
}

function alignedTraceWindowRange(history, windowMinutes, fallbackMinute) {
  const alignmentMinutes = traceWindowAlignmentMinutes(windowMinutes);
  const axisStepMinutes = traceAxisStepMinutes(windowMinutes);
  const latestMinute = history.length ? history[history.length - 1].minute : fallbackMinute;
  const startMinute = Math.floor(latestMinute / alignmentMinutes) * alignmentMinutes;
  return {
    startMinute,
    endMinute: startMinute + windowMinutes,
    latestMinute,
    windowMinutes,
    alignmentMinutes,
    axisStepMinutes,
  };
}

function runtimeTraceWindowRange() {
  const history = state.runtimeTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.runtimeTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  return alignedTraceWindowRange(history, windowMinutes, fallbackMinute);
}

function runtimeFormatClockMinute(minute) {
  const total = ((Math.round(minute) % 1440) + 1440) % 1440;
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:00`;
}

function formatYearTraceTickLabel(minute) {
  const absoluteDay = Math.floor(Math.max(0, Number(minute) || 0) / 1440);
  const year = Math.floor(absoluteDay / 365) + 1;
  let dayOfYear = absoluteDay % 365;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfYear >= monthDays[month]) {
    dayOfYear -= monthDays[month];
    month += 1;
  }
  return year === 1 ? `${String(month + 1).padStart(2, "0")}月` : `第${year}年${String(month + 1).padStart(2, "0")}月`;
}

function runtimeAxisTickLabel(minute, range, index, lastIndex) {
  const targetMinute = index === lastIndex ? range.endMinute : minute;
  if (range.windowMinutes <= 1440) return runtimeFormatClockMinute(targetMinute);
  if (range.windowMinutes >= 525600) return formatYearTraceTickLabel(targetMinute);
  const absolute = Math.max(0, Math.round(targetMinute));
  const day = Math.floor(absolute / 1440);
  const clock = runtimeFormatClockMinute(absolute).slice(0, 5);
  return absolute % 1440 === 0 ? `第${day + 1}天` : `第${day + 1}天 ${clock}`;
}

function runtimeTraceAxisTicks(range, canvasWidth) {
  const maxTicks = canvasWidth < 480 ? 4 : canvasWidth < 760 ? 5 : 8;
  let step = range.axisStepMinutes || traceAxisStepMinutes(range.windowMinutes);
  while (Math.floor(range.windowMinutes / step) + 1 > maxTicks) {
    step *= 2;
  }
  const ticks = [];
  for (let minute = range.startMinute; minute <= range.endMinute + 1e-9; minute += step) {
    ticks.push(minute);
  }
  if (ticks[ticks.length - 1] !== range.endMinute) ticks.push(range.endMinute);
  return ticks;
}

function runtimeAggregateTracePoint(point, devices) {
  const keys = devices.map(deviceKey);
  const signals = keys.map((key) => point.devices[key]).filter(Boolean);
  const average = (field) => {
    const values = signals.map((signal) => numberOrNull(signal[field])).filter((value) => value !== null);
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  };
  const first = signals[0] || {};
  return {
    minute: point.minute,
    sim_time: point.sim_time,
    control: average("control"),
    real: average("real"),
    scada: average("scada"),
    unit: first.unit || "",
    signal_kind: first.signal_kind || "",
  };
}

function resizeRuntimeTraceCanvas() {
  const canvas = $("runtimeTraceChart");
  if (!canvas) return false;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(340, Math.round(rect.width || canvas.clientWidth || canvas.width));
  const height = Math.max(240, Math.round(rect.height || canvas.clientHeight || canvas.height));
  if (canvas.width === width && canvas.height === height) return false;
  canvas.width = width;
  canvas.height = height;
  return true;
}

function drawRuntimeTraceChart() {
  const canvas = $("runtimeTraceChart");
  if (!canvas) return;
  resizeRuntimeTraceCanvas();
  const chartKey = "runtimeTrace";
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const plot = width < 640
    ? { left: 42, right: 14, top: 28, bottom: 32 }
    : { left: 58, right: 24, top: 28, bottom: 36 };
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  const selectedCommandSeries = selectedRuntimeCommandTraceSeries();
  const chartDevices = selectedCommandSeries ? [] : runtimeTraceDevicesForChart();
  const range = runtimeTraceWindowRange();
  const points = selectedCommandSeries?.points
    || runtimeTraceWindowPoints().map((point) => runtimeAggregateTracePoint(point, chartDevices));
  const seriesDefs = [
    { key: "control", field: "control", label: "控制指令", color: "#b87500" },
    { key: "real", field: "real", label: "实时值", color: "#008c8c" },
    { key: "scada", field: "scada", label: "量测值", color: "#c93a3a" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = "#63717a";
  for (let i = 0; i <= 4; i += 1) {
    const y = top + i * ((bottom - top) / 4);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  const xTicks = runtimeTraceAxisTicks(range, width);
  xTicks.forEach((minute, tickIndex) => {
    const ratio = (minute - range.startMinute) / range.windowMinutes;
    const x = left + ratio * (right - left);
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4;
    ctx.fillText(runtimeAxisTickLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12);
  });
  const label = runtimeFilterLabel();
  const chartLabel = selectedCommandSeries
    ? selectedCommandSeries.label
    : chartDevices.length > 1 ? `${label} · ${chartDevices.length}台平均` : label;
  $("runtimeTraceSummary").textContent = `${chartLabel} · ${points.length} 点`;
  if ((!selectedCommandSeries && !chartDevices.length) || !points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "center";
    ctx.fillText(!visibleSeries.length ? "所有曲线已隐藏" : "暂无跟踪数据", width / 2, height / 2);
    ctx.textAlign = "left";
    return;
  }
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (Math.abs(maxValue - minValue) < 1e-9) {
    minValue -= 1;
    maxValue += 1;
  }
  const padding = (maxValue - minValue) * 0.12;
  minValue -= padding;
  maxValue += padding;
  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * (right - left);
  const yForValue = (value) => bottom - ((value - minValue) / (maxValue - minValue)) * (bottom - top);
  const hitData = [];
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const drawSeries = (series, widthScale = 2) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = series.key === selectedSeries ? widthScale + 1.2 : widthScale;
    ctx.beginPath();
    let started = false;
    points.forEach((point) => {
      const value = numberOrNull(point[series.field]);
      if (value === null) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit, points: pixelPoints });
  };
  const unit = points.find((point) => point.unit)?.unit || "";
  visibleSeries.forEach((series) => drawSeries(series, series.key === "scada" ? 2 : 2.5));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    timeLabel: (point) => runtimeAxisTickLabel(point.minute, range, 0, 0),
    valueFormatter: formatMeasurementValue,
  });
  ctx.fillStyle = "#63717a";
  ctx.textAlign = "left";
  ctx.fillText(formatMeasurementValue(maxValue), 8, top + 4);
  ctx.fillText(formatMeasurementValue(minValue), 8, bottom);
  if (unit) ctx.fillText(unit, left, 18);
}

function renderRuntimeMonitor(force = false) {
  const activeEditor = document.activeElement?.closest?.("#runtimeTraceWindow");
  renderRuntimeDeviceTree();
  renderRuntimeDeviceTable();
  if (force || !activeEditor) drawRuntimeTraceChart();
}

function formatMeasurementValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 1000) return number.toFixed(2);
  if (Math.abs(number) >= 10) return number.toFixed(3);
  return number.toFixed(5);
}

function isWeatherMeasurement(row) {
  return row?.dev_type === "Environment" && row?.dev_name === "weather";
}

function weatherMeasurementLabel(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return WEATHER_MEASUREMENT_LABELS[type]?.label || row?.name || type || "气象";
}

function weatherMeasurementOrder(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return WEATHER_MEASUREMENT_LABELS[type]?.order ?? 99;
}

function measurementDisplayName(row) {
  return isWeatherMeasurement(row) ? `气象.${weatherMeasurementLabel(row)}` : row.name;
}

function measurementDeviceDisplay(row) {
  return isWeatherMeasurement(row) ? "气象.weather" : `${row.dev_type || "--"}.${row.dev_name || "--"}`;
}

function measurementTypeDisplay(row) {
  return isWeatherMeasurement(row) ? weatherMeasurementLabel(row) : row.meas_type;
}

function compareMeasurementsForDisplay(left, right) {
  const leftWeather = isWeatherMeasurement(left);
  const rightWeather = isWeatherMeasurement(right);
  if (leftWeather !== rightWeather) return leftWeather ? -1 : 1;
  if (leftWeather && rightWeather) return weatherMeasurementOrder(left) - weatherMeasurementOrder(right);
  const typeCompare = String(left.dev_type || "").localeCompare(String(right.dev_type || ""), "zh-Hans-CN");
  if (typeCompare) return typeCompare;
  const nameCompare = String(left.dev_name || "").localeCompare(String(right.dev_name || ""), "zh-Hans-CN");
  if (nameCompare) return nameCompare;
  return String(left.name || "").localeCompare(String(right.name || ""), "zh-Hans-CN");
}

function sortMeasurementsForDisplay(rows) {
  return [...(rows || [])].sort(compareMeasurementsForDisplay);
}

function measurementCompareRows(measurements = state.snapshot?.measurements || {}) {
  const definitions = state.snapshot?.definitions?.measurement || measurements.definitions || [];
  const primaryRows = definitions.length
    ? definitions
    : (measurements.scada?.length ? measurements.scada : measurements.real || []);
  const realByKey = new Map();
  const scadaByKey = new Map();
  const addRows = (rows, target) => {
    (rows || []).forEach((row) => {
      target.set(measurementKey(row), row);
    });
  };
  addRows(measurements.real, realByKey);
  addRows(measurements.scada, scadaByKey);
  return sortMeasurementsForDisplay(primaryRows.map((definition) => {
    const key = measurementKey(definition);
    const real = realByKey.get(key);
    const scada = scadaByKey.get(key);
    const realValue = real?.value;
    const scadaValue = scada?.value;
    const realNumber = Number(realValue);
    const scadaNumber = Number(scadaValue);
    const diff = Number.isFinite(realNumber) && Number.isFinite(scadaNumber)
      ? scadaNumber - realNumber
      : null;
    return {
      idx: definition.idx,
      name: definition.name,
      dev_type: definition.dev_type,
      dev_name: definition.dev_name,
      meas_type: definition.meas_type,
      weight: definition.weight ?? "--",
      valid: scada?.valid ?? real?.valid ?? definition.valid ?? 0,
      real_value: realValue,
      scada_value: scadaValue,
      diff,
    };
  }));
}

function measurementUnit(measType) {
  const type = String(measType || "").toUpperCase();
  if (WEATHER_MEASUREMENT_LABELS[type]?.unit) return WEATHER_MEASUREMENT_LABELS[type].unit;
  if (type.startsWith("P")) return "kW";
  if (type.startsWith("Q")) return "kvar";
  if (type.startsWith("V")) return "V";
  if (type.startsWith("I")) return "A";
  return "";
}

function appendMeasurementTrace(snapshot) {
  const clock = snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return;
  const result = snapshot.result || {};
  const summary = snapshot.summary || {};
  const signature = [
    snapshot.model?.id || state.activeModelId,
    clock.absolute_minute ?? clock.minute ?? "",
    clock.time || "",
    result.updated ?? "",
    result.solver_info || "",
    summary.scada_count ?? 0,
  ].join("|");
  if (signature === state.lastMeasurementTraceKey) return;
  state.lastMeasurementTraceKey = signature;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.measurementTraceHistory.length) || 0,
    sim_time: clock.time || "--",
    record_time: Date.now(),
    measurements: {},
  };
  measurementCompareRows(snapshot.measurements || {}).forEach((row) => {
    const key = measurementKey(row);
    point.measurements[key] = {
      name: measurementDisplayName(row) || "",
      dev_type: row.dev_type || "",
      dev_name: row.dev_name || "",
      meas_type: measurementTypeDisplay(row) || "",
      unit: measurementUnit(row.meas_type),
      real: numberOrNull(row.real_value),
      scada: numberOrNull(row.scada_value),
      valid: Number(row.valid) === 1 ? 1 : 0,
    };
  });
  state.measurementTraceHistory.push(point);
  state.measurementTraceHistory = state.measurementTraceHistory.slice(-TRACE_HISTORY_LIMIT);
}

function ensureSelectedMeasurementKey(rows, allRows) {
  const availableRows = rows.length ? rows : allRows;
  const availableKeys = new Set(availableRows.map((row) => measurementKey(row)));
  if (state.selectedMeasurementKey && availableKeys.has(state.selectedMeasurementKey)) {
    return state.selectedMeasurementKey;
  }
  state.selectedMeasurementKey = availableRows.length ? measurementKey(availableRows[0]) : "";
  return state.selectedMeasurementKey;
}

function selectedMeasurementRow(rows = measurementCompareRows()) {
  if (!state.selectedMeasurementKey) return null;
  return rows.find((row) => measurementKey(row) === state.selectedMeasurementKey) || null;
}

function setSelectedMeasurementKey(key) {
  state.selectedMeasurementKey = key || "";
  renderMeasurementCompareTable();
  drawMeasurementTraceChart();
}

function measurementTraceWindowRange() {
  const history = state.measurementTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.measurementTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  return alignedTraceWindowRange(history, windowMinutes, fallbackMinute);
}

function measurementTraceWindowPoints(key = state.selectedMeasurementKey) {
  if (!key) return [];
  const range = measurementTraceWindowRange();
  return (state.measurementTraceHistory || [])
    .filter((point) => point.minute >= range.startMinute && point.minute <= range.endMinute)
    .map((point) => {
      const measurement = point.measurements[key];
      if (!measurement) return null;
      return {
        minute: point.minute,
        sim_time: point.sim_time,
        real: measurement.real,
        scada: measurement.scada,
        unit: measurement.unit || "",
      };
    })
    .filter(Boolean);
}

function resizeMeasurementTraceCanvas() {
  const canvas = $("measurementTraceChart");
  if (!canvas) return false;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(340, Math.round(rect.width || canvas.clientWidth || canvas.width));
  const height = Math.max(240, Math.round(rect.height || canvas.clientHeight || canvas.height));
  if (canvas.width === width && canvas.height === height) return false;
  canvas.width = width;
  canvas.height = height;
  return true;
}

function drawMeasurementTraceChart() {
  const canvas = $("measurementTraceChart");
  if (!canvas) return;
  resizeMeasurementTraceCanvas();
  const chartKey = "measurementTrace";
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const plot = width < 640
    ? { left: 42, right: 14, top: 28, bottom: 32 }
    : { left: 58, right: 24, top: 28, bottom: 36 };
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  const range = measurementTraceWindowRange();
  const allRows = measurementCompareRows();
  const selectedRow = selectedMeasurementRow(allRows);
  const points = measurementTraceWindowPoints();
  const seriesDefs = [
    { key: "real", field: "real", label: "真值", color: "#008c8c" },
    { key: "scada", field: "scada", label: "量测值", color: "#c93a3a" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = "#63717a";
  for (let i = 0; i <= 4; i += 1) {
    const y = top + i * ((bottom - top) / 4);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  const xTicks = runtimeTraceAxisTicks(range, width);
  xTicks.forEach((minute, tickIndex) => {
    const ratio = (minute - range.startMinute) / range.windowMinutes;
    const x = left + ratio * (right - left);
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4;
    ctx.fillText(runtimeAxisTickLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12);
  });
  const label = selectedRow ? measurementDisplayName(selectedRow) : "请选择测点";
  $("measurementTraceSummary").textContent = `${label} · ${points.length} 点`;
  if (!selectedRow || !points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "center";
    ctx.fillText(!visibleSeries.length ? "所有曲线已隐藏" : "暂无跟踪数据", width / 2, height / 2);
    ctx.textAlign = "left";
    return;
  }
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (Math.abs(maxValue - minValue) < 1e-9) {
    minValue -= 1;
    maxValue += 1;
  }
  const padding = (maxValue - minValue) * 0.12;
  minValue -= padding;
  maxValue += padding;
  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * (right - left);
  const yForValue = (value) => bottom - ((value - minValue) / (maxValue - minValue)) * (bottom - top);
  const hitData = [];
  const unit = points.find((point) => point.unit)?.unit || measurementUnit(selectedRow.meas_type);
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const drawSeries = (series, widthScale = 2.5) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = series.key === selectedSeries ? widthScale + 1.2 : widthScale;
    ctx.beginPath();
    let started = false;
    points.forEach((point) => {
      const value = numberOrNull(point[series.field]);
      if (value === null) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit, points: pixelPoints });
  };
  visibleSeries.forEach((series) => drawSeries(series, series.key === "scada" ? 2 : 2.5));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    timeLabel: (point) => runtimeAxisTickLabel(point.minute, range, 0, 0),
    valueFormatter: formatMeasurementValue,
  });
  ctx.fillStyle = "#63717a";
  ctx.textAlign = "left";
  ctx.fillText(formatMeasurementValue(maxValue), 8, top + 4);
  ctx.fillText(formatMeasurementValue(minValue), 8, bottom);
  if (unit) ctx.fillText(unit, left, 18);
}

function measurementCompareDevices(rows = measurementCompareRows()) {
  const devices = new Map();
  rows.forEach((row) => {
    if (!row.dev_type || !row.dev_name) return;
    const key = deviceKey(row);
    const entry = devices.get(key) || { dev_type: row.dev_type, dev_name: row.dev_name, count: 0 };
    entry.count += 1;
    devices.set(key, entry);
  });
  return Array.from(devices.values()).sort((left, right) => {
    if (left.dev_type === "Environment" && right.dev_type !== "Environment") return -1;
    if (left.dev_type !== "Environment" && right.dev_type === "Environment") return 1;
    const typeCompare = String(left.dev_type).localeCompare(String(right.dev_type));
    return typeCompare || String(left.dev_name).localeCompare(String(right.dev_name));
  });
}

function filteredMeasurementCompareRows(rows = measurementCompareRows()) {
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  return rows.filter((row) => {
    if (filter.dev_type && filter.dev_type !== "all" && row.dev_type !== filter.dev_type) return false;
    if (filter.dev_name && row.dev_name !== filter.dev_name) return false;
    return true;
  });
}

function renderMeasurementCompareDeviceTree(rows = measurementCompareRows()) {
  const container = $("measurementCompareDeviceTree");
  if (!container) return;
  const devices = measurementCompareDevices(rows);
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  $("measurementCompareTreeSummary").textContent = `${groupEntries.length} 类 · ${devices.length} 台`;
  container.innerHTML = `
    <button
      type="button"
      class="tree-node tree-root ${filter.dev_type === "all" ? "is-active" : ""}"
      data-measurement-tree-type="all"
      data-measurement-tree-name=""
    >
      <span>全部设备</span>
      <strong>${devices.length}</strong>
    </button>
    ${groupEntries.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("measurement", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${filter.dev_type === devType && !filter.dev_name ? "is-active" : filter.dev_type === devType ? "is-parent-active" : ""}"
          data-measurement-tree-type="${escapeHtml(devType)}"
          data-measurement-tree-name=""
          ${deviceTreeTypeAttrs("measurement", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((item) => `
            <button
              type="button"
              class="tree-node tree-child ${filter.dev_type === item.dev_type && filter.dev_name === item.dev_name ? "is-active" : ""}"
              data-measurement-tree-type="${escapeHtml(item.dev_type)}"
              data-measurement-tree-name="${escapeHtml(item.dev_name)}"
            >
              <span>${escapeHtml(item.dev_type === "Environment" && item.dev_name === "weather" ? "气象" : item.dev_name)}</span>
              <small>${escapeHtml(item.count)}点</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("")}
  `;
}

function setMeasurementCompareFilter(devType, devName = "") {
  state.measurementCompareFilter = { dev_type: devType || "all", dev_name: devName || "" };
  renderMeasurementCompareTable();
}

function renderMeasurementCompareTable() {
  const container = $("measurementCompareTable");
  if (!container) return;
  const allRows = measurementCompareRows();
  renderMeasurementCompareDeviceTree(allRows);
  const rows = filteredMeasurementCompareRows(allRows);
  const selectedKey = ensureSelectedMeasurementKey(rows, allRows);
  const validCount = rows.filter((row) => Number(row.valid) === 1).length;
  $("measurementCompareSummary").textContent = `${rows.length}/${allRows.length} 点 · 有效 ${validCount} 点`;
  if (!allRows.length) {
    container.innerHTML = '<div class="empty-state">暂无实时量测数据</div>';
    drawMeasurementTraceChart();
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无量测</div>';
    drawMeasurementTraceChart();
    return;
  }
  container.innerHTML = `
    <table class="measurement-compare-table">
      <thead>
        <tr>
          <th>量测名称</th>
          <th>设备</th>
          <th>量测类型</th>
          <th>真值</th>
          <th>量测值</th>
          <th>偏差</th>
          <th>权重</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => {
          const diffClass = row.diff === null || Math.abs(row.diff) < 1e-6 ? "diff-neutral" : "diff-active";
          const key = measurementKey(row);
          return `
            <tr
              class="${key === selectedKey ? "is-selected" : ""}"
              data-measurement-select-key="${escapeHtml(key)}"
              tabindex="0"
              aria-selected="${key === selectedKey ? "true" : "false"}"
            >
              <td>${escapeHtml(measurementDisplayName(row) || "--")}</td>
              <td>${escapeHtml(measurementDeviceDisplay(row))}</td>
              <td>${escapeHtml(measurementTypeDisplay(row) || "--")}</td>
              <td class="numeric-cell">${formatMeasurementValue(row.real_value)}</td>
              <td class="numeric-cell">${formatMeasurementValue(row.scada_value)}</td>
              <td class="numeric-cell ${diffClass}">${row.diff === null ? "--" : formatMeasurementValue(row.diff)}</td>
              <td class="numeric-cell">${escapeHtml(row.weight)}</td>
              <td><span class="status-dot ${Number(row.valid) === 1 ? "on" : ""}"></span>${Number(row.valid) === 1 ? "有效" : "无效"}</td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>`;
  drawMeasurementTraceChart();
}

function renderDevices(devices) {
  $("deviceTable").innerHTML = `
    <table>
      <thead><tr><th>设备</th><th>类型</th><th>投运</th><th>状态</th><th>模式</th><th>设值</th></tr></thead>
      <tbody>
        ${devices.slice(0, 12).map((dev) => `
          <tr>
            <td>${dev.dev_name}</td>
            <td>${dev.dev_type}</td>
            <td><span class="status-dot ${dev.run_stat ? "on" : ""}"></span>${dev.run_stat ? "投入" : "退出"}</td>
            <td>${dev.status ? "闭合/可用" : "断开/故障"}</td>
            <td>${dev.mode || "--"}</td>
            <td>${Object.entries(dev.set_values || {}).map(([k, v]) => `${k}=${v}`).join(" ") || "--"}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function setFaultTab(tabName) {
  state.activeFaultTab = tabName;
  document.querySelectorAll("[data-fault-tab]").forEach((button) => {
    const active = button.dataset.faultTab === tabName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-fault-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.faultPanel === tabName);
  });
}

function deviceKey(dev) {
  return `${dev.dev_type}|${dev.dev_name}`;
}

function measurementKey(meas) {
  return `${meas.name}|${meas.dev_type}|${meas.dev_name}|${meas.meas_type}`;
}

function faultDevices() {
  return state.snapshot?.devices || [];
}

function faultMeasurements() {
  const measurements = state.snapshot?.measurements || {};
  return measurements.scada?.length
    ? measurements.scada
    : measurements.definitions?.length
      ? measurements.definitions
      : measurements.real || [];
}

function findDeviceFault(dev) {
  return state.deviceFaults.find((fault) => fault.dev_type === dev.dev_type && fault.dev_name === dev.dev_name);
}

function findMeasurementFault(meas) {
  return state.measurementFaults.find((fault) => measurementFaultMatches(fault, meas));
}

function measurementFaultMatches(fault, meas) {
    if (fault.dev_type && fault.dev_type !== meas.dev_type) return false;
    if (fault.dev_name && fault.dev_name !== meas.dev_name) return false;
    if (fault.meas_type && String(fault.meas_type).toUpperCase() !== String(meas.meas_type).toUpperCase()) return false;
    const target = fault.target || fault.name || "";
    return !target || target === meas.name || target === meas.dev_name || target === measurementKey(meas);
}

function ensureDeviceFault(dev) {
  let fault = findDeviceFault(dev);
  if (!fault) {
    fault = {
      dev_type: dev.dev_type,
      dev_name: dev.dev_name,
      start_minute: 60,
      clear_minute: 120,
      start_day: 1,
      clear_day: 2,
      run_stat: 0,
      status: 0,
    };
    state.deviceFaults.push(fault);
  }
  return fault;
}

function ensureMeasurementFault(meas) {
  let fault = findMeasurementFault(meas);
  if (!fault) {
    fault = {
      name: meas.name,
      target: meas.name,
      dev_type: meas.dev_type,
      dev_name: meas.dev_name,
      meas_type: meas.meas_type,
      fault_type: "dead",
      start_minute: 180,
      clear_minute: 240,
      start_day: 1,
      clear_day: 2,
      median: meas.value ?? 0,
      bias: 0,
    };
    state.measurementFaults.push(fault);
  }
  return fault;
}

function deviceTreeBadge(dev) {
  const raw = dev.raw || {};
  return String(dev.mode || raw.control_type || raw.ctrl_mode || (Number(dev.run_stat ?? 1) !== 0 ? "投" : "退"));
}

function groupedByDeviceType(items) {
  const groups = new Map();
  items.forEach((item) => {
    const devType = item.dev_type || "未分类";
    const list = groups.get(devType) || [];
    list.push(item);
    groups.set(devType, list);
  });
  return Array.from(groups.entries())
    .map(([devType, list]) => [
      devType,
      list.sort((left, right) => String(left.dev_name || left.name || "").localeCompare(String(right.dev_name || right.name || ""))),
    ])
    .sort(([left], [right]) => {
      if (left === "Environment" && right !== "Environment") return -1;
      if (left !== "Environment" && right === "Environment") return 1;
      return String(left).localeCompare(String(right));
    });
}

function filteredFaultDevices() {
  const filter = state.faultDeviceFilter || { dev_type: "all", dev_name: "" };
  return faultDevices()
    .map((dev, index) => ({ dev, index }))
    .filter(({ dev }) => {
      if (filter.dev_type && filter.dev_type !== "all" && dev.dev_type !== filter.dev_type) return false;
      if (filter.dev_name && dev.dev_name !== filter.dev_name) return false;
      return true;
    });
}

function filteredFaultMeasurements() {
  const filter = state.faultMeasurementFilter || { dev_type: "all", dev_name: "", key: "" };
  return faultMeasurements()
    .map((meas, index) => ({ meas, index }))
    .filter(({ meas }) => {
      if (filter.dev_type && filter.dev_type !== "all" && meas.dev_type !== filter.dev_type) return false;
      if (filter.dev_name && meas.dev_name !== filter.dev_name) return false;
      if (filter.key && measurementKey(meas) !== filter.key) return false;
      return true;
    });
}

function faultMeasurementDevices(measurements = faultMeasurements()) {
  const devices = new Map();
  measurements.forEach((meas) => {
    if (!meas.dev_type || !meas.dev_name) return;
    const key = deviceKey(meas);
    const entry = devices.get(key) || { dev_type: meas.dev_type, dev_name: meas.dev_name, count: 0 };
    entry.count += 1;
    devices.set(key, entry);
  });
  return Array.from(devices.values()).sort((left, right) => {
    const typeCompare = String(left.dev_type).localeCompare(String(right.dev_type));
    return typeCompare || String(left.dev_name).localeCompare(String(right.dev_name));
  });
}

function renderFaultDeviceTree() {
  const container = $("faultDeviceTree");
  if (!container) return;
  const devices = faultDevices();
  const filter = state.faultDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  $("faultDeviceTreeSummary").textContent = `${groupEntries.length} 类 · ${devices.length} 台`;
  container.innerHTML = `
    <button
      type="button"
      class="tree-node tree-root ${filter.dev_type === "all" ? "is-active" : ""}"
      data-fault-device-tree-type="all"
      data-fault-device-tree-name=""
    >
      <span>全部设备</span>
      <strong>${devices.length}</strong>
    </button>
    ${groupEntries.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("faultDevice", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${filter.dev_type === devType && !filter.dev_name ? "is-active" : filter.dev_type === devType ? "is-parent-active" : ""}"
          data-fault-device-tree-type="${escapeHtml(devType)}"
          data-fault-device-tree-name=""
          ${deviceTreeTypeAttrs("faultDevice", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
            <button
              type="button"
              class="tree-node tree-child ${filter.dev_type === dev.dev_type && filter.dev_name === dev.dev_name ? "is-active" : ""}"
              data-fault-device-tree-type="${escapeHtml(dev.dev_type)}"
              data-fault-device-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("")}
  `;
}

function renderFaultMeasurementTree() {
  const container = $("faultMeasurementTree");
  if (!container) return;
  const measurements = faultMeasurements();
  const devices = faultMeasurementDevices(measurements);
  const filter = state.faultMeasurementFilter || { dev_type: "all", dev_name: "", key: "" };
  const groupEntries = groupedByDeviceType(devices);
  $("faultMeasurementTreeSummary").textContent = `${groupEntries.length} 类 · ${devices.length} 台`;
  container.innerHTML = `
    <button
      type="button"
      class="tree-node tree-root ${filter.dev_type === "all" ? "is-active" : ""}"
      data-fault-measurement-tree-type="all"
      data-fault-measurement-tree-name=""
    >
      <span>全部设备</span>
      <strong>${devices.length}</strong>
    </button>
    ${groupEntries.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("faultMeasurement", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${filter.dev_type === devType && !filter.dev_name ? "is-active" : filter.dev_type === devType ? "is-parent-active" : ""}"
          data-fault-measurement-tree-type="${escapeHtml(devType)}"
          data-fault-measurement-tree-name=""
          ${deviceTreeTypeAttrs("faultMeasurement", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
            <button
              type="button"
              class="tree-node tree-child ${filter.dev_type === dev.dev_type && filter.dev_name === dev.dev_name ? "is-active" : ""}"
              data-fault-measurement-tree-type="${escapeHtml(dev.dev_type)}"
              data-fault-measurement-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(dev.count)}点</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("")}
  `;
}

function setDeviceFaultFilter(devType, devName = "") {
  state.faultDeviceFilter = { dev_type: devType || "all", dev_name: devName || "" };
  renderFaults(true);
}

function setMeasurementFaultFilter(devType, devName = "") {
  state.faultMeasurementFilter = { dev_type: devType || "all", dev_name: devName || "", key: "" };
  renderFaults(true);
}

function renderFaults(force = false) {
  const activeEditor = document.activeElement?.closest?.("#deviceFaultTable, #measurementFaultTable");
  if (!force && activeEditor) return;
  renderFaultDeviceTree();
  renderDeviceFaultTable();
  renderFaultMeasurementTree();
  renderMeasurementFaultTable();
}

function faultWindowFields() {
  if (state.curveMode === "year") {
    return {
      startField: "start_day",
      clearField: "clear_day",
      startLabel: "故障启始日",
      clearLabel: "结束日",
      inputType: "text",
      min: "",
      max: "",
      step: "",
      placeholder: "1月1日",
      deviceStart: 1,
      deviceClear: 2,
      measurementStart: 1,
      measurementClear: 2,
    };
  }
  return {
    startField: "start_minute",
    clearField: "clear_minute",
    startLabel: "故障启始时刻",
    clearLabel: "结束时刻",
    inputType: "time",
    min: "00:00",
    max: "23:59",
    step: 60,
    placeholder: "",
    deviceStart: 60,
    deviceClear: 120,
    measurementStart: 180,
    measurementClear: 240,
  };
}

function dayOfYearToMonthDay(day) {
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let remain = clamp(Math.round(Number(day) || 1), 1, 365);
  let month = 0;
  while (month < monthDays.length - 1 && remain > monthDays[month]) {
    remain -= monthDays[month];
    month += 1;
  }
  return `${month + 1}月${remain}日`;
}

function monthDayToDayOfYear(value, fallback = 1) {
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const text = String(value ?? "").trim();
  const numeric = Number(text);
  if (Number.isFinite(numeric) && text !== "") {
    return clamp(Math.round(numeric), 1, 365);
  }
  const match = text.match(/(\d{1,2})\D+(\d{1,2})/);
  if (!match) return clamp(Math.round(Number(fallback) || 1), 1, 365);
  const month = clamp(Math.round(Number(match[1]) || 1), 1, 12);
  const day = clamp(Math.round(Number(match[2]) || 1), 1, monthDays[month - 1]);
  const previousDays = monthDays.slice(0, month - 1).reduce((total, count) => total + count, 0);
  return previousDays + day;
}

function faultWindowInputValue(fault, field, fallback) {
  if (field === "start_minute" || field === "clear_minute") {
    return minuteToTimeInput(fault?.[field], fallback);
  }
  const value = Number(fault?.[field]);
  return dayOfYearToMonthDay(Number.isFinite(value) ? value : fallback);
}

function faultSimulationModeLabel() {
  return state.curveMode === "year" ? "年仿真 · 按日整定" : "日仿真 · 按时分整定";
}

function renderDeviceFaultTable() {
  const container = $("deviceFaultTable");
  const devices = faultDevices();
  const rows = filteredFaultDevices();
  const windowFields = faultWindowFields();
  if (!container) return;
  $("deviceFaultSummary").textContent = `${faultSimulationModeLabel()} · ${state.deviceFaults.length} 个故障 · 显示 ${rows.length}/${devices.length} 台`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无设备数据</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  container.innerHTML = `
    <table class="fault-editor-table">
      <thead>
        <tr>
          <th>设备类型</th>
          <th>设备名称</th>
          <th>运行状态</th>
          <th>故障状态</th>
          <th>${windowFields.startLabel}</th>
          <th>${windowFields.clearLabel}</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ dev, index }) => {
          const fault = findDeviceFault(dev);
          const disabled = fault ? "" : "disabled";
          return `
            <tr>
              <td>${escapeHtml(dev.dev_type)}</td>
              <td>${escapeHtml(dev.dev_name)}</td>
              <td><span class="status-dot ${dev.run_stat ? "on" : ""}"></span>${dev.run_stat ? "投入" : "退出"}</td>
              <td>
                <select data-device-index="${index}" data-device-field="faulted">
                  <option value="normal" ${fault ? "" : "selected"}>正常</option>
                  <option value="fault" ${fault ? "selected" : ""}>故障</option>
                </select>
              </td>
              <td><input data-device-index="${index}" data-device-field="${windowFields.startField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.startField, windowFields.deviceStart)}" ${disabled} /></td>
              <td><input data-device-index="${index}" data-device-field="${windowFields.clearField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.clearField, windowFields.deviceClear)}" ${disabled} /></td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function renderMeasurementFaultTable() {
  const container = $("measurementFaultTable");
  const measurements = faultMeasurements();
  const rows = filteredFaultMeasurements();
  const windowFields = faultWindowFields();
  if (!container) return;
  $("measurementFaultSummary").textContent = `${faultSimulationModeLabel()} · ${state.measurementFaults.length} 个故障 · 显示 ${rows.length}/${measurements.length} 点`;
  if (!measurements.length) {
    container.innerHTML = '<div class="empty-state">暂无量测数据</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无量测</div>';
    return;
  }
  container.innerHTML = `
    <table class="fault-editor-table">
      <thead>
        <tr>
          <th>量测名称</th>
          <th>设备</th>
          <th>量测类型</th>
          <th>当前值</th>
          <th>量测状态</th>
          <th>${windowFields.startLabel}</th>
          <th>${windowFields.clearLabel}</th>
          <th>中值</th>
          <th>误差</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ meas, index }) => {
          const fault = findMeasurementFault(meas);
          const faultType = fault?.fault_type || "normal";
          const disabled = fault ? "" : "disabled";
          return `
            <tr>
              <td>${escapeHtml(meas.name)}</td>
              <td>${escapeHtml(meas.dev_type)}.${escapeHtml(meas.dev_name)}</td>
              <td>${escapeHtml(meas.meas_type)}</td>
              <td>${meas.value ?? "--"}</td>
              <td>
                <select data-meas-index="${index}" data-meas-field="fault_type">
                  <option value="normal" ${faultType === "normal" ? "selected" : ""}>正常</option>
                  <option value="dead" ${faultType === "dead" ? "selected" : ""}>死数</option>
                  <option value="zero" ${faultType === "zero" ? "selected" : ""}>0值</option>
                </select>
              </td>
              <td><input data-meas-index="${index}" data-meas-field="${windowFields.startField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.startField, windowFields.measurementStart)}" ${disabled} /></td>
              <td><input data-meas-index="${index}" data-meas-field="${windowFields.clearField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.clearField, windowFields.measurementClear)}" ${disabled} /></td>
              <td><input data-meas-index="${index}" data-meas-field="median" type="number" step="0.001" value="${fault?.median ?? meas.value ?? 0}" ${disabled} /></td>
              <td><input data-meas-index="${index}" data-meas-field="bias" type="number" step="0.001" value="${fault?.bias ?? 0}" ${disabled} /></td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function updateDeviceFault(index, field, rawValue, shouldRender = true) {
  const dev = faultDevices()[index];
  if (!dev) return;
  if (field === "faulted" && rawValue === "normal") {
    state.deviceFaults = state.deviceFaults.filter((fault) => deviceKey(fault) !== deviceKey(dev));
    renderFaults(true);
    return;
  }
  const fault = ensureDeviceFault(dev);
  if (field === "start_minute" || field === "clear_minute") {
    fault[field] = timeInputToMinute(rawValue, fault[field]);
  } else if (field === "start_day" || field === "clear_day") {
    fault[field] = monthDayToDayOfYear(rawValue, fault[field] || 1);
  }
  if (shouldRender) renderFaults(true);
}

function updateMeasurementFault(index, field, rawValue, shouldRender = true) {
  const meas = faultMeasurements()[index];
  if (!meas) return;
  if (field === "fault_type" && rawValue === "normal") {
    state.measurementFaults = state.measurementFaults.filter((fault) => !measurementFaultMatches(fault, meas));
    renderFaults(true);
    return;
  }
  const fault = ensureMeasurementFault(meas);
  if (field === "fault_type") {
    fault.fault_type = rawValue;
  } else if (field === "start_minute" || field === "clear_minute") {
    fault[field] = timeInputToMinute(rawValue, fault[field]);
  } else if (field === "start_day" || field === "clear_day") {
    fault[field] = monthDayToDayOfYear(rawValue, fault[field] || 1);
  } else if (field === "median" || field === "bias") {
    fault[field] = Number(rawValue);
  }
  if (shouldRender) renderFaults(true);
}

function isModeCapableDevice(dev) {
  if (!dev?.dev_type || !dev?.dev_name) return false;
  if (dev.mode !== undefined && String(dev.mode) !== "") return true;
  const raw = dev.raw || {};
  return ["control_type", "mode", "ctrl_mode"].some((column) => raw[column] !== undefined);
}

function syncModesFromDevices(devices, currentModes = []) {
  const currentByKey = new Map();
  currentModes.forEach((item) => {
    if (item?.dev_type && item?.dev_name) {
      currentByKey.set(deviceKey(item), item);
    }
  });
  return devices.filter(isModeCapableDevice).map((dev) => {
    const existing = currentByKey.get(deviceKey(dev));
    const mode = String(existing?.mode ?? existing?.control_type ?? dev.mode ?? "PQ");
    return {
      dev_type: dev.dev_type,
      dev_name: dev.dev_name,
      mode: mode || "PQ",
    };
  });
}

function modeDeviceMap() {
  return new Map((state.snapshot?.devices || []).map((dev) => [deviceKey(dev), dev]));
}

function modeRows() {
  const devices = modeDeviceMap();
  const filter = state.modeFilter || { dev_type: "all", dev_name: "" };
  return state.modes
    .map((item, index) => ({ item, index, device: devices.get(deviceKey(item)) }))
    .filter(({ item }) => {
      if (filter.dev_type && filter.dev_type !== "all" && item.dev_type !== filter.dev_type) return false;
      if (filter.dev_name && item.dev_name !== filter.dev_name) return false;
      return true;
    });
}

function modeOptionsHtml(value) {
  const current = String(value || "PQ");
  const options = MODE_OPTIONS.includes(current)
    ? MODE_OPTIONS
    : [current, ...MODE_OPTIONS.filter((mode) => mode !== current)];
  return options.map((mode) => `
    <option value="${escapeHtml(mode)}" ${mode === current ? "selected" : ""}>${escapeHtml(mode)}</option>
  `).join("");
}

function renderModeDeviceTree() {
  const container = $("modeDeviceTree");
  if (!container) return;
  const filter = state.modeFilter || { dev_type: "all", dev_name: "" };
  const groups = new Map();
  state.modes.forEach((item) => {
    const list = groups.get(item.dev_type) || [];
    list.push(item);
    groups.set(item.dev_type, list);
  });
  const groupEntries = Array.from(groups.entries()).sort(([left], [right]) => left.localeCompare(right));
  $("modeTreeSummary").textContent = `${groupEntries.length} 类 · ${state.modes.length} 台`;
  container.innerHTML = `
    <button
      type="button"
      class="tree-node tree-root ${filter.dev_type === "all" ? "is-active" : ""}"
      data-mode-tree-type="all"
      data-mode-tree-name=""
    >
      <span>全部设备</span>
      <strong>${state.modes.length}</strong>
    </button>
    ${groupEntries.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("mode", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${filter.dev_type === devType && !filter.dev_name ? "is-active" : filter.dev_type === devType ? "is-parent-active" : ""}"
          data-mode-tree-type="${escapeHtml(devType)}"
          data-mode-tree-name=""
          ${deviceTreeTypeAttrs("mode", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((item) => `
            <button
              type="button"
              class="tree-node tree-child ${filter.dev_type === item.dev_type && filter.dev_name === item.dev_name ? "is-active" : ""}"
              data-mode-tree-type="${escapeHtml(item.dev_type)}"
              data-mode-tree-name="${escapeHtml(item.dev_name)}"
            >
              <span>${escapeHtml(item.dev_name)}</span>
              <small>${escapeHtml(item.mode)}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("")}
  `;
}

function renderModeDeviceTable() {
  const container = $("modeDeviceTable");
  if (!container) return;
  const rows = modeRows();
  $("modeTableSummary").textContent = `${rows.length}/${state.modes.length} 台设备`;
  if (!state.modes.length) {
    container.innerHTML = '<div class="empty-state">暂无可设模式设备</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  container.innerHTML = `
    <table class="mode-editor-table">
      <thead>
        <tr>
          <th>设备类型</th>
          <th>设备名称</th>
          <th>当前状态</th>
          <th>设备状态</th>
          <th>当前模式</th>
          <th>运行模式</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ item, index, device }) => {
          const running = Number(device?.run_stat ?? 1) !== 0;
          const available = Number(device?.status ?? 1) !== 0;
          const currentMode = device?.mode || item.mode || "--";
          return `
            <tr>
              <td>${escapeHtml(item.dev_type)}</td>
              <td class="device-name">${escapeHtml(item.dev_name)}</td>
              <td><span class="status-dot ${running ? "on" : ""}"></span>${running ? "投入" : "退出"}</td>
              <td>${available ? "可用/闭合" : "断开/故障"}</td>
              <td>${escapeHtml(currentMode)}</td>
              <td>
                <select data-mode-device-index="${index}" data-mode-field="mode">
                  ${modeOptionsHtml(item.mode)}
                </select>
              </td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>`;
}

function renderModes(force = false) {
  const activeEditor = document.activeElement?.closest?.("#modeDeviceTable");
  if (!force && activeEditor) return;
  renderModeDeviceTree();
  renderModeDeviceTable();
}

function setModeFilter(devType, devName = "") {
  state.modeFilter = { dev_type: devType || "all", dev_name: devName || "" };
  renderModes(true);
}

function updateModeValue(index, field, rawValue) {
  if (field !== "mode" || !state.modes[index]) return;
  state.modes[index].mode = rawValue;
  renderModes(true);
}

async function saveCurves() {
  syncCurvePayload();
  const config = curveModeConfig();
  await api("/api/curves", {
    method: "POST",
    body: JSON.stringify({
      mode: state.curveMode,
      point_count: config.pointCount,
      time_step_minutes: config.stepMinutes,
      weather: state.weatherPoints,
      loads: state.loadPointsByName,
    }),
  });
  $("curveStatus").textContent = "已保存";
}

async function pushSettings() {
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      device_faults: state.deviceFaults,
      measurement_faults: state.measurementFaults,
      modes: state.modes,
    }),
  });
  await refresh();
}

document.querySelectorAll("[data-clock]").forEach((button) => {
  button.addEventListener("click", () => handleClockAction(button.dataset.clock));
});
$("exportDefinitionsButton").addEventListener("click", exportDefinitionsArchive);
$("importDefinitionsButton").addEventListener("click", () => $("importDefinitionsInput").click());
$("importDefinitionsInput").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) openImportModelDialog(file);
});
$("traineeLinkButton").addEventListener("click", openTraineeLinkDialog);
$("copyTraineeLink").addEventListener("click", copyTraineeLink);
$("closeTraineeLinkDialog").addEventListener("click", closeTraineeLinkDialog);
$("cancelTraineeLinkDialog").addEventListener("click", closeTraineeLinkDialog);
$("traineeLinkDialog").addEventListener("click", (event) => {
  if (event.target.id === "traineeLinkDialog") closeTraineeLinkDialog();
});
$("closeStartSimulationDialog").addEventListener("click", closeStartSimulationDialog);
$("cancelStartSimulation").addEventListener("click", closeStartSimulationDialog);
$("startSimulationDialog").addEventListener("click", (event) => {
  if (event.target.id === "startSimulationDialog") closeStartSimulationDialog();
});
$("startSimulationForm").addEventListener("submit", (event) => {
  event.preventDefault();
  startSimulationFromDialog();
});
$("closeImportModelDialog").addEventListener("click", closeImportModelDialog);
$("cancelImportModel").addEventListener("click", closeImportModelDialog);
$("importModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "importModelDialog") closeImportModelDialog();
});
$("importModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  importDefinitionModel();
});
$("importModelName").addEventListener("input", () => validateImportModelName());
$("cloneModelButton").addEventListener("click", openCloneModelDialog);
$("closeCloneModelDialog").addEventListener("click", closeCloneModelDialog);
$("cancelCloneModel").addEventListener("click", closeCloneModelDialog);
$("cloneModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "cloneModelDialog") closeCloneModelDialog();
});
$("cloneModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  cloneCurrentModel();
});
$("cloneModelName").addEventListener("input", () => validateCloneModelName());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("startSimulationDialog").hidden) {
    closeStartSimulationDialog();
    return;
  }
  if (event.key === "Escape" && !$("importModelDialog").hidden) {
    closeImportModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("cloneModelDialog").hidden) {
    closeCloneModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("traineeLinkDialog").hidden) {
    closeTraineeLinkDialog();
  }
});

$("generateDenseCurves").addEventListener("click", () => {
  generateCurves(0);
  $("curveStatus").textContent = "已生成";
});
$("randomCurves").addEventListener("click", () => {
  generateCurves(Math.random() * 8 - 4);
  $("curveStatus").textContent = "本地扰动";
});
$("saveCurves").addEventListener("click", saveCurves);
document.querySelectorAll("[data-curve-mode]").forEach((button) => {
  button.addEventListener("click", () => switchSimulationMode(button.dataset.curveMode));
});
$(`simulationModeSelector`).addEventListener("change", (event) => switchSimulationMode(event.target.value));
const curveTreeElement = $("curveTree");
if (curveTreeElement) {
  curveTreeElement.addEventListener("pointerdown", beginCurveTreePointerSelection);
  curveTreeElement.addEventListener("pointerover", extendCurveTreePointerSelection);
}
window.addEventListener("pointerup", finishCurveTreePointerSelection);
window.addEventListener("pointercancel", resetCurveTreePointerSelection);
$("modelSelector").addEventListener("change", (event) => setActiveModel(event.target.value));
$("runtimeLogTypeFilter").addEventListener("change", (event) => {
  state.runtimeLogTypeFilter = event.target.value || "all";
  state.runtimeLogPage = 1;
  renderRuntimeLogs();
});
$("clearRuntimeLogs").addEventListener("click", clearRuntimeLogs);
$("runtimeLogPager").addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-runtime-log-page]") : null;
  if (!button) return;
  const direction = button.dataset.runtimeLogPage;
  const pageCount = runtimeLogPageCount(filteredRuntimeLogs());
  state.runtimeLogPage = direction === "prev"
    ? Math.max(1, state.runtimeLogPage - 1)
    : Math.min(pageCount, state.runtimeLogPage + 1);
  renderRuntimeLogs();
});
$("saveDeviceFaults").addEventListener("click", async () => {
  await pushSettings();
  $("deviceFaultSummary").textContent = `${faultSimulationModeLabel()} · 已保存 ${state.deviceFaults.length} 个故障`;
});
$("saveMeasurementFaults").addEventListener("click", async () => {
  await pushSettings();
  $("measurementFaultSummary").textContent = `${faultSimulationModeLabel()} · 已保存 ${state.measurementFaults.length} 个故障`;
});
document.querySelectorAll("[data-fault-tab]").forEach((button) => {
  button.addEventListener("click", () => setFaultTab(button.dataset.faultTab));
});
$("pushModes").addEventListener("click", pushSettings);
$("saveSystemParameters").addEventListener("click", saveSystemParameters);
$("resetSystemParameters").addEventListener("click", resetSystemParameterForm);
["parameterClockSpeed", "parameterComputeInterval"].forEach((id) => {
  const element = $(id);
  if (element) element.addEventListener("input", markSystemParametersDirty);
});
document.addEventListener("click", (event) => {
  const chartToggle = event.target.closest("[data-chart-toggle][data-chart-series]");
  if (chartToggle) {
    event.preventDefault();
    const chartKey = chartToggle.dataset.chartToggle || "";
    const seriesKey = chartToggle.dataset.chartSeries || "";
    const drawFn = chartKey === "runtimeTrace" ? drawRuntimeTraceChart
      : chartKey === "measurementTrace" ? drawMeasurementTraceChart
        : null;
    toggleChartSeriesVisibility(chartKey, seriesKey, drawFn);
    return;
  }
  const runtimeCommandTab = event.target.closest("[data-runtime-command-tab]");
  if (runtimeCommandTab) {
    setRuntimeCommandTab(runtimeCommandTab.dataset.runtimeCommandTab || "");
    return;
  }
  const runtimeCommandRow = event.target.closest("[data-runtime-command-row-key]");
  if (runtimeCommandRow) {
    selectRuntimeCommandTrace(
      runtimeCommandRow.dataset.runtimeCommandRowKey || "",
      runtimeCommandRow.dataset.runtimeCommandRowLabel || "",
    );
    return;
  }
  const modelParamTab = event.target.closest("[data-model-param-tab]");
  if (modelParamTab) {
    setModelParamTab(modelParamTab.dataset.modelParamTab || "");
    return;
  }
  const curveTreeButton = event.target.closest("[data-curve-tree-type]");
  if (curveTreeButton) {
    if (state.suppressNextCurveTreeClick) {
      state.suppressNextCurveTreeClick = false;
      event.preventDefault();
      return;
    }
    selectCurveTreeButton(curveTreeButton);
    event.preventDefault();
    return;
  }
  const faultDeviceTreeButton = event.target.closest("[data-fault-device-tree-type]");
  if (faultDeviceTreeButton) {
    if (faultDeviceTreeButton.dataset.treeToggleScope) {
      toggleDeviceTreeGroup(
        faultDeviceTreeButton.dataset.treeToggleScope,
        faultDeviceTreeButton.dataset.treeToggleGroup,
      );
    }
    setDeviceFaultFilter(
      faultDeviceTreeButton.dataset.faultDeviceTreeType,
      faultDeviceTreeButton.dataset.faultDeviceTreeName || "",
    );
  }
  const faultMeasurementTreeButton = event.target.closest("[data-fault-measurement-tree-type]");
  if (faultMeasurementTreeButton) {
    if (faultMeasurementTreeButton.dataset.treeToggleScope) {
      toggleDeviceTreeGroup(
        faultMeasurementTreeButton.dataset.treeToggleScope,
        faultMeasurementTreeButton.dataset.treeToggleGroup,
      );
    }
    setMeasurementFaultFilter(
      faultMeasurementTreeButton.dataset.faultMeasurementTreeType,
      faultMeasurementTreeButton.dataset.faultMeasurementTreeName || "",
    );
  }
  const measurementSelectRow = event.target.closest("[data-measurement-select-key]");
  if (measurementSelectRow) {
    setSelectedMeasurementKey(measurementSelectRow.dataset.measurementSelectKey || "");
  }
  const measurementTreeButton = event.target.closest("[data-measurement-tree-type]");
  if (measurementTreeButton) {
    if (measurementTreeButton.dataset.treeToggleScope) {
      toggleDeviceTreeGroup(
        measurementTreeButton.dataset.treeToggleScope,
        measurementTreeButton.dataset.treeToggleGroup,
      );
    }
    setMeasurementCompareFilter(
      measurementTreeButton.dataset.measurementTreeType,
      measurementTreeButton.dataset.measurementTreeName || "",
    );
  }
  const modelTreeButton = event.target.closest("[data-model-tree-type]");
  if (modelTreeButton) {
    if (modelTreeButton.dataset.treeToggleScope) {
      toggleDeviceTreeGroup(
        modelTreeButton.dataset.treeToggleScope,
        modelTreeButton.dataset.treeToggleGroup,
      );
    }
    setGridModelFilter(
      modelTreeButton.dataset.modelTreeType,
      modelTreeButton.dataset.modelTreeName || "",
    );
  }
  const runtimeTreeButton = event.target.closest("[data-runtime-tree-type]");
  if (runtimeTreeButton) {
    if (runtimeTreeButton.dataset.treeToggleScope) {
      toggleDeviceTreeGroup(
        runtimeTreeButton.dataset.treeToggleScope,
        runtimeTreeButton.dataset.treeToggleGroup,
      );
    }
    setRuntimeDeviceFilter(
      runtimeTreeButton.dataset.runtimeTreeType,
      runtimeTreeButton.dataset.runtimeTreeName || "",
    );
  }
  const modeTreeButton = event.target.closest("[data-mode-tree-type]");
  if (modeTreeButton) {
    if (modeTreeButton.dataset.treeToggleScope) {
      toggleDeviceTreeGroup(
        modeTreeButton.dataset.treeToggleScope,
        modeTreeButton.dataset.treeToggleGroup,
      );
    }
    setModeFilter(modeTreeButton.dataset.modeTreeType, modeTreeButton.dataset.modeTreeName || "");
  }
});
document.addEventListener("dblclick", (event) => {
  const runtimeCommandRow = event.target.closest("[data-runtime-command-row-key]");
  if (!runtimeCommandRow) return;
  event.preventDefault();
  selectRuntimeCommandTrace(
    runtimeCommandRow.dataset.runtimeCommandRowKey || "",
    runtimeCommandRow.dataset.runtimeCommandRowLabel || "",
  );
});
document.addEventListener("change", (event) => {
  if (event.target.dataset.modeField !== undefined) {
    updateModeValue(Number(event.target.dataset.modeDeviceIndex), event.target.dataset.modeField, event.target.value);
  }
  if (event.target.dataset.modeIndex !== undefined) {
    state.modes[Number(event.target.dataset.modeIndex)].mode = event.target.value;
  }
  if (event.target.dataset.deviceField !== undefined) {
    updateDeviceFault(Number(event.target.dataset.deviceIndex), event.target.dataset.deviceField, event.target.value);
  }
  if (event.target.dataset.measField !== undefined) {
    updateMeasurementFault(Number(event.target.dataset.measIndex), event.target.dataset.measField, event.target.value);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.dataset.deviceField !== undefined && event.target.tagName === "INPUT") {
    updateDeviceFault(Number(event.target.dataset.deviceIndex), event.target.dataset.deviceField, event.target.value, false);
  }
  if (event.target.dataset.measField !== undefined && event.target.tagName === "INPUT") {
    updateMeasurementFault(Number(event.target.dataset.measIndex), event.target.dataset.measField, event.target.value, false);
  }
});
initPageNavigation();
generateCurves(0);
initCurveEditor();
initRuntimeMonitor();
initMeasurementMonitor();
initOverviewBottomSplitter();
setFaultTab(state.activeFaultTab);
renderFaults(true);
setInterval(refresh, 1000);
loadModels().finally(refresh);
