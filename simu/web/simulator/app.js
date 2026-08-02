const apiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const OVERVIEW_BOTTOM_HEIGHT_KEY = "polarOverviewBottomHeight";
const OVERVIEW_BOTTOM_DEFAULT_HEIGHT = 156;
const OVERVIEW_BOTTOM_MIN_HEIGHT = 96;
const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;
const OVERVIEW_BOTTOM_COLUMN_RATIO_KEY = "polarSimulatorOverviewBottomColumnRatio";
const OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO = 50;
const OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX = 260;
const VERTICAL_SPLIT_STORAGE_KEY = "polarSimulatorVerticalSplitRatios";
const VERTICAL_SPLIT_DEFAULTS = {
  "simulator-curves": 60,
  "simulator-runtime": 52,
  "simulator-measurements": 52,
};
const VERTICAL_SPLIT_DEFAULT_RATIO = 55;
const VERTICAL_SPLIT_MIN_TOP_PX = 120;
const VERTICAL_SPLIT_MIN_BOTTOM_PX = 120;
const STATIC_CACHE_STORAGE_KEY = "polarSimulatorStaticCacheV2";
const STATIC_CACHE_MODEL_LIMIT = 4;
const API_REQUEST_TIMEOUT_MS = 30000;
const CURVE_REQUEST_TIMEOUT_MS = 8000;
const state = {
  snapshot: null,
  activePage: "",
  pageSections: {},
  pageMain: null,
  models: [],
  modelsLoaded: false,
  activeModelId: localStorage.getItem("polarSimulatorModelId") || "",
  refreshRequestActive: false,
  deviceFaults: [],
  measurementFaults: [],
  modes: [],
  weatherPoints: [],
  loadPoints: [],
  loadPointsByName: {},
  curveSummary: null,
  curveSummaryLoadedModelId: "",
  curveSummaryRequest: null,
  curveSummaryRequestModelId: "",
  curveSummaryAbortController: null,
  curveSeriesRequestKey: "",
  curveSeriesRequest: null,
  curveSeriesAbortController: null,
  curveEditorLoadRequest: null,
  curveEditorLoadRequestKey: "",
  curveLoadError: "",
  curveDataRevision: 0,
  lastCurveEditorRenderKey: "",
  lastCurveEditorTableKey: "",
  curveDirtyKeys: new Set(),
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
  runtimeCommandKeywordFilter: "",
  runtimeCommandTypeFilter: "all",
  runtimeCommandOnlyActive: false,
  measurementCompareFilter: { dev_type: "all", dev_name: "" },
  measurementCompareKeywordFilter: "",
  measurementCompareTypeFilter: "all",
  activeMeasurementCompareTab: "telemetry",
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
  traceRunId: null,
  traceStepCount: null,
  selectedManagementModelId: "",
  updateTargetModelId: "",
  cloneSourceModelId: "",
  modeFilter: { dev_type: "all", dev_name: "" },
  collapsedDeviceTreeGroups: {},
  deviceTreeSearch: {},
  deviceTreeSelectionAnchors: {},
  runtimeLogs: [],
  runtimeLogTypeFilter: "all",
  runtimeLogPage: 1,
  runtimeLogPageSize: 20,
  runtimeLogSeq: 0,
  runtimeLogBackendSeq: 0,
  runtimeLogRequestActive: false,
  runtimeLogHistoryRequestActive: false,
  runtimeLogTotal: 0,
  lastRuntimeLogKey: "",
  measurementDeltaSeq: 0,
  measurementDeltaRequestActive: false,
  systemParameters: { clock_speed: 1, compute_interval_seconds: 1, storage_initial_soc: 0.5 },
  systemParametersDirty: false,
  systemParametersSaving: false,
  overviewBottomHeight: overviewInitialBottomHeight(),
  overviewBottomSplitDrag: null,
  overviewBottomColumnRatio: overviewInitialBottomColumnRatio(),
  overviewBottomColumnSplitDrag: null,
  verticalSplitRatios: initialVerticalSplitRatios(),
  verticalSplitDrag: null,
  virtualTables: {},
  virtualTableScrollRaf: {},
};

const $ = (id) => document.getElementById(id);
const deviceTreeRenderKeys = new WeakMap();
const MODE_OPTIONS = ["PQ", "PV", "PH", "V"];

function overviewInitialBottomHeight() {
  const storedHeight = Number(localStorage.getItem(OVERVIEW_BOTTOM_HEIGHT_KEY));
  if (!Number.isFinite(storedHeight) || storedHeight <= 0) return OVERVIEW_BOTTOM_DEFAULT_HEIGHT;
  return Math.max(OVERVIEW_BOTTOM_MIN_HEIGHT, Math.min(OVERVIEW_BOTTOM_MAX_HEIGHT, storedHeight));
}

function overviewInitialBottomColumnRatio() {
  const storedRatio = Number(localStorage.getItem(OVERVIEW_BOTTOM_COLUMN_RATIO_KEY));
  if (!Number.isFinite(storedRatio) || storedRatio <= 0) return OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO;
  return Math.max(10, Math.min(90, storedRatio));
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
const TRACE_HIGH_RES_WINDOW_MINUTES = 24 * 60;
const VIRTUAL_TABLE_ROW_HEIGHT = 34;
const VIRTUAL_TABLE_MIN_ROWS = 220;
const VIRTUAL_TABLE_BUFFER_ROWS = 12;
const WEATHER_MEASUREMENT_LABELS = {
  WIND_SPEED: { label: "风速", unit: "m/s", order: 0 },
  SOLAR_IRRADIANCE: { label: "太阳辐照", unit: "W/m2", order: 1 },
  AIR_TEMP: { label: "气温", unit: "℃", order: 2 },
  HUMIDITY: { label: "湿度", unit: "%", order: 3 },
  AIR_PRESSURE: { label: "气压", unit: "hPa", order: 4 },
};
const SIGNAL_MEASUREMENT_LABELS = {
  RUN_STAT: { label: "运行状态", order: 0 },
  STATUS: { label: "开关状态", order: 1 },
};
let pendingImportDefinitionFile = null;
let pendingNewModelFile = null;
let pendingNewModelSvgFile = null;
let pendingUpdateModelFile = null;
let pendingUpdateModelSvgFile = null;

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

function canvasRenderedSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  const rect = canvas.getBoundingClientRect();
  return {
    width: Math.max(1, Math.round(rect.width || canvas.clientWidth || fallbackWidth)),
    height: Math.max(1, Math.round(rect.height || canvas.clientHeight || fallbackHeight)),
  };
}

function resizeCanvasToRenderedSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  if (!canvas) return false;
  const { width, height } = canvasRenderedSize(canvas, fallbackWidth, fallbackHeight);
  if (canvas.width === width && canvas.height === height) return false;
  canvas.width = width;
  canvas.height = height;
  return true;
}

function sampleCurvePointsForCanvas(values, canvasWidth, density = 1.5) {
  const total = Array.isArray(values) ? values.length : 0;
  const target = Math.max(16, Math.floor((Number(canvasWidth) || 900) * density));
  if (total <= target) return values.map((value, index) => ({ index, value }));
  const bucketSize = total / target;
  const sampled = new Map();
  for (let bucket = 0; bucket < target; bucket += 1) {
    const start = Math.floor(bucket * bucketSize);
    const end = Math.min(total, Math.max(start + 1, Math.ceil((bucket + 1) * bucketSize)));
    let minIndex = start;
    let maxIndex = start;
    for (let index = start; index < end; index += 1) {
      if (Number(values[index]) < Number(values[minIndex])) minIndex = index;
      if (Number(values[index]) > Number(values[maxIndex])) maxIndex = index;
    }
    [start, minIndex, maxIndex, end - 1].forEach((index) => sampled.set(index, values[index]));
  }
  sampled.set(total - 1, values[total - 1]);
  return Array.from(sampled.entries())
    .sort((left, right) => left[0] - right[0])
    .map(([index, value]) => ({ index, value }));
}

function compactTraceHistory(history, visibleWindowMinutes = 24 * 60) {
  if (!Array.isArray(history) || history.length <= TRACE_HISTORY_LIMIT) return history || [];
  const latestMinute = Number(history[history.length - 1]?.minute ?? 0) || 0;
  const highResStart = latestMinute - Math.max(TRACE_HIGH_RES_WINDOW_MINUTES, Number(visibleWindowMinutes) || 0);
  const recent = [];
  const archived = new Map();
  const bucketMinutes = Math.max(5, Math.ceil(Math.max(1, latestMinute - highResStart) / 1200));
  history.forEach((point) => {
    const minute = Number(point?.minute ?? 0) || 0;
    if (minute >= highResStart) {
      recent.push(point);
      return;
    }
    const bucket = Math.floor(minute / bucketMinutes);
    archived.set(bucket, point);
  });
  return [...archived.values(), ...recent].slice(-TRACE_HISTORY_LIMIT);
}

function virtualTableWindow(key, rows, options = {}) {
  const sourceRows = Array.isArray(rows) ? rows : [];
  const total = sourceRows.length;
  const rowHeight = Math.max(1, Number(options.rowHeight) || VIRTUAL_TABLE_ROW_HEIGHT);
  const minRows = Math.max(1, Number(options.minRows) || VIRTUAL_TABLE_MIN_ROWS);
  const bufferRows = Math.max(0, Number(options.bufferRows) || VIRTUAL_TABLE_BUFFER_ROWS);
  if (total <= minRows) {
    return {
      enabled: false,
      rows: sourceRows,
      start: 0,
      end: total,
      beforeHeight: 0,
      afterHeight: 0,
      rowHeight,
      total,
    };
  }
  const tableState = state.virtualTables?.[key] || {};
  const viewportHeight = Math.max(180, Number(tableState.viewportHeight) || 420);
  const maxScrollTop = Math.max(0, total * rowHeight - viewportHeight);
  const scrollTop = clamp(Number(tableState.scrollTop) || 0, 0, maxScrollTop);
  const visibleRows = Math.ceil(viewportHeight / rowHeight) + bufferRows * 2;
  const maxStart = Math.max(0, total - visibleRows);
  const start = clamp(Math.floor(scrollTop / rowHeight) - bufferRows, 0, maxStart);
  const end = Math.min(total, start + visibleRows);
  state.virtualTables[key] = { ...tableState, scrollTop, viewportHeight };
  return {
    enabled: true,
    rows: sourceRows.slice(start, end),
    start,
    end,
    beforeHeight: start * rowHeight,
    afterHeight: Math.max(0, total - end) * rowHeight,
    rowHeight,
    total,
    scrollTop,
    viewportHeight,
  };
}

function renderVirtualSpacerRow(height, colSpan) {
  if (!height || height <= 0) return "";
  return `<tr class="virtual-table-spacer" aria-hidden="true"><td colspan="${Number(colSpan) || 1}" style="height:${Math.round(height)}px"></td></tr>`;
}

function restoreVirtualTableScroll(container, key) {
  const selector = `[data-virtual-table="${key}"]`;
  const scroller = container?.matches?.(selector) ? container : container?.querySelector?.(selector);
  if (!scroller) return;
  const tableState = state.virtualTables?.[key] || {};
  const scrollTop = Number(tableState.scrollTop) || 0;
  if (Math.abs(scroller.scrollTop - scrollTop) > 1) scroller.scrollTop = scrollTop;
  state.virtualTables[key] = {
    ...tableState,
    scrollTop: scroller.scrollTop,
    viewportHeight: scroller.clientHeight || tableState.viewportHeight || 420,
  };
}

function scheduleVirtualTableRender(key) {
  if (!key) return;
  state.virtualTableScrollRaf = state.virtualTableScrollRaf || {};
  if (state.virtualTableScrollRaf[key]) return;
  state.virtualTableScrollRaf[key] = requestAnimationFrame(() => {
    delete state.virtualTableScrollRaf[key];
    if (key === "measurementCompare" && currentPageName() === "measurements") {
      renderMeasurementCompareTable();
    }
    if (key.startsWith("runtimeCommand") && currentPageName() === "runtime") {
      renderRuntimeDeviceTable();
    }
    if (key.startsWith("curveEditor:") && currentPageName() === "curves") {
      renderHourlyTable(true);
    }
  });
}

function handleVirtualTableScroll(event) {
  const scroller = event.target instanceof Element ? event.target.closest("[data-virtual-table]") : null;
  if (!scroller || scroller !== event.target) return;
  const key = scroller.dataset.virtualTable || "";
  const tableState = state.virtualTables?.[key] || {};
  state.virtualTables[key] = {
    ...tableState,
    scrollTop: scroller.scrollTop,
    viewportHeight: scroller.clientHeight || tableState.viewportHeight || 420,
  };
  scheduleVirtualTableRender(key);
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

function deviceTreeSearchText(scope) {
  return String(state.deviceTreeSearch?.[scope] || "").trim().toLocaleLowerCase("zh-CN");
}

function deviceTreeVisibleName(item, devType = "") {
  const name = String(item?.dev_name ?? item?.name ?? "");
  if ((devType || item?.dev_type) === "Environment" && name === "weather") return "气象";
  return name;
}

function deviceTreeSearchFields(item, devType = "") {
  const raw = item?.raw || {};
  return [
    devType,
    item?.dev_type,
    item?.dev_name,
    item?.name,
    deviceTreeVisibleName(item, devType),
    item?.idx,
    raw.idx,
    item?.count,
    item?.mode,
    item ? deviceTreeBadge(item) : "",
  ].filter((value) => value !== undefined && value !== null && String(value).trim() !== "");
}

function filterDeviceTreeGroups(groupEntries, scope) {
  const query = deviceTreeSearchText(scope);
  const total = groupEntries.reduce((sum, [, items]) => sum + items.length, 0);
  if (!query) return { groupEntries, total, filteredTotal: total, query };
  const filtered = groupEntries
    .map(([devType, items]) => {
      const typeText = [devType, devType === "Environment" ? "气象环境" : ""]
        .join(" ")
        .toLocaleLowerCase("zh-CN");
      const matchedItems = typeText.includes(query)
        ? items
        : items.filter((item) => deviceTreeSearchFields(item, devType).join(" ").toLocaleLowerCase("zh-CN").includes(query));
      return [devType, matchedItems];
    })
    .filter(([, items]) => items.length);
  const filteredTotal = filtered.reduce((sum, [, items]) => sum + items.length, 0);
  return { groupEntries: filtered, total, filteredTotal, query };
}

function deviceTreeSummary(result) {
  return result.query
    ? `${result.groupEntries.length} 类 · ${result.filteredTotal}/${result.total} 台`
    : `${result.groupEntries.length} 类 · ${result.total} 台`;
}

function renderDeviceTreeFilterEmpty(query) {
  return query ? `<div class="empty-state">未匹配“${escapeHtml(query)}”</div>` : '<div class="empty-state">暂无设备</div>';
}

function updateDeviceTreeHtml(container, html, renderKey = html) {
  if (!container) return;
  const key = String(renderKey || "");
  if (deviceTreeRenderKeys.get(container) === key) return;
  const scrollTop = container.scrollTop;
  const restoreScrollTop = () => {
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    container.scrollTop = Math.min(scrollTop, maxScrollTop);
  };
  container.innerHTML = html;
  deviceTreeRenderKeys.set(container, key);
  restoreScrollTop();
  requestAnimationFrame(() => {
    restoreScrollTop();
  });
}

function deviceTreeItemType(item) {
  return String(item?.dev_type || item?.type || "");
}

function deviceTreeItemName(item) {
  return String(item?.dev_name || item?.name || "");
}

function deviceTreeFilterKey(devType, devName = "") {
  return `${devType || "all"}::${devName || ""}`;
}

function deviceTreeFilterItem(devType, devName = "") {
  return { dev_type: devType || "all", dev_name: devName || "" };
}

function uniqueDeviceTreeSelection(items) {
  const seen = new Set();
  const result = [];
  (items || []).forEach((item) => {
    const devType = String(item?.dev_type || "all");
    const devName = String(item?.dev_name || "");
    const key = deviceTreeFilterKey(devType, devName);
    if (seen.has(key)) return;
    seen.add(key);
    result.push(deviceTreeFilterItem(devType, devName));
  });
  return result.some((item) => item.dev_type === "all")
    ? [deviceTreeFilterItem("all", "")]
    : result;
}

function deviceTreeFilterSelection(filter = {}) {
  const selectedItems = Array.isArray(filter?.selected_items) ? filter.selected_items : [];
  const selected = uniqueDeviceTreeSelection(selectedItems);
  if (selected.length) return selected;
  return [deviceTreeFilterItem(filter?.dev_type || "all", filter?.dev_name || "")];
}

function withDeviceTreeSelection(filter = {}, selection = []) {
  const selected = uniqueDeviceTreeSelection(selection);
  const primary = selected[0] || deviceTreeFilterItem("all", "");
  return {
    ...filter,
    dev_type: primary.dev_type,
    dev_name: primary.dev_name,
    selected_items: selected.length ? selected : [deviceTreeFilterItem("all", "")],
  };
}

function isDeviceTreeNodeActive(filter, devType, devName = "") {
  const key = deviceTreeFilterKey(devType || "all", devName || "");
  return deviceTreeFilterSelection(filter).some((item) => deviceTreeFilterKey(item.dev_type, item.dev_name) === key);
}

function isDeviceTreeParentActive(filter, devType) {
  return deviceTreeFilterSelection(filter).some((item) => item.dev_type === devType);
}

function deviceFilterMatches(dev, filter) {
  const selection = deviceTreeFilterSelection(filter);
  if (selection.some((item) => item.dev_type === "all")) return true;
  const devType = deviceTreeItemType(dev);
  const devName = deviceTreeItemName(dev);
  return selection.some((item) => item.dev_type === devType && (!item.dev_name || item.dev_name === devName));
}

function deviceTreeButtonItem(button, dataPrefix) {
  const dataset = button?.dataset || {};
  const typeKey = `${dataPrefix}TreeType`;
  const nameKey = `${dataPrefix}TreeName`;
  return deviceTreeFilterItem(dataset[typeKey] || "all", dataset[nameKey] || "");
}

function selectDeviceTreeRangeItems(button, dataPrefix, anchorKey = "") {
  const container = button?.closest?.(".device-tree") || button?.parentElement;
  if (!container) return [deviceTreeButtonItem(button, dataPrefix)];
  const selector = `[data-${dataPrefix.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)}-tree-type]`;
  const buttons = Array.from(container.querySelectorAll(selector)).filter((item) => item instanceof HTMLElement);
  const currentKey = deviceTreeFilterKey(
    button.dataset?.[`${dataPrefix}TreeType`] || "all",
    button.dataset?.[`${dataPrefix}TreeName`] || "",
  );
  const currentIndex = buttons.findIndex((item) => deviceTreeFilterKey(
    item.dataset?.[`${dataPrefix}TreeType`] || "all",
    item.dataset?.[`${dataPrefix}TreeName`] || "",
  ) === currentKey);
  const anchorIndex = buttons.findIndex((item) => deviceTreeFilterKey(
    item.dataset?.[`${dataPrefix}TreeType`] || "all",
    item.dataset?.[`${dataPrefix}TreeName`] || "",
  ) === anchorKey);
  if (currentIndex < 0 || anchorIndex < 0) return [deviceTreeButtonItem(button, dataPrefix)];
  const [start, end] = currentIndex < anchorIndex ? [currentIndex, anchorIndex] : [anchorIndex, currentIndex];
  return buttons.slice(start, end + 1).map((item) => deviceTreeButtonItem(item, dataPrefix));
}

function updateDeviceTreeFilterSelection(filterName, devType, devName = "", event = null, dataPrefix = "", button = null) {
  const currentFilter = state[filterName] || { dev_type: "all", dev_name: "" };
  const clicked = deviceTreeFilterItem(devType || "all", devName || "");
  const clickedKey = deviceTreeFilterKey(clicked.dev_type, clicked.dev_name);
  const isMulti = Boolean(event?.ctrlKey || event?.metaKey);
  const isRange = Boolean(event?.shiftKey);
  let nextSelection = [clicked];
  const targetButton = button || event?.currentTarget;
  if (clicked.dev_type !== "all" && isRange && dataPrefix && targetButton) {
    nextSelection = selectDeviceTreeRangeItems(
      targetButton,
      dataPrefix,
      state.deviceTreeSelectionAnchors?.[filterName] || "",
    );
  } else if (clicked.dev_type !== "all" && isMulti) {
    const currentSelection = deviceTreeFilterSelection(currentFilter).filter((item) => item.dev_type !== "all");
    const exists = currentSelection.some((item) => deviceTreeFilterKey(item.dev_type, item.dev_name) === clickedKey);
    nextSelection = exists
      ? currentSelection.filter((item) => deviceTreeFilterKey(item.dev_type, item.dev_name) !== clickedKey)
      : [...currentSelection, clicked];
    if (!nextSelection.length) nextSelection = [deviceTreeFilterItem("all", "")];
  }
  state.deviceTreeSelectionAnchors = {
    ...(state.deviceTreeSelectionAnchors || {}),
    [filterName]: clickedKey,
  };
  state[filterName] = withDeviceTreeSelection(currentFilter, nextSelection);
  return state[filterName];
}

function deviceFilterLabel(filter = {}) {
  const selection = deviceTreeFilterSelection(filter);
  if (!selection.length || selection[0].dev_type === "all") return "全部设备";
  if (selection.length > 1) return `已选 ${selection.length} 项`;
  return selection[0].dev_name || selection[0].dev_type;
}

function tableFilterText(value) {
  return String(value ?? "").trim().toLocaleLowerCase("zh-CN");
}

function tableFilterMatchesKeyword(fields, keyword) {
  const query = tableFilterText(keyword);
  if (!query) return true;
  return (fields || []).some((field) => tableFilterText(field).includes(query));
}

function tableFilterTypeOptions(rows, labelFn) {
  const labels = new Map();
  (rows || []).forEach((row) => {
    const label = String(labelFn(row) || "").trim();
    if (label) labels.set(label, label);
  });
  return Array.from(labels.values()).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncTableKeywordFilter(inputId, value) {
  const input = $(inputId);
  if (input && input.value !== String(value || "")) input.value = String(value || "");
}

function syncTableTypeFilter(selectId, stateKey, options) {
  const select = $(selectId);
  if (!select) return;
  if (state[stateKey] !== "all" && !(options || []).includes(state[stateKey])) {
    state[stateKey] = "all";
  }
  const html = [
    '<option value="all">全部类型</option>',
    ...(options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`),
  ].join("");
  if (select.innerHTML !== html) select.innerHTML = html;
  if (select.value !== state[stateKey]) select.value = state[stateKey];
}

function tableFilterIsActive(keyword, type) {
  return Boolean(String(keyword || "").trim()) || (type && type !== "all");
}

function refreshDeviceTreeFilterScope(scope) {
  if (scope === "model") renderGridModelDeviceTree();
  if (scope === "faultDevice") renderFaultDeviceTree();
  if (scope === "faultMeasurement") renderFaultMeasurementTree();
  if (scope === "mode") renderModeDeviceTree();
  if (scope === "runtime") renderRuntimeDeviceTree();
  if (scope === "measurement") renderMeasurementCompareDeviceTree();
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

function clockControlButtonDisabled(action, clockState) {
  if (clockState === "running" && ["start", "step"].includes(action)) return true;
  if (clockState === "paused" && action === "pause") return true;
  if (clockState === "stopped" && ["stop", "pause", "step"].includes(action)) return true;
  return false;
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
    button.disabled = clockControlButtonDisabled(action, clock.state || "stopped");
    button.setAttribute("aria-disabled", button.disabled ? "true" : "false");
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
    storage_initial_soc: Math.max(0, Math.min(1, parameterNumber(params.storage_initial_soc, 0.5))),
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
  const currentStorageInitialSoc = $("currentStorageInitialSoc");
  if (currentSpeed) currentSpeed.textContent = `x${parameterText(params.clock_speed, 1)}`;
  if (currentInterval) currentInterval.textContent = `${parameterText(params.compute_interval_seconds, 2)} s`;
  if (currentStorageInitialSoc) currentStorageInitialSoc.textContent = parameterText(params.storage_initial_soc, 2);

  const form = $("systemParameterForm");
  const isEditing = Boolean(form?.contains(document.activeElement));
  if (!state.systemParametersDirty && !isEditing) {
    const speedInput = $("parameterClockSpeed");
    const intervalInput = $("parameterComputeInterval");
    const storageInitialSocInput = $("parameterStorageInitialSoc");
    if (speedInput) speedInput.value = String(params.clock_speed);
    if (intervalInput) intervalInput.value = parameterText(params.compute_interval_seconds, 2);
    if (storageInitialSocInput) storageInitialSocInput.value = parameterText(params.storage_initial_soc, 2);
  }

  const summary = $("systemParameterSummary");
  if (summary) {
    summary.textContent = state.systemParametersSaving
      ? "保存中"
      : state.systemParametersDirty
        ? "有未保存修改"
        : `x${parameterText(params.clock_speed, 1)} · ${parameterText(params.compute_interval_seconds, 2)} s · SOC ${parameterText(params.storage_initial_soc, 2)}`;
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
    parameterStorageInitialSocState: parameterText(params.storage_initial_soc, 2),
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
    storage_initial_soc: Math.max(
      0,
      Math.min(
        1,
        parameterNumber(
          $("parameterStorageInitialSoc")?.value,
          state.systemParameters.storage_initial_soc ?? 0.5,
        ),
      ),
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

function setNewModelMessage(text, kind = "") {
  const message = $("newModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setNewModelBusy(isBusy) {
  const confirm = $("confirmNewModel");
  const button = $("newModelButton");
  const input = $("newModelName");
  const selectButton = $("selectNewModelFile");
  const selectSvgButton = $("selectNewModelSvgFile");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "新建中" : "新建";
  }
  if (button) button.disabled = isBusy;
  if (input) input.disabled = isBusy;
  if (selectButton) selectButton.disabled = isBusy;
  if (selectSvgButton) selectSvgButton.disabled = isBusy;
}

function uniqueNewModelName(baseName = "新模型") {
  const base = String(baseName || "新模型").trim().replace(/\s+/g, "_") || "新模型";
  if (!isModelNameTaken(base)) return base;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${base}_${index}`;
    if (!isModelNameTaken(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

function suggestedNewModelName(filename) {
  return uniqueNewModelName(
    String(filename || "新模型")
      .replace(/\.e$/i, "")
      .trim() || "新模型",
  );
}

function validateNewModelForm(showBlank = false) {
  const input = $("newModelName");
  const confirm = $("confirmNewModel");
  const name = String(input?.value || "").trim();
  if (!name) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(`模型已存在：${name}，请输入新的模型名称。`, "error");
    return false;
  }
  if (!pendingNewModelFile) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(showBlank ? "请选择 model.e 文件。" : "", showBlank ? "error" : "");
    return false;
  }
  if (!String(pendingNewModelFile.name || "").toLowerCase().endsWith(".e")) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage("请选择 .e 格式的模型定义文件。", "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setNewModelMessage("");
  return true;
}

function setModelManagementMessage(text, kind = "") {
  const message = $("modelManagementMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function modelClockState(model) {
  const modelId = String(model?.id || "");
  if (modelId && modelId === state.activeModelId && state.snapshot?.clock?.state) {
    return state.snapshot.clock.state;
  }
  return String(model?.clock_state || "stopped");
}

function modelClockStateText(clockState) {
  return {
    running: "运行中",
    paused: "暂停中",
    stopped: "已停止",
  }[clockState] || clockState || "--";
}

function ensureSelectedManagementModelId(models = normalizeModels(state.models)) {
  if (!models.length) {
    state.selectedManagementModelId = "";
    return "";
  }
  const selectedId = String(state.selectedManagementModelId || "");
  if (selectedId && models.some((model) => String(model.id || "") === selectedId)) {
    return selectedId;
  }
  const activeId = String(state.activeModelId || "");
  const nextId = (activeId && models.some((model) => String(model.id || "") === activeId))
    ? activeId
    : String(models[0]?.id || "");
  state.selectedManagementModelId = nextId;
  return nextId;
}

function selectedManagementModelId() {
  return ensureSelectedManagementModelId();
}

function selectedManagementModel() {
  const modelId = selectedManagementModelId();
  return normalizeModels(state.models).find((model) => String(model.id || "") === modelId) || null;
}

function updateModelContextMenuActions() {
  const models = normalizeModels(state.models);
  const selected = selectedManagementModel();
  const hasSelected = Boolean(selected);
  const clockState = selected ? modelClockState(selected) : "";
  const menu = $("modelContextMenu");
  const exportButton = menu?.querySelector('[data-model-context-action="export"]');
  const cloneButton = menu?.querySelector('[data-model-context-action="clone"]');
  const updateButton = menu?.querySelector('[data-model-context-action="update"]');
  const deleteButton = menu?.querySelector('[data-model-context-action="delete"]');
  if (exportButton) exportButton.disabled = !hasSelected;
  if (cloneButton) cloneButton.disabled = !hasSelected;
  if (updateButton) {
    const canUpdate = hasSelected && clockState === "stopped";
    updateButton.disabled = !canUpdate;
    updateButton.title = !hasSelected
      ? "请选择模型"
      : (clockState === "stopped" ? "导入修改后的模型与图形数据" : "模型运行中或暂停中，不能修改");
  }
  if (deleteButton) {
    const canDelete = hasSelected && models.length > 1 && clockState === "stopped";
    deleteButton.disabled = !canDelete;
    deleteButton.title = !hasSelected
      ? "请选择模型"
      : (models.length <= 1
        ? "至少需要保留一个模型"
        : (clockState === "stopped" ? "删除选中的模型" : "模型运行中或暂停中，不能删除"));
  }
}

function setSelectedManagementModel(modelId, render = true) {
  state.selectedManagementModelId = String(modelId || "");
  ensureSelectedManagementModelId();
  updateModelContextMenuActions();
  if (render) renderModelManagementList();
}

function renderModelManagementList() {
  const list = $("modelManagementList");
  if (!list) return;
  const models = normalizeModels(state.models);
  if (!models.length) {
    list.innerHTML = '<div class="model-management-empty">暂无模型</div>';
    state.selectedManagementModelId = "";
    updateModelContextMenuActions();
    return;
  }
  const selectedId = ensureSelectedManagementModelId(models);
  const branchHtml = models.map((model) => {
    const modelId = String(model.id || "");
    const isActive = modelId === state.activeModelId;
    const isSelected = modelId === selectedId;
    const clockState = modelClockState(model);
    return `
      <div
        class="model-management-item ${isActive ? "is-active" : ""} ${isSelected ? "is-selected" : ""}"
        role="treeitem"
        tabindex="0"
        aria-selected="${isSelected ? "true" : "false"}"
        data-model-id="${escapeHtml(modelId)}"
      >
        <span class="model-management-node-mark" aria-hidden="true"></span>
        <strong class="model-node-name">${escapeHtml(model.name || modelId)}</strong>
        <div class="model-item-badges">
          ${isActive ? '<span class="model-current-pill">当前</span>' : ""}
          <span class="model-state-pill" data-state="${escapeHtml(clockState)}">${escapeHtml(modelClockStateText(clockState))}</span>
        </div>
      </div>
    `;
  }).join("");
  list.innerHTML = `
    <div class="model-management-tree-root" role="treeitem" aria-expanded="true">
      <span class="model-management-root-caret" aria-hidden="true">▾</span>
      <strong>模型列表</strong>
      <small>${models.length} 个</small>
    </div>
    <div class="model-management-branches" role="group">
      ${branchHtml}
    </div>
  `;
  updateModelContextMenuActions();
}

async function openModelManagementDialog() {
  const dialog = $("modelManagementDialog");
  if (!dialog) return;
  dialog.hidden = false;
  setModelManagementMessage("正在读取模型列表...");
  try {
    await loadModels();
    ensureSelectedManagementModelId();
    renderModelManagementList();
    setModelManagementMessage(`共 ${state.models.length} 个模型，右键模型节点可操作。`, "ok");
  } catch (error) {
    renderModelManagementList();
    setModelManagementMessage(apiErrorText(error), "error");
  }
}

function closeModelManagementDialog() {
  closeModelContextMenu();
  const dialog = $("modelManagementDialog");
  if (dialog) dialog.hidden = true;
  setModelManagementMessage("");
}

function openNewModelDialog() {
  const dialog = $("newModelDialog");
  const input = $("newModelName");
  const filename = $("newModelFilename");
  const svgFilename = $("newModelSvgFilename");
  const fileInput = $("newModelFileInput");
  const svgInput = $("newModelSvgInput");
  if (!dialog || !input) return;
  pendingNewModelFile = null;
  pendingNewModelSvgFile = null;
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  if (filename) filename.textContent = "未选择文件";
  if (svgFilename) svgFilename.textContent = "未选择图形";
  input.value = uniqueNewModelName("新模型");
  dialog.hidden = false;
  validateNewModelForm();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeNewModelDialog() {
  const dialog = $("newModelDialog");
  if (dialog) dialog.hidden = true;
  pendingNewModelFile = null;
  pendingNewModelSvgFile = null;
  const fileInput = $("newModelFileInput");
  const svgInput = $("newModelSvgInput");
  const filename = $("newModelFilename");
  const svgFilename = $("newModelSvgFilename");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  if (filename) filename.textContent = "未选择文件";
  if (svgFilename) svgFilename.textContent = "未选择图形";
  setNewModelMessage("");
  setNewModelBusy(false);
}

function handleNewModelFileSelected(event) {
  const file = event.target.files?.[0] || null;
  pendingNewModelFile = file;
  const filename = $("newModelFilename");
  if (filename) filename.textContent = file?.name || "未选择文件";
  const input = $("newModelName");
  if (file && input && !String(input.value || "").trim()) {
    input.value = suggestedNewModelName(file.name);
  }
  validateNewModelForm(Boolean(file));
}

function handleNewModelSvgFileSelected(event) {
  const file = event.target.files?.[0] || null;
  pendingNewModelSvgFile = file;
  const filename = $("newModelSvgFilename");
  if (filename) filename.textContent = file?.name || "未选择图形";
  if (file && !String(file.name || "").toLowerCase().endsWith(".svg")) {
    setNewModelMessage("请选择 .svg 格式的接线图文件。", "error");
    const confirm = $("confirmNewModel");
    if (confirm) confirm.disabled = true;
    return;
  }
  validateNewModelForm(Boolean(pendingNewModelFile));
}

async function createNewModelFromFile() {
  const file = pendingNewModelFile;
  const input = $("newModelName");
  const name = String(input?.value || "").trim();
  if (!file || !validateNewModelForm(true)) {
    input?.focus();
    return;
  }
  setNewModelBusy(true);
  setNewModelMessage("正在读取 model.e 并生成模型定义...");
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const diagramSvgBase64 = pendingNewModelSvgFile
      ? arrayBufferToBase64(await pendingNewModelSvgFile.arrayBuffer())
      : "";
    const result = await api("/api/models/create", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({
        name,
        filename: file.name,
        data_base64: dataBase64,
        diagram_filename: pendingNewModelSvgFile?.name || "",
        diagram_svg_base64: diagramSvgBase64,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    closeNewModelDialog();
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setNewModelMessage(
      message.includes("已存在") ? `${message}，请输入新的模型名称。` : message,
      "error",
    );
  } finally {
    setNewModelBusy(false);
    if (!$("newModelDialog").hidden) validateNewModelForm();
  }
}

function setUpdateModelMessage(text, kind = "") {
  const message = $("updateModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setUpdateModelBusy(isBusy) {
  const confirm = $("confirmUpdateModel");
  const selectFile = $("selectUpdateModelFile");
  const selectSvg = $("selectUpdateModelSvgFile");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "修改中" : "修改";
  }
  if (selectFile) selectFile.disabled = isBusy;
  if (selectSvg) selectSvg.disabled = isBusy;
}

function validateUpdateModelForm(showBlank = false) {
  const confirm = $("confirmUpdateModel");
  const target = state.models.find((model) => model.id === state.updateTargetModelId);
  if (!target) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择要修改的模型。", "error");
    return false;
  }
  if (modelClockState(target) !== "stopped") {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("模型运行中或暂停中，不能修改。", "error");
    return false;
  }
  if (!pendingUpdateModelFile) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage(showBlank ? "请选择 model.e 文件。" : "");
    return false;
  }
  if (!String(pendingUpdateModelFile.name || "").toLowerCase().endsWith(".e")) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择 .e 格式的模型定义文件。", "error");
    return false;
  }
  if (pendingUpdateModelSvgFile && !String(pendingUpdateModelSvgFile.name || "").toLowerCase().endsWith(".svg")) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择 .svg 格式的接线图文件。", "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setUpdateModelMessage("");
  return true;
}

function openUpdateModelDialog(modelId = selectedManagementModelId()) {
  const target = normalizeModels(state.models).find((model) => String(model.id || "") === String(modelId || ""));
  if (!target) {
    setModelManagementMessage("请选择要修改的模型。", "error");
    return;
  }
  if (modelClockState(target) !== "stopped") {
    setModelManagementMessage("模型运行中或暂停中，不能修改。", "error");
    return;
  }
  state.updateTargetModelId = String(target.id || "");
  pendingUpdateModelFile = null;
  pendingUpdateModelSvgFile = null;
  const dialog = $("updateModelDialog");
  if (!dialog) return;
  const fileInput = $("updateModelFileInput");
  const svgInput = $("updateModelSvgInput");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  $("updateModelTargetName").textContent = target.name || target.id || "--";
  $("updateModelFilename").textContent = "未选择文件";
  $("updateModelSvgFilename").textContent = "未选择图形";
  dialog.hidden = false;
  validateUpdateModelForm();
}

function closeUpdateModelDialog() {
  const dialog = $("updateModelDialog");
  if (dialog) dialog.hidden = true;
  state.updateTargetModelId = "";
  pendingUpdateModelFile = null;
  pendingUpdateModelSvgFile = null;
  const fileInput = $("updateModelFileInput");
  const svgInput = $("updateModelSvgInput");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  setUpdateModelMessage("");
  setUpdateModelBusy(false);
}

function handleUpdateModelFileSelected(event) {
  const file = event.target.files?.[0] || null;
  pendingUpdateModelFile = file;
  const filename = $("updateModelFilename");
  if (filename) filename.textContent = file?.name || "未选择文件";
  validateUpdateModelForm(Boolean(file));
}

function handleUpdateModelSvgFileSelected(event) {
  const file = event.target.files?.[0] || null;
  pendingUpdateModelSvgFile = file;
  const filename = $("updateModelSvgFilename");
  if (filename) filename.textContent = file?.name || "未选择图形";
  validateUpdateModelForm(Boolean(pendingUpdateModelFile));
}

async function updateModelFromFile() {
  const file = pendingUpdateModelFile;
  const modelId = state.updateTargetModelId;
  if (!file || !validateUpdateModelForm(true)) return;
  const updatedActiveModel = String(modelId || "") === String(state.activeModelId || "");
  setUpdateModelBusy(true);
  setUpdateModelMessage("正在导入修改后的模型与图形数据...");
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const diagramSvgBase64 = pendingUpdateModelSvgFile
      ? arrayBufferToBase64(await pendingUpdateModelSvgFile.arrayBuffer())
      : "";
    const result = await api("/api/models/update-definitions", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({
        model_id: modelId,
        filename: file.name,
        data_base64: dataBase64,
        diagram_filename: pendingUpdateModelSvgFile?.name || "",
        diagram_svg_base64: diagramSvgBase64,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    closeUpdateModelDialog();
    state.selectedManagementModelId = modelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage("模型已修改。", "ok");
    if (updatedActiveModel) await refresh();
  } catch (error) {
    setUpdateModelMessage(apiErrorText(error), "error");
  } finally {
    setUpdateModelBusy(false);
    if (!$("updateModelDialog").hidden) validateUpdateModelForm();
  }
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

function openCloneModelDialog(sourceModelId = "") {
  const dialog = $("cloneModelDialog");
  const input = $("cloneModelName");
  if (!dialog || !input) return;
  state.cloneSourceModelId = sourceModelId || state.activeModelId || "";
  const source = state.models.find((model) => model.id === state.cloneSourceModelId) || activeModelInfo();
  const base = String(source.name || source.id || "model").replace(/\s+/g, "_");
  input.value = uniqueCloneName(base);
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
  state.cloneSourceModelId = "";
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
  const input = $("cloneModelName");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "复制中" : "复制";
  }
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
    const sourceModelId = state.cloneSourceModelId || state.activeModelId || "";
    const result = await api("/api/models/clone", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ model_id: sourceModelId, name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    state.selectedManagementModelId = newModelId;
    closeCloneModelDialog();
    renderModelSelector();
    renderModelManagementList();
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
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
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

const SIMULATOR_PAGE_ROUTES = {
  "/": "overview",
  "/overview": "overview",
  "/model": "model",
  "/diagram": "diagram",
  "/curves": "curves",
  "/faults": "faults",
  "/modes": "modes",
  "/parameters": "parameters",
  "/runtime": "runtime",
  "/measurements": "measurements",
  "/logs": "logs",
};

function normalizePagePath(pathname) {
  const path = String(pathname || "/").replace(/\/+$/, "") || "/";
  return path.startsWith("/") ? path : `/${path}`;
}

function pagePath(page) {
  return page === "overview" ? "/" : `/${page}`;
}

function pageFromLocation() {
  const fallback = document.querySelector(".app-shell")?.dataset.defaultPage || "overview";
  const hashPage = (location.hash || "").replace("#", "").trim();
  if (hashPage) return hashPage;
  return SIMULATOR_PAGE_ROUTES[normalizePagePath(location.pathname)] || fallback;
}

function currentPageName() {
  return state.activePage || document.querySelector("[data-page].is-active")?.dataset.page || pageFromLocation();
}

function collectPageSections() {
  const main = document.querySelector(".page-main");
  if (!main) return;
  state.pageMain = main;
  state.pageSections = {};
  Array.from(main.children).forEach((section) => {
    if (!(section instanceof HTMLElement) || !section.dataset.page) return;
    section.classList.remove("is-active");
    state.pageSections[section.dataset.page] = section;
    section.remove();
  });
}

function mountPageSection(page) {
  const main = state.pageMain || document.querySelector(".page-main");
  const section = state.pageSections?.[page];
  if (!main || !section) return;
  const current = Array.from(main.children).find((child) => child instanceof HTMLElement && child.dataset.page);
  if (current === section) {
    section.classList.add("is-active");
    return;
  }
  if (current) {
    current.classList.remove("is-active");
    current.remove();
  }
  section.classList.add("is-active");
  main.appendChild(section);
}

function showPage(page, updateHash = true) {
  const target = state.pageSections?.[page] ? page : "overview";
  const previousPage = state.activePage || currentPageName();
  if (previousPage === "curves" && target !== "curves") cancelCurveRequests();
  state.activePage = target;
  mountPageSection(target);
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.navPage === target);
  });
  const nextPath = pagePath(target);
  if (updateHash && normalizePagePath(location.pathname) !== nextPath) {
    history.pushState(null, "", nextPath);
  } else if (location.hash) {
    history.replaceState(null, "", nextPath);
  }
  requestAnimationFrame(() => {
    renderActiveSimulatorPage(state.snapshot, true);
    if (state.snapshot && !hasStaticSnapshotPayload(state.snapshot, staticSnapshotKeysForPage(target))) {
      refresh();
    }
  });
}

function initPageNavigation() {
  collectPageSections();
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.navPage));
  });
  window.addEventListener("popstate", () => showPage(pageFromLocation(), false));
  window.addEventListener("hashchange", () => showPage(pageFromLocation(), true));
  showPage(pageFromLocation(), false);
}

function modelScopedPath(path) {
  if (!state.activeModelId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}model_id=${encodeURIComponent(state.activeModelId)}`;
}

async function api(path, options = {}) {
  const {
    modelScoped = true,
    timeoutMs = API_REQUEST_TIMEOUT_MS,
    signal: callerSignal,
    ...fetchOptions
  } = options;
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  const controller = new AbortController();
  const boundedTimeout = Math.max(0, Number(timeoutMs) || 0);
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  const timeoutId = boundedTimeout
    ? setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, boundedTimeout)
    : null;
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }
  try {
    const response = await fetch(`${apiBase}${targetPath}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  } catch (error) {
    if (timedOut) throw new Error(`请求超时（${Math.round(boundedTimeout / 1000)} 秒）`);
    throw error;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    callerSignal?.removeEventListener?.("abort", abortFromCaller);
  }
}

const STATIC_SNAPSHOT_KEYS = [
  "files",
  "source_files",
  "work_files",
  "definitions",
  "curves",
  "settings",
  "device_parameters",
  "diagram",
];

const STATIC_SNAPSHOT_KEYS_BY_PAGE = {
  "overview": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "model": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "diagram": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters", "diagram"],
  "curves": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "faults": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "modes": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "parameters": ["settings"],
  "runtime": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "measurements": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "logs": [],
};

const CACHEABLE_STATIC_KEYS = STATIC_SNAPSHOT_KEYS.filter((key) => key !== "curves");

function staticSnapshotKeysForPage(page = currentPageName()) {
  return STATIC_SNAPSHOT_KEYS_BY_PAGE[page] || STATIC_SNAPSHOT_KEYS;
}

function hasStaticSnapshotPayload(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return Boolean(snapshot && requiredKeys.every((key) => snapshot[key] !== undefined));
}

function staticMetaSignature(meta) {
  return JSON.stringify(meta || null);
}

function staticMetaMatches(left, right) {
  return staticMetaSignature(left) === staticMetaSignature(right);
}

function readStaticCacheStore() {
  try {
    const raw = localStorage.getItem(STATIC_CACHE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function writeStaticCacheStore(store) {
  try {
    localStorage.setItem(STATIC_CACHE_STORAGE_KEY, JSON.stringify(store));
    return true;
  } catch (_error) {
    return false;
  }
}

function pruneStaticCacheStore(store) {
  const entries = Object.entries(store || {})
    .sort((left, right) => Number(right[1]?.updatedAt || 0) - Number(left[1]?.updatedAt || 0));
  return Object.fromEntries(entries.slice(0, STATIC_CACHE_MODEL_LIMIT));
}

function restoreStaticSnapshotCache(snapshot, page = currentPageName()) {
  if (!snapshot?.model?.id || !snapshot.static_meta) return snapshot;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => CACHEABLE_STATIC_KEYS.includes(key));
  if (!requiredKeys.length) return snapshot;
  const entry = readStaticCacheStore()[snapshot.model.id];
  if (!entry?.fields) return snapshot;
  let restored = snapshot;
  requiredKeys.forEach((key) => {
    if (restored[key] !== undefined) return;
    const cached = entry.fields[key];
    if (!cached || !staticMetaMatches(cached.meta, restored.static_meta?.[key])) return;
    if (restored === snapshot) restored = { ...snapshot };
    restored[key] = cached.value;
  });
  return restored;
}

function persistStaticSnapshotCache(snapshot, page = currentPageName()) {
  if (!snapshot?.model?.id || !snapshot.static_meta) return;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => (
    CACHEABLE_STATIC_KEYS.includes(key)
    && snapshot[key] !== undefined
    && snapshot.static_meta?.[key] !== undefined
  ));
  if (!requiredKeys.length) return;
  const store = readStaticCacheStore();
  const entry = store[snapshot.model.id] || { fields: {} };
  const fields = { ...(entry.fields || {}) };
  requiredKeys.forEach((key) => {
    fields[key] = {
      meta: snapshot.static_meta[key],
      value: snapshot[key],
    };
  });
  store[snapshot.model.id] = { updatedAt: Date.now(), fields };
  if (writeStaticCacheStore(pruneStaticCacheStore(store))) return;
  requiredKeys.forEach((key) => {
    if (fields[key]?.value?.svg) delete fields[key];
  });
  store[snapshot.model.id] = { updatedAt: Date.now(), fields };
  writeStaticCacheStore(pruneStaticCacheStore(store));
}

function staticSnapshotMissingKeys(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return (requiredKeys || []).filter((key) => snapshot?.[key] === undefined);
}

function pageNeedsMeasurementDelta(page = currentPageName()) {
  return ["overview", "diagram", "runtime", "measurements"].includes(page);
}

function pageNeedsRuntimeLogDelta(page = currentPageName()) {
  return ["overview", "logs"].includes(page);
}

function pageNeedsDevices(page = currentPageName()) {
  return ["overview", "faults", "modes", "runtime"].includes(page);
}

function pageNeedsDeviceStates(page = currentPageName()) {
  return page === "diagram";
}

function pageNeedsCommands(page = currentPageName()) {
  return ["overview", "diagram", "runtime"].includes(page);
}

function mergeSnapshot(previous, incoming) {
  if (!previous || !incoming) return incoming;
  const merged = { ...previous, ...incoming };
  const previousModelId = String(previous.model?.id || "");
  const incomingModelId = String(incoming.model?.id || "");
  const modelChanged = Boolean(previousModelId && incomingModelId && previousModelId !== incomingModelId);
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (incoming[key] !== undefined) return;
    const incomingMeta = incoming.static_meta?.[key];
    const previousMeta = previous.static_meta?.[key];
    const revisionChanged = Boolean(
      incomingMeta
      && previousMeta
      && !staticMetaMatches(incomingMeta, previousMeta)
    );
    if (modelChanged || revisionChanged) {
      delete merged[key];
      return;
    }
    if (previous[key] !== undefined) merged[key] = previous[key];
  });
  if (modelChanged && incoming.device_states === undefined) delete merged.device_states;
  if (incoming.runtime_logs === undefined) delete merged.runtime_logs;
  return merged;
}

function snapshotPollPath(page = currentPageName(), forceStaticKeys = null) {
  if (!Array.isArray(forceStaticKeys) && state.snapshot?.static_meta) {
    state.snapshot = restoreStaticSnapshotCache(state.snapshot, page);
  }
  const currentModelId = String(state.snapshot?.model?.id || "");
  const modelChanged = currentModelId && state.activeModelId && currentModelId !== state.activeModelId;
  const requiredStaticKeys = Array.isArray(forceStaticKeys)
    ? forceStaticKeys
    : (
      state.snapshot?.static_meta && !modelChanged
        ? staticSnapshotMissingKeys(state.snapshot, staticSnapshotKeysForPage(page))
        : []
    );
  const params = new URLSearchParams();
  params.set("logs", "0");
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("device_states", pageNeedsDeviceStates(page) ? "1" : "0");
  params.set("commands", pageNeedsCommands(page) ? "1" : "0");
  if (requiredStaticKeys.length) {
    params.set("static", requiredStaticKeys.join(","));
  } else {
    params.set("lite", "1");
  }
  return `/api/snapshot?${params.toString()}`;
}

function apiUrl(path, modelScoped = true) {
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  return `${apiBase}${targetPath}`;
}

function mergeRuntimeLogItems(items = [], { reset = false, latestSeq = 0, total = null } = {}) {
  if (reset) state.runtimeLogs = [];
  const bySeq = new Map();
  state.runtimeLogs.forEach((item) => {
    const seq = Number(item.seq) || 0;
    if (seq) bySeq.set(seq, item);
  });
  (items || []).forEach((item, index) => {
    const normalized = normalizeRuntimeLog(item, index + 1);
    const seq = Number(normalized.seq) || 0;
    if (seq) bySeq.set(seq, normalized);
  });
  state.runtimeLogs = Array.from(bySeq.values())
    .sort((left, right) => Number(right.seq || 0) - Number(left.seq || 0))
    .slice(0, 300);
  const nextBackendSeq = Math.max(
    Number(latestSeq) || 0,
    state.runtimeLogs.reduce((maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0), 0),
  );
  state.runtimeLogBackendSeq = reset ? nextBackendSeq : Math.max(
    Number(state.runtimeLogBackendSeq) || 0,
    nextBackendSeq,
  );
  if (Number.isFinite(Number(total))) {
    state.runtimeLogTotal = Math.max(Number(total) || 0, state.runtimeLogs.length);
  } else {
    state.runtimeLogTotal = Math.max(Number(state.runtimeLogTotal) || 0, state.runtimeLogs.length);
  }
  state.runtimeLogSeq = Math.max(state.runtimeLogSeq, state.runtimeLogBackendSeq);
}

async function refreshRuntimeLogs(renderNow = false) {
  if (state.runtimeLogRequestActive) return;
  state.runtimeLogRequestActive = true;
  try {
    const payload = await api(`/api/runtime-logs?after_seq=${state.runtimeLogBackendSeq}&limit=200`);
    const items = payload.items || payload.logs || [];
    const receivedLatestSeq = items.reduce(
      (maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0),
      Number(state.runtimeLogBackendSeq) || 0,
    );
    mergeRuntimeLogItems(items, {
      reset: Boolean(payload.reset),
      latestSeq: receivedLatestSeq || payload.latest_seq,
      total: payload.total,
    });
    if (renderNow && currentPageName() === "logs") renderRuntimeLogs();
  } catch (error) {
    console.error("运行日志增量刷新失败", error);
  } finally {
    state.runtimeLogRequestActive = false;
  }
}

async function fetchRuntimeLogHistoryPage(renderNow = false) {
  if (state.runtimeLogHistoryRequestActive || state.runtimeLogTypeFilter !== "all") return;
  const oldestSeq = state.runtimeLogs.reduce((minSeq, item) => {
    const seq = Number(item.seq) || 0;
    return seq > 0 ? Math.min(minSeq, seq) : minSeq;
  }, Number.POSITIVE_INFINITY);
  if (!Number.isFinite(oldestSeq) || oldestSeq <= 1) return;
  state.runtimeLogHistoryRequestActive = true;
  try {
    const payload = await api(`/api/runtime-logs?before_seq=${oldestSeq}&limit=120`);
    mergeRuntimeLogItems(payload.items || payload.logs || [], {
      latestSeq: payload.latest_seq,
      total: payload.total,
    });
    if (renderNow && currentPageName() === "logs") renderRuntimeLogs();
  } catch (error) {
    console.error("运行日志历史分页拉取失败", error);
  } finally {
    state.runtimeLogHistoryRequestActive = false;
  }
}

function measurementNameKey(item) {
  return String(item?.name || "");
}

function measurementChannelIndex(rows = []) {
  return new Map((rows || []).map((row) => [measurementNameKey(row), row]));
}

function ensureMeasurementChannelRow(measurements, definitionsByName, channel, item) {
  if (item.deleted) {
    measurements[channel] = (measurements[channel] || []).filter((row) => measurementNameKey(row) !== item.name);
    return null;
  }
  const rows = measurements[channel] || [];
  let row = rows.find((entry) => measurementNameKey(entry) === item.name);
  if (!row) {
    const definition = definitionsByName.get(item.name);
    if (!definition) return null;
    row = { ...definition };
    rows.push(row);
    measurements[channel] = rows;
  }
  return row;
}

function applyMeasurementDelta(payload) {
  if (!payload || !state.snapshot) return false;
  const measurements = state.snapshot.measurements || {};
  state.snapshot.measurements = measurements;
  if (payload.reset) {
    measurements.real = [];
    measurements.scada = [];
  }
  const definitions = measurements.definitions || state.snapshot.definitions?.measurement || [];
  const definitionsByName = new Map(definitions.map((row) => [measurementNameKey(row), row]));
  let changed = false;
  (payload.items || []).forEach((item) => {
    if (!item?.name) return;
    if (item.deleted) {
      ensureMeasurementChannelRow(measurements, definitionsByName, "real", item);
      ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item);
      changed = true;
      return;
    }
    const realRow = item.real_value !== undefined && item.real_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "real", item)
      : null;
    const scadaRow = item.scada_value !== undefined && item.scada_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item)
      : null;
    if (realRow) {
      realRow.value = item.real_value;
      realRow.valid = item.valid;
      realRow.updated_simu_time = item.updated_simu_time;
      realRow.updated_wall_time = item.updated_wall_time;
      changed = true;
    }
    if (scadaRow) {
      scadaRow.value = item.scada_value;
      scadaRow.valid = item.valid;
      scadaRow.updated_simu_time = item.updated_simu_time;
      scadaRow.updated_wall_time = item.updated_wall_time;
      changed = true;
    }
  });
  if (payload.reset) state.measurementDeltaSeq = Number(payload.seq) || 0;
  else state.measurementDeltaSeq = Math.max(Number(state.measurementDeltaSeq) || 0, Number(payload.seq) || 0);
  return changed;
}

async function refreshMeasurementDelta(renderNow = false) {
  if (state.measurementDeltaRequestActive || !state.snapshot) return false;
  state.measurementDeltaRequestActive = true;
  try {
    const payload = await api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}`);
    const changed = applyMeasurementDelta(payload);
    if (changed && renderNow && currentPageName() === "measurements") renderMeasurementCompareTable();
    return changed;
  } catch (error) {
    console.error("量测增量刷新失败", error);
    return false;
  } finally {
    state.measurementDeltaRequestActive = false;
  }
}

async function refreshSnapshotPayload(page = currentPageName()) {
  let snapshot = mergeSnapshot(state.snapshot, await api(snapshotPollPath(page)));
  snapshot = restoreStaticSnapshotCache(snapshot, page);
  let requiredStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  if (requiredStaticKeys.length) {
    snapshot = mergeSnapshot(snapshot, await api(snapshotPollPath(page, requiredStaticKeys)));
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    requiredStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  }
  if (!requiredStaticKeys.length) persistStaticSnapshotCache(snapshot, page);
  state.snapshot = snapshot;
  return snapshot;
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

async function exportDefinitionsArchive(modelId = state.activeModelId, actionButton = null) {
  const button = actionButton;
  const originalText = button?.textContent || "";
  if (button) button.disabled = true;
  try {
    let directoryHandle = null;
    if (typeof window.showDirectoryPicker === "function") {
      if (button) button.textContent = "选择目录";
      directoryHandle = await window.showDirectoryPicker({
        id: "simu-definition-export",
        mode: "readwrite",
        startIn: "downloads",
      });
    }
    if (button) button.textContent = "导出中";
    const targetModelId = String(modelId || state.activeModelId || "").trim();
    const exportPath = targetModelId
      ? `/api/export-definitions?format=json&model_id=${encodeURIComponent(targetModelId)}`
      : "/api/export-definitions?format=json";
    const payload = await api(exportPath, { modelScoped: false });
    const blob = blobFromBase64(payload.data_base64, payload.content_type);
    const filename = safeExportFilename(filenameFromDisposition("", payload.filename || "model_definitions.zip"));
    if (directoryHandle) {
      const fileHandle = await directoryHandle.getFileHandle(filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      if (button) button.textContent = "已导出";
    } else {
      downloadBlob(blob, filename);
    }
  } catch (error) {
    if (error?.name === "AbortError") return;
    alert(apiErrorText(error));
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function deleteManagedModel(modelId) {
  const target = state.models.find((model) => model.id === modelId);
  if (!target) return;
  if (normalizeModels(state.models).length <= 1) {
    setModelManagementMessage("至少需要保留一个模型。", "error");
    return;
  }
  if (modelClockState(target) !== "stopped") {
    setModelManagementMessage("模型运行中或暂停中，不能删除。", "error");
    return;
  }
  const modelName = target.name || target.id || modelId;
  if (!window.confirm(`确认删除模型“${modelName}”吗？此操作会删除对应模型文件夹和运行数据。`)) {
    return;
  }
  const deletedActiveModel = String(target.id || "") === String(state.activeModelId || "");
  setModelManagementMessage(`正在删除模型：${modelName}`);
  try {
    const result = await api("/api/models/delete", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ model_id: modelId }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const nextId = state.models.some((model) => model.id === state.activeModelId)
      ? state.activeModelId
      : (result.active_model_id || state.models[0]?.id || "");
    state.selectedManagementModelId = deletedActiveModel
      ? nextId
      : (state.models.some((model) => model.id === state.selectedManagementModelId)
        ? state.selectedManagementModelId
        : (state.activeModelId || nextId));
    if (deletedActiveModel) {
      setActiveModel(nextId, true);
    } else {
      renderModelSelector();
      renderModelManagementList();
    }
    setModelManagementMessage(`已删除模型：${modelName}`, "ok");
  } catch (error) {
    await loadModels();
    renderModelManagementList();
    setModelManagementMessage(apiErrorText(error), "error");
  }
}

function handleModelManagementAction(event) {
  closeModelContextMenu();
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  const modelId = item.dataset.modelId || "";
  if (!modelId) return;
  setSelectedManagementModel(modelId);
  setModelManagementMessage("右键模型节点可导出、复制、修改或删除。", "ok");
}

function handleModelManagementKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  closeModelContextMenu();
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  const modelId = item.dataset.modelId || "";
  setSelectedManagementModel(modelId);
  setModelManagementMessage("右键模型节点可导出、复制、修改或删除。", "ok");
}

function closeModelContextMenu() {
  const menu = $("modelContextMenu");
  if (!menu) return;
  menu.hidden = true;
}

function positionModelContextMenu(menu, x, y) {
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    menu.style.left = `${Math.max(8, Math.min(x, maxLeft))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, maxTop))}px`;
  });
}

function openModelContextMenu(event) {
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  const modelId = item.dataset.modelId || "";
  if (!modelId) return;
  setSelectedManagementModel(modelId);
  const menu = $("modelContextMenu");
  if (!menu) return;
  updateModelContextMenuActions();
  menu.hidden = false;
  positionModelContextMenu(menu, event.clientX, event.clientY);
}

function handleModelContextMenuAction(event) {
  const button = event.target instanceof Element ? event.target.closest("[data-model-context-action]") : null;
  if (!button || button.disabled) return;
  const action = button.dataset.modelContextAction || "";
  closeModelContextMenu();
  switch (action) {
    case "export":
      exportDefinitionsArchive(selectedManagementModelId(), button);
      break;
    case "clone":
      openCloneModelDialog(selectedManagementModelId());
      break;
    case "update":
      openUpdateModelDialog(selectedManagementModelId());
      break;
    case "delete":
      deleteManagedModel(selectedManagementModelId());
      break;
    default:
      break;
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
  if (!$("modelManagementDialog")?.hidden) renderModelManagementList();
}

function setActiveModel(modelId, shouldRefresh = true) {
  const nextId = modelId || state.models[0]?.id || "";
  if (state.activeModelId === nextId && shouldRefresh) {
    refresh();
    return;
  }
  cancelCurveRequests();
  state.activeModelId = nextId;
  state.selectedManagementModelId = nextId;
  localStorage.setItem("polarSimulatorModelId", nextId);
  state.snapshot = null;
  state.settingsLoaded = false;
  state.deviceFaults = [];
  state.measurementFaults = [];
  state.modes = [];
  state.runtimeLogs = [];
  state.runtimeLogTypeFilter = "all";
  state.runtimeLogSeq = 0;
  state.runtimeLogBackendSeq = 0;
  state.runtimeLogTotal = 0;
  state.lastRuntimeLogKey = "";
  state.measurementDeltaSeq = 0;
  state.systemParameters = { clock_speed: 1, compute_interval_seconds: 1, storage_initial_soc: 0.5 };
  state.systemParametersDirty = false;
  state.systemParametersSaving = false;
  state.runtimeTraceHistory = [];
  state.lastRuntimeTraceKey = "";
  state.measurementTraceHistory = [];
  state.lastMeasurementTraceKey = "";
  state.traceRunId = null;
  state.traceStepCount = null;
  state.selectedMeasurementKey = "";
  state.modeFilter = { dev_type: "all", dev_name: "" };
  state.faultDeviceFilter = { dev_type: "all", dev_name: "" };
  state.faultMeasurementFilter = { dev_type: "all", dev_name: "", key: "" };
  state.modelDeviceFilter = { dev_type: "all", dev_name: "" };
  state.activeModelParamTab = "";
  state.runtimeDeviceFilter = { dev_type: "all", dev_name: "" };
  state.activeRuntimeCommandTab = "remote_control";
  state.measurementCompareFilter = { dev_type: "all", dev_name: "" };
  state.deviceTreeSelectionAnchors = {};
  state.activeCurveKey = "wind_speed_mps";
  state.selectedCurveKeys = ["wind_speed_mps"];
  state.curveEditKey = "";
  state.curveSummary = null;
  state.curveSummaryLoadedModelId = "";
  state.curveSummaryRequest = null;
  state.curveSummaryRequestModelId = "";
  state.curveSummaryAbortController = null;
  state.curveSeriesRequestKey = "";
  state.curveSeriesRequest = null;
  state.curveSeriesAbortController = null;
  state.curveEditorLoadRequest = null;
  state.curveEditorLoadRequestKey = "";
  state.curveLoadError = "";
  state.curveDataRevision += 1;
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
  state.curveDirtyKeys = new Set();
  state.curveSeries = {};
  state.curveSeriesByMode = {};
  state.curvesLoadedModelId = "";
  renderModelSelector();
  if (currentPageName() === "curves") renderCurveEditorLoading("正在加载曲线摘要...");
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
  } finally {
    state.modelsLoaded = true;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

function sanitizeDiagramSvg(svgText) {
  const raw = String(svgText || "").trim();
  if (!raw) return "";
  const documentParser = new DOMParser();
  const parsed = documentParser.parseFromString(raw, "image/svg+xml");
  if (parsed.querySelector("parsererror")) return "";
  const svg = parsed.querySelector("svg");
  if (!svg) return "";
  svg.querySelectorAll("script, foreignObject, iframe, object, embed").forEach((node) => node.remove());
  svg.querySelectorAll("*").forEach((node) => {
    [...node.attributes].forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      const value = String(attribute.value || "").trim().toLowerCase();
      if (name.startsWith("on") || value.startsWith("javascript:")) node.removeAttribute(attribute.name);
      if ((name === "href" || name.endsWith(":href")) && value.startsWith("javascript:")) node.removeAttribute(attribute.name);
    });
  });
  normalizeDiagramSvgBackground(svg);
  svg.classList.add("model-diagram-svg");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return svg.outerHTML;
}

const DIAGRAM_TREND_WINDOWS = Object.freeze({ hour: 60, day: 24 * 60 });
const DIAGRAM_DISPLAY_PREFERENCES_KEY = "simulator.svgDisplayPreferences.v1";
const DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS = Object.freeze({
  measurements: true,
  labels: true,
  flowArrows: true,
});
const DIAGRAM_MAX_ZOOM = 8;
const DIAGRAM_PAN_THRESHOLD_PX = 5;
const DIAGRAM_TOOLTIP_HIDE_DELAY_MS = 500;

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

function loadDiagramDisplayPreferences(storage = typeof localStorage === "undefined" ? null : localStorage) {
  try {
    const raw = storage?.getItem?.(DIAGRAM_DISPLAY_PREFERENCES_KEY);
    return normalizeDiagramDisplayPreferences(raw ? JSON.parse(raw) : null);
  } catch (_error) {
    return normalizeDiagramDisplayPreferences(null);
  }
}

function saveDiagramDisplayPreferences(preferences, storage = typeof localStorage === "undefined" ? null : localStorage) {
  const normalized = normalizeDiagramDisplayPreferences(preferences);
  try {
    storage?.setItem?.(DIAGRAM_DISPLAY_PREFERENCES_KEY, JSON.stringify(normalized));
  } catch (_error) {
    // The current page still uses the normalized in-memory preference when storage is unavailable.
  }
  return normalized;
}

let diagramDisplayPreferences = loadDiagramDisplayPreferences();

function diagramTooltipPointerMoveAction(currentHover, nextHover, tooltipHidden = false) {
  if (currentHover && !tooltipHidden && nextHover?.kind !== currentHover.kind) return "schedule-hide";
  if (!nextHover) return "hide";
  if (tooltipHidden || nextHover.key !== currentHover?.key) return "refresh";
  return "hold";
}

function diagramTooltipNeedsPosition(hover, positionedKey = "") {
  if (!hover) return false;
  const hoverKey = String(hover.key || "");
  return !hoverKey || hoverKey !== String(positionedKey || "");
}

function diagramSvgDoubleClickAction(targetKind = "", insideCanvas = false) {
  if (!insideCanvas) return "ignore";
  return String(targetKind || "").trim() ? "ignore" : "fit";
}

function diagramInteractionEventTarget(container, viewport, event) {
  const svg = viewport?.svg;
  const directTarget = event?.target;
  if (!container || !svg || !(directTarget instanceof Element)) return null;
  if (directTarget !== container && !container.contains(directTarget)) return null;
  if (directTarget.closest("svg") === svg) return directTarget;
  const clientX = Number(event?.clientX);
  const clientY = Number(event?.clientY);
  const pointTarget = Number.isFinite(clientX)
    && Number.isFinite(clientY)
    && typeof document !== "undefined"
    && typeof document.elementFromPoint === "function"
    ? document.elementFromPoint(clientX, clientY)
    : null;
  if (
    pointTarget instanceof Element
    && container.contains(pointTarget)
    && pointTarget.closest("svg") === svg
  ) {
    return pointTarget;
  }
  return svg;
}

function diagramViewBoxValue(value) {
  const values = String(value || "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (values.length !== 4 || values.some((item) => !Number.isFinite(item))) return null;
  const [x, y, width, height] = values;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function normalizeDiagramSvgBackground(svg) {
  const viewBox = diagramViewBoxValue(svg?.getAttribute("viewBox"));
  if (!viewBox) return 0;
  let normalized = 0;
  svg.querySelectorAll("rect").forEach((rect) => {
    const width = String(rect.getAttribute("width") || "").trim();
    const height = String(rect.getAttribute("height") || "").trim();
    if (width !== "100%" || height !== "100%") return;
    if (rect.closest("defs, symbol, marker, pattern, clipPath, mask")) return;
    rect.setAttribute("x", String(viewBox.x));
    rect.setAttribute("y", String(viewBox.y));
    rect.setAttribute("width", String(viewBox.width));
    rect.setAttribute("height", String(viewBox.height));
    rect.setAttribute("pointer-events", "none");
    rect.classList.add("diagram-svg-background");
    normalized += 1;
  });
  return normalized;
}

function diagramTrendWindowMinutes(period = "hour") {
  return DIAGRAM_TREND_WINDOWS[period] || DIAGRAM_TREND_WINDOWS.hour;
}

function diagramTrendPeriodRange(period = "hour", endMinute = 0) {
  const windowMinutes = diagramTrendWindowMinutes(period);
  const latestMinute = Number.isFinite(Number(endMinute)) ? Number(endMinute) : 0;
  const startMinute = Math.floor(latestMinute / windowMinutes) * windowMinutes;
  return {
    startMinute,
    endMinute: startMinute + windowMinutes,
    latestMinute,
    windowMinutes,
  };
}

function diagramTrendPeriodLabels(period = "hour", range = {}) {
  if (period === "day") return { start: "00:00", end: "24:00" };
  const startMinute = Number(range.startMinute) || 0;
  const endMinute = Number(range.endMinute) || startMinute + DIAGRAM_TREND_WINDOWS.hour;
  const dayStart = Math.floor(startMinute / DIAGRAM_TREND_WINDOWS.day) * DIAGRAM_TREND_WINDOWS.day;
  const clockText = (minute) => {
    const offset = Math.round(Number(minute) - dayStart);
    if (offset === DIAGRAM_TREND_WINDOWS.day) return "24:00";
    const normalized = ((offset % DIAGRAM_TREND_WINDOWS.day) + DIAGRAM_TREND_WINDOWS.day) % DIAGRAM_TREND_WINDOWS.day;
    return `${String(Math.floor(normalized / 60)).padStart(2, "0")}:${String(normalized % 60).padStart(2, "0")}`;
  };
  return { start: clockText(startMinute), end: clockText(endMinute) };
}

function diagramTrendWindowPoints(points, period = "hour", endMinute = null) {
  const valid = (points || []).filter((point) => (
    Number.isFinite(Number(point?.minute)) && Number.isFinite(Number(point?.value))
  ));
  if (!valid.length) return [];
  const explicitEndMinute = endMinute === null || endMinute === undefined || endMinute === ""
    ? null
    : Number(endMinute);
  const latestMinute = Number.isFinite(explicitEndMinute)
    ? explicitEndMinute
    : Number(valid[valid.length - 1].minute);
  const range = diagramTrendPeriodRange(period, latestMinute);
  return valid.filter((point) => (
    Number(point.minute) >= range.startMinute
    && Number(point.minute) <= range.latestMinute
    && Number(point.minute) < range.endMinute
  ));
}

function diagramSampleTrendPoints(points, targetCount = 160) {
  const source = Array.isArray(points) ? points : [];
  const target = Math.max(4, Math.floor(Number(targetCount) || 160));
  if (source.length <= target) return [...source];
  const bucketCount = Math.max(1, Math.floor(target / 4));
  const bucketSize = source.length / bucketCount;
  const sampled = new Map();
  for (let bucket = 0; bucket < bucketCount; bucket += 1) {
    const start = Math.floor(bucket * bucketSize);
    const end = Math.min(source.length, Math.max(start + 1, Math.ceil((bucket + 1) * bucketSize)));
    let minIndex = start;
    let maxIndex = start;
    for (let index = start + 1; index < end; index += 1) {
      if (Number(source[index]?.value) < Number(source[minIndex]?.value)) minIndex = index;
      if (Number(source[index]?.value) > Number(source[maxIndex]?.value)) maxIndex = index;
    }
    [start, minIndex, maxIndex, end - 1].forEach((index) => sampled.set(index, source[index]));
  }
  sampled.set(0, source[0]);
  sampled.set(source.length - 1, source[source.length - 1]);
  return Array.from(sampled.entries())
    .sort((left, right) => left[0] - right[0])
    .map(([, point]) => point);
}

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
  return {
    minute: Number(point.minute),
    time: point.time || "--",
    value: Number(point.value),
    unit: String(unit || ""),
  };
}

function diagramZoomViewBox(current, original, focus, factor) {
  const boxes = [current, original];
  if (boxes.some((box) => !box || [box.x, box.y, box.width, box.height].some((value) => !Number.isFinite(Number(value))))) {
    return current;
  }
  const originalWidth = Number(original.width);
  const originalHeight = Number(original.height);
  const currentWidth = Number(current.width);
  const currentHeight = Number(current.height);
  if (originalWidth <= 0 || originalHeight <= 0 || currentWidth <= 0 || currentHeight <= 0) return current;
  const zoomFactor = Number(factor);
  if (!Number.isFinite(zoomFactor) || zoomFactor <= 0) return current;
  const nextWidth = Math.max(originalWidth / DIAGRAM_MAX_ZOOM, Math.min(originalWidth, currentWidth * zoomFactor));
  const scale = nextWidth / currentWidth;
  const nextHeight = Math.max(originalHeight / DIAGRAM_MAX_ZOOM, Math.min(originalHeight, currentHeight * scale));
  const focusX = Number.isFinite(Number(focus?.x)) ? Number(focus.x) : Number(current.x) + currentWidth / 2;
  const focusY = Number.isFinite(Number(focus?.y)) ? Number(focus.y) : Number(current.y) + currentHeight / 2;
  const rawX = focusX - (focusX - Number(current.x)) * (nextWidth / currentWidth);
  const rawY = focusY - (focusY - Number(current.y)) * (nextHeight / currentHeight);
  const minX = Number(original.x);
  const minY = Number(original.y);
  const maxX = minX + originalWidth - nextWidth;
  const maxY = minY + originalHeight - nextHeight;
  return {
    x: Math.max(minX, Math.min(maxX, rawX)),
    y: Math.max(minY, Math.min(maxY, rawY)),
    width: nextWidth,
    height: nextHeight,
  };
}

function diagramPanViewBox(current, original, delta) {
  const boxes = [current, original];
  if (boxes.some((box) => !box || [box.x, box.y, box.width, box.height].some((value) => !Number.isFinite(Number(value))))) {
    return current;
  }
  const originalWidth = Number(original.width);
  const originalHeight = Number(original.height);
  const currentWidth = Number(current.width);
  const currentHeight = Number(current.height);
  if (originalWidth <= 0 || originalHeight <= 0 || currentWidth <= 0 || currentHeight <= 0) return current;
  const deltaX = Number.isFinite(Number(delta?.x)) ? Number(delta.x) : 0;
  const deltaY = Number.isFinite(Number(delta?.y)) ? Number(delta.y) : 0;
  const minX = Number(original.x);
  const minY = Number(original.y);
  const maxX = minX + originalWidth - currentWidth;
  const maxY = minY + originalHeight - currentHeight;
  return {
    x: Math.max(minX, Math.min(maxX, Number(current.x) - deltaX)),
    y: Math.max(minY, Math.min(maxY, Number(current.y) - deltaY)),
    width: currentWidth,
    height: currentHeight,
  };
}

function fitDiagramViewport(viewport) {
  const original = viewport?.original;
  const svg = viewport?.svg;
  if (!original || !svg || typeof svg.setAttribute !== "function") return false;
  const values = [original.x, original.y, original.width, original.height].map(Number);
  if (values.some((value) => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) return false;
  const [x, y, width, height] = values;
  viewport.current = { x, y, width, height };
  svg.setAttribute("viewBox", `${x} ${y} ${width} ${height}`);
  return true;
}

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

function diagramNumberText(value) {
  const number = Number(value);
  if (Number.isFinite(number)) return number.toFixed(2);
  const text = String(value ?? "").trim();
  return text || "--";
}

function diagramRowText(row) {
  if (!row) return "--";
  const unit = String(row.unit || "").trim();
  return `${diagramNumberText(row.value)}${unit ? ` ${unit}` : ""}`;
}

function addDiagramMeasurementAliases(map, row) {
  if (!row) return;
  const aliases = [
    row.name,
    measurementKey(row),
    `${row.dev_type || ""}.${row.dev_name || ""}.${row.meas_type || ""}`,
  ].map((item) => String(item || "").trim()).filter(Boolean);
  aliases.forEach((alias) => map.set(alias, row));
}

function normalizeDiagramMeasurementToken(value) {
  return String(value || "").trim().toUpperCase();
}

function diagramMetricMeasurementTypes(devType, metricType) {
  const metricName = String(metricType || "").trim().toLowerCase();
  const metricEntry = Object.entries(DIAGRAM_METRIC_MEASUREMENT_TYPES)
    .find(([key]) => key.toLowerCase() === metricName)?.[1] || {};
  const specific = metricEntry[normalizeDiagramMeasurementToken(devType)] || [];
  return [...new Set([...specific, ...(metricEntry["*"] || [])])];
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

function diagramMetricBindingValue(binding, maps) {
  const candidates = diagramMetricMeasurementTypes(binding?.devType, binding?.metricType);
  for (const measType of candidates) {
    const key = diagramDeviceMeasurementKey(binding.devType, binding.devName, measType);
    if (maps.scadaByDevice?.has(key)) return maps.scadaByDevice.get(key);
  }
  for (const measType of candidates) {
    const key = diagramDeviceMeasurementKey(binding.devType, binding.devName, measType);
    if (maps.realByDevice?.has(key)) return maps.realByDevice.get(key);
  }
  return null;
}

function diagramDisplayRow(row, metricType = "") {
  if (!row) return row;
  if (
    String(metricType || "").trim().toLowerCase() === "level"
    && normalizeDiagramMeasurementToken(row.meas_type) === "SOC"
    && Number.isFinite(Number(row.value))
  ) {
    return { ...row, value: Number(row.value) * 100 };
  }
  return row;
}

function diagramTrendDisplayValue(value, row, metricType = "") {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const displayRow = diagramDisplayRow({ ...(row || {}), value: number }, metricType);
  return Number.isFinite(Number(displayRow?.value)) ? Number(displayRow.value) : null;
}

function diagramDeviceStateKey(devType, devName) {
  return `${normalizeDiagramMeasurementToken(devType)}\u0000${String(devName || "").trim()}`;
}

function diagramDeviceOperatingStateMaps(snapshot = {}) {
  const exact = new Map();
  const byName = new Map();
  (snapshot.device_states || snapshot.devices || []).forEach((item) => {
    const devType = String(item?.dev_type || "").trim();
    const devName = String(item?.dev_name || item?.name || "").trim();
    if (!devType || !devName) return;
    exact.set(diagramDeviceStateKey(devType, devName), item);
    if (!byName.has(devName)) {
      byName.set(devName, item);
      return;
    }
    const previous = byName.get(devName);
    if (previous && normalizeDiagramMeasurementToken(previous.dev_type) !== normalizeDiagramMeasurementToken(devType)) {
      byName.set(devName, null);
    }
  });
  return { exact, byName };
}

function diagramDeviceOperatingState(device, maps) {
  if (!device) return null;
  return maps.exact.get(diagramDeviceStateKey(device.devType, device.devName))
    || maps.byName.get(String(device.devName || "").trim())
    || null;
}

function diagramDeviceIsOffline(deviceState) {
  if (!deviceState) return false;
  const deadIsland = deviceState.dead_island === true
    || Number(deviceState.dead_island) === 1
    || String(deviceState.dead_island).trim().toLowerCase() === "true";
  return Number(deviceState.run_stat ?? deviceState.running ?? 1) === 0 || deadIsland;
}

function diagramSwitchState(value) {
  if (typeof value === "boolean") return value ? "closed" : "open";
  const text = String(value ?? "").trim();
  if (!text || text === "--") return "unknown";
  const number = Number(text);
  if (Number.isFinite(number)) return number > 0.5 ? "closed" : "open";
  const token = text.toLowerCase().replace(/\s+/g, "");
  if (["closed", "close", "on", "合", "合闸", "闭合", "投入", "true"].includes(token)) return "closed";
  if (["open", "off", "分", "分闸", "断开", "退出", "false"].includes(token)) return "open";
  return "unknown";
}

function diagramSwitchStateHref(href, switchState) {
  const value = String(href || "");
  if (!value || !["open", "closed"].includes(switchState)) return value;
  const stateValue = switchState === "closed" ? 1 : 0;
  return value.replace(/_state_[01](?=(?:_\d+)?(?:$|[?#]))/, `_state_${stateValue}`);
}

function diagramSwitchMeasurementRow(device, maps) {
  if (!device) return null;
  const key = diagramDeviceMeasurementKey(device.devType, device.devName, "STATUS");
  return maps.scadaByDevice?.get(key) || maps.realByDevice?.get(key) || null;
}

function setDiagramSwitchElementState(element, switchState) {
  element.setAttribute("data-diagram-switch-state", switchState);
  element.classList.toggle("is-diagram-switch-open", switchState === "open");
  element.classList.toggle("is-diagram-switch-closed", switchState === "closed");
}

function updateDiagramSwitchVisualStates(container, maps) {
  if (!container) return;
  const elementsByDevice = new Map();
  container.querySelectorAll("[dev-id], [dev]").forEach((element) => {
    [element.getAttribute("dev-id"), element.getAttribute("dev")]
      .map((value) => String(value || "").trim())
      .filter(Boolean)
      .forEach((devId) => {
        if (!elementsByDevice.has(devId)) elementsByDevice.set(devId, []);
        elementsByDevice.get(devId).push(element);
      });
  });
  const devices = diagramDeviceIndex(container);
  container.querySelectorAll("use[dev-id], use[id][name]").forEach((element) => {
    const devId = String(element.getAttribute("dev-id") || element.getAttribute("id") || "").trim();
    const device = devices.get(devId);
    if (!devId || !device) return;
    const currentHref = element.getAttribute("href") || element.getAttribute("xlink:href") || "";
    const supportsStateSymbols = /_state_[01](?=(?:_\d+)?(?:$|[?#]))/.test(currentHref)
      || element.hasAttribute("data-open-href")
      || element.hasAttribute("data-closed-href");
    if (!supportsStateSymbols) return;
    const switchState = diagramSwitchState(diagramSwitchMeasurementRow(device, maps)?.value);
    (elementsByDevice.get(devId) || [element]).forEach((related) => {
      setDiagramSwitchElementState(related, switchState);
    });
    if (switchState === "unknown") return;
    const explicitHref = element.getAttribute(switchState === "closed" ? "data-closed-href" : "data-open-href");
    const nextHref = explicitHref || diagramSwitchStateHref(currentHref, switchState);
    if (!nextHref || nextHref === currentHref) return;
    element.setAttribute("href", nextHref);
    if (element.hasAttribute("xlink:href")) element.setAttribute("xlink:href", nextHref);
  });
}

function addDiagramControlAliases(map, aliases, value, updated) {
  aliases.map((item) => String(item || "").trim()).filter(Boolean).forEach((alias) => {
    map.set(alias, { value, updated });
  });
}

function diagramControlMap(snapshot = state.snapshot || {}) {
  const map = new Map();
  activeCommandHistory(snapshot).forEach((entry) => {
    const normalized = entry.normalized || {};
    const payload = entry.payload || {};
    const updated = entry.receive_simu_time || entry.simu_time || entry.wall_time || "";
    (normalized.run_status || payload.run_status || []).forEach((item) => {
      const devType = item.dev_type || "";
      const devName = item.dev_name || "";
      addDiagramControlAliases(map, [
        item.name,
        `${devType}.${devName}.RUN_STAT`,
        `${devType}.${devName}.STATUS`,
      ], item.run_stat ?? item.status ?? item.value, updated);
    });
    (normalized.set_values || payload.set_values || payload.setpoints || []).forEach((item) => {
      const devType = item.dev_type || "";
      const devName = item.dev_name || "";
      const setType = item.set_type || "";
      addDiagramControlAliases(map, [
        item.name,
        `${devType}.${devName}.${setType}`,
      ], item.set_value ?? item.value, updated);
    });
  });
  return map;
}

function diagramBindingValue(name, maps, channel = "scada") {
  const key = String(name || "").trim();
  if (!key) return null;
  if (channel === "real") return maps.real.get(key) || null;
  if (channel === "control") return maps.controls.get(key) || null;
  return maps.scada.get(key) || maps.real.get(key) || null;
}

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

const diagramDeviceIndexCache = new WeakMap();
const diagramMetricBindingCache = new WeakMap();
const diagramInteractionCache = new WeakMap();
const diagramViewportCache = new WeakMap();

function compileDiagramDeviceIndex(container) {
  const devices = new Map();
  container.querySelectorAll("[dev-id][name], use[id][name]").forEach((element) => {
    const devId = element.getAttribute("dev-id") || element.getAttribute("id") || "";
    const devName = element.getAttribute("name") || "";
    if (!devId || !devName || devices.has(devId)) return;
    const layerType = element.closest("[device-type]")?.getAttribute("device-type") || "";
    devices.set(devId, {
      devId,
      devType: layerType || devId.split("-", 1)[0],
      devName,
    });
  });
  return devices;
}

function diagramDeviceIndex(container) {
  let devices = diagramDeviceIndexCache.get(container);
  if (!devices) {
    devices = compileDiagramDeviceIndex(container);
    diagramDeviceIndexCache.set(container, devices);
  }
  return devices;
}

function compileDiagramMetricBindings(container) {
  const devices = diagramDeviceIndex(container);
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

function diagramInteractionState(container) {
  let interaction = diagramInteractionCache.get(container);
  if (!interaction) {
    interaction = {
      initialized: false,
      selectedDevId: "",
      hover: null,
      snapshot: null,
      tooltip: null,
      tooltipPositionKey: "",
      trendPeriod: "hour",
      trendChart: null,
      pointer: { x: 0, y: 0 },
      hideTimer: null,
      drag: null,
      suppressClick: false,
      suppressClickTimer: null,
    };
    diagramInteractionCache.set(container, interaction);
  }
  return interaction;
}

function diagramDeviceRecord(container, devId) {
  const key = String(devId || "").trim();
  if (!key) return null;
  const indexed = diagramDeviceIndex(container).get(key);
  if (indexed) return indexed;
  return {
    devId: key,
    devType: key.includes("-") ? key.split("-", 1)[0] : "",
    devName: key,
  };
}

const DIAGRAM_DEVICE_ELEMENT_SELECTOR = "[dev-id], [dev], use[id][name]";

function diagramElementDeviceId(element) {
  if (!element || typeof element.getAttribute !== "function") return "";
  const explicit = element.getAttribute("dev-id") || element.getAttribute("dev");
  if (explicit) return String(explicit).trim();
  if (String(element.tagName || "").toLowerCase() !== "use" || !element.getAttribute("name")) return "";
  return String(element.getAttribute("id") || "").trim();
}

function diagramTargetDeviceId(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return "";
  const metricElement = target.closest("[mt]");
  if (metricElement && container.contains(metricElement)) {
    const owner = metricElement.closest("[dev]");
    if (owner && container.contains(owner)) return String(owner.getAttribute("dev") || "").trim();
  }
  const deviceElement = target.closest(DIAGRAM_DEVICE_ELEMENT_SELECTOR);
  if (!deviceElement || !container.contains(deviceElement)) return "";
  return diagramElementDeviceId(deviceElement);
}

function diagramHoverTarget(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return null;
  const metricElement = target.closest("[mt]");
  if (metricElement && container.contains(metricElement)) {
    const owner = metricElement.closest("[dev]");
    const devId = String(owner?.getAttribute("dev") || "").trim();
    const metricType = String(metricElement.getAttribute("mt") || "").trim();
    if (devId && metricType) {
      return {
        kind: "metric",
        key: `metric:${devId}:${metricType}`,
        element: metricElement,
        binding: { ...diagramDeviceRecord(container, devId), metricType },
      };
    }
  }
  const namedMetric = target.closest("[data-meas-name], [data-scada-name], [data-real-name]");
  if (namedMetric && container.contains(namedMetric)) {
    const channel = namedMetric.hasAttribute("data-real-name") ? "real" : "scada";
    const name = namedMetric.getAttribute("data-meas-name")
      || namedMetric.getAttribute("data-scada-name")
      || namedMetric.getAttribute("data-real-name")
      || "";
    if (name) {
      return {
        kind: "metric",
        key: `named-metric:${channel}:${name}`,
        element: namedMetric,
        channel,
        name,
        metricType: "",
      };
    }
  }
  const devId = diagramTargetDeviceId(container, target);
  if (!devId) return null;
  return {
    kind: "device",
    key: `device:${devId}`,
    element: target.closest(DIAGRAM_DEVICE_ELEMENT_SELECTOR),
    device: diagramDeviceRecord(container, devId),
  };
}

function setDiagramSelectedDevice(container, devId = "") {
  if (!container) return;
  const interaction = diagramInteractionState(container);
  const selectedDevId = String(devId || "").trim();
  interaction.selectedDevId = selectedDevId;
  container.querySelectorAll(".is-diagram-selected").forEach((element) => {
    element.classList.remove("is-diagram-selected");
  });
  if (!selectedDevId) return;
  container.querySelectorAll(DIAGRAM_DEVICE_ELEMENT_SELECTOR).forEach((element) => {
    if (diagramElementDeviceId(element) === selectedDevId) element.classList.add("is-diagram-selected");
  });
}

function updateDiagramDeviceVisualStates(container, snapshot = {}) {
  if (!container) return;
  const maps = diagramDeviceOperatingStateMaps(snapshot);
  container.querySelectorAll("[dev-id], [dev]").forEach((element) => {
    const devId = String(element.getAttribute("dev-id") || element.getAttribute("dev") || "").trim();
    const deviceState = diagramDeviceOperatingState(diagramDeviceRecord(container, devId), maps);
    const offline = diagramDeviceIsOffline(deviceState);
    element.classList.toggle("is-diagram-offline", offline);
    if (!deviceState) {
      element.removeAttribute("data-diagram-operating-state");
    } else if (Number(deviceState.run_stat ?? 1) === 0) {
      element.setAttribute("data-diagram-operating-state", "retired");
    } else if (diagramDeviceIsOffline(deviceState)) {
      element.setAttribute("data-diagram-operating-state", "dead-island");
    } else {
      element.setAttribute("data-diagram-operating-state", "running");
    }
  });
}

function diagramTooltipValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.map((item) => diagramTooltipValue(item)).join(", ");
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return String(value);
    }
  }
  return String(value);
}

function diagramMeasurementUnit(measType) {
  const type = normalizeDiagramMeasurementToken(measType);
  if (type === "SOC" || type === "LEVEL") return "%";
  if (type.startsWith("P")) return "kW";
  if (type.startsWith("Q")) return "kvar";
  if (type.startsWith("V")) return "V";
  if (type.startsWith("I")) return "A";
  if (type.includes("FREQ")) return "Hz";
  if (type.includes("TEMP")) return "℃";
  return "";
}

function diagramTooltipRows(rows = []) {
  const content = rows
    .filter((row) => row && row[0])
    .map(([label, value]) => `
      <div class="diagram-tooltip-row">
        <dt>${escapeHtml(label)}</dt>
        <dd>${escapeHtml(diagramTooltipValue(value))}</dd>
      </div>`)
    .join("");
  return content ? `<dl class="diagram-tooltip-grid">${content}</dl>` : "";
}

function diagramDeviceData(container, device, snapshot = state.snapshot || {}) {
  if (!device) return { definition: null, live: null, raw: {}, svgIdx: "" };
  const type = normalizeDiagramMeasurementToken(device.devType);
  const name = String(device.devName || "");
  const definition = definedModelDevices(snapshot).find((item) => (
    normalizeDiagramMeasurementToken(item.dev_type) === type
    && String(item.dev_name || "") === name
  )) || null;
  const live = (snapshot.devices || []).find((item) => (
    normalizeDiagramMeasurementToken(item.dev_type) === type
    && String(item.dev_name || "") === name
  )) || null;
  const svgElement = [...container.querySelectorAll("[dev-id]")]
    .find((element) => String(element.getAttribute("dev-id") || "") === device.devId);
  return {
    definition,
    live,
    raw: { ...(definition?.raw || {}), ...(live?.raw || {}) },
    svgIdx: svgElement?.getAttribute("idx") || "",
  };
}

function diagramDeviceMeasurements(device, snapshot = state.snapshot || {}) {
  if (!device) return [];
  const type = normalizeDiagramMeasurementToken(device.devType);
  const name = String(device.devName || "");
  const matches = (row) => (
    normalizeDiagramMeasurementToken(row?.dev_type) === type
    && String(row?.dev_name || "") === name
    && Number(row?.valid ?? 1) === 1
  );
  const rows = new Map();
  (snapshot.measurements?.scada || []).filter(matches).forEach((row) => rows.set(measurementKey(row), row));
  (snapshot.measurements?.real || []).filter(matches).forEach((row) => {
    const key = measurementKey(row);
    if (!rows.has(key)) rows.set(key, row);
  });
  return [...rows.values()].sort((left, right) => (
    String(left.meas_type || left.name || "").localeCompare(String(right.meas_type || right.name || ""), "zh-Hans-CN")
  ));
}

function renderDiagramDeviceTooltip(container, hover, snapshot) {
  const device = hover?.device || null;
  if (!device) return "";
  const { definition, live, raw, svgIdx } = diagramDeviceData(container, device, snapshot);
  const idx = live?.raw?.idx ?? definition?.idx ?? raw.idx ?? svgIdx ?? "--";
  const identityRows = [
    ["设备类型", device.devType || "--"],
    ["设备标识", device.devId || "--"],
    ["idx", idx],
  ];
  const statusRows = [
    ["运行状态", live?.run_stat ?? raw.run_stat],
    ["开关状态", live?.status ?? raw.status],
    ["控制模式", live?.mode ?? raw.control_type ?? raw.mode],
  ];
  const setRows = Object.entries(live?.set_values || {})
    .map(([key, value]) => [key, value]);
  const duplicateKeys = new Set([
    "idx", "name", "dev_name", "dev_type", "run_stat", "status", "mode", "control_type",
    ...Object.keys(live?.set_values || {}),
  ]);
  const rawRows = Object.entries(raw)
    .filter(([key]) => !duplicateKeys.has(key))
    .map(([key, value]) => [key, value]);
  const measurementRows = diagramDeviceMeasurements(device, snapshot).map((row) => {
    const metricType = normalizeDiagramMeasurementToken(row.meas_type) === "SOC" ? "level" : "";
    const value = diagramTrendDisplayValue(row.value, row, metricType);
    const unit = diagramMeasurementUnit(row.meas_type);
    return [row.meas_type || row.name || "量测", value === null ? "--" : `${diagramNumberText(value)}${unit ? ` ${unit}` : ""}`];
  });
  return `
    <div class="diagram-tooltip-head">
      <strong>${escapeHtml(device.devName || device.devId || "设备")}</strong>
      <span>设备参数</span>
    </div>
    <div class="diagram-tooltip-body">
      ${diagramTooltipRows(identityRows)}
      ${statusRows.some((row) => row[1] !== undefined && row[1] !== null && row[1] !== "") ? `<h4>运行信息</h4>${diagramTooltipRows(statusRows)}` : ""}
      ${setRows.length ? `<h4>当前设定值</h4>${diagramTooltipRows(setRows)}` : ""}
      ${rawRows.length ? `<h4>Model.e 参数</h4>${diagramTooltipRows(rawRows)}` : ""}
      ${measurementRows.length ? `<h4>实时量测</h4>${diagramTooltipRows(measurementRows)}` : ""}
    </div>`;
}

function diagramMetricCurrentRow(container, hover, snapshot) {
  const maps = diagramMeasurementMaps(snapshot);
  if (hover?.binding) return diagramMetricBindingValue(hover.binding, maps);
  if (hover?.name) return diagramBindingValue(hover.name, maps, hover.channel || "scada");
  return null;
}

function diagramTrendHistoryPoints(row, metricType = "") {
  if (!row) return [];
  const key = measurementKey(row);
  return (state.measurementTraceHistory || []).map((point) => {
    let measurement = point.measurements?.[key];
    if (!measurement) {
      measurement = Object.values(point.measurements || {}).find((item) => (
        normalizeDiagramMeasurementToken(item?.dev_type) === normalizeDiagramMeasurementToken(row.dev_type)
        && String(item?.dev_name || "") === String(row.dev_name || "")
        && normalizeDiagramMeasurementToken(item?.meas_type) === normalizeDiagramMeasurementToken(row.meas_type)
      ));
    }
    if (!measurement) return null;
    const candidates = [measurement.scada, measurement.real, measurement.value];
    const rawValue = candidates.find((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
    const value = diagramTrendDisplayValue(rawValue, row, metricType);
    if (value === null) return null;
    return {
      minute: Number(point.minute),
      time: point.sim_time || point.time || "--",
      value,
    };
  }).filter((point) => point && Number.isFinite(point.minute));
}

function diagramMetricLabel(metricType, row) {
  const labels = {
    activepower: "有功功率",
    reactivepower: "无功功率",
    voltage: "电压",
    current: "电流",
    status: "状态",
    level: "SOC",
    frequency: "频率",
    flow: "流量",
    pressure: "压力",
    temperature: "温度",
  };
  return labels[String(metricType || "").trim().toLowerCase()]
    || row?.meas_type
    || row?.name
    || "动态量测";
}

function diagramTrendChartHtml(points, period, tooltipWidth = 360, currentMinute = null, unit = "", interaction = null) {
  if (!points.length) {
    if (interaction) interaction.trendChart = null;
    return '<div class="diagram-trend-empty">当前分页暂无历史曲线</div>';
  }
  const targetCount = Math.max(32, Math.floor(Math.max(tooltipWidth, 320) * 0.75));
  const sampled = diagramSampleTrendPoints(points, targetCount);
  const values = sampled.map((point) => Number(point.value));
  const axis = diagramTrendAxisScale(values, 4);
  const width = 336;
  const height = 148;
  const plot = { left: 52, right: 10, top: 20, bottom: 10 };
  const range = diagramTrendPeriodRange(
    period,
    currentMinute !== null && currentMinute !== undefined && currentMinute !== "" && Number.isFinite(Number(currentMinute))
      ? Number(currentMinute)
      : Number(points[points.length - 1].minute),
  );
  const labels = diagramTrendPeriodLabels(period, range);
  const minuteSpan = Math.max(1, range.endMinute - range.startMinute);
  const valueSpan = Math.max(1e-9, axis.max - axis.min);
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const renderedPoints = sampled.map((point) => {
    const x = plot.left + ((Number(point.minute) - range.startMinute) / minuteSpan) * (width - plot.left - plot.right);
    const y = plot.top + ((axis.max - Number(point.value)) / valueSpan) * plotHeight;
    return { ...point, x, y };
  });
  if (interaction) {
    interaction.trendChart = {
      width,
      height,
      plot,
      range,
      points: renderedPoints,
      unit: String(unit || ""),
    };
  }
  const polyline = renderedPoints.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const axisTicks = axis.ticks.map((value) => {
    const y = plot.top + ((axis.max - Number(value)) / valueSpan) * plotHeight;
    return `
      <g class="diagram-trend-y-tick">
        <line x1="${plot.left}" y1="${y.toFixed(2)}" x2="${width - plot.right}" y2="${y.toFixed(2)}" class="diagram-trend-grid-line"></line>
        <text x="${plot.left - 7}" y="${(y + 3.5).toFixed(2)}">${escapeHtml(diagramNumberText(value))}</text>
      </g>`;
  }).join("");
  const last = points[points.length - 1];
  return `
    <svg class="diagram-trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${period === "day" ? "日曲线" : "小时曲线"}">
      <text x="${plot.left}" y="12" class="diagram-trend-axis-unit">${escapeHtml(unit)}</text>
      ${axisTicks}
      <line x1="${plot.left}" y1="${plot.top}" x2="${plot.left}" y2="${height - plot.bottom}" class="diagram-trend-y-axis"></line>
      <polyline class="diagram-trend-series" points="${polyline}" fill="none" vector-effect="non-scaling-stroke"></polyline>
      <line x1="0" y1="${plot.top}" x2="0" y2="${height - plot.bottom}" class="diagram-trend-cursor diagram-trend-cursor-line" data-diagram-trend-cursor data-diagram-trend-cursor-line visibility="hidden"></line>
      <circle cx="0" cy="0" r="3.5" class="diagram-trend-cursor diagram-trend-cursor-point" data-diagram-trend-cursor data-diagram-trend-cursor-point visibility="hidden"></circle>
      <g class="diagram-trend-cursor diagram-trend-cursor-label" data-diagram-trend-cursor data-diagram-trend-cursor-label visibility="hidden">
        <rect width="112" height="34" rx="4" ry="4"></rect>
        <text x="7" y="13" data-diagram-trend-cursor-time>--</text>
        <text x="7" y="27" data-diagram-trend-cursor-value>--</text>
      </g>
    </svg>
    <div class="diagram-trend-range"><span>${escapeHtml(labels.start)}</span><span>${escapeHtml(labels.end)}</span></div>
    <div class="diagram-trend-stats">
      <span>最小 <strong>${diagramNumberText(Math.min(...points.map((point) => point.value)))}</strong></span>
      <span>最大 <strong>${diagramNumberText(Math.max(...points.map((point) => point.value)))}</strong></span>
      <span>最新 <strong>${diagramNumberText(last.value)}</strong></span>
    </div>`;
}

function hideDiagramTrendCursor(interaction) {
  interaction?.tooltip?.querySelectorAll("[data-diagram-trend-cursor]").forEach((element) => {
    element.setAttribute("visibility", "hidden");
  });
}

function updateDiagramTrendCursor(interaction, chart, event) {
  const model = interaction?.trendChart;
  const rect = chart?.getBoundingClientRect?.();
  if (!model?.points?.length || !rect?.width || !Number.isFinite(Number(event?.clientX))) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  const viewX = ((Number(event.clientX) - rect.left) / rect.width) * model.width;
  const plotWidth = model.width - model.plot.left - model.plot.right;
  if (viewX < model.plot.left || viewX > model.width - model.plot.right || plotWidth <= 0) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  const targetMinute = model.range.startMinute
    + ((viewX - model.plot.left) / plotWidth) * (model.range.endMinute - model.range.startMinute);
  const point = diagramNearestTrendPoint(model.points, targetMinute);
  const line = chart.querySelector("[data-diagram-trend-cursor-line]");
  const marker = chart.querySelector("[data-diagram-trend-cursor-point]");
  const label = chart.querySelector("[data-diagram-trend-cursor-label]");
  const timeText = chart.querySelector("[data-diagram-trend-cursor-time]");
  const valueText = chart.querySelector("[data-diagram-trend-cursor-value]");
  if (!point || !line || !marker || !label || !timeText || !valueText) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  line.setAttribute("x1", point.x.toFixed(2));
  line.setAttribute("x2", point.x.toFixed(2));
  marker.setAttribute("cx", point.x.toFixed(2));
  marker.setAttribute("cy", point.y.toFixed(2));
  const labelWidth = 112;
  const labelHeight = 34;
  const labelGap = 8;
  const maxLabelX = model.width - model.plot.right - labelWidth - 2;
  const labelX = Math.max(model.plot.left + 2, Math.min(point.x + labelGap, maxLabelX));
  const preferredY = point.y - labelHeight - labelGap;
  const fallbackY = point.y + labelGap;
  const labelY = Math.max(
    model.plot.top + 2,
    Math.min(preferredY >= model.plot.top ? preferredY : fallbackY, model.height - model.plot.bottom - labelHeight - 2),
  );
  label.setAttribute("transform", `translate(${labelX.toFixed(2)} ${labelY.toFixed(2)})`);
  timeText.textContent = point.time || "--";
  const value = diagramNumberText(point.value);
  valueText.textContent = model.unit ? `${value} ${model.unit}` : value;
  chart.querySelectorAll("[data-diagram-trend-cursor]").forEach((element) => {
    element.setAttribute("visibility", "visible");
  });
}

function renderDiagramMetricTooltip(container, hover, snapshot, interaction) {
  const row = diagramMetricCurrentRow(container, hover, snapshot);
  const metricType = hover?.binding?.metricType || hover?.metricType || "";
  const displayValue = diagramTrendDisplayValue(row?.value, row, metricType);
  const unit = row?.unit || diagramMeasurementUnit(row?.meas_type || metricType);
  const period = interaction.trendPeriod === "day" ? "day" : "hour";
  const history = diagramTrendHistoryPoints(row, metricType);
  const endMinute = Number(snapshot?.clock?.absolute_minute ?? snapshot?.clock?.minute);
  const windowPoints = diagramTrendWindowPoints(
    history,
    period,
    Number.isFinite(endMinute) ? endMinute : null,
  );
  const deviceName = hover?.binding?.devName || row?.dev_name || row?.name || "动态量测";
  const metricLabel = diagramMetricLabel(metricType, row);
  const validText = row ? (Number(row.valid ?? 1) === 1 ? "有效" : "无效") : "缺失";
  return `
    <div class="diagram-tooltip-head">
      <strong>${escapeHtml(deviceName)}</strong>
      <span>${escapeHtml(metricLabel)}</span>
    </div>
    <div class="diagram-metric-current">
      <strong>${displayValue === null ? "--" : escapeHtml(diagramNumberText(displayValue))}</strong>
      <span>${escapeHtml(unit)}</span>
      <small>${escapeHtml(validText)}</small>
    </div>
    <div class="diagram-trend-tabs" role="tablist" aria-label="量测趋势范围">
      <button type="button" data-diagram-trend-period="hour" class="${period === "hour" ? "is-active" : ""}" aria-selected="${period === "hour"}">小时曲线</button>
      <button type="button" data-diagram-trend-period="day" class="${period === "day" ? "is-active" : ""}" aria-selected="${period === "day"}">日曲线</button>
    </div>
    <div class="diagram-trend-content">
      ${diagramTrendChartHtml(windowPoints, period, interaction.tooltip?.clientWidth || 360, endMinute, unit, interaction)}
    </div>`;
}

function positionDiagramTooltip(interaction) {
  const tooltip = interaction?.tooltip;
  if (!tooltip || tooltip.hidden) return;
  if (!diagramTooltipNeedsPosition(interaction.hover, interaction.tooltipPositionKey)) return;
  const gap = 14;
  const padding = 10;
  const rect = tooltip.getBoundingClientRect();
  let left = interaction.pointer.x + gap;
  let top = interaction.pointer.y + gap;
  if (left + rect.width > window.innerWidth - padding) left = interaction.pointer.x - rect.width - gap;
  if (top + rect.height > window.innerHeight - padding) top = interaction.pointer.y - rect.height - gap;
  tooltip.style.left = `${Math.max(padding, Math.min(left, window.innerWidth - rect.width - padding))}px`;
  tooltip.style.top = `${Math.max(padding, Math.min(top, window.innerHeight - rect.height - padding))}px`;
  interaction.tooltipPositionKey = String(interaction.hover?.key || "");
}

function clearDiagramTooltipHide(interaction) {
  if (!interaction?.hideTimer) return;
  clearTimeout(interaction.hideTimer);
  interaction.hideTimer = null;
}

function hideDiagramTooltip(container) {
  if (!container) {
    document.querySelectorAll(".diagram-tooltip").forEach((tooltip) => {
      tooltip.hidden = true;
      tooltip.classList.remove("is-visible");
    });
    return;
  }
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  clearDiagramTooltipHide(interaction);
  interaction.hover = null;
  interaction.tooltipPositionKey = "";
  hideDiagramTrendCursor(interaction);
  interaction.trendChart = null;
  if (interaction.tooltip) {
    interaction.tooltip.hidden = true;
    interaction.tooltip.classList.remove("is-visible");
  }
}

function scheduleDiagramTooltipHide(container) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  clearDiagramTooltipHide(interaction);
  interaction.hideTimer = setTimeout(() => hideDiagramTooltip(container), DIAGRAM_TOOLTIP_HIDE_DELAY_MS);
}

function refreshDiagramTooltip(container, snapshot = state.snapshot || {}) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  interaction.snapshot = snapshot;
  if (!interaction.hover || !interaction.tooltip) return;
  hideDiagramTrendCursor(interaction);
  interaction.trendChart = null;
  const html = interaction.hover.kind === "metric"
    ? renderDiagramMetricTooltip(container, interaction.hover, snapshot, interaction)
    : renderDiagramDeviceTooltip(container, interaction.hover, snapshot);
  if (!html) {
    hideDiagramTooltip(container);
    return;
  }
  interaction.tooltip.dataset.kind = interaction.hover.kind;
  interaction.tooltip.innerHTML = html;
  interaction.tooltip.hidden = false;
  interaction.tooltip.classList.add("is-visible");
  positionDiagramTooltip(interaction);
}

function resetDiagramInteractions(container) {
  if (!container) return;
  const interaction = diagramInteractionCache.get(container);
  if (interaction) {
    clearDiagramTooltipHide(interaction);
    if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
    interaction.selectedDevId = "";
    interaction.hover = null;
    interaction.snapshot = null;
    interaction.tooltipPositionKey = "";
    hideDiagramTrendCursor(interaction);
    interaction.trendChart = null;
    interaction.drag = null;
    interaction.suppressClick = false;
    interaction.suppressClickTimer = null;
    if (interaction.tooltip) {
      interaction.tooltip.hidden = true;
      interaction.tooltip.classList.remove("is-visible");
    }
  }
  container.classList.remove("is-diagram-panning");
  container.querySelectorAll(".is-diagram-selected").forEach((element) => element.classList.remove("is-diagram-selected"));
  diagramDeviceIndexCache.delete(container);
  diagramMetricBindingCache.delete(container);
  diagramViewportCache.delete(container);
}

function diagramViewBox(svg) {
  const values = String(svg?.getAttribute("viewBox") || "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) return null;
  const [x, y, width, height] = values;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function diagramViewportState(container) {
  const svg = container?.querySelector("svg.model-diagram-svg");
  if (!svg) return null;
  const cached = diagramViewportCache.get(container);
  if (cached?.svg === svg) return cached;
  const original = diagramViewBox(svg);
  if (!original) return null;
  const viewport = { svg, original: { ...original }, current: { ...original } };
  diagramViewportCache.set(container, viewport);
  return viewport;
}

function diagramPointerSvgPoint(svg, event, inverseMatrix = null) {
  if (!svg || !event || typeof svg.createSVGPoint !== "function") return null;
  try {
    const inverse = inverseMatrix || svg.getScreenCTM?.()?.inverse?.();
    if (!inverse) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(inverse);
  } catch (_error) {
    return null;
  }
}

function beginDiagramPan(container, event) {
  if (!event || event.button !== 0 || event.isPrimary === false) return false;
  const viewport = diagramViewportState(container);
  const interaction = diagramInteractionState(container);
  if (!viewport || !(event.target instanceof Element) || event.target.closest("svg") !== viewport.svg) return false;
  let inverseMatrix;
  try {
    inverseMatrix = viewport.svg.getScreenCTM?.()?.inverse?.();
  } catch (_error) {
    inverseMatrix = null;
  }
  const startPoint = diagramPointerSvgPoint(viewport.svg, event, inverseMatrix);
  if (!startPoint || !inverseMatrix) return false;
  if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
  interaction.suppressClick = false;
  interaction.suppressClickTimer = null;
  interaction.drag = {
    pointerId: event.pointerId,
    svg: viewport.svg,
    inverseMatrix,
    startPoint: { x: startPoint.x, y: startPoint.y },
    startClient: { x: event.clientX, y: event.clientY },
    startViewBox: { ...viewport.current },
    moved: false,
  };
  try {
    container.setPointerCapture?.(event.pointerId);
  } catch (_error) {
    // Pointer capture is optional; normal pointer events still support panning inside the canvas.
  }
  return true;
}

function moveDiagramPan(container, event) {
  const interaction = diagramInteractionCache.get(container);
  const drag = interaction?.drag;
  if (!drag || event.pointerId !== drag.pointerId) return false;
  const clientDistance = Math.hypot(event.clientX - drag.startClient.x, event.clientY - drag.startClient.y);
  if (!drag.moved && clientDistance < DIAGRAM_PAN_THRESHOLD_PX) return false;
  const viewport = diagramViewportState(container);
  if (!viewport || viewport.svg !== drag.svg) return false;
  const point = diagramPointerSvgPoint(viewport.svg, event, drag.inverseMatrix);
  if (!point) return false;
  if (!drag.moved) {
    drag.moved = true;
    container.classList.add("is-diagram-panning");
    hideDiagramTooltip(container);
  }
  const next = diagramPanViewBox(drag.startViewBox, viewport.original, {
    x: point.x - drag.startPoint.x,
    y: point.y - drag.startPoint.y,
  });
  viewport.current = { ...next };
  viewport.svg.setAttribute("viewBox", `${next.x} ${next.y} ${next.width} ${next.height}`);
  event.preventDefault();
  return true;
}

function finishDiagramPan(container, event) {
  const interaction = diagramInteractionCache.get(container);
  const drag = interaction?.drag;
  if (!drag || event.pointerId !== drag.pointerId) return false;
  const moved = Boolean(drag.moved);
  interaction.drag = null;
  container.classList.remove("is-diagram-panning");
  try {
    if (container.hasPointerCapture?.(event.pointerId)) container.releasePointerCapture?.(event.pointerId);
  } catch (_error) {
    // The pointer may already have been released by the browser.
  }
  if (moved) {
    interaction.suppressClick = true;
    interaction.suppressClickTimer = setTimeout(() => {
      interaction.suppressClick = false;
      interaction.suppressClickTimer = null;
    }, 0);
    event.preventDefault();
  }
  return moved;
}

function zoomDiagramAtPointer(container, event) {
  const viewport = diagramViewportState(container);
  if (!viewport || !event || !Number.isFinite(Number(event.deltaY)) || Number(event.deltaY) === 0) return false;
  const { svg } = viewport;
  if (!(event.target instanceof Element) || event.target.closest("svg") !== svg) return false;
  const screenMatrix = svg.getScreenCTM?.();
  if (!screenMatrix || typeof screenMatrix.inverse !== "function" || typeof svg.createSVGPoint !== "function") return false;
  let focus;
  try {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    focus = point.matrixTransform(screenMatrix.inverse());
  } catch (_error) {
    return false;
  }
  const factor = Number(event.deltaY) < 0 ? 0.88 : 1.12;
  const next = diagramZoomViewBox(viewport.current, viewport.original, focus, factor);
  const changed = ["x", "y", "width", "height"].some((key) => Math.abs(Number(next[key]) - Number(viewport.current[key])) > 1e-7);
  if (!changed) return false;
  viewport.current = { ...next };
  svg.setAttribute("viewBox", `${next.x} ${next.y} ${next.width} ${next.height}`);
  event.preventDefault();
  return true;
}

function initDiagramInteractions(container) {
  if (!container) return;
  const interaction = diagramInteractionState(container);
  if (interaction.initialized) return;
  interaction.initialized = true;
  const tooltip = document.createElement("div");
  tooltip.className = "diagram-tooltip";
  tooltip.hidden = true;
  tooltip.setAttribute("role", "tooltip");
  document.body.appendChild(tooltip);
  interaction.tooltip = tooltip;

  container.addEventListener("pointerdown", (event) => {
    beginDiagramPan(container, event);
  });
  container.addEventListener("pointermove", (event) => {
    interaction.pointer = { x: event.clientX, y: event.clientY };
    if (moveDiagramPan(container, event)) return;
    const nextHover = diagramHoverTarget(container, event.target);
    const tooltipAction = diagramTooltipPointerMoveAction(
      interaction.hover,
      nextHover,
      Boolean(interaction.tooltip?.hidden),
    );
    if (!nextHover) {
      if (tooltipAction === "schedule-hide") scheduleDiagramTooltipHide(container);
      else hideDiagramTooltip(container);
      return;
    }
    clearDiagramTooltipHide(interaction);
    interaction.hover = nextHover;
    if (tooltipAction === "refresh") {
      refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
    } else if (tooltipAction === "position") {
      positionDiagramTooltip(interaction);
    }
  });
  container.addEventListener("pointerup", (event) => finishDiagramPan(container, event));
  container.addEventListener("pointercancel", (event) => finishDiagramPan(container, event));
  container.addEventListener("dblclick", (event) => {
    const viewport = diagramViewportState(container);
    const target = diagramInteractionEventTarget(container, viewport, event);
    const hover = target ? diagramHoverTarget(container, target) : null;
    const action = diagramSvgDoubleClickAction(hover?.kind || "", Boolean(target));
    if (action !== "fit") return;
    if (!fitDiagramViewport(viewport)) return;
    hideDiagramTooltip(container);
    event.preventDefault();
    event.stopPropagation();
  });
  container.addEventListener("pointerleave", () => {
    if (!interaction.drag) scheduleDiagramTooltipHide(container);
  });
  container.addEventListener("click", (event) => {
    if (interaction.suppressClick) {
      if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
      interaction.suppressClick = false;
      interaction.suppressClickTimer = null;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const viewport = diagramViewportState(container);
    const target = diagramInteractionEventTarget(container, viewport, event);
    const devId = target ? diagramTargetDeviceId(container, target) : "";
    setDiagramSelectedDevice(container, devId);
  });
  container.addEventListener("wheel", (event) => {
    zoomDiagramAtPointer(container, event);
  }, { passive: false });
  tooltip.addEventListener("pointerenter", () => clearDiagramTooltipHide(interaction));
  tooltip.addEventListener("pointermove", (event) => {
    const chart = event.target instanceof Element ? event.target.closest(".diagram-trend-chart") : null;
    if (!chart || !tooltip.contains(chart)) {
      hideDiagramTrendCursor(interaction);
      return;
    }
    updateDiagramTrendCursor(interaction, chart, event);
  });
  tooltip.addEventListener("pointerout", (event) => {
    const chart = event.target instanceof Element ? event.target.closest(".diagram-trend-chart") : null;
    if (!chart) return;
    if (event.relatedTarget instanceof Element && chart.contains(event.relatedTarget)) return;
    hideDiagramTrendCursor(interaction);
  });
  tooltip.addEventListener("pointerleave", () => {
    hideDiagramTrendCursor(interaction);
    scheduleDiagramTooltipHide(container);
  });
  tooltip.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-diagram-trend-period]") : null;
    if (!button) return;
    const period = button.getAttribute("data-diagram-trend-period") === "day" ? "day" : "hour";
    if (period === interaction.trendPeriod) return;
    interaction.trendPeriod = period;
    refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
  });
}

function updateDiagramRealtimeBindings(container = $("modelDiagramCanvas"), snapshot = state.snapshot || {}) {
  if (!container) return;
  updateDiagramDeviceVisualStates(container, snapshot);
  const measurementMaps = diagramMeasurementMaps(snapshot);
  updateDiagramSwitchVisualStates(container, measurementMaps);
  const maps = { ...measurementMaps, controls: diagramControlMap(snapshot) };
  container.querySelectorAll("[data-meas-name], [data-scada-name]").forEach((element) => {
    const name = element.getAttribute("data-meas-name") || element.getAttribute("data-scada-name") || "";
    setDiagramElementValue(element, diagramBindingValue(name, maps, "scada"));
  });
  container.querySelectorAll("[data-real-name]").forEach((element) => {
    setDiagramElementValue(element, diagramBindingValue(element.getAttribute("data-real-name"), maps, "real"));
  });
  container.querySelectorAll("[data-control-name]").forEach((element) => {
    setDiagramElementValue(element, diagramBindingValue(element.getAttribute("data-control-name"), maps, "control"));
  });
  diagramMetricBindings(container).forEach((binding) => {
    setDiagramElementValue(
      binding.element,
      diagramMetricBindingValue(binding, maps),
      binding.metricType,
    );
  });
  refreshDiagramTooltip(container, snapshot);
}

function renderModelDiagramPage(snapshot = state.snapshot || {}) {
  const activeSnapshot = snapshot || {};
  const canvas = $("modelDiagramCanvas");
  const summary = $("modelDiagramSummary");
  if (!canvas) return;
  const diagram = activeSnapshot.diagram || {};
  const modelName = activeSnapshot.model?.name || activeSnapshot.model?.id || "当前模型";
  if (!diagram.svg) {
    resetDiagramInteractions(canvas);
    canvas.dataset.diagramKey = "";
    canvas.innerHTML = '<div class="empty-state">当前模型未配置接线图</div>';
    if (summary) summary.textContent = `${modelName} · 未配置`;
    return;
  }
  const key = `${activeSnapshot.model?.id || ""}|${diagram.updated_at || ""}|${diagram.size || ""}`;
  if (canvas.dataset.diagramKey !== key) {
    const sanitized = sanitizeDiagramSvg(diagram.svg);
    resetDiagramInteractions(canvas);
    canvas.dataset.diagramKey = key;
    canvas.innerHTML = sanitized
      ? `<div class="model-diagram-svg-wrap">${sanitized}</div>`
      : '<div class="empty-state">接线图 SVG 无法解析</div>';
  }
  initDiagramInteractions(canvas);
  if (summary) summary.textContent = `${modelName} · ${diagram.filename || "diagram.svg"}`;
  updateDiagramRealtimeBindings(canvas, activeSnapshot);
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
  if (!loads.length && Array.isArray(state.curveSummary?.loads)) {
    return state.curveSummary.loads
      .map((item) => ({ dev_type: item.dev_type || "ACLoad", dev_name: item.name || loadNameFromCurveKey(item.key) }))
      .filter((dev) => dev.dev_name);
  }
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

function curveFallbackValue(key) {
  if (String(key || "").startsWith("load:")) return 120;
  return curveMetaForKey(key).min;
}

function curveHasLoadedSeries(key) {
  return Array.isArray(state.curveSeries?.[key]) && state.curveSeries[key].length > 0;
}

function ensureCurveSeries(keys = selectedCurveKeys()) {
  let changed = false;
  const available = new Set(allCurveKeys());
  const targetKeys = Array.from(new Set(keys || []))
    .filter((key) => available.has(key) || ENV_CURVE_KEYS.includes(key) || String(key || "").startsWith("load:"));
  targetKeys.forEach((key) => {
    changed = normalizeCurveSeriesLength(key, curveFallbackValue(key)) || changed;
  });
  return changed;
}

function markCurveDirty(key) {
  if (!key) return;
  if (!(state.curveDirtyKeys instanceof Set)) state.curveDirtyKeys = new Set(state.curveDirtyKeys || []);
  state.curveDirtyKeys.add(key);
  state.curveDataRevision += 1;
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
}

function markCurveKeysDirty(keys = []) {
  keys.forEach((key) => markCurveDirty(key));
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
    ensureCurveSeries(selectedCurveKeys());
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
  state.curveSummary = curveSummaryFromCurves(curves);
  state.curveSummaryLoadedModelId = modelId || "loaded";
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
  state.curveDataRevision += 1;
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
}

function curveSummaryFromCurves(curves = {}) {
  const mode = CURVE_MODES[curves.mode] ? curves.mode : "day";
  const config = curveModeConfig(mode);
  const weather = Array.isArray(curves.weather) ? curves.weather : [];
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  return {
    mode,
    time_step_minutes: Number(curves.time_step_minutes || config.stepMinutes),
    point_count: Number(curves.point_count || weather.length || config.pointCount),
    environment: ENV_CURVE_KEYS.map((key) => ({ key, point_count: weather.length })),
    loads: Object.keys(loads).map((name) => ({
      key: loadCurveKey(name),
      name,
      point_count: Array.isArray(loads[name]) ? loads[name].length : 0,
    })),
  };
}

function curveSummaryHasCatalog(summary = state.curveSummary) {
  return Boolean(summary && Array.isArray(summary.environment) && Array.isArray(summary.loads));
}

function applyCurveSummary(summary, modelId = state.activeModelId) {
  if (!summary || typeof summary !== "object") return;
  const mode = CURVE_MODES[summary.mode] ? summary.mode : "day";
  state.curveSummary = summary;
  state.curveSummaryLoadedModelId = modelId || "loaded";
  state.curveMode = mode;
  state.curveLoadError = "";
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
  localStorage.setItem("polarSimulatorCurveMode", mode);
}

function isAbortRequestError(error) {
  return error?.name === "AbortError";
}

function cancelCurveRequests() {
  state.curveSummaryAbortController?.abort();
  state.curveSeriesAbortController?.abort();
  state.curveSummaryAbortController = null;
  state.curveSeriesAbortController = null;
  state.curveSummaryRequest = null;
  state.curveSummaryRequestModelId = "";
  state.curveSeriesRequest = null;
  state.curveSeriesRequestKey = "";
  state.curveEditorLoadRequest = null;
  state.curveEditorLoadRequestKey = "";
}

async function loadCurveSummary(modelId = state.activeModelId) {
  if (state.curveSummaryLoadedModelId === modelId && curveSummaryHasCatalog(state.curveSummary)) return state.curveSummary;
  if (state.curveSummaryRequest && state.curveSummaryRequestModelId === modelId) return state.curveSummaryRequest;
  state.curveSummaryAbortController?.abort();
  const controller = new AbortController();
  state.curveSummaryAbortController = controller;
  state.curveSummaryRequestModelId = modelId;
  state.curveSummaryRequest = api("/api/curves/summary", {
    signal: controller.signal,
    timeoutMs: CURVE_REQUEST_TIMEOUT_MS,
  })
    .then((summary) => {
      if (modelId === state.activeModelId) applyCurveSummary(summary, modelId);
      return summary;
    })
    .finally(() => {
      if (state.curveSummaryRequestModelId === modelId && state.curveSummaryAbortController === controller) {
        state.curveSummaryRequest = null;
        state.curveSummaryRequestModelId = "";
        state.curveSummaryAbortController = null;
      }
    });
  return state.curveSummaryRequest;
}

function applyCurveSeriesPayload(payload = {}, requestedKeys = []) {
  if (!payload || typeof payload !== "object") return;
  if (CURVE_MODES[payload.mode]) {
    state.curveMode = payload.mode;
    localStorage.setItem("polarSimulatorCurveMode", state.curveMode);
  }
  const series = payload.series && typeof payload.series === "object" ? payload.series : {};
  Object.entries(series).forEach(([key, values]) => {
    if (!Array.isArray(values)) return;
    state.curveSeries[key] = resampleSeries(values.map((value) => Number(value) || 0), curvePointCount(), curveFallbackValue(key));
  });
  requestedKeys.forEach((key) => {
    if (!curveHasLoadedSeries(key)) normalizeCurveSeriesLength(key, curveFallbackValue(key));
  });
  state.curveSeriesByMode[state.curveMode] = state.curveSeries;
  state.curveDataRevision += 1;
  state.curveLoadError = "";
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
}

async function ensureCurveSeriesLoaded(keys = selectedCurveKeys()) {
  const requested = Array.from(new Set(keys || [])).filter(Boolean);
  const keysToFetch = requested.filter((key) => !curveHasLoadedSeries(key));
  if (!keysToFetch.length) return true;
  const modelId = state.activeModelId;
  const requestKey = `${modelId}|${keysToFetch.slice().sort().join("|")}`;
  if (state.curveSeriesRequestKey === requestKey && state.curveSeriesRequest) return state.curveSeriesRequest;
  state.curveSeriesAbortController?.abort();
  const controller = new AbortController();
  state.curveSeriesRequestKey = requestKey;
  state.curveSeriesAbortController = controller;
  state.curveSeriesRequest = api(`/api/curves/series?keys=${encodeURIComponent(keysToFetch.join(","))}`, {
    signal: controller.signal,
    timeoutMs: CURVE_REQUEST_TIMEOUT_MS,
  })
    .then((payload) => {
      if (modelId === state.activeModelId) applyCurveSeriesPayload(payload, keysToFetch);
      return true;
    })
    .catch((error) => {
      if (!isAbortRequestError(error)) {
        state.curveLoadError = apiErrorText(error);
        const status = $("curveStatus");
        if (status) status.textContent = `曲线加载失败：${state.curveLoadError}`;
      }
      return false;
    })
    .finally(() => {
      if (state.curveSeriesRequestKey === requestKey && state.curveSeriesAbortController === controller) {
        state.curveSeriesRequest = null;
        state.curveSeriesRequestKey = "";
        state.curveSeriesAbortController = null;
      }
    });
  return state.curveSeriesRequest;
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

function drawCurveLoading(message = "正在加载曲线...") {
  const canvas = $("curveEditorChart");
  if (!canvas) return;
  resizeCurveCanvas();
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d8e1e5";
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  ctx.fillStyle = "#63717a";
  ctx.font = "14px Microsoft YaHei, Arial";
  ctx.textAlign = "center";
  ctx.fillText(message, width / 2, height / 2);
  ctx.textAlign = "left";
}

function renderCurveTableLoading(message = "正在加载曲线数据...") {
  const container = $("hourlyCurveTable");
  if (!container) return;
  container.removeAttribute("data-virtual-table");
  container.innerHTML = `
    <table class="curve-table">
      <tbody>
        <tr><td>${escapeHtml(message)}</td></tr>
      </tbody>
    </table>`;
}

function renderCurveTreeLoading(message = "正在加载曲线摘要...") {
  const container = $("curveTree");
  if (!container) return;
  const summary = $("curveTreeSummary");
  const activeInput = $("activeCurve");
  const activeLabel = $("activeCurveLabel");
  if (summary) summary.textContent = "加载中";
  if (activeInput) activeInput.value = "";
  if (activeLabel) activeLabel.textContent = "--";
  container.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderCurveEditorLoading(message) {
  if (curveSummaryHasCatalog(state.curveSummary)) renderCurveTree();
  else renderCurveTreeLoading(message);
  renderCurveModeControls();
  updateCurveModeLabels();
  const status = $("curveStatus");
  if (status) status.textContent = message;
  drawCurveLoading(message);
  renderCurveTableLoading(message);
}

function renderCurveEditorError(message = state.curveLoadError || "曲线加载失败") {
  const detail = String(message || "曲线加载失败");
  if (curveSummaryHasCatalog(state.curveSummary)) renderCurveTree();
  else renderCurveTreeLoading("曲线摘要加载失败");
  renderCurveModeControls();
  updateCurveModeLabels();
  const status = $("curveStatus");
  if (status) status.textContent = `曲线加载失败：${detail}`;
  drawCurveLoading("曲线加载失败，请重试");
  const container = $("hourlyCurveTable");
  if (container) {
    container.removeAttribute("data-virtual-table");
    container.innerHTML = `
      <div class="empty-state">
        <span>${escapeHtml(detail)}</span>
        <button type="button" class="primary" data-curve-retry>重试</button>
      </div>`;
  }
}

function startCurveEditorLoad(modelId = state.activeModelId) {
  const requestKey = String(modelId || "");
  if (state.curveEditorLoadRequest && state.curveEditorLoadRequestKey === requestKey) {
    return state.curveEditorLoadRequest;
  }
  state.curveLoadError = "";
  state.curveEditorLoadRequestKey = requestKey;
  let request;
  request = (async () => {
    await loadCurveSummary(modelId);
    if (modelId !== state.activeModelId || currentPageName() !== "curves") return false;
    const loaded = await ensureCurveSeriesLoaded(selectedCurveKeys());
    if (modelId !== state.activeModelId || currentPageName() !== "curves") return false;
    if (!loaded) throw new Error(state.curveLoadError || "曲线数据加载失败");
    state.lastCurveEditorRenderKey = "";
    renderCurveEditor(true);
    return true;
  })()
    .catch((error) => {
      if (isAbortRequestError(error) || modelId !== state.activeModelId || currentPageName() !== "curves") {
        return false;
      }
      state.curveLoadError = apiErrorText(error);
      renderCurveEditorError(state.curveLoadError);
      return false;
    })
    .finally(() => {
      if (state.curveEditorLoadRequest === request) {
        state.curveEditorLoadRequest = null;
        state.curveEditorLoadRequestKey = "";
      }
    });
  state.curveEditorLoadRequest = request;
  return request;
}

function retryCurveEditorLoad() {
  cancelCurveRequests();
  state.curveLoadError = "";
  state.lastCurveEditorRenderKey = "";
  renderCurveEditorLoading("正在重新加载曲线...");
  startCurveEditorLoad(state.activeModelId);
}

function curveEditorRenderKey() {
  return JSON.stringify({
    model: state.activeModelId,
    mode: state.curveMode,
    points: curvePointCount(),
    selected: selectedCurveKeys(),
    hidden: [...(state.hiddenCurveKeys || [])].sort(),
    revision: state.curveDataRevision,
  });
}

function renderCurveEditor(force = false) {
  const modelId = state.activeModelId;
  if (!state.modelsLoaded) {
    renderCurveEditorLoading("正在加载模型列表...");
    return;
  }
  const summaryMissing = state.curveSummaryLoadedModelId !== modelId || !curveSummaryHasCatalog(state.curveSummary);
  if (summaryMissing) {
    if (state.curveLoadError) {
      renderCurveEditorError(state.curveLoadError);
      return;
    }
    renderCurveEditorLoading("正在加载曲线摘要...");
    startCurveEditorLoad(modelId);
    return;
  }
  const selectedKeys = selectedCurveKeys();
  const missingKeys = selectedKeys.filter((key) => !curveHasLoadedSeries(key));
  if (missingKeys.length) {
    if (state.curveLoadError) {
      renderCurveEditorError(state.curveLoadError);
      return;
    }
    renderCurveEditorLoading(`正在加载 ${missingKeys.length} 条曲线...`);
    startCurveEditorLoad(modelId);
    return;
  }
  ensureCurveSeries(selectedKeys);
  const renderKey = curveEditorRenderKey();
  if (!force && renderKey === state.lastCurveEditorRenderKey) return;
  state.lastCurveEditorRenderKey = renderKey;
  renderCurveTree();
  renderCurveModeControls();
  updateCurveModeLabels();
  const status = $("curveStatus");
  if (status && /^正在加载|^曲线加载失败/.test(status.textContent || "")) status.textContent = "已加载";
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
  markCurveKeysDirty(Object.keys(state.curveSeries));
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
  return resizeCanvasToRenderedSize(canvas, 900, 260);
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
    const sampledPoints = sampleCurvePointsForCanvas(values, right - left, 1.4);
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = editKey && meta.key === editKey ? 3.5 : 2;
    ctx.beginPath();
    sampledPoints.forEach((point, index) => {
      const x = left + (point.index / Math.max(1, values.length - 1)) * (right - left);
      const y = valueToY(point.value, meta, canvas);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
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
  markCurveDirty(editKey);
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

function renderHourlyTable(force = false) {
  const container = $("hourlyCurveTable");
  if (!container) return;
  const metas = visibleCurveMetas();
  const pointCount = curvePointCount();
  const tableKey = `curveEditor:${state.activeModelId}:${state.curveMode}`;
  const signature = JSON.stringify({
    tableKey,
    pointCount,
    selected: metas.map((meta) => meta.key),
    revision: state.curveDataRevision,
  });
  if (!force && signature === state.lastCurveEditorTableKey) return;
  state.lastCurveEditorTableKey = signature;
  const rowIndexes = Array.from({ length: pointCount }, (_unused, index) => index);
  const virtualRows = virtualTableWindow(tableKey, rowIndexes);
  const columnCount = metas.length + 1;
  container.setAttribute("data-virtual-table", tableKey);
  container.innerHTML = `
    <table class="curve-table">
      <thead>
        <tr>
          <th>时刻</th>
          ${metas.map((meta) => `<th>${escapeHtml(meta.label)}<small>${escapeHtml(meta.unit)}</small></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
        ${virtualRows.rows.map((index) => `
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
        ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
      </tbody>
    </table>`;
  restoreVirtualTableScroll(container, tableKey);
}

function applyHourlyTableEdit(cell) {
  const index = Number(cell.dataset.index);
  const key = cell.dataset.key;
  const meta = curveMetaForKey(key);
  const rawValue = Number(cell.textContent);
  if (!meta || !Number.isFinite(rawValue) || !Number.isInteger(index)) {
    renderHourlyTable(true);
    return;
  }
  const value = roundCurveValue(key, rawValue);
  const values = state.curveSeries[key] || [];
  if (index >= 0 && index < values.length) values[index] = value;
  markCurveDirty(key);
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
  if (state.refreshRequestActive) return;
  state.refreshRequestActive = true;
  try {
    const activePage = currentPageName();
    const snapshot = await refreshSnapshotPayload(activePage);
    const deltaRequests = [];
    if (pageNeedsRuntimeLogDelta(activePage)) deltaRequests.push(refreshRuntimeLogs(false));
    if (pageNeedsMeasurementDelta(activePage)) deltaRequests.push(refreshMeasurementDelta(false));
    await Promise.all(deltaRequests);
    renderSnapshot(snapshot);
  } catch (error) {
    console.error("模拟台快照刷新失败", error);
    $("simState").textContent = "offline";
    const solverInfo = $("solverInfo");
    if (solverInfo) solverInfo.textContent = "连接失败";
  } finally {
    state.refreshRequestActive = false;
  }
}

function latestRuntimeLog(snapshot, type) {
  const logs = state.runtimeLogs.length ? state.runtimeLogs : (snapshot.runtime_logs || []);
  return [...logs].find((item) => item?.type === type) || null;
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

function powerSummaryNumber(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function parsePowerFlowOverview(snapshot) {
  const summary = snapshot.power_summary && typeof snapshot.power_summary === "object"
    ? snapshot.power_summary
    : {};
  const structured = {
    source: String(summary.source || ""),
    wind: powerSummaryNumber(summary.wind),
    solar: powerSummaryNumber(summary.solar),
    diesel: powerSummaryNumber(summary.diesel),
    load: powerSummaryNumber(summary.load),
    storage: powerSummaryNumber(summary.storage),
    storageDischarge: powerSummaryNumber(summary.storageDischarge),
    storageCharge: powerSummaryNumber(summary.storageCharge),
    greenPower: powerSummaryNumber(summary.greenPower),
    soc: powerSummaryNumber(summary.soc),
    generation: powerSummaryNumber(summary.generation),
    consumption: powerSummaryNumber(summary.consumption),
    balance: powerSummaryNumber(summary.balance),
  };
  const log = latestRuntimeLog(snapshot, "潮流计算");
  const text = logDetailText(log);
  const controlText = logDetailText(latestRuntimeLog(snapshot, "控制响应"));
  const soc = storageSocPercentFromText(text);
  return {
    log,
    source: structured.source,
    wind: structured.wind ?? matchedNumber(text, /风力发电总功率\s*([-+\d.]+)/),
    solar: structured.solar ?? matchedNumber(text, /光伏发电总功率\s*([-+\d.]+)/),
    diesel: structured.diesel ?? matchedNumber(text, /柴油发电总功率\s*([-+\d.]+)/),
    load: structured.load ?? matchedNumber(text, /负荷用电总功率\s*([-+\d.]+)/),
    storage: structured.storage,
    storageDischarge: structured.storageDischarge ?? matchedNumber(text, /储能发电总功率\s*([-+\d.]+)/),
    storageCharge: structured.storageCharge ?? matchedNumber(text, /储能充电总功率\s*([-+\d.]+)/),
    greenPower: structured.greenPower,
    soc: structured.soc ?? (Number.isFinite(soc) ? soc : storageSocPercentFromText(controlText)),
    generation: structured.generation ?? matchedNumber(text, /电源发电总功率\s*([-+\d.]+)/),
    consumption: structured.consumption ?? matchedNumber(text, /用电及充电总功率\s*([-+\d.]+)/),
    balance: structured.balance ?? matchedNumber(text, /功率差额\s*([-+\d.]+)/),
  };
}

function overviewCurveBoundary(snapshot) {
  const boundary = snapshot.curve_boundary || {};
  if (boundary && typeof boundary === "object" && boundary.point) {
    return {
      point: boundary.point || {},
      loadTotal: Number(boundary.load_total ?? boundary.loadTotal ?? 0),
      index: Number(boundary.index) || 0,
    };
  }
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

function hasOverviewNumber(value) {
  return value !== null && value !== undefined && String(value).trim() !== "" && Number.isFinite(Number(value));
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
  const mainMinHeight = Number.parseFloat(mainGrid ? getComputedStyle(mainGrid).minHeight : "") || 180;
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

function overviewBottomColumnRatioBounds() {
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  const splitter = $("overviewBottomColumnSplitter");
  const gridWidth = bottomGrid?.getBoundingClientRect().width || 0;
  const splitterWidth = splitter?.getBoundingClientRect().width || 12;
  const contentWidth = Math.max(0, gridWidth - splitterWidth);
  if (contentWidth < OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX * 2) {
    return { min: 0, max: 100, contentWidth };
  }
  const minRatio = (OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX / contentWidth) * 100;
  return { min: minRatio, max: 100 - minRatio, contentWidth };
}

function applyOverviewBottomColumnRatio(ratio, persist = false) {
  const numericRatio = Number(ratio);
  const requestedRatio = Number.isFinite(numericRatio) ? numericRatio : OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO;
  const bounds = overviewBottomColumnRatioBounds();
  const nextRatio = Number(clamp(requestedRatio, bounds.min, bounds.max).toFixed(2));
  state.overviewBottomColumnRatio = nextRatio;
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (bottomGrid) {
    bottomGrid.style.setProperty("--overview-bottom-left-ratio", `${nextRatio}fr`);
    bottomGrid.style.setProperty("--overview-bottom-right-ratio", `${Number((100 - nextRatio).toFixed(2))}fr`);
  }
  const splitter = $("overviewBottomColumnSplitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", bounds.min.toFixed(2));
    splitter.setAttribute("aria-valuemax", bounds.max.toFixed(2));
    splitter.setAttribute("aria-valuenow", String(nextRatio));
    splitter.setAttribute("aria-valuetext", `左侧 ${nextRatio.toFixed(2)}%，右侧 ${(100 - nextRatio).toFixed(2)}%`);
  }
  if (persist) localStorage.setItem(OVERVIEW_BOTTOM_COLUMN_RATIO_KEY, String(nextRatio));
}

function beginOverviewBottomColumnSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = $("overviewBottomColumnSplitter");
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (!splitter || !bottomGrid) return;
  const bounds = overviewBottomColumnRatioBounds();
  if (bounds.contentWidth <= 0) return;
  event.preventDefault();
  state.overviewBottomColumnSplitDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startRatio: state.overviewBottomColumnRatio,
    contentWidth: bounds.contentWidth,
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-overview-column-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or cancelled pointer events do not always have capturable pointers.
    }
  }
}

function handleOverviewBottomColumnSplitterDrag(event) {
  const drag = state.overviewBottomColumnSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  const deltaRatio = ((event.clientX - drag.startX) / drag.contentWidth) * 100;
  applyOverviewBottomColumnRatio(drag.startRatio + deltaRatio);
}

function finishOverviewBottomColumnSplitterDrag(event) {
  const drag = state.overviewBottomColumnSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = $("overviewBottomColumnSplitter");
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
  document.body.classList.remove("is-overview-column-splitter-dragging");
  state.overviewBottomColumnSplitDrag = null;
  applyOverviewBottomColumnRatio(state.overviewBottomColumnRatio, true);
}

function handleOverviewBottomColumnSplitterKeydown(event) {
  const bounds = overviewBottomColumnRatioBounds();
  let nextRatio = null;
  if (event.key === "ArrowLeft") nextRatio = state.overviewBottomColumnRatio - 2;
  if (event.key === "ArrowRight") nextRatio = state.overviewBottomColumnRatio + 2;
  if (event.key === "PageUp") nextRatio = state.overviewBottomColumnRatio - 8;
  if (event.key === "PageDown") nextRatio = state.overviewBottomColumnRatio + 8;
  if (event.key === "Home") nextRatio = bounds.min;
  if (event.key === "End") nextRatio = bounds.max;
  if (nextRatio === null) return;
  event.preventDefault();
  applyOverviewBottomColumnRatio(nextRatio, true);
}

function initOverviewBottomColumnSplitter() {
  const splitter = $("overviewBottomColumnSplitter");
  if (!splitter) return;
  applyOverviewBottomColumnRatio(state.overviewBottomColumnRatio);
  if (splitter.dataset.splitterReady === "true") return;
  splitter.dataset.splitterReady = "true";
  splitter.addEventListener("pointerdown", beginOverviewBottomColumnSplitterDrag);
  splitter.addEventListener("keydown", handleOverviewBottomColumnSplitterKeydown);
  window.addEventListener("pointermove", handleOverviewBottomColumnSplitterDrag);
  window.addEventListener("pointerup", finishOverviewBottomColumnSplitterDrag);
  window.addEventListener("pointercancel", finishOverviewBottomColumnSplitterDrag);
  window.addEventListener("resize", () => applyOverviewBottomColumnRatio(overviewInitialBottomColumnRatio()));
}

function initialVerticalSplitRatios() {
  const ratios = { ...VERTICAL_SPLIT_DEFAULTS };
  try {
    const stored = JSON.parse(localStorage.getItem(VERTICAL_SPLIT_STORAGE_KEY) || "{}");
    Object.entries(stored || {}).forEach(([splitId, ratio]) => {
      const numericRatio = Number(ratio);
      if (Number.isFinite(numericRatio)) ratios[splitId] = numericRatio;
    });
  } catch (error) {
    localStorage.removeItem(VERTICAL_SPLIT_STORAGE_KEY);
  }
  return ratios;
}

function verticalSplitDefaultRatio(splitId) {
  return VERTICAL_SPLIT_DEFAULTS[splitId] || VERTICAL_SPLIT_DEFAULT_RATIO;
}

function verticalSplitContainer(splitId) {
  return Array.from(document.querySelectorAll("[data-vertical-split]"))
    .find((container) => container.dataset.verticalSplit === splitId) || null;
}

function verticalSplitBounds(container) {
  if (!container) return { min: 20, max: 80 };
  const rect = container.getBoundingClientRect();
  const splitter = container.querySelector("[data-vertical-splitter]");
  const splitterHeight = splitter?.getBoundingClientRect().height || 10;
  const availableHeight = rect.height > 0 ? rect.height - splitterHeight : 0;
  if (availableHeight <= 0) return { min: 20, max: 80 };
  const minTop = Number(container.dataset.verticalSplitMinTop) || VERTICAL_SPLIT_MIN_TOP_PX;
  const minBottom = Number(container.dataset.verticalSplitMinBottom) || VERTICAL_SPLIT_MIN_BOTTOM_PX;
  const minRatio = clamp((minTop / availableHeight) * 100, 8, 88);
  const maxRatio = clamp(100 - (minBottom / availableHeight) * 100, 12, 92);
  if (minRatio <= maxRatio) return { min: minRatio, max: maxRatio };
  const centerRatio = clamp(50, 8, 92);
  return { min: centerRatio, max: centerRatio };
}

function applyVerticalSplit(splitId, ratio, persist = false, redraw = false) {
  const container = verticalSplitContainer(splitId);
  if (!container) return;
  const bounds = verticalSplitBounds(container);
  const numericRatio = Number(ratio);
  const nextRatio = Math.round(clamp(
    Number.isFinite(numericRatio) ? numericRatio : verticalSplitDefaultRatio(splitId),
    bounds.min,
    bounds.max,
  ) * 10) / 10;
  state.verticalSplitRatios[splitId] = nextRatio;
  container.style.setProperty("--vertical-split-top", `${nextRatio}%`);
  const splitter = container.querySelector(`[data-vertical-splitter="${splitId}"]`);
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    splitter.setAttribute("aria-valuenow", String(nextRatio));
    splitter.setAttribute("aria-valuetext", `${nextRatio}%`);
  }
  if (persist) localStorage.setItem(VERTICAL_SPLIT_STORAGE_KEY, JSON.stringify(state.verticalSplitRatios));
  if (redraw) redrawVerticalSplitContent(splitId);
}

function redrawVerticalSplitContent(splitId) {
  requestAnimationFrame(() => {
    if (splitId === "simulator-curves") drawCurves();
    if (splitId === "simulator-runtime") drawRuntimeTraceChart();
    if (splitId === "simulator-measurements") drawMeasurementTraceChart();
  });
}

function beginVerticalSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = event.currentTarget;
  const splitId = splitter?.dataset.verticalSplitter || "";
  const container = verticalSplitContainer(splitId);
  if (!splitter || !container) return;
  event.preventDefault();
  const containerRect = container.getBoundingClientRect();
  const splitterRect = splitter.getBoundingClientRect();
  state.verticalSplitDrag = {
    splitId,
    pointerId: event.pointerId,
    startY: event.clientY,
    startTopPx: splitterRect.top - containerRect.top,
    availableHeight: Math.max(1, containerRect.height - splitterRect.height),
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-vertical-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Pointer capture can fail for synthetic events during tests.
    }
  }
}

function handleVerticalSplitterDrag(event) {
  const drag = state.verticalSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  const nextTopPx = drag.startTopPx + (event.clientY - drag.startY);
  applyVerticalSplit(drag.splitId, (nextTopPx / drag.availableHeight) * 100, false, true);
}

function finishVerticalSplitterDrag(event) {
  const drag = state.verticalSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = document.querySelector(`[data-vertical-splitter="${drag.splitId}"]`);
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be released.
      }
    }
  }
  document.body.classList.remove("is-vertical-splitter-dragging");
  state.verticalSplitDrag = null;
  applyVerticalSplit(drag.splitId, state.verticalSplitRatios[drag.splitId], true, true);
}

function handleVerticalSplitterKeydown(event) {
  const splitId = event.currentTarget?.dataset.verticalSplitter || "";
  const currentRatio = state.verticalSplitRatios[splitId] || verticalSplitDefaultRatio(splitId);
  const bounds = verticalSplitBounds(verticalSplitContainer(splitId));
  let nextRatio = null;
  if (event.key === "ArrowUp") nextRatio = currentRatio - 2;
  if (event.key === "ArrowDown") nextRatio = currentRatio + 2;
  if (event.key === "PageUp") nextRatio = currentRatio - 8;
  if (event.key === "PageDown") nextRatio = currentRatio + 8;
  if (event.key === "Home") nextRatio = bounds.min;
  if (event.key === "End") nextRatio = bounds.max;
  if (nextRatio === null) return;
  event.preventDefault();
  applyVerticalSplit(splitId, nextRatio, true, true);
}

function initVerticalSplitters() {
  document.querySelectorAll("[data-vertical-splitter]").forEach((splitter) => {
    const splitId = splitter.dataset.verticalSplitter || "";
    if (!splitId) return;
    applyVerticalSplit(splitId, state.verticalSplitRatios[splitId] || verticalSplitDefaultRatio(splitId));
    if (splitter.dataset.verticalSplitterReady === "true") return;
    splitter.dataset.verticalSplitterReady = "true";
    splitter.addEventListener("pointerdown", beginVerticalSplitterDrag);
    splitter.addEventListener("keydown", handleVerticalSplitterKeydown);
  });
  if (document.body.dataset.verticalSplitterResizeReady === "true") return;
  document.body.dataset.verticalSplitterResizeReady = "true";
  window.addEventListener("pointermove", handleVerticalSplitterDrag);
  window.addEventListener("pointerup", finishVerticalSplitterDrag);
  window.addEventListener("pointercancel", finishVerticalSplitterDrag);
  window.addEventListener("resize", () => {
    document.querySelectorAll("[data-vertical-split]").forEach((container) => {
      const splitId = container.dataset.verticalSplit || "";
      applyVerticalSplit(splitId, state.verticalSplitRatios[splitId], true, true);
    });
  });
}

function renderOverviewEvents(snapshot) {
  const container = $("commandInbox");
  if (!container) return;
  const logs = (state.runtimeLogs.length ? state.runtimeLogs : [...(snapshot.runtime_logs || [])].reverse()).slice(0, 8);
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
  const measurements = snapshot.measurements || {};
  const context = runtimeCommandBuildContext(snapshot, measurements);
  return runtimeCommandRowsForDevices(controlDefinitionDevices(snapshot), measurements, context)
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
          <th>本机时刻</th>
          <th>设备</th>
          <th>指令项</th>
          <th>控制指令</th>
          <th>仿真时刻</th>
          <th>实时值</th>
          <th>量测值</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr title="${escapeHtml(runtimeCommandTraceLabel(row))}">
            <td class="mono-cell">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
            <td>${escapeHtml(row.device?.dev_name || "--")}</td>
            <td>${escapeHtml(row.command || "--")} <small class="command-set-type">${escapeHtml(row.set_type || "")}</small></td>
            <td class="numeric-cell">${escapeHtml(runtimeCommandTableValueText(row, "control"))}</td>
            <td class="mono-cell">${escapeHtml(row.receive_time?.simu_time || "--")}</td>
            <td class="numeric-cell">${escapeHtml(runtimeCommandTableValueText(row, "real"))}</td>
            <td class="numeric-cell">${escapeHtml(runtimeCommandTableValueText(row, "scada"))}</td>
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
  const overviewMode = snapshot.curve_boundary?.mode || snapshot.curves?.mode || state.curveMode;
  setOverviewText("overviewMode", overviewMode === "year" ? "年仿真" : "日仿真");
  setOverviewText("overviewStep", `${formatOverviewNumber(clock.step_minutes || 1)} min`);
  setOverviewText("metricScada", validMeasurements);
  setOverviewText("overviewMeasurementTotal", totalMeasurements);
  setOverviewText("metricCommands", snapshot.summary?.command_count || 0);
  setOverviewText("metricAlarms", snapshot.summary?.alarm_count || 0);
  setOverviewText("overviewBoundaryTime", formatSimulationClock(clock));
  setOverviewText("overviewWindSpeed", hasOverviewNumber(boundary.point.wind_speed_mps) ? `${formatOverviewNumber(boundary.point.wind_speed_mps)} m/s` : "--");
  setOverviewText("overviewIrradiance", hasOverviewNumber(boundary.point.solar_irradiance_w_m2) ? `${formatOverviewNumber(boundary.point.solar_irradiance_w_m2)} W/m²` : "--");
  setOverviewText("overviewTemperature", hasOverviewNumber(boundary.point.air_temp_c) ? `${formatOverviewNumber(boundary.point.air_temp_c)} ℃` : "--");
  setOverviewText("overviewLoadBoundary", overviewPowerText(boundary.loadTotal));
  setOverviewText("overviewOnlineDevices", `${onlineDevices}/${devices.length} 台`);
  setOverviewText("overviewActiveCommands", `${activeOverviewCommands.length} 条`);
  const storagePower = Number.isFinite(power.storage)
    ? power.storage
    : Number.isFinite(power.storageDischarge) && Number.isFinite(power.storageCharge)
      ? power.storageDischarge - power.storageCharge
      : null;
  const storageFlow = storagePower === null ? "idle" : storagePower > 0 ? "discharge" : storagePower < 0 ? "charge" : "idle";
  const storageNode = $("overviewStorageFlowNode");
  if (storageNode) storageNode.dataset.storageFlow = storageFlow;
  const storageLink = $("overviewStorageFlowLink");
  if (storageLink) storageLink.dataset.storageFlow = storageFlow;
  setOverviewText("overviewFlowWindPower", overviewPowerText(power.wind));
  setOverviewText("overviewFlowWindMeta", hasOverviewNumber(boundary.point.wind_speed_mps) ? `风速 ${formatOverviewNumber(boundary.point.wind_speed_mps)} m/s` : "风速 未知");
  setOverviewText("overviewFlowSolarPower", overviewPowerText(power.solar));
  setOverviewText("overviewFlowSolarMeta", hasOverviewNumber(boundary.point.solar_irradiance_w_m2) ? `辐照 ${formatOverviewNumber(boundary.point.solar_irradiance_w_m2)} W/m²` : "辐照 未知");
  setOverviewText("overviewFlowDieselPower", overviewPowerText(power.diesel));
  setOverviewText("overviewFlowStoragePower", overviewPowerText(storagePower));
  setOverviewText("overviewFlowStorageDirection", storagePower === null ? "待计算" : storagePower > 0 ? "放电" : storagePower < 0 ? "充电" : "静置");
  setOverviewText("overviewFlowSoc", Number.isFinite(power.soc) ? `${formatOverviewNumber(power.soc)}%` : "--");
  setOverviewText("overviewFlowLoadPower", overviewPowerText(power.load));
  setOverviewText("overviewFlowLoadMeta", Number.isFinite(boundary.loadTotal) ? `需求 ${overviewPowerText(boundary.loadTotal)}` : "需求 --");
  const greenPowerShare = Number.isFinite(power.diesel) && Number.isFinite(power.load) && Math.abs(power.load) > 1e-9
    ? (1.0 - power.diesel / power.load) * 100.0
    : null;
  const greenPower = Number.isFinite(power.greenPower) ? -power.greenPower : null;
  setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderEnergyFlowVisuals(power, storagePower, greenPowerShare);
  setOverviewText("overviewCommandCount", `${activeOverviewCommands.length} 条控制指令`);
  renderOverviewEvents(snapshot);
}

function renderActiveSimulatorPage(snapshot = state.snapshot, force = false) {
  const activePage = currentPageName();
  if (activePage !== "diagram") {
    hideDiagramTooltip(state.pageSections?.diagram?.querySelector?.("#modelDiagramCanvas") || null);
  }
  if (activePage === "overview") {
    if (snapshot) renderOverviewDashboard(snapshot);
    initOverviewBottomSplitter();
    initOverviewBottomColumnSplitter();
    return;
  }
  if (activePage === "model") {
    renderGridModelPage();
    return;
  }
  if (activePage === "diagram") {
    renderModelDiagramPage(snapshot);
    return;
  }
  if (activePage === "curves") {
    resizeCurveCanvas();
    renderCurveEditor(force);
    return;
  }
  if (activePage === "faults") {
    renderFaults(force);
    return;
  }
  if (activePage === "modes") {
    renderModes(force);
    return;
  }
  if (activePage === "parameters") {
    renderSystemParameters(snapshot);
    return;
  }
  if (activePage === "runtime") {
    renderRuntimeMonitor(force);
    return;
  }
  if (activePage === "measurements") {
    renderMeasurementCompareTable();
    return;
  }
  if (activePage === "logs") {
    renderRuntimeLogs();
  }
}

function renderSnapshot(snapshot) {
  if (snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock);
  state.systemParameters = snapshotSystemParameters(snapshot || {});
  const runId = Number(snapshot.clock?.run_id ?? 0);
  const stepCount = Number(snapshot.clock?.step_count ?? 0);
  const traceLifecycleChanged = state.traceRunId !== null && (
    runId !== state.traceRunId
    || (state.traceStepCount !== null && stepCount < state.traceStepCount)
  );
  if (traceLifecycleChanged) {
    state.runtimeTraceHistory = [];
    state.lastRuntimeTraceKey = "";
    state.measurementTraceHistory = [];
    state.lastMeasurementTraceKey = "";
  }
  state.traceRunId = runId;
  state.traceStepCount = stepCount;
  if (snapshot.curves && state.curvesLoadedModelId !== state.activeModelId) {
    loadCurvesFromSnapshot(snapshot.curves, state.activeModelId);
  } else if (snapshot.curve_boundary?.mode) {
    const boundaryMode = CURVE_MODES[snapshot.curve_boundary.mode] ? snapshot.curve_boundary.mode : "day";
    state.curveMode = boundaryMode;
    localStorage.setItem("polarSimulatorCurveMode", boundaryMode);
    state.curveSummary = {
      ...(state.curveSummary || {}),
      mode: boundaryMode,
      time_step_minutes: Number(snapshot.curve_boundary.time_step_minutes) || curveStepMinutes(boundaryMode),
      point_count: Number(snapshot.curve_boundary.point_count) || curvePointCount(boundaryMode),
    };
    if (!curveSummaryHasCatalog(state.curveSummary)) state.curveSummaryLoadedModelId = "";
  }
  const solverInfo = $("solverInfo");
  if (solverInfo) solverInfo.textContent = snapshot.result.solver_info || "待运行";
  if (Array.isArray(snapshot.runtime_logs)) appendRuntimeLog(snapshot);
  appendRuntimeTrace(snapshot);
  appendMeasurementTrace(snapshot);
  if (!state.settingsLoaded && snapshot.settings !== undefined) {
    state.deviceFaults = [...(snapshot.settings?.device_faults || [])];
    state.measurementFaults = [...(snapshot.settings?.measurement_faults || [])];
    state.settingsLoaded = true;
  }
  state.modes = syncModesFromDevices(snapshot.devices || [], [
    ...(snapshot.settings?.modes || []),
    ...state.modes,
  ]);
  renderActiveSimulatorPage(snapshot);
}

function appendRuntimeLog(snapshot) {
  const backendLogs = snapshot.runtime_logs;
  if (Array.isArray(backendLogs)) {
    mergeRuntimeLogItems(backendLogs, {
      reset: true,
      latestSeq: backendLogs.reduce((maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0), 0),
    });
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
  const totalLogs = state.runtimeLogTypeFilter === "all"
    ? Math.max(state.runtimeLogs.length, Number(state.runtimeLogTotal) || 0)
    : state.runtimeLogs.length;
  $("runtimeLogSummary").textContent = state.runtimeLogTypeFilter === "all"
    ? `已加载 ${state.runtimeLogs.length}/${totalLogs} 条`
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
  return deviceFilterMatches(dev, filter);
}

function filteredGridModelDevices(devices = gridModelDevices()) {
  return devices.filter((dev) => gridModelFilterMatches(dev));
}

function gridModelFilterLabel(filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" }) {
  return deviceFilterLabel(filter);
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
  const treeResult = filterDeviceTreeGroups(groupEntries, "model");
  $("modelTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-model-tree-type="all"
      data-model-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("model", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
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
              class="tree-node tree-child model-tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
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
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
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
  const total = state.runtimeLogTypeFilter === "all"
    ? Math.max((logs || []).length, Number(state.runtimeLogTotal) || 0)
    : (logs || []).length;
  return Math.max(1, Math.ceil(total / pageSize));
}

function pagedRuntimeLogs(logs = filteredRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const pageCount = runtimeLogPageCount(logs);
  state.runtimeLogPage = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (state.runtimeLogPage - 1) * pageSize;
  return logs.slice(start, start + pageSize);
}

async function ensureRuntimeLogPageLoaded(page = state.runtimeLogPage) {
  if (state.runtimeLogTypeFilter !== "all") return;
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const neededRows = Math.max(0, Number(page) || 1) * pageSize;
  if (state.runtimeLogs.length >= neededRows) return;
  await fetchRuntimeLogHistoryPage(false);
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
  const total = state.runtimeLogTypeFilter === "all"
    ? Math.max(logs.length, Number(state.runtimeLogTotal) || 0)
    : logs.length;
  const end = Math.min(total, page * state.runtimeLogPageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${total} 条</span>
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

function setGridModelFilter(devType, devName = "", event = null, button = null) {
  state.modelDeviceFilter = updateDeviceTreeFilterSelection(
    "modelDeviceFilter",
    devType,
    devName,
    event,
    "model",
    button,
  );
  if (devType && devType !== "all" && !devName) state.activeModelParamTab = devType;
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

function runtimeSnapshotDevicesByKey(snapshot = state.snapshot || {}) {
  const snapshotDevicesByKey = new Map();
  (snapshot.devices || []).forEach((dev) => {
    snapshotDevicesByKey.set(`${dev.dev_type || ""}|${dev.dev_name || ""}`, dev);
  });
  return snapshotDevicesByKey;
}

function runtimeControlDeviceFromRow(row, snapshot = state.snapshot || {}, context = null) {
  const live = context?.snapshotDevicesByKey?.get(`${row.dev_type || ""}|${row.dev_name || ""}`)
    || runtimeSnapshotDevice(row.dev_type, row.dev_name, snapshot)
    || {};
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
  return deviceFilterMatches(dev, filter);
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

function groupRuntimeMeasurementRowsByDevice(rows = []) {
  const rowsByDevice = new Map();
  (rows || []).forEach((row) => {
    const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
    const deviceRows = rowsByDevice.get(key) || [];
    deviceRows.push(row);
    rowsByDevice.set(key, deviceRows);
  });
  return rowsByDevice;
}

function runtimeMeasurementRowsByDevice(measurements = state.snapshot?.measurements || {}) {
  return groupRuntimeMeasurementRowsByDevice(measurementCompareRows(measurements));
}

function runtimeMeasurementPair(dev, meta, measurements = state.snapshot?.measurements || {}, context = null) {
  const measurementRowsByDevice = context?.measurementRowsByDevice
    || groupRuntimeMeasurementRowsByDevice(measurementCompareRows(measurements));
  const rows = measurementRowsByDevice.get(`${dev.dev_type || ""}|${dev.dev_name || ""}`) || [];
  const best = rows.find((row) => runtimeMeasTypeMatchesSetKey(row.meas_type, meta.key || meta.kind)) || {};
  return {
    name: best.name || "",
    meas_type: best.meas_type || "",
    real: numberOrNull(best.real_value),
    scada: numberOrNull(best.scada_value),
  };
}

function runtimeSignalMeasurementPair(dev, measType, measurements = state.snapshot?.measurements || {}, context = null) {
  const measurementRowsByDevice = context?.measurementRowsByDevice
    || runtimeMeasurementRowsByDevice(measurements);
  const rows = measurementRowsByDevice.get(`${dev.dev_type || ""}|${dev.dev_name || ""}`) || [];
  const expectedType = String(measType || "").toUpperCase();
  const best = rows.find((row) => String(row.meas_type || "").toUpperCase() === expectedType) || {};
  return {
    name: best.name || "",
    meas_type: best.meas_type || "",
    real: numberOrNull(best.real_value),
    scada: numberOrNull(best.scada_value),
  };
}

function formatRuntimeRemoteSignal(value, commandType) {
  const numeric = numberOrNull(value);
  if (numeric === null) return "--";
  if (commandType === "status") return numeric !== 0 ? "闭合" : "断开";
  return numeric !== 0 ? "投入" : "退出";
}

function runtimeDeviceTraceSignal(dev, measurements = state.snapshot?.measurements || {}, context = null) {
  const control = runtimeControlMeta(dev);
  const pair = runtimeMeasurementPair(dev, control, measurements, context);
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

function runtimeCommandTypeLabel(row) {
  return row?.command || row?.set_type || row?.category || row?.signal_kind || "";
}

function runtimeCommandFilterFields(row) {
  const dev = row?.device || {};
  return [
    runtimeCommandTraceLabel(row),
    runtimeCommandTypeLabel(row),
    row?.category,
    row?.command_kind,
    row?.command,
    row?.set_type,
    row?.signal_kind,
    row?.command_text,
    row?.real_text,
    row?.scada_text,
    dev.dev_type,
    dev.dev_name,
    dev.mode,
  ];
}

function syncRuntimeCommandTypeFilter(rows) {
  syncTableKeywordFilter("runtimeCommandKeywordFilter", state.runtimeCommandKeywordFilter);
  syncTableTypeFilter(
    "runtimeCommandTypeFilter",
    "runtimeCommandTypeFilter",
    tableFilterTypeOptions(rows, runtimeCommandTypeLabel),
  );
}

function applyRuntimeCommandTableFilters(rows) {
  const keyword = state.runtimeCommandKeywordFilter || "";
  const type = state.runtimeCommandTypeFilter || "all";
  return (rows || []).filter((row) => {
    if (state.runtimeCommandOnlyActive && !row.active) return false;
    if (!tableFilterMatchesKeyword(runtimeCommandFilterFields(row), keyword)) return false;
    if (type !== "all" && runtimeCommandTypeLabel(row) !== type) return false;
    return true;
  });
}

function syncRuntimeCommandOnlyActiveControl() {
  const input = $("runtimeCommandOnlyActive");
  const text = $("runtimeCommandOnlyActiveText");
  if (input) input.checked = Boolean(state.runtimeCommandOnlyActive);
  if (text) text.textContent = state.runtimeCommandOnlyActive ? "是" : "否";
}

function runtimeCommandRowsForDevices(devices, measurements = state.snapshot?.measurements || {}, context = null) {
  return [
    ...runtimeRemoteControlRows(devices, context),
    ...runtimeRemoteAdjustmentRows(devices, measurements, context),
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
  const context = runtimeCommandBuildContext(snapshot, snapshot.measurements || {});
  const devices = [];
  controlDefinitionDevices(snapshot).forEach((dev) => {
    devices.push(dev);
    point.devices[deviceKey(dev)] = runtimeDeviceTraceSignal(dev, snapshot.measurements || {}, context);
  });
  runtimeCommandRowsForDevices(devices, snapshot.measurements || {}, context).forEach((row) => {
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
  state.runtimeTraceHistory = compactTraceHistory(state.runtimeTraceHistory, state.runtimeTraceWindowMinutes);
}

function renderRuntimeDeviceTree() {
  const container = $("runtimeDeviceTree");
  if (!container) return;
  const devices = runtimeDevices();
  const filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "runtime");
  $("runtimeTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-runtime-tree-type="all"
      data-runtime-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("runtime", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
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
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-runtime-tree-type="${escapeHtml(dev.dev_type)}"
              data-runtime-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function setRuntimeDeviceFilter(devType, devName = "", event = null, button = null) {
  state.runtimeDeviceFilter = updateDeviceTreeFilterSelection(
    "runtimeDeviceFilter",
    devType,
    devName,
    event,
    "runtime",
    button,
  );
  renderRuntimeMonitor(true);
}

function runtimeFilterLabel(filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" }) {
  return deviceFilterLabel(filter);
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
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = numberOrNull(entry.issued_absolute_minute);
    const expires = numberOrNull(entry.expires_at_absolute_minute);
    if (issued === null || expires === null) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function runtimeCommandRefreshIndex(snapshot = state.snapshot || {}) {
  const commandRefreshIndex = {
    run_stat: new Map(),
    status: new Map(),
    set_value: new Map(),
  };
  activeCommandHistory(snapshot).forEach((entry) => {
    const normalized = entry.normalized || {};
    const payload = entry.payload || {};
    const info = commandReceiveTimeInfo(entry);
    const setItems = Array.isArray(normalized.set_values)
      ? normalized.set_values
      : Array.isArray(payload.set_values)
        ? payload.set_values
        : [];
    setItems.forEach((item) => {
      if (!item?.dev_type || !item?.dev_name || !item?.set_type) return;
      commandRefreshIndex.set_value.set(
        `${item.dev_type}|${item.dev_name}|${item.set_type}`,
        info,
      );
    });
    const runItems = Array.isArray(normalized.run_status)
      ? normalized.run_status
      : Array.isArray(payload.run_status)
        ? payload.run_status
        : [];
    runItems.forEach((item) => {
      if (!item?.dev_type || !item?.dev_name) return;
      if (Object.prototype.hasOwnProperty.call(item, "status")) {
        commandRefreshIndex.status.set(`${item.dev_type}|${item.dev_name}|status`, info);
      }
      if (item.run_stat !== undefined && item.run_stat !== "") {
        commandRefreshIndex.run_stat.set(`${item.dev_type}|${item.dev_name}|run_stat`, info);
      }
    });
  });
  return commandRefreshIndex;
}

function runtimeCommandBuildContext(snapshot = state.snapshot || {}, measurements = snapshot.measurements || {}, options = {}) {
  return {
    commandRefreshIndex: runtimeCommandRefreshIndex(snapshot),
    measurementRowsByDevice: options.includeMeasurements === false ? null : runtimeMeasurementRowsByDevice(measurements),
    snapshotDevicesByKey: runtimeSnapshotDevicesByKey(snapshot),
  };
}

function runtimeCommandRefreshInfo(dev, commandType, setType = "", snapshot = state.snapshot || {}, context = null) {
  const commandRefreshIndex = context?.commandRefreshIndex || runtimeCommandRefreshIndex(snapshot);
  const key = `${dev.dev_type || ""}|${dev.dev_name || ""}|${commandType === "set_value" ? setType : commandType}`;
  const indexed = commandRefreshIndex[commandType]?.get(key);
  if (indexed) return indexed;
  if (context?.commandRefreshIndex) return emptyCommandTimeInfo();
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

function runtimeRemoteControlRows(devices, context = null, options = {}) {
  const live = options.live !== false;
  const selectedKeys = selectedRuntimeDeviceKeys(devices);
  const runRows = definedControlRows("RunStat").filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
  const cbRows = definedControlRows("CbOpenStat").filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
  return [
    ...runRows.map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow, state.snapshot || {}, context);
      const runStatTime = runtimeCommandRefreshInfo(dev, "run_stat", "", state.snapshot || {}, context);
      const runPair = live
        ? runtimeSignalMeasurementPair(dev, "RUN_STAT", state.snapshot?.measurements || {}, context)
        : {};
      const value = Number(dev.run_stat ?? definitionRow.run_stat ?? 0);
      return {
        category: "遥控指令",
        command_kind: "remote_control",
        device: dev,
        command: "设备投退",
        set_type: "run_stat",
        command_text: formatRuntimeRemoteSignal(value, "run_stat"),
        real_text: formatRuntimeRemoteSignal(runPair.real ?? value, "run_stat"),
        scada_text: formatRuntimeRemoteSignal(runPair.scada, "run_stat"),
        refresh_time: runStatTime.simu_time,
        receive_time: runStatTime,
        active: commandTimeInfoAvailable(runStatTime),
        control_value: value,
        real_value: runPair.real ?? value,
        scada_value: runPair.scada ?? null,
        signal_kind: "STAT",
        unit: "",
        meas_name: runPair.name || "",
        meas_type: runPair.meas_type || "RUN_STAT",
        trace_label: `${dev.dev_name}.设备投退`,
      };
    }),
    ...cbRows.map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow, state.snapshot || {}, context);
      const statusTime = runtimeCommandRefreshInfo(dev, "status", "", state.snapshot || {}, context);
      const statusPair = live
        ? runtimeSignalMeasurementPair(dev, "STATUS", state.snapshot?.measurements || {}, context)
        : {};
      const value = Number(dev.status ?? definitionRow.status ?? 0);
      return {
        category: "遥控指令",
        command_kind: "remote_control",
        device: dev,
        command: "开关开合",
        set_type: "status",
        command_text: formatRuntimeRemoteSignal(value, "status"),
        real_text: formatRuntimeRemoteSignal(statusPair.real ?? value, "status"),
        scada_text: formatRuntimeRemoteSignal(statusPair.scada, "status"),
        refresh_time: statusTime.simu_time,
        receive_time: statusTime,
        active: commandTimeInfoAvailable(statusTime),
        control_value: value,
        real_value: statusPair.real ?? value,
        scada_value: statusPair.scada ?? null,
        signal_kind: "STAT",
        unit: "",
        meas_name: statusPair.name || "",
        meas_type: statusPair.meas_type || "STATUS",
        trace_label: `${dev.dev_name}.开关开合`,
      };
    }),
  ];
}

function runtimeRemoteAdjustmentRows(devices, measurements = state.snapshot?.measurements || {}, context = null, options = {}) {
  const live = options.live !== false;
  const selectedKeys = selectedRuntimeDeviceKeys(devices);
  return definedControlRows("SetValue")
    .filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`))
    .map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow, state.snapshot || {}, context);
      const key = definitionRow.set_type || "";
      const value = dev.set_values?.[key] ?? definitionRow.set_value;
      const meta = runtimeMetaFromSetKey(key, Number(value));
      const pair = live ? runtimeMeasurementPair(dev, meta, measurements, context) : {};
      const commandTime = runtimeCommandRefreshInfo(dev, "set_value", key, state.snapshot || {}, context);
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
        active: commandTimeInfoAvailable(commandTime),
        control_value: meta.value,
        real_value: pair.real,
        scada_value: pair.scada,
        signal_kind: meta.kind,
        unit: meta.unit,
        trace_label: `${dev.dev_name}.${key}`,
      };
    });
}

function renderRuntimeCommandTabs(remoteControlRows, remoteAdjustmentRows, activeTab = state.activeRuntimeCommandTab) {
  const normalizedTab = activeTab === "remote_adjustment" ? "remote_adjustment" : "remote_control";
  return `
    <div class="runtime-command-tabs" role="tablist" aria-label="控制指令类型">
      <button
        type="button"
        role="tab"
        class="runtime-command-tab ${normalizedTab === "remote_control" ? "is-active" : ""}"
        data-runtime-command-tab="remote_control"
        aria-selected="${normalizedTab === "remote_control" ? "true" : "false"}"
      >
        <span>遥控指令</span><strong>${remoteControlRows.length}</strong>
      </button>
      <button
        type="button"
        role="tab"
        class="runtime-command-tab ${normalizedTab === "remote_adjustment" ? "is-active" : ""}"
        data-runtime-command-tab="remote_adjustment"
        aria-selected="${normalizedTab === "remote_adjustment" ? "true" : "false"}"
      >
        <span>遥调指令</span><strong>${remoteAdjustmentRows.length}</strong>
      </button>
    </div>
  `;
}

function runtimeCommandTableStructureKey(rows) {
  const filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" };
  return [
    state.activeRuntimeCommandTab || "remote_control",
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.runtimeCommandKeywordFilter || "",
    state.runtimeCommandTypeFilter || "all",
    state.runtimeCommandOnlyActive ? "active" : "all",
    rows.map((row) => runtimeCommandTraceKey(row)).join("||"),
  ].join("::");
}

function runtimeCommandTableValueText(row, field) {
  const textFields = {
    control: "command_text",
    real: "real_text",
    scada: "scada_text",
  };
  const text = String(row?.[textFields[field]] ?? "--");
  const unit = String(row?.unit || "").trim();
  if (!unit || text === "--") return text;
  const suffix = ` ${unit}`;
  return text.endsWith(suffix) ? text.slice(0, -suffix.length) : text;
}

function runtimeCommandLiveCellHtml(row, field) {
  if (field === "control") return escapeHtml(runtimeCommandTableValueText(row, "control"));
  if (field === "wall_time") return escapeHtml(row.receive_time?.wall_time || "--");
  if (field === "simu_time") return escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--");
  if (field === "real") return escapeHtml(runtimeCommandTableValueText(row, "real"));
  if (field === "scada") return escapeHtml(runtimeCommandTableValueText(row, "scada"));
  return "";
}

function updateRuntimeCommandTableLiveCells(rows) {
  const tableRows = Array.from(document.querySelectorAll("#deviceTable [data-runtime-command-row-key]"));
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [runtimeCommandTraceKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.runtimeCommandRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    const selected = key === state.selectedRuntimeCommandKey;
    tableRow.classList.toggle("is-selected", selected);
    tableRow.dataset.runtimeCommandRowLabel = runtimeCommandTraceLabel(row);
    tableRow.querySelectorAll("[data-runtime-command-live-field]").forEach((cell) => {
      cell.innerHTML = runtimeCommandLiveCellHtml(row, cell.dataset.runtimeCommandLiveField || "");
    });
  }
  return true;
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
      <td class="numeric-cell" data-runtime-command-live-field="control">${runtimeCommandLiveCellHtml(row, "control")}</td>
      <td class="mono-cell" data-runtime-command-live-field="wall_time">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
      <td class="mono-cell" data-runtime-command-live-field="simu_time">${escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--")}</td>
      <td class="numeric-cell" data-runtime-command-live-field="real">${runtimeCommandLiveCellHtml(row, "real")}</td>
      <td class="numeric-cell" data-runtime-command-live-field="scada">${runtimeCommandLiveCellHtml(row, "scada")}</td>
    </tr>
  `;
  }).join("");
}

function renderRuntimeCommandTable(rows, emptyText, virtualRows = { beforeHeight: 0, afterHeight: 0 }) {
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
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 9)}
        ${renderRuntimeCommandRows(rows)}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 9)}
      </tbody>
    </table>
  `;
}

function renderRuntimeDeviceTable() {
  const container = $("deviceTable");
  if (!container) return;
  syncRuntimeCommandOnlyActiveControl();
  const devices = runtimeDevices();
  const selectedDevices = filteredRuntimeDevices(devices);
  const activeTab = state.activeRuntimeCommandTab === "remote_adjustment" ? "remote_adjustment" : "remote_control";
  const context = runtimeCommandBuildContext(state.snapshot || {}, state.snapshot?.measurements || {}, {
    includeMeasurements: true,
  });
  const remoteControlRows = runtimeRemoteControlRows(selectedDevices, context, { live: activeTab === "remote_control" });
  const remoteAdjustmentRows = runtimeRemoteAdjustmentRows(selectedDevices, state.snapshot?.measurements || {}, context, { live: activeTab === "remote_adjustment" });
  const totalCommandRows = [...remoteControlRows, ...remoteAdjustmentRows];
  syncRuntimeCommandTypeFilter(totalCommandRows);
  const filteredRemoteControlRows = applyRuntimeCommandTableFilters(remoteControlRows);
  const filteredRemoteAdjustmentRows = applyRuntimeCommandTableFilters(remoteAdjustmentRows);
  const commandCount = filteredRemoteControlRows.length + filteredRemoteAdjustmentRows.length;
  const totalCommandCount = totalCommandRows.length;
  const visibleCommandKeys = new Set([...filteredRemoteControlRows, ...filteredRemoteAdjustmentRows].map(runtimeCommandTraceKey));
  if (state.selectedRuntimeCommandKey && !visibleCommandKeys.has(state.selectedRuntimeCommandKey)) {
    state.selectedRuntimeCommandKey = "";
    state.selectedRuntimeCommandLabel = "";
  }
  const filterActive = state.runtimeCommandOnlyActive
    || tableFilterIsActive(state.runtimeCommandKeywordFilter, state.runtimeCommandTypeFilter);
  $("runtimeDeviceSummary").textContent = filterActive
    ? `${runtimeFilterLabel()} · ${commandCount}/${totalCommandCount} 条指令`
    : `${runtimeFilterLabel()} · ${totalCommandCount} 条指令`;
  if (!devices.length) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = '<div class="empty-state">暂无设备数据</div>';
    return;
  }
  if (!selectedDevices.length) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  if (!totalCommandCount) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = '<div class="empty-state">当前筛选无控制指令</div>';
    return;
  }
  const tabHtml = renderRuntimeCommandTabs(filteredRemoteControlRows, filteredRemoteAdjustmentRows, activeTab);
  const activeRows = activeTab === "remote_adjustment"
    ? filteredRemoteAdjustmentRows
    : filteredRemoteControlRows;
  const virtualRows = virtualTableWindow(`runtimeCommand:${activeTab}`, activeRows);
  const structureKey = [
    runtimeCommandTableStructureKey(activeRows),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  const emptyText = activeTab === "remote_adjustment"
    ? (filterActive ? "当前过滤无遥调指令" : "当前筛选无遥调指令")
    : (filterActive ? "当前过滤无遥控指令" : "当前筛选无遥控指令");
  if (!activeRows.length) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = `${tabHtml}<section class="runtime-command-tab-page is-active" data-runtime-command-page="${activeTab}" role="tabpanel"><div class="empty-state">${escapeHtml(emptyText)}</div></section>`;
    return;
  }
  if (
    container.dataset.runtimeCommandStructureKey === structureKey
    && updateRuntimeCommandTableLiveCells(virtualRows.rows)
  ) {
    return;
  }
  container.dataset.runtimeCommandStructureKey = structureKey;
  container.innerHTML = `
    ${tabHtml}
    <section class="runtime-command-tab-page is-active" data-runtime-command-page="${activeTab}" role="tabpanel">
      <div class="runtime-command-table-wrap virtual-table-scroll" data-virtual-table="runtimeCommand:${activeTab}">
        ${renderRuntimeCommandTable(virtualRows.rows, emptyText, virtualRows)}
      </div>
    </section>
  `;
  restoreVirtualTableScroll(container, `runtimeCommand:${activeTab}`);
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
  const context = runtimeCommandBuildContext(state.snapshot || {}, state.snapshot?.measurements || {});
  return runtimeCommandRowsForDevices(devices, state.snapshot?.measurements || {}, context);
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
  return resizeCanvasToRenderedSize(canvas, 900, 260);
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

function isSignalMeasurement(row) {
  return Object.prototype.hasOwnProperty.call(SIGNAL_MEASUREMENT_LABELS, String(row?.meas_type || "").toUpperCase());
}

function weatherMeasurementLabel(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return WEATHER_MEASUREMENT_LABELS[type]?.label || row?.name || type || "气象";
}

function signalMeasurementLabel(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return SIGNAL_MEASUREMENT_LABELS[type]?.label || row?.name || type || "遥信";
}

function weatherMeasurementOrder(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return WEATHER_MEASUREMENT_LABELS[type]?.order ?? 99;
}

function signalMeasurementOrder(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return SIGNAL_MEASUREMENT_LABELS[type]?.order ?? 99;
}

function measurementDisplayName(row) {
  if (isSignalMeasurement(row)) return `${row.dev_name || row.name || ""}.${signalMeasurementLabel(row)}`;
  return isWeatherMeasurement(row) ? `气象.${weatherMeasurementLabel(row)}` : row.name;
}

function measurementDeviceDisplay(row) {
  return isWeatherMeasurement(row) ? "气象.weather" : `${row.dev_type || "--"}.${row.dev_name || "--"}`;
}

function measurementTypeDisplay(row) {
  if (isSignalMeasurement(row)) return signalMeasurementLabel(row);
  return isWeatherMeasurement(row) ? weatherMeasurementLabel(row) : row.meas_type;
}

function compareMeasurementsForDisplay(left, right) {
  const leftWeather = isWeatherMeasurement(left);
  const rightWeather = isWeatherMeasurement(right);
  if (leftWeather !== rightWeather) return leftWeather ? -1 : 1;
  if (leftWeather && rightWeather) return weatherMeasurementOrder(left) - weatherMeasurementOrder(right);
  const leftSignal = isSignalMeasurement(left);
  const rightSignal = isSignalMeasurement(right);
  if (leftSignal !== rightSignal) return leftSignal ? -1 : 1;
  if (leftSignal && rightSignal) {
    const signalOrder = signalMeasurementOrder(left) - signalMeasurementOrder(right);
    if (signalOrder) return signalOrder;
  }
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
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
}

function ensureSelectedMeasurementKey(rows, fallbackRows = []) {
  const availableRows = rows.length ? rows : fallbackRows;
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
  return resizeCanvasToRenderedSize(canvas, 900, 260);
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
    let previousMinute = null;
    points.forEach((point) => {
      const value = numberOrNull(point[series.field]);
      if (value === null) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      const restartPath = started && previousMinute !== null && point.minute <= previousMinute;
      if (restartPath) {
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x, y);
      } else if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
      previousMinute = point.minute;
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
  return rows.filter((row) => deviceFilterMatches(row, filter));
}

function measurementCompareTypeFilterLabel(row) {
  return measurementTypeDisplay(row) || row?.meas_type || "";
}

function measurementCompareFilterFields(row) {
  return [
    measurementDisplayName(row),
    measurementDeviceDisplay(row),
    measurementCompareTypeFilterLabel(row),
    row?.name,
    row?.idx,
    row?.dev_type,
    row?.dev_name,
    row?.meas_type,
  ];
}

function syncMeasurementCompareTypeFilter(rows) {
  syncTableKeywordFilter("measurementCompareKeywordFilter", state.measurementCompareKeywordFilter);
  syncTableTypeFilter(
    "measurementCompareTypeFilter",
    "measurementCompareTypeFilter",
    tableFilterTypeOptions(rows, measurementCompareTypeFilterLabel),
  );
}

function applyMeasurementCompareTableFilters(rows) {
  const keyword = state.measurementCompareKeywordFilter || "";
  const type = state.measurementCompareTypeFilter || "all";
  return (rows || []).filter((row) => {
    if (!tableFilterMatchesKeyword(measurementCompareFilterFields(row), keyword)) return false;
    if (type !== "all" && measurementCompareTypeFilterLabel(row) !== type) return false;
    return true;
  });
}

function measurementTelemetryRows(rows) {
  return (rows || []).filter((row) => !isSignalMeasurement(row));
}

function measurementSignalRows(rows) {
  return (rows || []).filter((row) => isSignalMeasurement(row));
}

function setMeasurementCompareTab(tabName) {
  state.activeMeasurementCompareTab = tabName === "signal" ? "signal" : "telemetry";
  renderMeasurementCompareTable();
  drawMeasurementTraceChart();
}

function activeMeasurementCompareRows(rows) {
  return state.activeMeasurementCompareTab === "signal"
    ? measurementSignalRows(rows)
    : measurementTelemetryRows(rows);
}

function renderMeasurementCompareTabs(telemetryRows, signalRows) {
  const activeTab = state.activeMeasurementCompareTab === "signal" ? "signal" : "telemetry";
  const tabs = [
    { key: "telemetry", label: "遥测", count: telemetryRows.length },
    { key: "signal", label: "遥信", count: signalRows.length },
  ];
  return `
    <div class="measurement-type-tabs" role="tablist" aria-label="量测类型">
      ${tabs.map((tab) => `
        <button
          type="button"
          role="tab"
          class="measurement-type-tab ${activeTab === tab.key ? "is-active" : ""}"
          data-measurement-compare-tab="${tab.key}"
          aria-selected="${activeTab === tab.key ? "true" : "false"}"
        >
          <span>${tab.label}</span>
          <strong>${tab.count}</strong>
        </button>
      `).join("")}
    </div>
  `;
}

function measurementCompareTableStructureKey(rows) {
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  return [
    state.activeMeasurementCompareTab || "telemetry",
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.measurementCompareKeywordFilter || "",
    state.measurementCompareTypeFilter || "all",
    rows.map((row) => measurementKey(row)).join("||"),
  ].join("::");
}

function measurementLiveCellHtml(row, field) {
  if (field === "real") return formatMeasurementValue(row.real_value);
  if (field === "scada") return formatMeasurementValue(row.scada_value);
  if (field === "weight") return escapeHtml(row.weight);
  if (field === "status") {
    const valid = Number(row.valid) === 1;
    return `<span class="status-dot ${valid ? "on" : ""}"></span>${valid ? "有效" : "无效"}`;
  }
  if (field === "diff") return row.diff === null ? "--" : formatMeasurementValue(row.diff);
  return "";
}

function updateMeasurementCompareTableLiveCells(rows, selectedKey) {
  const tableRows = Array.from(document.querySelectorAll("#measurementCompareTable [data-measurement-row-key]"));
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [measurementKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.measurementRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    const selected = key === selectedKey;
    tableRow.classList.toggle("is-selected", selected);
    tableRow.setAttribute("aria-selected", selected ? "true" : "false");
    tableRow.querySelectorAll("[data-measurement-live-field]").forEach((cell) => {
      const field = cell.dataset.measurementLiveField || "";
      cell.innerHTML = measurementLiveCellHtml(row, field);
      if (field === "diff") {
        const diffActive = row.diff !== null && Math.abs(row.diff) >= 1e-6;
        cell.classList.toggle("diff-active", diffActive);
        cell.classList.toggle("diff-neutral", !diffActive);
      }
    });
  }
  return true;
}

function renderMeasurementCompareDeviceTree(rows = measurementCompareRows()) {
  const container = $("measurementCompareDeviceTree");
  if (!container) return;
  const devices = measurementCompareDevices(rows);
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "measurement");
  $("measurementCompareTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-measurement-tree-type="all"
      data-measurement-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("measurement", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
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
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, item.dev_type, item.dev_name) ? "is-active" : ""}"
              data-measurement-tree-type="${escapeHtml(item.dev_type)}"
              data-measurement-tree-name="${escapeHtml(item.dev_name)}"
            >
              <span>${escapeHtml(item.dev_type === "Environment" && item.dev_name === "weather" ? "气象" : item.dev_name)}</span>
              <small>${escapeHtml(item.count)}点</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function setMeasurementCompareFilter(devType, devName = "", event = null, button = null) {
  state.measurementCompareFilter = updateDeviceTreeFilterSelection(
    "measurementCompareFilter",
    devType,
    devName,
    event,
    "measurement",
    button,
  );
  renderMeasurementCompareTable();
}

function renderMeasurementCompareTable() {
  const container = $("measurementCompareTable");
  if (!container) return;
  const allRows = measurementCompareRows();
  renderMeasurementCompareDeviceTree(allRows);
  const filteredRows = filteredMeasurementCompareRows(allRows);
  syncMeasurementCompareTypeFilter(filteredRows);
  const tableFilteredRows = applyMeasurementCompareTableFilters(filteredRows);
  const telemetryRows = measurementTelemetryRows(tableFilteredRows);
  const signalRows = measurementSignalRows(tableFilteredRows);
  const rows = activeMeasurementCompareRows(tableFilteredRows);
  const selectedKey = ensureSelectedMeasurementKey(rows, []);
  const validCount = rows.filter((row) => Number(row.valid) === 1).length;
  const activeLabel = state.activeMeasurementCompareTab === "signal" ? "遥信" : "遥测";
  const filterActive = tableFilterIsActive(state.measurementCompareKeywordFilter, state.measurementCompareTypeFilter);
  $("measurementCompareSummary").textContent = filterActive
    ? `${activeLabel} ${rows.length}/${tableFilteredRows.length} 点 · 有效 ${validCount} 点 · 过滤 ${tableFilteredRows.length}/${filteredRows.length} 点`
    : `${activeLabel} ${rows.length}/${filteredRows.length} 点 · 有效 ${validCount} 点`;
  const tabHtml = renderMeasurementCompareTabs(telemetryRows, signalRows);
  const virtualRows = virtualTableWindow("measurementCompare", rows);
  const structureKey = [
    measurementCompareTableStructureKey(rows),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  if (!allRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">暂无实时量测数据</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (!filteredRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">当前筛选无量测</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (!tableFilteredRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">当前过滤无量测</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (!rows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">当前分类无量测</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (
    container.dataset.measurementStructureKey === structureKey
    && updateMeasurementCompareTableLiveCells(rows, selectedKey)
  ) {
    drawMeasurementTraceChart();
    return;
  }
  container.dataset.measurementStructureKey = structureKey;
  container.innerHTML = `
    ${tabHtml}
    <div class="measurement-type-tab-page is-active">
    <div class="virtual-table-scroll" data-virtual-table="measurementCompare">
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
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 8)}
        ${virtualRows.rows.map((row) => {
          const diffClass = row.diff === null || Math.abs(row.diff) < 1e-6 ? "diff-neutral" : "diff-active";
          const key = measurementKey(row);
          return `
            <tr
              class="${key === selectedKey ? "is-selected" : ""}"
              data-measurement-row-key="${escapeHtml(key)}"
              data-measurement-select-key="${escapeHtml(key)}"
              tabindex="0"
              aria-selected="${key === selectedKey ? "true" : "false"}"
            >
              <td>${escapeHtml(measurementDisplayName(row) || "--")}</td>
              <td>${escapeHtml(measurementDeviceDisplay(row))}</td>
              <td>${escapeHtml(measurementTypeDisplay(row) || "--")}</td>
              <td class="numeric-cell" data-measurement-live-field="real">${formatMeasurementValue(row.real_value)}</td>
              <td class="numeric-cell" data-measurement-live-field="scada">${formatMeasurementValue(row.scada_value)}</td>
              <td class="numeric-cell ${diffClass}" data-measurement-live-field="diff">${row.diff === null ? "--" : formatMeasurementValue(row.diff)}</td>
              <td class="numeric-cell" data-measurement-live-field="weight">${escapeHtml(row.weight)}</td>
              <td data-measurement-live-field="status"><span class="status-dot ${Number(row.valid) === 1 ? "on" : ""}"></span>${Number(row.valid) === 1 ? "有效" : "无效"}</td>
            </tr>
          `;
        }).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 8)}
      </tbody>
    </table>
    </div>
    </div>`;
  restoreVirtualTableScroll(container, "measurementCompare");
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
    .filter(({ dev }) => deviceFilterMatches(dev, filter));
}

function filteredFaultMeasurements() {
  const filter = state.faultMeasurementFilter || { dev_type: "all", dev_name: "", key: "" };
  return faultMeasurements()
    .map((meas, index) => ({ meas, index }))
    .filter(({ meas }) => {
      if (!deviceFilterMatches(meas, filter)) return false;
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
  const treeResult = filterDeviceTreeGroups(groupEntries, "faultDevice");
  $("faultDeviceTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-fault-device-tree-type="all"
      data-fault-device-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("faultDevice", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
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
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-fault-device-tree-type="${escapeHtml(dev.dev_type)}"
              data-fault-device-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function renderFaultMeasurementTree() {
  const container = $("faultMeasurementTree");
  if (!container) return;
  const measurements = faultMeasurements();
  const devices = faultMeasurementDevices(measurements);
  const filter = state.faultMeasurementFilter || { dev_type: "all", dev_name: "", key: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "faultMeasurement");
  $("faultMeasurementTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-fault-measurement-tree-type="all"
      data-fault-measurement-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("faultMeasurement", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
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
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-fault-measurement-tree-type="${escapeHtml(dev.dev_type)}"
              data-fault-measurement-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(dev.count)}点</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function setDeviceFaultFilter(devType, devName = "", event = null, button = null) {
  state.faultDeviceFilter = updateDeviceTreeFilterSelection(
    "faultDeviceFilter",
    devType,
    devName,
    event,
    "faultDevice",
    button,
  );
  renderFaults(true);
}

function setMeasurementFaultFilter(devType, devName = "", event = null, button = null) {
  state.faultMeasurementFilter = {
    ...updateDeviceTreeFilterSelection(
      "faultMeasurementFilter",
      devType,
      devName,
      event,
      "faultMeasurement",
      button,
    ),
    key: "",
  };
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
    .filter(({ item }) => deviceFilterMatches(item, filter));
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
  const treeResult = filterDeviceTreeGroups(groupEntries, "mode");
  $("modeTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-mode-tree-type="all"
      data-mode-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : state.modes.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("mode", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
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
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, item.dev_type, item.dev_name) ? "is-active" : ""}"
              data-mode-tree-type="${escapeHtml(item.dev_type)}"
              data-mode-tree-name="${escapeHtml(item.dev_name)}"
            >
              <span>${escapeHtml(item.dev_name)}</span>
              <small>${escapeHtml(item.mode)}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
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

function setModeFilter(devType, devName = "", event = null, button = null) {
  state.modeFilter = updateDeviceTreeFilterSelection(
    "modeFilter",
    devType,
    devName,
    event,
    "mode",
    button,
  );
  renderModes(true);
}

function updateModeValue(index, field, rawValue) {
  if (field !== "mode" || !state.modes[index]) return;
  state.modes[index].mode = rawValue;
  renderModes(true);
}

async function saveCurves() {
  const config = curveModeConfig();
  const dirtyKeys = state.curveDirtyKeys instanceof Set ? Array.from(state.curveDirtyKeys) : [];
  const keysToSave = Array.from(new Set([...dirtyKeys, ...selectedCurveKeys()]))
    .filter((key) => curveHasLoadedSeries(key));
  if (!keysToSave.length) {
    $("curveStatus").textContent = "没有需要保存的曲线";
    return;
  }
  await ensureCurveSeriesLoaded(keysToSave);
  const series = {};
  keysToSave.forEach((key) => {
    if (curveHasLoadedSeries(key)) series[key] = state.curveSeries[key].map((value) => roundCurveValue(key, value));
  });
  await api("/api/curves/series", {
    method: "POST",
    body: JSON.stringify({
      mode: state.curveMode,
      point_count: config.pointCount,
      time_step_minutes: config.stepMinutes,
      series,
    }),
  });
  state.curveDirtyKeys = new Set();
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
$("modelManagementButton").addEventListener("click", openModelManagementDialog);
$("closeModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("cancelModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("modelManagementDialog").addEventListener("click", (event) => {
  if (event.target.id === "modelManagementDialog") closeModelManagementDialog();
});
$("modelManagementList").addEventListener("click", handleModelManagementAction);
$("modelManagementList").addEventListener("keydown", handleModelManagementKeydown);
$("modelManagementList").addEventListener("contextmenu", openModelContextMenu);
$("modelManagementList").addEventListener("scroll", closeModelContextMenu);
$("modelContextMenu").addEventListener("click", handleModelContextMenuAction);
document.addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("#modelContextMenu")) return;
  closeModelContextMenu();
});
$("newModelButton").addEventListener("click", openNewModelDialog);
$("selectNewModelFile").addEventListener("click", () => $("newModelFileInput").click());
$("newModelFileInput").addEventListener("change", handleNewModelFileSelected);
$("selectNewModelSvgFile").addEventListener("click", () => $("newModelSvgInput").click());
$("newModelSvgInput").addEventListener("change", handleNewModelSvgFileSelected);
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
$("closeNewModelDialog").addEventListener("click", closeNewModelDialog);
$("cancelNewModel").addEventListener("click", closeNewModelDialog);
$("newModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "newModelDialog") closeNewModelDialog();
});
$("newModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createNewModelFromFile();
});
$("newModelName").addEventListener("input", () => validateNewModelForm());
$("closeUpdateModelDialog").addEventListener("click", closeUpdateModelDialog);
$("cancelUpdateModel").addEventListener("click", closeUpdateModelDialog);
$("updateModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "updateModelDialog") closeUpdateModelDialog();
});
$("selectUpdateModelFile").addEventListener("click", () => $("updateModelFileInput").click());
$("updateModelFileInput").addEventListener("change", handleUpdateModelFileSelected);
$("selectUpdateModelSvgFile").addEventListener("click", () => $("updateModelSvgInput").click());
$("updateModelSvgInput").addEventListener("change", handleUpdateModelSvgFileSelected);
$("updateModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  updateModelFromFile();
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
  if (event.key === "Escape") closeModelContextMenu();
  if (event.key === "Escape" && !$("startSimulationDialog").hidden) {
    closeStartSimulationDialog();
    return;
  }
  if (event.key === "Escape" && !$("importModelDialog").hidden) {
    closeImportModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("newModelDialog").hidden) {
    closeNewModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("updateModelDialog").hidden) {
    closeUpdateModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("cloneModelDialog").hidden) {
    closeCloneModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("traineeLinkDialog").hidden) {
    closeTraineeLinkDialog();
    return;
  }
  if (event.key === "Escape" && !$("modelManagementDialog").hidden) {
    closeModelManagementDialog();
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
$("saveCurves").addEventListener("click", () => {
  saveCurves().catch((error) => {
    $("curveStatus").textContent = `保存失败：${apiErrorText(error)}`;
  });
});
document.addEventListener("click", (event) => {
  const retryButton = event.target instanceof Element ? event.target.closest("[data-curve-retry]") : null;
  if (!retryButton) return;
  event.preventDefault();
  retryCurveEditorLoad();
});
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
$("runtimeLogPager").addEventListener("click", async (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-runtime-log-page]") : null;
  if (!button) return;
  const direction = button.dataset.runtimeLogPage;
  const pageCount = runtimeLogPageCount(filteredRuntimeLogs());
  state.runtimeLogPage = direction === "prev"
    ? Math.max(1, state.runtimeLogPage - 1)
    : Math.min(pageCount, state.runtimeLogPage + 1);
  await ensureRuntimeLogPageLoaded(state.runtimeLogPage);
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
["parameterClockSpeed", "parameterComputeInterval", "parameterStorageInitialSoc"].forEach((id) => {
  const element = $(id);
  if (element) element.addEventListener("input", markSystemParametersDirty);
});
function handleSimulatorTableFilterControl(target) {
  if (!(target instanceof Element)) return false;
  const control = target.closest("[data-table-filter-scope]");
  if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return false;
  const scope = control.dataset.tableFilterScope || "";
  const field = control.dataset.tableFilterField || "";
  if (scope === "measurementCompare") {
    if (field === "type") state.measurementCompareTypeFilter = control.value || "all";
    else state.measurementCompareKeywordFilter = control.value || "";
    renderMeasurementCompareTable();
    drawMeasurementTraceChart();
    return true;
  }
  if (scope === "runtimeCommand") {
    if (field === "type") state.runtimeCommandTypeFilter = control.value || "all";
    else state.runtimeCommandKeywordFilter = control.value || "";
    renderRuntimeDeviceTable();
    drawRuntimeTraceChart();
    return true;
  }
  return false;
}

document.addEventListener("input", (event) => {
  if (handleSimulatorTableFilterControl(event.target)) return;
  const input = event.target.closest?.("[data-device-tree-filter-scope]");
  if (!input) return;
  const scope = input.dataset.deviceTreeFilterScope || "";
  state.deviceTreeSearch[scope] = input.value || "";
  refreshDeviceTreeFilterScope(scope);
});
document.addEventListener("change", (event) => {
  if (!(event.target instanceof Element)) return;
  const target = event.target;
  const onlyActiveToggle = target.closest("#runtimeCommandOnlyActive");
  if (!(onlyActiveToggle instanceof HTMLInputElement)) return;
  state.runtimeCommandOnlyActive = onlyActiveToggle.checked;
  syncRuntimeCommandOnlyActiveControl();
  renderRuntimeDeviceTable();
  drawRuntimeTraceChart();
});
document.addEventListener("scroll", handleVirtualTableScroll, true);
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
  const measurementCompareTab = event.target.closest("[data-measurement-compare-tab]");
  if (measurementCompareTab) {
    setMeasurementCompareTab(measurementCompareTab.dataset.measurementCompareTab || "telemetry");
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
    if (faultDeviceTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        faultDeviceTreeButton.dataset.treeToggleScope,
        faultDeviceTreeButton.dataset.treeToggleGroup,
      );
    }
    setDeviceFaultFilter(
      faultDeviceTreeButton.dataset.faultDeviceTreeType,
      faultDeviceTreeButton.dataset.faultDeviceTreeName || "",
      event,
      faultDeviceTreeButton,
    );
  }
  const faultMeasurementTreeButton = event.target.closest("[data-fault-measurement-tree-type]");
  if (faultMeasurementTreeButton) {
    if (faultMeasurementTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        faultMeasurementTreeButton.dataset.treeToggleScope,
        faultMeasurementTreeButton.dataset.treeToggleGroup,
      );
    }
    setMeasurementFaultFilter(
      faultMeasurementTreeButton.dataset.faultMeasurementTreeType,
      faultMeasurementTreeButton.dataset.faultMeasurementTreeName || "",
      event,
      faultMeasurementTreeButton,
    );
  }
  const measurementSelectRow = event.target.closest("[data-measurement-select-key]");
  if (measurementSelectRow) {
    setSelectedMeasurementKey(measurementSelectRow.dataset.measurementSelectKey || "");
  }
  const measurementTreeButton = event.target.closest("[data-measurement-tree-type]");
  if (measurementTreeButton) {
    if (measurementTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        measurementTreeButton.dataset.treeToggleScope,
        measurementTreeButton.dataset.treeToggleGroup,
      );
    }
    setMeasurementCompareFilter(
      measurementTreeButton.dataset.measurementTreeType,
      measurementTreeButton.dataset.measurementTreeName || "",
      event,
      measurementTreeButton,
    );
  }
  const modelTreeButton = event.target.closest("[data-model-tree-type]");
  if (modelTreeButton) {
    if (modelTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        modelTreeButton.dataset.treeToggleScope,
        modelTreeButton.dataset.treeToggleGroup,
      );
    }
    setGridModelFilter(
      modelTreeButton.dataset.modelTreeType,
      modelTreeButton.dataset.modelTreeName || "",
      event,
      modelTreeButton,
    );
  }
  const runtimeTreeButton = event.target.closest("[data-runtime-tree-type]");
  if (runtimeTreeButton) {
    if (runtimeTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        runtimeTreeButton.dataset.treeToggleScope,
        runtimeTreeButton.dataset.treeToggleGroup,
      );
    }
    setRuntimeDeviceFilter(
      runtimeTreeButton.dataset.runtimeTreeType,
      runtimeTreeButton.dataset.runtimeTreeName || "",
      event,
      runtimeTreeButton,
    );
  }
  const modeTreeButton = event.target.closest("[data-mode-tree-type]");
  if (modeTreeButton) {
    if (modeTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        modeTreeButton.dataset.treeToggleScope,
        modeTreeButton.dataset.treeToggleGroup,
      );
    }
    setModeFilter(modeTreeButton.dataset.modeTreeType, modeTreeButton.dataset.modeTreeName || "", event, modeTreeButton);
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
  if (handleSimulatorTableFilterControl(event.target)) return;
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
generateCurves(0);
initCurveEditor();
initRuntimeMonitor();
initMeasurementMonitor();
initOverviewBottomSplitter();
initOverviewBottomColumnSplitter();
initVerticalSplitters();
setFaultTab(state.activeFaultTab);
renderFaults(true);
initPageNavigation();
setInterval(refresh, 1000);
loadModels().finally(refresh);
