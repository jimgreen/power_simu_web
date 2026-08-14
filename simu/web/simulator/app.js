const directSimulatorServiceMode = document.documentElement.dataset.simulatorUiMode === "direct";
const directSimulatorServiceApiBase = (
  new URLSearchParams(location.search).get("service")
  || window.POLAR_SIM_SERVICE_URL
  || location.origin
).replace(/\/$/, "");
const controlPlaneApiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
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
const CURVE_TREE_COLLAPSE_KEY = "polarSimulatorCurveTreeCollapsedGroups";
const RUNTIME_LOG_COLUMN_WIDTHS_KEY = "polarSimulatorRuntimeLogColumnWidths";
const RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS = Object.freeze([104, 104, 112, 190, 104, 640]);
const RUNTIME_LOG_COLUMN_MIN_WIDTHS = Object.freeze([82, 82, 78, 110, 78, 180]);
const HIDDEN_REFRESH_INTERVAL_MS = 10000;
const WEB_RUNTIME_FALLBACKS = {
  frontend_refresh_seconds: 1,
  frontend_request_timeout_seconds: 30,
  runtime_log_page_size: 20,
  runtime_log_cache_limit: 300,
  curve_request_timeout_seconds: 8,
  runtime_log_delta_batch_size: 200,
  runtime_log_history_batch_size: 120,
  diagram_flow_electric_threshold_kw: 0.1,
  diagram_flow_hydrogen_threshold_nm3_h: 0.1,
};
const WEB_RUNTIME_CURRENT_IDS = {
  frontend_refresh_seconds: "currentWebRuntimeFrontendRefresh",
  frontend_request_timeout_seconds: "currentWebRuntimeFrontendRequestTimeout",
  runtime_log_page_size: "currentWebRuntimeLogPageSize",
  runtime_log_cache_limit: "currentWebRuntimeLogCacheLimit",
  curve_request_timeout_seconds: "currentWebRuntimeCurveRequestTimeout",
  runtime_log_delta_batch_size: "currentWebRuntimeLogDeltaBatchSize",
  runtime_log_history_batch_size: "currentWebRuntimeLogHistoryBatchSize",
  diagram_flow_electric_threshold_kw: "currentWebRuntimeDiagramElectricFlowThreshold",
  diagram_flow_hydrogen_threshold_nm3_h: "currentWebRuntimeDiagramHydrogenFlowThreshold",
};
const state = {
  snapshot: null,
  activePage: "",
  pageSections: {},
  pageMain: null,
  models: [],
  modelsLoaded: false,
  serviceSuggestion: { host: "127.0.0.1", port: 8711 },
  modelServiceOperationActive: false,
  clockControlOperationActive: false,
  serviceCatalogLastLoadedAt: 0,
  activeModelId: localStorage.getItem("polarSimulatorModelId") || "",
  manualDefinitionChanges: [],
  manualDefinitionChangesRevision: 0,
  manualDefinitionChangesLoadedModelId: "",
  manualDefinitionChangesLoading: false,
  manualDefinitionChangesResetting: false,
  manualDefinitionChangesRetrying: false,
  manualDefinitionChangesError: "",
  manualDefinitionChangesMessage: "",
  manualDefinitionChangesMessageWarning: false,
  manualDefinitionChangeSelection: new Set(),
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
  curveTreeGroupCollapsed: readStoredCurveTreeCollapsedGroups(),
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
  chartPeriodOffsets: { runtimeTrace: 0, measurementTrace: 0 },
  runtimeTraceHistory: [],
  runtimeTraceWindowMinutes: 60,
  lastRuntimeTraceKey: "",
  runtimeCommandKeywordFilter: "",
  runtimeCommandTypeFilter: "all",
  runtimeCommandOriginFilter: "all",
  runtimeCommandOnlyActive: false,
  runtimeCommandDeleteSending: new Set(),
  measurementCompareFilter: { dev_type: "all", dev_name: "" },
  measurementCompareKeywordFilter: "",
  measurementCompareTypeFilter: "all",
  activeMeasurementCompareTab: "telemetry",
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
  measurementHistoryLoaded: {},
  measurementHistoryRequests: {},
  measurementHistoryGeneration: 0,
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
  runtimeLogColumnWidths: readStoredRuntimeLogColumnWidths(),
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
  embeddedMeasurementDeltaReceived: false,
  measurementArrayWarning: "",
  systemParameters: {
    clock_speed: 1,
    compute_interval_seconds: 1,
    storage_initial_soc: 0.5,
    remote_adjustment_response_ratio: 0.7,
  },
  systemParametersDirty: false,
  systemParametersSaving: false,
  webRuntimeSettings: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeDefaults: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeConstraints: {},
  webRuntimeDraft: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeUpdatedAt: "",
  webRuntimeLoadedModelId: "",
  webRuntimeLoading: false,
  webRuntimeSaving: false,
  webRuntimeDirty: false,
  webRuntimeError: "",
  frontendRefreshTimerId: null,
  deviceRuntimeSignature: "",
  deviceRuntimeNeedsFullRefresh: false,
  deviceRuntimeWarning: "",
  frontendDiagnostics: {
    requestCount: 0,
    responseBytes: 0,
    requestDurationMs: 0,
    snapshotRequestCount: 0,
    snapshotResponseBytes: 0,
    snapshotRenderCount: 0,
  },
  overviewBottomHeight: overviewInitialBottomHeight(),
  overviewBottomSplitDrag: null,
  overviewBottomColumnRatio: overviewInitialBottomColumnRatio(),
  overviewBottomColumnSplitDrag: null,
  verticalSplitRatios: initialVerticalSplitRatios(),
  verticalSplitDrag: null,
  virtualTables: {},
  virtualTableScrollRaf: {},
};
window.__polarFrontendDiagnostics = state.frontendDiagnostics;

const $ = (id) => document.getElementById(id);
const deviceTreeRenderKeys = new WeakMap();
const MODE_OPTIONS = ["PQ", "PV", "PH", "V"];

function activeRuntimeSetting(name) {
  const value = Number(state.webRuntimeSettings?.[name]);
  if (Number.isFinite(value)) return value;
  const configuredDefault = Number(state.webRuntimeDefaults?.[name]);
  if (Number.isFinite(configuredDefault)) return configuredDefault;
  return Number(WEB_RUNTIME_FALLBACKS[name]) || 0;
}

function frontendRefreshIntervalMs() {
  return Math.max(200, activeRuntimeSetting("frontend_refresh_seconds") * 1000);
}

function frontendRequestTimeoutMs() {
  return Math.max(1000, activeRuntimeSetting("frontend_request_timeout_seconds") * 1000);
}

function curveRequestTimeoutMs() {
  return Math.max(1000, activeRuntimeSetting("curve_request_timeout_seconds") * 1000);
}

function pageIsHidden() {
  return document.visibilityState === "hidden";
}

function refreshSchedulerIntervalMs() {
  return pageIsHidden() ? HIDDEN_REFRESH_INTERVAL_MS : frontendRefreshIntervalMs();
}

function scheduleNextRefresh(delayMs = refreshSchedulerIntervalMs()) {
  if (state.frontendRefreshTimerId) clearTimeout(state.frontendRefreshTimerId);
  state.frontendRefreshTimerId = setTimeout(runRefreshScheduler, Math.max(0, delayMs));
}

function restartRefreshScheduler() {
  scheduleNextRefresh();
}

async function runRefreshScheduler() {
  state.frontendRefreshTimerId = null;
  const startedAtMs = Date.now();
  try {
    await refreshServiceCatalog();
    if (activeModelServiceRunning()) await refresh();
  } finally {
    const elapsedMs = Date.now() - startedAtMs;
    scheduleNextRefresh(Math.max(0, refreshSchedulerIntervalMs() - elapsedMs));
  }
}

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
  hour: { key: "hour", label: "时曲线", pointCount: 3600, stepMinutes: 1 / 60, durationMinutes: 60, simulationLabel: "时仿真", defaultClockSpeed: 1, tableTitle: "时曲线数据表", tableSummary: "1秒间隔 · 可编辑" },
  day: { key: "day", label: "日曲线", pointCount: 1440, stepMinutes: 1, durationMinutes: 24 * 60, simulationLabel: "日仿真", defaultClockSpeed: 60, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 可编辑" },
  week: { key: "week", label: "周曲线", pointCount: 10080, stepMinutes: 1, durationMinutes: 7 * 24 * 60, simulationLabel: "周仿真", defaultClockSpeed: 60, tableTitle: "周曲线数据表", tableSummary: "1分钟间隔 · 可编辑" },
  month: { key: "month", label: "月曲线", pointCount: 720, stepMinutes: 60, durationMinutes: 30 * 24 * 60, simulationLabel: "月仿真", defaultClockSpeed: 3600, tableTitle: "月曲线数据表", tableSummary: "1小时间隔 · 可编辑" },
  year: { key: "year", label: "年曲线", pointCount: 8760, stepMinutes: 60, durationMinutes: 365 * 24 * 60, simulationLabel: "年仿真", defaultClockSpeed: 3600, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 可编辑" },
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
const LOAD_CURVE_FAMILIES = [
  { key: "electric", label: "电负荷曲线", blocks: ["ACLoad", "DCLoad"], unit: "kW", setType: "p_set", valueKey: "p_kw" },
  { key: "hydrogen", label: "氢负荷曲线", blocks: ["HydroLoad"], unit: "Nm³/h", setType: "flow_set", valueKey: "flow_set" },
  { key: "heat", label: "热负荷曲线", blocks: ["HeatLoad"], unit: "kW", setType: "heat_power", valueKey: "heat_power" },
];
const SOURCE_CURVE_FAMILIES = [
  { key: "electric", label: "电源曲线" },
  { key: "hydrogen", label: "氢源曲线" },
  { key: "heat", label: "热源曲线" },
];
const SOURCE_CURVE_COLORS = ["#126f8a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_PLOT = { left: 58, right: 24, top: 46, bottom: 34 };
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
const DIAGRAM_MEASUREMENT_FIELD_LABELS = Object.freeze({
  P_GEN: "p",
  Q_GEN: "q",
  V_GEN: "u",
  I_GEN: "i",
  P_LOAD: "p",
  Q_LOAD: "q",
  V_LOAD: "u",
  I_LOAD: "i",
});
let pendingImportDefinitionFile = null;
let pendingNewModelFile = null;
let pendingNewModelSvgFile = null;
let newModelCreationActive = false;
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

function compactTraceHistory(history) {
  return Array.isArray(history) ? history : [];
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

function chartPointAtCursorAnchor(points, anchorPoint) {
  const source = points || [];
  const anchorTime = String(anchorPoint?.time || anchorPoint?.sim_time || "").trim();
  if (anchorTime && anchorTime !== "--") {
    const matchingTime = source.filter((point) => (
      String(point?.time || point?.sim_time || "").trim() === anchorTime
    ));
    if (matchingTime.length) return matchingTime[matchingTime.length - 1];
  }
  const anchorMinute = Number(anchorPoint?.minute);
  if (Number.isFinite(anchorMinute)) {
    const matchingMinute = source.filter((point) => {
      const minute = Number(point?.minute);
      return Number.isFinite(minute) && Math.abs(minute - anchorMinute) <= 1e-9;
    });
    if (matchingMinute.length) return matchingMinute[matchingMinute.length - 1];
    return null;
  }
  return nearestChartPoint(source, Number(anchorPoint?.x));
}

function chartCursorSnapshot(seriesData, selectedKey, cursorX) {
  const source = seriesData || [];
  const anchorSeries = source.find((series) => (
    series.key === selectedKey && Array.isArray(series.points) && series.points.length
  )) || source.find((series) => Array.isArray(series.points) && series.points.length);
  if (!anchorSeries) return null;
  const anchorPoint = nearestChartPoint(anchorSeries.points, cursorX);
  if (!anchorPoint) return null;
  const samples = source.map((series) => ({
    series,
    point: chartPointAtCursorAnchor(series.points, anchorPoint),
  })).filter((item) => item.point);
  return samples.length ? { anchorPoint, samples } : null;
}

function drawChartCursor(ctx, chartKey, canvas, plot, seriesData, options = {}) {
  const cursor = state.chartCursors?.[chartKey];
  const visibleSeries = (seriesData || []).filter((series) => !isChartSeriesHidden(chartKey, series.key));
  if (!cursor?.visible || !visibleSeries.length) return;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const selectedKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const snapshot = chartCursorSnapshot(visibleSeries, selectedKey, clamp(cursor.x, left, right));
  if (!snapshot) return;
  const { anchorPoint: mainPoint, samples } = snapshot;
  const x = clamp(mainPoint.x, left, right);
  const y = clamp(mainPoint.y, top, bottom);
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

function simulationModeLabel(mode = state.curveMode) {
  return CURVE_MODES[mode]?.simulationLabel || CURVE_MODES.day.simulationLabel;
}

function simulationModeDayCount(mode = state.curveMode) {
  if (mode === "week") return 7;
  if (mode === "month") return 30;
  if (mode === "year") return 365;
  return 1;
}

function simulationModeDurationMinutes(mode = state.curveMode) {
  return CURVE_MODES[mode]?.durationMinutes || CURVE_MODES.day.durationMinutes;
}

function isExtendedSimulationMode(mode = state.curveMode) {
  return simulationModeDayCount(mode) > 1;
}

function formatClockDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value >= 3600 && value % 3600 === 0) return `${formatOverviewNumber(value / 3600)} h`;
  if (value >= 60 && value % 60 === 0) return `${formatOverviewNumber(value / 60)} min`;
  return `${formatOverviewNumber(value)} s`;
}

function formatSimulationClock(clock) {
  const timeText = clock?.time || "00:00:00";
  const mode = CURVE_MODES[state.curveMode] ? state.curveMode : "day";
  if (!isExtendedSimulationMode(mode)) return timeText;
  const absoluteMinute = Math.max(0, Number(clock?.absolute_minute ?? clock?.minute ?? 0) || 0);
  let dayOfCycle = Math.floor(absoluteMinute / 1440) % simulationModeDayCount(mode);
  if (mode !== "year") return `第${dayOfCycle + 1}天 ${timeText}`;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfCycle >= monthDays[month]) {
    dayOfCycle -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(dayOfCycle + 1).padStart(2, "0")} ${timeText}`;
}

function clockControlButtonDisabled(action, clockState) {
  if (clockState === "running" && ["start", "step"].includes(action)) return true;
  if (clockState === "paused" && action === "pause") return true;
  if (clockState === "stopped" && ["stop", "pause", "step"].includes(action)) return true;
  return false;
}

function clockControlButtonUnavailable(action, clockState) {
  return (
    state.clockControlOperationActive
    || modelServiceDependentControlsDisabled()
    || clockControlButtonDisabled(action, clockState)
  );
}

function renderClockControlAvailability(clockState = "") {
  const resolvedClockState = (
    clockState
    || document.querySelector(".clock-readout")?.dataset.clockState
    || state.snapshot?.clock?.state
    || "stopped"
  );
  document.querySelectorAll("[data-clock]").forEach((button) => {
    const action = button.dataset.clock;
    button.disabled = clockControlButtonUnavailable(action, resolvedClockState);
    button.setAttribute("aria-disabled", button.disabled ? "true" : "false");
  });
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
    readout.classList.toggle("is-year-mode", isExtendedSimulationMode());
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
  renderClockControlAvailability(clock.state || "stopped");
  renderCurveModeControls();
}

function renderPowerFlowFailureAlert(snapshot = state.snapshot || {}) {
  const alert = $("powerFlowFailureAlert");
  if (!alert) return;
  const computeStatus = String(snapshot.compute?.status || "").toLowerCase();
  const failed = computeStatus === "failed" || computeStatus === "timeout";
  alert.hidden = !failed;
  if (!failed) return;
  const timedOut = computeStatus === "timeout";
  const simulationPaused = String(snapshot.clock?.state || "").toLowerCase() === "paused";
  const simuTime = snapshot.compute?.simu_time || snapshot.clock?.time || "--";
  const lastSuccessTime = snapshot.compute?.last_successful_simu_time || "";
  const error = snapshot.compute?.error || snapshot.result?.error || "潮流内核未返回可用结果";
  const title = $("powerFlowFailureTitle");
  const detail = $("powerFlowFailureDetail");
  if (title) {
    title.textContent = simulationPaused
      ? (timedOut ? "潮流计算超时，仿真已暂停" : "潮流计算失败，仿真已暂停")
      : (timedOut ? "潮流计算超时，本轮结果已丢弃" : "潮流计算失败，本轮结果已丢弃");
  }
  if (detail) {
    const staleFrameText = lastSuccessTime
      ? `当前画面量测为上一成功帧（${lastSuccessTime}）`
      : "当前画面没有成功潮流量测帧";
    detail.textContent = (
      `失败仿真时刻 ${simuTime}。${error}。`
      + `本轮潮流结果未采用，${staleFrameText}，请修正边界后${simulationPaused ? "再恢复运行" : "重新计算"}。`
    );
  }
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

function parameterPercentInputText(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? parameterText(number * 100, digits) : "";
}

function parameterPercentText(value, digits = 2) {
  const text = parameterPercentInputText(value, digits);
  return text ? `${text}%` : "--";
}

function snapshotSystemParameters(snapshot = state.snapshot || {}) {
  const params = snapshot.system_parameters || {};
  const clock = snapshot.clock || {};
  const clockStepSeconds = parameterNumber(params.clock_step_seconds ?? clock.step_seconds, 1);
  const clockSpeed = parameterNumber(params.clock_speed ?? clock.speed, 1);
  return {
    clock_speed: clockSpeed,
    compute_interval_seconds: parameterNumber(params.compute_interval_seconds, 1),
    storage_initial_soc: Math.max(0, Math.min(1, parameterNumber(params.storage_initial_soc, 0.5))),
    remote_adjustment_response_ratio: Math.max(
      0.01,
      Math.min(1, parameterNumber(params.remote_adjustment_response_ratio, 0.7)),
    ),
    clock_step_seconds: clockStepSeconds,
    clock_step_minutes: parameterNumber(params.clock_step_minutes ?? clock.step_minutes, clockStepSeconds / 60),
    effective_step_seconds: parameterNumber(
      params.effective_step_seconds ?? clock.effective_step_seconds,
      clockStepSeconds * clockSpeed,
    ),
    effective_step_minutes: parameterNumber(
      params.effective_step_minutes ?? clock.effective_step_minutes,
      (clockStepSeconds * clockSpeed) / 60,
    ),
  };
}

function renderSystemParameters(snapshot = state.snapshot) {
  const params = snapshotSystemParameters(snapshot || {});
  state.systemParameters = params;
  const currentSpeed = $("currentClockSpeed");
  const currentInterval = $("currentComputeInterval");
  const currentStorageInitialSoc = $("currentStorageInitialSoc");
  const currentRemoteAdjustmentResponseRatio = $("currentRemoteAdjustmentResponseRatio");
  if (currentSpeed) currentSpeed.textContent = `x${parameterText(params.clock_speed, 1)}`;
  if (currentInterval) currentInterval.textContent = `${parameterText(params.compute_interval_seconds, 2)} s`;
  if (currentStorageInitialSoc) currentStorageInitialSoc.textContent = parameterPercentText(params.storage_initial_soc, 2);
  if (currentRemoteAdjustmentResponseRatio) {
    currentRemoteAdjustmentResponseRatio.textContent = parameterText(params.remote_adjustment_response_ratio, 2);
  }

  const form = $("systemParameterForm");
  const isEditing = Boolean(form?.contains(document.activeElement));
  if (!state.systemParametersDirty && !isEditing) {
    const speedInput = $("parameterClockSpeed");
    const intervalInput = $("parameterComputeInterval");
    const storageInitialSocInput = $("parameterStorageInitialSoc");
    const remoteAdjustmentResponseRatioInput = $("parameterRemoteAdjustmentResponseRatio");
    if (speedInput) speedInput.value = String(params.clock_speed);
    if (intervalInput) intervalInput.value = parameterText(params.compute_interval_seconds, 2);
    if (storageInitialSocInput) storageInitialSocInput.value = parameterPercentInputText(params.storage_initial_soc, 2);
    if (remoteAdjustmentResponseRatioInput) {
      remoteAdjustmentResponseRatioInput.value = parameterText(params.remote_adjustment_response_ratio, 2);
    }
  }

  const summary = $("systemParameterSummary");
  if (summary) {
    summary.textContent = state.systemParametersSaving
      ? "保存中"
      : state.systemParametersDirty
        ? "有未保存修改"
        : `x${parameterText(params.clock_speed, 1)} · ${parameterText(params.compute_interval_seconds, 2)} s · SOC ${parameterPercentText(params.storage_initial_soc, 2)} · 遥调 ${parameterText(params.remote_adjustment_response_ratio, 2)}`;
  }

  const modelName = snapshot?.model?.name || snapshot?.model?.id || state.activeModelId || "--";
  const clock = snapshot?.clock || {};
  const modeLabel = simulationModeLabel();
  const stateText = clock.state || "--";
  const stateMap = { running: "运行中", paused: "已暂停", stopped: "已停止" };
  const values = {
    systemParameterState: state.systemParametersDirty ? "待保存" : "已同步",
    parameterModelName: modelName,
    parameterSimulationMode: modeLabel,
    parameterClockState: stateMap[stateText] || stateText,
    parameterClockTime: snapshot?.clock ? formatSimulationClock(clock) : "--",
    parameterEffectiveStep: formatClockDuration(params.effective_step_seconds),
    parameterComputePeriod: `${parameterText(params.compute_interval_seconds, 2)} s`,
    parameterStorageInitialSocState: parameterPercentText(params.storage_initial_soc, 2),
    parameterRemoteAdjustmentResponseRatioState: parameterText(params.remote_adjustment_response_ratio, 2),
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
          (state.systemParameters.storage_initial_soc ?? 0.5) * 100,
        ) / 100,
      ),
    ),
    remote_adjustment_response_ratio: Math.max(
      0.01,
      Math.min(
        1,
        parameterNumber(
          $("parameterRemoteAdjustmentResponseRatio")?.value,
          state.systemParameters.remote_adjustment_response_ratio ?? 0.7,
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

function runtimeParameterElement(id) {
  return $(id) || state.pageSections?.parameters?.querySelector?.(`#${id}`) || null;
}

function resetWebRuntimeSettingsState() {
  state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS };
  state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS };
  state.webRuntimeConstraints = {};
  state.webRuntimeDraft = { ...WEB_RUNTIME_FALLBACKS };
  state.webRuntimeUpdatedAt = "";
  state.webRuntimeLoadedModelId = "";
  state.webRuntimeLoading = false;
  state.webRuntimeSaving = false;
  state.webRuntimeDirty = false;
  state.webRuntimeError = "";
}

function runtimeSettingDisplay(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(3)));
}

function renderWebRuntimeSettings() {
  const root = state.pageSections?.parameters || document;
  const values = state.webRuntimeDirty ? state.webRuntimeDraft : state.webRuntimeSettings;
  root.querySelectorAll?.("[data-runtime-setting]").forEach((input) => {
    const name = input.dataset.runtimeSetting || "";
    const value = Number(values?.[name]);
    if (Number.isFinite(value) && document.activeElement !== input) input.value = String(value);
    const constraint = state.webRuntimeConstraints?.[name] || {};
    if (constraint.min !== undefined) input.min = String(constraint.min);
    if (constraint.max !== undefined) input.max = String(constraint.max);
    input.disabled = state.webRuntimeLoading || state.webRuntimeSaving;
  });
  Object.entries(WEB_RUNTIME_CURRENT_IDS).forEach(([name, id]) => {
    const node = runtimeParameterElement(id);
    if (node) node.textContent = runtimeSettingDisplay(state.webRuntimeSettings?.[name]);
  });
  const activeModel = state.models.find((model) => model.id === state.activeModelId);
  const modelName = activeModel?.name || state.snapshot?.model?.name || state.activeModelId || "--";
  const modelNode = runtimeParameterElement("runtimeParameterModelName");
  const updatedNode = runtimeParameterElement("runtimeParameterUpdatedAt");
  if (modelNode) modelNode.textContent = modelName;
  if (updatedNode) updatedNode.textContent = state.webRuntimeUpdatedAt || "尚未保存（使用默认值）";
  const summary = runtimeParameterElement("runtimeParameterSummary");
  if (summary) {
    summary.textContent = state.webRuntimeSaving
      ? "保存中"
      : state.webRuntimeLoading
        ? "加载中"
        : state.webRuntimeError
          ? `加载失败：${state.webRuntimeError}`
          : state.webRuntimeDirty
            ? "有未保存修改"
            : "已生效";
  }
  const saveButton = runtimeParameterElement("saveRuntimeParameters");
  const undoButton = runtimeParameterElement("undoRuntimeParameters");
  const defaultsButton = runtimeParameterElement("restoreRuntimeParameterDefaults");
  if (saveButton) saveButton.disabled = !state.webRuntimeDirty || state.webRuntimeLoading || state.webRuntimeSaving;
  if (undoButton) undoButton.disabled = !state.webRuntimeDirty || state.webRuntimeLoading || state.webRuntimeSaving;
  if (defaultsButton) defaultsButton.disabled = state.webRuntimeLoading || state.webRuntimeSaving;
}

function applyWebRuntimeSettings() {
  state.runtimeLogPageSize = Math.max(5, Math.round(activeRuntimeSetting("runtime_log_page_size")));
  const logLimit = Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit")));
  state.runtimeLogs = state.runtimeLogs.slice(0, logLimit);
  state.runtimeTraceHistory = compactTraceHistory(state.runtimeTraceHistory, state.runtimeTraceWindowMinutes);
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
  restartRefreshScheduler();
}

async function loadWebRuntimeSettings(force = false) {
  const modelId = state.activeModelId;
  if (!modelId || !activeModelServiceRunning()) return null;
  if (!force && state.webRuntimeLoadedModelId === modelId) {
    renderWebRuntimeSettings();
    return state.webRuntimeSettings;
  }
  state.webRuntimeLoading = true;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
  try {
    const payload = await api("/api/runtime-settings", { timeoutMs: frontendRequestTimeoutMs() });
    if (modelId !== state.activeModelId) return null;
    state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS, ...(payload.settings || {}) };
    state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS, ...(payload.defaults || {}) };
    state.webRuntimeConstraints = payload.constraints || {};
    state.webRuntimeDraft = { ...state.webRuntimeSettings };
    state.webRuntimeUpdatedAt = payload.updatedAt || "";
    state.webRuntimeLoadedModelId = modelId;
    state.webRuntimeDirty = false;
    applyWebRuntimeSettings();
    return payload;
  } catch (error) {
    if (modelId === state.activeModelId) state.webRuntimeError = apiErrorText(error);
    return null;
  } finally {
    if (modelId === state.activeModelId) {
      state.webRuntimeLoading = false;
      renderWebRuntimeSettings();
    }
  }
}

function updateWebRuntimeDraft(input) {
  const name = input?.dataset?.runtimeSetting || "";
  if (!name) return;
  const value = Number(input.value);
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    [name]: Number.isFinite(value) ? value : input.value,
  };
  state.webRuntimeDirty = true;
  renderWebRuntimeSettings();
}

async function saveWebRuntimeSettings() {
  if (state.webRuntimeSaving || !state.webRuntimeDirty) return;
  state.webRuntimeSaving = true;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
  try {
    const payload = await api("/api/runtime-settings", {
      method: "POST",
      body: JSON.stringify({ settings: state.webRuntimeDraft }),
    });
    state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS, ...(payload.settings || {}) };
    state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS, ...(payload.defaults || {}) };
    state.webRuntimeConstraints = payload.constraints || {};
    state.webRuntimeDraft = { ...state.webRuntimeSettings };
    state.webRuntimeUpdatedAt = payload.updatedAt || "";
    state.webRuntimeLoadedModelId = state.activeModelId;
    state.webRuntimeDirty = false;
    applyWebRuntimeSettings();
  } catch (error) {
    state.webRuntimeError = apiErrorText(error);
  } finally {
    state.webRuntimeSaving = false;
    renderWebRuntimeSettings();
  }
}

function undoWebRuntimeSettings() {
  state.webRuntimeDraft = { ...state.webRuntimeSettings };
  state.webRuntimeDirty = false;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
}

function restoreWebRuntimeDefaults() {
  state.webRuntimeDraft = { ...state.webRuntimeDefaults };
  state.webRuntimeDirty = true;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
}

function setClockButtonsBusy(isBusy) {
  state.clockControlOperationActive = Boolean(isBusy);
  document.querySelectorAll("[data-clock]").forEach((button) => {
    button.classList.toggle("is-busy", isBusy);
  });
  renderClockControlAvailability();
}

async function controlClock(action, payload = {}) {
  setClockButtonsBusy(true);
  try {
    const clock = await api("/api/clock", { method: "POST", body: JSON.stringify({ ...payload, action }) });
    renderClock(clock);
    await refresh();
    return clock;
  } catch (error) {
    const simState = $("simState");
    const solverInfo = $("solverInfo");
    if (simState) simState.textContent = "error";
    if (solverInfo) solverInfo.textContent = "时钟控制失败";
    throw error;
  } finally {
    setClockButtonsBusy(false);
  }
}

function startSimulationMode() {
  return CURVE_MODES[state.curveMode] ? state.curveMode : "day";
}

function startSimulationDefaultAbsoluteSecond() {
  const clock = state.snapshot?.clock || {};
  const second = Number(
    clock.absolute_second
      ?? ((clock.absolute_minute ?? clock.minute ?? 0) * 60),
  );
  return Number.isFinite(second) ? Math.max(0, second) : 0;
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
  const mode = startSimulationMode();
  const dayCount = simulationModeDayCount(mode);
  const usesDay = dayCount > 1;
  const dayField = $("startSimulationDayField");
  const dayInput = $("startSimulationDay");
  const hint = $("startSimulationHint");
  if (dayField) dayField.hidden = !usesDay;
  if (dayInput) {
    dayInput.disabled = !usesDay;
    dayInput.max = String(dayCount);
  }
  if (hint) {
    hint.textContent = usesDay
      ? `${simulationModeLabel(mode)}按周期内起始日和时刻启动；后台会按当前时钟步长向上对齐。`
      : `${simulationModeLabel(mode)}按起始时刻启动；后台会按当前时钟步长向上对齐。`;
  }
}

function openStartSimulationDialog() {
  const dialog = $("startSimulationDialog");
  const dayInput = $("startSimulationDay");
  const timeInput = $("startSimulationTime");
  if (!dialog || !timeInput) return;
  const absoluteSecond = startSimulationDefaultAbsoluteSecond();
  const dayCount = simulationModeDayCount(startSimulationMode());
  const day = Math.floor(absoluteSecond / 86400) % dayCount + 1;
  if (dayInput) dayInput.value = String(day);
  timeInput.value = secondToTimeInput(absoluteSecond % 86400, 0);
  updateStartSimulationFields();
  setStartSimulationBusy(false);
  setStartSimulationMessage("");
  dialog.hidden = false;
  requestAnimationFrame(() => {
    if (isExtendedSimulationMode(startSimulationMode()) && dayInput) {
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

function startSimulationSecondFromDialog() {
  const timeSecond = timeInputToSecond($("startSimulationTime")?.value, 0);
  const dayCount = simulationModeDayCount(startSimulationMode());
  if (dayCount <= 1) return timeSecond;
  const rawDay = Number($("startSimulationDay")?.value);
  const day = clamp(Math.round(Number.isFinite(rawDay) ? rawDay : 1), 1, dayCount);
  return (day - 1) * 86400 + timeSecond;
}

async function startSimulationFromDialog() {
  const second = startSimulationSecondFromDialog();
  setStartSimulationBusy(true);
  setStartSimulationMessage("正在启动仿真...");
  try {
    await controlClock("start", { second });
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
  const hostInput = $("newModelServiceHost");
  const portInput = $("newModelServicePort");
  const selectButton = $("selectNewModelFile");
  const selectSvgButton = $("selectNewModelSvgFile");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "新建中" : "新建";
  }
  if (button) button.disabled = isBusy;
  if (input) input.disabled = isBusy;
  if (hostInput) hostInput.disabled = isBusy;
  if (portInput) portInput.disabled = isBusy;
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
  const serviceAddress = validateServiceAddressInputs("newModelServiceHost", "newModelServicePort");
  updateServiceAddressPreview("newModelServiceHost", "newModelServicePort", "newModelServicePreview");
  if (!serviceAddress.ok) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(serviceAddress.message, "error");
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
  const serviceState = String(model?.service?.state || "stopped");
  if (serviceState !== "running") return "stopped";
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

function modelServiceStateText(serviceState) {
  return {
    running: "服务运行",
    starting: "启动中",
    stopping: "停止中",
    failed: "服务异常",
    stopped: "服务停止",
  }[serviceState] || serviceState || "服务停止";
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
  const serviceState = String(selected?.service?.state || "stopped");
  const menu = $("modelContextMenu");
  const exportButton = menu?.querySelector('[data-model-context-action="export"]');
  const cloneButton = menu?.querySelector('[data-model-context-action="clone"]');
  const updateButton = menu?.querySelector('[data-model-context-action="update"]');
  const deleteButton = menu?.querySelector('[data-model-context-action="delete"]');
  if (exportButton) exportButton.disabled = !hasSelected;
  if (cloneButton) cloneButton.disabled = !hasSelected;
  if (updateButton) {
    const canUpdate = hasSelected && (
      clockState === "stopped"
      || (serviceState === "running" && clockState === "unknown")
    );
    updateButton.disabled = !canUpdate;
    updateButton.title = !hasSelected
      ? "请选择模型"
      : (clockState === "stopped"
        ? "导入修改后的模型与图形数据"
        : (canUpdate ? "打开后核实仿真时钟状态" : "模型运行中或暂停中，不能修改"));
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
    const serviceState = String(model?.service?.state || "stopped");
    const endpoint = modelServiceEndpoint(model);
    return `
      <div
        class="model-management-item ${isActive ? "is-active" : ""} ${isSelected ? "is-selected" : ""}"
        role="treeitem"
        tabindex="0"
        aria-selected="${isSelected ? "true" : "false"}"
        data-model-id="${escapeHtml(modelId)}"
      >
        <span class="model-management-node-mark" aria-hidden="true"></span>
        <div class="model-node-main">
          <strong class="model-node-name">${escapeHtml(model.name || modelId)}</strong>
          <span class="model-service-address" title="${escapeHtml(model?.service?.base_url || endpoint.accessLink)}">${escapeHtml(endpoint.accessLink)}</span>
        </div>
        <div class="model-item-badges">
          ${isActive ? '<span class="model-current-pill">当前</span>' : ""}
          <span class="model-service-state-pill" data-state="${escapeHtml(serviceState)}">${escapeHtml(modelServiceStateText(serviceState))}</span>
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
  const hostInput = $("newModelServiceHost");
  const portInput = $("newModelServicePort");
  if (!dialog || !input) return;
  pendingNewModelFile = null;
  pendingNewModelSvgFile = null;
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  if (filename) filename.textContent = "未选择文件";
  if (svgFilename) svgFilename.textContent = "未选择图形";
  input.value = uniqueNewModelName("新模型");
  if (hostInput) hostInput.value = state.serviceSuggestion.host || "127.0.0.1";
  if (portInput) portInput.value = String(state.serviceSuggestion.port || 8711);
  updateServiceAddressPreview("newModelServiceHost", "newModelServicePort", "newModelServicePreview");
  dialog.hidden = false;
  validateNewModelForm();
  const initialHost = String(hostInput?.value || "");
  const initialPort = String(portInput?.value || "");
  api("/api/simulator-services/suggestion", {
    modelScoped: false,
    controlPlane: true,
    timeoutMs: 3000,
  }).then((result) => {
    captureServiceSuggestion(result);
    if (dialog.hidden) return;
    if (String(hostInput?.value || "") !== initialHost || String(portInput?.value || "") !== initialPort) return;
    if (hostInput) hostInput.value = state.serviceSuggestion.host || "127.0.0.1";
    if (portInput) portInput.value = String(state.serviceSuggestion.port || 8711);
    updateServiceAddressPreview("newModelServiceHost", "newModelServicePort", "newModelServicePreview");
    validateNewModelForm();
  }).catch(() => {});
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
  if (newModelCreationActive) return;
  const file = pendingNewModelFile;
  const input = $("newModelName");
  const name = String(input?.value || "").trim();
  const serviceAddress = validateServiceAddressInputs("newModelServiceHost", "newModelServicePort");
  if (!file || !validateNewModelForm(true)) {
    input?.focus();
    return;
  }
  newModelCreationActive = true;
  setNewModelBusy(true);
  setNewModelMessage("正在读取 model.e 并生成模型定义...");
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const diagramSvgBase64 = pendingNewModelSvgFile
      ? arrayBufferToBase64(await pendingNewModelSvgFile.arrayBuffer())
      : "";
    const result = await controlPlaneApi("/api/models/create", {
      method: "POST",
      body: JSON.stringify({
        name,
        service_host: serviceAddress.host,
        service_port: serviceAddress.port,
        filename: file.name,
        data_base64: dataBase64,
        diagram_filename: pendingNewModelSvgFile?.name || "",
        diagram_svg_base64: diagramSvgBase64,
      }),
    });
    captureServiceSuggestion(result);
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
    newModelCreationActive = false;
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
  const hostInput = $("updateModelServiceHost");
  const portInput = $("updateModelServicePort");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "保存中" : "确认";
  }
  if (selectFile) selectFile.disabled = isBusy;
  if (selectSvg) selectSvg.disabled = isBusy;
  if (hostInput) hostInput.disabled = isBusy;
  if (portInput) portInput.disabled = isBusy;
}

function formatSelectedModelFile(file) {
  if (!file) return "";
  const size = Number(file.size);
  let sizeText = "";
  if (Number.isFinite(size) && size >= 0) {
    sizeText = size < 1024
      ? `${size} B`
      : size < 1024 * 1024
        ? `${(size / 1024).toFixed(1)} KB`
        : `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  return [String(file.name || "").trim(), sizeText].filter(Boolean).join(" · ");
}

function renderPendingUpdateModelFiles() {
  const filename = $("updateModelFilename");
  const svgFilename = $("updateModelSvgFilename");
  if (filename) {
    filename.textContent = pendingUpdateModelFile
      ? formatSelectedModelFile(pendingUpdateModelFile)
      : "未选择，保持当前文件";
  }
  if (svgFilename) {
    svgFilename.textContent = pendingUpdateModelSvgFile
      ? formatSelectedModelFile(pendingUpdateModelSvgFile)
      : "未选择，保持当前图形";
  }
}

function updateModelSelectionMessage() {
  if (pendingUpdateModelFile && pendingUpdateModelSvgFile) {
    return `已选择 E 文件“${pendingUpdateModelFile.name}”和 SVG 图“${pendingUpdateModelSvgFile.name}”，确认后导入。`;
  }
  if (pendingUpdateModelFile) {
    return `已选择 E 文件“${pendingUpdateModelFile.name}”；SVG 图保持不变。`;
  }
  if (pendingUpdateModelSvgFile) {
    return `已选择 SVG 图“${pendingUpdateModelSvgFile.name}”；E 文件保持不变。`;
  }
  return "未选择新文件，仅保存访问链接。";
}

function openUpdateModelFilePicker(inputId) {
  const input = $(inputId);
  if (!(input instanceof HTMLInputElement)) return;
  // Clear the native input so selecting the same file again still emits change.
  input.value = "";
  input.click();
}

function validateUpdateModelForm(showSelection = false) {
  const confirm = $("confirmUpdateModel");
  const hostInput = $("updateModelServiceHost");
  const portInput = $("updateModelServicePort");
  hostInput?.removeAttribute("aria-invalid");
  portInput?.removeAttribute("aria-invalid");
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
  const serviceAddress = validateServiceAddressInputs("updateModelServiceHost", "updateModelServicePort");
  updateServiceAddressPreview("updateModelServiceHost", "updateModelServicePort", "updateModelServicePreview");
  if (!serviceAddress.ok) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage(serviceAddress.message, "error");
    return false;
  }
  if (pendingUpdateModelFile && !String(pendingUpdateModelFile.name || "").toLowerCase().endsWith(".e")) {
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
  setUpdateModelMessage(showSelection ? updateModelSelectionMessage() : "");
  return true;
}

async function openUpdateModelDialog(modelId = selectedManagementModelId()) {
  const target = normalizeModels(state.models).find((model) => String(model.id || "") === String(modelId || ""));
  if (!target) {
    setModelManagementMessage("请选择要修改的模型。", "error");
    return;
  }
  let refreshedTarget = target;
  const serviceBase = String(target?.service?.base_url || "").replace(/\/$/, "");
  if (String(target?.service?.state || "") === "running" && serviceBase) {
    try {
      const response = await fetch(`${serviceBase}/api/snapshot`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const snapshot = await response.json();
      refreshedTarget = {
        ...target,
        clock_state: String(snapshot?.clock?.state || "unknown"),
      };
      state.models = normalizeModels(state.models).map((model) => (
        String(model.id || "") === String(modelId || "") ? refreshedTarget : model
      ));
    } catch (error) {
      setModelManagementMessage(`无法核实模型仿真时钟状态：${apiErrorText(error)}`, "error");
      return;
    }
  }
  if (modelClockState(refreshedTarget) !== "stopped") {
    setModelManagementMessage("模型运行中或暂停中，不能修改。", "error");
    return;
  }
  state.updateTargetModelId = String(refreshedTarget.id || "");
  pendingUpdateModelFile = null;
  pendingUpdateModelSvgFile = null;
  const dialog = $("updateModelDialog");
  if (!dialog) return;
  const fileInput = $("updateModelFileInput");
  const svgInput = $("updateModelSvgInput");
  const hostInput = $("updateModelServiceHost");
  const portInput = $("updateModelServicePort");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  $("updateModelTargetName").textContent = refreshedTarget.name || refreshedTarget.id || "--";
  renderPendingUpdateModelFiles();
  const endpoint = modelServiceEndpoint(refreshedTarget);
  if (hostInput) hostInput.value = endpoint.host;
  if (portInput) portInput.value = String(endpoint.port || "");
  updateServiceAddressPreview("updateModelServiceHost", "updateModelServicePort", "updateModelServicePreview");
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
  const file = event.currentTarget?.files?.[0] || null;
  pendingUpdateModelFile = file;
  renderPendingUpdateModelFiles();
  validateUpdateModelForm(true);
}

function handleUpdateModelSvgFileSelected(event) {
  const file = event.currentTarget?.files?.[0] || null;
  pendingUpdateModelSvgFile = file;
  renderPendingUpdateModelFiles();
  validateUpdateModelForm(true);
}

async function updateModelFromFile() {
  const file = pendingUpdateModelFile;
  const diagramFile = pendingUpdateModelSvgFile;
  const modelId = state.updateTargetModelId;
  const serviceAddress = validateServiceAddressInputs("updateModelServiceHost", "updateModelServicePort");
  if (!validateUpdateModelForm(true)) return;
  const updatedActiveModel = String(modelId || "") === String(state.activeModelId || "");
  let updateFailed = false;
  let invalidServiceAddress = false;
  setUpdateModelBusy(true);
  if (file) setUpdateModelMessage("正在保存模型定义与访问链接...");
  else if (diagramFile) setUpdateModelMessage("正在保存 SVG 图与访问链接...");
  else setUpdateModelMessage("正在保存访问链接...");
  try {
    const dataBase64 = file ? arrayBufferToBase64(await file.arrayBuffer()) : "";
    const diagramSvgBase64 = diagramFile
      ? arrayBufferToBase64(await diagramFile.arrayBuffer())
      : "";
    const payload = {
      model_id: modelId,
      service_host: serviceAddress.host,
      service_port: serviceAddress.port,
      restart_service: Boolean(file || diagramFile),
    };
    if (file) {
      payload.filename = file.name;
      payload.data_base64 = dataBase64;
    }
    if (diagramFile) {
      payload.diagram_filename = diagramFile.name;
      payload.diagram_svg_base64 = diagramSvgBase64;
    }
    const result = await api("/api/models/update-definitions", {
      modelScoped: false,
      controlPlane: true,
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (Array.isArray(result.models)) {
      state.models = normalizeModels(result.models);
    } else if (result.model) {
      const updatedModel = normalizeModels([result.model])[0];
      if (updatedModel) {
        let replaced = false;
        state.models = state.models.map((model) => {
          if (model.id !== updatedModel.id) return model;
          replaced = true;
          return updatedModel;
        });
        if (!replaced) state.models.push(updatedModel);
      }
    }
    closeUpdateModelDialog();
    state.selectedManagementModelId = modelId;
    renderModelSelector();
    renderModelManagementList();
    const serviceRestarted = result.updated?.service_restart?.restarted === true;
    setModelManagementMessage(
      file || diagramFile
        ? `模型已修改${serviceRestarted ? "，模拟服务已自动重启" : ""}。`
        : `访问链接已修改${serviceRestarted ? "，模拟服务已自动重启" : ""}。`,
      "ok",
    );
    if (updatedActiveModel && (file || diagramFile)) {
      invalidateManualDefinitionChanges();
      if (currentPageName() === "manual-changes") loadManualDefinitionChanges();
      await refresh();
    }
  } catch (error) {
    updateFailed = true;
    const message = apiErrorText(error);
    setUpdateModelMessage(`保存失败：${message}`, "error");
    if (message.includes("已分配给模型") || message.includes("不同模型不能共用同一 IP 和端口")) {
      invalidServiceAddress = true;
      const portInput = $("updateModelServicePort");
      portInput?.setAttribute("aria-invalid", "true");
    }
  } finally {
    setUpdateModelBusy(false);
    if (invalidServiceAddress) {
      const portInput = $("updateModelServicePort");
      portInput?.focus();
      portInput?.select();
    }
    if (!updateFailed && !$("updateModelDialog").hidden) validateUpdateModelForm();
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
      controlPlane: true,
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
      modelScoped: false,
      controlPlane: true,
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
  "/manual-changes": "manual-changes",
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
    if (target === "manual-changes") loadManualDefinitionChanges();
    if (state.snapshot && !hasStaticSnapshotPayload(state.snapshot, staticSnapshotKeysForPage(target))) {
      refresh();
    }
  });
}

function captureServiceSuggestion(payload) {
  const suggestion = payload?.service_suggestion;
  const host = String(suggestion?.host || "").trim();
  const port = Number(suggestion?.port);
  if (host && Number.isInteger(port) && port >= 1 && port <= 65535) {
    state.serviceSuggestion = { host, port };
  }
  return state.serviceSuggestion;
}

function modelServiceEndpoint(model) {
  const service = model?.service || {};
  const baseUrl = String(service.base_url || "").trim();
  let parsedBaseUrl = null;
  if (baseUrl) {
    try {
      parsedBaseUrl = new URL(baseUrl);
    } catch (_error) {
      parsedBaseUrl = null;
    }
  }
  const host = String(service.host || parsedBaseUrl?.hostname || "127.0.0.1").trim() || "127.0.0.1";
  const port = Number(service.port || parsedBaseUrl?.port);
  const normalizedPort = Number.isInteger(port) ? port : 0;
  const fallbackAccessLink = parsedBaseUrl?.host || (normalizedPort ? `${host}:${normalizedPort}` : host);
  return {
    host,
    port: normalizedPort,
    accessLink: String(service.access_link || fallbackAccessLink),
  };
}

function renderOverviewServiceLink(snapshot = state.snapshot) {
  const modelId = String(state.activeModelId || snapshot?.model?.id || "");
  const model = state.models.find((item) => String(item?.id || "") === modelId);
  const accessLink = model ? modelServiceEndpoint(model).accessLink : "--";
  setOverviewText("overviewServiceLink", accessLink || "--");
}

function validateServiceAddressInputs(hostInputId, portInputId) {
  const host = String($(hostInputId)?.value || "").trim();
  const port = Number($(portInputId)?.value);
  const hostPattern = /^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;
  if (
    !host
    || host.includes("://")
    || host.includes(":")
    || host.includes("/")
    || host.includes("\\")
    || host.includes("..")
    || /\s/.test(host)
    || !hostPattern.test(host)
  ) {
    return { ok: false, host, port, message: "请输入有效的 IPv4 地址或主机名，不要包含协议、端口或路径。" };
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { ok: false, host, port, message: "端口必须是 1-65535 之间的整数。" };
  }
  return { ok: true, host, port, accessLink: `${host}:${port}`, message: "" };
}

function updateServiceAddressPreview(hostInputId, portInputId, previewId) {
  const host = String($(hostInputId)?.value || "").trim() || "--";
  const port = String($(portInputId)?.value || "").trim() || "--";
  const preview = $(previewId);
  if (preview) preview.textContent = `${host}:${port}`;
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

function activeModelService() {
  const model = state.models.find((item) => item.id === state.activeModelId);
  if (model?.service) return model.service;
  return directSimulatorServiceMode
    ? {
        state: "running",
        healthy: true,
        base_url: directSimulatorServiceApiBase,
      }
    : {};
}

function activeModelServiceBase() {
  if (directSimulatorServiceMode) return directSimulatorServiceApiBase;
  return String(activeModelService().base_url || "").replace(/\/$/, "");
}

function activeModelServiceRunning() {
  if (directSimulatorServiceMode) {
    return Boolean(state.activeModelId && directSimulatorServiceApiBase);
  }
  const service = activeModelService();
  return service.state === "running" && service.healthy !== false && Boolean(service.base_url);
}

function modelServiceDependentControlsDisabled() {
  return !activeModelServiceRunning();
}

function renderModelServiceDependentControls() {
  const controlsDisabled = modelServiceDependentControlsDisabled();
  const topbar = document.querySelector(".topbar");
  if (topbar) topbar.classList.toggle("is-model-service-stopped", controlsDisabled);

  const traineeLinkButton = $("traineeLinkButton");
  if (traineeLinkButton) {
    traineeLinkButton.disabled = controlsDisabled;
    traineeLinkButton.setAttribute("aria-disabled", controlsDisabled ? "true" : "false");
    traineeLinkButton.title = controlsDisabled ? "请先启动选中模型的模拟服务" : "生成学员台交互链接";
  }

  renderCurveModeControls();
  renderClockControlAvailability();
}

function recordFrontendRequestDiagnostics(path, response, durationMs) {
  const diagnostics = state.frontendDiagnostics;
  const responseBytes = Math.max(0, Number(response?.headers?.get?.("Content-Length")) || 0);
  diagnostics.requestCount += 1;
  diagnostics.responseBytes += responseBytes;
  diagnostics.requestDurationMs += Math.max(0, Number(durationMs) || 0);
  if (/\/api\/snapshot(?:\?|$)/.test(String(path || ""))) {
    diagnostics.snapshotRequestCount += 1;
    diagnostics.snapshotResponseBytes += responseBytes;
  }
}

async function api(path, options = {}) {
  const {
    modelScoped = true,
    controlPlane = false,
    timeoutMs = frontendRequestTimeoutMs(),
    signal: callerSignal,
    ...fetchOptions
  } = options;
  if (directSimulatorServiceMode && controlPlane) {
    throw new Error("直连模拟服务界面不提供代理控制面操作");
  }
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  const requestBase = controlPlane ? controlPlaneApiBase : activeModelServiceBase();
  if (!requestBase) {
    throw new Error("选中模型的模拟服务尚未启动");
  }
  const requestStartedAtMs = performance.now();
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
    const response = await fetch(`${requestBase}${targetPath}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
    recordFrontendRequestDiagnostics(
      targetPath,
      response,
      performance.now() - requestStartedAtMs,
    );
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

function controlPlaneApi(path, options = {}) {
  return api(path, {
    ...options,
    modelScoped: false,
    controlPlane: true,
  });
}

function invalidateManualDefinitionChanges() {
  state.manualDefinitionChanges = [];
  state.manualDefinitionChangesRevision = 0;
  state.manualDefinitionChangesLoadedModelId = "";
  state.manualDefinitionChangesLoading = false;
  state.manualDefinitionChangesResetting = false;
  state.manualDefinitionChangesRetrying = false;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "";
  state.manualDefinitionChangesMessageWarning = false;
  state.manualDefinitionChangeSelection = new Set();
}

function manualDefinitionChangeValue(change, key) {
  const value = String(change?.[key] ?? "");
  if (change?.field === "valid") {
    return Number(value) === 1 ? "有效（1）" : "无效（0）";
  }
  if (change?.field === "weight") {
    const sigmaKey = key === "default_value" ? "default_error_sigma" : "current_error_sigma";
    const sigma = Number(change?.[sigmaKey]);
    return Number.isFinite(sigma) && sigma > 0
      ? `${value || "--"} / σ ${Number(sigma.toPrecision(6))}`
      : (value || "--");
  }
  return value || "--";
}

function renderManualDefinitionChanges() {
  const container = $("manualDefinitionChangesTable");
  if (!container) return;
  const changes = Array.isArray(state.manualDefinitionChanges) ? state.manualDefinitionChanges : [];
  const availableIds = new Set(changes.map((item) => String(item.id || "")));
  state.manualDefinitionChangeSelection = new Set(
    [...state.manualDefinitionChangeSelection].filter((changeId) => availableIds.has(changeId)),
  );
  const selectedCount = state.manualDefinitionChangeSelection.size;
  const pendingChanges = changes.filter((item) => !item.persisted);
  const summary = $("manualDefinitionChangesSummary");
  if (summary) summary.textContent = `${changes.length} 项修改 · ${pendingChanges.length} 项未保存 · 已选 ${selectedCount} 项`;
  const message = $("manualDefinitionChangesMessage");
  if (message) {
    const text = state.manualDefinitionChangesError || state.manualDefinitionChangesMessage || "";
    message.textContent = text;
    message.hidden = !text;
    message.classList.toggle("is-error", Boolean(state.manualDefinitionChangesError));
    message.classList.toggle(
      "is-warning",
      !state.manualDefinitionChangesError
        && (state.manualDefinitionChangesMessageWarning || pendingChanges.length > 0),
    );
  }
  const resetButton = $("resetSelectedManualChanges");
  if (resetButton) {
    resetButton.disabled = !selectedCount || state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying;
    resetButton.textContent = state.manualDefinitionChangesResetting ? "恢复中" : "恢复默认值";
  }
  const refreshButton = $("refreshManualChanges");
  if (refreshButton) {
    refreshButton.disabled = state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying;
    refreshButton.textContent = state.manualDefinitionChangesLoading ? "刷新中" : "刷新";
  }
  const retryButton = $("retryPendingManualChanges");
  if (retryButton) {
    retryButton.disabled = !pendingChanges.length || state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying;
    retryButton.textContent = state.manualDefinitionChangesRetrying ? "保存中" : "重试保存";
  }

  if (state.manualDefinitionChangesLoading && !changes.length) {
    container.innerHTML = '<div class="empty-state">正在加载人工修改记录...</div>';
    return;
  }
  if (state.manualDefinitionChangesError && !changes.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(state.manualDefinitionChangesError)}</div>`;
    return;
  }
  if (!changes.length) {
    container.innerHTML = '<div class="empty-state">当前模型没有人工修改</div>';
    return;
  }

  const allSelected = changes.every((item) => state.manualDefinitionChangeSelection.has(String(item.id || "")));
  container.innerHTML = `
    <table class="manual-definition-changes-table">
      <thead>
        <tr>
          <th class="manual-change-select-cell">
            <input
              type="checkbox"
              data-manual-change-select-all
              aria-label="选择全部人工修改"
              ${allSelected ? "checked" : ""}
            />
          </th>
          <th>对象</th>
          <th>修改类型</th>
          <th>参数 / 状态项</th>
          <th>默认值</th>
          <th>当前值</th>
          <th>修改时间</th>
          <th>保存状态</th>
        </tr>
      </thead>
      <tbody>
        ${changes.map((change) => {
          const changeId = String(change.id || "");
          const checked = state.manualDefinitionChangeSelection.has(changeId);
          const modifiedAt = String(change.modified_at || "").replace("T", " ") || "--";
          return `
            <tr class="${checked ? "is-selected" : ""}">
              <td class="manual-change-select-cell">
                <input
                  type="checkbox"
                  data-manual-change-id="${escapeHtml(changeId)}"
                  aria-label="选择 ${escapeHtml(change.object_label || change.object_name || changeId)}"
                  ${checked ? "checked" : ""}
                />
              </td>
              <td>
                <strong>${escapeHtml(change.object_label || change.object_name || "--")}</strong>
                <small>${escapeHtml(change.measurement_type || change.source_file || "")}</small>
              </td>
              <td>${escapeHtml(change.change_type || "--")}</td>
              <td><code>${escapeHtml(change.field_label || change.field || "--")}</code></td>
              <td class="manual-change-value-cell">${escapeHtml(manualDefinitionChangeValue(change, "default_value"))}</td>
              <td class="manual-change-value-cell">${escapeHtml(manualDefinitionChangeValue(change, "current_value"))}</td>
              <td>${escapeHtml(modifiedAt)}</td>
              <td>
                <span class="manual-change-persistence ${change.persisted ? "is-saved" : "is-warning"}" title="${escapeHtml(change.last_sync_error || "")}">
                  ${escapeHtml(change.persistence_status || (change.persisted ? "已保存" : "保存失败"))}
                </span>
              </td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
  const selectAll = container.querySelector("[data-manual-change-select-all]");
  if (selectAll) selectAll.indeterminate = selectedCount > 0 && !allSelected;
}

function toggleManualDefinitionChange(changeId, selected) {
  const normalizedId = String(changeId || "");
  if (!normalizedId) return;
  if (selected === undefined) {
    if (state.manualDefinitionChangeSelection.has(normalizedId)) state.manualDefinitionChangeSelection.delete(normalizedId);
    else state.manualDefinitionChangeSelection.add(normalizedId);
  } else if (selected) {
    state.manualDefinitionChangeSelection.add(normalizedId);
  } else {
    state.manualDefinitionChangeSelection.delete(normalizedId);
  }
  renderManualDefinitionChanges();
}

async function loadManualDefinitionChanges() {
  if (state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying) return;
  const requestedModelId = state.activeModelId;
  state.manualDefinitionChangesLoading = true;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "";
  state.manualDefinitionChangesMessageWarning = false;
  renderManualDefinitionChanges();
  try {
    const payload = await api("/api/definitions/manual-changes");
    if (requestedModelId !== state.activeModelId) return;
    state.manualDefinitionChanges = Array.isArray(payload.changes) ? payload.changes : [];
    state.manualDefinitionChangesRevision = Number(payload.revision) || 0;
    state.manualDefinitionChangesLoadedModelId = requestedModelId;
    state.manualDefinitionChangesMessage = `已加载 ${state.manualDefinitionChanges.length} 项人工修改`;
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesError = apiErrorText(error);
      state.manualDefinitionChangesLoadedModelId = "";
    }
  } finally {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesLoading = false;
      renderManualDefinitionChanges();
    }
  }
}

async function retryPendingManualDefinitionChanges() {
  if (state.manualDefinitionChangesRetrying) return;
  const changeIds = state.manualDefinitionChanges
    .filter((item) => !item.persisted)
    .map((item) => String(item.id || ""))
    .filter(Boolean);
  if (!changeIds.length) return;
  const requestedModelId = state.activeModelId;
  state.manualDefinitionChangesRetrying = true;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "正在重新保存人工覆盖层";
  state.manualDefinitionChangesMessageWarning = false;
  renderManualDefinitionChanges();
  try {
    const result = await api("/api/definitions/manual-changes/retry", {
      method: "POST",
      body: JSON.stringify({
        revision: state.manualDefinitionChangesRevision,
        change_ids: changeIds,
      }),
    });
    captureServiceSuggestion(result);
    if (requestedModelId !== state.activeModelId) return;
    state.manualDefinitionChanges = Array.isArray(result.changes) ? result.changes : [];
    state.manualDefinitionChangesRevision = Number(result.revision) || 0;
    state.manualDefinitionChangesLoadedModelId = requestedModelId;
    const resultWarning = definitionEditResultHasWarning(result);
    state.manualDefinitionChangesMessageWarning = resultWarning;
    state.manualDefinitionChangesMessage = result.warning
      || (resultWarning
        ? "重试保存未完整完成，请查看保存状态并重试"
        : `已重新保存 ${Number(result.persisted_count) || 0} 项人工修改`);
    if (state.snapshot) {
      state.snapshot.static_meta = {
        ...(state.snapshot.static_meta || {}),
        ...(result.static_meta || {}),
      };
      delete state.snapshot.definitions;
      delete state.snapshot.device_parameters;
    }
    refresh();
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesError = apiErrorText(error);
      state.manualDefinitionChangesLoadedModelId = "";
    }
  } finally {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesRetrying = false;
      renderManualDefinitionChanges();
    }
  }
}

async function resetSelectedManualDefinitionChanges() {
  if (state.manualDefinitionChangesResetting) return;
  const changeIds = [...state.manualDefinitionChangeSelection];
  if (!changeIds.length) return;
  if (!window.confirm(`确认将选中的 ${changeIds.length} 项人工修改恢复为默认值吗？`)) return;
  const requestedModelId = state.activeModelId;
  state.manualDefinitionChangesResetting = true;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "正在从原始 E 文件恢复默认值";
  state.manualDefinitionChangesMessageWarning = false;
  renderManualDefinitionChanges();
  try {
    const result = await api("/api/definitions/manual-changes/reset", {
      method: "POST",
      body: JSON.stringify({
        revision: state.manualDefinitionChangesRevision,
        change_ids: changeIds,
      }),
    });
    if (requestedModelId !== state.activeModelId) return;
    state.manualDefinitionChanges = Array.isArray(result.changes) ? result.changes : [];
    state.manualDefinitionChangesRevision = Number(result.revision) || 0;
    state.manualDefinitionChangesLoadedModelId = requestedModelId;
    state.manualDefinitionChangeSelection = new Set();
    const resultWarning = definitionEditResultHasWarning(result);
    state.manualDefinitionChangesMessageWarning = resultWarning;
    state.manualDefinitionChangesMessage = result.warning
      || (resultWarning
        ? "恢复默认值未完整完成，请查看保存状态并重试"
        : `已恢复 ${Number(result.reset_count) || changeIds.length} 项人工修改`);
    if (state.snapshot) {
      state.snapshot.static_meta = {
        ...(state.snapshot.static_meta || {}),
        ...(result.static_meta || {}),
      };
      delete state.snapshot.definitions;
      delete state.snapshot.device_parameters;
    }
    refresh();
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesError = apiErrorText(error);
      state.manualDefinitionChangesLoadedModelId = "";
    }
  } finally {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesResetting = false;
      renderManualDefinitionChanges();
    }
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
  "manual-changes": [],
  "runtime": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "measurements": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "logs": [],
};

const CACHEABLE_STATIC_KEYS = STATIC_SNAPSHOT_KEYS.filter((key) => key !== "curves");
let staticCacheStoreMemory = null;

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
  if (staticCacheStoreMemory) return staticCacheStoreMemory;
  try {
    const raw = localStorage.getItem(STATIC_CACHE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    staticCacheStoreMemory = parsed && typeof parsed === "object" ? parsed : {};
  } catch (_error) {
    staticCacheStoreMemory = {};
  }
  return staticCacheStoreMemory;
}

function writeStaticCacheStore(store) {
  staticCacheStoreMemory = store;
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

function staticCacheEntryMatchesSnapshot(entry, snapshot, requiredKeys) {
  if (!entry?.fields) return false;
  return requiredKeys.every((key) => (
    entry.fields[key]
    && staticMetaMatches(entry.fields[key].meta, snapshot.static_meta?.[key])
  ));
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
  if (staticCacheEntryMatchesSnapshot(entry, snapshot, requiredKeys)) return;
  const fields = { ...(entry.fields || {}) };
  let changed = false;
  requiredKeys.forEach((key) => {
    if (fields[key] && staticMetaMatches(fields[key].meta, snapshot.static_meta[key])) return;
    fields[key] = {
      meta: snapshot.static_meta[key],
      value: snapshot[key],
    };
    changed = true;
  });
  if (!changed) return;
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
  return ["overview", "diagram", "faults", "modes", "runtime"].includes(page);
}

function pageNeedsDeviceStates(page = currentPageName()) {
  return page === "diagram";
}

function pageNeedsCommands(page = currentPageName()) {
  return ["overview", "diagram", "runtime"].includes(page);
}

function pageNeedsCommandHistory(page = currentPageName()) {
  return page === "runtime";
}

const DEVICE_RUNTIME_ENCODING = "device-runtime-arrays-v1";

function deviceRuntimeIdentity(row = {}) {
  return [
    String(row.dev_type || "").trim(),
    String(row.dev_name || row.name || "").trim(),
  ];
}

function orderedDeviceRuntimeRows(rows, label) {
  if (!Array.isArray(rows)) throw new Error(`${label} is not an array`);
  const ordered = rows.filter((row) => row && typeof row === "object").slice().sort((left, right) => {
    const leftKey = deviceRuntimeIdentity(left);
    const rightKey = deviceRuntimeIdentity(right);
    if (leftKey[0] < rightKey[0]) return -1;
    if (leftKey[0] > rightKey[0]) return 1;
    if (leftKey[1] < rightKey[1]) return -1;
    if (leftKey[1] > rightKey[1]) return 1;
    return 0;
  });
  const identities = ordered.map((row) => deviceRuntimeIdentity(row));
  if (identities.some(([devType, devName]) => !devType || !devName)) {
    throw new Error(`${label} contains an empty device identity`);
  }
  const unique = new Set(identities.map(([devType, devName]) => `${devType}\u0000${devName}`));
  if (unique.size !== identities.length) throw new Error(`${label} contains duplicate device identities`);
  return ordered;
}

function deviceRuntimeOrderSignature(rows, label) {
  const encoder = new TextEncoder();
  let checksum = 0x811c9dc5;
  orderedDeviceRuntimeRows(rows, label).forEach((row) => {
    const [devType, devName] = deviceRuntimeIdentity(row);
    encoder.encode(`${devType}\u001e${devName}\u001f`).forEach((value) => {
      checksum ^= value;
      checksum = Math.imul(checksum, 0x01000193) >>> 0;
    });
  });
  return `${rows.length}:${checksum.toString(16).padStart(8, "0")}`;
}

function validatedDeviceRuntimeCount(payload, name, expected) {
  if (Number(payload?.[name]) !== expected) {
    throw new Error(`${name} mismatch: expected ${expected}, received ${payload?.[name]}`);
  }
}

function validatedDeviceRuntimeArray(payload, name, expected) {
  const values = payload?.[name];
  if (!Array.isArray(values) || values.length !== expected) {
    throw new Error(`${name} length mismatch: expected ${expected}, received ${Array.isArray(values) ? values.length : -1}`);
  }
  return values;
}

function rejectDeviceRuntimeFrame(incoming, message) {
  state.deviceRuntimeSignature = "";
  state.deviceRuntimeNeedsFullRefresh = true;
  state.deviceRuntimeWarning = message;
  console.warn(`设备运行帧已拒绝，下一周期重取完整设备数据：${message}`);
  const rejected = { ...(incoming || {}) };
  delete rejected.device_runtime;
  delete rejected.device_runtime_signature;
  return rejected;
}

function applyDeviceRuntimePayload(previous, incoming) {
  if (!incoming || typeof incoming !== "object") return incoming;
  const advertisedSignature = String(incoming.device_runtime_signature || "").trim();
  const frame = incoming.device_runtime;
  if (!advertisedSignature) {
    if (incoming.devices !== undefined || incoming.device_states !== undefined) {
      state.deviceRuntimeSignature = "";
      state.deviceRuntimeNeedsFullRefresh = false;
      state.deviceRuntimeWarning = "";
    }
    return incoming;
  }
  if (!frame || typeof frame !== "object") {
    if (state.deviceRuntimeSignature && advertisedSignature === state.deviceRuntimeSignature) return incoming;
    return rejectDeviceRuntimeFrame(incoming, "设备运行签名变化但未携带运行帧");
  }
  try {
    if (String(frame.encoding || "") !== DEVICE_RUNTIME_ENCODING) {
      throw new Error(`unsupported encoding ${frame.encoding || "--"}`);
    }
    if (String(frame.runtime_signature || "") !== advertisedSignature) {
      throw new Error("advertised runtime signature mismatch");
    }
    const baseDevices = Array.isArray(incoming.devices) ? incoming.devices : previous?.devices;
    if (!Array.isArray(baseDevices)) throw new Error("missing base device definitions");
    const deviceCount = baseDevices.length;
    const stateCount = Number(frame.state_count);
    validatedDeviceRuntimeCount(frame, "device_count", deviceCount);
    if (!Number.isInteger(stateCount) || stateCount < 0) throw new Error("invalid state_count");
    if (String(frame.device_signature || "") !== deviceRuntimeOrderSignature(baseDevices, "devices")) {
      throw new Error("device signature mismatch");
    }
    const runStats = validatedDeviceRuntimeArray(frame, "device_run_stats", deviceCount);
    const statuses = validatedDeviceRuntimeArray(frame, "device_statuses", deviceCount);
    const modes = validatedDeviceRuntimeArray(frame, "device_modes", deviceCount);
    const setValues = validatedDeviceRuntimeArray(frame, "device_set_values", deviceCount);
    const socPresent = validatedDeviceRuntimeArray(frame, "device_soc_present", deviceCount);
    const socValues = validatedDeviceRuntimeArray(frame, "device_soc_values", deviceCount);
    const stateRunStats = validatedDeviceRuntimeArray(frame, "state_run_stats", stateCount);
    const stateDeadIslands = validatedDeviceRuntimeArray(frame, "state_dead_islands", stateCount);

    const decodedDevices = baseDevices.map((row) => ({ ...row, set_values: { ...(row?.set_values || {}) } }));
    orderedDeviceRuntimeRows(decodedDevices, "devices").forEach((row, index) => {
      row.run_stat = runStats[index];
      row.status = statuses[index];
      row.mode = modes[index];
      row.set_values = setValues[index] && typeof setValues[index] === "object"
        ? { ...setValues[index] }
        : {};
      if (socPresent[index]) row.soc_curr = socValues[index];
    });

    const baseStates = Array.isArray(incoming.device_states) ? incoming.device_states : previous?.device_states;
    let decodedStates = null;
    if (Array.isArray(baseStates)) {
      validatedDeviceRuntimeCount(frame, "state_count", baseStates.length);
      if (String(frame.state_signature || "") !== deviceRuntimeOrderSignature(baseStates, "device_states")) {
        throw new Error("device state signature mismatch");
      }
      decodedStates = baseStates.map((row) => ({ ...row }));
      orderedDeviceRuntimeRows(decodedStates, "device_states").forEach((row, index) => {
        row.run_stat = stateRunStats[index];
        row.dead_island = Boolean(stateDeadIslands[index]);
      });
    }

    const applied = { ...incoming, devices: decodedDevices };
    if (decodedStates) applied.device_states = decodedStates;
    delete applied.device_runtime;
    state.deviceRuntimeSignature = advertisedSignature;
    state.deviceRuntimeNeedsFullRefresh = false;
    state.deviceRuntimeWarning = "";
    return applied;
  } catch (error) {
    return rejectDeviceRuntimeFrame(incoming, error?.message || String(error));
  }
}

function canUseCompactDeviceRuntime(page = currentPageName()) {
  if (!pageNeedsDevices(page) || state.deviceRuntimeNeedsFullRefresh) return false;
  if (!Array.isArray(state.snapshot?.devices) || !state.snapshot.devices.length) return false;
  return !pageNeedsDeviceStates(page) || Array.isArray(state.snapshot?.device_states);
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
  const compactDeviceRuntime = !Array.isArray(forceStaticKeys) && canUseCompactDeviceRuntime(page);
  params.set("logs", "0");
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("device_states", pageNeedsDeviceStates(page) ? "1" : "0");
  if (compactDeviceRuntime) {
    params.set("devices", "0");
    params.set("device_states", "0");
    params.set("device_runtime_compact", "1");
    if (state.deviceRuntimeSignature) {
      params.set("after_device_runtime_signature", state.deviceRuntimeSignature);
    }
  }
  params.set("commands", pageNeedsCommands(page) ? "1" : "0");
  if (pageNeedsCommands(page) && state.snapshot?.command_signature) {
    params.set("after_command_signature", state.snapshot.command_signature);
  }
  params.set("command_history", pageNeedsCommandHistory(page) ? "1" : "0");
  if (pageNeedsMeasurementDelta(page)) {
    params.set("measurement_after_seq", String(state.measurementDeltaSeq || 0));
    params.set("measurement_compact", "1");
  }
  if (requiredStaticKeys.length) {
    params.set("static", requiredStaticKeys.join(","));
  } else {
    params.set("lite", "1");
  }
  return `/api/snapshot?${params.toString()}`;
}

function apiUrl(path, modelScoped = true) {
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  return `${activeModelServiceBase()}${targetPath}`;
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
    .slice(0, Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit"))));
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
    const batchSize = Math.max(20, Math.round(activeRuntimeSetting("runtime_log_delta_batch_size")));
    const payload = await api(`/api/runtime-logs?after_seq=${state.runtimeLogBackendSeq}&limit=${batchSize}`);
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
    const batchSize = Math.max(20, Math.round(activeRuntimeSetting("runtime_log_history_batch_size")));
    const payload = await api(`/api/runtime-logs?before_seq=${oldestSeq}&limit=${batchSize}`);
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

function ensureMeasurementChannelRow(measurements, definitionsByName, channel, item, channelIndex) {
  if (item.deleted) {
    channelIndex.delete(item.name);
    return null;
  }
  let row = channelIndex.get(item.name);
  if (!row) {
    const definition = definitionsByName.get(item.name);
    if (!definition) return null;
    row = { ...definition };
    channelIndex.set(item.name, row);
  }
  return row;
}

function compactMeasurementDeltaItems(payload) {
  if (payload && payload.encoding === "measurement-rows-v1") {
    const simuTime = payload.simu_time ?? payload.time ?? "--";
    const wallTime = payload.wall_time ?? "--";
    return (payload.rows || []).map((row) => {
      const flags = Number(row?.[5]) || 0;
      return {
        name: String(row?.[0] || ""),
        real_value: flags & 2 ? row?.[1] : null,
        scada_value: flags & 4 ? row?.[2] : null,
        valid: row?.[3],
        weight: row?.[4],
        deleted: Boolean(flags & 1),
        updated_simu_time: simuTime,
        updated_wall_time: wallTime,
        updated_absolute_minute: payload.absolute_minute,
      };
    });
  }
  return payload?.items || [];
}

function measurementDefinitionSignature(definitions = [], definitionRevision = "") {
  const rows = Array.isArray(definitions) ? definitions : [];
  const revisionKey = String(definitionRevision ?? "");
  const cache = measurementDefinitionSignature.cache
    || (measurementDefinitionSignature.cache = new WeakMap());
  const cached = cache.get(rows);
  if (
    revisionKey
    && cached?.revisionKey === revisionKey
    && cached?.length === rows.length
  ) {
    return cached.signature;
  }
  const encoder = new TextEncoder();
  let checksum = 0x811c9dc5;
  rows.forEach((definition) => {
    const token = ["name", "dev_type", "dev_name", "meas_type"]
      .map((fieldName) => String(definition?.[fieldName] ?? ""))
      .join("\x1e") + "\x1f";
    encoder.encode(token).forEach((value) => {
      checksum ^= value;
      checksum = Math.imul(checksum, 0x01000193) >>> 0;
    });
  });
  const signature = `${rows.length}:${checksum.toString(16).padStart(8, "0")}`;
  cache.set(rows, { revisionKey, length: rows.length, signature });
  return signature;
}

function reportMeasurementArrayWarning(message) {
  const changed = state.measurementArrayWarning !== message;
  state.measurementArrayWarning = message;
  console.warn(message);
  const summary = $("measurementCompareSummary") || $("measurementSummary");
  if (summary) summary.textContent = message;
  if (changed && typeof addRuntimeLog === "function") {
    addRuntimeLog("实时量测", "量测数组帧", "整帧拒绝", message, "warn");
  }
}

function applyMeasurementArrayFrame(payload, measurements, definitions) {
  const count = Number(payload.count);
  const frame = payload.frame !== false;
  const expectedValueCount = frame ? count : 0;
  const statusValues = payload.status_values;
  const fixedValues = payload.fixed_values;
  if (
    !Number.isInteger(count)
    || count < 0
    || definitions.length !== count
    || !Array.isArray(payload.real_values)
    || payload.real_values.length !== expectedValueCount
    || !Array.isArray(payload.scada_values)
    || payload.scada_values.length !== expectedValueCount
    || !Array.isArray(payload.valid_values)
    || payload.valid_values.length !== expectedValueCount
    || (
      statusValues !== undefined
      && statusValues !== null
      && (
        !Array.isArray(statusValues)
        || statusValues.length !== expectedValueCount
      )
    )
    || (
      fixedValues !== undefined
      && fixedValues !== null
      && (
        !Array.isArray(fixedValues)
        || fixedValues.length !== expectedValueCount
      )
    )
  ) {
    reportMeasurementArrayWarning(
      `实时量测数组长度不一致，整帧已拒绝：定义=${definitions.length}，声明=${payload.count}，`
      + `真值=${payload.real_values?.length ?? "非数组"}，量测=${payload.scada_values?.length ?? "非数组"}，`
      + `状态=${payload.valid_values?.length ?? "非数组"}`,
    );
    return false;
  }
  const expectedSignature = measurementDefinitionSignature(
    definitions,
    payload.definition_revision ?? measurements.definition_revision ?? "",
  );
  const receivedSignature = String(payload.definition_signature || "");
  if (!receivedSignature) {
    reportMeasurementArrayWarning("实时量测定义顺序签名缺失，整帧已拒绝");
    return false;
  }
  if (receivedSignature !== expectedSignature) {
    reportMeasurementArrayWarning(
      `实时量测定义顺序不一致，整帧已拒绝：接收=${receivedSignature}，本地=${expectedSignature}`,
    );
    return false;
  }
  if (!frame) {
    state.measurementArrayWarning = "";
    return false;
  }

  const simuTime = payload.simu_time ?? payload.time ?? "--";
  const wallTime = payload.wall_time ?? "--";
  const absoluteMinute = payload.absolute_minute;
  const currentReal = Array.isArray(measurements.real) ? measurements.real : [];
  const currentScada = Array.isArray(measurements.scada) ? measurements.scada : [];
  const realRows = definitions.map((definition, index) => {
    const row = currentReal[index] || {};
    Object.assign(row, definition);
    row.value = payload.real_values[index];
    row.valid = payload.valid_values[index] ?? definition.valid ?? row.valid;
    row.weight = definition.weight ?? row.weight;
    row.status = statusValues?.[index] ?? definition.status ?? row.status;
    row.fixed_value = fixedValues?.[index] ?? definition.fixed_value ?? row.fixed_value;
    row.updated_simu_time = simuTime;
    row.updated_wall_time = wallTime;
    row.updated_absolute_minute = absoluteMinute;
    return row;
  });
  const scadaRows = definitions.map((definition, index) => {
    const row = currentScada[index] || {};
    Object.assign(row, definition);
    row.value = payload.scada_values[index];
    row.valid = payload.valid_values[index] ?? definition.valid ?? row.valid;
    row.weight = definition.weight ?? row.weight;
    row.status = statusValues?.[index] ?? definition.status ?? row.status;
    row.fixed_value = fixedValues?.[index] ?? definition.fixed_value ?? row.fixed_value;
    row.updated_simu_time = simuTime;
    row.updated_wall_time = wallTime;
    row.updated_absolute_minute = absoluteMinute;
    return row;
  });
  measurements.definitions = definitions;
  measurements.real = realRows;
  measurements.scada = scadaRows;
  measurements.definition_signature = expectedSignature;
  measurements.definition_revision = payload.definition_revision;
  state.measurementDeltaSeq = Math.max(Number(state.measurementDeltaSeq) || 0, Number(payload.seq) || 0);
  state.measurementArrayWarning = "";
  return true;
}

function appendMeasurementTraceAfterDelta(changed) {
  if (
    changed
    && state.snapshot
    && typeof appendMeasurementTrace === "function"
  ) {
    appendMeasurementTrace(state.snapshot);
  }
  return changed;
}

function applyMeasurementDelta(payload) {
  if (!payload || !state.snapshot) return false;
  if (payload.measurement_clock && typeof payload.measurement_clock === "object") {
    state.snapshot.measurement_clock = { ...payload.measurement_clock };
  }
  const measurements = state.snapshot.measurements || {};
  state.snapshot.measurements = measurements;
  const definitions = measurements.definitions || state.snapshot.definitions?.measurement || [];
  if (payload.encoding === "measurement-arrays-v1") {
    return appendMeasurementTraceAfterDelta(
      applyMeasurementArrayFrame(payload, measurements, definitions),
    );
  }
  if (payload.reset) {
    measurements.real = [];
    measurements.scada = [];
  }
  const definitionsByName = new Map(definitions.map((row) => [measurementNameKey(row), row]));
  const channelIndexes = {
    real: measurementChannelIndex(measurements.real || []),
    scada: measurementChannelIndex(measurements.scada || []),
  };
  let changed = false;
  compactMeasurementDeltaItems(payload).forEach((item) => {
    if (!item?.name) return;
    if (item.deleted) {
      ensureMeasurementChannelRow(measurements, definitionsByName, "real", item, channelIndexes.real);
      ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada);
      changed = true;
      return;
    }
    const realRow = item.real_value !== undefined && item.real_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "real", item, channelIndexes.real)
      : null;
    const scadaRow = item.scada_value !== undefined && item.scada_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada)
      : null;
    if (realRow) {
      realRow.value = item.real_value;
      if (item.valid !== undefined && item.valid !== null) realRow.valid = item.valid;
      if (item.weight !== undefined && item.weight !== null) realRow.weight = item.weight;
      realRow.updated_simu_time = item.updated_simu_time;
      realRow.updated_wall_time = item.updated_wall_time;
      realRow.updated_absolute_minute = item.updated_absolute_minute;
      changed = true;
    }
    if (scadaRow) {
      scadaRow.value = item.scada_value;
      if (item.valid !== undefined && item.valid !== null) scadaRow.valid = item.valid;
      if (item.weight !== undefined && item.weight !== null) scadaRow.weight = item.weight;
      scadaRow.updated_simu_time = item.updated_simu_time;
      scadaRow.updated_wall_time = item.updated_wall_time;
      scadaRow.updated_absolute_minute = item.updated_absolute_minute;
      changed = true;
    }
  });
  measurements.real = Array.from(channelIndexes.real.values());
  measurements.scada = Array.from(channelIndexes.scada.values());
  if (payload.reset) state.measurementDeltaSeq = Number(payload.seq) || 0;
  else state.measurementDeltaSeq = Math.max(Number(state.measurementDeltaSeq) || 0, Number(payload.seq) || 0);
  return appendMeasurementTraceAfterDelta(changed);
}

function applyEmbeddedMeasurementDelta(snapshot) {
  const payload = snapshot?.measurement_delta;
  state.embeddedMeasurementDeltaReceived = Boolean(payload);
  if (!payload) return false;
  delete snapshot.measurement_delta;
  state.snapshot = snapshot;
  return applyMeasurementDelta(payload);
}

async function refreshMeasurementDelta(renderNow = false) {
  if (state.measurementDeltaRequestActive || !state.snapshot) return false;
  state.measurementDeltaRequestActive = true;
  try {
    const payload = await api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}&compact=1`);
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
  state.embeddedMeasurementDeltaReceived = false;
  const incoming = applyDeviceRuntimePayload(state.snapshot, await api(snapshotPollPath(page)));
  let embeddedMeasurementDelta = incoming?.measurement_delta || null;
  if (incoming?.measurement_delta) delete incoming.measurement_delta;
  let snapshot = mergeSnapshot(state.snapshot, incoming);
  snapshot = restoreStaticSnapshotCache(snapshot, page);
  let requiredStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  if (requiredStaticKeys.length) {
    const staticIncoming = applyDeviceRuntimePayload(
      snapshot,
      await api(snapshotPollPath(page, requiredStaticKeys)),
    );
    if (staticIncoming?.measurement_delta) {
      embeddedMeasurementDelta = staticIncoming.measurement_delta;
      delete staticIncoming.measurement_delta;
    }
    snapshot = mergeSnapshot(snapshot, staticIncoming);
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    requiredStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  }
  if (!requiredStaticKeys.length) persistStaticSnapshotCache(snapshot, page);
  state.snapshot = snapshot;
  if (embeddedMeasurementDelta) {
    snapshot.measurement_delta = embeddedMeasurementDelta;
    applyEmbeddedMeasurementDelta(snapshot);
  }
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
      controlPlane: true,
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
  void modelId;
  const serviceBase = activeModelServiceBase();
  if (!serviceBase) return "";
  return `${serviceBase}/api/trainee-link`;
}

function modelServiceStateLabel(service = activeModelService()) {
  const labels = {
    running: "运行中",
    starting: "启动中",
    stopping: "停止中",
    failed: "异常",
    stopped: "已停止",
  };
  return labels[service.state] || "未知";
}

function renderModelServiceControl() {
  if (directSimulatorServiceMode) {
    renderModelServiceDependentControls();
    return;
  }
  const service = activeModelService();
  const stateElement = $("modelServiceState");
  const button = $("modelServiceToggle");
  const serviceState = service.state || "stopped";
  if (stateElement) {
    stateElement.textContent = modelServiceStateLabel(service);
    stateElement.dataset.state = serviceState;
    stateElement.title = service.error || service.base_url || "";
  }
  renderModelServiceDependentControls();
  if (!button) return;
  const running = serviceState === "running";
  button.textContent = running ? "停止" : "启动";
  button.dataset.action = running ? "stop" : "start";
  button.disabled = (
    !state.activeModelId
    || state.modelServiceOperationActive
    || serviceState === "starting"
    || serviceState === "stopping"
  );
  button.title = service.base_url
    ? `${running ? "停止" : "启动"} ${service.base_url}`
    : `${running ? "停止" : "启动"}选中模型的模拟服务`;
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
    const payload = await api("/api/trainee-link", { modelScoped: false });
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
  const modelOptionsKey = JSON.stringify(models.map((model) => [model.id, model.name || model.id]));
  if (selector.dataset.modelOptionsKey !== modelOptionsKey) {
    selector.innerHTML = models.map((model) => `
      <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
    `).join("");
    selector.dataset.modelOptionsKey = modelOptionsKey;
  }
  selector.value = state.activeModelId || models[0]?.id || "";
  selector.disabled = models.length <= 1;
  const active = models.find((model) => model.id === selector.value) || models[0] || {};
  $("activeModelName").textContent = active.name || active.id || "默认模型";
  renderOverviewServiceLink();
  renderModelServiceControl();
  if (!$("modelManagementDialog")?.hidden) renderModelManagementList();
}

async function setActiveModel(modelId, shouldRefresh = true) {
  const nextId = modelId || state.models[0]?.id || "";
  if (state.activeModelId === nextId && shouldRefresh) {
    await loadWebRuntimeSettings();
    await refresh();
    return;
  }
  cancelCurveRequests();
  state.activeModelId = nextId;
  state.selectedManagementModelId = nextId;
  state.deviceRuntimeSignature = "";
  state.deviceRuntimeNeedsFullRefresh = false;
  state.deviceRuntimeWarning = "";
  localStorage.setItem("polarSimulatorModelId", nextId);
  invalidateManualDefinitionChanges();
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
  state.systemParameters = {
    clock_speed: 1,
    compute_interval_seconds: 1,
    storage_initial_soc: 0.5,
    remote_adjustment_response_ratio: 0.7,
  };
  state.systemParametersDirty = false;
  state.systemParametersSaving = false;
  resetWebRuntimeSettingsState();
  restartRefreshScheduler();
  state.runtimeTraceHistory = [];
  resetChartPeriodOffsets("runtimeTrace");
  state.lastRuntimeTraceKey = "";
  state.measurementTraceHistory = [];
  resetChartPeriodOffsets("measurementTrace");
  state.lastMeasurementTraceKey = "";
  resetMeasurementHistoryHydration();
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
  renderModelServiceControl();
  if (activeModelServiceRunning()) {
    await loadWebRuntimeSettings();
    if (shouldRefresh) await refresh();
  } else {
    $("simState").textContent = "stopped";
    const solverInfo = $("solverInfo");
    if (solverInfo) solverInfo.textContent = "模拟服务已停止";
  }
}

async function loadModels({ preserveSelection = true } = {}) {
  if (directSimulatorServiceMode) {
    try {
      await loadDirectSimulatorServiceModel();
    } catch (error) {
      console.error("直连模拟服务模型加载失败", error);
    } finally {
      state.modelsLoaded = true;
    }
    return;
  }
  try {
    const catalog = await api("/api/models", { modelScoped: false, controlPlane: true });
    captureServiceSuggestion(catalog);
    state.models = normalizeModels(Array.isArray(catalog.models) ? catalog.models : []);
    state.serviceCatalogLastLoadedAt = Date.now();
    const preferred = (preserveSelection ? state.activeModelId : "") || catalog.active_model_id || state.models[0]?.id || "";
    const exists = state.models.some((model) => model.id === preferred);
    await setActiveModel(exists ? preferred : state.models[0]?.id || "", false);
  } catch (_error) {
    state.models = [];
    renderModelSelector();
  } finally {
    state.modelsLoaded = true;
  }
}

async function loadDirectSimulatorServiceModel() {
  state.activeModelId = "";
  try {
    const catalog = await api("/api/models", { modelScoped: false });
    const source = normalizeModels(Array.isArray(catalog.models) ? catalog.models : [])[0]
      || {
        id: String(catalog.active_model_id || "").trim(),
        name: String(catalog.active_model_id || "").trim(),
      };
    const modelId = String(source.id || catalog.active_model_id || "").trim();
    if (!modelId) throw new Error("模拟服务未返回当前模型标识");
    state.models = [{
      ...source,
      id: modelId,
      name: source.name || modelId,
      service: {
        ...(source.service || {}),
        state: "running",
        healthy: true,
        base_url: directSimulatorServiceApiBase,
      },
    }];
    state.serviceCatalogLastLoadedAt = Date.now();
    await setActiveModel(modelId, false);
  } catch (error) {
    state.models = [];
    state.activeModelId = "";
    renderModelSelector();
    throw error;
  }
}

async function refreshServiceCatalog(force = false) {
  if (directSimulatorServiceMode) return state.models;
  if (!force && Date.now() - state.serviceCatalogLastLoadedAt < 3000) return state.models;
  try {
    const catalog = await api("/api/simulator-services", {
      modelScoped: false,
      controlPlane: true,
      timeoutMs: 3000,
    });
    captureServiceSuggestion(catalog);
    state.models = normalizeModels(Array.isArray(catalog.models) ? catalog.models : []);
    state.serviceCatalogLastLoadedAt = Date.now();
    renderModelSelector();
    return state.models;
  } catch (error) {
    console.error("模拟服务目录刷新失败", error);
    return state.models;
  }
}

async function toggleActiveModelService() {
  if (directSimulatorServiceMode) return;
  if (!state.activeModelId || state.modelServiceOperationActive) return;
  const running = activeModelService().state === "running";
  const path = running ? "/api/simulator-services/stop" : "/api/simulator-services/start";
  state.modelServiceOperationActive = true;
  const activeModel = state.models.find((model) => model.id === state.activeModelId);
  if (activeModel?.service) activeModel.service.state = running ? "stopping" : "starting";
  renderModelServiceControl();
  try {
    const payload = await api(path, {
      method: "POST",
      body: JSON.stringify({ model_id: state.activeModelId }),
      modelScoped: false,
      controlPlane: true,
      timeoutMs: running ? 15000 : 45000,
    });
    state.models = normalizeModels(Array.isArray(payload.models) ? payload.models : state.models);
    state.serviceCatalogLastLoadedAt = Date.now();
    renderModelSelector();
    if (activeModelServiceRunning()) {
      resetWebRuntimeSettingsState();
      await loadWebRuntimeSettings(true);
      await refresh();
    } else {
      state.snapshot = null;
      $("simState").textContent = "stopped";
      const solverInfo = $("solverInfo");
      if (solverInfo) solverInfo.textContent = "模拟服务已停止";
    }
  } catch (error) {
    await refreshServiceCatalog(true);
    const message = apiErrorText(error);
    const stateElement = $("modelServiceState");
    if (stateElement) {
      stateElement.textContent = "操作失败";
      stateElement.dataset.state = "failed";
      stateElement.title = message;
    }
  } finally {
    state.modelServiceOperationActive = false;
    renderModelServiceControl();
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

function traceWindowRealPoints(points, range = {}, options = {}) {
  const startMinute = Number(range.startMinute);
  const defaultEndMinute = Number(range.endMinute);
  const requestedEndMinute = Number(options.endMinute);
  const endMinute = Number.isFinite(requestedEndMinute) ? requestedEndMinute : defaultEndMinute;
  if (!Number.isFinite(startMinute) || !Number.isFinite(endMinute) || endMinute < startMinute) return [];
  const includeEnd = options.includeEnd !== false;
  const source = (Array.isArray(points) ? points : [])
    .filter((point) => Number.isFinite(Number(point?.minute)))
    .slice()
    .sort((left, right) => Number(left.minute) - Number(right.minute));
  return source.filter((point) => {
    const minute = Number(point.minute);
    return minute >= startMinute && (includeEnd ? minute <= endMinute : minute < endMinute);
  });
}

function traceWindowDataPointCount(points) {
  return Array.isArray(points) ? points.length : 0;
}

const DIAGRAM_DISPLAY_PREFERENCES_KEY = "simulator.svgDisplayPreferences.v1";
const DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS = Object.freeze({
  measurements: true,
  labels: true,
  flowArrows: true,
  measurementSource: "scada",
});
const DIAGRAM_MAX_ZOOM = 8;
const DIAGRAM_PAN_THRESHOLD_PX = 5;
const DIAGRAM_FIT_PADDING_RATIO = 0.006;
const DIAGRAM_TOOLTIP_HIDE_DELAY_MS = 150;

function normalizeDiagramDisplayPreferences(value) {
  const source = value && typeof value === "object" ? value : {};
  return {
    measurements: typeof source.measurements === "boolean" ? source.measurements : true,
    labels: typeof source.labels === "boolean" ? source.labels : true,
    flowArrows: typeof source.flowArrows === "boolean" ? source.flowArrows : true,
    measurementSource: source.measurementSource === "real" ? "real" : "scada",
  };
}

function diagramDisplayPreferenceMenuItems(preferences) {
  const value = normalizeDiagramDisplayPreferences(preferences);
  const items = [
    { key: "measurements", label: value.measurements ? "不显示量测" : "显示量测" },
    { key: "labels", label: value.labels ? "不显示标识" : "显示标识" },
    { key: "flowArrows", label: value.flowArrows ? "不显示流动箭头" : "显示流动箭头" },
  ];
  if (value.measurements) {
    items.unshift({
      key: "measurementSource",
      value: value.measurementSource === "scada" ? "real" : "scada",
      label: value.measurementSource === "scada" ? "数据源: 量测" : "数据源: 真值",
    });
  }
  return items;
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

function diagramContextMenuAction(targetKind = "", insideCanvas = false) {
  return insideCanvas && !String(targetKind || "").trim() ? "open" : "ignore";
}

function diagramFloatingPosition(anchor, size, viewport, padding = 8) {
  const inset = Math.max(0, Number(padding) || 0);
  const viewportWidth = Math.max(0, Number(viewport?.width) || 0);
  const viewportHeight = Math.max(0, Number(viewport?.height) || 0);
  const width = Math.max(0, Number(size?.width) || 0);
  const height = Math.max(0, Number(size?.height) || 0);
  const anchorX = Number.isFinite(Number(anchor?.x)) ? Number(anchor.x) : inset;
  const anchorY = Number.isFinite(Number(anchor?.y)) ? Number(anchor.y) : inset;
  return {
    left: Math.max(inset, Math.min(anchorX, Math.max(inset, viewportWidth - width - inset))),
    top: Math.max(inset, Math.min(anchorY, Math.max(inset, viewportHeight - height - inset))),
  };
}

function diagramFlowArrowDirection(power, orientation = 1) {
  const value = Number(power) * (Number(orientation) < 0 ? -1 : 1);
  return value < 0 ? -1 : value > 0 ? 1 : 0;
}

function diagramFlowArrowSize(power, referencePower) {
  const reference = Math.abs(Number(referencePower));
  const magnitude = Math.abs(Number(power));
  if (!Number.isFinite(magnitude) || magnitude <= 0) return 10;
  const ratio = reference > 0 ? Math.max(0, Math.min(1, magnitude / reference)) : 1;
  return 10 + 14 * Math.sqrt(ratio);
}

function diagramFlowArrowCount(routeLength) {
  const length = Number(routeLength);
  if (!Number.isFinite(length) || length <= 0) return 2;
  return Math.max(2, Math.min(6, Math.ceil(length / 80) + 1));
}

function diagramFlowMotionAttributes(direction) {
  const reverse = Number(direction) < 0;
  return {
    keyPoints: reverse ? "1;0" : "0;1",
    rotate: reverse ? "auto-reverse" : "auto",
  };
}

const DIAGRAM_FLOW_POWER_MEASUREMENT_TYPES = Object.freeze({
  ACGENERATOR: Object.freeze(["P_GEN"]),
  DCGENERATOR: Object.freeze(["P_GEN"]),
  ACLOAD: Object.freeze(["P_LOAD"]),
  DCLOAD: Object.freeze(["P_LOAD"]),
  ACDCCONVERTER: Object.freeze(["P_AC", "P_DC"]),
  DCACCONVERTER: Object.freeze(["P_AC", "P_DC"]),
  DCDCCONVERTER: Object.freeze(["P_FROM", "P_TO"]),
  ACACCONVERTER: Object.freeze(["P_FROM", "P_TO"]),
  ACTRANSFORMER: Object.freeze(["P_FROM", "P_TO"]),
  ACBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  DCBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  ACZEROBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  DCZEROBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  ACBREAK: Object.freeze(["P_FROM", "P_TO"]),
  DCBREAK: Object.freeze(["P_FROM", "P_TO"]),
  ACSWITCH: Object.freeze(["P_FROM", "P_TO"]),
  DCSWITCH: Object.freeze(["P_FROM", "P_TO"]),
  HYDROSOURCE: Object.freeze(["FLOW"]),
  HYDROLOAD: Object.freeze(["FLOW"]),
  HYDROSTORAGE: Object.freeze(["FLOW"]),
  ACE2HYDRO: Object.freeze([]),
  DCE2HYDRO: Object.freeze([]),
  HYDRO2ACE: Object.freeze([]),
  HYDRO2DCE: Object.freeze([]),
  HYDROPIPE: Object.freeze(["FLOW"]),
  HYDROVALVE: Object.freeze(["FLOW"]),
  HYDROCOMPRESSOR: Object.freeze(["FLOW"]),
  HYDROPRESSREGULATOR: Object.freeze(["FLOW"]),
  HYDROSTOPVALVE: Object.freeze(["FLOW"]),
});

function diagramFlowPowerMeasurementTypes(devType) {
  const type = normalizeDiagramMeasurementToken(devType);
  const specific = DIAGRAM_FLOW_POWER_MEASUREMENT_TYPES[type];
  return specific ? [...specific] : diagramMetricMeasurementTypes(devType, "activePower");
}

function diagramFlowCanonicalPower(measType, value) {
  const power = Number(value);
  if (!Number.isFinite(power)) return Number.NaN;
  const type = normalizeDiagramMeasurementToken(measType);
  if (type === "P_AC" || type === "P_TO") return -power;
  return power;
}

function diagramFlowPowerRouteOrientation(device, nodes = []) {
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (["HYDRO2ACE", "HYDRO2DCE"].includes(type)) return -1;
  if (["ACE2HYDRO", "DCE2HYDRO"].includes(type)) return 1;
  if (type !== "ACDCCONVERTER" && type !== "DCACCONVERTER") return 1;
  const terminalFor = (domain) => Number((nodes || []).find((item) => {
    const nodeDomain = normalizeDiagramMeasurementToken(
      item?.domain || String(item?.key || "").split(":", 1)[0],
    );
    return nodeDomain === domain;
  })?.terminal) || 0;
  const acTerminal = terminalFor("AC");
  const dcTerminal = terminalFor("DC");
  if (acTerminal === 1 && dcTerminal === 2) return -1;
  return 1;
}

function diagramFlowInlineDeviceKind(devType, nodes = []) {
  const type = normalizeDiagramMeasurementToken(devType);
  if (type === "HYDROPIPE") return "branch";
  if ([
    "ACE2HYDRO",
    "DCE2HYDRO",
    "HYDRO2ACE",
    "HYDRO2DCE",
    "HYDROVALVE",
    "HYDROSTOPVALVE",
    "HYDROCOMPRESSOR",
    "HYDROPRESSREGULATOR",
  ].includes(type)) return "device";
  if (diagramHydrogenFlowInlineKind(type, nodes)) return "device";
  if (type.includes("BRANCH")) return "branch";
  if (
    type.includes("BREAK")
    || type.includes("SWITCH")
    || type.includes("CONVERTER")
    || type.includes("TRANSFORMER")
  ) return "device";
  return "";
}

function diagramFlowSeriesOrientation(subjectTerminal, neighborKind, neighborTerminal = 0) {
  const terminal = Number(subjectTerminal);
  if (["generator", "source", "storage"].includes(neighborKind)) return terminal === 1 ? 1 : -1;
  if (neighborKind === "load") return terminal === 2 ? 1 : -1;
  return terminal !== Number(neighborTerminal) ? 1 : -1;
}

function diagramFlowEdgeTerminalOrientation(position, terminal) {
  const terminalIndex = Number(terminal);
  if (position === "source") return terminalIndex === 2 ? 1 : -1;
  return terminalIndex === 1 ? 1 : -1;
}

function diagramFlowNodeKey(node, domain = "") {
  return `${normalizeDiagramMeasurementToken(diagramFlowDomain(domain)) || "NODE"}:${String(node || "").trim()}`;
}

function diagramFlowArrowThreshold(measType, electricThreshold, hydrogenThreshold) {
  const type = normalizeDiagramMeasurementToken(measType);
  const threshold = type === "FLOW" ? Number(hydrogenThreshold) : Number(electricThreshold);
  return Number.isFinite(threshold) ? Math.max(0, threshold) : 0;
}

function diagramFlowArrowVisibility({ power, threshold = 0, valid = true, offline = false } = {}) {
  const magnitude = Math.abs(Number(power));
  if (!valid || offline || !Number.isFinite(magnitude)) return false;
  return magnitude > Math.max(0, Number(threshold) || 0);
}

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

function diagramTrendNavigationRange(
  points,
  period = "hour",
  endMinute = null,
  requestedOffset = 0,
  simulationDurationMinutes = Number.POSITIVE_INFINITY,
) {
  let earliestHistoryMinute = Number.POSITIVE_INFINITY;
  let latestHistoryMinute = Number.NEGATIVE_INFINITY;
  (Array.isArray(points) ? points : []).forEach((point) => {
    const minute = Number(point?.minute);
    if (!Number.isFinite(minute) || !diagramTrendPointHasFiniteValue(point)) return;
    earliestHistoryMinute = Math.min(earliestHistoryMinute, minute);
    latestHistoryMinute = Math.max(latestHistoryMinute, minute);
  });
  const hasHistory = Number.isFinite(earliestHistoryMinute) && Number.isFinite(latestHistoryMinute);
  const explicitEndMinute = endMinute === null || endMinute === undefined || endMinute === ""
    ? null
    : Number(endMinute);
  const latestMinute = Number.isFinite(explicitEndMinute)
    ? explicitEndMinute
    : (hasHistory ? latestHistoryMinute : 0);
  const currentRange = diagramTrendPeriodRange(period, latestMinute);
  const normalizedSimulationDuration = Number(simulationDurationMinutes);
  const cycleStartMinute = Number.isFinite(normalizedSimulationDuration) && normalizedSimulationDuration > 0
    ? Math.floor((latestMinute + 1e-9) / normalizedSimulationDuration) * normalizedSimulationDuration
    : Number.NEGATIVE_INFINITY;
  const earliestMinute = hasHistory
    ? Math.max(earliestHistoryMinute, cycleStartMinute)
    : latestMinute;
  const periodNavigationAllowed = !Number.isFinite(normalizedSimulationDuration)
    || normalizedSimulationDuration <= 0
    || currentRange.windowMinutes < normalizedSimulationDuration;
  const minWindowOffset = periodNavigationAllowed && hasHistory
    ? Math.min(0, Math.floor((earliestMinute - currentRange.startMinute) / currentRange.windowMinutes))
    : 0;
  const normalizedOffset = periodNavigationAllowed
    ? Math.min(0, Math.trunc(Number(requestedOffset) || 0))
    : 0;
  const windowOffset = Math.max(minWindowOffset, normalizedOffset);
  const startMinute = currentRange.startMinute + windowOffset * currentRange.windowMinutes;
  return {
    ...currentRange,
    startMinute,
    endMinute: startMinute + currentRange.windowMinutes,
    currentStartMinute: currentRange.startMinute,
    earliestMinute,
    windowOffset,
    minWindowOffset,
    periodNavigationAllowed,
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

function diagramTrendPointHasFiniteValue(point) {
  return [point?.value, point?.scada, point?.real].some((value) => (
    value !== null
    && value !== undefined
    && value !== ""
    && Number.isFinite(Number(value))
  ));
}

function diagramTrendWindowPoints(points, period = "hour", endMinute = null, requestedOffset = 0, rangeOverride = null) {
  const valid = (points || []).filter((point) => (
    Number.isFinite(Number(point?.minute)) && diagramTrendPointHasFiniteValue(point)
  ));
  if (!valid.length) return [];
  const explicitEndMinute = endMinute === null || endMinute === undefined || endMinute === ""
    ? null
    : Number(endMinute);
  const latestMinute = Number.isFinite(explicitEndMinute)
    ? explicitEndMinute
    : Number(valid[valid.length - 1].minute);
  const range = rangeOverride || diagramTrendNavigationRange(valid, period, latestMinute, requestedOffset);
  const visibleLatestMinute = range.windowOffset === 0 ? range.latestMinute : range.endMinute;
  return traceWindowRealPoints(valid, range, {
    endMinute: visibleLatestMinute,
    includeEnd: visibleLatestMinute < range.endMinute,
  });
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

function diagramSvgRenderMapping(viewBox, viewportRect, preserveAspectRatio = "") {
  const viewValues = [viewBox?.x, viewBox?.y, viewBox?.width, viewBox?.height].map(Number);
  const rectValues = [viewportRect?.left, viewportRect?.top, viewportRect?.width, viewportRect?.height].map(Number);
  if (
    viewValues.some((value) => !Number.isFinite(value))
    || rectValues.some((value) => !Number.isFinite(value))
    || viewValues[2] <= 0
    || viewValues[3] <= 0
    || rectValues[2] <= 0
    || rectValues[3] <= 0
  ) return null;
  const [left, top, viewportWidth, viewportHeight] = rectValues;
  const tokens = String(preserveAspectRatio || "xMidYMid meet").trim().split(/\s+/).filter(Boolean);
  if (tokens.includes("none")) {
    return {
      left,
      top,
      scaleX: viewportWidth / viewValues[2],
      scaleY: viewportHeight / viewValues[3],
    };
  }
  const align = tokens.find((token) => /^x(?:Min|Mid|Max)Y(?:Min|Mid|Max)$/.test(token)) || "xMidYMid";
  const scale = (tokens.includes("slice") ? Math.max : Math.min)(
    viewportWidth / viewValues[2],
    viewportHeight / viewValues[3],
  );
  const spareX = viewportWidth - viewValues[2] * scale;
  const spareY = viewportHeight - viewValues[3] * scale;
  const alignX = align.startsWith("xMin") ? 0 : align.startsWith("xMax") ? spareX : spareX / 2;
  const alignY = align.endsWith("YMin") ? 0 : align.endsWith("YMax") ? spareY : spareY / 2;
  return { left: left + alignX, top: top + alignY, scaleX: scale, scaleY: scale };
}

function diagramMeasurementFitViewBox(svg, source) {
  const sourceValues = [source?.x, source?.y, source?.width, source?.height].map(Number);
  if (sourceValues.some((value) => !Number.isFinite(value)) || sourceValues[2] <= 0 || sourceValues[3] <= 0) {
    return source;
  }
  const [sourceX, sourceY, sourceWidth, sourceHeight] = sourceValues;
  const fallback = { x: sourceX, y: sourceY, width: sourceWidth, height: sourceHeight };
  if (
    typeof svg?.getBoundingClientRect !== "function"
    || typeof svg?.querySelectorAll !== "function"
  ) return fallback;
  const renderedViewBox = diagramViewBoxValue(svg.getAttribute?.("viewBox")) || fallback;
  const mapping = diagramSvgRenderMapping(
    renderedViewBox,
    svg.getBoundingClientRect(),
    svg.getAttribute?.("preserveAspectRatio") || "",
  );
  if (!mapping) return fallback;
  let minX = sourceX;
  let minY = sourceY;
  let maxX = sourceX + sourceWidth;
  let maxY = sourceY + sourceHeight;
  [...svg.querySelectorAll(".diagram-measurement-layer")].forEach((element) => {
    if (typeof element?.getBoundingClientRect !== "function") return;
    const rect = element.getBoundingClientRect();
    const values = [rect?.left, rect?.top, rect?.width, rect?.height].map(Number);
    if (values.some((value) => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) return;
    const left = renderedViewBox.x + (values[0] - mapping.left) / mapping.scaleX;
    const top = renderedViewBox.y + (values[1] - mapping.top) / mapping.scaleY;
    const right = left + values[2] / mapping.scaleX;
    const bottom = top + values[3] / mapping.scaleY;
    minX = Math.min(minX, left);
    minY = Math.min(minY, top);
    maxX = Math.max(maxX, right);
    maxY = Math.max(maxY, bottom);
  });
  const epsilon = 1e-7;
  const expandsLeft = minX < sourceX - epsilon;
  const expandsTop = minY < sourceY - epsilon;
  const expandsRight = maxX > sourceX + sourceWidth + epsilon;
  const expandsBottom = maxY > sourceY + sourceHeight + epsilon;
  if (!expandsLeft && !expandsTop && !expandsRight && !expandsBottom) return fallback;
  const padding = Math.max(
    4,
    Math.min(24, Math.max(sourceWidth, sourceHeight) * DIAGRAM_FIT_PADDING_RATIO),
  );
  const x = expandsLeft ? minX - padding : sourceX;
  const y = expandsTop ? minY - padding : sourceY;
  const right = expandsRight ? maxX + padding : sourceX + sourceWidth;
  const bottom = expandsBottom ? maxY + padding : sourceY + sourceHeight;
  return { x, y, width: right - x, height: bottom - y };
}

function fitDiagramViewport(viewport) {
  const svg = viewport?.svg;
  const source = viewport?.source || viewport?.original;
  if (!source || !svg || typeof svg.setAttribute !== "function") return false;
  const values = [source.x, source.y, source.width, source.height].map(Number);
  if (values.some((value) => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) return false;
  const original = diagramMeasurementFitViewBox(svg, {
    x: values[0],
    y: values[1],
    width: values[2],
    height: values[3],
  });
  viewport.source = { x: values[0], y: values[1], width: values[2], height: values[3] };
  viewport.original = { ...original };
  viewport.current = { ...original };
  svg.setAttribute("viewBox", `${original.x} ${original.y} ${original.width} ${original.height}`);
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
  gas_quantity: Object.freeze({ "*": ["GAS_QUANTITY"] }),
  soc: Object.freeze({ "*": ["SOC"] }),
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

function normalizeDiagramMetricType(value) {
  const metricName = String(value || "").trim().toLowerCase();
  const compactName = metricName.replace(/[\s_-]+/g, "");
  if (compactName === "soc" || compactName === "stateofcharge") return "level";
  if (compactName === "gasquantity") return "gas_quantity";
  return metricName;
}

function diagramMetricTypeFromElement(element) {
  return String(element?.getAttribute?.("mti") || element?.getAttribute?.("mt") || "").trim();
}

function diagramMetricMeasurementTypes(devType, metricType) {
  const metricName = normalizeDiagramMetricType(metricType);
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

function diagramCouplingMeasurementEndpointKey(devType, devName) {
  return [normalizeDiagramMeasurementToken(devType), String(devName || "").trim()].join("\u0000");
}

function diagramIsHydrogenConversionDevice(device) {
  return ["ACE2HYDRO", "DCE2HYDRO", "HYDRO2ACE", "HYDRO2DCE"].includes(
    normalizeDiagramMeasurementToken(device?.devType ?? device?.dev_type),
  );
}

function diagramCouplingMeasurementEndpoints(snapshot = {}) {
  const result = new Map();
  (snapshot.devices || []).forEach((device) => {
    if (!diagramIsHydrogenConversionDevice(device)) return;
    const endpoints = { electric: null, hydrogen: null };
    (Array.isArray(device?.control_bindings) ? device.control_bindings : []).forEach((binding) => {
      const target = {
        devType: String(binding?.target_dev_type || "").trim(),
        devName: String(binding?.target_dev_name || "").trim(),
      };
      const targetType = normalizeDiagramMeasurementToken(target.devType);
      if (!target.devType || !target.devName) return;
      if (["ACGENERATOR", "DCGENERATOR", "ACLOAD", "DCLOAD"].includes(targetType)) endpoints.electric = target;
      if (["HYDROSOURCE", "HYDROLOAD", "HYDROSTORAGE"].includes(targetType)) endpoints.hydrogen = target;
    });
    result.set(
      diagramCouplingMeasurementEndpointKey(device.dev_type, device.dev_name),
      endpoints,
    );
  });
  return result;
}

function diagramCouplingMeasurementEndpoint(device, maps, metricType = "", measurementTypes = null) {
  if (!diagramIsHydrogenConversionDevice(device)) return device;
  const endpoints = maps?.couplingEndpoints?.get(
    diagramCouplingMeasurementEndpointKey(device?.devType, device?.devName),
  );
  if (!endpoints) return null;
  const explicitTypes = Array.isArray(measurementTypes)
    ? measurementTypes.map(normalizeDiagramMeasurementToken)
    : [];
  const hydrogenMetric = normalizeDiagramMetricType(metricType) === "flow"
    || (explicitTypes.length > 0 && explicitTypes.every((type) => type === "FLOW"));
  return (hydrogenMetric ? endpoints.hydrogen : endpoints.electric) || device;
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
  return {
    scada,
    real,
    scadaByDevice,
    realByDevice,
    couplingEndpoints: diagramCouplingMeasurementEndpoints(snapshot),
  };
}

function diagramMetricBindingValue(binding, maps, channel = "auto") {
  const measurementDevice = diagramCouplingMeasurementEndpoint(binding, maps, binding?.metricType);
  if (!measurementDevice) return null;
  const candidates = diagramMetricMeasurementTypes(measurementDevice?.devType, binding?.metricType);
  const sources = channel === "real"
    ? [maps.realByDevice]
    : channel === "scada"
      ? [maps.scadaByDevice]
      : [maps.scadaByDevice, maps.realByDevice];
  for (const source of sources) {
    for (const measType of candidates) {
      const key = diagramDeviceMeasurementKey(measurementDevice.devType, measurementDevice.devName, measType);
      if (source?.has(key)) return source.get(key);
    }
  }
  return null;
}

function diagramDisplayRow(row, metricType = "") {
  if (!row) return row;
  if (
    normalizeDiagramMetricType(metricType) === "level"
    && normalizeDiagramMeasurementToken(row.meas_type) === "SOC"
    && Number.isFinite(Number(row.value))
  ) {
    return { ...row, value: Number(row.value) * 100 };
  }
  return row;
}

function diagramTrendDisplayValue(value, row, metricType = "") {
  if (value === null || value === undefined || value === "") return null;
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
const diagramRealtimeBindingCache = new WeakMap();
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
      devType: layerType,
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
    const metricType = diagramMetricTypeFromElement(element);
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

function diagramRealtimeBindings(container) {
  let bindings = diagramRealtimeBindingCache.get(container);
  if (!bindings) {
    const named = (attribute) => [...container.querySelectorAll(`[${attribute}]`)].map((element) => ({
      element,
      name: element.getAttribute(attribute),
    }));
    bindings = {
      measurements: named("data-meas-name"),
      scada: named("data-scada-name"),
      real: named("data-real-name"),
      controls: named("data-control-name"),
      metrics: diagramMetricBindings(container),
    };
    diagramRealtimeBindingCache.set(container, bindings);
  }
  return bindings;
}

function diagramDisplaySvg(container) {
  if (!container) return null;
  if (container.matches?.("svg.model-diagram-svg")) return container;
  return container.querySelector?.("svg.model-diagram-svg") || null;
}

function removeDiagramRuntimeLabels(container) {
  container
    ?.querySelectorAll?.(".diagram-device-label-id[data-diagram-runtime-label]")
    .forEach((element) => element.remove());
}

function prepareDiagramDisplayLayers(container) {
  const svg = diagramDisplaySvg(container);
  if (!svg) return { measurements: 0, labels: 0 };
  removeDiagramRuntimeLabels(svg);
  const measurementLayers = new Set();
  svg.querySelectorAll("[dev] [mt]").forEach((element) => {
    const owner = element.closest("[dev]");
    if (owner) measurementLayers.add(owner);
  });
  svg.querySelectorAll("[data-meas-name], [data-scada-name], [data-real-name], [data-control-name]").forEach((element) => {
    measurementLayers.add(element.closest("text") || element);
  });
  measurementLayers.forEach((element) => element.classList.add("diagram-measurement-layer"));

  let labelCount = 0;
  svg.querySelectorAll('text[id^="label_"][dev-id]').forEach((nameLabel) => {
    const devId = String(nameLabel.getAttribute("dev-id") || "").trim();
    if (!devId || !nameLabel.parentNode) return;
    nameLabel.classList.add("diagram-device-label-name");
    const idLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    ["x", "text-anchor", "transform", "dominant-baseline", "font-family", "font-weight", "font-style"].forEach((attribute) => {
      const value = nameLabel.getAttribute(attribute);
      if (value !== null && value !== "") idLabel.setAttribute(attribute, value);
    });
    const fontSize = Math.max(8, Number.parseFloat(nameLabel.getAttribute("font-size")) || 14);
    const sourceY = String(nameLabel.getAttribute("y") || "").trim();
    const numericY = Number(sourceY);
    if (sourceY && Number.isFinite(numericY)) idLabel.setAttribute("y", String(numericY + fontSize * 1.15));
    else {
      if (sourceY) idLabel.setAttribute("y", sourceY);
      idLabel.setAttribute("dy", String(fontSize * 1.15));
    }
    idLabel.setAttribute("font-size", String(Math.max(8, fontSize * 0.72)));
    idLabel.setAttribute("dev-id", devId);
    idLabel.setAttribute("data-diagram-runtime-label", "device-id");
    idLabel.setAttribute("aria-label", `设备编号 ${devId}`);
    idLabel.classList.add("diagram-device-label-id");
    idLabel.textContent = devId;
    nameLabel.parentNode.insertBefore(idLabel, nameLabel.nextSibling);
    labelCount += 1;
  });
  return { measurements: measurementLayers.size, labels: labelCount };
}

function applyDiagramDisplayPreferences(container, preferences = diagramDisplayPreferences) {
  const svg = diagramDisplaySvg(container);
  if (!svg) return null;
  const value = normalizeDiagramDisplayPreferences(preferences);
  svg.classList.toggle("is-diagram-measurements-hidden", !value.measurements);
  svg.classList.toggle("is-diagram-labels-hidden", !value.labels);
  svg.classList.toggle("is-diagram-flow-arrows-hidden", !value.flowArrows);
  svg.dataset.diagramMeasurementSource = value.measurementSource;
  return value;
}

function renderDiagramContextMenu(interaction) {
  const menu = interaction?.contextMenu;
  if (!menu) return;
  menu.innerHTML = diagramDisplayPreferenceMenuItems(diagramDisplayPreferences).map((item) => `
    <button type="button" class="diagram-context-menu-item" data-diagram-display-toggle="${item.key}"${item.value ? ` data-diagram-display-value="${item.value}"` : ""}>
      ${escapeHtml(item.label)}
    </button>`).join("");
}

function closeDiagramContextMenu(interaction) {
  if (!interaction?.contextMenu) return;
  interaction.contextMenu.hidden = true;
}

function openDiagramContextMenu(interaction, event) {
  const menu = interaction?.contextMenu;
  if (!menu) return;
  renderDiagramContextMenu(interaction);
  menu.hidden = false;
  menu.style.left = "0px";
  menu.style.top = "0px";
  const rect = menu.getBoundingClientRect();
  const position = diagramFloatingPosition(
    { x: event.clientX, y: event.clientY },
    { width: rect.width, height: rect.height },
    { width: window.innerWidth, height: window.innerHeight },
    8,
  );
  menu.style.left = `${position.left}px`;
  menu.style.top = `${position.top}px`;
}

function diagramFlowRouteD(element) {
  if (!element) return "";
  if (String(element.tagName || "").toLowerCase() === "line") {
    const values = ["x1", "y1", "x2", "y2"].map((attribute) => Number(element.getAttribute(attribute)));
    if (values.some((value) => !Number.isFinite(value))) return "";
    return `M ${values[0]} ${values[1]} L ${values[2]} ${values[3]}`;
  }
  return String(element.getAttribute?.("d") || "").trim();
}

function diagramFlowRouteLength(element) {
  try {
    const length = Number(element?.getTotalLength?.());
    return Number.isFinite(length) && length > 0 ? length : 0;
  } catch (_error) {
    return 0;
  }
}

function diagramFlowArrowColor(sourceElement) {
  const computed = typeof window !== "undefined" && typeof window.getComputedStyle === "function"
    ? window.getComputedStyle(sourceElement)
    : null;
  const values = [
    sourceElement?.getAttribute?.("stroke"),
    computed?.stroke,
    sourceElement?.getAttribute?.("color"),
    computed?.color,
  ];
  return values.find((value) => {
    const normalized = String(value || "").trim().toLowerCase();
    return normalized
      && !["none", "transparent", "currentcolor", "inherit", "initial", "unset"].includes(normalized)
      && normalized !== "rgba(0, 0, 0, 0)";
  }) || "";
}

function diagramFlowSymbol(svg, useElement) {
  const href = String(useElement?.getAttribute("href") || useElement?.getAttribute("xlink:href") || "").trim();
  if (!href.startsWith("#")) return null;
  const id = href.slice(1);
  return [...(svg?.querySelectorAll("symbol") || [])].find((symbol) => symbol.getAttribute("id") === id) || null;
}

function diagramFlowPathTransforms(path, symbol) {
  const elements = [];
  let current = path?.parentElement || null;
  while (current && current !== symbol) {
    elements.unshift(current);
    current = current.parentElement;
  }
  if (path) elements.push(path);
  return elements
    .map((element) => String(element.getAttribute?.("transform") || "").trim())
    .filter(Boolean);
}

function diagramUseRouteTransform(useElement, symbol) {
  const viewBox = diagramViewBoxValue(symbol?.getAttribute("viewBox"));
  if (!viewBox) return "";
  const x = Number(useElement.getAttribute("x")) || 0;
  const y = Number(useElement.getAttribute("y")) || 0;
  const width = Number(useElement.getAttribute("width")) || viewBox.width;
  const height = Number(useElement.getAttribute("height")) || viewBox.height;
  if (width <= 0 || height <= 0) return "";
  const preserve = String(
    useElement.getAttribute("preserveAspectRatio")
    || symbol.getAttribute("preserveAspectRatio")
    || "xMidYMid meet",
  ).trim();
  if (preserve.startsWith("none")) {
    const scaleX = width / viewBox.width;
    const scaleY = height / viewBox.height;
    return `translate(${x - viewBox.x * scaleX} ${y - viewBox.y * scaleY}) scale(${scaleX} ${scaleY})`;
  }
  const parts = preserve.split(/\s+/);
  const align = parts[0] || "xMidYMid";
  const scaleMode = parts.includes("slice") ? "slice" : "meet";
  const scaleX = width / viewBox.width;
  const scaleY = height / viewBox.height;
  const scale = scaleMode === "slice" ? Math.max(scaleX, scaleY) : Math.min(scaleX, scaleY);
  const spareX = width - viewBox.width * scale;
  const spareY = height - viewBox.height * scale;
  const alignX = align.includes("xMax") ? spareX : align.includes("xMid") ? spareX / 2 : 0;
  const alignY = align.includes("YMax") ? spareY : align.includes("YMid") ? spareY / 2 : 0;
  return `translate(${x + alignX - viewBox.x * scale} ${y + alignY - viewBox.y * scale}) scale(${scale})`;
}

function diagramFlowEndpointKind(device) {
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (type.includes("CONVERTER")) return "";
  if (type.includes("GENERATOR")) return "generator";
  if (type.includes("LOAD")) return "load";
  return "";
}

function diagramHydrogenFlowRole(devType) {
  const type = normalizeDiagramMeasurementToken(devType);
  if (["ACE2HYDRO", "DCE2HYDRO", "HYDROSOURCE"].includes(type)) return "source";
  if (["HYDRO2ACE", "HYDRO2DCE", "HYDROLOAD"].includes(type)) return "load";
  if (type === "HYDROSTORAGE") return "storage";
  return "";
}

function diagramHydrogenFlowInlineKind(devType, nodes = []) {
  const type = normalizeDiagramMeasurementToken(devType);
  if (type === "HYDROPIPE") return "branch";
  if ([
    "HYDROVALVE",
    "HYDROSTOPVALVE",
    "HYDROCOMPRESSOR",
    "HYDROPRESSREGULATOR",
  ].includes(type)) return "device";
  const hydrogenTerminals = (nodes || []).filter((node) => (
    Number(node?.terminal) > 0 && diagramFlowDomain(node?.domain) === "hydro"
  ));
  if (hydrogenTerminals.length === 2) return "device";
  return "";
}

const DIAGRAM_HYDROGEN_TERMINAL_DOMAINS = Object.freeze({
  HYDROSOURCE: Object.freeze(["hydro"]),
  HYDROLOAD: Object.freeze(["hydro"]),
  HYDROSTORAGE: Object.freeze(["hydro"]),
  HYDROBUS: Object.freeze(["hydro"]),
  HYDROPIPE: Object.freeze(["hydro", "hydro"]),
  HYDROVALVE: Object.freeze(["hydro", "hydro"]),
  HYDROSTOPVALVE: Object.freeze(["hydro", "hydro"]),
  HYDROCOMPRESSOR: Object.freeze(["hydro", "hydro"]),
  HYDROPRESSREGULATOR: Object.freeze(["hydro", "hydro"]),
  ACE2HYDRO: Object.freeze(["ac", "hydro"]),
  DCE2HYDRO: Object.freeze(["dc", "hydro"]),
  HYDRO2ACE: Object.freeze(["ac", "hydro"]),
  HYDRO2DCE: Object.freeze(["dc", "hydro"]),
});

function diagramFlowTerminalDomains(devType) {
  const domains = DIAGRAM_HYDROGEN_TERMINAL_DOMAINS[normalizeDiagramMeasurementToken(devType)];
  return domains ? [...domains] : [];
}

function diagramFlowDomain(value) {
  const type = normalizeDiagramMeasurementToken(value);
  if (["HYDRO", "HYDROGEN", "H2"].includes(type)) return "hydro";
  if (type === "AC") return "ac";
  if (type === "DC") return "dc";
  return String(value || "").trim().toLowerCase();
}

function diagramHydrogenFlowEdgeTerminal(entry, otherEntry) {
  const hydrogenNodes = (entry?.nodes || []).filter((node) => (
    diagramFlowDomain(node?.domain || String(node?.key || "").split(":", 1)[0]) === "hydro"
  ));
  return hydrogenNodes.find((node) => (
    (otherEntry?.nodes || []).some((otherNode) => otherNode.key === node.key)
  )) || null;
}

function diagramHydrogenFlowEdgeCandidate(position, entry, otherEntry, topology) {
  const terminalNode = diagramHydrogenFlowEdgeTerminal(entry, otherEntry);
  if (!terminalNode) return null;
  const role = diagramHydrogenFlowRole(entry?.device?.devType);
  if (role) {
    const orientation = role === "load"
      ? (position === "target" ? 1 : -1)
      : (position === "source" ? 1 : -1);
    return {
      entry,
      orientation,
      priority: role === "storage" ? 1 : 2,
      powerBindings: [{
        device: entry.device,
        nodes: entry.nodes || [],
        orientation: 1,
        priority: role === "storage" ? 1 : 2,
        measurementTypes: ["FLOW"],
      }],
    };
  }
  if (!diagramHydrogenFlowInlineKind(entry?.device?.devType, entry?.nodes) || Number(terminalNode.terminal) <= 0) return null;
  return {
    entry,
    orientation: diagramFlowEdgeTerminalOrientation(position, terminalNode.terminal),
    priority: 3,
    powerBindings: diagramFlowPowerBindings(entry.device, entry.element, topology),
  };
}

function diagramHydrogenFlowEdgeBinding(sourceEntry, targetEntry, topology) {
  const candidates = [
    diagramHydrogenFlowEdgeCandidate("source", sourceEntry, targetEntry, topology),
    diagramHydrogenFlowEdgeCandidate("target", targetEntry, sourceEntry, topology),
  ].filter(Boolean).sort((left, right) => right.priority - left.priority);
  if (!candidates.length) return null;
  const selected = candidates[0];
  const orientation = selected.orientation;
  const uniqueBindings = new Map();
  candidates.forEach((candidate) => {
    candidate.powerBindings.forEach((binding) => {
      const adjusted = {
        ...binding,
        orientation: (Number(binding.orientation) < 0 ? -1 : 1)
          * candidate.orientation
          * orientation,
      };
      const key = `${adjusted.device?.devId || ""}|${adjusted.orientation}|${(adjusted.measurementTypes || []).join(",")}`;
      if (!uniqueBindings.has(key)) uniqueBindings.set(key, adjusted);
    });
  });
  return {
    kind: "hydrogen",
    device: selected.entry.device,
    orientation,
    powerBindings: [...uniqueBindings.values()],
  };
}

function diagramFlowPowerAnchorKind(device, nodes = []) {
  const hydrogenRole = diagramHydrogenFlowRole(device?.devType);
  if (hydrogenRole) return hydrogenRole;
  if (diagramHydrogenFlowInlineKind(device?.devType, nodes)) return "two-terminal";
  const endpointKind = diagramFlowEndpointKind(device);
  if (endpointKind) return endpointKind;
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (type.includes("BRANCH") || type.includes("CONVERTER") || type.includes("TRANSFORMER")) {
    return "two-terminal";
  }
  return "";
}

function diagramFlowDeviceNodes(element) {
  if (!element?.getAttribute) return [];
  const node1 = String(element.getAttribute("node-1") || "").trim();
  const node2 = String(element.getAttribute("node-2") || "").trim();
  const baseDomain = String(element.getAttribute("voltage-type") || "").trim();
  const fallbackType = normalizeDiagramMeasurementToken(element.parentElement?.getAttribute?.("device-type"));
  const terminalDomains = diagramFlowTerminalDomains(fallbackType);
  const fallbackDomain = fallbackType.startsWith("AC") ? "ac" : fallbackType.startsWith("DC") ? "dc" : "";
  const domain1 = diagramFlowDomain(element.getAttribute("voltage-type-1") || terminalDomains[0] || baseDomain || fallbackDomain);
  const domain2 = diagramFlowDomain(element.getAttribute("voltage-type-2") || terminalDomains[1] || baseDomain || fallbackDomain);
  const nodes = [];
  if (node1) nodes.push({ node: node1, key: diagramFlowNodeKey(node1, domain1), terminal: 1, domain: domain1 });
  if (node2) nodes.push({ node: node2, key: diagramFlowNodeKey(node2, domain2), terminal: 2, domain: domain2 });
  if (!nodes.length) {
    const node = String(element.getAttribute("node") || "").trim();
    const domain = diagramFlowDomain(terminalDomains[0] || baseDomain || fallbackDomain);
    if (node) nodes.push({ node, key: diagramFlowNodeKey(node, domain), terminal: 0, domain });
  }
  return nodes;
}

function diagramFlowTopology(svg, container) {
  const entries = [];
  const byId = new Map();
  const byNode = new Map();
  svg?.querySelectorAll?.("g[device-type] > use[dev-id]").forEach((element) => {
    const devId = diagramElementDeviceId(element);
    const device = diagramDeviceRecord(container, devId);
    const entry = { devId, device, element, nodes: diagramFlowDeviceNodes(element) };
    entries.push(entry);
    byId.set(devId, entry);
    entry.nodes.forEach(({ key }) => {
      if (!byNode.has(key)) byNode.set(key, []);
      byNode.get(key).push(entry);
    });
  });
  return { entries, byId, byNode };
}

function diagramFlowDeviceRoute(symbol) {
  const viewBox = diagramViewBoxValue(symbol?.getAttribute?.("viewBox"));
  if (!viewBox) return null;
  const y = viewBox.y + viewBox.height / 2;
  const inset = viewBox.width * 0.08;
  const x1 = viewBox.x + inset;
  const x2 = viewBox.x + viewBox.width - inset;
  const orientationGroup = [...(symbol.children || [])].find(
    (element) => String(element.tagName || "").toLowerCase() === "g",
  );
  return {
    routeD: `M ${x1} ${y} L ${x2} ${y}`,
    routeLength: viewBox.width * 0.45,
    transforms: [String(orientationGroup?.getAttribute?.("transform") || "").trim()].filter(Boolean),
  };
}

function diagramFlowPowerBindings(device, element, topology) {
  const entry = topology?.byId?.get(String(device?.devId || ""));
  const ownNodes = entry?.nodes || diagramFlowDeviceNodes(element);
  const hydrogenInline = diagramHydrogenFlowInlineKind(device?.devType, ownNodes);
  const own = {
    device,
    nodes: ownNodes,
    orientation: diagramFlowPowerRouteOrientation(device, ownNodes),
    priority: hydrogenInline ? 3 : 1,
    ...(hydrogenInline ? { measurementTypes: ["FLOW"] } : {}),
  };
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (!type.includes("BREAK") && !type.includes("SWITCH") && !hydrogenInline) return [own];
  if (!entry) return [own];
  const fallbacks = [];
  entry.nodes.filter(({ terminal }) => terminal > 0).forEach(({ key, terminal }) => {
    (topology.byNode.get(key) || []).forEach((neighbor) => {
      if (neighbor === entry) return;
      const neighborKind = diagramFlowPowerAnchorKind(neighbor.device, neighbor.nodes);
      if (!neighborKind) return;
      const hydrogenNeighbor = Boolean(
        diagramHydrogenFlowRole(neighbor.device?.devType)
        || diagramHydrogenFlowInlineKind(neighbor.device?.devType, neighbor.nodes),
      );
      if (hydrogenInline && !hydrogenNeighbor) return;
      const neighborTerminal = neighbor.nodes.find((item) => item.key === key)?.terminal || 0;
      fallbacks.push({
        device: neighbor.device,
        nodes: neighbor.nodes,
        orientation: diagramFlowSeriesOrientation(terminal, neighborKind, neighborTerminal)
          * diagramFlowPowerRouteOrientation(neighbor.device, neighbor.nodes),
        priority: 2,
        ...(hydrogenNeighbor ? { measurementTypes: ["FLOW"] } : {}),
      });
    });
  });
  const unique = new Map();
  fallbacks.forEach((binding) => {
    const key = `${binding.device?.devId || ""}|${binding.orientation}`;
    if (!unique.has(key)) unique.set(key, binding);
  });
  return [...unique.values(), own];
}

function diagramFlowEdgeBinding(sourceEntry, targetEntry, topology) {
  const hydrogenBinding = diagramHydrogenFlowEdgeBinding(sourceEntry, targetEntry, topology);
  if (hydrogenBinding) return hydrogenBinding;
  const endpoints = [
    { position: "source", entry: sourceEntry, endpointKind: diagramFlowEndpointKind(sourceEntry?.device) },
    { position: "target", entry: targetEntry, endpointKind: diagramFlowEndpointKind(targetEntry?.device) },
  ];
  const direct = endpoints.filter((item) => item.endpointKind);
  if (direct.length === 1) {
    const selected = direct[0];
    const orientation = selected.endpointKind === "generator"
      ? (selected.position === "source" ? 1 : -1)
      : (selected.position === "target" ? 1 : -1);
    return {
      kind: "endpoint",
      device: selected.entry.device,
      orientation,
      powerBindings: diagramFlowPowerBindings(selected.entry.device, selected.entry.element, topology),
    };
  }
  if (direct.length > 1) return null;
  const connectorCandidates = endpoints.map((item) => {
    const inlineKind = diagramFlowInlineDeviceKind(item.entry?.device?.devType, item.entry?.nodes);
    const type = normalizeDiagramMeasurementToken(item.entry?.device?.devType);
    const priority = inlineKind === "branch" ? 3 : type.includes("CONVERTER") ? 2 : inlineKind ? 1 : 0;
    return { ...item, priority };
  }).filter((item) => item.priority > 0);
  if (!connectorCandidates.length) return null;
  const bestPriority = Math.max(...connectorCandidates.map((item) => item.priority));
  const best = connectorCandidates.filter((item) => item.priority === bestPriority);
  if (best.length !== 1) return null;
  const selected = best[0];
  const other = selected.position === "source" ? targetEntry : sourceEntry;
  const terminal = selected.entry.nodes.find(
    (item) => item.terminal > 0 && other?.nodes?.some((otherNode) => otherNode.key === item.key),
  )?.terminal;
  if (!terminal) return null;
  return {
    kind: "connector",
    device: selected.entry.device,
    orientation: diagramFlowEdgeTerminalOrientation(selected.position, terminal),
    powerBindings: diagramFlowPowerBindings(selected.entry.device, selected.entry.element, topology),
  };
}

function diagramFlowDevicePowerSample(device, measurementMaps, measurementTypes = null) {
  const measurementDevice = diagramCouplingMeasurementEndpoint(
    device,
    measurementMaps,
    "",
    measurementTypes,
  );
  if (!measurementDevice) return null;
  const types = Array.isArray(measurementTypes) && measurementTypes.length
    ? measurementTypes
    : diagramFlowPowerMeasurementTypes(measurementDevice?.devType);
  for (const map of [measurementMaps?.scadaByDevice, measurementMaps?.realByDevice]) {
    const candidates = types.map((measType, order) => {
      const key = diagramDeviceMeasurementKey(measurementDevice?.devType, measurementDevice?.devName, measType);
      const row = map?.get(key);
      const rawPower = Number(row?.value);
      const valid = Boolean(row) && Number(row.valid ?? 1) === 1 && Number.isFinite(rawPower);
      return valid ? {
        row,
        power: diagramFlowCanonicalPower(
          row?.meas_type || row?.measurement_type || measType,
          rawPower,
        ),
        order,
      } : null;
    }).filter(Boolean);
    if (candidates.length) {
      return candidates.reduce((best, item) => (
        Math.abs(item.power) > Math.abs(best.power) ? item : best
      ));
    }
  }
  return null;
}

function diagramFlowResolvePower(record, measurementMaps) {
  const resolved = (record?.powerBindings || [{ device: record?.device, orientation: 1, priority: 1 }])
    .map((binding) => {
      const sample = diagramFlowDevicePowerSample(
        binding.device,
        measurementMaps,
        binding.measurementTypes,
      );
      return {
        binding,
        row: sample?.row || null,
        valid: Boolean(sample) && Number.isFinite(sample.power),
        power: Number(sample?.power) * (Number(binding.orientation) < 0 ? -1 : 1),
      };
    })
    .filter((item) => item.valid);
  if (!resolved.length) return { row: null, binding: null, power: Number.NaN, valid: false };
  const priority = Math.max(...resolved.map((item) => Number(item.binding.priority) || 0));
  const candidates = resolved.filter((item) => (Number(item.binding.priority) || 0) === priority);
  const selected = candidates.reduce((best, item) => (
    Math.abs(item.power) > Math.abs(best.power) ? item : best
  ));
  return { ...selected, valid: true };
}

function diagramFlowDeviceBlocksFlow(device, deviceState, measurementMaps) {
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (!["HYDROVALVE", "HYDROSTOPVALVE"].includes(type)) return false;
  const status = diagramSwitchMeasurementRow(device, measurementMaps)?.value ?? deviceState?.status;
  return diagramSwitchState(status) === "open";
}

function createDiagramFlowArrow(sourceElement, routeD, transforms = [], routeLength = 0) {
  if (!sourceElement?.parentNode || !routeD) return null;
  const createSvgElement = (tagName) => document.createElementNS("http://www.w3.org/2000/svg", tagName);
  const root = createSvgElement("g");
  root.classList.add("diagram-flow-arrow");
  root.setAttribute("data-diagram-runtime-flow", "true");
  root.setAttribute("hidden", "");
  const color = diagramFlowArrowColor(sourceElement);
  if (color) root.style.setProperty("--diagram-flow-color", color);
  let parent = root;
  transforms.filter(Boolean).forEach((transform) => {
    const group = createSvgElement("g");
    group.setAttribute("transform", transform);
    parent.appendChild(group);
    parent = group;
  });
  const guide = createSvgElement("path");
  guide.classList.add("diagram-flow-guide");
  guide.setAttribute("d", routeD);
  guide.setAttribute("fill", "none");
  parent.appendChild(guide);
  const markerCount = diagramFlowArrowCount(routeLength);
  const durationSeconds = 1.8;
  const markers = Array.from({ length: markerCount }, (_value, index) => {
    const marker = createSvgElement("g");
    marker.classList.add("diagram-flow-arrow-marker");
    marker.setAttribute("data-flow-marker-index", String(index));
    const polygon = createSvgElement("polygon");
    polygon.setAttribute("points", "-5,-3 5,0 -5,3");
    const animation = createSvgElement("animateMotion");
    animation.setAttribute("path", routeD);
    animation.setAttribute("dur", `${durationSeconds}s`);
    animation.setAttribute("begin", `${-(durationSeconds * index / markerCount).toFixed(3)}s`);
    animation.setAttribute("repeatCount", "indefinite");
    animation.setAttribute("calcMode", "linear");
    animation.setAttribute("keyTimes", "0;1");
    animation.setAttribute("keyPoints", "0;1");
    animation.setAttribute("rotate", "auto");
    marker.appendChild(polygon);
    marker.appendChild(animation);
    parent.appendChild(marker);
    return { marker, polygon, animation };
  });
  sourceElement.parentNode.insertBefore(root, sourceElement.nextSibling);
  return { root, guide, markers, direction: 0 };
}

function removeDiagramFlowArrows(container) {
  container?.querySelectorAll?.('.diagram-flow-arrow[data-diagram-runtime-flow]').forEach((element) => element.remove());
  const interaction = container ? diagramInteractionCache.get(container) : null;
  if (interaction) {
    interaction.flowArrows = [];
    interaction.flowArrowPeakReferences = new Map();
  }
}

function compileDiagramFlowArrows(container) {
  const svg = diagramDisplaySvg(container);
  const interaction = diagramInteractionState(container);
  removeDiagramFlowArrows(container);
  interaction.flowArrows = [];
  interaction.flowArrowPeakReferences = new Map();
  if (!svg) return interaction.flowArrows;
  const topology = diagramFlowTopology(svg, container);

  topology.entries.forEach(({ device, element: useElement, nodes }) => {
    const inlineKind = diagramFlowInlineDeviceKind(device?.devType, nodes);
    if (!inlineKind) return;
    const symbol = diagramFlowSymbol(svg, useElement);
    if (!symbol) return;
    const baseTransforms = [
      String(useElement.getAttribute("transform") || "").trim(),
      diagramUseRouteTransform(useElement, symbol),
    ].filter(Boolean);
    const powerBindings = diagramFlowPowerBindings(device, useElement, topology);
    if (inlineKind === "branch") {
      const routePath = symbol.querySelector(".routable-line-device-glyph path[d]");
      const routeD = diagramFlowRouteD(routePath);
      if (!routePath || !routeD) return;
      const transforms = [...baseTransforms, ...diagramFlowPathTransforms(routePath, symbol)];
      const arrow = createDiagramFlowArrow(useElement, routeD, transforms, diagramFlowRouteLength(routePath));
      if (!arrow) return;
      arrow.root.setAttribute("data-flow-source-id", String(device?.devId || ""));
      interaction.flowArrows.push({
        ...arrow,
        kind: "branch",
        device,
        pathDevices: [device],
        powerBindings,
        orientation: 1,
      });
      return;
    }
    const route = diagramFlowDeviceRoute(symbol);
    if (!route?.routeD) return;
    const arrow = createDiagramFlowArrow(
      useElement,
      route.routeD,
      [...baseTransforms, ...(route.transforms || [])],
      route.routeLength,
    );
    if (!arrow) return;
    arrow.root.setAttribute("data-flow-source-id", String(device?.devId || ""));
    interaction.flowArrows.push({
      ...arrow,
      kind: "device",
      device,
      pathDevices: [device],
      powerBindings,
      orientation: 1,
    });
  });

  svg.querySelectorAll("path[source-dev-id][target-dev-id], line[source-dev-id][target-dev-id]").forEach((edge) => {
    if (edge.closest("defs, symbol, marker, pattern, clipPath, mask") || edge.hasAttribute("data-diagram-runtime-flow")) return;
    const sourceEntry = topology.byId.get(String(edge.getAttribute("source-dev-id") || ""));
    const targetEntry = topology.byId.get(String(edge.getAttribute("target-dev-id") || ""));
    const binding = diagramFlowEdgeBinding(sourceEntry, targetEntry, topology);
    if (!binding) return;
    const routeD = diagramFlowRouteD(edge);
    if (!routeD) return;
    const transforms = [String(edge.getAttribute("transform") || "").trim()].filter(Boolean);
    const arrow = createDiagramFlowArrow(edge, routeD, transforms, diagramFlowRouteLength(edge));
    if (arrow) {
      arrow.root.setAttribute("data-flow-source-id", String(binding.device?.devId || ""));
      interaction.flowArrows.push({
        ...arrow,
        kind: binding.kind,
        device: binding.device,
        pathDevices: [sourceEntry?.device, targetEntry?.device].filter(Boolean),
        powerBindings: binding.powerBindings,
        orientation: binding.orientation,
      });
    }
  });
  return interaction.flowArrows;
}

function diagramFlowReferencePower(container, device, snapshot, interaction, power) {
  const raw = diagramDeviceData(container, device, snapshot).raw || {};
  const capacities = new Map(Object.entries(raw).map(([key, value]) => [
    String(key).trim().toLowerCase(),
    Number(value),
  ]));
  for (const key of ["flow_max", "rated_capacity", "rated_power", "p_max", "max_power", "max_charge_power", "max_discharge_power"]) {
    const value = Math.abs(Number(capacities.get(key)));
    if (Number.isFinite(value) && value > 0) return value;
  }
  const peakKey = normalizeDiagramMeasurementToken(device?.devType) || String(device?.devId || "unknown");
  const magnitude = Math.abs(Number(power));
  const previous = Number(interaction?.flowArrowPeakReferences?.get(peakKey)) || 0;
  const peak = Math.max(previous, Number.isFinite(magnitude) ? magnitude : 0);
  interaction?.flowArrowPeakReferences?.set(peakKey, peak);
  return peak > 0 ? peak : 1;
}

function updateDiagramFlowArrows(container, snapshot = state.snapshot || {}, measurementMaps = diagramMeasurementMaps(snapshot)) {
  const interaction = container ? diagramInteractionCache.get(container) : null;
  if (!interaction?.flowArrows?.length) return;
  const operatingMaps = diagramDeviceOperatingStateMaps(snapshot);
  interaction.flowArrows.forEach((record) => {
    const resolved = diagramFlowResolvePower(record, measurementMaps);
    const power = Number(resolved.power);
    const valid = Boolean(resolved.valid) && Number.isFinite(power);
    const relevantDevices = [
      record.device,
      resolved.binding?.device,
      ...(record.pathDevices || []),
    ].filter(Boolean);
    const offline = relevantDevices.some((device) => (
      diagramDeviceIsOffline(diagramDeviceOperatingState(device, operatingMaps))
      || diagramFlowDeviceBlocksFlow(
        device,
        diagramDeviceOperatingState(device, operatingMaps),
        measurementMaps,
      )
    ));
    const referenceDevice = resolved.binding?.device || record.device;
    const referencePower = diagramFlowReferencePower(container, referenceDevice, snapshot, interaction, power);
    const threshold = diagramFlowArrowThreshold(
      resolved.row?.meas_type || resolved.row?.measurement_type,
      activeRuntimeSetting("diagram_flow_electric_threshold_kw"),
      activeRuntimeSetting("diagram_flow_hydrogen_threshold_nm3_h"),
    );
    const visible = diagramFlowArrowVisibility({ power, threshold, valid, offline });
    record.root.setAttribute("data-flow-power", valid ? String(power) : "");
    record.root.setAttribute("data-flow-binding-id", String(resolved.binding?.device?.devId || ""));
    record.root.setAttribute(
      "data-flow-measurement-type",
      String(resolved.row?.meas_type || resolved.row?.measurement_type || ""),
    );
    record.root.toggleAttribute("hidden", !visible);
    if (!visible) return;
    const size = diagramFlowArrowSize(power, referencePower);
    const halfLength = size / 2;
    const halfHeight = Math.max(2, size * 0.32);
    record.markers.forEach(({ polygon }) => {
      polygon.setAttribute(
        "points",
        `${-halfLength},${-halfHeight} ${halfLength},0 ${-halfLength},${halfHeight}`,
      );
    });
    const direction = diagramFlowArrowDirection(power, record.orientation);
    if (direction !== record.direction) {
      record.direction = direction;
      const motion = diagramFlowMotionAttributes(direction);
      record.markers.forEach(({ animation }) => {
        animation.setAttribute("keyPoints", motion.keyPoints);
        animation.setAttribute("rotate", motion.rotate);
      });
    }
    record.root.setAttribute("data-flow-direction", direction < 0 ? "reverse" : "forward");
  });
}

function diagramInteractionState(container) {
  let interaction = diagramInteractionCache.get(container);
  if (!interaction) {
    interaction = {
      container,
      initialized: false,
      selectedDevId: "",
      hover: null,
      snapshot: null,
      tooltip: null,
      tooltipPositionKey: "",
      trendPeriod: "hour",
      trendPeriodOffsets: { hour: 0, day: 0 },
      trendNavigationRange: null,
      trendChart: null,
      trendCursorClientX: null,
      contextMenu: null,
      flowArrows: [],
      flowArrowPeakReferences: new Map(),
      pointer: { x: 0, y: 0 },
      hideTimer: null,
      definitionEditor: null,
      definitionSaving: false,
      definitionLeavePrompt: false,
      definitionCloseAfterSave: false,
      definitionMessage: "",
      definitionMessageWarning: false,
      deviceTooltipHostKey: "",
      deviceTooltipTabKey: "self",
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
    devType: "",
    devName: key,
  };
}

const DIAGRAM_DEVICE_ELEMENT_SELECTOR = "[dev-id], use[id][name]";

function diagramElementDeviceId(element) {
  if (!element || typeof element.getAttribute !== "function") return "";
  const explicit = element.getAttribute("dev-id") || element.getAttribute("dev");
  if (explicit) return String(explicit).trim();
  if (String(element.tagName || "").toLowerCase() !== "use" || !element.getAttribute("name")) return "";
  return String(element.getAttribute("id") || "").trim();
}

function diagramMetricElementForTarget(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return null;
  const directMetric = target.closest("[mt]");
  if (directMetric && container.contains(directMetric)) return directMetric;
  const owner = target.closest("[dev]");
  const row = target.closest("text");
  if (!owner || !row || !container.contains(owner) || !owner.contains(row)) return null;
  const rowMetric = row.querySelector("[mt]");
  return rowMetric && container.contains(rowMetric) ? rowMetric : null;
}

function diagramTargetDeviceId(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return "";
  const metricElement = diagramMetricElementForTarget(container, target);
  if (metricElement) {
    const owner = metricElement.closest("[dev]");
    if (owner && container.contains(owner)) return String(owner.getAttribute("dev") || "").trim();
  }
  const deviceElement = target.closest(DIAGRAM_DEVICE_ELEMENT_SELECTOR);
  if (!deviceElement || !container.contains(deviceElement)) return "";
  return diagramElementDeviceId(deviceElement);
}

function diagramHoverTarget(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return null;
  const metricElement = diagramMetricElementForTarget(container, target);
  if (metricElement) {
    const owner = metricElement.closest("[dev]");
    const devId = String(owner?.getAttribute("dev") || "").trim();
    const metricType = String(
      metricElement.getAttribute("mti") || metricElement.getAttribute("mt") || "",
    ).trim();
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
  if (type === "PRESSURE") return "MPa";
  if (type === "FLOW") return "Nm3/h";
  if (type === "GAS_QUANTITY") return "Nm3";
  if (type.startsWith("P")) return "kW";
  if (type.startsWith("Q")) return "kvar";
  if (type.startsWith("V")) return "V";
  if (type.startsWith("I")) return "A";
  if (type.includes("FREQ")) return "Hz";
  if (type.includes("TEMP")) return "℃";
  return "";
}

function diagramTooltipRowKey(sectionKey, label, index = 0) {
  return `${String(sectionKey || "section")}:${String(label || index)}`;
}

function diagramIntegratedDefinitionBindingMatchesEditor(binding, interaction) {
  return Boolean(diagramDeviceDefinitionRecordEditor(
    interaction?.definitionEditor,
    binding,
  ));
}

function renderDiagramIntegratedDefinitionRow(label, value, rowKey, binding, interaction) {
  const fieldEditable = Boolean(binding?.editable);
  const activeEditor = diagramDeviceDefinitionRecordEditor(
    interaction?.definitionEditor,
    binding,
  );
  const editing = Boolean(activeEditor && fieldEditable);
  const recordAttributes = binding
    ? ` data-diagram-definition-block="${escapeHtml(binding.blockName)}" data-diagram-definition-row-index="${binding.rowIndex}"`
    : "";
  if (!editing) {
    return `
      <div class="diagram-tooltip-row${fieldEditable ? " is-editable" : ""}" data-diagram-tooltip-row="${escapeHtml(rowKey)}"${recordAttributes}>
        <dt>${escapeHtml(label)}</dt>
        <dd
          data-diagram-tooltip-value="${escapeHtml(rowKey)}"
          ${fieldEditable ? 'data-diagram-definition-editable="device"' : ""}
        >${escapeHtml(diagramDefinitionDisplayValue(binding?.field, value))}</dd>
      </div>`;
  }
  const enumOptions = diagramDefinitionEnumOptions(
    { ...binding, row: activeEditor.draft },
    binding.field,
  );
  if (enumOptions.length) {
    return `
      <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(rowKey)}"${recordAttributes}>
        <dt>${escapeHtml(label)}</dt>
        <dd data-diagram-tooltip-value="${escapeHtml(rowKey)}">
          ${renderDiagramDefinitionEnumSelect(
            { ...binding, row: activeEditor.draft },
            binding.field,
            activeEditor.draft[binding.field],
            interaction,
          )}
        </dd>
      </div>`;
  }
  const descriptor = diagramDefinitionInputDescriptor(binding.field, activeEditor.draft[binding.field]);
  return `
    <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(rowKey)}"${recordAttributes}>
      <dt>${escapeHtml(label)}</dt>
      <dd data-diagram-tooltip-value="${escapeHtml(rowKey)}">
        <span class="diagram-definition-input-wrap">
          <input
            class="diagram-definition-input"
            data-diagram-tooltip-inline-input
            data-diagram-definition-input="device"
            data-diagram-definition-field="${escapeHtml(binding.field)}"
            type="${descriptor.type}"
            ${descriptor.type === "number" ? 'step="any"' : ""}
            ${descriptor.min !== "" ? `min="${descriptor.min}"` : ""}
            ${descriptor.max !== "" ? `max="${descriptor.max}"` : ""}
            value="${escapeHtml(descriptor.value)}"
            ${interaction?.definitionSaving ? "disabled" : ""}
          >
          ${descriptor.suffix ? `<small>${escapeHtml(descriptor.suffix)}</small>` : ""}
        </span>
      </dd>
    </div>`;
}

function diagramTooltipRows(rows = [], sectionKey = "", interaction = null) {
  const content = rows
    .filter((row) => row && row[0])
    .map(([label, value, key, binding], index) => {
      const rowKey = String(key || diagramTooltipRowKey(sectionKey, label, index));
      if (binding) {
        return renderDiagramIntegratedDefinitionRow(label, value, rowKey, binding, interaction);
      }
      return `
      <div class="diagram-tooltip-row" data-diagram-tooltip-row="${escapeHtml(rowKey)}">
        <dt>${escapeHtml(label)}</dt>
        <dd data-diagram-tooltip-value="${escapeHtml(rowKey)}">${escapeHtml(diagramTooltipValue(value))}</dd>
      </div>`;
    })
    .join("");
  return content ? `<dl class="diagram-tooltip-grid">${content}</dl>` : "";
}

const DIAGRAM_DEFINITION_PROTECTED_FIELDS = new Set([
  "idx", "name", "dev_name", "dev_type", "path",
  "node", "i_node", "j_node", "ac_node", "dc_node",
  "isl",
]);

const DIAGRAM_DEFINITION_IDENTITY_FIELDS = new Set([
  "idx", "name", "dev_name", "dev_type",
]);
const DIAGRAM_REALTIME_MEASUREMENT_FIELDS = new Set(["p", "q", "u", "i", "f"]);

function diagramDefinitionDisplayHeaders(record) {
  const integratedFields = record?.integratedFields instanceof Set
    ? record.integratedFields
    : new Set(record?.integratedFields || []);
  return (record?.headers || []).filter((field) => {
    const name = String(field || "").trim().toLowerCase();
    return !DIAGRAM_DEFINITION_IDENTITY_FIELDS.has(name)
      && !integratedFields.has(name)
      && !DIAGRAM_REALTIME_MEASUREMENT_FIELDS.has(name);
  });
}

function diagramDefinitionFieldBinding(records, fieldNames = []) {
  const candidates = new Set(fieldNames.map((field) => String(field || "").trim().toLowerCase()));
  for (const record of records || []) {
    const field = (record.headers || []).find((header) => (
      candidates.has(String(header || "").trim().toLowerCase())
    ));
    if (!field) continue;
    if (!(record.integratedFields instanceof Set)) record.integratedFields = new Set();
    record.integratedFields.add(String(field).trim().toLowerCase());
    return {
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      field,
      editable: diagramDeviceParameterEditable(field),
    };
  }
  return null;
}

const DIAGRAM_LINKED_DEFINITION_BLOCKS = Object.freeze({
  ACGENERATOR: [
    { blockName: "ACWindGen", referenceField: "idx_acgenerator" },
    { blockName: "ACPVGen", referenceField: "idx_acgenerator" },
    { blockName: "ACStorageGen", referenceField: "idx_acgenerator" },
  ],
  DCGENERATOR: [
    { blockName: "DCWindGen", referenceField: "idx_dcgenerator" },
    { blockName: "DCPVGen", referenceField: "idx_dcgenerator" },
    { blockName: "DCStorageGen", referenceField: "idx_dcgenerator" },
  ],
});

function diagramDeviceParameterEditable(field) {
  const name = String(field || "").trim().toLowerCase();
  return Boolean(name)
    && !DIAGRAM_DEFINITION_PROTECTED_FIELDS.has(name)
    && !DIAGRAM_REALTIME_MEASUREMENT_FIELDS.has(name)
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

const DIAGRAM_MEASUREMENT_STATUS_LABELS = Object.freeze({
  valid: "有效",
  invalid: "无效",
  undefined: "无定义",
  dead: "死数",
  zero: "零值",
  fixed: "固定值",
});

function diagramMeasurementStatus(value, valid = 1) {
  const status = String(value || "").trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(DIAGRAM_MEASUREMENT_STATUS_LABELS, status)) return status;
  return Number(valid) === 1 ? "valid" : "invalid";
}

function diagramMeasurementStatusLabel(value, valid = 1) {
  return DIAGRAM_MEASUREMENT_STATUS_LABELS[diagramMeasurementStatus(value, valid)] || "无效";
}

function diagramDefinitionEditorMessageHtml(interaction, validationError = "") {
  const validation = String(validationError || "").trim();
  const message = validation || String(interaction?.definitionMessage || "").trim();
  const warning = Boolean(validation || interaction?.definitionMessageWarning);
  return `<div class="diagram-definition-message${warning ? " is-warning" : " is-success"}" data-diagram-definition-message${message ? "" : " hidden"}>${escapeHtml(message)}</div>`;
}

function diagramDefinitionRecord(blockName, block, row, rowIndex) {
  const headers = Array.isArray(block?.headers) ? [...block.headers] : Object.keys(row || {});
  const recordRow = Object.fromEntries(headers.map((header) => [header, row?.[header] ?? ""]));
  return {
    blockName,
    headers,
    row: recordRow,
    rowIndex,
    rowKey: {
      idx: recordRow.idx ?? "",
      name: recordRow.name ?? "",
    },
    editableFields: headers.filter((field) => diagramDeviceParameterEditable(field)),
  };
}

function diagramDeviceDefinitionRecords(device, snapshot = state.snapshot || {}) {
  if (!device) return [];
  const blocks = snapshot?.definitions?.model || {};
  const deviceType = normalizeDiagramMeasurementToken(device.devType);
  const primaryEntry = Object.entries(blocks).find(([blockName]) => (
    normalizeDiagramMeasurementToken(blockName) === deviceType
  ));
  if (!primaryEntry) return [];
  const [primaryBlockName, primaryBlock] = primaryEntry;
  const primaryRows = Array.isArray(primaryBlock?.rows) ? primaryBlock.rows : [];
  const deviceName = String(device.devName || "");
  const primaryIndex = primaryRows.findIndex((row, rowIndex) => {
    const rowName = String(row?.name ?? row?.dev_name ?? "");
    if (rowName) return rowName === deviceName;
    const idx = String(row?.idx ?? rowIndex + 1);
    return deviceName === `${primaryBlockName}_${idx}`
      || String(device.devId || "") === `${primaryBlockName}-${idx}`;
  });
  if (primaryIndex < 0) return [];
  const primaryRecord = diagramDefinitionRecord(
    primaryBlockName,
    primaryBlock,
    primaryRows[primaryIndex],
    primaryIndex,
  );
  const primaryIdx = String(primaryRecord.row.idx ?? "");
  if (!primaryIdx) return [primaryRecord];

  const configuredLinks = DIAGRAM_LINKED_DEFINITION_BLOCKS[deviceType] || [];
  const configuredByBlock = new Map(configuredLinks.map((item) => [item.blockName, item.referenceField]));
  const expectedReference = `idx_${String(primaryBlockName || "").toLowerCase()}`;
  const linkedRecords = [];
  Object.entries(blocks).forEach(([blockName, block]) => {
    if (blockName === primaryBlockName) return;
    const headers = Array.isArray(block?.headers) ? block.headers : [];
    const configuredReference = configuredByBlock.get(blockName);
    const referenceField = configuredReference && headers.includes(configuredReference)
      ? configuredReference
      : headers.find((field) => String(field || "").toLowerCase() === expectedReference);
    if (!referenceField) return;
    (block.rows || []).forEach((row, rowIndex) => {
      if (String(row?.[referenceField] ?? "") !== primaryIdx) return;
      linkedRecords.push(diagramDefinitionRecord(blockName, block, row, rowIndex));
    });
  });
  return [primaryRecord, ...linkedRecords];
}

function diagramMetricMeasurementRows(snapshot = state.snapshot || {}) {
  const measurements = snapshot?.measurements || {};
  return {
    definitions: snapshot?.definitions?.measurement || measurements.definitions || [],
    scada: measurements.scada || [],
    real: measurements.real || [],
  };
}

function diagramMeasurementIdentityMatches(row, identity) {
  if (!row || !identity) return false;
  if (identity.name) return String(row.name || "") === String(identity.name);
  return normalizeDiagramMeasurementToken(row.dev_type) === normalizeDiagramMeasurementToken(identity.devType)
    && String(row.dev_name || "") === String(identity.devName || "")
    && normalizeDiagramMeasurementToken(row.meas_type) === normalizeDiagramMeasurementToken(identity.measType);
}

function diagramMeasurementFiniteValue(row) {
  if (!row || row.value === null || row.value === undefined || row.value === "") return null;
  const value = Number(row.value);
  return Number.isFinite(value) ? value : null;
}

function diagramMetricMeasurementPair(hover, snapshot = state.snapshot || {}) {
  const rows = diagramMetricMeasurementRows(snapshot);
  let identity = null;
  if (hover?.name) {
    identity = { name: hover.name };
  } else if (hover?.binding) {
    const candidates = diagramMetricMeasurementTypes(
      hover.binding.devType,
      hover.binding.metricType,
    );
    const measType = candidates.find((candidate) => {
      const candidateIdentity = {
        devType: hover.binding.devType,
        devName: hover.binding.devName,
        measType: candidate,
      };
      return [...rows.scada, ...rows.real, ...rows.definitions]
        .some((row) => diagramMeasurementIdentityMatches(row, candidateIdentity));
    }) || candidates[0] || hover.binding.metricType;
    identity = {
      devType: hover.binding.devType,
      devName: hover.binding.devName,
      measType,
    };
  }
  const scadaRow = rows.scada.find((row) => diagramMeasurementIdentityMatches(row, identity)) || null;
  const realRow = rows.real.find((row) => diagramMeasurementIdentityMatches(row, identity)) || null;
  const channelRow = scadaRow || realRow;
  if (identity?.name && channelRow) {
    identity = {
      name: identity.name,
      devType: channelRow.dev_type,
      devName: channelRow.dev_name,
      measType: channelRow.meas_type,
    };
  }
  const definition = rows.definitions.find((row) => (
    identity?.name
      ? String(row.name || "") === String(identity.name)
      : diagramMeasurementIdentityMatches(row, identity)
  )) || null;
  const scadaValue = diagramMeasurementFiniteValue(scadaRow);
  const realValue = diagramMeasurementFiniteValue(realRow);
  const weightNumber = Number(definition?.weight ?? channelRow?.weight);
  const validNumber = Number(definition?.valid ?? channelRow?.valid ?? 1);
  const weight = Number.isFinite(weightNumber) ? weightNumber : null;
  const status = diagramMeasurementStatus(
    definition?.status ?? channelRow?.status,
    validNumber,
  );
  const fixedValueNumber = Number(definition?.fixed_value ?? channelRow?.fixed_value);
  const medianDeviationNumber = Number(definition?.median_deviation ?? channelRow?.median_deviation ?? 0);
  return {
    definition,
    scadaRow,
    realRow,
    row: scadaRow || realRow || definition,
    name: String(definition?.name || channelRow?.name || identity?.name || ""),
    devType: String(definition?.dev_type || channelRow?.dev_type || identity?.devType || ""),
    devName: String(definition?.dev_name || channelRow?.dev_name || identity?.devName || ""),
    measType: String(definition?.meas_type || channelRow?.meas_type || identity?.measType || ""),
    scadaValue,
    realValue,
    deviation: scadaValue !== null && realValue !== null ? scadaValue - realValue : null,
    valid: validNumber === 0 ? 0 : 1,
    status,
    fixedValue: Number.isFinite(fixedValueNumber) ? fixedValueNumber : null,
    weight,
    errorSigma: diagramDefinitionSigmaFromWeight(weight),
    medianDeviation: Number.isFinite(medianDeviationNumber) ? medianDeviationNumber : 0,
  };
}

function diagramDefinitionRowMatches(row, rowKey = {}) {
  const name = String(rowKey.name ?? "");
  const idx = String(rowKey.idx ?? "");
  if (name && String(row?.name ?? "") !== name) return false;
  if (idx && String(row?.idx ?? "") !== idx) return false;
  return Boolean(name || idx);
}

function patchDiagramModelDefinitionRecord(snapshot, record) {
  const blockName = String(record?.block_name || "");
  const block = snapshot?.definitions?.model?.[blockName];
  if (!block) return false;
  const row = (block.rows || []).find((item) => diagramDefinitionRowMatches(item, record.row_key || {}));
  if (!row) return false;
  (block.headers || Object.keys(row)).forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(record, field)) row[field] = record[field];
  });
  const parameterRows = snapshot?.device_parameters?.[blockName];
  if (Array.isArray(parameterRows)) {
    const parameterRow = parameterRows.find((item) => diagramDefinitionRowMatches(item, record.row_key || {}));
    if (parameterRow) Object.assign(parameterRow, row);
  }
  return true;
}

function patchDiagramRuntimeControlRecord(snapshot, runtime) {
  const devType = String(runtime?.dev_type || "").trim();
  const devName = String(runtime?.dev_name || "").trim();
  if (!snapshot || !runtime || !devType || !devName) return false;
  const matches = (item) => (
    normalizeDiagramMeasurementToken(item?.dev_type) === normalizeDiagramMeasurementToken(devType)
    && String(item?.dev_name || item?.name || "").trim() === devName
  );
  let changed = false;
  if (Array.isArray(snapshot.devices)) {
    snapshot.devices.forEach((device) => {
      if (!matches(device)) return;
      if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) device.run_stat = runtime.run_stat;
      if (Object.prototype.hasOwnProperty.call(runtime, "status")) device.status = runtime.status;
      if (runtime.set_values && typeof runtime.set_values === "object") {
        device.set_values = {
          ...(device.set_values || {}),
          ...runtime.set_values,
        };
      }
      if (device.raw && typeof device.raw === "object") {
        if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) device.raw.run_stat = runtime.run_stat;
        if (Object.prototype.hasOwnProperty.call(runtime, "status")) device.raw.status = runtime.status;
        if (runtime.set_values && typeof runtime.set_values === "object") {
          device.raw = {
            ...(device.raw || {}),
            ...runtime.set_values,
          };
        }
      }
      changed = true;
    });
  }
  if (Array.isArray(snapshot.device_states)) {
    snapshot.device_states.forEach((deviceState) => {
      if (!matches(deviceState)) return;
      if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) deviceState.run_stat = runtime.run_stat;
      changed = true;
    });
  }
  if (snapshot.measurements && (Object.prototype.hasOwnProperty.call(runtime, "run_stat") || Object.prototype.hasOwnProperty.call(runtime, "status"))) {
    const measurementUpdates = new Map();
    if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) {
      measurementUpdates.set(normalizeDiagramMeasurementToken("RUN_STAT"), runtime.run_stat);
    }
    if (Object.prototype.hasOwnProperty.call(runtime, "status")) {
      measurementUpdates.set(normalizeDiagramMeasurementToken("STATUS"), runtime.status);
    }
    ["definitions", "real", "scada"].forEach((channel) => {
      const rows = snapshot.measurements[channel];
      if (!Array.isArray(rows)) return;
      rows.forEach((row) => {
        if (
          normalizeDiagramMeasurementToken(row?.dev_type) !== normalizeDiagramMeasurementToken(devType)
          || String(row?.dev_name || "").trim() !== devName
        ) {
          return;
        }
        const measType = normalizeDiagramMeasurementToken(row?.meas_type || row?.name || "");
        if (!measurementUpdates.has(measType)) return;
        row.value = measurementUpdates.get(measType);
        row.valid = 1;
        changed = true;
      });
    });
  }
  return changed;
}

function patchDiagramMeasurementDefinitionRecord(snapshot, record) {
  const name = String(record?.name || "");
  if (!name) return false;
  let changed = false;
  const definitionLists = [
    snapshot?.definitions?.measurement,
    snapshot?.measurements?.definitions,
  ];
  const visited = new Set();
  definitionLists.forEach((rows) => {
    if (!Array.isArray(rows) || visited.has(rows)) return;
    visited.add(rows);
    const row = rows.find((item) => String(item?.name || "") === name);
    if (!row) return;
    Object.assign(row, record);
    changed = true;
  });
  [snapshot?.measurements?.real, snapshot?.measurements?.scada].forEach((rows) => {
    if (!Array.isArray(rows)) return;
    const row = rows.find((item) => String(item?.name || "") === name);
    if (!row) return;
    if (record.valid !== undefined) row.valid = record.valid;
    if (record.weight !== undefined) row.weight = record.weight;
    if (record.status !== undefined) row.status = record.status;
    if (record.fixed_value !== undefined) row.fixed_value = record.fixed_value;
  });
  return changed;
}

function applyDefinitionEditResult(result) {
  if (!result?.memory_updated || !state.snapshot || !result.record) return false;
  if (typeof invalidateManualDefinitionChanges === "function") invalidateManualDefinitionChanges();
  const record = result.record;
  const changed = record.block_name
    ? patchDiagramModelDefinitionRecord(state.snapshot, record)
    : patchDiagramMeasurementDefinitionRecord(state.snapshot, record);
  const runtimeChanged = patchDiagramRuntimeControlRecord(state.snapshot, result.runtime_control);
  if (result.static_meta) {
    state.snapshot.static_meta = {
      ...(state.snapshot.static_meta || {}),
      ...result.static_meta,
    };
  }
  persistStaticSnapshotCache(state.snapshot, currentPageName());
  return changed || runtimeChanged;
}

function definitionEditResultHasWarning(result) {
  return !result?.persisted
    || result?.change_record_persisted === false
    || Boolean(result?.warning);
}

function diagramDeviceHasSwitchStatus(definitionRecords = [], raw = {}) {
  const modelDefinesStatus = definitionRecords.some((record) => (
    (record?.headers || []).some((field) => String(field || "").trim().toLowerCase() === "status")
  ));
  return modelDefinesStatus || Object.prototype.hasOwnProperty.call(raw || {}, "status");
}

function diagramDeviceDefinitionEditorRecords(records = []) {
  return records
    .filter((record) => Array.isArray(record?.editableFields) && record.editableFields.length)
    .map((record) => ({
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      rowKey: { ...record.rowKey },
      editableFields: [...record.editableFields],
      original: { ...record.row },
      draft: { ...record.row },
      dirtyFields: new Set(),
    }));
}

function diagramDeviceDefinitionRecordEditor(editor, record) {
  if (editor?.kind !== "device" || !record) return null;
  return (editor.records || []).find((item) => (
    item.blockName === record.blockName
    && Number(item.rowIndex) === Number(record.rowIndex)
  )) || null;
}

function diagramDeviceDefinitionDirtyUpdates(editor) {
  if (editor?.kind !== "device") return [];
  return (editor.records || []).map((record) => {
    const changes = Object.fromEntries(
      [...(record.dirtyFields || [])].map((field) => [field, record.draft[field]]),
    );
    return Object.keys(changes).length ? {
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      rowKey: { ...record.rowKey },
      changes,
    } : null;
  }).filter(Boolean);
}

function diagramDefinitionPendingFieldLabel(field, kind = "device") {
  const name = String(field || "").trim();
  if (kind === "measurement") {
    return ({
      errorSigma: "误差 σ",
      weight: "权重",
      medianDeviation: "中值偏差",
      status: "量测状态",
      fixedValue: "固定值",
    })[name] || name;
  }
  const normalized = name.toLowerCase();
  return ({
    control_type: "控制模式",
    ac_control_type: "交流侧控制模式",
    dc_control_type: "直流侧控制模式",
    i_control_type: "I 侧控制模式",
    j_control_type: "J 侧控制模式",
    run_stat: "运行状态",
    status: "开关状态",
  })[normalized] || name;
}

function diagramDefinitionPendingDeviceValue(field, value) {
  if (typeof diagramDefinitionDisplayValue === "function") {
    return String(diagramDefinitionDisplayValue(field, value));
  }
  const name = String(field || "").trim().toLowerCase();
  const token = String(value ?? "").trim().toUpperCase();
  if (name === "run_stat") return ["1", "TRUE", "ON", "投入"].includes(token) ? "投入" : "退出";
  if (name === "status") return ["1", "TRUE", "ON", "CLOSED", "闭合", "合闸"].includes(token) ? "闭合" : "断开";
  return diagramTooltipValue(value);
}

function diagramDefinitionPendingValuesEqual(field, before, after, kind = "device") {
  if (kind === "measurement" && field === "status") {
    return diagramMeasurementStatus(before) === diagramMeasurementStatus(after);
  }
  const left = String(before ?? "").trim();
  const right = String(after ?? "").trim();
  if (left === right) return true;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  return left !== "" && right !== ""
    && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)
    && leftNumber === rightNumber;
}

function diagramDefinitionEditorPendingChanges(editor) {
  if (editor?.kind === "device") {
    return (editor.records || []).flatMap((record) => [...(record.dirtyFields || [])]
      .filter((field) => !diagramDefinitionPendingValuesEqual(
        field,
        record.original?.[field],
        record.draft?.[field],
      ))
      .map((field) => ({
      kind: "device",
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      field,
      label: `${record.blockName || "设备"} · ${diagramDefinitionPendingFieldLabel(field)}`,
      before: diagramDefinitionPendingDeviceValue(field, record.original?.[field]),
      after: diagramDefinitionPendingDeviceValue(field, record.draft?.[field]),
      })));
  }
  if (editor?.kind === "measurement") {
    return [...(editor.dirtyFields || [])]
      .filter((field) => !diagramDefinitionPendingValuesEqual(
        field,
        editor.original?.[field],
        editor.draft?.[field],
        "measurement",
      ))
      .map((field) => ({
      kind: "measurement",
      field,
      label: diagramDefinitionPendingFieldLabel(field, "measurement"),
      before: field === "status"
        ? diagramMeasurementStatusLabel(editor.original?.[field], editor.original?.valid)
        : diagramTooltipValue(editor.original?.[field]),
      after: field === "status"
        ? diagramMeasurementStatusLabel(editor.draft?.[field], editor.draft?.valid)
        : diagramTooltipValue(editor.draft?.[field]),
      }));
  }
  return [];
}

function renderDiagramDefinitionLeavePrompt(interaction) {
  if (!interaction?.definitionLeavePrompt || !interaction?.definitionEditor) return "";
  const changes = diagramDefinitionEditorPendingChanges(interaction.definitionEditor);
  if (!changes.length) return "";
  const disabled = interaction.definitionSaving ? "disabled" : "";
  return `
    <div class="diagram-definition-leave-prompt" data-diagram-definition-leave-prompt>
      <strong>以下修改尚未保存</strong>
      <ul class="diagram-definition-change-list">
        ${changes.map((change) => `
          <li>
            <span>${escapeHtml(change.label)}</span>
            <code>${escapeHtml(change.before)}</code>
            <span aria-hidden="true">→</span>
            <code>${escapeHtml(change.after)}</code>
          </li>`).join("")}
      </ul>
      <p>是否保存这些修改？</p>
      <div class="diagram-definition-leave-actions">
        <button type="button" class="primary" data-diagram-definition-leave-action="save" ${disabled}>保存并关闭</button>
        <button type="button" data-diagram-definition-leave-action="discard" ${disabled}>不保存并关闭</button>
        <button type="button" data-diagram-definition-leave-action="continue" ${disabled}>继续编辑</button>
      </div>
    </div>`;
}

function diagramMeasurementFieldName(row = {}) {
  const field = String(row?.meas_type || row?.name || "量测").trim();
  if (!field) return "量测";
  return DIAGRAM_MEASUREMENT_FIELD_LABELS[field.toUpperCase()] || field.toLowerCase();
}

function diagramDeviceData(container, device, snapshot = state.snapshot || {}) {
  if (!device) return { definition: null, live: null, raw: {}, svgIdx: "" };
  const resolvedDevice = diagramResolvedTooltipDevice(container, device);
  const type = normalizeDiagramMeasurementToken(resolvedDevice.devType);
  const name = String(resolvedDevice.devName || "");
  const definition = definedModelDevices(snapshot).find((item) => (
    normalizeDiagramMeasurementToken(item.dev_type) === type
    && String(item.dev_name || "") === name
  )) || null;
  const live = (snapshot.devices || []).find((item) => (
    normalizeDiagramMeasurementToken(item.dev_type) === type
    && String(item.dev_name || "") === name
  )) || null;
  const svgElement = [...container.querySelectorAll("[dev-id]")]
    .find((element) => String(element.getAttribute("dev-id") || "") === resolvedDevice.devId);
  return {
    device: resolvedDevice,
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

function diagramDeviceIdentityKey(device) {
  const devType = normalizeDiagramMeasurementToken(device?.devType ?? device?.dev_type);
  const devName = String(device?.devName ?? device?.dev_name ?? device?.name ?? "").trim();
  return devType && devName ? `${devType}|${devName}` : "";
}

function diagramTooltipDeviceRecord(device = {}) {
  return {
    devId: String(device?.devId ?? device?.dev_id ?? "").trim(),
    devType: String(device?.devType ?? device?.dev_type ?? "").trim(),
    devName: String(device?.devName ?? device?.dev_name ?? device?.name ?? "").trim(),
  };
}

function diagramDeviceSnapshotEntry(snapshot, devType, devName) {
  const identity = diagramDeviceIdentityKey({ devType, devName });
  if (!identity) return null;
  return (snapshot?.devices || []).find((item) => diagramDeviceIdentityKey(item) === identity)
    || definedModelDevices(snapshot).find((item) => diagramDeviceIdentityKey(item) === identity)
    || null;
}

function diagramResolvedTooltipDevice(container, device) {
  const record = diagramTooltipDeviceRecord(device);
  if (record.devId || !container) return record;
  const identity = diagramDeviceIdentityKey(record);
  const svgRecord = [...diagramDeviceIndex(container).values()]
    .find((item) => diagramDeviceIdentityKey(item) === identity);
  return svgRecord ? { ...record, devId: svgRecord.devId } : record;
}

function diagramCouplingDevicePages(device, snapshot = state.snapshot || {}) {
  const hostDevice = diagramTooltipDeviceRecord(device);
  if (!hostDevice.devType || !hostDevice.devName) return [];
  const pages = [{ key: "self", label: "设备本体", relation: null, device: hostDevice }];
  const hostEntry = diagramDeviceSnapshotEntry(snapshot, hostDevice.devType, hostDevice.devName);
  const bindings = Array.isArray(hostEntry?.control_bindings) ? hostEntry.control_bindings : [];
  const seen = new Set([diagramDeviceIdentityKey(hostDevice)]);
  bindings.forEach((binding) => {
    const targetType = String(binding?.target_dev_type || "").trim();
    const targetName = String(binding?.target_dev_name || "").trim();
    const targetEntry = diagramDeviceSnapshotEntry(snapshot, targetType, targetName);
    if (!targetEntry) return;
    const targetDevice = diagramTooltipDeviceRecord(targetEntry);
    const identity = diagramDeviceIdentityKey(targetDevice);
    if (!identity || seen.has(identity)) return;
    seen.add(identity);
    pages.push({
      key: `related:${identity}`,
      label: targetDevice.devName || targetDevice.devType,
      relation: { ...binding },
      device: targetDevice,
    });
  });
  return pages;
}

function diagramActiveDeviceTooltipPage(interaction, hover, pages = []) {
  if (!pages.length) return null;
  const hostKey = String(hover?.key || "");
  if (!interaction) return pages[0];
  if (String(interaction.deviceTooltipHostKey || "") !== hostKey) {
    interaction.deviceTooltipHostKey = hostKey;
    interaction.deviceTooltipTabKey = "self";
  }
  const active = pages.find((page) => page.key === interaction.deviceTooltipTabKey) || pages[0];
  interaction.deviceTooltipTabKey = active.key;
  return active;
}

function diagramSingleDeviceTooltipData(container, device, snapshot) {
  if (!device) return null;
  const { device: resolvedDevice, definition, live, raw, svgIdx } = diagramDeviceData(container, device, snapshot);
  const definitionRecords = diagramDeviceDefinitionRecords(resolvedDevice, snapshot);
  const idx = live?.raw?.idx ?? definition?.idx ?? raw.idx ?? svgIdx ?? "--";
  const identityRows = [
    ["设备类型", resolvedDevice.devType || "--", "identity:type"],
    ["设备标识", resolvedDevice.devId || "--", "identity:id"],
    ["idx", idx, "identity:idx"],
  ];
  const runStatBinding = diagramDefinitionFieldBinding(definitionRecords, ["run_stat"]);
  const statusBinding = diagramDefinitionFieldBinding(definitionRecords, ["status"]);
  const modeBinding = diagramDefinitionFieldBinding(definitionRecords, ["control_type", "mode"]);
  const hasSwitchStatus = diagramDeviceHasSwitchStatus(definitionRecords, raw);
  const statusRows = [
    ["运行状态", live?.run_stat ?? raw.run_stat, "status:run_stat", runStatBinding],
    ...(hasSwitchStatus
      ? [["开关状态", live?.status ?? raw.status, "status:status", statusBinding]]
      : []),
    ["控制模式", live?.mode ?? raw.control_type ?? raw.mode, "status:mode", modeBinding],
  ];
  const setRows = Object.entries(live?.set_values || {})
    .map(([key, value]) => [
      key,
      value,
      `set:${key}`,
      diagramDefinitionFieldBinding(definitionRecords, [key]),
    ]);
  const duplicateKeys = new Set([
    "idx", "name", "dev_name", "dev_type", "run_stat", "status", "mode", "control_type",
    ...Object.keys(live?.set_values || {}),
  ]);
  const rawRows = Object.entries(raw)
    .filter(([key]) => !duplicateKeys.has(key) && !definitionRecords.length)
    .map(([key, value]) => [key, value, `raw:${key}`]);
  const measurementRows = diagramDeviceMeasurements(resolvedDevice, snapshot).map((row) => {
    const metricType = normalizeDiagramMeasurementToken(row.meas_type) === "SOC" ? "level" : "";
    const value = diagramTrendDisplayValue(row.value, row, metricType);
    const unit = diagramMeasurementUnit(row.meas_type);
    return [
      diagramMeasurementFieldName(row),
      value === null ? "--" : `${diagramNumberText(value)}${unit ? ` ${unit}` : ""}`,
      `measurement:${measurementKey(row)}`,
    ];
  });
  return {
    title: resolvedDevice.devName || resolvedDevice.devId || "设备",
    dynamicSections: [
      { key: "identity", title: "", rows: identityRows },
      { key: "status", title: "运行信息", rows: statusRows },
      { key: "set", title: "当前设定值", rows: setRows },
      { key: "raw", title: "Model.e 参数（只读）", rows: rawRows },
      { key: "measurement", title: "实时量测", rows: measurementRows },
    ].filter((section) => section.rows.length),
    definitionRecords,
  };
}

function diagramDeviceTooltipData(container, hover, snapshot, interaction = null) {
  const pages = diagramCouplingDevicePages(hover?.device, snapshot);
  const activePage = diagramActiveDeviceTooltipPage(interaction, hover, pages);
  const data = diagramSingleDeviceTooltipData(container, activePage?.device, snapshot);
  if (!data || !activePage) return null;
  return {
    ...data,
    pages,
    activePageKey: activePage.key,
  };
}

function diagramTooltipSectionsHtml(sections = [], interaction = null) {
  return sections.map((section) => `
    <section class="diagram-tooltip-section" data-diagram-tooltip-section="${escapeHtml(section.key)}">
      ${section.title ? `<h4>${escapeHtml(section.title)}</h4>` : ""}
      ${diagramTooltipRows(section.rows, section.key, interaction)}
    </section>`).join("");
}

function diagramDefinitionMessageHtml(interaction) {
  const message = String(interaction?.definitionMessage || "").trim();
  if (!message) return "";
  const levelClass = interaction?.definitionMessageWarning ? " is-warning" : " is-success";
  return `<div class="diagram-definition-message${levelClass}" data-diagram-definition-message>${escapeHtml(message)}</div>`;
}

const DIAGRAM_DEFINITION_RATIO_FIELDS = new Set([
  "initial_soc",
  "soc_initial",
  "soc_init",
  "state_of_charge",
  "soc",
  "soc_curr",
  "soc_cur",
  "soc_min",
  "soc_max",
  "soc_lower_limit",
  "soc_upper_limit",
]);

const DIAGRAM_DEFINITION_FIELD_LABELS = Object.freeze({
  control_type: "控制模式",
  ac_control_type: "交流侧控制模式",
  dc_control_type: "直流侧控制模式",
  i_control_type: "I 侧控制模式",
  j_control_type: "J 侧控制模式",
  run_stat: "运行状态",
  status: "开关状态",
  e2h_coeff: "电-气效率 (Nm3/kWh)",
  h2e_coeff: "气-电效率 (kWh/Nm3)",
});
const DIAGRAM_HYDROGEN_CONVERSION_BLOCKS = new Set([
  "AcE2Hydro",
  "DcE2Hydro",
  "Hydro2AcE",
  "Hydro2DcE",
]);

function diagramDefinitionFieldLabel(field) {
  const name = String(field || "").trim().toLowerCase();
  return DIAGRAM_DEFINITION_FIELD_LABELS[name] || String(field || "");
}

function diagramDefinitionControlModeValue(value) {
  const token = String(value || "").trim().toUpperCase();
  return ({
    P: "定电功率 (P)",
    PQ: "定有功/无功 (PQ)",
    PV: "定有功/电压 (PV)",
    Q: "定无功 (Q)",
    V: "定电压 (V)",
    I: "定电流 (I)",
    B: "定电纳 (B)",
    Z: "定阻抗 (Z)",
    SLACK: "平衡参考 (SLACK)",
    PH: "构网定压/相角 (PH)",
    FLOW: "定气流量 (FLOW)",
    PRESSURE: "定压力 (PRESSURE)",
    NONE: "无控制 (NONE)",
    PQQ: "两侧定功率 (PQQ)",
    PVQ: "I侧定压/J侧定功率 (PVQ)",
    PQV: "I侧定功率/J侧定压 (PQV)",
    PVV: "两侧定压 (PVV)",
  })[token] || diagramTooltipValue(value);
}

const DIAGRAM_CONTROL_MODE_OPTIONS_BY_BLOCK = Object.freeze({
  ACGENERATOR: ["PQ", "P", "PV", "V", "SLACK", "PH"],
  ACREALBS: ["Q", "V", "B", "Z"],
  ACACCONVERTER: ["PQQ", "PVQ", "PQV", "PVV"],
  DCGENERATOR: ["P", "V", "I", "SLACK"],
  DCDCCONVERTER: ["P", "V", "I"],
  HYDROSOURCE: ["PRESSURE", "FLOW"],
  HYDROLOAD: ["FLOW"],
  HYDROSTORAGE: ["PRESSURE", "FLOW"],
  ACE2HYDRO: ["P", "FLOW"],
  DCE2HYDRO: ["P", "FLOW"],
  HYDRO2ACE: ["P", "FLOW"],
  HYDRO2DCE: ["P", "FLOW"],
});
const DIAGRAM_AC_SIDE_CONTROL_OPTIONS = Object.freeze(["PQ", "PV", "PH", "NONE"]);
const DIAGRAM_DC_SIDE_CONTROL_OPTIONS = Object.freeze(["P", "V", "I", "NONE"]);
const DIAGRAM_DCAC_CONTROL_PAIRS = Object.freeze([
  ["PQ", "NONE"],
  ["PQ", "V"],
  ["PH", "NONE"],
  ["NONE", "P"],
]);

function diagramDefinitionEnumCanonicalValue(record, field, value) {
  const name = String(field || "").trim().toLowerCase();
  const block = normalizeDiagramMeasurementToken(record?.blockName);
  let token = String(value ?? "").trim().toUpperCase();
  if (name === "run_stat" || name === "status") {
    if (["TRUE", "ON", "CLOSED", "投入", "闭合", "合闸"].includes(token)) return "1";
    if (["FALSE", "OFF", "OPEN", "退出", "断开", "分闸"].includes(token)) return "0";
    return Number(token) === 1 ? "1" : (Number(token) === 0 ? "0" : token);
  }
  if (name === "i_control_type" || name === "j_control_type") {
    if (token === "CTRL_P") token = "P";
    if (token === "CTRL_I") token = "I";
    if (block === "ACACCONVERTER") {
      if (["CTRL_PQ", "Q"].includes(token)) token = "PQ";
      if (["CTRL_PV", "CTRL_V", "V"].includes(token)) token = "PV";
      if (token === "CTRL_PH") token = "PH";
      if (["CTRL_NONE", "UNSPEC", "UNDEFINED", "NA"].includes(token)) token = "NONE";
    } else if (block === "DCDCCONVERTER") {
      if (token === "CTRL_V") token = "V";
      if (["SLACK", "CTRL_SLACK", "CTRL_NONE"].includes(token)) token = "NONE";
    }
  }
  return token;
}

function diagramDefinitionEnumOption(value, label = "") {
  const token = String(value);
  return { value: token, label: label || diagramDefinitionControlModeValue(token) };
}

function diagramDefinitionEnumOptions(record, field) {
  const name = String(field || "").trim().toLowerCase();
  const block = normalizeDiagramMeasurementToken(record?.blockName);
  const row = record?.row || {};
  if (name === "run_stat") {
    return [diagramDefinitionEnumOption("1", "投入"), diagramDefinitionEnumOption("0", "退出")];
  }
  if (name === "status") {
    return [diagramDefinitionEnumOption("1", "闭合"), diagramDefinitionEnumOption("0", "断开")];
  }
  let values = [];
  if (block === "DCACCONVERTER" && name === "ac_control_type") {
    values = DIAGRAM_DCAC_CONTROL_PAIRS.map((pair) => pair[0]);
  } else if (block === "DCACCONVERTER" && name === "dc_control_type") {
    values = DIAGRAM_DCAC_CONTROL_PAIRS.map((pair) => pair[1]);
  } else if (name === "ac_control_type") {
    values = DIAGRAM_AC_SIDE_CONTROL_OPTIONS;
  } else if (name === "dc_control_type") {
    values = DIAGRAM_DC_SIDE_CONTROL_OPTIONS;
  } else if (name === "i_control_type" || name === "j_control_type") {
    values = block === "ACACCONVERTER"
      ? DIAGRAM_AC_SIDE_CONTROL_OPTIONS
      : DIAGRAM_DC_SIDE_CONTROL_OPTIONS;
  } else if (name === "control_type") {
    values = DIAGRAM_CONTROL_MODE_OPTIONS_BY_BLOCK[block] || [];
  } else if (name.endsWith("_control_type") || name === "mode" || name.endsWith("_mode")) {
    values = [];
  } else {
    return [];
  }
  const current = diagramDefinitionEnumCanonicalValue(record, field, row[field]);
  const unique = [...new Set(values.map((value) => String(value)))];
  if (!unique.length && current) unique.push(current);
  return unique.map((value) => diagramDefinitionEnumOption(value));
}

function diagramDefinitionCoupledEnumValues(record, field, value) {
  const block = normalizeDiagramMeasurementToken(record?.blockName);
  const name = String(field || "").trim().toLowerCase();
  const row = record?.row || {};
  const selected = diagramDefinitionEnumCanonicalValue(record, field, value);
  const changes = { [field]: selected };
  if (block === "DCDCCONVERTER" && ["i_control_type", "j_control_type"].includes(name)) {
    const otherField = name === "i_control_type" ? "j_control_type" : "i_control_type";
    const other = diagramDefinitionEnumCanonicalValue(record, otherField, row[otherField]);
    changes[otherField] = selected === "NONE"
      ? (["P", "V", "I"].includes(other) ? other : "P")
      : "NONE";
  }
  if (block === "DCACCONVERTER" && name === "ac_control_type") {
    const dcMode = diagramDefinitionEnumCanonicalValue(record, "dc_control_type", row.dc_control_type);
    changes.dc_control_type = selected === "NONE"
      ? "P"
      : (selected === "PQ" && dcMode === "V" ? "V" : "NONE");
  }
  if (block === "DCACCONVERTER" && name === "dc_control_type") {
    const acMode = diagramDefinitionEnumCanonicalValue(record, "ac_control_type", row.ac_control_type);
    changes.ac_control_type = selected === "P"
      ? "NONE"
      : (selected === "V" ? "PQ" : (["PQ", "PH"].includes(acMode) ? acMode : "PQ"));
  }
  return changes;
}

function diagramDefinitionControlModeOptions(record, field) {
  return diagramDefinitionEnumOptions(record, field).map((option) => option.value);
}

function renderDiagramDefinitionEnumSelect(record, field, value, interaction) {
  const options = diagramDefinitionEnumOptions(record, field);
  const current = diagramDefinitionEnumCanonicalValue(record, field, value);
  const currentValid = options.some((option) => option.value === current);
  return `
    <select
      class="diagram-definition-input"
      data-diagram-tooltip-inline-input
      data-diagram-definition-input="device"
      data-diagram-definition-enum
      data-diagram-definition-control-mode
      data-diagram-definition-field="${escapeHtml(field)}"
      ${interaction?.definitionSaving ? "disabled" : ""}
    >
      ${currentValid ? "" : `<option value="" selected disabled>${escapeHtml(`无效选项 (${current || "空"})，请选择`)}</option>`}
      ${options.map((option) => `
        <option value="${escapeHtml(option.value)}" ${current === option.value ? "selected" : ""}>
          ${escapeHtml(option.label)}
        </option>`).join("")}
    </select>`;
}

function diagramDefinitionSocField(field) {
  const name = String(field || "").trim().toLowerCase();
  return DIAGRAM_DEFINITION_RATIO_FIELDS.has(name) || name.startsWith("soc_");
}

function diagramDefinitionEfficiencyField(field) {
  const name = String(field || "").trim().toLowerCase();
  return name.includes("efficiency")
    || name === "eta"
    || name.startsWith("eta_")
    || name.endsWith("_eta")
    || name.endsWith("_eff");
}

function diagramDefinitionRatioField(field) {
  return diagramDefinitionSocField(field) || diagramDefinitionEfficiencyField(field);
}

function diagramDefinitionRatioFromStored(field, value) {
  const raw = String(value ?? "").trim();
  const explicitPercent = raw.endsWith("%");
  const numericText = explicitPercent ? raw.slice(0, -1).trim() : raw;
  let number = Number(numericText);
  if (!Number.isFinite(number)) return null;
  if (explicitPercent) return number / 100;
  if (diagramDefinitionEfficiencyField(field) && number > 1 && number <= 100) number /= 100;
  if (diagramDefinitionSocField(field) && Math.abs(number) > 2 && Math.abs(number) <= 100) number /= 100;
  return number;
}

function diagramDefinitionNumberText(value) {
  if (!Number.isFinite(Number(value))) return "";
  const number = Number(Number(value).toPrecision(15));
  return Object.is(number, -0) ? "0" : String(number);
}

function diagramDefinitionDisplayValue(field, value) {
  const name = String(field || "").trim().toLowerCase();
  const canonical = diagramDefinitionEnumCanonicalValue({}, field, value);
  if (name === "run_stat") return canonical === "1" ? "投入" : (canonical === "0" ? "退出" : diagramTooltipValue(value));
  if (name === "status") return canonical === "1" ? "闭合" : (canonical === "0" ? "断开" : diagramTooltipValue(value));
  if (name === "control_type" || name === "mode" || name.endsWith("_control_type") || name.endsWith("_mode")) {
    return diagramDefinitionControlModeValue(value);
  }
  if (!diagramDefinitionRatioField(field)) return diagramTooltipValue(value);
  const ratio = diagramDefinitionRatioFromStored(field, value);
  return ratio === null ? diagramTooltipValue(value) : `${diagramDefinitionNumberText(ratio * 100)}%`;
}

function diagramDefinitionStoredValue(field, value) {
  const raw = String(value ?? "").trim();
  if (!diagramDefinitionRatioField(field)) return raw;
  const numericText = raw.endsWith("%") ? raw.slice(0, -1).trim() : raw;
  const percent = Number(numericText);
  return Number.isFinite(percent) ? diagramDefinitionNumberText(percent / 100) : raw;
}

function diagramDefinitionCanonicalStoredValue(field, value) {
  if (!diagramDefinitionRatioField(field)) return String(value ?? "").trim();
  const ratio = diagramDefinitionRatioFromStored(field, value);
  return ratio === null ? String(value ?? "").trim() : diagramDefinitionNumberText(ratio);
}

function diagramDefinitionInputDescriptor(field, value) {
  const raw = String(value ?? "").trim();
  if (diagramDefinitionRatioField(field)) {
    const ratio = diagramDefinitionRatioFromStored(field, value);
    if (ratio !== null) {
      return {
        type: "number",
        value: diagramDefinitionNumberText(ratio * 100),
        suffix: "%",
        min: "0",
        max: "100",
      };
    }
  }
  const suffix = raw.endsWith("%") ? "%" : "";
  const numericText = suffix ? raw.slice(0, -1).trim() : raw;
  const number = Number(numericText);
  return Number.isFinite(number)
    ? { type: "number", value: numericText, suffix, min: "", max: "" }
    : { type: "text", value: raw, suffix: "", min: "", max: "" };
}

function renderDiagramDeviceDefinitionEditor(record, editor, interaction) {
  const canSave = diagramDeviceDefinitionDirtyUpdates(editor).length > 0
    && !interaction?.definitionSaving;
  return `
    <div class="diagram-definition-actions diagram-definition-head-actions" data-diagram-definition-actions="device">
      <button type="button" data-diagram-definition-cancel>取消</button>
      <button type="button" class="primary" data-diagram-definition-save="device" ${canSave ? "" : "disabled"}>
        ${interaction?.definitionSaving ? "保存中" : "保存"}
      </button>
    </div>`;
}

function renderDiagramDeviceDefinitionHeadActions(records, interaction) {
  const editor = interaction?.definitionEditor?.kind === "device"
    ? interaction.definitionEditor
    : null;
  const activeRecord = editor
    ? records.find((record) => diagramDeviceDefinitionRecordEditor(editor, record))
    : null;
  return editor && activeRecord
    ? renderDiagramDeviceDefinitionEditor(activeRecord, editor, interaction)
    : "";
}

function renderDiagramDeviceDefinitionValueRow(record, field, activeEditor, interaction) {
  const key = `definition:${record.blockName}:${record.rowIndex}:${field}`;
  const fieldEditable = diagramDeviceParameterEditable(field);
  const editable = Boolean(activeEditor && diagramDeviceParameterEditable(field));
  if (!editable) {
    return `
      <div class="diagram-tooltip-row${fieldEditable ? " is-editable" : ""}" data-diagram-tooltip-row="${escapeHtml(key)}">
        <dt>${escapeHtml(diagramDefinitionFieldLabel(field))}</dt>
        <dd
          data-diagram-definition-value="${escapeHtml(key)}"
          data-diagram-tooltip-value="${escapeHtml(key)}"
          ${fieldEditable ? 'data-diagram-definition-editable="device"' : ""}
        >${escapeHtml(diagramDefinitionDisplayValue(field, record.row[field]))}</dd>
      </div>`;
  }
  const enumRecord = { ...record, row: activeEditor.draft };
  const enumOptions = diagramDefinitionEnumOptions(enumRecord, field);
  if (enumOptions.length) {
    return `
      <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(key)}">
        <dt>${escapeHtml(diagramDefinitionFieldLabel(field))}</dt>
        <dd data-diagram-definition-value="${escapeHtml(key)}">
          ${renderDiagramDefinitionEnumSelect(
            enumRecord,
            field,
            activeEditor.draft[field],
            interaction,
          )}
        </dd>
      </div>`;
  }
  const descriptor = diagramDefinitionInputDescriptor(field, activeEditor.draft[field]);
  return `
    <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(key)}">
      <dt>${escapeHtml(diagramDefinitionFieldLabel(field))}</dt>
      <dd data-diagram-definition-value="${escapeHtml(key)}">
        <span class="diagram-definition-input-wrap">
          <input
            class="diagram-definition-input"
            data-diagram-tooltip-inline-input
            data-diagram-definition-input="device"
            data-diagram-definition-field="${escapeHtml(field)}"
            type="${descriptor.type}"
            ${descriptor.type === "number" ? 'step="any"' : ""}
            ${descriptor.min !== "" ? `min="${descriptor.min}"` : ""}
            ${descriptor.max !== "" ? `max="${descriptor.max}"` : ""}
            value="${escapeHtml(descriptor.value)}"
            ${interaction?.definitionSaving ? "disabled" : ""}
          >
          ${descriptor.suffix ? `<small>${escapeHtml(descriptor.suffix)}</small>` : ""}
        </span>
      </dd>
    </div>`;
}

function renderDiagramDeviceDefinitionRecord(record, interaction) {
  const activeEditor = diagramDeviceDefinitionRecordEditor(
    interaction?.definitionEditor,
    record,
  );
  const displayHeaders = diagramDefinitionDisplayHeaders(record);
  if (!displayHeaders.length) return "";
  const rows = displayHeaders
    .map((field) => renderDiagramDeviceDefinitionValueRow(record, field, activeEditor, interaction))
    .join("");
  return `
    <section class="diagram-tooltip-section diagram-definition-section" data-diagram-definition-block="${escapeHtml(record.blockName)}" data-diagram-definition-row-index="${record.rowIndex}">
      <div class="diagram-definition-section-head">
        <h4>${escapeHtml(record.blockName)} 参数</h4>
      </div>
      <dl class="diagram-tooltip-grid">${rows}</dl>
    </section>`;
}

function diagramDeviceDefinitionRecordsSignature(records) {
  const payload = (records || []).map((record) => {
    const headers = diagramDefinitionDisplayHeaders(record);
    return [
      record.blockName,
      Number(record.rowIndex),
      headers.map((field) => [field, record.row?.[field] ?? ""]),
    ];
  });
  const text = JSON.stringify(payload);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${payload.length}:${(hash >>> 0).toString(16)}`;
}

function renderDiagramDeviceDefinitionRecords(records, interaction) {
  if (!records.length) return "";
  const content = records
    .map((record) => renderDiagramDeviceDefinitionRecord(record, interaction))
    .filter(Boolean)
    .join("");
  if (!content) return "";
  return `
    <div
      class="diagram-definition-records"
      data-diagram-definition-records
      data-diagram-definition-signature="${diagramDeviceDefinitionRecordsSignature(records)}"
    >
      ${content}
    </div>`;
}

function renderDiagramDeviceDefinitionFooter(records, interaction) {
  const content = interaction?.definitionEditor?.kind === "device"
    ? diagramDefinitionEditorMessageHtml(interaction, interaction.definitionEditor.validationError)
    : diagramDefinitionMessageHtml(interaction);
  if (!content) return "";
  return `
    <div class="diagram-definition-footer" data-diagram-definition-footer>
      ${content}
    </div>`;
}

function renderDiagramDeviceClassifiedTable(data, interaction) {
  const [identitySection, ...detailSections] = data.dynamicSections;
  const identitySections = identitySection ? [identitySection] : [];
  return `
    <div
      class="diagram-device-tab-panel"
      role="tabpanel"
      data-diagram-device-tab-panel
      data-diagram-device-active-tab="${escapeHtml(data.activePageKey || "self")}"
      data-diagram-device-dynamic-body
    >
      ${diagramTooltipSectionsHtml(identitySections, interaction)}
      ${renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction)}
      ${diagramTooltipSectionsHtml(detailSections, interaction)}
      ${renderDiagramDeviceDefinitionFooter(data.definitionRecords, interaction)}
    </div>`;
}

function renderDiagramDeviceTabs(data, interaction) {
  if (!Array.isArray(data?.pages) || data.pages.length <= 1) return "";
  const disabled = diagramDefinitionEditPinned(interaction);
  return `
    <div class="diagram-device-tabs" role="tablist" aria-label="关联设备">
      ${data.pages.map((page) => {
        const active = page.key === data.activePageKey;
        const type = page.device?.devType || "";
        return `
          <button
            type="button"
            class="diagram-device-tab"
            role="tab"
            data-diagram-device-tab="${escapeHtml(page.key)}"
            aria-selected="${active ? "true" : "false"}"
            tabindex="${active ? "0" : "-1"}"
            title="${escapeHtml(type ? `${type} · ${page.label}` : page.label)}"
            ${disabled ? "disabled" : ""}
          >
            <span>${escapeHtml(page.label)}</span>
            ${type ? `<small>${escapeHtml(type)}</small>` : ""}
          </button>`;
      }).join("")}
    </div>`;
}

function renderDiagramDeviceTooltip(container, hover, snapshot, interaction) {
  const data = diagramDeviceTooltipData(container, hover, snapshot, interaction);
  if (!data) return "";
  const leavePrompt = renderDiagramDefinitionLeavePrompt(interaction);
  if (leavePrompt) {
    return `
      <div class="diagram-tooltip-head">
        <strong data-diagram-tooltip-device-name>${escapeHtml(data.title)}</strong>
        <span>设备参数</span>
      </div>
      <div class="diagram-tooltip-body">${leavePrompt}</div>`;
  }
  return `
    <div class="diagram-tooltip-head">
      <strong data-diagram-tooltip-device-name>${escapeHtml(data.title)}</strong>
      <div class="diagram-tooltip-head-controls">
        <span>设备参数</span>
        ${renderDiagramDeviceDefinitionHeadActions(data.definitionRecords, interaction)}
      </div>
    </div>
    <div class="diagram-tooltip-body" data-diagram-device-tooltip-body>
      ${renderDiagramDeviceTabs(data, interaction)}
      ${renderDiagramDeviceClassifiedTable(data, interaction)}
    </div>`;
}

function diagramDefinitionEditPinned(interaction) {
  return Boolean(interaction?.definitionEditor || interaction?.definitionSaving);
}

function beginDiagramDeviceDefinitionEdit(container, blockName, rowIndex = 0) {
  const interaction = diagramInteractionState(container);
  const snapshot = interaction.snapshot || state.snapshot || {};
  const pages = diagramCouplingDevicePages(interaction.hover?.device, snapshot);
  const activePage = diagramActiveDeviceTooltipPage(interaction, interaction.hover, pages);
  const records = diagramDeviceDefinitionRecords(activePage?.device, snapshot);
  const record = records.find((item) => (
    item.blockName === String(blockName || "")
    && Number(item.rowIndex) === Number(rowIndex)
  ));
  if (!record || !record.editableFields.length) return false;
  const editorRecords = diagramDeviceDefinitionEditorRecords(records);
  if (!editorRecords.length) return false;
  interaction.definitionEditor = {
    kind: "device",
    blockName: record.blockName,
    rowIndex: record.rowIndex,
    revision: Number(snapshot?.static_meta?.definitions?.revision),
    records: editorRecords,
    dirtyFields: new Set(),
    validationError: "",
    devicePageKey: activePage?.key || "self",
  };
  interaction.definitionSaving = false;
  interaction.definitionLeavePrompt = false;
  interaction.definitionCloseAfterSave = false;
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  interaction.tooltip?.classList.add("is-editing-definition");
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

function cancelDiagramDefinitionEdit(container) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction?.definitionEditor && !interaction?.definitionSaving) return false;
  interaction.definitionEditor = null;
  interaction.definitionSaving = false;
  interaction.definitionLeavePrompt = false;
  interaction.definitionCloseAfterSave = false;
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  interaction.tooltip?.classList.remove("is-editing-definition");
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

function updateDiagramDefinitionSaveState(interaction) {
  const button = interaction?.tooltip?.querySelector("[data-diagram-definition-save]");
  if (!button) return;
  const editor = interaction.definitionEditor;
  const invalid = editor?.validationError;
  button.disabled = Boolean(
    interaction.definitionSaving
    || !editor?.dirtyFields?.size
    || invalid,
  );
  const message = interaction.tooltip.querySelector("[data-diagram-definition-message]");
  if (message && invalid) {
    message.textContent = invalid;
    message.classList.add("is-warning");
  }
}

function updateDiagramDeviceDefinitionDraft(interaction, input) {
  const editor = interaction?.definitionEditor;
  if (editor?.kind !== "device") return false;
  const field = String(input?.getAttribute?.("data-diagram-definition-field") || "");
  if (!diagramDeviceParameterEditable(field)) return false;
  const section = input.closest?.("[data-diagram-definition-block]");
  const blockName = String(section?.getAttribute?.("data-diagram-definition-block") || "");
  const rowIndex = Number(section?.getAttribute?.("data-diagram-definition-row-index") || 0);
  const record = (editor.records || []).find((item) => (
    item.blockName === blockName && Number(item.rowIndex) === rowIndex
  ));
  if (!record || !record.editableFields.includes(field)) return false;
  const enumRecord = { ...record, row: record.draft };
  const enumOptions = diagramDefinitionEnumOptions(enumRecord, field);
  const changes = enumOptions.length
    ? diagramDefinitionCoupledEnumValues(enumRecord, field, input.value)
    : { [field]: diagramDefinitionStoredValue(field, input.value) };
  Object.entries(changes).forEach(([changedField, value]) => {
    if (!record.editableFields.includes(changedField)) return;
    record.draft[changedField] = value;
    const changedRecord = { ...record, row: record.draft };
    const originalValue = diagramDefinitionEnumOptions(changedRecord, changedField).length
      ? diagramDefinitionEnumCanonicalValue(changedRecord, changedField, record.original[changedField])
      : diagramDefinitionCanonicalStoredValue(changedField, record.original[changedField]);
    const dirtyKey = `${record.blockName}:${record.rowIndex}:${changedField}`;
    if (value === originalValue) {
      record.dirtyFields.delete(changedField);
      editor.dirtyFields.delete(dirtyKey);
    } else {
      record.dirtyFields.add(changedField);
      editor.dirtyFields.add(dirtyKey);
    }
    interaction.tooltip?.querySelectorAll?.(`[data-diagram-definition-field="${changedField}"]`).forEach((candidate) => {
      const candidateSection = candidate.closest?.("[data-diagram-definition-block]");
      if (String(candidateSection?.getAttribute?.("data-diagram-definition-block") || "") === record.blockName
          && Number(candidateSection?.getAttribute?.("data-diagram-definition-row-index") || 0) === record.rowIndex) {
        candidate.value = value;
      }
    });
  });
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  updateDiagramDefinitionSaveState(interaction);
  return true;
}

async function saveDiagramDeviceDefinitionEdit(container) {
  const interaction = diagramInteractionCache.get(container);
  const editor = interaction?.definitionEditor;
  if (!interaction || editor?.kind !== "device" || interaction.definitionSaving) return false;
  const updates = diagramDeviceDefinitionDirtyUpdates(editor);
  if (!updates.length) return false;
  const closeAfterSave = Boolean(interaction.definitionCloseAfterSave);
  interaction.definitionSaving = true;
  interaction.definitionMessage = `正在更新 ${updates.length} 个参数块并保存人工覆盖层`;
  interaction.definitionMessageWarning = false;
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  let completed = 0;
  let revision = editor.revision;
  let resultWarning = false;
  let warningMessage = "";
  let runtimeControlUpdated = false;
  try {
    for (const update of updates) {
      const result = await api("/api/definitions/device-parameters", {
        method: "POST",
        body: JSON.stringify({
          block_name: update.blockName,
          row_key: update.rowKey,
          revision,
          changes: update.changes,
        }),
      });
      applyDefinitionEditResult(result);
      revision = Number(
        result?.revision
        ?? result?.static_meta?.definitions?.revision
        ?? revision,
      );
      completed += 1;
      const updateWarning = definitionEditResultHasWarning(result);
      resultWarning = updateWarning || resultWarning;
      interaction.definitionMessageWarning = resultWarning;
      if (result?.warning) warningMessage = result.warning;
      runtimeControlUpdated = Boolean(result?.runtime_control) || runtimeControlUpdated;
      const savedRecord = (editor.records || []).find((record) => (
        record.blockName === update.blockName && Number(record.rowIndex) === Number(update.rowIndex)
      ));
      Object.keys(update.changes).forEach((field) => {
        if (!savedRecord || updateWarning) return;
        savedRecord.original[field] = savedRecord.draft[field];
        savedRecord.dirtyFields.delete(field);
        editor.dirtyFields.delete(`${savedRecord.blockName}:${savedRecord.rowIndex}:${field}`);
      });
      editor.revision = revision;
    }
    interaction.snapshot = state.snapshot;
    interaction.definitionSaving = false;
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    if (resultWarning) {
      interaction.definitionMessage = warningMessage || `${completed} 个参数块已更新，但人工覆盖层保存未完成，请重试`;
      interaction.definitionMessageWarning = true;
      renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
      return false;
    }
    interaction.definitionEditor = null;
    interaction.definitionMessage = resultWarning
      ? (warningMessage || `${completed} 个参数块已更新，但人工覆盖层需要重试`)
      : (runtimeControlUpdated
        ? `${completed} 个参数块及运行控制覆盖已接收，等待下一轮潮流计算执行`
        : `${completed} 个参数块的人工覆盖已保存`);
    interaction.definitionMessageWarning = resultWarning;
    interaction.tooltip?.classList.remove("is-editing-definition");
    if (closeAfterSave) hideDiagramTooltip(container);
    else renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
    return true;
  } catch (error) {
    interaction.snapshot = state.snapshot;
    interaction.definitionSaving = false;
    interaction.definitionCloseAfterSave = false;
    interaction.definitionMessage = completed
      ? `已保存 ${completed}/${updates.length} 个参数块；后续保存失败：${apiErrorText(error)}`
      : apiErrorText(error);
    interaction.definitionMessageWarning = true;
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
    return false;
  }
}

function reorderDiagramChildren(parent, desiredChildren = []) {
  if (!parent) return;
  desiredChildren.filter(Boolean).forEach((child, index) => {
    const current = parent.children[index] || null;
    if (current !== child) parent.insertBefore(child, current);
  });
}

function syncDiagramTooltipSections(body, sections = []) {
  if (!body) return false;
  const definitionAnchor = Array.from(body.children)
    .find((element) => element.hasAttribute("data-diagram-definition-records")) || null;
  const definitionFooter = Array.from(body.children)
    .find((element) => element.hasAttribute("data-diagram-definition-footer")) || null;
  const existingSections = new Map(Array.from(body.children)
    .filter((element) => element.hasAttribute("data-diagram-tooltip-section"))
    .map((element) => [element.getAttribute("data-diagram-tooltip-section") || "", element]));
  const desiredSectionKeys = new Set();
  const desiredSectionElements = [];
  sections.forEach((section) => {
    const sectionKey = String(section.key || "");
    desiredSectionKeys.add(sectionKey);
    let sectionElement = existingSections.get(sectionKey);
    if (!sectionElement) {
      sectionElement = document.createElement("section");
      sectionElement.className = "diagram-tooltip-section";
      sectionElement.setAttribute("data-diagram-tooltip-section", sectionKey);
    }
    let heading = Array.from(sectionElement.children).find((element) => element.tagName === "H4") || null;
    if (section.title) {
      if (!heading) {
        heading = document.createElement("h4");
        sectionElement.prepend(heading);
      }
      heading.textContent = section.title;
    } else if (heading) {
      heading.remove();
    }
    let list = Array.from(sectionElement.children).find((element) => element.classList.contains("diagram-tooltip-grid")) || null;
    if (!list) {
      list = document.createElement("dl");
      list.className = "diagram-tooltip-grid";
      sectionElement.appendChild(list);
    }
    const existingRows = new Map(Array.from(list.children)
      .filter((element) => element.hasAttribute("data-diagram-tooltip-row"))
      .map((element) => [element.getAttribute("data-diagram-tooltip-row") || "", element]));
    const desiredRowKeys = new Set();
    const desiredRows = [];
    section.rows.forEach(([label, value, key, binding], index) => {
      const rowKey = String(key || diagramTooltipRowKey(sectionKey, label, index));
      desiredRowKeys.add(rowKey);
      let rowElement = existingRows.get(rowKey);
      if (!rowElement) {
        rowElement = document.createElement("div");
        rowElement.className = "diagram-tooltip-row";
        rowElement.setAttribute("data-diagram-tooltip-row", rowKey);
        const term = document.createElement("dt");
        const description = document.createElement("dd");
        description.setAttribute("data-diagram-tooltip-value", rowKey);
        rowElement.append(term, description);
      }
      const term = rowElement.querySelector("dt");
      const description = rowElement.querySelector("dd");
      const inlineInput = description?.querySelector("[data-diagram-tooltip-inline-input]");
      if (term) term.textContent = label;
      if (description && !inlineInput) {
        description.textContent = binding
          ? diagramDefinitionDisplayValue(binding.field, value)
          : diagramTooltipValue(value);
      }
      if (!inlineInput) {
        rowElement.className = `diagram-tooltip-row${binding?.editable ? " is-editable" : ""}`;
        if (binding) {
          rowElement.setAttribute("data-diagram-definition-block", binding.blockName);
          rowElement.setAttribute("data-diagram-definition-row-index", String(binding.rowIndex));
        } else {
          rowElement.removeAttribute("data-diagram-definition-block");
          rowElement.removeAttribute("data-diagram-definition-row-index");
        }
        if (description) {
          if (binding?.editable) description.setAttribute("data-diagram-definition-editable", "device");
          else description.removeAttribute("data-diagram-definition-editable");
        }
      }
      desiredRows.push(rowElement);
    });
    existingRows.forEach((element, key) => {
      if (!desiredRowKeys.has(key)) element.remove();
    });
    reorderDiagramChildren(list, desiredRows);
    desiredSectionElements.push(sectionElement);
  });
  existingSections.forEach((element, key) => {
    if (!desiredSectionKeys.has(key)) element.remove();
  });
  const desiredBodyChildren = definitionAnchor
    ? [desiredSectionElements[0], definitionAnchor, ...desiredSectionElements.slice(1)]
    : [...desiredSectionElements];
  if (definitionFooter) desiredBodyChildren.push(definitionFooter);
  reorderDiagramChildren(body, desiredBodyChildren);
  return true;
}

function updateDiagramDeviceDynamicSections(tooltip, data) {
  const dynamicBody = tooltip?.querySelector("[data-diagram-device-dynamic-body]");
  if (!tooltip || !data || !dynamicBody) return false;
  const title = tooltip.querySelector("[data-diagram-tooltip-device-name]");
  if (title) title.textContent = data.title;
  return syncDiagramTooltipSections(dynamicBody, data.dynamicSections);
}

function syncDiagramDeviceTabs(tooltip, data, interaction) {
  const body = tooltip?.querySelector("[data-diagram-device-tooltip-body]");
  const panel = body?.querySelector("[data-diagram-device-tab-panel]");
  let tabs = body?.querySelector(".diagram-device-tabs") || null;
  if (!body || !panel) return false;
  panel.setAttribute("data-diagram-device-active-tab", data.activePageKey || "self");
  if (!Array.isArray(data.pages) || data.pages.length <= 1) {
    tabs?.remove();
    return true;
  }
  if (!tabs) {
    tabs = document.createElement("div");
    tabs.className = "diagram-device-tabs";
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", "关联设备");
    body.insertBefore(tabs, panel);
  }
  const existing = new Map(Array.from(tabs.querySelectorAll("[data-diagram-device-tab]"))
    .map((button) => [button.getAttribute("data-diagram-device-tab") || "", button]));
  const desiredKeys = new Set();
  const desiredButtons = data.pages.map((page) => {
    desiredKeys.add(page.key);
    let button = existing.get(page.key);
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "diagram-device-tab";
      button.setAttribute("role", "tab");
      button.setAttribute("data-diagram-device-tab", page.key);
      button.append(document.createElement("span"), document.createElement("small"));
    }
    const active = page.key === data.activePageKey;
    const type = String(page.device?.devType || "");
    button.querySelector("span").textContent = page.label;
    const typeLabel = button.querySelector("small");
    typeLabel.textContent = type;
    typeLabel.hidden = !type;
    button.title = type ? `${type} · ${page.label}` : page.label;
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
    button.disabled = diagramDefinitionEditPinned(interaction);
    return button;
  });
  existing.forEach((button, key) => {
    if (!desiredKeys.has(key)) button.remove();
  });
  reorderDiagramChildren(tabs, desiredButtons);
  return true;
}

function updateDiagramDeviceTooltip(container, hover, snapshot, interaction) {
  const tooltip = interaction?.tooltip;
  const data = diagramDeviceTooltipData(container, hover, snapshot, interaction);
  const definitions = tooltip?.querySelector("[data-diagram-definition-records]");
  if (!tooltip || !data) return false;
  syncDiagramDeviceTabs(tooltip, data, interaction);
  const dynamicUpdated = updateDiagramDeviceDynamicSections(tooltip, data);
  if (interaction.definitionEditor?.kind === "device") return dynamicUpdated;
  if (definitions) {
    const definitionSignature = diagramDeviceDefinitionRecordsSignature(data.definitionRecords);
    const currentDefinitionSignature = definitions.getAttribute("data-diagram-definition-signature") || "";
    if (currentDefinitionSignature !== definitionSignature) {
      const definitionHtml = renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction);
      if (definitionHtml) definitions.outerHTML = definitionHtml;
      else definitions.remove();
    }
  } else if (data.definitionRecords.length) {
    const dynamicBody = tooltip.querySelector("[data-diagram-device-dynamic-body]");
    const identitySection = dynamicBody?.querySelector('[data-diagram-tooltip-section="identity"]');
    const definitionHtml = renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction);
    if (definitionHtml) {
      if (!dynamicBody) return false;
      if (identitySection) identitySection.insertAdjacentHTML("afterend", definitionHtml);
      else dynamicBody.insertAdjacentHTML("afterbegin", definitionHtml);
    }
  }
  return dynamicUpdated;
}

function diagramMetricCurrentRow(container, hover, snapshot) {
  const maps = diagramMeasurementMaps(snapshot);
  if (hover?.binding) return diagramMetricBindingValue(hover.binding, maps);
  if (hover?.name) return diagramBindingValue(hover.name, maps, hover.channel || "scada");
  return null;
}

function diagramTrendHistorySeries(row, metricType = "") {
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
    const scada = diagramTrendDisplayValue(measurement.scada ?? measurement.value, row, metricType);
    const real = diagramTrendDisplayValue(measurement.real, row, metricType);
    if (scada === null && real === null) return null;
    return {
      minute: Number(point.minute),
      time: point.sim_time || point.time || "--",
      scada,
      real,
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
  return labels[normalizeDiagramMetricType(metricType)]
    || row?.meas_type
    || row?.name
    || "动态量测";
}

const DIAGRAM_TREND_SERIES = Object.freeze([
  Object.freeze({ key: "scada", label: "量测值" }),
  Object.freeze({ key: "real", label: "真值" }),
]);

function diagramTrendFiniteValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function diagramTrendChartModel(points, period, tooltipWidth = 360, currentMinute = null, unit = "", rangeOverride = null) {
  const sourcePoints = Array.isArray(points) ? points : [];
  const targetCount = Math.max(32, Math.floor(Math.max(tooltipWidth, 320) * 0.75));
  const values = sourcePoints.flatMap((point) => DIAGRAM_TREND_SERIES.flatMap((series) => {
    const value = diagramTrendFiniteValue(point?.[series.key]);
    return value === null ? [] : [value];
  }));
  const axis = diagramTrendAxisScale(values, 4);
  const width = 336;
  const height = 148;
  const plot = { left: 52, right: 10, top: 20, bottom: 10 };
  const lastSourcePoint = sourcePoints[sourcePoints.length - 1] || null;
  const fallbackMinute = Number(lastSourcePoint?.minute);
  const defaultRange = diagramTrendPeriodRange(
    period,
    currentMinute !== null && currentMinute !== undefined && currentMinute !== "" && Number.isFinite(Number(currentMinute))
      ? Number(currentMinute)
      : (Number.isFinite(fallbackMinute) ? fallbackMinute : 0),
  );
  const range = Number.isFinite(Number(rangeOverride?.startMinute))
    && Number.isFinite(Number(rangeOverride?.endMinute))
    ? { ...defaultRange, ...rangeOverride }
    : defaultRange;
  const labels = diagramTrendPeriodLabels(period, range);
  const minuteSpan = Math.max(1, range.endMinute - range.startMinute);
  const valueSpan = Math.max(1e-9, axis.max - axis.min);
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const xForMinute = (minute) => plot.left + ((Number(minute) - range.startMinute) / minuteSpan) * plotWidth;
  const yForValue = (value) => plot.top + ((axis.max - Number(value)) / valueSpan) * plotHeight;
  const series = Object.fromEntries(DIAGRAM_TREND_SERIES.map((definition) => {
    const sourceSeries = sourcePoints.map((point) => {
      const value = diagramTrendFiniteValue(point?.[definition.key]);
      return value === null ? null : { minute: point.minute, time: point.time, value };
    }).filter(Boolean);
    const renderedPoints = diagramSampleTrendPoints(sourceSeries, targetCount).map((point) => ({
      ...point,
      x: xForMinute(point.minute),
      y: yForValue(point.value),
    }));
    const numericValues = sourceSeries.map((point) => point.value);
    return [definition.key, {
      ...definition,
      renderedPoints,
      polyline: renderedPoints.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" "),
      min: numericValues.length ? Math.min(...numericValues) : null,
      max: numericValues.length ? Math.max(...numericValues) : null,
      latest: numericValues.length ? numericValues[numericValues.length - 1] : null,
    }];
  }));
  const cursorPoints = sourcePoints.map((point) => {
    const scada = diagramTrendFiniteValue(point?.scada);
    const real = diagramTrendFiniteValue(point?.real);
    const hasScada = scada !== null;
    const hasReal = real !== null;
    if (!hasScada && !hasReal) return null;
    return {
      minute: Number(point.minute),
      time: point.time || "--",
      x: xForMinute(point.minute),
      scada: hasScada ? scada : null,
      real: hasReal ? real : null,
      scadaY: hasScada ? yForValue(scada) : null,
      realY: hasReal ? yForValue(real) : null,
    };
  }).filter((point) => point && Number.isFinite(point.minute));
  return {
    empty: values.length === 0,
    period: period === "day" ? "day" : "hour",
    unit: String(unit || ""),
    width,
    height,
    plot,
    range,
    labels,
    axis,
    series,
    cursorPoints,
  };
}

function setDiagramTrendChartModel(interaction, model) {
  if (interaction) {
    interaction.trendChart = model.empty ? null : {
      width: model.width,
      height: model.height,
      plot: model.plot,
      range: model.range,
      points: model.cursorPoints,
      series: model.series,
      unit: model.unit,
    };
  }
}

function diagramTrendAxisTicksHtml(model) {
  const valueSpan = Math.max(1e-9, model.axis.max - model.axis.min);
  const plotHeight = model.height - model.plot.top - model.plot.bottom;
  return model.axis.ticks.map((value) => {
    const y = model.plot.top + ((model.axis.max - Number(value)) / valueSpan) * plotHeight;
    return `
      <g class="diagram-trend-y-tick">
        <line x1="${model.plot.left}" y1="${y.toFixed(2)}" x2="${model.width - model.plot.right}" y2="${y.toFixed(2)}" class="diagram-trend-grid-line"></line>
        <text x="${model.plot.left - 7}" y="${(y + 3.5).toFixed(2)}">${escapeHtml(diagramNumberText(value))}</text>
      </g>`;
  }).join("");
}

function diagramTrendNavigationState(range = {}) {
  const periodNavigationAllowed = range.periodNavigationAllowed !== false;
  const windowOffset = Math.min(0, Math.trunc(Number(range.windowOffset) || 0));
  const minWindowOffset = Math.min(0, Math.trunc(Number(range.minWindowOffset) || 0));
  return {
    visible: periodNavigationAllowed && (minWindowOffset < 0 || windowOffset < 0),
    previousDisabled: !periodNavigationAllowed || windowOffset <= minWindowOffset,
    currentDisabled: !periodNavigationAllowed || windowOffset === 0,
    nextDisabled: !periodNavigationAllowed || windowOffset >= 0,
  };
}

function diagramTrendNavigationHtml(range = {}) {
  const navigation = diagramTrendNavigationState(range);
  return `
    <div class="chart-period-navigation diagram-trend-period-navigation" data-diagram-trend-navigation${navigation.visible ? "" : " hidden"}>
      <button type="button" data-diagram-trend-action="previous" aria-label="上一时段" title="上一时段"${navigation.previousDisabled ? " disabled" : ""}>&#8592;</button>
      <button type="button" data-diagram-trend-action="current" aria-label="回到当前时段" title="回到当前时段"${navigation.currentDisabled ? " disabled" : ""}>&#9673;</button>
      <button type="button" data-diagram-trend-action="next" aria-label="下一时段" title="下一时段"${navigation.nextDisabled ? " disabled" : ""}>&#8594;</button>
    </div>`;
}

function diagramTrendChartHtml(points, period, tooltipWidth = 360, currentMinute = null, unit = "", interaction = null, rangeOverride = null) {
  const model = diagramTrendChartModel(points, period, tooltipWidth, currentMinute, unit, rangeOverride);
  setDiagramTrendChartModel(interaction, model);
  return `
    <div class="diagram-trend-empty" data-diagram-trend-empty${model.empty ? "" : " hidden"}>当前分页暂无历史曲线</div>
    <div class="diagram-trend-legend" data-diagram-trend-legend${model.empty ? " hidden" : ""}>
      <span><i class="is-scada"></i>量测值</span>
      <span><i class="is-real"></i>真值</span>
    </div>
    <svg class="diagram-trend-chart" data-diagram-trend-chart viewBox="0 0 ${model.width} ${model.height}" role="img" aria-label="${model.period === "day" ? "日曲线" : "小时曲线"}"${model.empty ? " hidden" : ""}>
      <text x="${model.plot.left}" y="12" class="diagram-trend-axis-unit" data-diagram-trend-unit>${escapeHtml(model.unit)}</text>
      <g data-diagram-trend-axis-ticks>${diagramTrendAxisTicksHtml(model)}</g>
      <line x1="${model.plot.left}" y1="${model.plot.top}" x2="${model.plot.left}" y2="${model.height - model.plot.bottom}" class="diagram-trend-y-axis"></line>
      <polyline class="diagram-trend-series is-scada" data-diagram-trend-series="scada" points="${model.series.scada.polyline}" fill="none" vector-effect="non-scaling-stroke"></polyline>
      <polyline class="diagram-trend-series is-real" data-diagram-trend-series="real" points="${model.series.real.polyline}" fill="none" vector-effect="non-scaling-stroke"></polyline>
      <line x1="0" y1="${model.plot.top}" x2="0" y2="${model.height - model.plot.bottom}" class="diagram-trend-cursor diagram-trend-cursor-line" data-diagram-trend-cursor data-diagram-trend-cursor-line visibility="hidden"></line>
      <circle cx="0" cy="0" r="3.5" class="diagram-trend-cursor diagram-trend-cursor-point is-scada" data-diagram-trend-cursor data-diagram-trend-cursor-point="scada" visibility="hidden"></circle>
      <circle cx="0" cy="0" r="3.5" class="diagram-trend-cursor diagram-trend-cursor-point is-real" data-diagram-trend-cursor data-diagram-trend-cursor-point="real" visibility="hidden"></circle>
      <g class="diagram-trend-cursor diagram-trend-cursor-label" data-diagram-trend-cursor data-diagram-trend-cursor-label visibility="hidden">
        <rect width="136" height="48" rx="4" ry="4"></rect>
        <text x="7" y="13" data-diagram-trend-cursor-time>--</text>
        <text x="7" y="27" data-diagram-trend-cursor-value="scada">--</text>
        <text x="7" y="41" data-diagram-trend-cursor-value="real">--</text>
      </g>
    </svg>
    <div class="diagram-trend-range" data-diagram-trend-range${model.empty ? " hidden" : ""}><span data-diagram-trend-range-start>${escapeHtml(model.labels.start)}</span><span data-diagram-trend-range-end>${escapeHtml(model.labels.end)}</span></div>
    <div class="diagram-trend-stats" data-diagram-trend-stats${model.empty ? " hidden" : ""}>
      <div><span class="diagram-trend-stat-label is-scada">量测值</span><span>最小 <strong data-diagram-trend-stat-scada-min>${model.series.scada.min === null ? "--" : diagramNumberText(model.series.scada.min)}</strong></span><span>最大 <strong data-diagram-trend-stat-scada-max>${model.series.scada.max === null ? "--" : diagramNumberText(model.series.scada.max)}</strong></span><span>最新 <strong data-diagram-trend-stat-scada-latest>${model.series.scada.latest === null ? "--" : diagramNumberText(model.series.scada.latest)}</strong></span></div>
      <div><span class="diagram-trend-stat-label is-real">真值</span><span>最小 <strong data-diagram-trend-stat-real-min>${model.series.real.min === null ? "--" : diagramNumberText(model.series.real.min)}</strong></span><span>最大 <strong data-diagram-trend-stat-real-max>${model.series.real.max === null ? "--" : diagramNumberText(model.series.real.max)}</strong></span><span>最新 <strong data-diagram-trend-stat-real-latest>${model.series.real.latest === null ? "--" : diagramNumberText(model.series.real.latest)}</strong></span></div>
    </div>`;
}

function syncDiagramTrendNavigation(tooltip, range = {}) {
  const container = tooltip?.querySelector?.("[data-diagram-trend-navigation]");
  if (!container) return false;
  const navigation = diagramTrendNavigationState(range);
  container.hidden = !navigation.visible;
  container.dataset.windowOffset = String(Number(range.windowOffset) || 0);
  const previous = container.querySelector('[data-diagram-trend-action="previous"]');
  const current = container.querySelector('[data-diagram-trend-action="current"]');
  const next = container.querySelector('[data-diagram-trend-action="next"]');
  if (previous) previous.disabled = navigation.previousDisabled;
  if (current) current.disabled = navigation.currentDisabled;
  if (next) next.disabled = navigation.nextDisabled;
  return true;
}

function hideDiagramTrendCursor(interaction) {
  if (interaction) interaction.trendCursorClientX = null;
  interaction?.tooltip?.querySelectorAll("[data-diagram-trend-cursor]").forEach((element) => {
    element.setAttribute("visibility", "hidden");
  });
}

function syncDiagramTrendAxisTicks(group, model) {
  if (!group || !model) return false;
  const valueSpan = Math.max(1e-9, model.axis.max - model.axis.min);
  const plotHeight = model.height - model.plot.top - model.plot.bottom;
  const existing = Array.from(group.children);
  model.axis.ticks.forEach((value, index) => {
    let tick = existing[index];
    if (!tick) {
      tick = document.createElementNS("http://www.w3.org/2000/svg", "g");
      tick.classList.add("diagram-trend-y-tick");
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.classList.add("diagram-trend-grid-line");
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      tick.append(line, text);
    }
    const y = model.plot.top + ((model.axis.max - Number(value)) / valueSpan) * plotHeight;
    const line = tick.querySelector("line");
    const text = tick.querySelector("text");
    line?.setAttribute("x1", String(model.plot.left));
    line?.setAttribute("y1", y.toFixed(2));
    line?.setAttribute("x2", String(model.width - model.plot.right));
    line?.setAttribute("y2", y.toFixed(2));
    text?.setAttribute("x", String(model.plot.left - 7));
    text?.setAttribute("y", (y + 3.5).toFixed(2));
    if (text) text.textContent = diagramNumberText(value);
    group.appendChild(tick);
  });
  existing.slice(model.axis.ticks.length).forEach((element) => element.remove());
  return true;
}

function updateDiagramTrendChart(content, points, period, tooltipWidth, currentMinute, unit, interaction, rangeOverride = null) {
  if (!content) return false;
  const model = diagramTrendChartModel(points, period, tooltipWidth, currentMinute, unit, rangeOverride);
  setDiagramTrendChartModel(interaction, model);
  const empty = content.querySelector("[data-diagram-trend-empty]");
  const legend = content.querySelector("[data-diagram-trend-legend]");
  const chart = content.querySelector("[data-diagram-trend-chart]");
  const tickGroup = content.querySelector("[data-diagram-trend-axis-ticks]");
  const seriesElements = Object.fromEntries(DIAGRAM_TREND_SERIES.map((series) => [
    series.key,
    content.querySelector(`[data-diagram-trend-series="${series.key}"]`),
  ]));
  const range = content.querySelector("[data-diagram-trend-range]");
  const stats = content.querySelector("[data-diagram-trend-stats]");
  if (!empty || !legend || !chart || !tickGroup || !range || !stats || Object.values(seriesElements).some((element) => !element)) return false;
  empty.hidden = !model.empty;
  legend.hidden = model.empty;
  chart.toggleAttribute("hidden", model.empty);
  range.hidden = model.empty;
  stats.hidden = model.empty;
  if (model.empty) {
    hideDiagramTrendCursor(interaction);
    return true;
  }
  chart.setAttribute("aria-label", model.period === "day" ? "日曲线" : "小时曲线");
  const unitElement = chart.querySelector("[data-diagram-trend-unit]");
  if (unitElement) unitElement.textContent = model.unit;
  syncDiagramTrendAxisTicks(tickGroup, model);
  DIAGRAM_TREND_SERIES.forEach((definition) => {
    seriesElements[definition.key].setAttribute("points", model.series[definition.key].polyline);
  });
  const rangeStart = range.querySelector("[data-diagram-trend-range-start]");
  const rangeEnd = range.querySelector("[data-diagram-trend-range-end]");
  if (rangeStart) rangeStart.textContent = model.labels.start;
  if (rangeEnd) rangeEnd.textContent = model.labels.end;
  DIAGRAM_TREND_SERIES.forEach((definition) => {
    ["min", "max", "latest"].forEach((field) => {
      const element = stats.querySelector(`[data-diagram-trend-stat-${definition.key}-${field}]`);
      const value = model.series[definition.key][field];
      if (element) element.textContent = value === null ? "--" : diagramNumberText(value);
    });
  });
  if (Number.isFinite(interaction?.trendCursorClientX)) {
    updateDiagramTrendCursor(interaction, chart, { clientX: interaction.trendCursorClientX });
  }
  return true;
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
  interaction.trendCursorClientX = Number(event.clientX);
  const targetMinute = model.range.startMinute
    + ((viewX - model.plot.left) / plotWidth) * (model.range.endMinute - model.range.startMinute);
  const point = diagramNearestTrendPoint(model.points, targetMinute);
  const line = chart.querySelector("[data-diagram-trend-cursor-line]");
  const markers = Object.fromEntries(DIAGRAM_TREND_SERIES.map((series) => [
    series.key,
    chart.querySelector(`[data-diagram-trend-cursor-point="${series.key}"]`),
  ]));
  const label = chart.querySelector("[data-diagram-trend-cursor-label]");
  const timeText = chart.querySelector("[data-diagram-trend-cursor-time]");
  const valueTexts = Object.fromEntries(DIAGRAM_TREND_SERIES.map((series) => [
    series.key,
    chart.querySelector(`[data-diagram-trend-cursor-value="${series.key}"]`),
  ]));
  if (!point || !line || !label || !timeText || Object.values(markers).some((element) => !element) || Object.values(valueTexts).some((element) => !element)) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  line.setAttribute("x1", point.x.toFixed(2));
  line.setAttribute("x2", point.x.toFixed(2));
  const pointYs = DIAGRAM_TREND_SERIES.flatMap((series) => {
    const y = diagramTrendFiniteValue(point[`${series.key}Y`]);
    return y === null ? [] : [y];
  });
  const anchorY = pointYs.length ? Math.min(...pointYs) : model.plot.top;
  const labelWidth = 136;
  const labelHeight = 48;
  const labelGap = 8;
  const maxLabelX = model.width - model.plot.right - labelWidth - 2;
  const labelX = Math.max(model.plot.left + 2, Math.min(point.x + labelGap, maxLabelX));
  const preferredY = anchorY - labelHeight - labelGap;
  const fallbackY = anchorY + labelGap;
  const labelY = Math.max(
    model.plot.top + 2,
    Math.min(preferredY >= model.plot.top ? preferredY : fallbackY, model.height - model.plot.bottom - labelHeight - 2),
  );
  label.setAttribute("transform", `translate(${labelX.toFixed(2)} ${labelY.toFixed(2)})`);
  timeText.textContent = point.time || "--";
  DIAGRAM_TREND_SERIES.forEach((series) => {
    const value = diagramTrendFiniteValue(point[series.key]);
    const y = diagramTrendFiniteValue(point[`${series.key}Y`]);
    const available = value !== null && y !== null;
    markers[series.key].setAttribute("cx", point.x.toFixed(2));
    if (available) markers[series.key].setAttribute("cy", y.toFixed(2));
    markers[series.key].setAttribute("visibility", available ? "visible" : "hidden");
    const text = available ? diagramNumberText(value) : "--";
    valueTexts[series.key].textContent = `${series.label} ${model.unit && available ? `${text} ${model.unit}` : text}`;
  });
  line.setAttribute("visibility", "visible");
  label.setAttribute("visibility", "visible");
}

function diagramMetricTooltipData(container, hover, snapshot, interaction) {
  const pair = diagramMetricMeasurementPair(hover, snapshot);
  const row = pair.row || diagramMetricCurrentRow(container, hover, snapshot);
  const metricType = hover?.binding?.metricType || hover?.metricType || "";
  const scadaValue = diagramTrendDisplayValue(pair.scadaValue, pair.scadaRow || row, metricType);
  const realValue = diagramTrendDisplayValue(pair.realValue, pair.realRow || row, metricType);
  const deviation = scadaValue !== null && realValue !== null ? scadaValue - realValue : null;
  const unit = row?.unit || diagramMeasurementUnit(row?.meas_type || metricType);
  const period = interaction.trendPeriod === "day" ? "day" : "hour";
  const history = diagramTrendHistorySeries(pair.scadaRow || pair.realRow || row, metricType);
  const endMinute = Number(snapshot?.clock?.absolute_minute ?? snapshot?.clock?.minute);
  const requestedOffset = Number(interaction?.trendPeriodOffsets?.[period]) || 0;
  const trendRange = diagramTrendNavigationRange(
    history,
    period,
    Number.isFinite(endMinute) ? endMinute : null,
    requestedOffset,
    simulationModeDurationMinutes(),
  );
  if (interaction) {
    interaction.trendPeriodOffsets = {
      ...(interaction.trendPeriodOffsets || { hour: 0, day: 0 }),
      [period]: trendRange.windowOffset,
    };
    interaction.trendNavigationRange = trendRange;
  }
  const windowPoints = diagramTrendWindowPoints(
    history,
    period,
    Number.isFinite(endMinute) ? endMinute : null,
    trendRange.windowOffset,
    trendRange,
  );
  const medianDeviationRaw = diagramTrendFiniteValue(pair.medianDeviation) ?? 0;
  const medianDeviation = diagramTrendDisplayValue(
    medianDeviationRaw,
    pair.row || row,
    metricType,
  ) ?? medianDeviationRaw;
  const medianDeviationScale = medianDeviationRaw === 0
    ? (diagramTrendDisplayValue(1, pair.row || row, metricType) ?? 1)
    : medianDeviation / medianDeviationRaw;
  const deviceName = hover?.binding?.devName || row?.dev_name || row?.name || "动态量测";
  const metricLabel = diagramMetricLabel(metricType, row);
  const validText = pair.row || pair.definition
    ? diagramMeasurementStatusLabel(pair.status, pair.valid)
    : "缺失";
  return {
    deviceName,
    metricLabel,
    displayText: formatMeasurementDisplayValue(scadaValue, pair.row, diagramNumberText),
    scadaValue,
    scadaText: formatMeasurementDisplayValue(scadaValue, pair.row, diagramNumberText),
    realValue,
    realText: formatMeasurementDisplayValue(realValue, pair.row, diagramNumberText),
    deviation,
    deviationText: formatMeasurementDisplayValue(deviation, pair.row, diagramNumberText),
    medianDeviation,
    medianDeviationRaw,
    medianDeviationScale,
    medianDeviationText: formatMeasurementDisplayValue(medianDeviation, pair.row, diagramNumberText),
    valid: pair.valid,
    status: pair.status,
    statusText: validText,
    fixedValue: pair.fixedValue,
    fixedValueText: pair.fixedValue === null ? "--" : diagramNumberText(pair.fixedValue),
    unit: String(unit || ""),
    validText,
    weight: pair.weight,
    errorSigma: pair.errorSigma,
    errorSigmaText: pair.errorSigma === null ? "--" : String(pair.errorSigma),
    definition: pair.definition,
    measurementName: pair.name,
    devType: pair.devType,
    devName: pair.devName,
    measType: pair.measType,
    period,
    endMinute: Number.isFinite(endMinute) ? endMinute : null,
    trendRange,
    windowPoints,
  };
}

function ensureDiagramMetricMeasurementHistory(container, hover, snapshot, interaction) {
  const pair = diagramMetricMeasurementPair(hover, snapshot);
  const row = pair.scadaRow || pair.realRow || pair.row || diagramMetricCurrentRow(container, hover, snapshot);
  if (!row) return;
  const hoverKey = String(hover?.key || "");
  ensureMeasurementHistoryForRow(row).then((changed) => {
    const current = diagramInteractionCache.get(container);
    if (
      changed
      && current === interaction
      && String(current?.hover?.key || "") === hoverKey
      && !current?.tooltip?.hidden
    ) {
      refreshDiagramTooltip(container, current.snapshot || state.snapshot || {});
    }
  });
}

function diagramMeasurementValueWithUnit(text, unit) {
  return text === "--" || !unit ? text : `${text} ${unit}`;
}

function renderDiagramMeasurementStatusOptions(selected, disabled = false) {
  return Object.entries(DIAGRAM_MEASUREMENT_STATUS_LABELS).map(([value, label]) => (
    `<option value="${value}" ${value === selected ? "selected" : ""}>${label}</option>`
  )).join("");
}

function renderDiagramMeasurementSummary(data, editor = null, interaction = null) {
  const editing = Boolean(editor);
  const editableDefinition = Boolean(data.definition);
  const measurementEditableAttr = !editing && editableDefinition ? 'data-diagram-definition-editable="measurement"' : "";
  const status = diagramMeasurementStatus(editor?.draft?.status ?? data.status, data.valid);
  const statusValue = editing
    ? `<select class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="status" data-diagram-measurement-valid ${interaction?.definitionSaving ? "disabled" : ""}>${renderDiagramMeasurementStatusOptions(status)}</select>`
    : `<span data-diagram-measurement-valid>${escapeHtml(diagramMeasurementStatusLabel(status, data.valid))}</span>`;
  const sigmaValue = editing
    ? `<input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="errorSigma" data-diagram-measurement-sigma type="number" min="0" step="any" value="${escapeHtml(editor.draft.errorSigma)}" ${interaction?.definitionSaving ? "disabled" : ""}>`
    : `<span data-diagram-measurement-sigma>${escapeHtml(data.errorSigmaText)}</span>`;
  const medianDeviationValue = editing
    ? `<div class="diagram-definition-input-wrap"><input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="medianDeviation" type="number" step="any" value="${escapeHtml(editor.draft.medianDeviation)}" ${interaction?.definitionSaving ? "disabled" : ""}>${data.unit ? `<small>${escapeHtml(data.unit)}</small>` : ""}</div>`
    : escapeHtml(diagramMeasurementValueWithUnit(data.medianDeviationText, data.unit));
  const fixedValue = editing ? editor.draft.fixedValue : data.fixedValue;
  const fixedValueText = fixedValue === null || fixedValue === undefined || fixedValue === ""
    ? "--"
    : diagramNumberText(fixedValue);
  const fixedValueCell = status === "fixed"
    ? `<div>
        <dt>固定值</dt>
        <dd data-diagram-measurement-fixed-value ${measurementEditableAttr}>${editing
          ? `<input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="fixedValue" type="number" step="any" value="${escapeHtml(fixedValueText)}" ${interaction?.definitionSaving ? "disabled" : ""}>`
          : escapeHtml(fixedValueText)}</dd>
      </div>`
    : "";
  return `
    <dl class="diagram-measurement-summary">
      <div>
        <dt>量测值</dt>
        <dd><strong data-diagram-tooltip-current-value data-diagram-measurement-scada>${escapeHtml(data.scadaText)}</strong><span data-diagram-tooltip-current-unit>${escapeHtml(data.unit)}</span></dd>
      </div>
      <div>
        <dt>真值</dt>
        <dd data-diagram-measurement-real>${escapeHtml(diagramMeasurementValueWithUnit(data.realText, data.unit))}</dd>
      </div>
      <div>
        <dt>当前偏差</dt>
        <dd data-diagram-measurement-deviation>${escapeHtml(diagramMeasurementValueWithUnit(data.deviationText, data.unit))}</dd>
      </div>
      <div>
        <dt>量测状态</dt>
        <dd data-diagram-tooltip-validity ${measurementEditableAttr}>${statusValue}</dd>
      </div>
      <div>
        <dt>误差 σ</dt>
        <dd ${measurementEditableAttr}>${sigmaValue}</dd>
      </div>
      <div>
        <dt>中值偏差</dt>
        <dd data-diagram-measurement-median-deviation ${measurementEditableAttr}>${medianDeviationValue}</dd>
      </div>
      ${fixedValueCell}
    </dl>`;
}

function syncDiagramMeasurementDefinitionFields(editor, changedField = "") {
  if (!editor || editor.kind !== "measurement") return { valid: false, error: "量测定义编辑器无效" };
  const sigma = Number(editor.draft.errorSigma);
  const weight = Number(editor.draft.weight);
  if (changedField === "errorSigma" && Number.isFinite(sigma) && sigma > 0) {
    editor.draft.weight = String(diagramDefinitionWeightFromSigma(sigma));
  } else if (changedField === "weight" && Number.isFinite(weight) && weight > 0) {
    editor.draft.errorSigma = String(diagramDefinitionSigmaFromWeight(weight));
  }
  const nextSigma = Number(editor.draft.errorSigma);
  const nextWeight = Number(editor.draft.weight);
  const nextMedianDeviation = Number(editor.draft.medianDeviation);
  const nextStatus = diagramMeasurementStatus(editor.draft.status, editor.original?.valid);
  editor.draft.status = nextStatus;
  const nextFixedValue = Number(editor.draft.fixedValue);
  let error = "";
  if (!Number.isFinite(nextSigma) || nextSigma <= 0) error = "误差 σ 必须大于 0";
  else if (!Number.isFinite(nextWeight) || nextWeight <= 0) error = "权重必须大于 0";
  else if (!Number.isFinite(nextMedianDeviation)) error = "中值偏差必须为有限数字";
  else if (nextStatus === "fixed" && !Number.isFinite(nextFixedValue)) error = "固定值必须为有限数字";
  editor.validationError = error;
  return { valid: !error, error };
}

function renderDiagramMeasurementDefinitionEditor(editor, interaction) {
  syncDiagramMeasurementDefinitionFields(editor);
  const canSave = editor.dirtyFields?.size > 0
    && !editor.validationError
    && !interaction?.definitionSaving;
  return `
    <div class="diagram-definition-actions diagram-definition-head-actions diagram-measurement-definition-editor" data-diagram-definition-actions="measurement">
      <button type="button" data-diagram-definition-cancel>取消</button>
      <button type="button" class="primary" data-diagram-definition-save="measurement" ${canSave ? "" : "disabled"}>
        ${interaction?.definitionSaving ? "保存中" : "保存"}
      </button>
    </div>`;
}

function beginDiagramMeasurementDefinitionEdit(container) {
  const interaction = diagramInteractionState(container);
  const snapshot = interaction.snapshot || state.snapshot || {};
  const data = diagramMetricTooltipData(
    container,
    interaction.hover,
    snapshot,
    interaction,
  );
  if (!data.definition || !data.measurementName) return false;
  const originalWeight = data.weight === null ? String(data.definition.weight ?? "") : String(data.weight);
  const originalSigma = data.errorSigma === null ? "" : String(data.errorSigma);
  const originalMedianDeviation = String(data.medianDeviation ?? 0);
  interaction.definitionEditor = {
    kind: "measurement",
    name: data.measurementName,
    devType: data.devType,
    devName: data.devName,
    measType: data.measType,
    revision: Number(snapshot?.static_meta?.definitions?.revision),
    original: {
      weight: originalWeight,
      errorSigma: originalSigma,
      medianDeviation: originalMedianDeviation,
      status: data.status,
      fixedValue: data.fixedValue === null ? "" : String(data.fixedValue),
      valid: String(data.valid),
    },
    draft: {
      weight: originalWeight,
      errorSigma: originalSigma,
      medianDeviation: originalMedianDeviation,
      status: data.status,
      fixedValue: data.fixedValue === null ? "" : String(data.fixedValue),
      valid: String(data.valid),
    },
    dirtyFields: new Set(),
    medianDeviationScale: Number(data.medianDeviationScale) || 1,
    validationError: "",
  };
  interaction.definitionSaving = false;
  interaction.definitionLeavePrompt = false;
  interaction.definitionCloseAfterSave = false;
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  interaction.tooltip?.classList.add("is-editing-definition");
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

function updateDiagramMeasurementDefinitionDraft(interaction, input) {
  const editor = interaction?.definitionEditor;
  if (editor?.kind !== "measurement") return false;
  const field = String(input?.getAttribute?.("data-diagram-measurement-definition-field") || "");
  if (!["errorSigma", "weight", "medianDeviation", "status", "fixedValue"].includes(field)) return false;
  editor.draft[field] = String(input.value ?? "");
  if (field === "errorSigma" || field === "weight") {
    syncDiagramMeasurementDefinitionFields(editor, field);
    ["errorSigma", "weight"].forEach((pairedField) => {
      if (diagramDefinitionPendingValuesEqual(
        pairedField,
        editor.original[pairedField],
        editor.draft[pairedField],
        "measurement",
      )) editor.dirtyFields.delete(pairedField);
      else editor.dirtyFields.add(pairedField);
    });
    const counterpartField = field === "errorSigma" ? "weight" : "errorSigma";
    const counterpart = interaction.tooltip?.querySelector(`[data-diagram-measurement-definition-field="${counterpartField}"]`);
    if (counterpart) counterpart.value = editor.draft[counterpartField];
  } else if (field === "status") {
    syncDiagramMeasurementDefinitionFields(editor, field);
    if (String(editor.draft.status) === String(editor.original.status)) editor.dirtyFields.delete("status");
    else editor.dirtyFields.add("status");
    if (editor.draft.status !== "fixed") {
      editor.dirtyFields.delete("fixedValue");
    } else if (String(editor.draft.fixedValue) === String(editor.original.fixedValue)) {
      editor.dirtyFields.delete("fixedValue");
    } else {
      editor.dirtyFields.add("fixedValue");
    }
  } else if (field === "medianDeviation") {
    syncDiagramMeasurementDefinitionFields(editor, field);
    if (String(editor.draft.medianDeviation) === String(editor.original.medianDeviation)) {
      editor.dirtyFields.delete("medianDeviation");
    } else {
      editor.dirtyFields.add("medianDeviation");
    }
  } else {
    syncDiagramMeasurementDefinitionFields(editor, field);
    if (String(editor.draft.fixedValue) === String(editor.original.fixedValue)) editor.dirtyFields.delete("fixedValue");
    else editor.dirtyFields.add("fixedValue");
  }
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  const message = interaction.tooltip?.querySelector("[data-diagram-definition-message]");
  if (message) {
    message.textContent = editor.validationError || "";
    message.classList.toggle("is-warning", Boolean(editor.validationError));
    message.hidden = !editor.validationError;
  }
  updateDiagramDefinitionSaveState(interaction);
  if (field === "status") renderActiveDiagramTooltip(interaction.container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

async function saveDiagramMeasurementDefinitionEdit(container) {
  const interaction = diagramInteractionCache.get(container);
  const editor = interaction?.definitionEditor;
  if (!interaction || editor?.kind !== "measurement" || interaction.definitionSaving) return false;
  const validation = syncDiagramMeasurementDefinitionFields(editor);
  if (!validation.valid || !editor.dirtyFields.size) {
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    updateDiagramDefinitionSaveState(interaction);
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
    return false;
  }
  const closeAfterSave = Boolean(interaction.definitionCloseAfterSave);
  interaction.definitionSaving = true;
  interaction.definitionMessage = "正在更新后台定义并保存人工覆盖层";
  interaction.definitionMessageWarning = false;
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  try {
    const result = await api("/api/definitions/measurement", {
      method: "POST",
      body: JSON.stringify({
        name: editor.name,
        dev_type: editor.devType,
        dev_name: editor.devName,
        meas_type: editor.measType,
        revision: editor.revision,
        changes: {
          weight: Number(editor.draft.weight),
          error_sigma: Number(editor.draft.errorSigma),
          ...(editor.dirtyFields.has("medianDeviation") ? {
            median_deviation: Number(editor.draft.medianDeviation) / (Number(editor.medianDeviationScale) || 1),
          } : {}),
          status: editor.draft.status,
          ...(editor.draft.status === "fixed" ? { fixed_value: Number(editor.draft.fixedValue) } : {}),
        },
      }),
    });
    applyDefinitionEditResult(result);
    editor.revision = Number(
      result?.revision
      ?? result?.static_meta?.definitions?.revision
      ?? editor.revision,
    );
    interaction.snapshot = state.snapshot;
    interaction.definitionSaving = false;
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    const resultWarning = definitionEditResultHasWarning(result);
    interaction.definitionMessageWarning = resultWarning;
    if (resultWarning) {
      interaction.definitionSaving = false;
      interaction.definitionLeavePrompt = false;
      interaction.definitionCloseAfterSave = false;
      interaction.definitionMessage = result.warning || "后台定义已更新，但人工覆盖层保存未完成，请重试";
      interaction.definitionMessageWarning = true;
      renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
      return false;
    }
    interaction.definitionEditor = null;
    interaction.definitionMessage = resultWarning
      ? (result.warning || "后台定义已更新，但人工覆盖层保存未完成，请重试")
      : "后台定义及人工覆盖层已保存";
    interaction.definitionMessageWarning = resultWarning;
    interaction.tooltip?.classList.remove("is-editing-definition");
    if (closeAfterSave) hideDiagramTooltip(container);
    else renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
    return true;
  } catch (error) {
    interaction.definitionSaving = false;
    interaction.definitionCloseAfterSave = false;
    interaction.definitionMessage = apiErrorText(error);
    interaction.definitionMessageWarning = true;
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
    return false;
  }
}

function renderDiagramMetricTooltip(container, hover, snapshot, interaction) {
  const data = diagramMetricTooltipData(container, hover, snapshot, interaction);
  const leavePrompt = renderDiagramDefinitionLeavePrompt(interaction);
  if (leavePrompt) {
    return `
      <div class="diagram-tooltip-head">
        <strong data-diagram-tooltip-device-name>${escapeHtml(data.deviceName)}</strong>
        <span>${escapeHtml(data.metricLabel)}</span>
      </div>
      <div class="diagram-metric-current">${leavePrompt}</div>`;
  }
  const editor = interaction?.definitionEditor?.kind === "measurement"
    && interaction.definitionEditor.name === data.measurementName
    ? interaction.definitionEditor
    : null;
  return `
    <div class="diagram-tooltip-head">
      <strong data-diagram-tooltip-device-name>${escapeHtml(data.deviceName)}</strong>
      <div class="diagram-tooltip-head-controls">
        <span data-diagram-tooltip-metric-label>${escapeHtml(data.metricLabel)}</span>
        ${editor ? renderDiagramMeasurementDefinitionEditor(editor, interaction) : ""}
      </div>
    </div>
    <div class="diagram-metric-current" data-diagram-measurement-summary>
      ${renderDiagramMeasurementSummary(data, editor, interaction)}
      ${editor ? diagramDefinitionEditorMessageHtml(interaction, editor.validationError) : ""}
    </div>
    ${!editor ? diagramDefinitionMessageHtml(interaction) : ""}
    <div class="diagram-trend-tabs" role="tablist" aria-label="量测趋势范围">
      <button type="button" data-diagram-trend-period="hour" class="${data.period === "hour" ? "is-active" : ""}" aria-selected="${data.period === "hour"}">小时曲线</button>
      <button type="button" data-diagram-trend-period="day" class="${data.period === "day" ? "is-active" : ""}" aria-selected="${data.period === "day"}">日曲线</button>
      ${diagramTrendNavigationHtml(data.trendRange)}
    </div>
    <div class="diagram-trend-content" data-diagram-trend-content>
      ${diagramTrendChartHtml(data.windowPoints, data.period, interaction.tooltip?.clientWidth || 360, data.endMinute, data.unit, interaction, data.trendRange)}
    </div>`;
}

function updateDiagramMetricDynamicValues(tooltip, data) {
  if (!tooltip || !data) return false;
  const values = [
    ["[data-diagram-tooltip-device-name]", data.deviceName],
    ["[data-diagram-tooltip-metric-label]", data.metricLabel],
    ["[data-diagram-measurement-scada]", data.scadaText],
    ["[data-diagram-tooltip-current-unit]", data.unit],
    ["[data-diagram-measurement-real]", diagramMeasurementValueWithUnit(data.realText, data.unit)],
    ["[data-diagram-measurement-deviation]", diagramMeasurementValueWithUnit(data.deviationText, data.unit)],
    ["[data-diagram-measurement-median-deviation]", diagramMeasurementValueWithUnit(data.medianDeviationText, data.unit)],
    ["[data-diagram-measurement-valid]", data.validText],
    ["[data-diagram-measurement-sigma]", data.errorSigmaText],
    ["[data-diagram-measurement-fixed-value]", data.fixedValueText],
  ];
  let updated = true;
  values.forEach(([selector, value]) => {
    const element = tooltip.querySelector(selector);
    if (!element) {
      if (selector === "[data-diagram-measurement-fixed-value]") return;
      updated = false;
      return;
    }
    if (!["INPUT", "SELECT", "TEXTAREA"].includes(element.tagName) && !element.querySelector("input,select,textarea")) element.textContent = value;
  });
  const statusControl = tooltip.querySelector('[data-diagram-measurement-definition-field="status"]');
  const expectedStatus = diagramMeasurementStatus(
    statusControl?.value || data.status,
    data.valid,
  );
  const hasFixedValueRow = Boolean(tooltip.querySelector("[data-diagram-measurement-fixed-value]"));
  if ((expectedStatus === "fixed") !== hasFixedValueRow) updated = false;
  return updated;
}

function updateDiagramMetricTooltip(container, hover, snapshot, interaction) {
  const tooltip = interaction?.tooltip;
  if (!tooltip) return false;
  const data = diagramMetricTooltipData(container, hover, snapshot, interaction);
  const content = tooltip.querySelector("[data-diagram-trend-content]");
  if (!content || !updateDiagramMetricDynamicValues(tooltip, data)) return false;
  tooltip.querySelectorAll("[data-diagram-trend-period]").forEach((button) => {
    const selected = button.getAttribute("data-diagram-trend-period") === data.period;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  if (!syncDiagramTrendNavigation(tooltip, data.trendRange)) return false;
  return updateDiagramTrendChart(
    content,
    data.windowPoints,
    data.period,
    interaction.tooltip?.clientWidth || 360,
    data.endMinute,
    data.unit,
    interaction,
    data.trendRange,
  );
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
  interaction.deviceTooltipHostKey = "";
  interaction.deviceTooltipTabKey = "self";
  interaction.tooltipPositionKey = "";
  interaction.trendPeriodOffsets = { hour: 0, day: 0 };
  interaction.trendNavigationRange = null;
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
  interaction.hideTimer = setTimeout(() => {
    interaction.hideTimer = null;
    if (interaction.definitionSaving || interaction.definitionLeavePrompt) return;
    if (!interaction.definitionEditor) {
      hideDiagramTooltip(container);
      return;
    }
    if (!diagramDefinitionEditorPendingChanges(interaction.definitionEditor).length) {
      interaction.definitionEditor = null;
      interaction.definitionCloseAfterSave = false;
      interaction.tooltip?.classList.remove("is-editing-definition");
      hideDiagramTooltip(container);
      return;
    }
    interaction.definitionLeavePrompt = true;
    interaction.definitionCloseAfterSave = false;
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  }, DIAGRAM_TOOLTIP_HIDE_DELAY_MS);
}

function renderActiveDiagramTooltip(container, snapshot, interaction) {
  const hover = interaction?.hover;
  const tooltip = interaction?.tooltip;
  if (!hover || !tooltip) return false;
  hideDiagramTrendCursor(interaction);
  interaction.trendChart = null;
  const html = hover.kind === "metric"
    ? renderDiagramMetricTooltip(container, hover, snapshot, interaction)
    : renderDiagramDeviceTooltip(container, hover, snapshot, interaction);
  if (!html) {
    hideDiagramTooltip(container);
    return false;
  }
  tooltip.dataset.kind = hover.kind;
  tooltip.dataset.hoverKey = String(hover.key || "");
  tooltip.innerHTML = html;
  tooltip.hidden = false;
  tooltip.classList.add("is-visible");
  tooltip.classList.toggle("is-editing-definition", diagramDefinitionEditPinned(interaction));
  positionDiagramTooltip(interaction);
  if (hover.kind === "metric") {
    ensureDiagramMetricMeasurementHistory(container, hover, snapshot, interaction);
  }
  return true;
}

function refreshDiagramTooltip(container, snapshot = state.snapshot || {}) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  interaction.snapshot = snapshot;
  if (!interaction.hover || !interaction.tooltip) return;
  const hoverKey = String(interaction.hover.key || "");
  if (interaction.tooltip.hidden || interaction.tooltip.dataset.hoverKey !== hoverKey) {
    renderActiveDiagramTooltip(container, snapshot, interaction);
    return;
  }
  const updated = interaction.hover.kind === "metric"
    ? updateDiagramMetricTooltip(container, interaction.hover, snapshot, interaction)
    : updateDiagramDeviceTooltip(container, interaction.hover, snapshot, interaction);
  if (interaction.hover.kind === "metric") {
    ensureDiagramMetricMeasurementHistory(container, interaction.hover, snapshot, interaction);
  }
  if (!updated) renderActiveDiagramTooltip(container, snapshot, interaction);
}

function resetDiagramInteractions(container) {
  if (!container) return;
  const interaction = diagramInteractionCache.get(container);
  if (interaction) {
    clearDiagramTooltipHide(interaction);
    closeDiagramContextMenu(interaction);
    if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
    interaction.selectedDevId = "";
    interaction.hover = null;
    interaction.deviceTooltipHostKey = "";
    interaction.deviceTooltipTabKey = "self";
    interaction.snapshot = null;
    interaction.tooltipPositionKey = "";
    interaction.trendPeriodOffsets = { hour: 0, day: 0 };
    interaction.trendNavigationRange = null;
    interaction.definitionEditor = null;
    interaction.definitionSaving = false;
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    interaction.definitionMessage = "";
    interaction.definitionMessageWarning = false;
    hideDiagramTrendCursor(interaction);
    interaction.trendChart = null;
    interaction.drag = null;
    interaction.suppressClick = false;
    interaction.suppressClickTimer = null;
    if (interaction.tooltip) {
      interaction.tooltip.hidden = true;
      interaction.tooltip.classList.remove("is-visible");
      interaction.tooltip.classList.remove("is-editing-definition");
    }
  }
  removeDiagramRuntimeLabels(container);
  removeDiagramFlowArrows(container);
  container.classList.remove("is-diagram-panning");
  container.querySelectorAll(".is-diagram-selected").forEach((element) => element.classList.remove("is-diagram-selected"));
  diagramDeviceIndexCache.delete(container);
  diagramMetricBindingCache.delete(container);
  diagramRealtimeBindingCache.delete(container);
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
  const viewport = {
    svg,
    source: { ...original },
    original: { ...original },
    current: { ...original },
  };
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
  const contextMenu = document.createElement("div");
  contextMenu.className = "diagram-context-menu";
  contextMenu.hidden = true;
  contextMenu.setAttribute("role", "menu");
  contextMenu.setAttribute("aria-label", "接线图显示选项");
  document.body.appendChild(contextMenu);
  interaction.contextMenu = contextMenu;
  renderDiagramContextMenu(interaction);

  container.addEventListener("pointerdown", (event) => {
    closeDiagramContextMenu(interaction);
    beginDiagramPan(container, event);
  });
  container.addEventListener("pointermove", (event) => {
    interaction.pointer = { x: event.clientX, y: event.clientY };
    if (moveDiagramPan(container, event)) return;
    if (diagramDefinitionEditPinned(interaction)) return;
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
    if (String(interaction.hover?.key || "") !== String(nextHover.key || "")) {
      interaction.trendPeriodOffsets = { hour: 0, day: 0 };
      interaction.trendNavigationRange = null;
    }
    interaction.hover = nextHover;
    if (tooltipAction === "refresh") {
      refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
    } else if (tooltipAction === "position") {
      positionDiagramTooltip(interaction);
    }
  });
  container.addEventListener("pointerup", (event) => finishDiagramPan(container, event));
  container.addEventListener("pointercancel", (event) => finishDiagramPan(container, event));
  container.addEventListener("contextmenu", (event) => {
    const viewport = diagramViewportState(container);
    const target = diagramInteractionEventTarget(container, viewport, event);
    const hover = target ? diagramHoverTarget(container, target) : null;
    const action = diagramContextMenuAction(hover?.kind || "", Boolean(target));
    if (action !== "open") {
      closeDiagramContextMenu(interaction);
      return;
    }
    event.preventDefault();
    hideDiagramTooltip(container);
    openDiagramContextMenu(interaction, event);
  });
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
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const leaveAction = target.closest("[data-diagram-definition-leave-action]");
    if (leaveAction) {
      clearDiagramTooltipHide(interaction);
      const action = leaveAction.getAttribute("data-diagram-definition-leave-action") || "";
      if (action === "save") {
        interaction.definitionLeavePrompt = false;
        interaction.definitionCloseAfterSave = true;
        if (interaction.definitionEditor?.kind === "measurement") {
          saveDiagramMeasurementDefinitionEdit(container);
        } else {
          saveDiagramDeviceDefinitionEdit(container);
        }
      } else if (action === "discard") {
        interaction.definitionEditor = null;
        interaction.definitionSaving = false;
        interaction.definitionLeavePrompt = false;
        interaction.definitionCloseAfterSave = false;
        interaction.definitionMessage = "";
        interaction.definitionMessageWarning = false;
        interaction.tooltip?.classList.remove("is-editing-definition");
        hideDiagramTooltip(container);
      } else if (action === "continue") {
        interaction.definitionLeavePrompt = false;
        interaction.definitionCloseAfterSave = false;
        renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
      }
      return;
    }
    const deviceTab = target.closest("[data-diagram-device-tab]");
    if (deviceTab) {
      clearDiagramTooltipHide(interaction);
      if (diagramDefinitionEditPinned(interaction)) return;
      const tabKey = deviceTab.getAttribute("data-diagram-device-tab") || "self";
      if (tabKey === interaction.deviceTooltipTabKey) return;
      interaction.deviceTooltipTabKey = tabKey;
      const updated = updateDiagramDeviceTooltip(
        container,
        interaction.hover,
        interaction.snapshot || state.snapshot || {},
        interaction,
      );
      if (!updated) renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
      interaction.tooltip?.querySelector(`[data-diagram-device-tab="${CSS.escape(tabKey)}"]`)?.focus();
      return;
    }
    const editable = target.closest("[data-diagram-definition-editable]");
    if (editable && !interaction.definitionEditor && !interaction.definitionSaving) {
      if (editable.getAttribute("data-diagram-definition-editable") === "measurement") {
        beginDiagramMeasurementDefinitionEdit(container);
      } else {
        const section = editable.closest("[data-diagram-definition-block]");
        beginDiagramDeviceDefinitionEdit(
          container,
          section?.getAttribute("data-diagram-definition-block") || "",
          Number(section?.getAttribute("data-diagram-definition-row-index") || 0),
        );
      }
      return;
    }
    if (target.closest("[data-diagram-definition-cancel]")) {
      cancelDiagramDefinitionEdit(container);
      return;
    }
    const save = target.closest("[data-diagram-definition-save]");
    if (save) {
      if (save.getAttribute("data-diagram-definition-save") === "measurement") {
        saveDiagramMeasurementDefinitionEdit(container);
      } else {
        saveDiagramDeviceDefinitionEdit(container);
      }
      return;
    }
    const navigationButton = target.closest("[data-diagram-trend-action]");
    if (navigationButton && !navigationButton.disabled) {
      const period = interaction.trendPeriod === "day" ? "day" : "hour";
      const currentOffset = Number(interaction.trendNavigationRange?.windowOffset)
        || Number(interaction.trendPeriodOffsets?.[period])
        || 0;
      const action = navigationButton.getAttribute("data-diagram-trend-action") || "";
      const nextOffset = action === "previous"
        ? currentOffset - 1
        : action === "next" ? currentOffset + 1 : 0;
      interaction.trendPeriodOffsets = {
        ...(interaction.trendPeriodOffsets || { hour: 0, day: 0 }),
        [period]: Math.min(0, nextOffset),
      };
      refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
      return;
    }
    const button = target.closest("[data-diagram-trend-period]");
    if (!button) return;
    const period = button.getAttribute("data-diagram-trend-period") === "day" ? "day" : "hour";
    if (period === interaction.trendPeriod) return;
    interaction.trendPeriod = period;
    refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
  });
  tooltip.addEventListener("input", (event) => {
    const input = event.target instanceof Element ? event.target.closest("[data-diagram-definition-input]") : null;
    if (!input) return;
    if (input.getAttribute("data-diagram-definition-input") === "measurement") {
      updateDiagramMeasurementDefinitionDraft(interaction, input);
    } else {
      updateDiagramDeviceDefinitionDraft(interaction, input);
    }
  });
  tooltip.addEventListener("change", (event) => {
    const input = event.target instanceof Element ? event.target.closest("[data-diagram-definition-input]") : null;
    if (!input || input.getAttribute("data-diagram-definition-input") !== "measurement") return;
    updateDiagramMeasurementDefinitionDraft(interaction, input);
  });
  contextMenu.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-diagram-display-toggle]") : null;
    if (!button) return;
    const key = button.getAttribute("data-diagram-display-toggle") || "";
    if (!Object.prototype.hasOwnProperty.call(DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS, key)) return;
    const nextValue = key === "measurementSource"
      ? (button.getAttribute("data-diagram-display-value") === "real" ? "real" : "scada")
      : !diagramDisplayPreferences[key];
    diagramDisplayPreferences = saveDiagramDisplayPreferences({
      ...diagramDisplayPreferences,
      [key]: nextValue,
    });
    applyDiagramDisplayPreferences(container, diagramDisplayPreferences);
    updateDiagramRealtimeBindings(container, interaction.snapshot || state.snapshot || {});
    closeDiagramContextMenu(interaction);
  });
  document.addEventListener("pointerdown", (event) => {
    if (contextMenu.hidden || contextMenu.contains(event.target)) return;
    closeDiagramContextMenu(interaction);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeDiagramContextMenu(interaction);
    if (diagramDefinitionEditPinned(interaction)) cancelDiagramDefinitionEdit(container);
  });
  window.addEventListener("resize", () => closeDiagramContextMenu(interaction));
}

function updateDiagramRealtimeBindings(container = $("modelDiagramCanvas"), snapshot = state.snapshot || {}) {
  if (!container) return;
  updateDiagramDeviceVisualStates(container, snapshot);
  const measurementMaps = diagramMeasurementMaps(snapshot);
  updateDiagramSwitchVisualStates(container, measurementMaps);
  const maps = { ...measurementMaps, controls: diagramControlMap(snapshot) };
  const bindings = diagramRealtimeBindings(container);
  bindings.measurements.forEach(({ element, name }) => {
    setDiagramElementValue(
      element,
      diagramBindingValue(name, maps, diagramDisplayPreferences.measurementSource),
    );
  });
  bindings.scada.forEach(({ element, name }) => {
    setDiagramElementValue(element, diagramBindingValue(name, maps, "scada"));
  });
  bindings.real.forEach(({ element, name }) => {
    setDiagramElementValue(element, diagramBindingValue(name, maps, "real"));
  });
  bindings.controls.forEach(({ element, name }) => {
    setDiagramElementValue(element, diagramBindingValue(name, maps, "control"));
  });
  bindings.metrics.forEach((binding) => {
    setDiagramElementValue(
      binding.element,
      diagramMetricBindingValue(binding, maps, diagramDisplayPreferences.measurementSource),
      binding.metricType,
    );
  });
  updateDiagramFlowArrows(container, snapshot, measurementMaps);
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
  const diagramChanged = canvas.dataset.diagramKey !== key;
  if (canvas.dataset.diagramKey !== key) {
    const sanitized = sanitizeDiagramSvg(diagram.svg);
    resetDiagramInteractions(canvas);
    canvas.dataset.diagramKey = key;
    canvas.innerHTML = sanitized
      ? `<div class="model-diagram-svg-wrap">${sanitized}</div>`
      : '<div class="empty-state">接线图 SVG 无法解析</div>';
    if (sanitized) {
      prepareDiagramDisplayLayers(canvas);
      compileDiagramFlowArrows(canvas);
    }
  }
  initDiagramInteractions(canvas);
  applyDiagramDisplayPreferences(canvas, diagramDisplayPreferences);
  if (summary) summary.textContent = `${modelName} · ${diagram.filename || "diagram.svg"}`;
  updateDiagramRealtimeBindings(canvas, activeSnapshot);
  if (diagramChanged) fitDiagramViewport(diagramViewportState(canvas));
}

window.addEventListener("storage", (event) => {
  if (event.key !== DIAGRAM_DISPLAY_PREFERENCES_KEY) return;
  try {
    diagramDisplayPreferences = normalizeDiagramDisplayPreferences(event.newValue ? JSON.parse(event.newValue) : null);
  } catch (_error) {
    diagramDisplayPreferences = normalizeDiagramDisplayPreferences(null);
  }
  const canvas = $("modelDiagramCanvas");
  applyDiagramDisplayPreferences(canvas, diagramDisplayPreferences);
  updateDiagramRealtimeBindings(canvas, state.snapshot || {});
  const interaction = canvas ? diagramInteractionCache.get(canvas) : null;
  if (interaction?.contextMenu && !interaction.contextMenu.hidden) renderDiagramContextMenu(interaction);
});

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
  return timeInputToSecond(value, Number(fallback) * 60) / 60;
}

function timeInputToSecond(value, fallback = 0) {
  const match = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(value || ""));
  if (!match) return clamp(Number(fallback) || 0, 0, 86399);
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  const second = Number(match[3] || 0);
  if (hour > 23 || minute > 59 || second > 59) return clamp(Number(fallback) || 0, 0, 86399);
  return hour * 3600 + minute * 60 + second;
}

function secondToTimeInput(value, fallback = 0) {
  const numeric = Number(value);
  const fallbackNumeric = Number(fallback);
  const totalSeconds = clamp(
    Math.round(Number.isFinite(numeric) ? numeric : (Number.isFinite(fallbackNumeric) ? fallbackNumeric : 0)),
    0,
    24 * 60 * 60 - 1,
  );
  const hourText = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minuteText = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const secondText = String(totalSeconds % 60).padStart(2, "0");
  return `${hourText}:${minuteText}:${secondText}`;
}

function minuteToSecondTimeInput(value, fallback = 0) {
  return secondToTimeInput(Number(value) * 60, Number(fallback) * 60);
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

function loadCurveFamilyConfig(family) {
  return LOAD_CURVE_FAMILIES.find((item) => item.key === family) || null;
}

function loadCurveFamilyForBlock(blockName) {
  const block = String(blockName || "").trim();
  return LOAD_CURVE_FAMILIES.find((item) => item.blocks.includes(block))?.key || "other";
}

function loadCurveFamilyKeys(family) {
  return curveLoadDevices()
    .filter((dev) => dev.family === family)
    .map((dev) => loadCurveKey(dev.dev_name));
}

function curveLoadDeviceForKey(key) {
  const devName = loadNameFromCurveKey(key);
  return curveLoadDevices().find((dev) => dev.dev_name === devName) || null;
}

function curveSourceCatalog() {
  const sources = Array.isArray(state.curveSummary?.sources) ? state.curveSummary.sources : [];
  return sources.filter((item) => item && item.key && item.family);
}

function allSourceCurveKeys() {
  return curveSourceCatalog().map((item) => item.key);
}

function allCurveKeys() {
  return [...ENV_CURVE_KEYS, ...allLoadCurveKeys(), ...allSourceCurveKeys()];
}

function semanticDeviceModelBlock(dev) {
  return String(dev?.model_block || dev?.raw?.model_block || "").trim();
}

function semanticDeviceFamily(dev) {
  return String(dev?.device_family || "").trim().toLowerCase();
}

function curveLoadDevices() {
  const summaryLoads = Array.isArray(state.curveSummary?.loads) ? state.curveSummary.loads : [];
  const summaryByName = new Map(summaryLoads.map((item) => [String(item.dev_name || item.name || ""), item]));
  const supportedBlocks = new Set(LOAD_CURVE_FAMILIES.flatMap((item) => item.blocks));
  const devices = (state.snapshot?.devices || [])
    .filter((dev) => (
      semanticDeviceFamily(dev) === "load"
      || supportedBlocks.has(semanticDeviceModelBlock(dev))
    ) && dev.dev_name)
    .map((dev) => {
      const summary = summaryByName.get(String(dev.dev_name || "")) || {};
      const modelBlock = semanticDeviceModelBlock(dev) || String(summary.dev_type || dev.dev_type || "");
      const family = String(summary.family || loadCurveFamilyForBlock(modelBlock));
      const config = loadCurveFamilyConfig(family);
      return {
        dev_type: modelBlock,
        dev_name: dev.dev_name,
        family,
        unit: summary.unit || config?.unit || "",
        set_type: summary.set_type || config?.setType || "",
        value_key: config?.valueKey || "value",
        default_value: Number(summary.default_value ?? dev.raw?.[summary.set_type || config?.setType || ""] ?? 0),
        min: Number(summary.min ?? dev.raw?.[`${String(summary.set_type || config?.setType || "").replace(/_set$/, "")}_min`]),
        max: Number(summary.max ?? dev.raw?.[`${String(summary.set_type || config?.setType || "").replace(/_set$/, "")}_max`]),
      };
    });
  const unique = new Map();
  devices.forEach((dev) => unique.set(`${dev.dev_type}|${dev.dev_name}`, dev));
  const loads = Array.from(unique.values()).sort((left, right) => left.dev_name.localeCompare(right.dev_name));
  if (!loads.length && summaryLoads.length) {
    return summaryLoads
      .map((item) => {
        const devType = String(item.dev_type || "");
        const family = String(item.family || loadCurveFamilyForBlock(devType));
        const config = loadCurveFamilyConfig(family);
        return {
          dev_type: devType,
          dev_name: item.dev_name || item.name || loadNameFromCurveKey(item.key),
          family,
          unit: item.unit || config?.unit || "",
          set_type: item.set_type || config?.setType || "",
          value_key: config?.valueKey || "value",
          default_value: Number(item.default_value ?? 0),
          min: Number(item.min),
          max: Number(item.max),
        };
      })
      .filter((dev) => dev.dev_name);
  }
  return loads.length ? loads : [{
    dev_type: "ACLoad",
    dev_name: "load_ac_1",
    family: "electric",
      unit: "kW",
      set_type: "p_set",
      value_key: "p_kw",
      default_value: 0,
      min: 0,
      max: 500,
  }];
}

function curveMetaForKey(key) {
  const meta = CURVE_META.find((item) => item.key === key);
  if (meta) return meta;
  if (String(key).startsWith("load:")) {
    const devName = loadNameFromCurveKey(key);
    const loadDevice = curveLoadDeviceForKey(key);
    const loadIndex = Math.max(0, allLoadCurveKeys().indexOf(key));
    const color = LOAD_CURVE_COLORS[loadIndex % LOAD_CURVE_COLORS.length];
    const lower = Number(loadDevice?.min);
    const upper = Number(loadDevice?.max);
    const defaultValue = Number(loadDevice?.default_value);
    return {
      ...LOAD_CURVE_META,
      key,
      label: devName,
      color,
      unit: loadDevice?.unit || LOAD_CURVE_META.unit,
      family: loadDevice?.family || "electric",
      devType: loadDevice?.dev_type || "",
      min: Number.isFinite(lower) ? lower : 0,
      max: Number.isFinite(upper) && upper > (Number.isFinite(lower) ? lower : 0)
        ? upper
        : Math.max(1, Number.isFinite(defaultValue) ? Math.abs(defaultValue) * 1.2 : LOAD_CURVE_META.max),
    };
  }
  if (String(key).startsWith("source:")) {
    const source = curveSourceCatalog().find((item) => item.key === key) || {};
    const sourceIndex = Math.max(0, allSourceCurveKeys().indexOf(key));
    const defaultValue = Number(source.default_value);
    const lower = Number(source.min);
    const upper = Number(source.max);
    const span = Math.max(1, Math.abs(Number.isFinite(defaultValue) ? defaultValue : 0));
    return {
      key,
      label: source.name || source.dev_name || key,
      color: SOURCE_CURVE_COLORS[sourceIndex % SOURCE_CURVE_COLORS.length],
      min: Number.isFinite(lower) ? lower : Math.min(0, (Number.isFinite(defaultValue) ? defaultValue : 0) - span),
      max: Number.isFinite(upper) ? upper : Math.max(1, (Number.isFinite(defaultValue) ? defaultValue : 0) + span),
      digits: 3,
      unit: source.unit || "",
      family: source.family || "electric",
      devType: source.dev_type || "",
    };
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

function curveFallbackValue(key) {
  if (String(key || "").startsWith("load:")) {
    const defaultValue = Number(curveLoadDeviceForKey(key)?.default_value);
    return Number.isFinite(defaultValue) ? defaultValue : 0;
  }
  if (String(key || "").startsWith("source:")) {
    const source = curveSourceCatalog().find((item) => item.key === key);
    return Number(source?.default_value) || 0;
  }
  return curveMetaForKey(key).min;
}

function curveHasLoadedSeries(key) {
  return Array.isArray(state.curveSeries?.[key]) && state.curveSeries[key].length > 0;
}

function ensureCurveSeries(keys = selectedCurveKeys()) {
  let changed = false;
  const available = new Set(allCurveKeys());
  const targetKeys = Array.from(new Set(keys || []))
    .filter((key) => available.has(key) || ENV_CURVE_KEYS.includes(key) || /^(load|source):/.test(String(key || "")));
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
      points.map((point) => Number(
        point[dev.value_key]
        ?? point.value
        ?? point.p_kw
        ?? point.load_kw
        ?? point.flow_set
        ?? point.heat_power,
      ) || 0),
      config.pointCount,
      curveFallbackValue(loadCurveKey(dev.dev_name)),
    );
  });
  (Array.isArray(curves.sources) ? curves.sources : []).forEach((source) => {
    if (!source?.key) return;
    const points = Array.isArray(source.points) ? source.points : [];
    state.curveSeries[source.key] = resampleSeries(
      points.map((point) => Number(point.value ?? point.set_value) || 0),
      config.pointCount,
      Number(source.default_value) || 0,
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
      ...(() => {
        const dev = (state.snapshot?.devices || []).find((item) => (
          String(item?.dev_name || "") === name
          && (semanticDeviceFamily(item) === "load" || loadCurveFamilyForBlock(semanticDeviceModelBlock(item)) !== "other")
        ));
        const devType = semanticDeviceModelBlock(dev);
        const family = loadCurveFamilyForBlock(devType);
        const config = loadCurveFamilyConfig(family);
        return devType ? {
          dev_type: devType,
          dev_name: name,
          family,
          unit: config?.unit || "",
          set_type: config?.setType || "",
        } : {};
      })(),
    })),
    sources: (Array.isArray(curves.sources) ? curves.sources : []).map((source) => ({
      ...source,
      point_count: Array.isArray(source.points) ? source.points.length : 0,
      points: undefined,
    })),
  };
}

function curveSummaryHasCatalog(summary = state.curveSummary) {
  return Boolean(summary && Array.isArray(summary.environment) && Array.isArray(summary.loads) && Array.isArray(summary.sources));
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
    timeoutMs: curveRequestTimeoutMs(),
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
    timeoutMs: curveRequestTimeoutMs(),
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
  if (modelServiceDependentControlsDisabled() || simulationModeLocked()) return;
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
  const controlsDisabled = modelServiceDependentControlsDisabled();
  document.querySelectorAll("[data-curve-mode]").forEach((button) => {
    const active = button.dataset.curveMode === state.curveMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = modeLocked || controlsDisabled;
    button.title = controlsDisabled
      ? "请先启动选中模型的模拟服务"
      : modeLocked ? "请先停止仿真，再切换仿真模式" : "";
  });
  const selector = $("simulationModeSelector");
  if (selector) {
    selector.value = state.curveMode;
    selector.disabled = modeLocked || controlsDisabled;
    selector.title = controlsDisabled
      ? "请先启动选中模型的模拟服务"
      : modeLocked ? "请先停止仿真，再切换仿真模式" : "选择时、日、周、月或年仿真";
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
  if (readout) readout.classList.toggle("is-year-mode", isExtendedSimulationMode());
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
  if (String(family).startsWith("load:")) return loadCurveFamilyKeys(String(family).slice(5));
  if (family === "source") return allSourceCurveKeys();
  if (String(family).startsWith("source:")) {
    const sourceFamily = String(family).slice(7);
    return curveSourceCatalog().filter((item) => item.family === sourceFamily).map((item) => item.key);
  }
  if (SOURCE_CURVE_FAMILIES.some((item) => item.key === family)) {
    return curveSourceCatalog().filter((item) => item.family === family).map((item) => item.key);
  }
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

function readStoredCurveTreeCollapsedGroups() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CURVE_TREE_COLLAPSE_KEY) || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch (_error) {
    // Invalid local UI state falls back to the default expanded tree.
  }
  return {};
}

function curveTreeGroupCollapsed(groupKey) {
  return Boolean(state.curveTreeGroupCollapsed?.[groupKey]);
}

function toggleCurveTreeGroup(groupKey) {
  if (!groupKey) return;
  state.curveTreeGroupCollapsed = {
    ...(state.curveTreeGroupCollapsed || {}),
    [groupKey]: !curveTreeGroupCollapsed(groupKey),
  };
  localStorage.setItem(CURVE_TREE_COLLAPSE_KEY, JSON.stringify(state.curveTreeGroupCollapsed));
  renderCurveTree();
}

function curveTreeGroupHeader(groupKey, label, count, buttonAttrs, buttonClasses = "", toggleAttribute = "data-curve-tree-toggle") {
  const collapsed = curveTreeGroupCollapsed(groupKey);
  return `
    <div class="tree-parent-row">
      <button
        type="button"
        class="tree-collapse-toggle ${collapsed ? "is-collapsed" : ""}"
        ${toggleAttribute}="${escapeHtml(groupKey)}"
        aria-label="${collapsed ? "展开" : "折叠"}${escapeHtml(label)}"
        aria-expanded="${collapsed ? "false" : "true"}"
      ><span class="tree-toggle" aria-hidden="true"></span></button>
      <button
        type="button"
        class="tree-node tree-type ${buttonClasses}"
        ${buttonAttrs}
      >
        <span>${escapeHtml(label)}</span>
        <strong>${count}</strong>
      </button>
    </div>`;
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
  const loadGroups = [
    ...LOAD_CURVE_FAMILIES.map((family) => ({
      ...family,
      loads: loadDevices.filter((dev) => dev.family === family.key),
    })),
    {
      key: "other",
      label: "其他负荷曲线",
      loads: loadDevices.filter((dev) => !LOAD_CURVE_FAMILIES.some((family) => family.key === dev.family)),
    },
  ].filter((group) => group.key !== "other" || group.loads.length);
  const sourceGroups = SOURCE_CURVE_FAMILIES.map((family) => ({
    ...family,
    sources: curveSourceCatalog().filter((item) => item.family === family.key),
  }));
  const envSelected = ENV_CURVE_KEYS.every((key) => selectedSet.has(key))
    && selectedKeys.every((key) => ENV_CURVE_KEYS.includes(key));
  const loadSelected = loadKeys.every((key) => selectedSet.has(key))
    && selectedKeys.every((key) => loadKeys.includes(key));
  const envPartial = ENV_CURVE_KEYS.some((key) => selectedSet.has(key));
  const loadPartial = loadKeys.some((key) => selectedSet.has(key));
  const sourceKeys = allSourceCurveKeys();
  const sourceSelected = sourceKeys.length && sourceKeys.every((key) => selectedSet.has(key))
    && selectedKeys.every((key) => sourceKeys.includes(key));
  const sourcePartial = sourceKeys.some((key) => selectedSet.has(key));
  $("curveTreeSummary").textContent = `${ENV_CURVE_KEYS.length + loadDevices.length + allSourceCurveKeys().length} 条`;
  $("activeCurve").value = activeKey;
  $("activeCurveLabel").textContent = selectedCurveLabel();
  container.innerHTML = `
    <div class="tree-group">
      ${curveTreeGroupHeader(
        "environment",
        "环境曲线",
        ENV_CURVE_KEYS.length,
        `data-curve-tree-type="environment" data-curve-family="environment" aria-pressed="${envSelected ? "true" : "false"}" aria-expanded="${curveTreeGroupCollapsed("environment") ? "false" : "true"}"`,
        envSelected ? "is-active" : envPartial ? "is-parent-active" : "",
        "data-curve-tree-toggle",
      )}
      <div class="tree-children" ${curveTreeGroupCollapsed("environment") ? "hidden" : ""}>
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
      ${curveTreeGroupHeader(
        "load",
        "负荷曲线",
        loadDevices.length,
        `data-curve-tree-type="load" data-curve-family="load" aria-pressed="${loadSelected ? "true" : "false"}" aria-expanded="${curveTreeGroupCollapsed("load") ? "false" : "true"}"`,
        loadSelected ? "is-active" : loadPartial ? "is-parent-active" : "",
        "data-curve-tree-toggle",
      )}
      <div id="curveLoadTree" class="tree-children" ${curveTreeGroupCollapsed("load") ? "hidden" : ""}>
        ${loadGroups.map((group) => {
          const groupKey = `load:${group.key}`;
          const keys = group.loads.map((dev) => loadCurveKey(dev.dev_name));
          const selected = keys.length && keys.every((key) => selectedSet.has(key))
            && selectedKeys.every((key) => keys.includes(key));
          const partial = keys.some((key) => selectedSet.has(key));
          return `
            <div class="tree-subgroup">
              ${curveTreeGroupHeader(
                groupKey,
                group.label,
                keys.length,
                `data-curve-tree-type="load" data-curve-family="${escapeHtml(groupKey)}" aria-pressed="${selected ? "true" : "false"}" aria-expanded="${curveTreeGroupCollapsed(groupKey) ? "false" : "true"}"`,
                selected ? "is-active" : partial ? "is-parent-active" : "",
              )}
              <div class="tree-children tree-grandchildren" ${curveTreeGroupCollapsed(groupKey) ? "hidden" : ""}>
                ${group.loads.map((dev) => {
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
                      <small>${escapeHtml(dev.unit || dev.dev_type)}</small>
                    </button>`;
                }).join("") || `<div class="empty-state compact">暂无${escapeHtml(group.label)}</div>`}
              </div>
            </div>`;
        }).join("")}
      </div>
    </div>
    <div class="tree-group">
      ${curveTreeGroupHeader(
        "source",
        "供能曲线",
        sourceKeys.length,
        `data-curve-tree-type="source" data-curve-family="source" aria-pressed="${sourceSelected ? "true" : "false"}" aria-expanded="${curveTreeGroupCollapsed("source") ? "false" : "true"}"`,
        sourceSelected ? "is-active" : sourcePartial ? "is-parent-active" : "",
        "data-curve-tree-toggle",
      )}
      <div class="tree-children" ${curveTreeGroupCollapsed("source") ? "hidden" : ""}>
        ${sourceGroups.map((group) => {
          const groupKey = `source:${group.key}`;
          const keys = group.sources.map((source) => source.key);
          const selected = keys.length && keys.every((key) => selectedSet.has(key))
            && selectedKeys.every((key) => keys.includes(key));
          const partial = keys.some((key) => selectedSet.has(key));
          return `
            <div class="tree-subgroup">
              ${curveTreeGroupHeader(
                groupKey,
                group.label,
                keys.length,
                `data-curve-tree-type="source" data-curve-family="${escapeHtml(groupKey)}" aria-pressed="${selected ? "true" : "false"}" aria-expanded="${curveTreeGroupCollapsed(groupKey) ? "false" : "true"}"`,
                selected ? "is-active" : partial ? "is-parent-active" : "",
              )}
              <div class="tree-children tree-grandchildren" ${curveTreeGroupCollapsed(groupKey) ? "hidden" : ""}>
                ${group.sources.map((source) => {
                  const key = source.key;
                  return `
                    <button
                      type="button"
                      class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""} ${editKey === key ? "is-edit-target" : ""} ${isCurveSeriesHidden(key) ? "is-hidden-series" : ""}"
                      data-curve-tree-type="source"
                      data-curve-key="${escapeHtml(key)}"
                      aria-pressed="${selectedSet.has(key) ? "true" : "false"}"
                    >
                      <span>${escapeHtml(source.name || source.dev_name || key)}</span>
                      <small>${escapeHtml(source.unit || source.dev_type || "")}</small>
                    </button>`;
                }).join("") || `<div class="empty-state compact">暂无${escapeHtml(group.label)}</div>`}
              </div>
            </div>`;
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
  const loadDevices = curveLoadDevices();
  loadDevices.forEach((dev) => {
    state.curveSeries[loadCurveKey(dev.dev_name)] = new Array(pointCount);
  });
  curveSourceCatalog().forEach((source) => {
    state.curveSeries[source.key] = new Array(pointCount).fill(Number(source.default_value) || 0);
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
    const loadShape = 0.84 + 0.18 * Math.sin((day - 0.18) * Math.PI * 2) + 0.08 * Math.sin(day * Math.PI * 8);
    state.curveSeries.wind_speed_mps[i] = Number(wind.toFixed(2));
    state.curveSeries.solar_irradiance_w_m2[i] = Number((solarPeak * sunShape).toFixed(1));
    state.curveSeries.air_temp_c[i] = Number(temp.toFixed(2));
    loadDevices.forEach((dev, loadIndex) => {
      const offset = 1 + loadIndex * 0.035;
      const base = curveFallbackValue(loadCurveKey(dev.dev_name));
      const lower = Number.isFinite(Number(dev.min)) ? Number(dev.min) : 0;
      const upper = Number.isFinite(Number(dev.max)) && Number(dev.max) >= lower
        ? Number(dev.max)
        : Math.max(lower, Math.abs(base) * 1.2, 1);
      state.curveSeries[loadCurveKey(dev.dev_name)][i] = Number(
        clamp(base * loadShape * offset, lower, upper).toFixed(2),
      );
    });
  }
  const firstElectricLoad = loadDevices.find((dev) => dev.family === "electric") || loadDevices[0];
  if (firstElectricLoad) {
    state.curveSeries.load_kw = [...state.curveSeries[loadCurveKey(firstElectricLoad.dev_name)]];
  }
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
      const point = { minute, [dev.value_key || "value"]: roundCurveValue(key, state.curveSeries[key]?.[i] ?? 0) };
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
    return { left: 48, right: 12, top: 58, bottom: 30 };
  }
  return CURVE_PLOT;
}

function curveYAxisTicks(meta = {}, divisions = 5) {
  const min = Number(meta?.min);
  const max = Number(meta?.max);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
  const segmentCount = Math.max(1, Math.floor(Number(divisions) || 5));
  const rawDigits = Number(meta?.digits);
  const digits = Math.max(0, Math.min(4, Number.isFinite(rawDigits) ? Math.floor(rawDigits) : 2));
  return Array.from({ length: segmentCount + 1 }, (_unused, index) => {
    const ratio = index / segmentCount;
    const value = Number((max - (max - min) * ratio).toFixed(digits));
    return { ratio, value, label: String(value) };
  });
}

function curveYAxisMeta(metas = [], preferredKey = "") {
  return metas.find((meta) => meta?.key === preferredKey) || metas[0] || null;
}

function drawCurveYAxis(ctx, canvas, plot, meta) {
  const ticks = curveYAxisTicks(meta, 5);
  if (!ticks.length) return;
  const left = plot.left;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  ctx.save();
  ctx.font = "11px Microsoft YaHei, Arial";
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#aebfc7";
  ctx.fillStyle = "#63717a";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.beginPath();
  ctx.moveTo(left, top);
  ctx.lineTo(left, bottom);
  ctx.stroke();
  ticks.forEach((tick) => {
    const y = top + tick.ratio * (bottom - top);
    ctx.beginPath();
    ctx.moveTo(left - 5, y);
    ctx.lineTo(left, y);
    ctx.stroke();
    ctx.fillText(tick.label, left - 8, y);
  });
  const unit = String(meta?.unit || "").trim();
  if (unit) {
    ctx.fillStyle = meta?.color || "#52656d";
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(unit, Math.max(4, left - 42), top - 10);
  }
  ctx.restore();
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
  if (state.curveMode === "hour") {
    const minuteStep = width < 560 ? 15 : 10;
    for (let minute = 0; minute <= 60; minute += minuteStep) {
      const x = left + (minute / 60) * (right - left);
      ctx.strokeStyle = minute % 30 === 0 ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      const labelHour = Math.floor(minute / 60);
      const labelMinute = minute % 60;
      ctx.fillText(`${String(labelHour).padStart(2, "0")}:${String(labelMinute).padStart(2, "0")}`, x - 14, height - 12);
    }
    return;
  }
  if (state.curveMode === "week" || state.curveMode === "month") {
    const dayCount = simulationModeDayCount();
    const dayStep = state.curveMode === "week" ? 1 : width < 560 ? 10 : width < 900 ? 5 : 3;
    for (let day = 0; day <= dayCount; day += dayStep) {
      const x = left + (day / dayCount) * (right - left);
      ctx.strokeStyle = day === 0 || day === dayCount ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      const labelDay = Math.min(day + 1, dayCount);
      ctx.fillText(`第${labelDay}天`, x - 16, height - 12);
    }
    if (dayCount % dayStep !== 0) {
      ctx.textAlign = "right";
      ctx.fillText(`第${dayCount}天`, right, height - 12);
      ctx.textAlign = "left";
    }
    return;
  }
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
  const axisMeta = curveYAxisMeta(metas, editKey || state.activeCurveKey);
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
  drawCurveYAxis(ctx, canvas, plot, axisMeta);
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
  if (state.curveMode === "hour") {
    const totalSeconds = Math.max(0, Math.round(Number(minute) * 60));
    const minutePart = Math.floor(totalSeconds / 60);
    const secondPart = totalSeconds % 60;
    return `00:${String(minutePart).padStart(2, "0")}:${String(secondPart).padStart(2, "0")}`;
  }
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
  if (state.curveMode === "week" || state.curveMode === "month") {
    const total = Math.max(0, Math.round(Number(minute)));
    const day = Math.floor(total / 1440) + 1;
    const minuteOfDay = total % 1440;
    const hour = Math.floor(minuteOfDay / 60);
    const minutePart = minuteOfDay % 60;
    return `第${day}天 ${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`;
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
      resetChartPeriodOffsets("runtimeTrace");
      drawRuntimeTraceChart();
    });
  }
  initChartPeriodNavigation("runtimeTrace", runtimeTraceWindowRange, drawRuntimeTraceChart);
  initTraceChartInteractions("runtimeTrace", "runtimeTraceChart", drawRuntimeTraceChart);
  window.addEventListener("resize", drawRuntimeTraceChart);
}

function initMeasurementMonitor() {
  const windowSelect = $("measurementTraceWindow");
  if (windowSelect) {
    state.measurementTraceWindowMinutes = Number(windowSelect.value) || state.measurementTraceWindowMinutes;
    windowSelect.addEventListener("change", (event) => {
      state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
      resetChartPeriodOffsets("measurementTrace");
      drawMeasurementTraceChart();
    });
  }
  initChartPeriodNavigation("measurementTrace", measurementTraceWindowRange, drawMeasurementTraceChart);
  initTraceChartInteractions("measurementTrace", "measurementTraceChart", drawMeasurementTraceChart);
  window.addEventListener("resize", drawMeasurementTraceChart);
}

async function refresh() {
  if (state.refreshRequestActive) return;
  if (!activeModelServiceRunning()) {
    $("simState").textContent = "stopped";
    const solverInfo = $("solverInfo");
    if (solverInfo) solverInfo.textContent = "模拟服务已停止";
    return;
  }
  state.refreshRequestActive = true;
  try {
    const activePage = currentPageName();
    const snapshot = await refreshSnapshotPayload(activePage);
    const deltaRequests = [];
    if (pageNeedsRuntimeLogDelta(activePage)) deltaRequests.push(refreshRuntimeLogs(false));
    if (pageNeedsMeasurementDelta(activePage) && !state.embeddedMeasurementDeltaReceived) {
      deltaRequests.push(refreshMeasurementDelta(false));
    }
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

const OVERVIEW_FLOW_GROUP_DEFINITIONS = [
  { key: "dcWind", category: "generation", region: "dc", color: "#2f9e62" },
  { key: "dcSolar", category: "generation", region: "dc", color: "#2f9e62" },
  { key: "dcGridFollowingStorage", category: "storage", region: "dc", color: "#2f9e62" },
  { key: "dcLoad", category: "load", region: "dc", color: "#bd5656" },
  { key: "fuelCell", category: "fuelCell", region: "hydrogen", color: "#16856a" },
  { key: "hydrogenStorage", category: "hydrogenStorage", region: "hydrogen", color: "#287ea0" },
  { key: "electrolyzer", category: "electrolyzer", region: "hydrogen", color: "#b56a22" },
  { key: "dcGridFormingStorage", category: "storage", region: "forming", color: "#2f9e62" },
  { key: "acGridFormingStorage", category: "storage", region: "forming", color: "#2f9e62" },
  { key: "acdcConverter", category: "converter", region: "bridge", color: "#0a8b8b" },
  { key: "acWind", category: "generation", region: "ac", color: "#2f9e62" },
  { key: "acSolar", category: "generation", region: "ac", color: "#2f9e62" },
  { key: "acGridFollowingStorage", category: "storage", region: "ac", color: "#2f9e62" },
  { key: "acLoad", category: "load", region: "ac", color: "#bd5656" },
  { key: "diesel", category: "generation", region: "ac", color: "#c84f4f" },
];

const OVERVIEW_FLOW_STATUS_LABELS = {
  generation: "发电",
  absorption: "吸收",
  consumption: "用电",
  discharge: "放电",
  charge: "充电",
  dcToAc: "直流送交流",
  acToDc: "交流送直流",
  idle: "待机",
  retired: "退运",
  deadIsland: "死岛",
  unmeasured: "待量测",
  storingHydrogen: "储气",
  releasingHydrogen: "供气",
};

function overviewFallbackFlowGroups(power) {
  return {
    acWind: { power: power.wind },
    dcSolar: { power: power.solar },
    dcGridFormingStorage: { power: power.storage, soc: power.soc },
    acdcConverter: { power: null },
    acLoad: { power: power.load },
    diesel: { power: power.diesel },
  };
}

function overviewFlowState(category, power) {
  if (!Number.isFinite(power)) return { status: "unmeasured", flowDirection: "idle" };
  if (Math.abs(power) <= 1e-9) return { status: "idle", flowDirection: "idle" };
  if (category === "storage") {
    return power > 0
      ? { status: "discharge", flowDirection: "toBus" }
      : { status: "charge", flowDirection: "fromBus" };
  }
  if (category === "load" || category === "electrolyzer") {
    return power > 0
      ? { status: "consumption", flowDirection: "fromBus" }
      : { status: "generation", flowDirection: "toBus" };
  }
  if (category === "converter") {
    return power > 0
      ? { status: "dcToAc", flowDirection: "toAc" }
      : { status: "acToDc", flowDirection: "toDc" };
  }
  return power > 0
    ? { status: "generation", flowDirection: "toBus" }
    : { status: "absorption", flowDirection: "fromBus" };
}

function overviewHydrogenStorageFlowState(gasFlow) {
  if (!Number.isFinite(gasFlow)) return { status: "unmeasured", flowDirection: "idle" };
  if (Math.abs(gasFlow) <= 1e-9) return { status: "idle", flowDirection: "idle" };
  return gasFlow > 0
    ? { status: "releasingHydrogen", flowDirection: "fromTank" }
    : { status: "storingHydrogen", flowDirection: "toTank" };
}

function normalizeOverviewFlowGroups(rawGroups, power) {
  const source = rawGroups && typeof rawGroups === "object" ? { ...rawGroups } : {};
  if (!source.dcLoad && !source.acLoad && source.load && typeof source.load === "object") {
    source.acLoad = source.load;
  }
  const hasStructuredGroups = Object.keys(source).length > 0;
  const fallback = overviewFallbackFlowGroups(power);
  return Object.fromEntries(OVERVIEW_FLOW_GROUP_DEFINITIONS.map((definition) => {
    const data = source[definition.key] && typeof source[definition.key] === "object"
      ? source[definition.key]
      : {};
    const fallbackData = hasStructuredGroups ? {} : (fallback[definition.key] || {});
    const groupPower = powerSummaryNumber(data.power ?? fallbackData.power);
    const gasFlow = powerSummaryNumber(data.gasFlow ?? fallbackData.gasFlow);
    const totalCountValue = Number(data.totalCount);
    const totalCount = Number.isFinite(totalCountValue)
      ? Math.max(0, Math.trunc(totalCountValue))
      : Number.isFinite(groupPower) ? 1 : 0;
    const onlineCountValue = Number(data.onlineCount);
    const onlineCount = Number.isFinite(onlineCountValue)
      ? Math.max(0, Math.trunc(onlineCountValue))
      : totalCount;
    const derived = definition.category === "hydrogenStorage"
      ? overviewHydrogenStorageFlowState(gasFlow)
      : overviewFlowState(definition.category, groupPower);
    const flowDirection = ["toBus", "fromBus", "toAc", "toDc", "toTank", "fromTank", "idle"].includes(data.flowDirection)
      ? data.flowDirection
      : derived.flowDirection;
    const status = String(data.status || derived.status);
    return [definition.key, {
      ...data,
      key: definition.key,
      category: definition.category,
      region: definition.region,
      color: definition.color,
      controlMode: String(data.controlMode ?? fallbackData.controlMode ?? "").trim().toUpperCase(),
      present: totalCount > 0,
      power: groupPower,
      targetPower: powerSummaryNumber(data.targetPower ?? fallbackData.targetPower),
      maxAvailablePower: powerSummaryNumber(data.maxAvailablePower ?? fallbackData.maxAvailablePower),
      gasFlow,
      targetGasFlow: powerSummaryNumber(data.targetGasFlow ?? fallbackData.targetGasFlow),
      gasPressure: powerSummaryNumber(data.gasPressure ?? fallbackData.gasPressure),
      gasQuantity: powerSummaryNumber(data.gasQuantity ?? fallbackData.gasQuantity),
      soc: powerSummaryNumber(data.soc ?? fallbackData.soc),
      totalCount,
      onlineCount,
      retiredCount: Math.max(0, Number(data.retiredCount) || 0),
      deadIslandCount: Math.max(0, Number(data.deadIslandCount) || 0),
      status,
      flowDirection,
    }];
  }));
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
  const power = {
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
  power.flowGroups = normalizeOverviewFlowGroups(summary.flowGroups, power);
  return power;
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
  const rawStep = Number(curves.time_step_minutes);
  const step = Number.isFinite(rawStep) && rawStep > 0 ? rawStep : 1;
  const targetMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0);
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

function overviewGasFlowText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} Nm3/h` : "--";
}

function overviewGasPressureText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} MPa` : "--";
}

function overviewGasQuantityText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} Nm3` : "--";
}

function overviewGreenGroupPower(groups, key) {
  const group = groups?.[key];
  if (!group || group.present === false) return 0;
  return Number.isFinite(group.power) ? Number(group.power) : null;
}

function overviewGreenMetrics(power = {}) {
  const groups = power.flowGroups || {};
  const dcLoadPower = overviewGreenGroupPower(groups, "dcLoad");
  const acLoadPower = overviewGreenGroupPower(groups, "acLoad");
  const electrolyzerPower = overviewGreenGroupPower(groups, "electrolyzer");
  const dieselPower = overviewGreenGroupPower(groups, "diesel");
  if ([dcLoadPower, acLoadPower, electrolyzerPower, dieselPower].some((value) => value === null)) {
    return { loadPower: null, greenPower: null, greenPowerShare: null };
  }
  const loadPower = dcLoadPower + acLoadPower + electrolyzerPower;
  const greenPower = loadPower - dieselPower;
  return {
    loadPower,
    greenPower,
    greenPowerShare: Math.abs(loadPower) > 1e-9
      ? (greenPower / loadPower) * 100.0
      : null,
  };
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

function setOverviewFlowVisualElement(element, powerValue, maxPower, color) {
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

function setOverviewFlowVisual(id, powerValue, maxPower, color) {
  setOverviewFlowVisualElement($(id), powerValue, maxPower, color);
}

function overviewFlowGroupMeta(group) {
  const status = OVERVIEW_FLOW_STATUS_LABELS[group.status] || "待量测";
  const count = `${group.onlineCount}/${group.totalCount} 台`;
  if (["fuelCell", "electrolyzer", "hydrogenStorage"].includes(group.category)) {
    return `${status} · 数量 ${count}`;
  }
  if (group.category !== "storage") return `${status} · ${count}`;
  const soc = Number.isFinite(group.soc) ? `${formatOverviewNumber(group.soc)}%` : "--";
  return `${status} · SOC ${soc} · ${count}`;
}

function overviewHydrogenActiveTarget(group) {
  const mode = String(group.controlMode || "").trim().toUpperCase();
  if (mode === "FLOW") {
    return {
      label: group.category === "fuelCell" ? "耗气目标" : "产气目标",
      value: overviewGasFlowText(group.targetGasFlow),
    };
  }
  if (["P", "PQ"].includes(mode)) {
    return {
      label: group.category === "fuelCell" ? "发电目标" : "耗电目标",
      value: overviewPowerText(group.targetPower),
    };
  }
  return { label: "有效目标", value: "--" };
}

function renderOverviewFlowGroups(power) {
  const groups = power.flowGroups || {};
  const visibleGroups = OVERVIEW_FLOW_GROUP_DEFINITIONS
    .map((definition) => groups[definition.key])
    .filter((group) => group?.present);
  const maxPower = Math.max(1, ...visibleGroups.map((group) => overviewFlowPowerValue(group.power)));
  const { greenPowerShare } = overviewGreenMetrics(power);

  OVERVIEW_FLOW_GROUP_DEFINITIONS.forEach((definition) => {
    const group = groups[definition.key] || { present: false };
    const node = document.querySelector(`[data-overview-group="${definition.key}"]`);
    const wrapper = document.querySelector(`[data-overview-group-wrapper="${definition.key}"]`);
    if (!node) return;
    node.hidden = !group.present;
    if (wrapper) wrapper.hidden = !group.present;
    if (!group.present) return;
    node.dataset.flowDirection = group.flowDirection;
    node.dataset.operatingState = group.status;
    const powerNode = node.querySelector("[data-overview-power]");
    const targetNode = node.querySelector("[data-overview-target]");
    const maxAvailableNode = node.querySelector("[data-overview-max-available]");
    const gasFlowNode = node.querySelector("[data-overview-gas-flow]");
    const targetGasFlowNode = node.querySelector("[data-overview-target-gas-flow]");
    const gasPressureNode = node.querySelector("[data-overview-gas-pressure]");
    const socNode = node.querySelector("[data-overview-soc]");
    const metaNode = node.querySelector("[data-overview-meta]");
    const countNode = node.querySelector("[data-overview-count]");
    const activeTargetLabelNode = node.querySelector("[data-overview-active-target-label]");
    const activeTargetNode = node.querySelector("[data-overview-active-target]");
    if (powerNode) powerNode.textContent = overviewPowerText(group.power);
    if (targetNode) targetNode.textContent = overviewPowerText(group.targetPower);
    if (maxAvailableNode) maxAvailableNode.textContent = overviewPowerText(group.maxAvailablePower);
    if (gasFlowNode) gasFlowNode.textContent = overviewGasFlowText(group.gasFlow);
    if (targetGasFlowNode) targetGasFlowNode.textContent = overviewGasFlowText(group.targetGasFlow);
    if (gasPressureNode) gasPressureNode.textContent = overviewGasPressureText(group.gasPressure);
    if (socNode) socNode.textContent = overviewPercentText(group.soc);
    if (metaNode) metaNode.textContent = overviewFlowGroupMeta(group);
    if (countNode) countNode.textContent = `${group.onlineCount}/${group.totalCount} 台`;
    const activeTarget = ["fuelCell", "electrolyzer"].includes(definition.key)
      ? overviewHydrogenActiveTarget(group)
      : null;
    if (activeTargetLabelNode) activeTargetLabelNode.textContent = activeTarget?.label || "有效目标";
    if (activeTargetNode) activeTargetNode.textContent = activeTarget?.value || "--";
    const tooltipParts = [
      node.querySelector("span")?.textContent || "设备",
      `当前 ${overviewPowerText(group.power)}`,
    ];
    if (activeTarget) tooltipParts.push(`${activeTarget.label} ${activeTarget.value}`);
    else tooltipParts.push(`目标 ${overviewPowerText(group.targetPower)}`);
    if (["dcWind", "dcSolar", "acWind", "acSolar"].includes(definition.key)) {
      tooltipParts.push(`最大可发 ${overviewPowerText(group.maxAvailablePower)}`);
    }
    if (["fuelCell", "electrolyzer"].includes(definition.key)) {
      tooltipParts.push(`气流实时 ${overviewGasFlowText(group.gasFlow)}`);
    }
    if (definition.key === "hydrogenStorage") {
      tooltipParts.push(`气流量 ${overviewGasFlowText(group.gasFlow)}`);
      tooltipParts.push(`储气压力 ${overviewGasPressureText(group.gasPressure)}`);
      tooltipParts.push(`SOC ${overviewPercentText(group.soc)}`);
    }
    tooltipParts.push(overviewFlowGroupMeta(group));
    node.title = tooltipParts.join(" · ");
    const flowPower = group.flowDirection === "idle" ? 0 : group.power;
    const color = definition.category === "load" ? overviewLoadFlowColor(greenPowerShare) : definition.color;
    setOverviewFlowVisualElement(node, flowPower, maxPower, color);
    if (wrapper) {
      wrapper.dataset.storageFlow = group.status === "discharge" ? "discharge" : group.status === "charge" ? "charge" : "idle";
      wrapper.dataset.operatingState = group.status;
      setOverviewFlowVisualElement(wrapper, flowPower, maxPower, color);
    }
  });

  document.querySelectorAll("[data-overview-region]").forEach((region) => {
    if (region.id === "overviewGridFormingStack") return;
    const regionKey = region.dataset.overviewRegion;
    region.hidden = !visibleGroups.some((group) => group.region === regionKey);
  });
  const formingStack = $("overviewGridFormingStack");
  if (formingStack) formingStack.hidden = !visibleGroups.some((group) => group.region === "forming");

  const hydrogenLinkState = (name, group, value, maxValue, direction, color, present) => {
    const link = document.querySelector(`[data-hydrogen-link="${name}"]`);
    if (!link) return;
    link.hidden = !present;
    link.dataset.flowDirection = direction;
    setOverviewFlowVisualElement(link, value, maxValue, color);
  };
  const fuelCellGroup = groups.fuelCell;
  const hydrogenStorageGroup = groups.hydrogenStorage;
  const electrolyzerGroup = groups.electrolyzer;
  const maxHydrogenPower = Math.max(
    1,
    overviewFlowPowerValue(fuelCellGroup?.power),
    overviewFlowPowerValue(electrolyzerGroup?.power),
  );
  const maxHydrogenFlow = Math.max(
    1,
    overviewFlowPowerValue(fuelCellGroup?.gasFlow),
    overviewFlowPowerValue(electrolyzerGroup?.gasFlow),
    overviewFlowPowerValue(hydrogenStorageGroup?.gasFlow),
  );
  hydrogenLinkState(
    "fuel-cell-electric",
    fuelCellGroup,
    fuelCellGroup?.power,
    maxHydrogenPower,
    Number(fuelCellGroup?.power) >= 0 ? "left" : "right",
    "#16856a",
    Boolean(fuelCellGroup?.present),
  );
  hydrogenLinkState(
    "fuel-cell-gas",
    fuelCellGroup,
    fuelCellGroup?.gasFlow,
    maxHydrogenFlow,
    Number(fuelCellGroup?.gasFlow) >= 0 ? "left" : "right",
    "#287ea0",
    Boolean(fuelCellGroup?.present && hydrogenStorageGroup?.present),
  );
  hydrogenLinkState(
    "electrolyzer-gas",
    electrolyzerGroup,
    electrolyzerGroup?.gasFlow,
    maxHydrogenFlow,
    Number(electrolyzerGroup?.gasFlow) >= 0 ? "left" : "right",
    "#287ea0",
    Boolean(electrolyzerGroup?.present && hydrogenStorageGroup?.present),
  );
  hydrogenLinkState(
    "electrolyzer-electric",
    electrolyzerGroup,
    electrolyzerGroup?.power,
    maxHydrogenPower,
    Number(electrolyzerGroup?.power) >= 0 ? "left" : "right",
    "#b56a22",
    Boolean(electrolyzerGroup?.present),
  );

  const converterGroup = groups.acdcConverter;
  const aggregateTrunkPower = visibleGroups
    .filter((group) => !["load", "converter", "electrolyzer", "hydrogenStorage"].includes(group.category))
    .reduce((total, group) => total + overviewFlowPowerValue(group.power), 0);
  const trunkPower = converterGroup?.present && Number.isFinite(converterGroup.power)
    ? converterGroup.power
    : aggregateTrunkPower;
  const trunk = $("overviewEnergyMainTrunk");
  if (trunk) trunk.dataset.flowDirection = converterGroup?.flowDirection || "toAc";
  setOverviewFlowVisual("overviewEnergyMainTrunk", trunkPower, maxPower, "#2f9e62");
}

function renderEnergyFlowVisuals(power) {
  renderOverviewFlowGroups(power);
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
  renderOverviewServiceLink(snapshot);
  const overviewMode = snapshot.curve_boundary?.mode || snapshot.curves?.mode || state.curveMode;
  setOverviewText("overviewMode", simulationModeLabel(overviewMode));
  const effectiveStepSeconds = Number(
    clock.effective_step_seconds
      ?? snapshot.system_parameters?.effective_step_seconds
      ?? ((clock.step_seconds ?? 1) * (clock.speed ?? 1)),
  );
  setOverviewText("overviewStep", formatClockDuration(effectiveStepSeconds));
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
  const { greenPower, greenPowerShare } = overviewGreenMetrics(power);
  setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderOverviewFlowGroups(power);
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
    renderWebRuntimeSettings();
    if (state.webRuntimeLoadedModelId !== state.activeModelId && !state.webRuntimeLoading) {
      loadWebRuntimeSettings();
    }
    return;
  }
  if (activePage === "manual-changes") {
    renderManualDefinitionChanges();
    const activeDefinitionRevision = Number(snapshot?.static_meta?.definitions?.revision) || 0;
    if (
      (
        state.manualDefinitionChangesLoadedModelId !== state.activeModelId
        || (activeDefinitionRevision && activeDefinitionRevision !== state.manualDefinitionChangesRevision)
      )
      && !state.manualDefinitionChangesLoading
      && !state.manualDefinitionChangesResetting
      && !state.manualDefinitionChangesRetrying
    ) {
      loadManualDefinitionChanges();
    }
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
  state.frontendDiagnostics.snapshotRenderCount += 1;
  if (snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock);
  renderPowerFlowFailureAlert(snapshot);
  state.systemParameters = snapshotSystemParameters(snapshot || {});
  const runId = Number(snapshot.clock?.run_id ?? 0);
  const stepCount = Number(snapshot.clock?.step_count ?? 0);
  const traceLifecycleChanged = state.traceRunId !== null && (
    runId !== state.traceRunId
    || (state.traceStepCount !== null && stepCount < state.traceStepCount)
  );
  if (traceLifecycleChanged) {
    state.runtimeTraceHistory = [];
    resetChartPeriodOffsets("runtimeTrace");
    state.lastRuntimeTraceKey = "";
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
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
  ensureSelectedMeasurementHistory();
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
  state.runtimeLogs = state.runtimeLogs.slice(
    0,
    Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit"))),
  );
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

function readStoredRuntimeLogColumnWidths() {
  try {
    const stored = JSON.parse(localStorage.getItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY) || "[]");
    if (Array.isArray(stored) && stored.length === RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS.length) {
      return stored.map((value, index) => Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
        Number(value) || RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[index],
      ));
    }
  } catch (_error) {
    // Invalid local UI state falls back to the default widths.
  }
  return [...RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS];
}

function runtimeLogColgroupHtml() {
  return `<colgroup>${state.runtimeLogColumnWidths.map((width) => `<col style="width:${Math.round(width)}px">`).join("")}</colgroup>`;
}

function applyRuntimeLogColumnWidths(table, widths = state.runtimeLogColumnWidths) {
  if (!table) return;
  const normalized = widths.map((value, index) => Math.max(
    RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
    Number(value) || RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[index],
  ));
  state.runtimeLogColumnWidths = normalized;
  table.querySelectorAll("colgroup col").forEach((column, index) => {
    if (normalized[index] !== undefined) column.style.width = `${Math.round(normalized[index])}px`;
  });
  table.style.width = `${Math.round(normalized.reduce((total, width) => total + width, 0))}px`;
  table.style.minWidth = "100%";
}

function enableRuntimeLogColumnResizing(table) {
  if (!table || table.dataset.columnResizeReady === "true") return;
  table.dataset.columnResizeReady = "true";
  applyRuntimeLogColumnWidths(table);
  const headers = Array.from(table.querySelectorAll("thead th"));
  headers.forEach((header, columnIndex) => {
    const handle = document.createElement("span");
    handle.className = "table-column-resize-handle";
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", `调整${header.textContent.trim()}列宽`);
    handle.title = "拖动调整列宽，双击恢复默认宽度";
    handle.tabIndex = 0;
    const restoreDefault = () => {
      state.runtimeLogColumnWidths[columnIndex] = RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[columnIndex];
      applyRuntimeLogColumnWidths(table);
      localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
    };
    handle.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      restoreDefault();
    });
    handle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const step = event.shiftKey ? 24 : 8;
      state.runtimeLogColumnWidths[columnIndex] = Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[columnIndex],
        state.runtimeLogColumnWidths[columnIndex] + (event.key === "ArrowRight" ? step : -step),
      );
      applyRuntimeLogColumnWidths(table);
      localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
    });
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      state.runtimeLogColumnWidths = headers.map((item, index) => Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
        Math.round(item.getBoundingClientRect().width),
      ));
      applyRuntimeLogColumnWidths(table);
      const startX = event.clientX;
      const startWidth = state.runtimeLogColumnWidths[columnIndex];
      document.body.classList.add("is-resizing-table-column");
      handle.setPointerCapture?.(event.pointerId);
      const move = (moveEvent) => {
        state.runtimeLogColumnWidths[columnIndex] = Math.max(
          RUNTIME_LOG_COLUMN_MIN_WIDTHS[columnIndex],
          Math.round(startWidth + moveEvent.clientX - startX),
        );
        applyRuntimeLogColumnWidths(table);
      };
      const finish = () => {
        document.body.classList.remove("is-resizing-table-column");
        localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    });
    header.appendChild(handle);
  });
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
    <table class="runtime-log-table runtime-log-table-resizable">
      ${runtimeLogColgroupHtml()}
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
  enableRuntimeLogColumnResizing(container.querySelector(".runtime-log-table-resizable"));
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

function formatModelParamValue(value, field = "") {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (diagramDefinitionRatioField(field)) return diagramDefinitionDisplayValue(field, value);
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
    record[key] = formatModelParamValue(raw[key], key);
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
  const acControlType = String(raw.ac_control_type ?? dev?.ac_control_type ?? "").trim().toUpperCase();
  const dcControlType = String(raw.dc_control_type ?? dev?.dc_control_type ?? "").trim().toUpperCase();
  const usesDcPowerSetpoint = dcControlType === "P"
    || (dcControlType === "NONE" && (!acControlType || acControlType === "NONE"));
  const preferred = [];
  if (mode.includes("V")) preferred.push("v_set", "v_ac_set", "v_dc_set");
  if (mode.includes("Q")) preferred.push("q_set", "q_ac_set");
  if (usesDcPowerSetpoint || mode.includes("P") || mode.includes("H")) {
    preferred.push(
      ...(usesDcPowerSetpoint
        ? ["p_dc_set", "p_ac_set", "p_set", "pv0"]
        : ["p_ac_set", "p_dc_set", "p_set", "pv0"]),
    );
  }
  preferred.push(
    ...(usesDcPowerSetpoint
      ? ["p_dc_set", "p_ac_set", "p_set", "pv0"]
      : ["p_ac_set", "p_dc_set", "p_set", "pv0"]),
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

function runtimeSetpointLabel(key, kind) {
  return {
    p_ac_set: "ACP有功设定值",
    p_dc_set: "DCP有功设定值",
  }[String(key || "").trim().toLowerCase()] || `${kind}设定值`;
}

function runtimeMeasurementTypeCandidates(dev, setKey) {
  const key = String(setKey || "").trim().toLowerCase();
  if (!key) return [];
  const measurementKey = key.endsWith("_set") ? key.slice(0, -4) : key;
  const exactType = measurementKey.toUpperCase();
  const quantity = measurementKey.split("_", 1)[0].toUpperCase();
  const family = String(dev?.device_family || "").trim().toLowerCase();
  const domains = new Set((Array.isArray(dev?.terminal_domains) ? dev.terminal_domains : [])
    .map((value) => String(value || "").trim().toUpperCase())
    .filter(Boolean));
  const candidates = [];
  const add = (...types) => types.forEach((type) => {
    const normalized = String(type || "").trim().toUpperCase();
    if (normalized && !candidates.includes(normalized)) candidates.push(normalized);
  });

  if (measurementKey.includes("_")) add(exactType);
  if (measurementKey.includes("soc")) add("SOC");
  if (family === "generator") {
    add(`${quantity}_GEN`);
  } else if (family === "load") {
    add(`${quantity}_LOAD`);
  } else if (family === "converter" && domains.has("AC") && domains.has("DC")) {
    add(`${quantity}_AC`, `${quantity}_DC`);
  } else if (family === "converter") {
    add(`${quantity}_FROM`, `${quantity}_TO`);
  } else {
    add(
      `${quantity}_GEN`,
      `${quantity}_LOAD`,
      `${quantity}_AC`,
      `${quantity}_DC`,
      `${quantity}_FROM`,
      `${quantity}_TO`,
    );
  }
  add(exactType, quantity);
  return candidates;
}

function runtimeMeasTypeMatchesSetKey(measType, setKey, dev = null) {
  const type = String(measType || "").toUpperCase();
  const normalizedSetKey = String(setKey || "").trim().toUpperCase();
  if (!type || !normalizedSetKey) return false;
  if (!normalizedSetKey.endsWith("_SET")) return type === normalizedSetKey;
  return runtimeMeasurementTypeCandidates(dev, setKey).includes(type);
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
  let best = {};
  for (const candidate of runtimeMeasurementTypeCandidates(dev, meta.key || meta.kind)) {
    best = rows.find((row) => runtimeMeasTypeMatchesSetKey(row.meas_type, candidate)) || {};
    if (best.meas_type) break;
  }
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

function runtimeCommandRowOrigin(row) {
  const origin = String(row?.receive_time?.command_origin || row?.command_origin || "").trim().toLowerCase();
  return ["manual", "automatic"].includes(origin) ? origin : "";
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
  const originSelect = $("runtimeCommandOriginFilter");
  if (originSelect) originSelect.value = state.runtimeCommandOriginFilter || "all";
}

function applyRuntimeCommandTableFilters(rows) {
  const keyword = state.runtimeCommandKeywordFilter || "";
  const type = state.runtimeCommandTypeFilter || "all";
  const origin = state.runtimeCommandOriginFilter || "all";
  return (rows || []).filter((row) => {
    if (state.runtimeCommandOnlyActive && !row.active) return false;
    if (!tableFilterMatchesKeyword(runtimeCommandFilterFields(row), keyword)) return false;
    if (type !== "all" && runtimeCommandTypeLabel(row) !== type) return false;
    if (origin !== "all" && runtimeCommandRowOrigin(row) !== origin) return false;
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
  const sampledClock = snapshot.measurement_clock;
  const clock = sampledClock && Number(sampledClock.step_count ?? 0) > 0
    ? sampledClock
    : snapshot.clock || {};
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
  return { wall_time: "--", simu_time: "--", source: "", command_origin: "", origin_text: "--" };
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
  const origin = commandOrigin(entry);
  return {
    wall_time: wallTime,
    simu_time: commandRefreshTimeFromMinute(minute),
    source: String(entry.source || entry.payload?.source || ""),
    command_origin: origin,
    origin_text: commandOriginLabel(origin),
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

function commandOrigin(entry = {}) {
  const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
  const explicit = String(entry.command_origin || payload.command_origin || "").trim().toLowerCase();
  if (["manual", "human", "operator", "人工"].includes(explicit)) return "manual";
  if (["automatic", "auto", "strategy", "自动"].includes(explicit)) return "automatic";
  return manualCommandHoldsAcrossClockLifecycle(entry) ? "manual" : "automatic";
}

function commandOriginLabel(originOrEntry = "") {
  const origin = typeof originOrEntry === "string"
    ? String(originOrEntry).trim().toLowerCase()
    : commandOrigin(originOrEntry);
  if (origin === "manual") return "人工";
  if (origin === "automatic") return "自动";
  return "--";
}

function activeCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const commandEntries = Array.isArray(snapshot.commands?.effective)
    ? snapshot.commands.effective
    : (snapshot.commands?.history || []);
  return [...commandEntries].filter((entry) => {
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
        trace_label: `${dev.dev_type}.${dev.dev_name}.设备投退`,
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
        trace_label: `${dev.dev_type}.${dev.dev_name}.开关开合`,
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
        command: runtimeSetpointLabel(key, meta.kind),
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
        trace_label: `${dev.dev_type}.${dev.dev_name}.${key}`,
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
    state.runtimeCommandOriginFilter || "all",
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

function runtimeCommandDeleteName(row) {
  const devType = String(row?.device?.dev_type || "").trim();
  const devName = String(row?.device?.dev_name || "").trim();
  const fieldName = String(row?.set_type || "").trim();
  return devType && devName && fieldName ? `${devType}.${devName}.${fieldName}` : "";
}

function runtimeCommandDeleteButtonHtml(row) {
  const commandName = runtimeCommandDeleteName(row);
  const sending = commandName && state.runtimeCommandDeleteSending.has(commandName);
  const label = runtimeCommandTraceLabel(row);
  return `
    <button
      type="button"
      class="runtime-command-delete-button"
      data-runtime-command-delete-name="${escapeHtml(commandName)}"
      data-runtime-command-delete-label="${escapeHtml(label)}"
      title="删除当前有效指令"
      aria-label="删除当前有效指令：${escapeHtml(label)}"
      ${row.active && !sending ? "" : "disabled"}
    >${sending ? "删除中" : "删除"}</button>
  `;
}

async function deleteRuntimeCommand(commandName, label = "") {
  const name = String(commandName || "").trim();
  if (!name || state.runtimeCommandDeleteSending.has(name)) return;
  const displayLabel = String(label || name).trim();
  if (!window.confirm(`确认删除当前有效指令：${displayLabel}？\n删除后恢复模拟台默认值，后续学员台新指令仍可生效。`)) return;

  state.runtimeCommandDeleteSending.add(name);
  renderRuntimeDeviceTable();
  try {
    const result = await api("/api/simulator/commands/delete", {
      method: "POST",
      body: JSON.stringify({ commands: [{ name }] }),
    });
    const deleted = result.deleted || result;
    const count = Number(deleted.remote_controls || 0) + Number(deleted.remote_adjustments || 0);
    if (!count) {
      window.alert(`未找到可删除的当前有效指令：${displayLabel}`);
    }
    await refresh();
  } catch (error) {
    window.alert(`删除控制指令失败：${apiErrorText(error)}`);
  } finally {
    state.runtimeCommandDeleteSending.delete(name);
    renderRuntimeDeviceTable();
  }
}

function runtimeCommandLiveCellHtml(row, field) {
  if (field === "control") return escapeHtml(runtimeCommandTableValueText(row, "control"));
  if (field === "origin") return escapeHtml(row.receive_time?.origin_text || "--");
  if (field === "wall_time") return escapeHtml(row.receive_time?.wall_time || "--");
  if (field === "simu_time") return escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--");
  if (field === "real") return escapeHtml(runtimeCommandTableValueText(row, "real"));
  if (field === "scada") return escapeHtml(runtimeCommandTableValueText(row, "scada"));
  if (field === "delete") return runtimeCommandDeleteButtonHtml(row);
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
      <td data-runtime-command-live-field="origin">${runtimeCommandLiveCellHtml(row, "origin")}</td>
      <td class="mono-cell" data-runtime-command-live-field="wall_time">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
      <td class="mono-cell" data-runtime-command-live-field="simu_time">${escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--")}</td>
      <td class="numeric-cell" data-runtime-command-live-field="real">${runtimeCommandLiveCellHtml(row, "real")}</td>
      <td class="numeric-cell" data-runtime-command-live-field="scada">${runtimeCommandLiveCellHtml(row, "scada")}</td>
      <td class="runtime-command-delete-cell" data-runtime-command-live-field="delete">${runtimeCommandLiveCellHtml(row, "delete")}</td>
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
          <th>指令来源</th>
          <th>接收本机时刻</th>
          <th>接收仿真时刻</th>
          <th>实时值</th>
          <th>量测值</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 11)}
        ${renderRuntimeCommandRows(rows)}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 11)}
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
    || state.runtimeCommandOriginFilter !== "all"
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

function selectedRuntimeCommandTraceSeries(range = runtimeTraceWindowRange()) {
  const key = state.selectedRuntimeCommandKey;
  if (!key) return null;
  const rows = selectedRuntimeCommandTraceRows();
  const row = rows.find((item) => runtimeCommandTraceKey(item) === key);
  if (!row) return null;
  const points = runtimeTraceWindowPoints(range)
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

function runtimeTraceWindowPoints(range = runtimeTraceWindowRange()) {
  const history = state.runtimeTraceHistory || [];
  if (!history.length) return [];
  return traceWindowRealPoints(history, range);
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

function traceHistoryMinuteBounds(history, fallbackMinute = 0) {
  let earliestMinute = Number.POSITIVE_INFINITY;
  let latestMinute = Number.NEGATIVE_INFINITY;
  (Array.isArray(history) ? history : []).forEach((point) => {
    const minute = Number(point?.minute);
    if (!Number.isFinite(minute)) return;
    earliestMinute = Math.min(earliestMinute, minute);
    latestMinute = Math.max(latestMinute, minute);
  });
  const fallback = Number.isFinite(Number(fallbackMinute)) ? Number(fallbackMinute) : 0;
  const hasHistory = Number.isFinite(earliestMinute) && Number.isFinite(latestMinute);
  return {
    earliestMinute: hasHistory ? earliestMinute : fallback,
    latestMinute: hasHistory ? latestMinute : fallback,
    hasHistory,
  };
}

function alignedTraceWindowRange(
  history,
  windowMinutes,
  fallbackMinute,
  requestedOffset = 0,
  simulationDurationMinutes = Number.POSITIVE_INFINITY,
) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  const alignmentMinutes = traceWindowAlignmentMinutes(minutes);
  const axisStepMinutes = traceAxisStepMinutes(minutes);
  const bounds = traceHistoryMinuteBounds(history, fallbackMinute);
  const fallback = Number.isFinite(Number(fallbackMinute)) ? Number(fallbackMinute) : bounds.latestMinute;
  const latestMinute = Math.max(bounds.latestMinute, fallback);
  const currentStartMinute = Math.floor(latestMinute / alignmentMinutes) * alignmentMinutes;
  const normalizedSimulationDuration = Number(simulationDurationMinutes);
  const cycleStartMinute = Number.isFinite(normalizedSimulationDuration) && normalizedSimulationDuration > 0
    ? Math.floor((latestMinute + 1e-9) / normalizedSimulationDuration) * normalizedSimulationDuration
    : Number.NEGATIVE_INFINITY;
  const earliestMinute = bounds.hasHistory
    ? Math.max(bounds.earliestMinute, cycleStartMinute)
    : latestMinute;
  const periodNavigationAllowed = !Number.isFinite(normalizedSimulationDuration)
    || normalizedSimulationDuration <= 0
    || minutes < normalizedSimulationDuration;
  const minWindowOffset = periodNavigationAllowed && bounds.hasHistory
    ? Math.min(0, Math.floor((earliestMinute - currentStartMinute) / minutes))
    : 0;
  const normalizedOffset = periodNavigationAllowed
    ? Math.min(0, Math.trunc(Number(requestedOffset) || 0))
    : 0;
  const windowOffset = Math.max(minWindowOffset, normalizedOffset);
  const startMinute = currentStartMinute + windowOffset * minutes;
  return {
    startMinute,
    endMinute: startMinute + minutes,
    latestMinute,
    earliestMinute,
    currentStartMinute,
    windowMinutes: minutes,
    alignmentMinutes,
    axisStepMinutes,
    windowOffset,
    minWindowOffset,
    periodNavigationAllowed,
  };
}

function tracePeriodNavigationState(range = {}) {
  const periodNavigationAllowed = range.periodNavigationAllowed !== false;
  const windowOffset = Math.min(0, Math.trunc(Number(range.windowOffset) || 0));
  const minWindowOffset = Math.min(0, Math.trunc(Number(range.minWindowOffset) || 0));
  return {
    visible: periodNavigationAllowed && (minWindowOffset < 0 || windowOffset < 0),
    previousDisabled: !periodNavigationAllowed || windowOffset <= minWindowOffset,
    currentDisabled: !periodNavigationAllowed || windowOffset === 0,
    nextDisabled: !periodNavigationAllowed || windowOffset >= 0,
  };
}

function chartPeriodOffset(chartKey) {
  return Math.min(0, Math.trunc(Number(state.chartPeriodOffsets?.[chartKey]) || 0));
}

function setChartPeriodOffset(chartKey, offset) {
  state.chartPeriodOffsets = {
    ...(state.chartPeriodOffsets || {}),
    [chartKey]: Math.min(0, Math.trunc(Number(offset) || 0)),
  };
}

function resetChartPeriodOffsets(...chartKeys) {
  const keys = chartKeys.length ? chartKeys : Object.keys(state.chartPeriodOffsets || {});
  keys.forEach((chartKey) => setChartPeriodOffset(chartKey, 0));
}

function syncChartPeriodNavigation(chartKey, range) {
  const navigation = tracePeriodNavigationState(range);
  document.querySelectorAll(`[data-chart-period-nav="${chartKey}"]`).forEach((container) => {
    container.hidden = !navigation.visible;
    container.dataset.windowOffset = String(Number(range?.windowOffset) || 0);
    const previous = container.querySelector('[data-chart-period-action="previous"]');
    const current = container.querySelector('[data-chart-period-action="current"]');
    const next = container.querySelector('[data-chart-period-action="next"]');
    if (previous) previous.disabled = navigation.previousDisabled;
    if (current) current.disabled = navigation.currentDisabled;
    if (next) next.disabled = navigation.nextDisabled;
  });
  return navigation;
}

function initChartPeriodNavigation(chartKey, rangeProvider, drawChart) {
  const container = document.querySelector(`[data-chart-period-nav="${chartKey}"]`);
  if (!container || container.dataset.periodNavigationReady === "true") return;
  container.dataset.periodNavigationReady = "true";
  container.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest('[data-chart-period-action]')
      : null;
    if (!button || button.disabled || !container.contains(button)) return;
    const range = rangeProvider();
    const action = button.getAttribute("data-chart-period-action") || "";
    const currentOffset = Number(range.windowOffset) || 0;
    const nextOffset = action === "previous"
      ? currentOffset - 1
      : action === "next" ? currentOffset + 1 : 0;
    setChartPeriodOffset(chartKey, nextOffset);
    drawChart();
  });
}

function runtimeTraceWindowRange() {
  const history = state.runtimeTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.runtimeTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("runtimeTrace"),
    simulationModeDurationMinutes(),
  );
  setChartPeriodOffset("runtimeTrace", range.windowOffset);
  return range;
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

function runtimeTracePointTimeLabel(point, range) {
  const time = String(point?.sim_time || point?.time || "").trim();
  if (time && time !== "--") return time;
  return runtimeAxisTickLabel(point?.minute, range, -1, 0);
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
  const range = runtimeTraceWindowRange();
  syncChartPeriodNavigation("runtimeTrace", range);
  const selectedCommandSeries = selectedRuntimeCommandTraceSeries(range);
  const chartDevices = selectedCommandSeries ? [] : runtimeTraceDevicesForChart();
  const points = selectedCommandSeries?.points
    || runtimeTraceWindowPoints(range).map((point) => runtimeAggregateTracePoint(point, chartDevices));
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
  $("runtimeTraceSummary").textContent = `${chartLabel} · ${traceWindowDataPointCount(points)} 点`;
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
    let previousY = Number.NaN;
    points.forEach((point) => {
      const value = numberOrNull(point[series.field]);
      if (value === null) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({
        x,
        y,
        minute: point.minute,
        time: point.sim_time || point.time,
        sim_time: point.sim_time || point.time,
        value,
      });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else if (series.key === "control") {
        ctx.lineTo(x, previousY);
        if (Math.abs(y - previousY) > 1e-9) ctx.lineTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      previousY = y;
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit, points: pixelPoints });
  };
  const unit = points.find((point) => point.unit)?.unit || "";
  visibleSeries.forEach((series) => drawSeries(series, series.key === "scada" ? 2 : 2.5));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    timeLabel: (point) => runtimeTracePointTimeLabel(point, range),
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

function measurementPresentationValue(value, row = null) {
  if (value === null || value === undefined || value === "") return value;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return String(row?.meas_type || "").toUpperCase() === "SOC" ? number * 100 : number;
}

function isWeatherMeasurement(row) {
  return row?.dev_type === "Environment" && row?.dev_name === "weather";
}

function isSignalMeasurement(row) {
  return Object.prototype.hasOwnProperty.call(SIGNAL_MEASUREMENT_LABELS, String(row?.meas_type || "").toUpperCase());
}

function formatMeasurementDisplayValue(value, row = null, analogFormatter = formatMeasurementValue) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return isSignalMeasurement(row) ? String(Math.round(number)) : analogFormatter(number);
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
  if (isSignalMeasurement(row)) return `${row.dev_type || ""}.${row.dev_name || row.name || ""}.${signalMeasurementLabel(row)}`;
  return isWeatherMeasurement(row) ? `Environment.weather.${weatherMeasurementLabel(row)}` : row.name;
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
  if (type === "SOC" || type === "LEVEL") return "%";
  if (type === "PRESSURE") return "MPa";
  if (type === "FLOW") return "Nm3/h";
  if (type === "GAS_QUANTITY") return "Nm3";
  if (type.startsWith("P")) return "kW";
  if (type.startsWith("Q")) return "kvar";
  if (type.startsWith("V")) return "V";
  if (type.startsWith("I")) return "A";
  return "";
}

function appendMeasurementTrace(snapshot) {
  const sampledClock = snapshot.measurement_clock;
  const clock = sampledClock && Number(sampledClock.step_count ?? 0) > 0
    ? sampledClock
    : snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return false;
  const rows = measurementCompareRows(snapshot.measurements || {});
  if (!rows.some((row) => (
    numberOrNull(row.real_value) !== null
    || numberOrNull(row.scada_value) !== null
  ))) {
    return false;
  }
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
  if (signature === state.lastMeasurementTraceKey) return false;
  state.lastMeasurementTraceKey = signature;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.measurementTraceHistory.length) || 0,
    sim_time: clock.time || "--",
    record_time: Date.now(),
    run_id: Number(clock.run_id ?? 0) || 0,
    step_count: Number(clock.step_count ?? 0) || 0,
    measurements: {},
  };
  rows.forEach((row) => {
    const key = measurementKey(row);
    point.measurements[key] = {
      name: measurementDisplayName(row) || "",
      dev_type: row.dev_type || "",
      dev_name: row.dev_name || "",
      meas_type: measurementTypeDisplay(row) || "",
      unit: measurementUnit(row.meas_type),
      real: numberOrNull(measurementPresentationValue(row.real_value, row)),
      scada: numberOrNull(measurementPresentationValue(row.scada_value, row)),
      valid: Number(row.valid) === 1 ? 1 : 0,
    };
  });
  const history = state.measurementTraceHistory || [];
  const latestPoint = history[history.length - 1];
  if (latestPoint && compareMeasurementHistoryPoints(point, latestPoint) <= 0) {
    const pointKey = measurementHistoryPointKey(point);
    let existingIndex = -1;
    for (let index = history.length - 1; index >= 0; index -= 1) {
      const candidate = history[index];
      if (measurementHistoryPointKey(candidate) === pointKey) {
        existingIndex = index;
        break;
      }
      if (compareMeasurementHistoryPoints(candidate, point) < 0) break;
    }
    if (existingIndex < 0) return false;
    const existing = history[existingIndex];
    history[existingIndex] = {
      ...existing,
      ...point,
      measurements: {
        ...(existing.measurements || {}),
        ...(point.measurements || {}),
      },
    };
  } else {
    history.push(point);
  }
  state.measurementTraceHistory = history;
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
  return true;
}

function resetMeasurementHistoryHydration() {
  state.measurementHistoryGeneration = (Number(state.measurementHistoryGeneration) || 0) + 1;
  state.measurementHistoryLoaded = {};
  state.measurementHistoryRequests = {};
}

function measurementHistoryDefinitions(snapshot = state.snapshot || {}) {
  const measurementDefinitions = snapshot.measurements?.definitions;
  if (Array.isArray(measurementDefinitions)) return measurementDefinitions;
  const staticDefinitions = snapshot.definitions?.measurement;
  return Array.isArray(staticDefinitions) ? staticDefinitions : [];
}

function measurementHistoryDefinitionIndex(row, definitions = measurementHistoryDefinitions()) {
  if (!row) return -1;
  const key = measurementKey(row);
  return definitions.findIndex((definition) => measurementKey(definition) === key);
}

function measurementHistoryPointKey(point) {
  return [
    Number(point?.run_id ?? 0) || 0,
    Number(point?.step_count ?? -1),
    Number(point?.minute ?? 0) || 0,
  ].join("|");
}

function compareMeasurementHistoryPoints(left, right) {
  return (
    (Number(left?.run_id) || 0) - (Number(right?.run_id) || 0)
    || (Number(left?.step_count) || 0) - (Number(right?.step_count) || 0)
    || (Number(left?.minute) || 0) - (Number(right?.minute) || 0)
  );
}

function mergeMeasurementHistoryPayload(payload, row, definitionIndex, definitions) {
  if (!payload || payload.encoding !== "measurement-history-arrays-v1") return false;
  const expectedSignature = measurementDefinitionSignature(definitions);
  if (String(payload.definition_signature || "") !== expectedSignature) {
    throw new Error("历史量测定义顺序签名不一致，历史帧已拒绝");
  }
  if (Number(payload.count) !== definitions.length) {
    throw new Error("历史量测定义长度不一致，历史帧已拒绝");
  }
  const currentRunId = Number(state.snapshot?.clock?.run_id ?? 0) || 0;
  const payloadRunId = Number(payload.run_id ?? 0) || 0;
  if (payloadRunId !== currentRunId) return false;
  const indices = Array.isArray(payload.indices) ? payload.indices.map(Number) : [];
  const selectedPosition = indices.indexOf(Number(definitionIndex));
  if (selectedPosition < 0) return false;
  const key = measurementKey(row);
  const incoming = (payload.frames || []).map((frame) => {
    const arrays = [frame.real_values, frame.scada_values, frame.valid_values];
    if (arrays.some((values) => !Array.isArray(values) || values.length !== indices.length)) {
      throw new Error("历史量测数组长度不一致，历史帧已拒绝");
    }
    const minute = Number(frame.absolute_minute);
    if (!Number.isFinite(minute)) throw new Error("历史量测仿真时刻无效，历史帧已拒绝");
    const real = numberOrNull(measurementPresentationValue(frame.real_values[selectedPosition], row));
    const scada = numberOrNull(measurementPresentationValue(frame.scada_values[selectedPosition], row));
    const validValue = frame.valid_values[selectedPosition];
    return {
      minute,
      sim_time: frame.simu_time || "--",
      record_time: frame.wall_time || "",
      run_id: Number(frame.run_id ?? payloadRunId) || payloadRunId,
      step_count: Number(frame.step_count ?? 0) || 0,
      history_seq: Number(frame.seq ?? 0) || 0,
      measurements: {
        [key]: {
          name: measurementDisplayName(row) || "",
          dev_type: row.dev_type || "",
          dev_name: row.dev_name || "",
          meas_type: measurementTypeDisplay(row) || "",
          unit: measurementUnit(row.meas_type),
          value: scada ?? real,
          real,
          scada,
          valid: validValue === null || validValue === undefined
            ? (Number(row.valid) === 1 ? 1 : 0)
            : (Number(validValue) === 1 ? 1 : 0),
        },
      },
    };
  });
  if (!incoming.length) return false;

  const merged = new Map();
  (state.measurementTraceHistory || []).forEach((point) => {
    merged.set(measurementHistoryPointKey(point), point);
  });
  incoming.forEach((point) => {
    const pointKey = measurementHistoryPointKey(point);
    const existing = merged.get(pointKey);
    if (existing) {
      existing.measurements = { ...(existing.measurements || {}), ...point.measurements };
      if (!existing.sim_time || existing.sim_time === "--") existing.sim_time = point.sim_time;
      if (!existing.record_time) existing.record_time = point.record_time;
      existing.run_id = point.run_id;
      existing.step_count = point.step_count;
      existing.history_seq = point.history_seq;
    } else {
      merged.set(pointKey, point);
    }
  });
  state.measurementTraceHistory = compactTraceHistory(
    Array.from(merged.values()).sort(compareMeasurementHistoryPoints),
    state.measurementTraceWindowMinutes,
  );
  return true;
}

async function ensureMeasurementHistoryForRow(row) {
  const definitions = measurementHistoryDefinitions();
  const definitionIndex = measurementHistoryDefinitionIndex(row, definitions);
  if (definitionIndex < 0 || !definitions.length) return false;
  const runId = Number(state.snapshot?.clock?.run_id ?? 0) || 0;
  const definitionSignature = measurementDefinitionSignature(definitions);
  const generation = Number(state.measurementHistoryGeneration) || 0;
  const requestKey = [state.activeModelId, runId, definitionSignature, definitionIndex, generation].join("|");
  if (state.measurementHistoryLoaded?.[requestKey]) return false;
  if (state.measurementHistoryRequests?.[requestKey]) {
    return state.measurementHistoryRequests[requestKey];
  }
  const request = api(`/api/measurement-history?indices=${definitionIndex}`)
    .then((payload) => {
      const currentDefinitions = measurementHistoryDefinitions();
      const currentRunId = Number(state.snapshot?.clock?.run_id ?? 0) || 0;
      if (
        (Number(state.measurementHistoryGeneration) || 0) !== generation
        ||
        currentRunId !== runId
        || measurementDefinitionSignature(currentDefinitions) !== definitionSignature
      ) {
        return false;
      }
      const changed = mergeMeasurementHistoryPayload(payload, row, definitionIndex, currentDefinitions);
      state.measurementHistoryLoaded[requestKey] = true;
      return changed;
    })
    .catch((error) => {
      console.warn("历史量测加载失败", error);
      return false;
    })
    .finally(() => {
      delete state.measurementHistoryRequests[requestKey];
    });
  state.measurementHistoryRequests[requestKey] = request;
  return request;
}

function ensureSelectedMeasurementHistory() {
  const row = selectedMeasurementRow();
  if (!row) return;
  ensureMeasurementHistoryForRow(row).then((changed) => {
    if (changed && measurementKey(row) === state.selectedMeasurementKey) {
      drawMeasurementTraceChart();
    }
  });
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
  ensureSelectedMeasurementHistory();
}

function measurementTraceWindowRange() {
  const history = state.measurementTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.measurementTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("measurementTrace"),
    simulationModeDurationMinutes(),
  );
  setChartPeriodOffset("measurementTrace", range.windowOffset);
  return range;
}

function measurementTraceWindowPoints(key = state.selectedMeasurementKey, range = measurementTraceWindowRange()) {
  if (!key) return [];
  const points = (state.measurementTraceHistory || [])
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
  return traceWindowRealPoints(points, range);
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
  syncChartPeriodNavigation("measurementTrace", range);
  const allRows = measurementCompareRows();
  const selectedRow = selectedMeasurementRow(allRows);
  const points = measurementTraceWindowPoints(state.selectedMeasurementKey, range);
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
  $("measurementTraceSummary").textContent = `${label} · ${traceWindowDataPointCount(points)} 点`;
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
      pixelPoints.push({
        x,
        y,
        minute: point.minute,
        time: point.sim_time || point.time,
        sim_time: point.sim_time || point.time,
        value,
      });
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
    timeLabel: (point) => runtimeTracePointTimeLabel(point, range),
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
  if (field === "real") return formatMeasurementDisplayValue(measurementPresentationValue(row.real_value, row), row);
  if (field === "scada") return formatMeasurementDisplayValue(measurementPresentationValue(row.scada_value, row), row);
  if (field === "weight") return escapeHtml(row.weight);
  if (field === "status") {
    const valid = Number(row.valid) === 1;
    return `<span class="status-dot ${valid ? "on" : ""}"></span>${valid ? "有效" : "无效"}`;
  }
  if (field === "diff") return formatMeasurementDisplayValue(measurementPresentationValue(row.diff, row), row);
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
              <td class="numeric-cell" data-measurement-live-field="real">${formatMeasurementDisplayValue(measurementPresentationValue(row.real_value, row), row)}</td>
              <td class="numeric-cell" data-measurement-live-field="scada">${formatMeasurementDisplayValue(measurementPresentationValue(row.scada_value, row), row)}</td>
              <td class="numeric-cell ${diffClass}" data-measurement-live-field="diff">${formatMeasurementDisplayValue(measurementPresentationValue(row.diff, row), row)}</td>
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
  if (isExtendedSimulationMode()) {
    const isYearMode = state.curveMode === "year";
    const dayCount = simulationModeDayCount();
    return {
      startField: "start_day",
      clearField: "clear_day",
      startLabel: "故障启始日",
      clearLabel: "结束日",
      inputType: isYearMode ? "text" : "number",
      min: isYearMode ? "" : "1",
      max: isYearMode ? "" : String(dayCount),
      step: isYearMode ? "" : "1",
      placeholder: isYearMode ? "1月1日" : `1-${dayCount}`,
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
  const day = Number.isFinite(value) ? value : fallback;
  return state.curveMode === "year"
    ? dayOfYearToMonthDay(day)
    : String(clamp(Math.round(Number(day) || 1), 1, simulationModeDayCount()));
}

function faultSimulationModeLabel() {
  return `${simulationModeLabel()} · ${isExtendedSimulationMode() ? "按日整定" : "按时分整定"}`;
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
    fault[field] = state.curveMode === "year"
      ? monthDayToDayOfYear(rawValue, fault[field] || 1)
      : clamp(Math.round(Number(rawValue) || Number(fault[field]) || 1), 1, simulationModeDayCount());
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
    fault[field] = state.curveMode === "year"
      ? monthDayToDayOfYear(rawValue, fault[field] || 1)
      : clamp(Math.round(Number(rawValue) || Number(fault[field]) || 1), 1, simulationModeDayCount());
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

function setCurveStatus(text) {
  const status = $("curveStatus") || state.pageSections?.curves?.querySelector("#curveStatus");
  if (status) status.textContent = text;
}

async function saveCurves() {
  const config = curveModeConfig();
  const dirtyKeys = state.curveDirtyKeys instanceof Set ? Array.from(state.curveDirtyKeys) : [];
  const keysToSave = Array.from(new Set([...dirtyKeys, ...selectedCurveKeys()]))
    .filter((key) => curveHasLoadedSeries(key));
  if (!keysToSave.length) {
    setCurveStatus("没有需要保存的曲线");
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
  setCurveStatus("已保存");
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
$("confirmNewModel").addEventListener("click", createNewModelFromFile);
$("newModelName").addEventListener("input", () => validateNewModelForm());
$("newModelServiceHost").addEventListener("input", () => validateNewModelForm());
$("newModelServicePort").addEventListener("input", () => validateNewModelForm());
$("closeUpdateModelDialog").addEventListener("click", closeUpdateModelDialog);
$("cancelUpdateModel").addEventListener("click", closeUpdateModelDialog);
$("updateModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "updateModelDialog") closeUpdateModelDialog();
});
$("selectUpdateModelFile").addEventListener("click", () => openUpdateModelFilePicker("updateModelFileInput"));
$("updateModelFileInput").addEventListener("change", handleUpdateModelFileSelected);
$("selectUpdateModelSvgFile").addEventListener("click", () => openUpdateModelFilePicker("updateModelSvgInput"));
$("updateModelSvgInput").addEventListener("change", handleUpdateModelSvgFileSelected);
$("updateModelServiceHost").addEventListener("input", () => validateUpdateModelForm());
$("updateModelServicePort").addEventListener("input", () => validateUpdateModelForm());
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
$("modelServiceToggle").addEventListener("click", toggleActiveModelService);
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
$("saveRuntimeParameters").addEventListener("click", saveWebRuntimeSettings);
$("undoRuntimeParameters").addEventListener("click", undoWebRuntimeSettings);
$("restoreRuntimeParameterDefaults").addEventListener("click", restoreWebRuntimeDefaults);
document.querySelectorAll("[data-runtime-setting]").forEach((input) => {
  input.addEventListener("input", () => updateWebRuntimeDraft(input));
});
$("refreshManualChanges").addEventListener("click", loadManualDefinitionChanges);
$("retryPendingManualChanges").addEventListener("click", retryPendingManualDefinitionChanges);
$("resetSelectedManualChanges").addEventListener("click", resetSelectedManualDefinitionChanges);
$("manualDefinitionChangesTable").addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") return;
  if (target.matches("[data-manual-change-select-all]")) {
    state.manualDefinitionChangeSelection = target.checked
      ? new Set(state.manualDefinitionChanges.map((item) => String(item.id || "")).filter(Boolean))
      : new Set();
    renderManualDefinitionChanges();
    return;
  }
  const changeId = target.dataset.manualChangeId || "";
  if (changeId) toggleManualDefinitionChange(changeId, target.checked);
});
[
  "parameterClockSpeed",
  "parameterComputeInterval",
  "parameterStorageInitialSoc",
  "parameterRemoteAdjustmentResponseRatio",
].forEach((id) => {
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
    else if (field === "origin") state.runtimeCommandOriginFilter = control.value || "all";
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
  const curveTreeToggle = event.target.closest("[data-curve-tree-toggle]");
  if (curveTreeToggle) {
    event.preventDefault();
    event.stopPropagation();
    toggleCurveTreeGroup(curveTreeToggle.dataset.curveTreeToggle || "");
    return;
  }
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
  const runtimeCommandDeleteButton = event.target.closest("[data-runtime-command-delete-name]");
  if (runtimeCommandDeleteButton) {
    event.preventDefault();
    event.stopPropagation();
    deleteRuntimeCommand(
      runtimeCommandDeleteButton.dataset.runtimeCommandDeleteName || "",
      runtimeCommandDeleteButton.dataset.runtimeCommandDeleteLabel || "",
    );
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
document.addEventListener("visibilitychange", () => {
  scheduleNextRefresh(pageIsHidden() ? HIDDEN_REFRESH_INTERVAL_MS : 0);
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
loadModels().finally(() => {
  if (activeModelServiceRunning()) refresh();
  restartRefreshScheduler();
});
