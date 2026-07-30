const apiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const MODEL_CONTEXTS_STORAGE_KEY = "polarTraineeModelContexts";
const OVERVIEW_BOTTOM_HEIGHT_KEY = "polarTraineeOverviewBottomHeight";
const OVERVIEW_BOTTOM_DEFAULT_HEIGHT = 156;
const OVERVIEW_BOTTOM_MIN_HEIGHT = 96;
const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;
const OVERVIEW_BOTTOM_COLUMN_RATIO_KEY = "polarTraineeOverviewBottomColumnRatio";
const OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO = 50;
const OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX = 260;
const VERTICAL_SPLIT_STORAGE_KEY = "polarTraineeVerticalSplitRatios";
const VERTICAL_SPLIT_DEFAULTS = {
  "trainee-curves": 60,
  "trainee-measurements": 52,
  "trainee-commands": 56,
  "trainee-renewable": 44,
};
const VERTICAL_SPLIT_DEFAULT_RATIO = 55;
const VERTICAL_SPLIT_MIN_TOP_PX = 120;
const VERTICAL_SPLIT_MIN_BOTTOM_PX = 120;
const STATIC_CACHE_STORAGE_KEY = "polarTraineeStaticCacheV1";
const STATIC_CACHE_MODEL_LIMIT = 4;
const API_REQUEST_TIMEOUT_MS = 30000;
const DEFAULT_CONVERTER_SOC_POWER_LIMITS = Object.freeze([
  0.0, 0.0, 0.2, 0.4, 0.4, 0.5, 0.6, 0.8, 0.8, 1.0,
]);

function readStoredModelContexts() {
  let contexts = {};
  try {
    const parsed = JSON.parse(localStorage.getItem(MODEL_CONTEXTS_STORAGE_KEY) || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) contexts = parsed;
  } catch (_error) {
    contexts = {};
  }
  const legacyModelId = localStorage.getItem("polarTraineeModelId") || "";
  const legacyLink = localStorage.getItem("polarTeacherInteractionLink") || "";
  if (legacyModelId && legacyLink && !contexts[legacyModelId]) {
    contexts[legacyModelId] = {
      interactionLink: legacyLink,
      teacherApiBase: (localStorage.getItem("polarTeacherApiUrl") || "").replace(/\/$/, ""),
      teacherModelName: localStorage.getItem("polarTeacherModelName") || legacyModelId,
      teacherSnapshotPath: localStorage.getItem("polarTeacherSnapshotPath") || "",
      teacherCommandPath: localStorage.getItem("polarTeacherCommandPath") || "",
      teacherMeasurementDeltaPath: localStorage.getItem("polarTeacherMeasurementDeltaPath") || "",
      receiveMode: false,
      frozen: false,
    };
  }
  return contexts;
}

const state = {
  snapshot: null,
  activePage: "",
  pageSections: {},
  pageMain: null,
  models: [],
  activeModelId: localStorage.getItem("polarTraineeModelId") || "",
  modelContexts: readStoredModelContexts(),
  receiveMode: false,
  frozen: false,
  receiveEpoch: 0,
  lastReceiveAt: "",
  snapshotSource: "",
  lastTeacherSnapshotLogKey: "",
  interactionLink: "",
  teacherApiBase: "",
  teacherModelId: "",
  teacherModelName: "",
  teacherSnapshotPath: "",
  teacherCommandPath: "",
  teacherMeasurementDeltaPath: "",
  localDefinitionSnapshot: null,
  localDefinitionModelId: "",
  receiveReconnectAttempts: 0,
  refreshRequestActive: false,
  receiveRequestActive: false,
  receiveStateSyncActive: false,
  lastReceiveStateSyncAtMs: 0,
  definitionMismatchLastKey: "",
  runtimeLogs: [],
  runtimeLogTypeFilter: "all",
  runtimeLogPage: 1,
  runtimeLogPageSize: 20,
  runtimeLogSeq: 0,
  seenCommandHistoryKeys: new Set(),
  selectedManagementModelId: "",
  cloneSourceModelId: "",
  updateTargetModelId: "",
  modelFilter: { dev_type: "all", dev_name: "" },
  activeModelParamTab: "",
  activeCurveDisplayKey: "wind_speed_mps",
  selectedCurveDisplayKeys: ["wind_speed_mps"],
  hiddenCurveDisplayKeys: [],
  curveDisplayCursor: { visible: false, x: 0, y: 0, index: 0 },
  curveDisplayLegendHitBoxes: [],
  lastCurveDisplayRenderKey: "",
  lastCurveDisplayTableKey: "",
  remoteControlDevice: null,
  remoteControlSending: false,
  remoteAdjustment: null,
  remoteAdjustmentSending: false,
  commandCancelSending: new Set(),
  measurementFilter: { dev_type: "all", dev_name: "" },
  measurementKeywordFilter: "",
  measurementTypeFilter: "all",
  measurementDeltaSeq: 0,
  measurementDeltaRequestActive: false,
  controlFilter: { dev_type: "all", dev_name: "" },
  commandKeywordFilter: "",
  commandTypeFilter: "all",
  commandOnlyActive: false,
  activeControlTab: "remote-control",
  selectedCommandTraceKey: "",
  selectedCommandTraceLabel: "",
  commandTraceHistory: [],
  commandTraceWindowMinutes: 60,
  chartSeriesHidden: {},
  chartSeriesSelected: {},
  chartCursors: {},
  chartSeriesHitData: {},
  chartPlotInfo: {},
  collapsedDeviceTreeGroups: {},
  deviceTreeSearch: {},
  activeMeasurementTab: "telemetry",
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  renewableTrendHistory: [],
  renewableTrendWindowMinutes: 60,
  traceRunId: null,
  renewableControl: {
    modelId: "",
    enabled: false,
    loopMode: "open",
    intervalSeconds: 2,
    largeStepThresholdKw: 10,
    stepCoefficient: 0.03,
    converterStepRatio: 0.03,
    dieselDeadbandRatio: 0.03,
    socDeadband: 0.05,
    converterSocPowerLimits: [...DEFAULT_CONVERTER_SOC_POWER_LIMITS],
    sending: false,
    requestActive: false,
    actionActive: false,
    revision: -1,
    lastPlan: null,
    lastCalculatedAt: "",
    lastSentAt: "",
    lastStatus: "请选择单次计算或启动实时控制。",
    logs: [],
    strategyTab: "wind",
    detailTab: "trend",
    logPage: 1,
    lastControlLogRenderKey: "",
  },
  overviewBottomHeight: overviewInitialBottomHeight(),
  overviewBottomSplitDrag: null,
  overviewBottomColumnRatio: overviewInitialBottomColumnRatio(),
  overviewBottomColumnSplitDrag: null,
  verticalSplitRatios: initialVerticalSplitRatios(),
  verticalSplitDrag: null,
  deviceTreeSelectionAnchors: {},
  virtualTables: {},
  virtualTableScrollRaf: {},
};
const pending = { run_status: new Map(), set_values: new Map() };
let pendingImportDefinitionFile = null;
let pendingNewModelFile = null;
let pendingUpdateModelFile = null;
const RENEWABLE_CONTROL_LOG_PAGE_SIZE = 8;
const RENEWABLE_STRATEGY_TABS = {
  wind: { label: "风电", categories: new Set(["风电"]) },
  pv: { label: "光伏", categories: new Set(["光伏"]) },
  storage: { label: "储能", categories: new Set(["储能平衡源"]) },
  diesel: { label: "柴发", categories: new Set(["柴油发电"]) },
  converter: { label: "变流", categories: new Set(["交直流变流器"]) },
};
const TRACE_HISTORY_LIMIT = 45000;
const TRACE_HIGH_RES_WINDOW_MINUTES = 24 * 60;
const VIRTUAL_TABLE_ROW_HEIGHT = 34;
const VIRTUAL_TABLE_MIN_ROWS = 220;
const VIRTUAL_TABLE_BUFFER_ROWS = 12;
const CURVE_DISPLAY_MODES = {
  year: { key: "year", label: "年仿真", pointCount: 8760, stepMinutes: 60, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 只读" },
  day: { key: "day", label: "日仿真", pointCount: 1440, stepMinutes: 1, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 只读" },
};
const CURVE_DISPLAY_ENV_KEYS = ["wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"];
const CURVE_DISPLAY_META = [
  { key: "wind_speed_mps", label: "风速", color: "#008c8c", min: 0, max: 50, digits: 2, unit: "m/s" },
  { key: "solar_irradiance_w_m2", label: "太阳辐照", color: "#b87500", min: 0, max: 1100, digits: 1, unit: "W/m2" },
  { key: "air_temp_c", label: "气温", color: "#2b6b7f", min: -60, max: 20, digits: 2, unit: "℃" },
];
const CURVE_DISPLAY_LOAD_META = { label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" };
const CURVE_DISPLAY_LOAD_COLORS = ["#c93a3a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_DISPLAY_PLOT = { left: 58, right: 24, top: 46, bottom: 34 };
const WEATHER_MEASUREMENT_LABELS = {
  WIND_SPEED: { label: "风速", order: 0 },
  SOLAR_IRRADIANCE: { label: "太阳辐照", order: 1 },
  AIR_TEMP: { label: "气温", order: 2 },
  HUMIDITY: { label: "湿度", order: 3 },
  AIR_PRESSURE: { label: "气压", order: 4 },
};
const SIGNAL_MEASUREMENT_LABELS = {
  RUN_STAT: { label: "运行状态", order: 0 },
  STATUS: { label: "开关状态", order: 1 },
};
const RECEIVE_STATE_SYNC_INTERVAL_MS = 5000;
const RECEIVE_MAX_RECONNECT_ATTEMPTS = 3;
const RECEIVE_WARNING_LIMIT = 40;

const $ = (id) => document.getElementById(id);
const deviceTreeRenderKeys = new WeakMap();

function contextKey(modelId = state.activeModelId) {
  return String(modelId || "__default__");
}

function defaultModelContext(modelId = state.activeModelId) {
  return {
    modelId: contextKey(modelId),
    receiveMode: false,
    frozen: false,
    interactionLink: "",
    teacherApiBase: "",
    teacherModelId: "",
    teacherModelName: "",
    teacherSnapshotPath: "",
    teacherCommandPath: "",
    teacherMeasurementDeltaPath: "",
    lastReceiveAt: "",
    snapshotSource: "",
    lastTeacherSnapshotLogKey: "",
    receiveReconnectAttempts: 0,
    measurementDeltaSeq: 0,
    runtimeLogSeq: 0,
    runtimeLogs: [],
    snapshot: null,
    measurementTraceHistory: [],
    commandTraceHistory: [],
    renewableTrendHistory: [],
  };
}

function activeModelContext(modelId = state.activeModelId) {
  const key = contextKey(modelId);
  return { ...defaultModelContext(modelId), ...(state.modelContexts[key] || {}) };
}

function serializableModelContext(context) {
  return {
    receiveMode: Boolean(context.receiveMode),
    frozen: Boolean(context.frozen),
    interactionLink: context.interactionLink || "",
    teacherApiBase: context.teacherApiBase || "",
    teacherModelId: context.teacherModelId || "",
    teacherModelName: context.teacherModelName || "",
    teacherSnapshotPath: context.teacherSnapshotPath || "",
    teacherCommandPath: context.teacherCommandPath || "",
    teacherMeasurementDeltaPath: context.teacherMeasurementDeltaPath || "",
    lastReceiveAt: context.lastReceiveAt || "",
  };
}

function persistModelContextsToStorage() {
  const payload = {};
  Object.entries(state.modelContexts || {}).forEach(([key, context]) => {
    payload[key] = serializableModelContext(context || {});
  });
  localStorage.setItem(MODEL_CONTEXTS_STORAGE_KEY, JSON.stringify(payload));
}

function captureActiveModelContext(overrides = {}) {
  return {
    ...activeModelContext(),
    receiveMode: state.receiveMode,
    frozen: state.frozen,
    interactionLink: state.interactionLink,
    teacherApiBase: state.teacherApiBase,
    teacherModelId: state.teacherModelId,
    teacherModelName: state.teacherModelName,
    teacherSnapshotPath: state.teacherSnapshotPath,
    teacherCommandPath: state.teacherCommandPath,
    teacherMeasurementDeltaPath: state.teacherMeasurementDeltaPath,
    lastReceiveAt: state.lastReceiveAt,
    snapshotSource: state.snapshotSource,
    lastTeacherSnapshotLogKey: state.lastTeacherSnapshotLogKey,
    receiveReconnectAttempts: state.receiveReconnectAttempts,
    measurementDeltaSeq: state.measurementDeltaSeq,
    runtimeLogSeq: state.runtimeLogSeq,
    runtimeLogs: state.runtimeLogs,
    snapshot: state.snapshot,
    measurementTraceHistory: state.measurementTraceHistory,
    commandTraceHistory: state.commandTraceHistory,
    renewableTrendHistory: state.renewableTrendHistory,
    ...overrides,
  };
}

function persistActiveModelContext(overrides = {}) {
  if (!state.activeModelId) return;
  state.modelContexts[contextKey()] = captureActiveModelContext(overrides);
  persistModelContextsToStorage();
}

function restoreModelContext(modelId = state.activeModelId) {
  const context = activeModelContext(modelId);
  state.receiveMode = Boolean(context.receiveMode);
  state.frozen = Boolean(context.frozen);
  state.interactionLink = context.interactionLink || "";
  state.teacherApiBase = (context.teacherApiBase || "").replace(/\/$/, "");
  state.teacherModelId = context.teacherModelId || "";
  state.teacherModelName = context.teacherModelName || "";
  state.teacherSnapshotPath = context.teacherSnapshotPath || "";
  state.teacherCommandPath = context.teacherCommandPath || "";
  state.teacherMeasurementDeltaPath = context.teacherMeasurementDeltaPath || "";
  state.lastReceiveAt = context.lastReceiveAt || "";
  state.snapshotSource = context.snapshotSource || "";
  state.lastTeacherSnapshotLogKey = context.lastTeacherSnapshotLogKey || "";
  state.receiveReconnectAttempts = Number(context.receiveReconnectAttempts) || 0;
  state.measurementDeltaSeq = Number(context.measurementDeltaSeq) || 0;
  state.runtimeLogSeq = Number(context.runtimeLogSeq) || 0;
  state.runtimeLogs = Array.isArray(context.runtimeLogs) ? context.runtimeLogs : [];
  state.snapshot = context.snapshot || null;
  state.measurementTraceHistory = Array.isArray(context.measurementTraceHistory) ? context.measurementTraceHistory : [];
  state.commandTraceHistory = Array.isArray(context.commandTraceHistory) ? context.commandTraceHistory : [];
  state.renewableTrendHistory = Array.isArray(context.renewableTrendHistory) ? context.renewableTrendHistory : [];
}

function receiveContextFromBackend(payload = {}) {
  return {
    receiveMode: Boolean(payload.active ?? payload.receiveMode),
    frozen: Boolean(payload.frozen),
    interactionLink: payload.interaction_link || payload.interactionLink || "",
    teacherApiBase: (payload.teacher_api_base || payload.teacherApiBase || "").replace(/\/$/, ""),
    teacherModelId: payload.teacher_model_id || payload.teacherModelId || "",
    teacherModelName: payload.teacher_model_name || payload.teacherModelName || payload.model_name || "",
    teacherSnapshotPath: payload.snapshot_path || payload.snapshotPath || "",
    teacherCommandPath: payload.command_path || payload.commandPath || "",
    teacherMeasurementDeltaPath: payload.measurement_delta_path || payload.measurementDeltaPath || "",
    lastReceiveAt: payload.last_receive_at || payload.lastReceiveAt || "",
  };
}

function receiveStatePayloadFromContext(context, overrides = {}) {
  const merged = { ...context, ...overrides };
  return {
    active: Boolean(merged.active ?? merged.receiveMode),
    frozen: Boolean(merged.frozen),
    interaction_link: merged.interactionLink || merged.interaction_link || "",
    teacher_api_base: merged.teacherApiBase || merged.teacher_api_base || "",
    teacher_model_id: merged.teacherModelId || merged.teacher_model_id || state.activeModelId || "",
    teacher_model_name: merged.teacherModelName || merged.teacher_model_name || merged.teacherModelName || "",
    snapshot_path: merged.teacherSnapshotPath || merged.snapshot_path || "",
    command_path: merged.teacherCommandPath || merged.command_path || "",
    measurement_delta_path: merged.teacherMeasurementDeltaPath || merged.measurement_delta_path || "",
    last_receive_at: merged.lastReceiveAt || merged.last_receive_at || "",
  };
}

function mergeBackendReceiveState(modelId, payload = {}, applyIfActive = false) {
  const key = contextKey(modelId);
  const previous = activeModelContext(modelId);
  state.modelContexts[key] = {
    ...previous,
    ...receiveContextFromBackend(payload),
  };
  persistModelContextsToStorage();
  if (applyIfActive && contextKey() === key) restoreModelContext(modelId);
  return state.modelContexts[key];
}

async function saveTraineeReceiveState(modelId = state.activeModelId, overrides = {}) {
  const key = contextKey(modelId);
  const context = key === contextKey() ? captureActiveModelContext(overrides) : { ...activeModelContext(modelId), ...overrides };
  const result = await api(`/api/trainee/receive-state?model_id=${encodeURIComponent(modelId)}`, {
    method: "POST",
    modelScoped: false,
    body: JSON.stringify(receiveStatePayloadFromContext(context, overrides)),
  });
  mergeBackendReceiveState(modelId, result, key === contextKey());
  return result;
}

async function syncActiveReceiveStateFromBackend(modelId = state.activeModelId) {
  if (!modelId) return null;
  const payload = await api(`/api/trainee/receive-state?model_id=${encodeURIComponent(modelId)}`, { modelScoped: false });
  return mergeBackendReceiveState(modelId, payload, contextKey(modelId) === contextKey());
}

async function syncActiveReceiveStateBeforeRefresh(force = false) {
  if (!state.activeModelId || state.receiveStateSyncActive) return;
  if (!force && Date.now() - state.lastReceiveStateSyncAtMs < RECEIVE_STATE_SYNC_INTERVAL_MS) return;
  state.receiveStateSyncActive = true;
  state.lastReceiveStateSyncAtMs = Date.now();
  const previousReceiveMode = state.receiveMode;
  const previousLink = state.interactionLink;
  try {
    await syncActiveReceiveStateFromBackend(state.activeModelId);
    if (state.receiveMode !== previousReceiveMode || state.interactionLink !== previousLink) {
      state.receiveEpoch += 1;
      state.receiveRequestActive = false;
      if (state.receiveMode) {
        state.frozen = false;
        state.lastReceiveAt = "";
        state.snapshotSource = "";
      }
    }
  } catch (_error) {
    // Keep the visible page usable if the local trainee service cannot read the shared receive state.
  } finally {
    state.receiveStateSyncActive = false;
  }
}

function mergeReceiveStatesFromBackend(items = {}) {
  Object.entries(items || {}).forEach(([modelId, payload]) => {
    mergeBackendReceiveState(modelId, payload, false);
  });
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
  return state.chartSeriesSelected?.[chartKey] || fallback || "";
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
    width: Math.max(1, Math.floor(rect.width || canvas.clientWidth || fallbackWidth)),
    height: Math.max(1, Math.floor(rect.height || canvas.clientHeight || fallbackHeight)),
  };
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
    if (key === "measurement" && currentPageName() === "measurements") {
      renderMeasurements(state.snapshot || {});
    }
    if (key.startsWith("traineeCommand:") && currentPageName() === "commands") {
      renderCombinedControlPage();
    }
    if (key.startsWith("curveDisplay:") && currentPageName() === "curves") {
      renderCurveDisplayTable(state.snapshot || {}, true);
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
  const ratio = options.ratio || 1;
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
  const valueFormatter = options.valueFormatter || formatNumber;
  const maxSeries = Math.max(1, Number(options.maxSeries) || 6);

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = 1 * ratio;
  ctx.setLineDash([5 * ratio, 4 * ratio]);
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
    ctx.lineWidth = 2 * ratio;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 4.5 * ratio, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = `${12 * ratio}px Microsoft YaHei, Arial`;
  const lines = [
    timeLabel ? `时刻: ${timeLabel}` : "",
    ...samples.slice(0, maxSeries).map(({ series, point }) => `${series.label}: ${valueFormatter(point.value)}${series.unit ? ` ${series.unit}` : ""}`),
    samples.length > maxSeries ? `另有 ${samples.length - maxSeries} 条曲线` : "",
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

const TRAINEE_PAGE_ROUTES = {
  "/": "overview",
  "/overview": "overview",
  "/model": "model",
  "/diagram": "diagram",
  "/curves": "curves",
  "/measurements": "measurements",
  "/commands": "commands",
  "/renewable": "renewable",
  "/history": "history",
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
  return TRAINEE_PAGE_ROUTES[normalizePagePath(location.pathname)] || fallback;
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
    renderActiveTraineePage(state.snapshot || {}, true);
    if (target === "renewable") refreshRenewableControlState({ preview: true });
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

function teacherScopedPath(path) {
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
  "diagram": ["files", "source_files", "work_files", "definitions", "diagram"],
  "curves": ["files", "source_files", "work_files", "definitions", "curves"],
  "measurements": ["files", "source_files", "work_files", "definitions"],
  "commands": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "renewable": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "history": [],
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

function staticCacheModelKey(snapshot = state.snapshot || {}) {
  const modelId = String(snapshot?.model?.id || state.activeModelId || "");
  if (!modelId) return "";
  if (state.receiveMode || state.snapshotSource === "teacher" || state.teacherApiBase) {
    return [
      "teacher",
      state.teacherApiBase || "",
      state.teacherSnapshotPath || "",
      state.teacherModelId || modelId,
    ].join("|");
  }
  return `local|${modelId}`;
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
  if (!snapshot?.static_meta) return snapshot;
  const cacheKey = staticCacheModelKey(snapshot);
  if (!cacheKey) return snapshot;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => CACHEABLE_STATIC_KEYS.includes(key));
  if (!requiredKeys.length) return snapshot;
  const entry = readStaticCacheStore()[cacheKey];
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
  if (!snapshot?.static_meta) return;
  const cacheKey = staticCacheModelKey(snapshot);
  if (!cacheKey) return;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => (
    CACHEABLE_STATIC_KEYS.includes(key)
    && snapshot[key] !== undefined
    && snapshot.static_meta?.[key] !== undefined
  ));
  if (!requiredKeys.length) return;
  const store = readStaticCacheStore();
  const entry = store[cacheKey] || { fields: {} };
  const fields = { ...(entry.fields || {}) };
  requiredKeys.forEach((key) => {
    fields[key] = {
      meta: snapshot.static_meta[key],
      value: snapshot[key],
    };
  });
  store[cacheKey] = { updatedAt: Date.now(), fields };
  if (writeStaticCacheStore(pruneStaticCacheStore(store))) return;
  requiredKeys.forEach((key) => {
    if (fields[key]?.value?.svg) delete fields[key];
  });
  store[cacheKey] = { updatedAt: Date.now(), fields };
  writeStaticCacheStore(pruneStaticCacheStore(store));
}

function staticSnapshotMissingKeys(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return (requiredKeys || []).filter((key) => snapshot?.[key] === undefined);
}

function mergeSnapshot(previous, incoming) {
  if (!previous || !incoming) return incoming;
  const merged = { ...previous, ...incoming };
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (
      incoming[key] === undefined
      && previous[key] !== undefined
      && (
        !incoming.static_meta?.[key]
        || !previous.static_meta?.[key]
        || staticMetaMatches(incoming.static_meta[key], previous.static_meta[key])
      )
    ) {
      merged[key] = previous[key];
    }
  });
  if (incoming.runtime_logs === undefined) delete merged.runtime_logs;
  return merged;
}

function pageNeedsRuntimeLogs(page = currentPageName()) {
  return ["overview", "history"].includes(page);
}

function snapshotLogLimit(page = currentPageName()) {
  return page === "history" ? 300 : 20;
}

function pageNeedsDevices(page = currentPageName()) {
  return ["overview", "model", "commands", "renewable"].includes(page);
}

function pageNeedsCommands(page = currentPageName()) {
  return ["overview", "commands", "renewable"].includes(page);
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
        : staticSnapshotKeysForPage(page)
    );
  const params = new URLSearchParams();
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("commands", pageNeedsCommands(page) ? "1" : "0");
  if (pageNeedsRuntimeLogs(page)) params.set("log_limit", String(snapshotLogLimit(page)));
  else params.set("logs", "0");
  if (requiredStaticKeys.length) params.set("static", requiredStaticKeys.join(","));
  else params.set("lite", "1");
  return `/api/snapshot?${params.toString()}`;
}

function appendUrlQuery(url, params) {
  try {
    const isAbsoluteUrl = /^https?:\/\//i.test(String(url || ""));
    const target = new URL(url, location.href);
    Object.entries(params || {}).forEach(([key, value]) => target.searchParams.set(key, String(value)));
    return isAbsoluteUrl ? target.href : `${target.pathname}${target.search}${target.hash}`;
  } catch (_error) {
    const separator = String(url || "").includes("?") ? "&" : "?";
    const query = new URLSearchParams(params || {}).toString();
    return `${url}${separator}${query}`;
  }
}

function teacherSnapshotPath() {
  if (state.teacherSnapshotPath) return state.teacherSnapshotPath;
  try {
    const legacyConnection = state.interactionLink
      ? legacyTeacherInteractionConnection(normalizeConnectionUrl(state.interactionLink))
      : null;
    if (legacyConnection?.snapshotPath) return legacyConnection.snapshotPath;
  } catch (_error) {
    // Ignore malformed cached links; fall back to the currently selected model.
  }
  return state.activeModelId
    ? `/api/snapshot?model_id=${encodeURIComponent(state.activeModelId)}`
    : "/api/snapshot";
}

function teacherReceiveAddress() {
  const base = state.teacherApiBase || "";
  const path = teacherSnapshotPath();
  if (!base) return path;
  return connectionApiUrl({ teacherApiBase: base }, path);
}

function teacherSnapshotPollAddress(page = currentPageName(), forceStaticKeys = null) {
  if (!Array.isArray(forceStaticKeys) && state.snapshot?.static_meta) {
    state.snapshot = restoreStaticSnapshotCache(state.snapshot, page);
  }
  const currentModelId = String(state.snapshot?.model?.id || "");
  const expectedTeacherModelId = String(state.teacherModelId || "");
  const modelChanged = currentModelId && expectedTeacherModelId && currentModelId !== expectedTeacherModelId;
  const requiredStaticKeys = Array.isArray(forceStaticKeys)
    ? forceStaticKeys
    : (
      state.snapshot?.static_meta && !modelChanged
        ? staticSnapshotMissingKeys(state.snapshot, staticSnapshotKeysForPage(page))
        : staticSnapshotKeysForPage(page)
    );
  const params = new URLSearchParams();
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("commands", pageNeedsCommands(page) ? "1" : "0");
  if (pageNeedsRuntimeLogs(page)) params.set("log_limit", String(snapshotLogLimit(page)));
  else params.set("logs", "0");
  if (requiredStaticKeys.length) params.set("static", requiredStaticKeys.join(","));
  else params.set("lite", "1");
  return `/api/trainee/snapshot?${params.toString()}`;
}

function measurementDeltaPathFromSnapshotPath(snapshotPath = "") {
  try {
    const url = new URL(snapshotPath || "/api/snapshot", location.href);
    const query = url.search || "";
    return `/api/measurements/delta${query}`;
  } catch (_error) {
    return "/api/measurements/delta";
  }
}

function teacherMeasurementDeltaAddress() {
  return appendUrlQuery("/api/trainee/measurements/delta", { after_seq: state.measurementDeltaSeq });
}

function displayReceiveAddress(address) {
  try {
    return decodeURI(String(address || ""));
  } catch (_error) {
    return String(address || "");
  }
}

async function teacherSnapshotApi(page = currentPageName(), forceStaticKeys = null) {
  return api(teacherSnapshotPollAddress(page, forceStaticKeys));
}

function measurementNameKey(item) {
  return String(item?.name || "");
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
    const payload = state.receiveMode
      ? await api(teacherMeasurementDeltaAddress())
      : await api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}`);
    const changed = applyMeasurementDelta(payload);
    if (changed && renderNow && currentPageName() === "measurements") renderMeasurements(state.snapshot || {});
    return changed;
  } finally {
    state.measurementDeltaRequestActive = false;
  }
}

function teacherCommandPath() {
  if (state.teacherCommandPath) return state.teacherCommandPath;
  return state.activeModelId
    ? `/api/student/commands?model_id=${encodeURIComponent(state.activeModelId)}`
    : "/api/student/commands";
}

function teacherCommandTargetName() {
  return `模拟台 ${teacherCommandPath()}`;
}

async function teacherCommandApi(options = {}) {
  return api("/api/trainee/commands", options);
}

function hasTeacherCommandConnection() {
  return Boolean(state.interactionLink && state.teacherCommandPath && state.teacherApiBase);
}

async function postTeacherCommand(body) {
  if (!hasTeacherCommandConnection()) {
    throw new Error("请先点击顶部“启动接收”，输入模拟台交互链接后再下发指令。");
  }
  return await teacherCommandApi({ method: "POST", body: JSON.stringify(body) });
}

function commandCycleMinutes(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const pointCount = Number(curves.point_count);
  const stepMinutes = Number(curves.time_step_minutes || CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)].stepMinutes);
  const curvePeriod = pointCount * stepMinutes;
  if (Number.isFinite(curvePeriod) && curvePeriod > 0) return curvePeriod;
  return curveDisplayMode(snapshot) === "year" ? 365 * 24 * 60 : 24 * 60;
}

function manualCommandExpiresAtAbsoluteMinute(snapshot = state.snapshot || {}) {
  const clock = snapshot.clock || {};
  const current = Number(clock.absolute_minute ?? clock.minute ?? 0) || 0;
  const cycleMinutes = commandCycleMinutes(snapshot);
  const cycleEnd = (Math.floor(current / cycleMinutes) + 1) * cycleMinutes;
  const stepMinutes = Number(clock.step_minutes || 1) || 1;
  const speed = Number(clock.speed || 1) || 1;
  return Math.max(cycleEnd, current + Math.max(1, stepMinutes * speed));
}

function manualCommandHoldPayload() {
  return {
    manual_hold: true,
    hold_until_cancelled: true,
    priority: "manual",
  };
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
  svg.classList.add("model-diagram-svg");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return svg.outerHTML;
}

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

function diagramMeasurementMaps(snapshot = state.snapshot || {}) {
  const measurements = snapshot.measurements || {};
  const scada = new Map();
  const real = new Map();
  (measurements.scada || []).forEach((row) => addDiagramMeasurementAliases(scada, row));
  (measurements.real || []).forEach((row) => addDiagramMeasurementAliases(real, row));
  return { scada, real };
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
    const updated = entry.issue_simu_time || entry.receive_simu_time || entry.simu_time || entry.wall_time || "";
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

function setDiagramElementValue(element, row) {
  const text = row?.value === undefined ? "--" : (row.unit !== undefined ? diagramRowText(row) : diagramNumberText(row.value));
  const tag = String(element.tagName || "").toLowerCase();
  if (["text", "tspan", "title", "desc"].includes(tag) || element instanceof HTMLElement) {
    element.textContent = text;
  } else {
    element.setAttribute("data-current-value", text);
  }
  element.classList.toggle("is-diagram-bound", row !== null && row !== undefined);
  element.setAttribute("data-bound-value", text);
  if (row?.updated) element.setAttribute("data-bound-time", row.updated);
}

function updateDiagramRealtimeBindings(container = $("modelDiagramCanvas"), snapshot = state.snapshot || {}) {
  if (!container) return;
  const measurementMaps = diagramMeasurementMaps(snapshot);
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
}

function renderModelDiagramPage(snapshot = state.snapshot || {}) {
  const activeSnapshot = snapshot || {};
  const canvas = $("modelDiagramCanvas");
  const summary = $("modelDiagramSummary");
  if (!canvas) return;
  const diagram = activeSnapshot.diagram || {};
  const modelName = activeSnapshot.model?.name || activeSnapshot.model?.id || "当前模型";
  if (!diagram.svg) {
    canvas.dataset.diagramKey = "";
    canvas.innerHTML = '<div class="empty-state">当前模型未配置接线图</div>';
    if (summary) summary.textContent = `${modelName} · 未配置`;
    return;
  }
  const key = `${activeSnapshot.model?.id || ""}|${diagram.updated_at || ""}|${diagram.size || ""}`;
  if (canvas.dataset.diagramKey !== key) {
    const sanitized = sanitizeDiagramSvg(diagram.svg);
    canvas.dataset.diagramKey = key;
    canvas.innerHTML = sanitized
      ? `<div class="model-diagram-svg-wrap">${sanitized}</div>`
      : '<div class="empty-state">接线图 SVG 无法解析</div>';
  }
  if (summary) summary.textContent = `${modelName} · ${diagram.filename || "diagram.svg"}`;
  updateDiagramRealtimeBindings(canvas, activeSnapshot);
}

function apiErrorText(error) {
  try {
    return JSON.parse(error.message)?.error || error.message;
  } catch (_parseError) {
    return error.message || "操作失败";
  }
}

function setReceiveLinkMessage(text, kind = "") {
  const message = $("receiveLinkMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function openReceiveLinkDialog() {
  const dialog = $("receiveLinkDialog");
  const input = $("receiveLinkInput");
  if (!dialog || !input) return;
  input.value = state.interactionLink || localStorage.getItem("polarTeacherInteractionLink") || "";
  setReceiveLinkMessage("请输入模拟台针对当前模型生成的交互链接。");
  $("confirmReceiveLink").disabled = false;
  dialog.showModal();
  input.focus();
  input.select();
}

function closeReceiveLinkDialog() {
  const dialog = $("receiveLinkDialog");
  if (dialog?.open) dialog.close();
}

function openReceiveWarningDialog(title, messages, summary = "") {
  const dialog = $("receiveWarningDialog");
  const titleNode = $("receiveWarningTitle");
  const summaryNode = $("receiveWarningSummary");
  const listNode = $("receiveWarningList");
  if (!dialog || !titleNode || !summaryNode || !listNode) return;
  const safeMessages = (Array.isArray(messages) ? messages : [messages])
    .filter((item) => String(item || "").trim())
    .slice(0, RECEIVE_WARNING_LIMIT);
  titleNode.textContent = title || "接收异常";
  summaryNode.textContent = summary || (safeMessages.length ? `发现 ${safeMessages.length} 项异常。` : "请检查交互链接与本地定义。");
  listNode.innerHTML = safeMessages.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  dialog.showModal();
}

function closeReceiveWarningDialog() {
  const dialog = $("receiveWarningDialog");
  if (dialog?.open) dialog.close();
}

function normalizeConnectionUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) throw new Error("请输入模拟台生成的交互链接。");
  const url = new URL(raw, location.href);
  if (!/^https?:$/.test(url.protocol)) throw new Error("交互链接必须是 http 或 https 地址。");
  return url;
}

function legacyTeacherInteractionConnection(url) {
  const path = url.pathname.replace(/\/+$/, "");
  if (!["/api/trainee-link", "/api/client-link"].includes(path)) {
    return null;
  }
  const modelId = url.searchParams.get("model_id") || url.searchParams.get("model") || "";
  if (!modelId) return null;
  const encodedModelId = encodeURIComponent(modelId);
  return {
    link: url.href,
    teacherApiBase: url.origin,
    modelId: String(modelId),
    modelName: String(modelId),
    snapshotPath: `/api/snapshot?model_id=${encodedModelId}`,
    commandPath: `/api/student/commands?model_id=${encodedModelId}`,
    measurementDeltaPath: `/api/measurements/delta?model_id=${encodedModelId}`,
  };
}

async function resolveTeacherInteractionLink(rawLink) {
  const url = normalizeConnectionUrl(rawLink);
  const payload = await api("/api/trainee/connect", {
    method: "POST",
    modelScoped: false,
    body: JSON.stringify({ link: url.href }),
  });
  const connection = payload.connection || {};
  const modelId = connection.model_id || connection.modelId || url.searchParams.get("model_id") || "";
  if (!modelId) throw new Error("交互链接缺少模型标识。");
  return {
    link: connection.link || url.href,
    teacherApiBase: String(connection.teacher_api_base || connection.teacherApiBase || url.origin).replace(/\/$/, ""),
    modelId: String(modelId),
    modelName: String(connection.model_name || connection.modelName || modelId),
    snapshotPath: String(connection.snapshot_path || connection.snapshotPath || `/api/snapshot?model_id=${encodeURIComponent(modelId)}`),
    commandPath: String(connection.command_path || connection.commandPath || `/api/student/commands?model_id=${encodeURIComponent(modelId)}`),
    measurementDeltaPath: String(
      connection.measurement_delta_path || connection.measurementDeltaPath || measurementDeltaPathFromSnapshotPath(
        connection.snapshot_path || connection.snapshotPath || `/api/snapshot?model_id=${encodeURIComponent(modelId)}`,
      ),
    ),
    initialSnapshot: payload.snapshot || null,
  };
}

function connectionApiUrl(connection, path) {
  const target = String(path || "");
  if (/^https?:\/\//i.test(target)) return target;
  const normalized = target.startsWith("/") ? target : `/${target}`;
  return `${connection.teacherApiBase}${normalized}`;
}

async function fetchTeacherSnapshot(connection) {
  if (connection?.initialSnapshot) return connection.initialSnapshot;
  return teacherSnapshotApi();
}

function hasLocalDefinitionModel(modelId) {
  return state.models.some((model) => model.id === modelId);
}

function localDefinitionModelId(preferredModelId = "") {
  if (preferredModelId && hasLocalDefinitionModel(preferredModelId)) return preferredModelId;
  if (hasLocalDefinitionModel(state.activeModelId)) return state.activeModelId;
  if (state.models.some((model) => model.id === state.localDefinitionModelId)) return state.localDefinitionModelId;
  return state.models[0]?.id || state.activeModelId || "";
}

async function fetchLocalDefinitionSnapshot(preferredModelId = "") {
  const modelId = localDefinitionModelId(preferredModelId);
  const path = modelId ? `/api/snapshot?model_id=${encodeURIComponent(modelId)}` : "/api/snapshot";
  const snapshot = await api(path, { modelScoped: false });
  return { modelId, snapshot };
}

async function selectLocalDefinitionSnapshotForTeacher(connection, teacherSnapshot, preferredLocalModelId = state.activeModelId) {
  const teacherModelId = String(connection?.modelId || "");
  const localModelId = String(preferredLocalModelId || "");
  if (teacherModelId && hasLocalDefinitionModel(teacherModelId)) {
    return { ...(await fetchLocalDefinitionSnapshot(teacherModelId)), usingTeacherBaseline: false };
  }
  if (!teacherModelId && hasLocalDefinitionModel(localModelId)) {
    return { ...(await fetchLocalDefinitionSnapshot(localModelId)), usingTeacherBaseline: false };
  }
  if (teacherModelId) {
    try {
      const local = await fetchLocalDefinitionSnapshot();
      return {
        modelId: teacherModelId,
        snapshot: teacherSnapshot,
        usingTeacherBaseline: true,
        fallbackModelId: local.modelId,
        mismatchMessages: compareSnapshotDefinitions(local.snapshot, teacherSnapshot),
      };
    } catch (error) {
      return {
        modelId: teacherModelId,
        snapshot: teacherSnapshot,
        usingTeacherBaseline: true,
        fallbackModelId: "",
        mismatchMessages: [apiErrorText(error)],
      };
    }
  }

  try {
    const local = await fetchLocalDefinitionSnapshot();
    const messages = compareSnapshotDefinitions(local.snapshot, teacherSnapshot);
    if (!messages.length) return { ...local, usingTeacherBaseline: false };
    return {
      modelId: teacherModelId || local.modelId,
      snapshot: teacherSnapshot,
      usingTeacherBaseline: true,
      fallbackModelId: local.modelId,
      mismatchMessages: messages,
    };
  } catch (error) {
    return {
      modelId: teacherModelId,
      snapshot: teacherSnapshot,
      usingTeacherBaseline: true,
      fallbackModelId: "",
      mismatchMessages: [apiErrorText(error)],
    };
  }
}

function applyTeacherConnection(connection) {
  state.interactionLink = connection.link;
  state.teacherApiBase = (connection.teacherApiBase || "").replace(/\/$/, "");
  state.teacherModelId = connection.modelId;
  state.teacherModelName = connection.modelName;
  state.teacherSnapshotPath = connection.snapshotPath;
  state.teacherCommandPath = connection.commandPath;
  state.teacherMeasurementDeltaPath = connection.measurementDeltaPath;
  state.measurementDeltaSeq = 0;
  persistActiveModelContext();
}

function sortedUnique(values) {
  return [...new Set((values || []).map((item) => String(item || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function previewList(values, limit = 8) {
  const list = Array.from(values || []);
  if (!list.length) return "无";
  const visible = list.slice(0, limit).join("，");
  return list.length > limit ? `${visible}，等 ${list.length} 项` : visible;
}

function pushSetDiff(messages, label, localValues, remoteValues) {
  const localSet = new Set(localValues || []);
  const remoteSet = new Set(remoteValues || []);
  const missing = [...localSet].filter((item) => !remoteSet.has(item)).sort((a, b) => a.localeCompare(b));
  const extra = [...remoteSet].filter((item) => !localSet.has(item)).sort((a, b) => a.localeCompare(b));
  if (missing.length) messages.push(`${label}缺少：${previewList(missing)}`);
  if (extra.length) messages.push(`${label}新增：${previewList(extra)}`);
}

function comparableScalar(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") return Number.isFinite(value) ? Number(value.toPrecision(12)) : String(value);
  if (typeof value === "boolean") return value;
  const text = String(value).trim();
  if (!text) return "";
  const number = Number(text);
  return Number.isFinite(number) ? Number(number.toPrecision(12)) : text;
}

function stableComparable(value) {
  if (Array.isArray(value)) return value.map(stableComparable);
  if (value && typeof value === "object") {
    return Object.keys(value).sort((a, b) => a.localeCompare(b)).reduce((result, key) => {
      result[key] = stableComparable(value[key]);
      return result;
    }, {});
  }
  return comparableScalar(value);
}

function stableStringify(value) {
  return JSON.stringify(stableComparable(value));
}

function textHash(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function definitionDevices(snapshot = {}) {
  const map = new Map();
  (snapshot.devices || []).forEach((dev) => {
    const devType = String(dev.dev_type || dev.type || "").trim();
    const devName = String(dev.dev_name || dev.name || "").trim();
    if (!devType || !devName) return;
    map.set(`${devType}.${devName}`, {
      setTypes: sortedUnique(dev.set_types || []),
    });
  });
  return map;
}

function definitionMeasurementKeys(snapshot = {}) {
  const measurements = snapshot.measurements || {};
  const rows = measurements.definitions?.length ? measurements.definitions : measurements.scada || [];
  return sortedUnique(rows.map((row) => [
    row.name || "",
    row.dev_type || "",
    row.dev_name || "",
    String(row.meas_type || "").toUpperCase(),
  ].join("|")));
}

function definitionParameterSummary(snapshot = {}) {
  const params = snapshot.device_parameters || {};
  const result = new Map();
  Object.keys(params).sort((a, b) => a.localeCompare(b)).forEach((blockName) => {
    const rows = Array.isArray(params[blockName]) ? params[blockName] : [];
    result.set(blockName, textHash(stableStringify(rows)));
  });
  return result;
}

function definitionCurveSummary(snapshot = {}) {
  const curves = snapshot.curves || {};
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  const loadNames = sortedUnique(Object.keys(loads));
  const loadCounts = loadNames.map((name) => `${name}:${Array.isArray(loads[name]) ? loads[name].length : 0}`);
  return {
    mode: String(curves.mode || "day"),
    stepMinutes: String(curves.time_step_minutes ?? ""),
    pointCount: String(curves.point_count ?? ""),
    weatherCount: Array.isArray(curves.weather) ? curves.weather.length : 0,
    weatherHash: textHash(stableStringify(curves.weather || [])),
    loadNames,
    loadCounts,
    loadHash: textHash(stableStringify(loadNames.map((name) => [name, loads[name] || []]))),
  };
}

function compareSnapshotDefinitions(localSnapshot, remoteSnapshot) {
  const messages = [];
  if (!localSnapshot) messages.push("本地模型定义不可用。");
  if (!remoteSnapshot) messages.push("模拟台数据不可用。");
  if (messages.length) return messages;

  const localDevices = definitionDevices(localSnapshot);
  const remoteDevices = definitionDevices(remoteSnapshot);
  pushSetDiff(messages, "模型设备", [...localDevices.keys()], [...remoteDevices.keys()]);
  [...localDevices.keys()].filter((key) => remoteDevices.has(key)).forEach((key) => {
    const localSetTypes = localDevices.get(key).setTypes;
    const remoteSetTypes = remoteDevices.get(key).setTypes;
    const localText = localSetTypes.join(",");
    const remoteText = remoteSetTypes.join(",");
    if (localText !== remoteText) {
      messages.push(`设备 ${key} 控制量定义不一致：本地 ${localText || "无"}；模拟台 ${remoteText || "无"}`);
    }
  });

  pushSetDiff(messages, "量测定义", definitionMeasurementKeys(localSnapshot), definitionMeasurementKeys(remoteSnapshot));

  const localParams = definitionParameterSummary(localSnapshot);
  const remoteParams = definitionParameterSummary(remoteSnapshot);
  pushSetDiff(messages, "设备参数表", [...localParams.keys()], [...remoteParams.keys()]);
  [...localParams.keys()].filter((key) => remoteParams.has(key)).forEach((key) => {
    if (localParams.get(key) !== remoteParams.get(key)) {
      messages.push(`设备参数表 ${key} 内容不一致。`);
    }
  });

  const localCurves = definitionCurveSummary(localSnapshot);
  const remoteCurves = definitionCurveSummary(remoteSnapshot);
  if (localCurves.mode !== remoteCurves.mode) messages.push(`仿真模式不一致：本地 ${localCurves.mode}；模拟台 ${remoteCurves.mode}`);
  if (localCurves.stepMinutes !== remoteCurves.stepMinutes) messages.push(`曲线步长不一致：本地 ${localCurves.stepMinutes || "--"}；模拟台 ${remoteCurves.stepMinutes || "--"}`);
  if (localCurves.pointCount !== remoteCurves.pointCount) messages.push(`曲线点数不一致：本地 ${localCurves.pointCount || "--"}；模拟台 ${remoteCurves.pointCount || "--"}`);
  if (localCurves.weatherCount !== remoteCurves.weatherCount || localCurves.weatherHash !== remoteCurves.weatherHash) {
    messages.push(`环境曲线定义不一致：本地 ${localCurves.weatherCount} 点；模拟台 ${remoteCurves.weatherCount} 点。`);
  }
  pushSetDiff(messages, "负荷曲线", localCurves.loadNames, remoteCurves.loadNames);
  if (localCurves.loadCounts.join("|") !== remoteCurves.loadCounts.join("|") || localCurves.loadHash !== remoteCurves.loadHash) {
    messages.push("负荷曲线数据不一致。");
  }

  return messages.slice(0, RECEIVE_WARNING_LIMIT);
}

function receiveMismatchKey(messages) {
  return (messages || []).join("\n");
}

function resetReceiveIssueStreak() {
  state.receiveReconnectAttempts = 0;
}

function stopReceiveAfterPersistentIssue(result, detail = [], simTime = "") {
  const detailItems = Array.isArray(detail) ? detail.filter(Boolean) : [detail].filter(Boolean);
  state.receiveMode = false;
  state.frozen = true;
  state.receiveEpoch += 1;
  state.receiveRequestActive = false;
  persistActiveModelContext({ receiveMode: false, frozen: true });
  saveTraineeReceiveState(state.activeModelId, { active: false, frozen: true }).catch((error) => {
    addRuntimeLog("接收模式", "学员台服务端", "保存保护状态失败", apiErrorText(error), "warn");
  });
  addRuntimeLog(
    "实时交互",
    "接收保护",
    "停止接收",
    [`连续 ${RECEIVE_MAX_RECONNECT_ATTEMPTS} 次接收异常`, ...detailItems],
    "error",
    true,
    simTime,
  );
  noteRenewableReceiveInterruption("连续接收异常，新能源优先策略保持运行，继续使用最近一次有效数据。");
  renderReceiveMode(result || "接收异常");
  openReceiveWarningDialog(
    `${result || "接收异常"}，已停止接收`,
    [`已连续 ${RECEIVE_MAX_RECONNECT_ATTEMPTS} 次发现接收异常。`, ...detailItems],
    "请检查模拟台仿真状态、交互链接和定义文件一致性。",
  );
}

function recordReceiveIssue(type, target, result, detail = "", simTime = "") {
  state.receiveReconnectAttempts += 1;
  const attempt = state.receiveReconnectAttempts;
  const detailItems = Array.isArray(detail) ? detail.filter(Boolean) : [detail].filter(Boolean);
  addRuntimeLog(
    type,
    target,
    result,
    [`连续告警 ${attempt}/${RECEIVE_MAX_RECONNECT_ATTEMPTS}`, ...detailItems],
    "warn",
    true,
    simTime,
  );
  if (attempt >= RECEIVE_MAX_RECONNECT_ATTEMPTS) {
    stopReceiveAfterPersistentIssue(result, detailItems, simTime);
    return false;
  }
  renderReceiveMode(`告警 ${attempt}/${RECEIVE_MAX_RECONNECT_ATTEMPTS}`);
  return true;
}

function handleReceiveDefinitionMismatch(messages, result = "定义不一致", simTime = "") {
  const detail = messages?.length ? messages : ["模拟台传入数据与本地定义不一致。"];
  const key = receiveMismatchKey(detail);
  state.definitionMismatchLastKey = key;
  return recordReceiveIssue("实时交互", "定义一致性校验", result, detail, simTime);
}

function validateTeacherSnapshotDefinitions(snapshot, result = "定义不一致") {
  if (!state.localDefinitionSnapshot) return true;
  if (!hasStaticSnapshotPayload(snapshot)) return true;
  const messages = compareSnapshotDefinitions(state.localDefinitionSnapshot, snapshot);
  if (!messages.length) {
    state.definitionMismatchLastKey = "";
    return true;
  }
  handleReceiveDefinitionMismatch(messages, result, snapshot.clock?.time || "--");
  return false;
}

function acceptTeacherSnapshot(snapshot, epoch = state.receiveEpoch) {
  if (!state.receiveMode || epoch !== state.receiveEpoch) return false;
  if (!validateTeacherSnapshotDefinitions(snapshot, "接收数据定义不一致")) return false;
  state.snapshotSource = "teacher";
  const clock = snapshot.clock || {};
  if (String(clock.state || "").toLowerCase() === "stopped") {
    renderSnapshot(snapshot);
    recordReceiveIssue(
      "实时交互",
      "模拟台 /api/snapshot",
      "模拟台未启动仿真",
      [`仿真状态 ${clock.state || "stopped"}`, "请在模拟台启动仿真后继续接收"],
      clock.time || "--",
    );
    return false;
  }
  resetReceiveIssueStreak();
  state.lastReceiveAt = new Date().toLocaleTimeString();
  const logKey = renewableClockKey(snapshot);
  if (logKey !== state.lastTeacherSnapshotLogKey) {
    const valuesNow = currentWeatherLoad(snapshot);
    const scada = snapshot.measurements?.scada || [];
    addRuntimeLog(
      "实时交互",
      "模拟台 /api/snapshot",
      "接收成功",
      [
        `量测 ${scada.length} 点`,
        Number.isFinite(valuesNow.windSpeed) ? `风速 ${formatNumber(valuesNow.windSpeed)} m/s` : "风速 未知",
        Number.isFinite(valuesNow.solarIrradiance) ? `光照 ${formatNumber(valuesNow.solarIrradiance)} W/m2` : "光照 未知",
        `负荷 ${formatNumber(valuesNow.loadKw)} kW`,
      ],
      "ok",
      false,
      snapshot.clock?.time || "--",
    );
    state.lastTeacherSnapshotLogKey = logKey;
  }
  renderSnapshot(snapshot);
  renderReceiveMode();
  return true;
}

async function attemptTeacherReconnect(epoch) {
  if (!state.receiveMode || epoch !== state.receiveEpoch) return;
  const attempt = state.receiveReconnectAttempts;
  renderReceiveMode(`重连中 ${attempt}/${RECEIVE_MAX_RECONNECT_ATTEMPTS}`);
  try {
    const connection = await resolveTeacherInteractionLink(state.interactionLink);
    const snapshot = await fetchTeacherSnapshot(connection);
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    applyTeacherConnection(connection);
    if (acceptTeacherSnapshot(snapshot, epoch)) {
      addRuntimeLog("实时交互", "模拟台交互链接", "重连成功", `模型 ${connection.modelName}`, "ok");
    }
  } catch (error) {
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    renderReceiveMode(`重连等待 ${attempt}/${RECEIVE_MAX_RECONNECT_ATTEMPTS}`);
  }
}

async function startReceiveModeFromLink() {
  const input = $("receiveLinkInput");
  const confirmButton = $("confirmReceiveLink");
  if (!input || !confirmButton) return;
  const activeModelIdBeforeReceive = state.activeModelId;
  confirmButton.disabled = true;
  setReceiveLinkMessage("正在校验交互链接。");
  try {
    const connection = await resolveTeacherInteractionLink(input.value);
    setReceiveLinkMessage("链接可用，正在接收第一帧数据。", "ok");
    const teacherSnapshot = await fetchTeacherSnapshot(connection);
    const {
      modelId: localModelId,
      snapshot: definitionSnapshot,
      usingTeacherBaseline,
      fallbackModelId,
      mismatchMessages,
    } = await selectLocalDefinitionSnapshotForTeacher(connection, teacherSnapshot, activeModelIdBeforeReceive);
    state.localDefinitionSnapshot = definitionSnapshot;
    state.localDefinitionModelId = localModelId;
    state.definitionMismatchLastKey = "";
    applyTeacherConnection(connection);
    state.receiveMode = true;
    state.frozen = false;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    state.measurementTraceHistory = [];
    state.commandTraceHistory = [];
    state.lastReceiveAt = "";
    state.snapshotSource = "";
    state.lastTeacherSnapshotLogKey = "";
    persistActiveModelContext();
    await saveTraineeReceiveState(activeModelIdBeforeReceive, { active: true, frozen: false });
    closeReceiveLinkDialog();
    addRuntimeLog(
      "接收模式",
      "模拟台交互链接",
      "启动接收",
      `模型 ${connection.modelName}；接收地址 ${teacherReceiveAddress()}`,
      "ok",
    );
    if (usingTeacherBaseline) {
      addRuntimeLog(
        "实时交互",
        "定义一致性校验",
        "使用远端定义基准",
        [
          `本地无同名模型 ${connection.modelName || connection.modelId}`,
          fallbackModelId ? `原本地模型 ${fallbackModelId}` : "",
          "已使用模拟台第一帧定义作为本次接收基准",
          ...(mismatchMessages || []).slice(0, 3),
        ],
        "warn",
      );
    }
    renderReceiveMode();
    acceptTeacherSnapshot(teacherSnapshot, state.receiveEpoch);
  } catch (error) {
    addRuntimeLog("接收模式", "模拟台交互链接", "启动接收失败", apiErrorText(error), "warn");
    setReceiveLinkMessage(apiErrorText(error), "error");
  } finally {
    confirmButton.disabled = false;
  }
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

function runtimeLogSimTime(simTime = "") {
  const explicit = String(simTime || "").trim();
  if (explicit) return explicit;
  return state.snapshot?.clock?.time || $("simTime")?.textContent?.trim() || "--";
}

function runtimeLogSimTimeFromCommandHistory(item = {}) {
  const explicit = item.simu_time || item.sim_time || item.clock?.time || "";
  if (explicit) return runtimeLogSimTime(explicit);
  const minute = Number(item.issued_absolute_minute);
  if (Number.isFinite(minute)) return formatTraceClockMinute(minute);
  return runtimeLogSimTime();
}

function simulationClockTextFromMinute(minute, snapshot = state.snapshot || {}) {
  const numericMinute = Number(minute);
  if (!Number.isFinite(numericMinute)) return "--";
  const timeText = formatTraceClockMinute(numericMinute);
  if (curveDisplayMode(snapshot) !== "year") return timeText;
  let dayOfYear = Math.floor(Math.max(0, Math.round(numericMinute)) / 1440) % 365;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfYear >= monthDays[month]) {
    dayOfYear -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(dayOfYear + 1).padStart(2, "0")} ${timeText}`;
}

function currentCommandSendTimeInfo(snapshot = state.snapshot || {}) {
  const clock = snapshot.clock || {};
  const minute = Number(clock.absolute_minute ?? clock.minute);
  const absoluteMinute = Number.isFinite(minute) ? minute : null;
  return {
    sent_wall_time: runtimeLogTime(),
    sent_simu_time: absoluteMinute === null ? runtimeLogSimTime(clock.time || "") : simulationClockTextFromMinute(absoluteMinute, snapshot),
    sent_absolute_minute: absoluteMinute,
  };
}

function withCommandSendTime(body, snapshot = state.snapshot || {}) {
  const timeInfo = currentCommandSendTimeInfo(snapshot);
  const payload = {
    ...body,
    sent_wall_time: timeInfo.sent_wall_time,
    sent_simu_time: timeInfo.sent_simu_time,
  };
  if (timeInfo.sent_absolute_minute !== null) payload.sent_absolute_minute = timeInfo.sent_absolute_minute;
  return payload;
}

function commandSentTimeInfo(entry = {}, snapshot = state.snapshot || {}) {
  const payload = entry.payload || {};
  const wallTime = runtimeLogWallTimeText(
    payload.sent_wall_time
    || payload.trainee_sent_wall_time
    || entry.sent_wall_time
    || entry.trainee_sent_wall_time
    || entry.time
    || "",
  );
  const explicitSimTime = String(
    payload.sent_simu_time
    || payload.trainee_sent_simu_time
    || entry.sent_simu_time
    || entry.trainee_sent_simu_time
    || entry.simu_time
    || entry.sim_time
    || "",
  ).trim();
  if (explicitSimTime) return { wall_time: wallTime, simu_time: explicitSimTime };
  const minute = Number(
    payload.sent_absolute_minute
    ?? payload.trainee_sent_absolute_minute
    ?? entry.sent_absolute_minute
    ?? entry.trainee_sent_absolute_minute
    ?? entry.issued_absolute_minute,
  );
  return {
    wall_time: wallTime,
    simu_time: Number.isFinite(minute) ? simulationClockTextFromMinute(minute, snapshot) : "--",
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
      const entryRunId = Number(entry.run_id);
      if (!Number.isFinite(entryRunId) || entryRunId !== currentRunId) return false;
    }
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = Number(entry.issued_absolute_minute);
    const expires = Number(entry.expires_at_absolute_minute);
    if (!Number.isFinite(issued) || !Number.isFinite(expires)) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function addRuntimeLog(type, target, result, detail = "", level = "info", renderNow = true, simuTime = "", scope = "") {
  state.runtimeLogSeq += 1;
  state.runtimeLogs.unshift({
    seq: state.runtimeLogSeq,
    wall_time: runtimeLogTime(),
    simu_time: runtimeLogSimTime(simuTime),
    type,
    target,
    result,
    detail,
    level,
    scope,
  });
  state.runtimeLogs = state.runtimeLogs.slice(0, 300);
  if (renderNow) renderHistoryIfMounted();
}

function runtimeLogDetailText(detail) {
  if (Array.isArray(detail)) return detail.filter(Boolean).join("；");
  if (detail && typeof detail === "object") {
    return Object.entries(detail)
      .map(([key, value]) => `${key}: ${value}`)
      .join("；");
  }
  return String(detail || "");
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 32768;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function setImportStatus(text, kind = "") {
  const target = $("importStatus");
  if (!target) return;
  target.textContent = text || "";
  target.classList.toggle("is-error", kind === "error");
  target.classList.toggle("is-ok", kind === "ok");
}

function normalizeModels(models = state.models) {
  return (Array.isArray(models) ? models : [])
    .map((model) => ({
      ...model,
      id: String(model?.id || model?.model_id || "").trim(),
      name: String(model?.name || model?.model_name || model?.id || model?.model_id || "").trim(),
    }))
    .filter((model) => model.id);
}

function modelById(modelId) {
  const targetId = String(modelId || "");
  return normalizeModels().find((model) => model.id === targetId) || null;
}

function isModelNameTaken(name, ignoreId = "") {
  const normalized = String(name || "").trim();
  const ignored = String(ignoreId || "").trim();
  return normalizeModels().some((model) => (model.id === normalized || model.name === normalized) && model.id !== ignored);
}

function traineeReceiveStateForModel(modelId) {
  return activeModelContext(modelId);
}

function modelManagementState(model) {
  const modelId = String(model?.id || "");
  const context = traineeReceiveStateForModel(modelId);
  if (context.receiveMode) return "receiving";
  if (context.frozen) return "frozen";
  return String(model?.clock_state || "stopped");
}

function modelManagementStateText(value) {
  return {
    receiving: "接收中",
    frozen: "已冻结",
    running: "运行中",
    paused: "暂停中",
    stopped: "已停止",
  }[value] || value || "--";
}

function canEditManagedModel(model) {
  const stateText = modelManagementState(model);
  return stateText !== "receiving" && stateText !== "running" && stateText !== "paused";
}

function setModelManagementMessage(text, kind = "") {
  const message = $("modelManagementMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function ensureSelectedManagementModelId(models = normalizeModels()) {
  if (!models.length) {
    state.selectedManagementModelId = "";
    return "";
  }
  const selectedId = String(state.selectedManagementModelId || "");
  if (selectedId && models.some((model) => model.id === selectedId)) return selectedId;
  const activeId = String(state.activeModelId || "");
  const nextId = activeId && models.some((model) => model.id === activeId) ? activeId : models[0].id;
  state.selectedManagementModelId = nextId;
  return nextId;
}

function selectedManagementModelId() {
  return ensureSelectedManagementModelId();
}

function selectedManagementModel() {
  return modelById(selectedManagementModelId());
}

function updateModelContextMenuActions() {
  const models = normalizeModels();
  const selected = selectedManagementModel();
  const hasSelected = Boolean(selected);
  const editable = selected ? canEditManagedModel(selected) : false;
  const menu = $("modelContextMenu");
  const exportButton = menu?.querySelector('[data-model-context-action="export"]');
  const cloneButton = menu?.querySelector('[data-model-context-action="clone"]');
  const updateButton = menu?.querySelector('[data-model-context-action="update"]');
  const deleteButton = menu?.querySelector('[data-model-context-action="delete"]');
  if (exportButton) exportButton.disabled = !hasSelected;
  if (cloneButton) cloneButton.disabled = !hasSelected;
  if (updateButton) {
    updateButton.disabled = !editable;
    updateButton.title = !hasSelected
      ? "请选择模型"
      : (editable ? "导入修改后的模型与图形等定义数据" : "模型正在接收或运行中，不能修改");
  }
  if (deleteButton) {
    const canDelete = hasSelected && models.length > 1 && editable;
    deleteButton.disabled = !canDelete;
    deleteButton.title = !hasSelected
      ? "请选择模型"
      : (models.length <= 1
        ? "至少需要保留一个模型"
        : (editable ? "删除选中的本地模型" : "模型正在接收或运行中，不能删除"));
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
  const models = normalizeModels();
  if (!models.length) {
    list.innerHTML = '<div class="model-management-empty">暂无本地模型</div>';
    state.selectedManagementModelId = "";
    updateModelContextMenuActions();
    return;
  }
  const selectedId = ensureSelectedManagementModelId(models);
  const branchHtml = models.map((model) => {
    const isActive = model.id === state.activeModelId;
    const isSelected = model.id === selectedId;
    const operationState = modelManagementState(model);
    return `
      <div
        class="model-management-item ${isActive ? "is-active" : ""} ${isSelected ? "is-selected" : ""}"
        role="treeitem"
        tabindex="0"
        aria-selected="${isSelected ? "true" : "false"}"
        data-model-id="${escapeHtml(model.id)}"
      >
        <span class="model-management-node-mark" aria-hidden="true"></span>
        <strong class="model-node-name">${escapeHtml(model.name || model.id)}</strong>
        <div class="model-item-badges">
          ${isActive ? '<span class="model-current-pill">当前</span>' : ""}
          <span class="model-state-pill" data-state="${escapeHtml(operationState)}">${escapeHtml(modelManagementStateText(operationState))}</span>
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
    <div class="model-management-branches" role="group">${branchHtml}</div>
  `;
  updateModelContextMenuActions();
}

async function openModelManagementDialog() {
  const dialog = $("modelManagementDialog");
  if (!dialog) return;
  if (!dialog.open) dialog.showModal();
  setModelManagementMessage("正在读取模型列表...");
  try {
    await loadModels();
    ensureSelectedManagementModelId();
    renderModelManagementList();
    setModelManagementMessage("可新建模型或导入定义包；右键模型节点可导出、复制、修改或删除。", "ok");
  } catch (error) {
    renderModelManagementList();
    setModelManagementMessage(apiErrorText(error), "error");
  }
}

function closeModelManagementDialog() {
  closeModelContextMenu();
  const dialog = $("modelManagementDialog");
  if (dialog?.open) dialog.close();
}

function closeModelContextMenu() {
  const menu = $("modelContextMenu");
  if (menu) menu.hidden = true;
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

function handleModelManagementAction(event) {
  closeModelContextMenu();
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  setSelectedManagementModel(item.dataset.modelId || "");
  setModelManagementMessage("可新建模型或导入定义包；右键模型节点可导出、复制、修改或删除。", "ok");
}

function handleModelManagementKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  setSelectedManagementModel(item.dataset.modelId || "");
}

function openModelContextMenu(event) {
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  setSelectedManagementModel(item.dataset.modelId || "");
  const menu = $("modelContextMenu");
  if (!menu) return;
  updateModelContextMenuActions();
  menu.hidden = false;
  positionModelContextMenu(menu, event.clientX, event.clientY);
}

function suggestedImportModelName(filename) {
  return String(filename || "导入模型")
    .replace(/\.zip$/i, "")
    .replace(/_definitions_\d{8}_\d{6}$/i, "")
    .replace(/_definitions$/i, "")
    .trim() || "导入模型";
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
  const input = $("newModelName");
  const button = $("newModelButton");
  const selectFile = $("selectNewModelFile");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "新建中" : "新建";
  }
  if (input) input.disabled = isBusy;
  if (button) button.disabled = isBusy;
  if (selectFile) selectFile.disabled = isBusy;
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
      .replace(/\.zip$/i, "")
      .replace(/_definitions_\d{8}_\d{6}$/i, "")
      .replace(/_definitions$/i, "")
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
    setNewModelMessage(showBlank ? "请选择模拟台导出的定义压缩包。" : "", showBlank ? "error" : "");
    return false;
  }
  if (!String(pendingNewModelFile.name || "").toLowerCase().endsWith(".zip")) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage("请选择 .zip 格式的定义压缩包。", "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setNewModelMessage("");
  return true;
}

function openNewModelDialog() {
  const dialog = $("newModelDialog");
  const input = $("newModelName");
  if (!dialog || !input) return;
  pendingNewModelFile = null;
  const fileInput = $("newModelFileInput");
  if (fileInput) fileInput.value = "";
  $("newModelFilename").textContent = "未选择文件";
  input.value = uniqueNewModelName("新模型");
  setNewModelMessage("");
  validateNewModelForm();
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeNewModelDialog() {
  const dialog = $("newModelDialog");
  if (dialog?.open) dialog.close();
  pendingNewModelFile = null;
  const fileInput = $("newModelFileInput");
  if (fileInput) fileInput.value = "";
  $("newModelFilename").textContent = "未选择文件";
  setNewModelMessage("");
  setNewModelBusy(false);
}

function handleNewModelFileSelected(event) {
  const file = event.target.files?.[0] || null;
  pendingNewModelFile = file;
  $("newModelFilename").textContent = file?.name || "未选择文件";
  const input = $("newModelName");
  if (file && input && !String(input.value || "").trim()) {
    input.value = suggestedNewModelName(file.name);
  }
  validateNewModelForm(Boolean(file));
}

async function createNewModelFromArchive() {
  const file = pendingNewModelFile;
  const input = $("newModelName");
  const name = String(input?.value || "").trim();
  if (!file || !validateNewModelForm(true)) {
    input?.focus();
    return;
  }
  setNewModelBusy(true);
  setNewModelMessage("正在导入模拟台定义压缩包并创建本地模型...");
  addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "新建请求", `${name} ← ${file.name}`);
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/models/import-definitions", {
      modelScoped: false,
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
    closeNewModelDialog();
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage(`已新建模型：${name}`, "ok");
    setImportStatus(`已新建模型：${name}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "新建成功", `模型 ${name}`, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setNewModelMessage(message.includes("已存在") ? `${message}，请输入新的模型名称。` : message, "error");
    setImportStatus(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "新建失败", message, "error");
  } finally {
    setNewModelBusy(false);
    if ($("newModelDialog")?.open) validateNewModelForm();
  }
}

function setImportModelMessage(text, kind = "") {
  const message = $("importModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function validateImportModelName(showBlank = false) {
  const input = $("importModelName");
  const confirm = $("confirmImportModel");
  const name = String(input?.value || "").trim();
  if (!pendingImportDefinitionFile) {
    if (confirm) confirm.disabled = true;
    setImportModelMessage(showBlank ? "请选择定义包。" : "");
    return false;
  }
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
  $("importModelFilename").textContent = file.name;
  input.value = suggestedImportModelName(file.name);
  setImportModelMessage("");
  validateImportModelName();
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeImportModelDialog() {
  const dialog = $("importModelDialog");
  if (dialog?.open) dialog.close();
  pendingImportDefinitionFile = null;
  const input = $("definitionArchiveInput");
  if (input) input.value = "";
  setImportModelMessage("");
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
  setImportStatus(file.name);
  addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "导入请求", `${name} ← ${file.name}`);
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/models/import-definitions", {
      modelScoped: false,
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
    setModelManagementMessage(`已导入模型：${name}`, "ok");
    setImportStatus(`已导入模型：${name}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "导入成功", `模型 ${name}`, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setImportModelMessage(message.includes("已存在") ? `${message}，请输入新的模型名称。` : message, "error");
    setImportStatus(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "导入失败", message, "error");
  } finally {
    setImportModelBusy(false);
  }
}

function setUpdateModelMessage(text, kind = "") {
  const message = $("updateModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function validateUpdateModelForm(showBlank = false) {
  const confirm = $("confirmUpdateModel");
  const target = modelById(state.updateTargetModelId);
  if (!target) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择要修改的模型。", "error");
    return false;
  }
  if (!canEditManagedModel(target)) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("模型正在接收或运行中，不能修改。", "error");
    return false;
  }
  if (!pendingUpdateModelFile) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage(showBlank ? "请选择模拟台导出的定义压缩包。" : "");
    return false;
  }
  if (!String(pendingUpdateModelFile.name || "").toLowerCase().endsWith(".zip")) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择 .zip 格式的定义压缩包。", "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setUpdateModelMessage("");
  return true;
}

function openUpdateModelDialog(modelId = selectedManagementModelId()) {
  const target = modelById(modelId);
  if (!target) {
    setModelManagementMessage("请选择要修改的模型。", "error");
    return;
  }
  if (!canEditManagedModel(target)) {
    setModelManagementMessage("模型正在接收或运行中，不能修改。", "error");
    return;
  }
  state.updateTargetModelId = target.id;
  pendingUpdateModelFile = null;
  $("updateModelTargetName").textContent = target.name || target.id;
  $("updateModelFilename").textContent = "未选择文件";
  const input = $("updateModelFileInput");
  if (input) input.value = "";
  setUpdateModelMessage("");
  validateUpdateModelForm();
  const dialog = $("updateModelDialog");
  if (!dialog?.open) dialog?.showModal();
}

function closeUpdateModelDialog() {
  const dialog = $("updateModelDialog");
  if (dialog?.open) dialog.close();
  state.updateTargetModelId = "";
  pendingUpdateModelFile = null;
  const input = $("updateModelFileInput");
  if (input) input.value = "";
  setUpdateModelMessage("");
}

function handleUpdateModelFileSelected(event) {
  const file = event.target.files?.[0] || null;
  pendingUpdateModelFile = file;
  $("updateModelFilename").textContent = file?.name || "未选择文件";
  validateUpdateModelForm(Boolean(file));
}

async function updateModelFromArchive() {
  const file = pendingUpdateModelFile;
  const modelId = state.updateTargetModelId;
  if (!file || !validateUpdateModelForm(true)) return;
  const target = modelById(modelId) || {};
  const modelName = target.name || target.id || modelId;
  const updatedActiveModel = String(modelId || "") === String(state.activeModelId || "");
  const confirm = $("confirmUpdateModel");
  if (confirm) {
    confirm.disabled = true;
    confirm.textContent = "修改中";
  }
  setUpdateModelMessage("正在导入模拟台定义压缩包并覆盖本地模型定义...");
  addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "修改请求", `${modelName} ← ${file.name}`);
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/models/import-definitions", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({
        model_id: modelId,
        filename: file.name,
        data_base64: dataBase64,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    closeUpdateModelDialog();
    state.selectedManagementModelId = modelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage(`模型已修改：${modelName}`, "ok");
    setImportStatus(`模型已修改：${modelName}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "修改成功", `模型 ${modelName}`, "ok");
    if (updatedActiveModel) {
      state.localDefinitionSnapshot = null;
      state.localDefinitionModelId = "";
      await refresh();
    }
  } catch (error) {
    const message = apiErrorText(error);
    setUpdateModelMessage(message, "error");
    setModelManagementMessage(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/import-definitions", "修改失败", message, "error");
  } finally {
    if (confirm) {
      confirm.textContent = "修改";
      validateUpdateModelForm();
    }
  }
}

function setCloneModelMessage(text, kind = "") {
  const message = $("cloneModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function uniqueCloneModelName(sourceName = "模型") {
  const base = String(sourceName || "模型").trim().replace(/_copy\d*$/i, "") || "模型";
  let candidate = `${base}_copy`;
  let index = 2;
  while (isModelNameTaken(candidate)) {
    candidate = `${base}_copy${index}`;
    index += 1;
  }
  return candidate;
}

function validateCloneModelName(showBlank = false) {
  const input = $("cloneModelName");
  const confirm = $("confirmCloneModel");
  const name = String(input?.value || "").trim();
  if (!name) {
    if (confirm) confirm.disabled = true;
    setCloneModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    if (confirm) confirm.disabled = true;
    setCloneModelMessage(`模型已存在：${name}，请输入新的模型名称。`, "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setCloneModelMessage("");
  return true;
}

function openCloneModelDialog(modelId = selectedManagementModelId()) {
  const source = modelById(modelId);
  if (!source) {
    setModelManagementMessage("请选择要复制的模型。", "error");
    return;
  }
  state.cloneSourceModelId = source.id;
  $("cloneModelSourceName").textContent = source.name || source.id;
  const input = $("cloneModelName");
  if (input) input.value = uniqueCloneModelName(source.name || source.id);
  setCloneModelMessage("");
  validateCloneModelName();
  const dialog = $("cloneModelDialog");
  if (!dialog?.open) dialog?.showModal();
  requestAnimationFrame(() => {
    input?.focus();
    input?.select();
  });
}

function closeCloneModelDialog() {
  const dialog = $("cloneModelDialog");
  if (dialog?.open) dialog.close();
  state.cloneSourceModelId = "";
  setCloneModelMessage("");
}

async function cloneManagedModel() {
  const sourceId = state.cloneSourceModelId || selectedManagementModelId();
  const input = $("cloneModelName");
  const name = String(input?.value || "").trim();
  if (!sourceId || !validateCloneModelName(true)) return;
  const confirm = $("confirmCloneModel");
  if (confirm) {
    confirm.disabled = true;
    confirm.textContent = "复制中";
  }
  try {
    const result = await api("/api/models/clone", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ model_id: sourceId, name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    closeCloneModelDialog();
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage(`已复制模型：${name}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/models/clone", "复制成功", `${sourceId} → ${name}`, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setCloneModelMessage(message.includes("已存在") ? `${message}，请输入新的模型名称。` : message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/clone", "复制失败", message, "error");
  } finally {
    if (confirm) {
      confirm.textContent = "复制";
      validateCloneModelName();
    }
  }
}

function blobFromBase64(dataBase64, contentType) {
  const binary = atob(dataBase64 || "");
  const chunkSize = 65536;
  const chunks = [];
  for (let offset = 0; offset < binary.length; offset += chunkSize) {
    const slice = binary.slice(offset, offset + chunkSize);
    const bytes = new Uint8Array(slice.length);
    for (let idx = 0; idx < slice.length; idx += 1) bytes[idx] = slice.charCodeAt(idx);
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

async function exportDefinitionsArchive(modelId = selectedManagementModelId(), actionButton = null) {
  const targetModelId = String(modelId || "").trim();
  if (!targetModelId) {
    setModelManagementMessage("请选择要导出的模型。", "error");
    return;
  }
  const button = actionButton;
  const originalText = button?.textContent || "";
  if (button) {
    button.disabled = true;
    button.textContent = "导出中";
  }
  try {
    const payload = await api("/api/export-definitions?format=json&model_id=" + encodeURIComponent(targetModelId), {
      modelScoped: false,
    });
    const filename = safeExportFilename(payload.filename || `${targetModelId}_definitions.zip`);
    downloadBlob(blobFromBase64(payload.data_base64, payload.content_type), filename);
    setModelManagementMessage(`已导出模型：${targetModelId}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/export-definitions", "导出成功", targetModelId, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    setModelManagementMessage(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/export-definitions", "导出失败", message, "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function deleteManagedModel(modelId = selectedManagementModelId()) {
  const target = modelById(modelId);
  const models = normalizeModels();
  if (!target) {
    setModelManagementMessage("请选择要删除的模型。", "error");
    return;
  }
  if (models.length <= 1) {
    setModelManagementMessage("至少需要保留一个模型。", "error");
    return;
  }
  if (!canEditManagedModel(target)) {
    setModelManagementMessage("模型正在接收或运行中，不能删除。", "error");
    return;
  }
  const modelName = target.name || target.id;
  if (!window.confirm(`确认删除模型“${modelName}”吗？此操作会删除本地模型文件夹和运行数据。`)) return;
  const deletedActiveModel = String(target.id || "") === String(state.activeModelId || "");
  setModelManagementMessage(`正在删除模型：${modelName}`);
  try {
    const result = await api("/api/models/delete", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ model_id: target.id }),
    });
    delete state.modelContexts[contextKey(target.id)];
    persistModelContextsToStorage();
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
    addRuntimeLog("模型管理", "学员台 /api/models/delete", "删除成功", modelName, "ok");
  } catch (error) {
    await loadModels();
    renderModelManagementList();
    const message = apiErrorText(error);
    setModelManagementMessage(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/delete", "删除失败", message, "error");
  }
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

function renderModelSelector() {
  const selector = $("modelSelector");
  const localModels = state.models.length ? state.models : [{ id: state.activeModelId || "", name: "默认模型" }];
  const hasActiveModel = localModels.some((model) => model.id === state.activeModelId);
  const externalModel = state.activeModelId && !hasActiveModel
    ? [{ id: state.activeModelId, name: state.teacherModelName || state.snapshot?.model?.name || state.activeModelId }]
    : [];
  const models = [...localModels, ...externalModel];
  let activeModelId = state.activeModelId || models[0]?.id || "";
  if (selector) {
    selector.innerHTML = models.map((model) => `
      <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
    `).join("");
    selector.value = activeModelId;
    selector.disabled = models.length <= 1;
    activeModelId = selector.value;
  }
  const active = models.find((model) => model.id === activeModelId) || models[0] || {};
  const activeModelName = $("activeModelName");
  if (activeModelName) {
    activeModelName.textContent = active.name || active.id || "默认模型";
  }
}

function setActiveModel(modelId, shouldRefresh = true) {
  persistActiveModelContext();
  const nextId = modelId || state.models[0]?.id || "";
  state.activeModelId = nextId;
  localStorage.setItem("polarTraineeModelId", nextId);
  restoreModelContext(nextId);
  pending.run_status.clear();
  pending.set_values.clear();
  if (!state.receiveMode) state.frozen = false;
  state.localDefinitionSnapshot = null;
  state.localDefinitionModelId = "";
  state.traceRunId = null;
  state.selectedMeasurementKey = "";
  state.selectedCommandTraceKey = "";
  state.selectedCommandTraceLabel = "";
  state.modelFilter = { dev_type: "all", dev_name: "" };
  state.activeModelParamTab = "";
  state.activeCurveDisplayKey = "wind_speed_mps";
  state.selectedCurveDisplayKeys = ["wind_speed_mps"];
  state.hiddenCurveDisplayKeys = [];
  state.curveDisplayCursor = { visible: false, x: 0, y: 0, index: 0 };
  state.curveDisplayLegendHitBoxes = [];
  state.lastCurveDisplayRenderKey = "";
  state.lastCurveDisplayTableKey = "";
  state.chartSeriesHidden = {};
  state.chartSeriesSelected = {};
  state.chartCursors = {};
  state.chartSeriesHitData = {};
  state.chartPlotInfo = {};
  state.measurementFilter = { dev_type: "all", dev_name: "" };
  state.controlFilter = { dev_type: "all", dev_name: "" };
  state.activeControlTab = "remote-control";
  state.deviceTreeSelectionAnchors = {};
  resetRenewableControlView(nextId);
  renderModelSelector();
  if ($("modelManagementDialog")?.open) renderModelManagementList();
  updatePendingCount();
  if (shouldRefresh) refresh();
}

async function loadModels() {
  try {
    const catalog = await api("/api/models", { modelScoped: false });
    state.models = Array.isArray(catalog.models) ? catalog.models : [];
    try {
      const receiveStates = await api("/api/trainee/receive-states", { modelScoped: false });
      mergeReceiveStatesFromBackend(receiveStates.items || {});
    } catch (_error) {
      // Older trainee services may not have receive-state persistence; local contexts still work.
    }
    const preferred = state.activeModelId || catalog.active_model_id || state.models[0]?.id || "";
    const exists = state.models.some((model) => model.id === preferred);
    setActiveModel(exists ? preferred : state.models[0]?.id || "", false);
    if ($("modelManagementDialog")?.open) renderModelManagementList();
  } catch (_error) {
    state.models = [];
    renderModelSelector();
    if ($("modelManagementDialog")?.open) renderModelManagementList();
  }
}

async function refresh() {
  await syncActiveReceiveStateBeforeRefresh();
  if (state.receiveMode) {
    await refreshFromTeacher(state.receiveEpoch);
    if (currentPageName() === "renewable") await refreshRenewableControlState({ preview: true });
    return;
  }
  if (state.frozen) {
    renderReceiveMode();
    if (currentPageName() === "renewable") await refreshRenewableControlState({ preview: true });
    return;
  }
  if (state.refreshRequestActive) return;
  state.refreshRequestActive = true;
  try {
    const page = currentPageName();
    let snapshot = mergeSnapshot(state.snapshot, await api(snapshotPollPath(page)));
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    let missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
    if (missingStaticKeys.length) {
      snapshot = mergeSnapshot(snapshot, await api(snapshotPollPath(page, missingStaticKeys)));
      snapshot = restoreStaticSnapshotCache(snapshot, page);
      missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
    }
    state.snapshot = snapshot;
    if (!missingStaticKeys.length) persistStaticSnapshotCache(state.snapshot, page);
    await refreshMeasurementDelta(false);
    $("connectionDot").className = "ok";
    $("connectionText").textContent = "在线";
    state.snapshotSource = "local";
    renderSnapshot(state.snapshot);
  } catch (_error) {
    $("connectionDot").className = "off";
    $("connectionText").textContent = "离线";
  } finally {
    state.refreshRequestActive = false;
    if (currentPageName() === "renewable") await refreshRenewableControlState({ preview: true });
  }
}

async function refreshFromTeacher(epoch = state.receiveEpoch) {
  if (state.receiveRequestActive) return;
  state.receiveRequestActive = true;
  try {
    const page = currentPageName();
    let snapshot = mergeSnapshot(state.snapshot, await teacherSnapshotApi(page));
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    let missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
    if (missingStaticKeys.length) {
      snapshot = mergeSnapshot(snapshot, await teacherSnapshotApi(page, missingStaticKeys));
      snapshot = restoreStaticSnapshotCache(snapshot, page);
      missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
    }
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    state.snapshot = snapshot;
    if (!missingStaticKeys.length) persistStaticSnapshotCache(state.snapshot, page);
    await refreshMeasurementDelta(false);
    acceptTeacherSnapshot(state.snapshot, epoch);
  } catch (_error) {
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    $("connectionDot").className = "off";
    $("connectionText").textContent = "正在重连";
    const shouldContinue = recordReceiveIssue(
      "实时交互",
      "模拟台 /api/snapshot",
      "通讯失败",
      [`数据接收失败：${apiErrorText(_error)}`, "将尝试自动重连模拟台交互链接"],
    );
    if (shouldContinue) await attemptTeacherReconnect(epoch);
  } finally {
    state.receiveRequestActive = false;
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  if (state.snapshotSource !== "teacher" && snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  if (state.snapshotSource === "teacher" && snapshot.model?.name) {
    state.teacherModelName = snapshot.model.name;
  }
  renderModelSelector();
  renderClock(snapshot.clock || {});
  const runId = Number(snapshot.clock?.run_id ?? 0);
  if (state.traceRunId !== null && runId !== state.traceRunId) {
    state.measurementTraceHistory = [];
    state.commandTraceHistory = [];
    state.selectedMeasurementKey = "";
  }
  state.traceRunId = runId;
  renderReceiveMode();
  appendMeasurementTrace(snapshot);
  appendCommandTrace(snapshot);
  syncCommandHistoryLogs(snapshot.commands?.history || []);
  updatePendingCount();
  renderActiveTraineePage(snapshot);
  persistActiveModelContext();
}

function renderReceiveMode(extraText = "") {
  const button = $("traineeRunToggle");
  const stateText = $("receiveStateText");
  const sourceText = $("teacherSourceText");
  const connectionDot = $("connectionDot");
  const connectionText = $("connectionText");
  if (button) {
    button.textContent = state.receiveMode ? "停止接收" : "启动接收";
    button.classList.toggle("is-running", state.receiveMode);
  }
  if (connectionDot && connectionText) {
    connectionDot.className = extraText ? "off" : state.receiveMode ? "ok" : state.frozen ? "" : "ok";
    connectionText.textContent = extraText || (state.receiveMode ? "接收中" : state.frozen ? "已冻结" : "在线");
  }
  if (stateText) {
    const label = state.receiveMode ? "运行接收" : state.frozen ? "已冻结" : "本地待命";
    stateText.textContent = extraText || label;
  }
  if (sourceText) {
    const receiveAddress = teacherReceiveAddress();
    const receiveAddressText = displayReceiveAddress(receiveAddress);
    sourceText.title = receiveAddress;
    sourceText.textContent = receiveAddressText || "--";
  }
}

function curveMinute(snapshot) {
  const curves = snapshot.curves || {};
  const clock = snapshot.clock || {};
  if (String(curves.mode || "").toLowerCase() === "year") {
    return Number(clock.absolute_minute ?? clock.minute ?? 0) || 0;
  }
  return Number(clock.minute ?? 0) || 0;
}

function interpolateCurve(points, minute, key, defaultValue = 0) {
  const pairs = (points || [])
    .map((point) => ({ minute: Number(point.minute), value: optionalNumber(point?.[key]) }))
    .filter((point) => Number.isFinite(point.minute) && Number.isFinite(point.value))
    .sort((left, right) => left.minute - right.minute);
  if (!pairs.length) return defaultValue;
  if (pairs.length === 1) return pairs[0].value;
  const target = Number(minute) || 0;
  let left = pairs[0];
  let right = pairs[pairs.length - 1];
  for (let idx = 0; idx < pairs.length - 1; idx += 1) {
    if (pairs[idx].minute <= target && target <= pairs[idx + 1].minute) {
      left = pairs[idx];
      right = pairs[idx + 1];
      break;
    }
  }
  if (target <= pairs[0].minute) return pairs[0].value;
  if (target >= pairs[pairs.length - 1].minute) return pairs[pairs.length - 1].value;
  const span = Math.max(1e-9, right.minute - left.minute);
  return left.value + ((target - left.minute) / span) * (right.value - left.value);
}

function renderTeacherWeather(snapshot) {
  const valuesNow = currentWeatherLoad(snapshot);
  const values = {
    teacherWind: Number.isFinite(valuesNow.windSpeed) ? `${formatNumber(valuesNow.windSpeed)} m/s` : "--",
    teacherSolar: Number.isFinite(valuesNow.solarIrradiance) ? `${formatNumber(valuesNow.solarIrradiance)} W/m2` : "--",
    teacherTemp: `${formatNumber(valuesNow.airTemp)} ℃`,
    teacherLoad: `${formatNumber(valuesNow.loadKw)} kW`,
    teacherWeatherTime: snapshot.clock?.time || "--",
  };
  Object.entries(values).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
}

function toNumber(value, defaultValue = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : defaultValue;
}

function optionalNumber(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function commandNumber(value) {
  const number = Math.abs(value) < 0.0005 ? 0 : value;
  return Number(number.toFixed(3));
}

function weatherMeasurementState(snapshot, measType) {
  const measurements = snapshot.measurements || {};
  for (const channel of [measurements.scada || [], measurements.real || []]) {
    const row = channel.find((item) => (
      item.dev_type === "Environment"
      && item.dev_name === "weather"
      && String(item.meas_type || "").toUpperCase() === measType
    ));
    if (!row) continue;
    const valid = Number(row.valid ?? 1) === 1;
    return { present: true, valid, value: valid ? optionalNumber(row.value) : null };
  }
  return { present: false, valid: false, value: null };
}

function currentWeatherLoad(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const boundary = snapshot.curve_boundary || {};
  const minute = curveMinute(snapshot);
  const weather = curves.weather || [];
  const loads = curves.loads || {};
  const boundaryPoint = boundary.point || {};
  let loadTotal = Object.values(loads).reduce((total, points) => (
    total + interpolateCurve(points, minute, "p_kw", 0)
  ), 0);
  if (!Object.keys(loads).length && Number.isFinite(Number(boundary.load_total))) {
    loadTotal = Number(boundary.load_total);
  }
  if (!Number.isFinite(loadTotal) || loadTotal <= 0) {
    loadTotal = estimateLoadFromDevices(snapshot.devices || []);
  }
  const windMeasurement = weatherMeasurementState(snapshot, "WIND_SPEED");
  const solarMeasurement = weatherMeasurementState(snapshot, "SOLAR_IRRADIANCE");
  const windSpeed = windMeasurement.present
    ? windMeasurement.value
    : weather.length
      ? interpolateCurve(weather, minute, "wind_speed_mps", null)
      : optionalNumber(boundaryPoint.wind_speed_mps);
  const solarIrradiance = solarMeasurement.present
    ? solarMeasurement.value
    : weather.length
      ? interpolateCurve(weather, minute, "solar_irradiance_w_m2", null)
      : optionalNumber(boundaryPoint.solar_irradiance_w_m2);
  return {
    minute: Number(boundary.target_minute ?? minute) || minute,
    windSpeed,
    windSpeedKnown: Number.isFinite(windSpeed),
    solarIrradiance,
    solarIrradianceKnown: Number.isFinite(solarIrradiance),
    airTemp: weather.length ? interpolateCurve(weather, minute, "air_temp_c", 25) : Number(boundaryPoint.air_temp_c ?? 25),
    loadKw: loadTotal,
  };
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
  const liveSoc = averageStorageSocRatio(snapshot);
  const logSoc = storageSocPercentFromText(text);
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
    soc: structured.soc
      ?? (Number.isFinite(liveSoc)
        ? liveSoc * 100
        : Number.isFinite(logSoc)
          ? logSoc
          : storageSocPercentFromText(controlText)),
    generation: structured.generation ?? matchedNumber(text, /电源发电总功率\s*([-+\d.]+)/),
    consumption: structured.consumption ?? matchedNumber(text, /用电及充电总功率\s*([-+\d.]+)/),
    balance: structured.balance ?? matchedNumber(text, /功率差额\s*([-+\d.]+)/),
  };
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

function overviewClamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
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

function setOptionalText(id, value) {
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
  if (container.hasAttribute("data-vertical-split-min-bottom")) {
    const bottomPriorityRatio = clamp(maxRatio, 8, 92);
    return { min: bottomPriorityRatio, max: bottomPriorityRatio };
  }
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
    if (splitId === "trainee-curves") drawCurveDisplay(state.snapshot || {});
    if (splitId === "trainee-measurements") drawMeasurementTraceChart();
    if (splitId === "trainee-commands") drawCommandTraceChart();
    if (splitId === "trainee-renewable" && state.renewableControl.detailTab === "trend") drawRenewableTrendChart();
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

function overviewClockText(snapshot) {
  const clock = snapshot.clock || {};
  const timeText = clock.time || "--";
  if (curveDisplayMode(snapshot) !== "year") return timeText;
  const dayIndex = Math.floor((Number(clock.absolute_minute ?? clock.minute ?? 0) || 0) / 1440) + 1;
  return `第${dayIndex}天 ${timeText}`;
}

function renderTraineeOverviewEvents() {
  const container = $("traineeOverviewEvents");
  if (!container) return;
  const logs = state.runtimeLogs.slice(0, 8);
  setOverviewText("overviewEventCount", `${logs.length} 条`);
  if (logs.length) {
    container.innerHTML = logs.map((item) => `
      <div class="overview-event-item">
        <time>${escapeHtml(item.wall_time || "--")}</time>
        <strong>${escapeHtml(item.type || "运行")}</strong>
        <span title="${escapeHtml(runtimeLogDetailText(item.detail))}">${escapeHtml(item.result || runtimeLogDetailText(item.detail) || "完成")}</span>
      </div>
    `).join("");
    return;
  }
  container.innerHTML = '<div class="overview-event-item"><time>--</time><strong>系统</strong><span>等待接收教员台数据</span></div>';
}

function renderTraineeOverviewDashboard(snapshot) {
  const clock = snapshot.clock || {};
  const measurements = measurementDisplayRows(snapshot);
  const validCount = measurements.filter((item) => Number(item.valid) === 1).length;
  const totalMeasurements = measurements.length;
  const weather = currentWeatherLoad(snapshot);
  const power = parsePowerFlowOverview(snapshot);
  const receiveDot = $("overviewReceiveDot");
  if (receiveDot) {
    receiveDot.classList.toggle("is-running", state.receiveMode);
    receiveDot.classList.toggle("is-paused", state.frozen && !state.receiveMode);
  }
  setOverviewText("overviewMode", curveDisplayMode(snapshot) === "year" ? "年仿真" : "日仿真");
  setOverviewText("overviewStep", `${formatOverviewNumber(clock.step_minutes || 1)} min`);
  setOverviewText("measureCount", `${totalMeasurements} 点`);
  setOverviewText("validCount", `${validCount} 可用`);

  setOverviewText("teacherWind", Number.isFinite(weather.windSpeed) ? `${formatOverviewNumber(weather.windSpeed)} m/s` : "--");
  setOverviewText("teacherSolar", Number.isFinite(weather.solarIrradiance) ? `${formatOverviewNumber(weather.solarIrradiance)} W/m²` : "--");
  setOverviewText("teacherTemp", `${formatOverviewNumber(weather.airTemp)} ℃`);
  setOverviewText("teacherLoad", overviewPowerText(weather.loadKw));
  setOverviewText("teacherWeatherTime", overviewClockText(snapshot));

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
  setOverviewText("overviewFlowWindMeta", Number.isFinite(weather.windSpeed) ? `风速 ${formatOverviewNumber(weather.windSpeed)} m/s` : "风速 未知");
  setOverviewText("overviewFlowSolarPower", overviewPowerText(power.solar));
  setOverviewText("overviewFlowSolarMeta", Number.isFinite(weather.solarIrradiance) ? `辐照 ${formatOverviewNumber(weather.solarIrradiance)} W/m²` : "辐照 未知");
  setOverviewText("overviewFlowDieselPower", overviewPowerText(power.diesel));
  setOverviewText("overviewFlowStoragePower", overviewPowerText(storagePower));
  setOverviewText("overviewFlowStorageDirection", storagePower === null ? "待接收" : storagePower > 0 ? "放电" : storagePower < 0 ? "充电" : "静置");
  setOverviewText("overviewFlowSoc", Number.isFinite(power.soc) ? `${formatOverviewNumber(power.soc)}%` : "--");
  setOverviewText("overviewFlowLoadPower", overviewPowerText(power.load));
  setOverviewText("overviewFlowLoadMeta", `需求 ${overviewPowerText(weather.loadKw)}`);
  const greenPowerShare = Number.isFinite(power.diesel) && Number.isFinite(power.load) && Math.abs(power.load) > 1e-9
    ? (1.0 - power.diesel / power.load) * 100.0
    : null;
  const greenPower = Number.isFinite(power.greenPower) ? -power.greenPower : null;
  setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderEnergyFlowVisuals(power, storagePower, greenPowerShare);
  renderTraineeOverviewEvents();
}

function renderActiveTraineePage(snapshot = state.snapshot || {}, force = false) {
  const activePage = currentPageName();
  if (activePage === "overview") {
    renderTeacherWeather(snapshot);
    renderTraineeOverviewDashboard(snapshot);
    initOverviewBottomSplitter();
    initOverviewBottomColumnSplitter();
    return;
  }
  if (activePage === "model") {
    renderTraineeModelPage(snapshot);
    return;
  }
  if (activePage === "diagram") {
    renderModelDiagramPage(snapshot);
    return;
  }
  if (activePage === "curves") {
    renderCurveDisplay(snapshot, force);
    return;
  }
  if (activePage === "measurements") {
    renderMeasurements(snapshot);
    return;
  }
  if (activePage === "commands") {
    renderCombinedControlPage();
    return;
  }
  if (activePage === "renewable") {
    renderRenewableControl(snapshot);
    return;
  }
  if (activePage === "history") {
    renderHistory();
  }
}

function curveDisplayMode(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const boundary = snapshot.curve_boundary || {};
  const rawMode = String(curves.mode || boundary.mode || "").toLowerCase();
  if (CURVE_DISPLAY_MODES[rawMode]) return rawMode;
  const pointCount = Number(curves.point_count || curves.weather?.length || boundary.point_count || 0);
  return pointCount > 2000 ? "year" : "day";
}

function curveDisplayConfig(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  const defaults = CURVE_DISPLAY_MODES[mode];
  const curves = snapshot.curves || {};
  const boundary = snapshot.curve_boundary || {};
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  const maxLoadCount = Object.values(loads).reduce((maxCount, points) => (
    Math.max(maxCount, Array.isArray(points) ? points.length : 0)
  ), 0);
  const pointCount = Math.max(
    1,
    Number(curves.point_count || 0) || Math.max(Array.isArray(curves.weather) ? curves.weather.length : 0, maxLoadCount, Number(boundary.point_count) || 0, defaults.pointCount),
  );
  const stepMinutes = Math.max(1, Number(curves.time_step_minutes || boundary.time_step_minutes || defaults.stepMinutes) || defaults.stepMinutes);
  return { ...defaults, pointCount, stepMinutes, durationMinutes: pointCount * stepMinutes };
}

function curveDisplayPointMinute(index, snapshot = state.snapshot || {}) {
  return index * curveDisplayConfig(snapshot).stepMinutes;
}

function curveDisplayLoadKey(loadName) {
  return `load:${loadName || "load"}`;
}

function curveDisplayLoadName(key) {
  return String(key || "").replace(/^load:/, "") || "load";
}

function curveDisplayLoads(snapshot = state.snapshot || {}) {
  const names = new Set(Object.keys(snapshot.curves?.loads || {}));
  (snapshot.devices || []).forEach((dev) => {
    if (["ACLoad", "DCLoad"].includes(deviceType(dev)) && deviceName(dev)) {
      names.add(deviceName(dev));
    }
  });
  return Array.from(names).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}

function curveDisplayLoadKeys(snapshot = state.snapshot || {}) {
  return curveDisplayLoads(snapshot).map(curveDisplayLoadKey);
}

function curveDisplayAllKeys(snapshot = state.snapshot || {}) {
  return [...CURVE_DISPLAY_ENV_KEYS, ...curveDisplayLoadKeys(snapshot)];
}

function curveDisplayRawPoints(key, snapshot = state.snapshot || {}) {
  if (String(key).startsWith("load:")) {
    const loadName = curveDisplayLoadName(key);
    const points = snapshot.curves?.loads?.[loadName];
    return Array.isArray(points) ? points : [];
  }
  return Array.isArray(snapshot.curves?.weather) ? snapshot.curves.weather : [];
}

function curveDisplayPointValue(point, key) {
  if (!point) return null;
  if (String(key).startsWith("load:")) {
    return Number(point.p_kw ?? point.value ?? point.load_kw);
  }
  return Number(point[key]);
}

function curveDisplayMetaForKey(key, snapshot = state.snapshot || {}) {
  const meta = CURVE_DISPLAY_META.find((item) => item.key === key);
  if (meta) return meta;
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const loadIndex = Math.max(0, loadKeys.indexOf(key));
  const values = curveDisplayRawPoints(key, snapshot)
    .map((point) => curveDisplayPointValue(point, key))
    .filter((value) => Number.isFinite(value));
  const dynamicMax = values.length ? Math.max(...values) * 1.12 : CURVE_DISPLAY_LOAD_META.max;
  return {
    ...CURVE_DISPLAY_LOAD_META,
    key,
    label: curveDisplayLoadName(key),
    color: CURVE_DISPLAY_LOAD_COLORS[loadIndex % CURVE_DISPLAY_LOAD_COLORS.length],
    max: Math.max(CURVE_DISPLAY_LOAD_META.max, dynamicMax, 1),
  };
}

function curveDisplayRoundValue(key, value, snapshot = state.snapshot || {}) {
  const meta = curveDisplayMetaForKey(key, snapshot);
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Number(numeric.toFixed(meta.digits));
}

function interpolateCurveDisplay(points, minute, key, defaultValue = 0) {
  const pairs = (points || [])
    .map((point, index) => ({
      minute: Number(point.minute ?? index),
      value: curveDisplayPointValue(point, key),
    }))
    .filter((point) => Number.isFinite(point.minute) && Number.isFinite(point.value))
    .sort((left, right) => left.minute - right.minute);
  if (!pairs.length) return defaultValue;
  if (pairs.length === 1) return pairs[0].value;
  const target = Number(minute) || 0;
  if (target <= pairs[0].minute) return pairs[0].value;
  if (target >= pairs[pairs.length - 1].minute) return pairs[pairs.length - 1].value;
  for (let idx = 0; idx < pairs.length - 1; idx += 1) {
    const left = pairs[idx];
    const right = pairs[idx + 1];
    if (left.minute <= target && target <= right.minute) {
      const span = Math.max(1e-9, right.minute - left.minute);
      return left.value + ((target - left.minute) / span) * (right.value - left.value);
    }
  }
  return defaultValue;
}

function curveDisplaySeries(key, snapshot = state.snapshot || {}) {
  const config = curveDisplayConfig(snapshot);
  const points = curveDisplayRawPoints(key, snapshot);
  const meta = curveDisplayMetaForKey(key, snapshot);
  if (points.length === config.pointCount) {
    return points.map((point) => curveDisplayRoundValue(key, curveDisplayPointValue(point, key) ?? meta.min, snapshot));
  }
  return Array.from({ length: config.pointCount }, (_unused, index) => (
    curveDisplayRoundValue(key, interpolateCurveDisplay(points, curveDisplayPointMinute(index, snapshot), key, meta.min), snapshot)
  ));
}

function selectedCurveDisplayKeys(snapshot = state.snapshot || {}) {
  const available = new Set(curveDisplayAllKeys(snapshot));
  const selected = Array.from(new Set(state.selectedCurveDisplayKeys || []))
    .filter((key) => available.has(key));
  if (!selected.length && available.has(state.activeCurveDisplayKey)) selected.push(state.activeCurveDisplayKey);
  if (!selected.length) selected.push("wind_speed_mps");
  state.selectedCurveDisplayKeys = selected;
  if (!selected.includes(state.activeCurveDisplayKey)) {
    state.activeCurveDisplayKey = selected[selected.length - 1] || "wind_speed_mps";
  }
  return selected;
}

function curveDisplayHiddenSet() {
  return new Set(state.hiddenCurveDisplayKeys || []);
}

function isCurveDisplaySeriesHidden(key) {
  return curveDisplayHiddenSet().has(key);
}

function visibleCurveDisplayKeys(snapshot = state.snapshot || {}) {
  return selectedCurveDisplayKeys(snapshot).filter((key) => !isCurveDisplaySeriesHidden(key));
}

function visibleCurveDisplayMetas(snapshot = state.snapshot || {}) {
  return visibleCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
}

function toggleCurveDisplaySeriesVisibility(key, shouldRender = true) {
  if (!key) return;
  const hidden = curveDisplayHiddenSet();
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  state.hiddenCurveDisplayKeys = Array.from(hidden);
  state.activeCurveDisplayKey = key;
  if (shouldRender) {
    renderCurveDisplayTree(state.snapshot || {});
    drawCurveDisplay(state.snapshot || {});
  }
}

function curveDisplayFamilyKeys(family, snapshot = state.snapshot || {}) {
  if (family === "environment") return [...CURVE_DISPLAY_ENV_KEYS];
  if (family === "load") return curveDisplayLoadKeys(snapshot);
  return [];
}

function setCurveDisplaySelection(keys, activeKey = keys?.[keys.length - 1], shouldRender = true) {
  const available = new Set(curveDisplayAllKeys(state.snapshot || {}));
  const selected = Array.from(new Set(keys || [])).filter((key) => available.has(key));
  if (!selected.length) selected.push("wind_speed_mps");
  state.selectedCurveDisplayKeys = selected;
  state.activeCurveDisplayKey = selected.includes(activeKey) ? activeKey : selected[selected.length - 1] || "wind_speed_mps";
  if (selected.length === 1) {
    const hidden = curveDisplayHiddenSet();
    hidden.delete(selected[0]);
    state.hiddenCurveDisplayKeys = Array.from(hidden);
  }
  state.lastCurveDisplayTableKey = "";
  if (shouldRender) renderCurveDisplay(state.snapshot || {}, true);
}

function selectCurveDisplayButton(button) {
  if (!button) return;
  const keys = button.dataset.curveDisplayFamily
    ? curveDisplayFamilyKeys(button.dataset.curveDisplayFamily, state.snapshot || {})
    : button.dataset.curveDisplayKey ? [button.dataset.curveDisplayKey] : [];
  setCurveDisplaySelection(keys, button.dataset.curveDisplayKey || keys[0], true);
}

function curveDisplaySelectedLabel(snapshot = state.snapshot || {}) {
  const selected = selectedCurveDisplayKeys(snapshot);
  return selected.length <= 1 ? curveDisplayMetaForKey(selected[0], snapshot).label : `已选${selected.length}条`;
}

function renderCurveDisplayTree(snapshot = state.snapshot || {}) {
  const container = $("curveDisplayTree");
  if (!container) return;
  const selected = selectedCurveDisplayKeys(snapshot);
  const selectedSet = new Set(selected);
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const envSelected = CURVE_DISPLAY_ENV_KEYS.every((key) => selectedSet.has(key))
    && selected.every((key) => CURVE_DISPLAY_ENV_KEYS.includes(key));
  const loadSelected = loadKeys.length && loadKeys.every((key) => selectedSet.has(key))
    && selected.every((key) => loadKeys.includes(key));
  const envPartial = CURVE_DISPLAY_ENV_KEYS.some((key) => selectedSet.has(key));
  const loadPartial = loadKeys.some((key) => selectedSet.has(key));
  $("curveDisplayTreeSummary").textContent = `${CURVE_DISPLAY_ENV_KEYS.length + loadKeys.length} 条`;
  container.innerHTML = `
    <div class="tree-group">
      <button
        type="button"
        class="tree-node tree-type ${envSelected ? "is-active" : envPartial ? "is-parent-active" : ""}"
        data-curve-display-tree-type="environment"
        data-curve-display-family="environment"
      >
        <span>环境曲线</span>
        <strong>${CURVE_DISPLAY_ENV_KEYS.length}</strong>
      </button>
      <div class="tree-children">
        ${CURVE_DISPLAY_ENV_KEYS.map((key) => {
          const meta = curveDisplayMetaForKey(key, snapshot);
          const shortLabel = key === "wind_speed_mps" ? "风" : key === "solar_irradiance_w_m2" ? "光" : "温";
          return `
            <button
              type="button"
              class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""} ${isCurveDisplaySeriesHidden(key) ? "is-hidden-series" : ""}"
              data-curve-display-tree-type="environment"
              data-curve-display-key="${escapeHtml(key)}"
            >
              <span>${shortLabel}</span>
              <small>${escapeHtml(meta.unit)}</small>
            </button>`;
        }).join("")}
      </div>
    </div>
    <div class="tree-group">
      <button
        type="button"
        class="tree-node tree-type ${loadSelected ? "is-active" : loadPartial ? "is-parent-active" : ""}"
        data-curve-display-tree-type="load"
        data-curve-display-family="load"
      >
        <span>负荷曲线</span>
        <strong>${loadKeys.length}</strong>
      </button>
      <div class="tree-children">
        ${loadKeys.map((key) => `
          <button
            type="button"
            class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""} ${isCurveDisplaySeriesHidden(key) ? "is-hidden-series" : ""}"
            data-curve-display-tree-type="load"
            data-curve-display-key="${escapeHtml(key)}"
          >
            <span>${escapeHtml(curveDisplayLoadName(key))}</span>
            <small>kW</small>
          </button>
        `).join("") || '<div class="empty-state compact">暂无负荷曲线</div>'}
      </div>
    </div>`;
}

function renderCurveDisplayModeControls(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  document.querySelectorAll("[data-curve-display-mode]").forEach((button) => {
    const active = button.dataset.curveDisplayMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = true;
  });
}

function formatCurveDisplayTableTime(minute, snapshot = state.snapshot || {}) {
  if (curveDisplayMode(snapshot) === "year") {
    const dayOfYear = Math.floor(minute / 1440);
    const hour = Math.floor((minute % 1440) / 60);
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
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function renderCurveDisplayLabels(snapshot = state.snapshot || {}) {
  const config = curveDisplayConfig(snapshot);
  const pointCount = $("curveDisplayPointCount");
  const status = $("curveDisplayStatus");
  const activeLabel = $("curveDisplayActiveLabel");
  const tableTitle = $("curveDisplayTableTitle");
  const tableSummary = $("curveDisplayTableSummary");
  if (pointCount) pointCount.textContent = `${config.pointCount}点`;
  if (status) status.textContent = `${config.label} · 只读`;
  if (activeLabel) activeLabel.textContent = curveDisplaySelectedLabel(snapshot);
  if (tableTitle) tableTitle.textContent = config.tableTitle;
  if (tableSummary) tableSummary.textContent = config.tableSummary;
}

function resizeCurveDisplayCanvas() {
  const canvas = $("curveDisplayChart");
  if (!canvas) return false;
  const { width, height } = canvasRenderedSize(canvas, 900, 260);
  if (canvas.width === width && canvas.height === height) return false;
  canvas.width = width;
  canvas.height = height;
  return true;
}

function curveDisplayPlot(canvas) {
  if (canvas.width < 640) return { left: 34, right: 12, top: 58, bottom: 30 };
  return CURVE_DISPLAY_PLOT;
}

function curveDisplayValueToY(value, meta, canvas) {
  const plot = curveDisplayPlot(canvas);
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const span = Math.max(1e-9, meta.max - meta.min);
  const ratio = (clamp(value, meta.min, meta.max) - meta.min) / span;
  return bottom - ratio * (bottom - top);
}

function drawCurveDisplayXAxis(ctx, canvas, plot, snapshot = state.snapshot || {}) {
  const width = canvas.width;
  const height = canvas.height;
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (curveDisplayMode(snapshot) === "year") {
    const monthStarts = [["01月", 0], ["02月", 31], ["03月", 59], ["04月", 90], ["05月", 120], ["06月", 151], ["07月", 181], ["08月", 212], ["09月", 243], ["10月", 273], ["11月", 304], ["12月", 334]];
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

function curveDisplayPointIndexFromX(x, canvas, snapshot = state.snapshot || {}) {
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const pointCount = curveDisplayConfig(snapshot).pointCount;
  return clamp(Math.round(((x - left) / Math.max(1, right - left)) * (pointCount - 1)), 0, pointCount - 1);
}

function curveDisplayXFromPointIndex(index, canvas, snapshot = state.snapshot || {}) {
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const pointCount = curveDisplayConfig(snapshot).pointCount;
  return left + (clamp(index, 0, pointCount - 1) / Math.max(1, pointCount - 1)) * (right - left);
}

function drawCurveDisplayCursor(ctx, canvas, plot, metas, seriesByKey, snapshot = state.snapshot || {}) {
  const cursor = state.curveDisplayCursor;
  if (!cursor.visible || !metas.length) return;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const index = clamp(cursor.index, 0, curveDisplayConfig(snapshot).pointCount - 1);
  const x = curveDisplayXFromPointIndex(index, canvas, snapshot);
  const y = clamp(cursor.y, top, bottom);
  const tooltipMetas = metas.slice(0, 6);
  const timeLabel = formatCurveDisplayTableTime(curveDisplayPointMinute(index, snapshot), snapshot);

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
    const values = seriesByKey.get(meta.key) || [];
    if (!values.length) return;
    const markerY = curveDisplayValueToY(values[index], meta, canvas);
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, markerY, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = "12px Microsoft YaHei, Arial";
  const lines = [
    `时刻: ${timeLabel}`,
    `点号: ${index + 1}`,
    ...tooltipMetas.map((meta) => `${meta.label}: ${formatNumber(seriesByKey.get(meta.key)?.[index])} ${meta.unit}`),
    metas.length > tooltipMetas.length ? `另有 ${metas.length - tooltipMetas.length} 条曲线` : "",
  ].filter(Boolean);
  const tooltipWidth = Math.max(158, ...lines.map((line) => ctx.measureText(line).width + 24));
  const tooltipHeight = 14 + lines.length * 18;
  let tooltipX = x + 14;
  let tooltipY = y + 14;
  if (tooltipX + tooltipWidth > right - 6) tooltipX = x - tooltipWidth - 14;
  if (tooltipY + tooltipHeight > bottom - 6) tooltipY = y - tooltipHeight - 14;
  tooltipX = clamp(tooltipX, left + 6, right - tooltipWidth - 6);
  tooltipY = clamp(tooltipY, top + 6, bottom - tooltipHeight - 6);
  ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
  ctx.strokeStyle = "rgba(171, 190, 198, 0.9)";
  ctx.beginPath();
  ctx.roundRect(tooltipX, tooltipY, tooltipWidth, tooltipHeight, 8);
  ctx.fill();
  ctx.stroke();
  lines.forEach((line, lineIndex) => {
    ctx.fillStyle = lineIndex < 2 ? "#1f3037" : "#314850";
    ctx.fillText(line, tooltipX + 10, tooltipY + 18 + lineIndex * 18);
  });
  ctx.restore();
}

function drawCurveDisplay(snapshot = state.snapshot || {}) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return;
  resizeCurveDisplayCanvas();
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const allMetas = selectedCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
  const metas = allMetas.filter((meta) => !isCurveDisplaySeriesHidden(meta.key));
  const seriesByKey = new Map(allMetas.map((meta) => [meta.key, curveDisplaySeries(meta.key, snapshot)]));
  const legendColumns = width < 560 ? 2 : Math.max(1, allMetas.length);
  const legendColumnWidth = (right - left) / legendColumns;
  state.curveDisplayLegendHitBoxes = [];
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  for (let i = 0; i <= 5; i += 1) {
    const y = top + i * ((bottom - top) / 5);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  drawCurveDisplayXAxis(ctx, canvas, plot, snapshot);
  const activeKey = isCurveDisplaySeriesHidden(state.activeCurveDisplayKey) ? "" : state.activeCurveDisplayKey;
  metas.forEach((meta) => {
    const values = seriesByKey.get(meta.key) || [];
    const sampledPoints = sampleCurvePointsForCanvas(values, right - left, 1.4);
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = activeKey === meta.key ? 3.4 : 2;
    ctx.beginPath();
    sampledPoints.forEach((point, index) => {
      const x = left + (point.index / Math.max(1, values.length - 1)) * (right - left);
      const y = curveDisplayValueToY(point.value, meta, canvas);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (values.length) ctx.lineTo(right, curveDisplayValueToY(values[values.length - 1], meta, canvas));
    ctx.stroke();
  });
  if (!metas.length && allMetas.length) {
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "center";
    ctx.fillText("所有曲线已隐藏", (left + right) / 2, (top + bottom) / 2);
    ctx.textAlign = "left";
  }
  allMetas.forEach((meta, metaIndex) => {
    const legendX = left + (metaIndex % legendColumns) * legendColumnWidth;
    const legendY = 20 + Math.floor(metaIndex / legendColumns) * 16;
    const hidden = isCurveDisplaySeriesHidden(meta.key);
    const labelText = `${meta.label} (${meta.unit})${hidden ? " 隐藏" : ""}`;
    state.curveDisplayLegendHitBoxes.push({
      key: meta.key,
      x: legendX - 6,
      y: legendY - 9,
      width: Math.min(legendColumnWidth - 8, ctx.measureText(labelText).width + 42),
      height: 16,
    });
    ctx.fillStyle = hidden ? "#9aa9af" : meta.color;
    ctx.fillRect(legendX, legendY, 18, 3);
    ctx.fillStyle = hidden ? "#9aa9af" : activeKey === meta.key ? "#1f3037" : "#63717a";
    ctx.fillText(labelText, legendX + 26, legendY + 4);
  });
  drawCurveDisplayCursor(ctx, canvas, plot, metas, seriesByKey, snapshot);
}

function renderCurveDisplayTable(snapshot = state.snapshot || {}, force = false) {
  const container = $("curveDisplayTable");
  if (!container) return;
  const config = curveDisplayConfig(snapshot);
  const metas = selectedCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
  const seriesByKey = new Map(metas.map((meta) => [meta.key, curveDisplaySeries(meta.key, snapshot)]));
  const tableKey = `curveDisplay:${state.activeModelId}:${config.key}`;
  const signature = JSON.stringify({
    model: state.activeModelId,
    mode: config.key,
    points: config.pointCount,
    selected: metas.map((meta) => meta.key),
    staticMeta: snapshot.static_meta?.curves || null,
    source: `${snapshot.curves?.weather?.length || 0}|${Object.values(snapshot.curves?.loads || {}).map((points) => points?.length || 0).join(",")}`,
  });
  if (!force && signature === state.lastCurveDisplayTableKey) return;
  state.lastCurveDisplayTableKey = signature;
  const rowIndexes = Array.from({ length: config.pointCount }, (_unused, index) => index);
  const virtualRows = virtualTableWindow(tableKey, rowIndexes);
  const columnCount = metas.length + 1;
  container.setAttribute("data-virtual-table", tableKey);
  container.innerHTML = `
    <table class="curve-table curve-display-table">
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
            <td>${formatCurveDisplayTableTime(curveDisplayPointMinute(index, snapshot), snapshot)}</td>
            ${metas.map((meta) => `<td class="numeric-cell">${formatNumber(seriesByKey.get(meta.key)?.[index])}</td>`).join("")}
          </tr>
        `).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
      </tbody>
    </table>`;
  restoreVirtualTableScroll(container, tableKey);
}

function renderCurveDisplay(snapshot = state.snapshot || {}, forceTable = false) {
  const container = $("curveDisplayTree");
  if (!container) return;
  if (!snapshot?.curves) {
    container.innerHTML = '<div class="empty-state">暂无曲线数据</div>';
    $("curveDisplayTable").removeAttribute("data-virtual-table");
    $("curveDisplayTable").innerHTML = '<div class="empty-state">暂无曲线数据</div>';
    return;
  }
  const renderKey = JSON.stringify({
    model: state.activeModelId,
    mode: curveDisplayMode(snapshot),
    points: curveDisplayConfig(snapshot).pointCount,
    selected: selectedCurveDisplayKeys(snapshot),
    hidden: [...(state.hiddenCurveDisplayKeys || [])].sort(),
    staticMeta: snapshot.static_meta?.curves || null,
  });
  if (!forceTable && renderKey === state.lastCurveDisplayRenderKey) return;
  state.lastCurveDisplayRenderKey = renderKey;
  renderCurveDisplayTree(snapshot);
  renderCurveDisplayModeControls(snapshot);
  renderCurveDisplayLabels(snapshot);
  drawCurveDisplay(snapshot);
  renderCurveDisplayTable(snapshot);
}

function pointerPositionOnCurveDisplayCanvas(event) {
  const canvas = $("curveDisplayChart");
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function curveDisplayLegendKeyAtPointer(event) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const hit = (state.curveDisplayLegendHitBoxes || []).find((box) => (
    pos.x >= box.x && pos.x <= box.x + box.width && pos.y >= box.y && pos.y <= box.y + box.height
  ));
  return hit?.key || "";
}

function curveDisplayKeyAtPointer(event) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) return "";
  const index = curveDisplayPointIndexFromX(pos.x, canvas, state.snapshot || {});
  const tolerance = canvas.width < 640 ? 18 : 14;
  let bestKey = "";
  let bestDistance = Infinity;
  visibleCurveDisplayMetas(state.snapshot || {}).forEach((meta) => {
    const values = curveDisplaySeries(meta.key, state.snapshot || {});
    if (!values.length) return;
    const distance = Math.abs(curveDisplayValueToY(values[index], meta, canvas) - pos.y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestKey = meta.key;
    }
  });
  return bestDistance <= tolerance ? bestKey : "";
}

function setCurveDisplayCursorFromEvent(event, shouldDraw = true) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return;
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) {
    state.curveDisplayCursor = { visible: false, x: pos.x, y: pos.y, index: state.curveDisplayCursor.index || 0 };
  } else {
    state.curveDisplayCursor = {
      visible: true,
      x: clamp(pos.x, left, right),
      y: clamp(pos.y, top, bottom),
      index: curveDisplayPointIndexFromX(pos.x, canvas, state.snapshot || {}),
    };
  }
  if (shouldDraw) drawCurveDisplay(state.snapshot || {});
}

function hideCurveDisplayCursor() {
  if (!state.curveDisplayCursor.visible) return;
  state.curveDisplayCursor.visible = false;
  drawCurveDisplay(state.snapshot || {});
}

function estimateLoadFromDevices(devices) {
  return (devices || []).reduce((total, dev) => {
    if (!["ACLoad", "DCLoad"].includes(deviceType(dev)) || !isDeviceOnline(dev)) return total;
    const raw = dev.raw || {};
    const values = dev.set_values || {};
    return total + toNumber(values.p_set ?? raw.pv0 ?? raw.p_set ?? 0, 0);
  }, 0);
}

function isDeviceOnline(dev) {
  if (!dev) return false;
  return Number(dev.run_stat ?? 1) === 1 && Number(dev.status ?? 1) !== 0;
}

function parameterRows(snapshot, blockName) {
  const params = snapshot.device_parameters || {};
  const rows = params[blockName] || params[blockName.toLowerCase()] || params[blockName.toUpperCase()] || [];
  return Array.isArray(rows) ? rows : [];
}

function parameterName(row) {
  return String(row?.name || row?.dev_name || "");
}

function parameterNumber(value, defaultValue = null) {
  if (value === null || value === undefined || String(value).trim() === "") return defaultValue;
  const direct = Number(value);
  if (Number.isFinite(direct)) return direct;
  const match = String(value).replace(/,/g, "").match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/i);
  if (!match) return defaultValue;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : defaultValue;
}

function liveStorageSocRatio(value, defaultValue) {
  const number = parameterNumber(value, null);
  if (number === null) return defaultValue;
  return typeof value === "string" && value.includes("%") ? number / 100 : number;
}

function indexedDevice(snapshot, devType, index) {
  const target = String(index ?? "").trim();
  if (!target) return null;
  return (snapshot.devices || []).find((dev) => (
    deviceType(dev) === devType && String(deviceIndex(dev)).trim() === target
  )) || null;
}

function measurementValuesByDevice(snapshot, measurementTypes) {
  const values = new Map();
  const measurements = snapshot.measurements || {};
  const channels = [measurements.scada || [], measurements.real || []];
  (measurementTypes || []).map((type) => String(type || "").toUpperCase()).forEach((measurementType) => {
    channels.forEach((channel) => {
      channel.forEach((row) => {
        if (String(row.meas_type || "").toUpperCase() !== measurementType || Number(row.valid ?? 1) !== 1) return;
        const value = optionalNumber(row.value);
        if (!Number.isFinite(value)) return;
        const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
        if (!values.has(key)) values.set(key, value);
      });
    });
  });
  return values;
}

function storageSocRatiosByDevice(snapshot) {
  const measured = measurementValuesByDevice(snapshot, ["SOC"]);
  const ratios = new Map();
  const storageParams = parameterRows(snapshot, "DCStorageGen");
  if (storageParams.length) {
    storageParams.forEach((param, index) => {
      const dev = indexedDevice(snapshot, "DCGenerator", param.idx_dcgenerator);
      const name = deviceName(dev) || `DCGenerator_${param.idx_dcgenerator ?? index + 1}`;
      const key = `DCGenerator|${name}`;
      const soc = liveStorageSocRatio(
        measured.get(key) ?? dev?.soc_curr ?? dev?.raw?.soc_curr,
        null,
      );
      if (Number.isFinite(soc)) ratios.set(key, soc);
    });
    return ratios;
  }

  const legacyDevices = new Map((snapshot.devices || [])
    .filter((dev) => deviceType(dev) === "ESS")
    .map((dev) => [deviceName(dev), dev]));
  parameterRows(snapshot, "estorage").forEach((param) => {
    const name = parameterName(param);
    const dev = legacyDevices.get(name);
    const key = `ESS|${name}`;
    const soc = liveStorageSocRatio(
      measured.get(key) ?? dev?.soc_curr ?? dev?.raw?.soc_curr,
      null,
    );
    if (Number.isFinite(soc)) ratios.set(key, soc);
  });
  return ratios;
}

function averageStorageSocRatio(snapshot) {
  const values = [...storageSocRatiosByDevice(snapshot).values()]
    .filter((value) => Number.isFinite(value));
  return values.length
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : null;
}
function renewableClockKey(snapshot) {
  const clock = snapshot.clock || {};
  return `${clock.absolute_minute ?? clock.minute ?? ""}|${clock.time || ""}`;
}

function normalizeConverterSocPowerLimits(values, fallback = DEFAULT_CONVERTER_SOC_POWER_LIMITS) {
  const fallbackValues = Array.isArray(fallback) && fallback.length === 10
    ? fallback
    : DEFAULT_CONVERTER_SOC_POWER_LIMITS;
  if (!Array.isArray(values) || values.length !== 10) return [...fallbackValues];
  const normalized = values.map((value) => Number(value));
  for (let index = 0; index < normalized.length; index += 1) {
    const value = normalized[index];
    if (!Number.isFinite(value) || value < 0 || value > 1) return [...fallbackValues];
    const tenth = Math.round(value * 10);
    if (Math.abs(value * 10 - tenth) > 1e-7) return [...fallbackValues];
    normalized[index] = tenth / 10;
    if (index > 0 && normalized[index] < normalized[index - 1]) return [...fallbackValues];
  }
  return normalized;
}

function renewableControlApiPath(preview = false) {
  return preview ? "/api/trainee/renewable-control?refresh=1" : "/api/trainee/renewable-control";
}

function resetRenewableControlView(modelId = state.activeModelId) {
  const control = state.renewableControl;
  Object.assign(control, {
    modelId: modelId || "",
    enabled: false,
    loopMode: "open",
    sending: false,
    requestActive: false,
    actionActive: false,
    revision: -1,
    lastPlan: null,
    lastCalculatedAt: "",
    lastSentAt: "",
    lastStatus: "正在读取学员台后台控制状态。",
    logs: [],
    converterSocPowerLimits: [...DEFAULT_CONVERTER_SOC_POWER_LIMITS],
    logPage: 1,
    lastControlLogRenderKey: "",
  });
  state.renewableTrendHistory = [];
  closeConverterSocLimitDialog();
}

function applyRenewableControlState(payload = {}) {
  if (!payload || typeof payload !== "object") return false;
  const control = state.renewableControl;
  const incomingRevision = Number(payload.revision);
  if (
    payload.modelId
    && control.modelId === payload.modelId
    && Number.isFinite(incomingRevision)
    && incomingRevision < Number(control.revision ?? -1)
  ) {
    return false;
  }
  const settings = payload.settings && typeof payload.settings === "object" ? payload.settings : {};
  const converterSocPowerLimits = normalizeConverterSocPowerLimits(
    settings.converterSocPowerLimits,
    control.converterSocPowerLimits,
  );
  Object.assign(control, {
    modelId: String(payload.modelId || state.activeModelId || ""),
    enabled: Boolean(payload.enabled),
    loopMode: payload.loopMode === "closed" ? "closed" : "open",
    sending: Boolean(payload.sending),
    intervalSeconds: Math.max(1, toNumber(settings.intervalSeconds, control.intervalSeconds || 2)),
    largeStepThresholdKw: Math.max(0, toNumber(settings.largeStepThresholdKw, control.largeStepThresholdKw || 10)),
    stepCoefficient: Math.max(0, toNumber(settings.renewableStepRatio ?? settings.stepCoefficient, control.stepCoefficient || 0.03)),
    converterStepRatio: Math.max(0, toNumber(settings.converterStepRatio, control.converterStepRatio || 0.03)),
    dieselDeadbandRatio: Math.max(0, toNumber(settings.dieselDeadbandRatio, control.dieselDeadbandRatio || 0.03)),
    socDeadband: Math.max(0, toNumber(settings.socDeadband, control.socDeadband || 0.05)),
    converterSocPowerLimits,
    lastPlan: payload.lastPlan || null,
    lastCalculatedAt: payload.lastCalculatedAt || "",
    lastSentAt: payload.lastSentAt || "",
    lastStatus: payload.status || "学员台后台控制状态已同步。",
    revision: Number.isFinite(incomingRevision) ? incomingRevision : control.revision,
    logs: Array.isArray(payload.logs) ? payload.logs : [],
  });
  state.renewableTrendHistory = Array.isArray(payload.trend) ? payload.trend : [];
  return true;
}

async function refreshRenewableControlState({ preview = false, render = true } = {}) {
  const control = state.renewableControl;
  if (!state.activeModelId || control.requestActive) return null;
  const requestedModelId = state.activeModelId;
  control.requestActive = true;
  try {
    const payload = await api(renewableControlApiPath(preview));
    if (requestedModelId !== state.activeModelId) return null;
    applyRenewableControlState(payload);
    return payload;
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      control.lastStatus = `学员台后台控制状态获取失败：${apiErrorText(error)}`;
    }
    return null;
  } finally {
    if (requestedModelId === state.activeModelId) {
      control.requestActive = false;
      if (render && currentPageName() === "renewable") renderRenewableControl(state.snapshot || {});
    }
  }
}

async function runRenewableControlAction(action, payload = {}) {
  const control = state.renewableControl;
  if (!state.activeModelId || control.actionActive) return null;
  const requestedModelId = state.activeModelId;
  control.actionActive = true;
  renderRenewableControl(state.snapshot || {});
  try {
    const response = await api("/api/trainee/renewable-control", {
      method: "POST",
      body: JSON.stringify({ action, ...payload }),
    });
    if (requestedModelId !== state.activeModelId) return null;
    applyRenewableControlState(response);
    return response;
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      control.lastStatus = `后台控制操作失败：${apiErrorText(error)}`;
    }
    return null;
  } finally {
    if (requestedModelId === state.activeModelId) {
      control.actionActive = false;
      renderRenewableControl(state.snapshot || {});
    }
  }
}
function renewableLoopMode(control = state.renewableControl) {
  return control?.loopMode === "closed" ? "closed" : "open";
}

function renewableLoopModeLabel(mode = renewableLoopMode()) {
  return mode === "closed" ? "闭环" : "开环";
}

function noteRenewableReceiveInterruption(message) {
  if (!state.renewableControl.enabled || currentPageName() !== "renewable") return;
  refreshRenewableControlState({ preview: false });
}

function renderRenewablePager(kind, totalCount) {
  if (kind !== "logs") return;
  const pageSize = RENEWABLE_CONTROL_LOG_PAGE_SIZE;
  const pager = $("renewableControlLogPager");
  if (!pager) return;
  const total = Math.max(0, Number(totalCount) || 0);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, Number(state.renewableControl.logPage) || 1), pageCount);
  state.renewableControl.logPage = page;
  if (!total) {
    pager.innerHTML = "";
    return;
  }
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${total} 条</span>
    <button type="button" data-renewable-pager="logs" data-renewable-page-action="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <strong>第 ${page} / ${pageCount} 页</strong>
    <button type="button" data-renewable-pager="logs" data-renewable-page-action="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

function renewableRemoteAdjustmentPointName(row = {}) {
  if (!row.dev_type || !row.dev_name || !row.set_type) return "--";
  return `${row.dev_type}.${row.dev_name}.${row.set_type}`;
}

function renewableStrategyRows(plan, tabKey = state.renewableControl.strategyTab) {
  const normalizedTab = RENEWABLE_STRATEGY_TABS[tabKey] ? tabKey : "wind";
  const categories = RENEWABLE_STRATEGY_TABS[normalizedTab].categories;
  return (plan?.commandRows || []).filter((row) => categories.has(row.category));
}

function renderRenewableStrategyTabs(plan) {
  const requestedTab = state.renewableControl.strategyTab;
  const activeTab = RENEWABLE_STRATEGY_TABS[requestedTab] ? requestedTab : "wind";
  state.renewableControl.strategyTab = activeTab;
  document.querySelectorAll("[data-renewable-strategy-tab]").forEach((button) => {
    const tabKey = button.dataset.renewableStrategyTab || "";
    const tab = RENEWABLE_STRATEGY_TABS[tabKey];
    if (!tab) return;
    const active = tabKey === activeTab;
    const count = renewableStrategyRows(plan, tabKey).length;
    button.textContent = `${tab.label} ${count}`;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

function renewableControlLogs() {
  return Array.isArray(state.renewableControl.logs) ? state.renewableControl.logs : [];
}

function renderRenewableDetailTabs() {
  const activeTab = state.renewableControl.detailTab === "logs" ? "logs" : "trend";
  state.renewableControl.detailTab = activeTab;
  document.querySelectorAll("[data-renewable-detail-tab]").forEach((button) => {
    const active = button.dataset.renewableDetailTab === activeTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-renewable-detail-pane]").forEach((pane) => {
    const active = pane.dataset.renewableDetailPane === activeTab;
    pane.hidden = !active;
    pane.classList.toggle("is-active", active);
  });
  if (activeTab === "logs") {
    renderRenewableControlLogs();
  } else {
    requestAnimationFrame(drawRenewableTrendChart);
  }
}

function renderRenewableControlLogs() {
  const table = $("renewableControlLogTable");
  const summary = $("renewableControlLogSummary");
  if (!table || !summary) return;
  const logs = renewableControlLogs();
  summary.textContent = `${logs.length} 条`;
  renderRenewablePager("logs", logs.length);
  const page = state.renewableControl.logPage;
  const start = (page - 1) * RENEWABLE_CONTROL_LOG_PAGE_SIZE;
  const pageLogs = logs.slice(start, start + RENEWABLE_CONTROL_LOG_PAGE_SIZE);
  const renderKey = `${page}|${logs.length}|${pageLogs.map((item) => item.seq).join(",")}`;
  if (renderKey === state.renewableControl.lastControlLogRenderKey) return;
  state.renewableControl.lastControlLogRenderKey = renderKey;
  if (!pageLogs.length) {
    table.innerHTML = '<div class="empty-state compact">暂无新能源控制日志</div>';
    return;
  }
  table.innerHTML = `
    <table class="runtime-log-table renewable-control-log-table">
      <thead><tr><th>本机时刻</th><th>仿真时刻</th><th>类型</th><th>结果</th><th>决策过程</th></tr></thead>
      <tbody>
        ${pageLogs.map((item) => `
          <tr class="runtime-log-row is-${escapeHtml(item.level || "info")}">
            <td>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time || "--")}</td>
            <td>${escapeHtml(item.type || "")}</td>
            <td>${escapeHtml(item.result || "")}</td>
            <td class="runtime-log-detail">${escapeHtml(runtimeLogDetailText(item.detail))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renewableTrendWindowRange() {
  const history = state.renewableTrendHistory || [];
  const windowMinutes = Math.max(1, Number(state.renewableTrendWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  return alignedTraceWindowRange(history, windowMinutes, fallbackMinute);
}

function renewableTrendWindowPoints() {
  const range = renewableTrendWindowRange();
  return (state.renewableTrendHistory || []).filter((point) => (
    point.minute >= range.startMinute && point.minute <= range.endMinute
  ));
}

function drawRenewableTrendChart() {
  const canvas = $("renewableTrendChart");
  if (!canvas) return;
  const chartKey = "renewableTrend";
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);

  const left = 72 * ratio;
  const right = 70 * ratio;
  const top = 30 * ratio;
  const bottom = 38 * ratio;
  const plotWidth = Math.max(1, width - left - right);
  const plotHeight = Math.max(1, height - top - bottom);
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };

  const range = renewableTrendWindowRange();
  const points = renewableTrendWindowPoints();
  const seriesDefs = [
    { key: "load", field: "loadKw", label: "负荷功率", color: "#c93a3a", axis: "left", unit: "kW" },
    { key: "diesel", field: "dieselKw", label: "柴发功率", color: "#b87500", axis: "left", unit: "kW" },
    { key: "storage", field: "storageKw", label: "储能功率", color: "#4369b2", axis: "left", unit: "kW" },
    { key: "storageSoc", field: "storageSocPercent", label: "储能SOC", color: "#7a4fb3", axis: "right", unit: "%" },
    { key: "renewable", field: "renewableKw", label: "新能源功率", color: "#23854a", axis: "left", unit: "kW" },
    { key: "acdcCurrent", field: "acdcCurrentKw", label: "变流器当前值", color: "#0a8b8b", axis: "left", unit: "kW" },
    { key: "acdcTarget", field: "acdcTargetKw", label: "变流器目标值", color: "#d24f93", axis: "left", unit: "kW", dashed: true },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const visiblePowerSeries = visibleSeries.filter((series) => series.axis !== "right");
  const powerValues = points.flatMap((point) => visiblePowerSeries.map((series) => point[series.field]))
    .filter((value) => Number.isFinite(value));
  let powerMin = powerValues.length ? Math.min(0, ...powerValues) : -1;
  let powerMax = powerValues.length ? Math.max(0, ...powerValues) : 1;
  if (Math.abs(powerMax - powerMin) < 1e-9) {
    powerMin -= 1;
    powerMax += 1;
  }
  const powerPadding = Math.max(1, (powerMax - powerMin) * 0.08);
  powerMin -= powerPadding;
  powerMax += powerPadding;

  ctx.font = `${11 * ratio}px Consolas, Microsoft YaHei, Arial`;
  for (let index = 0; index <= 4; index += 1) {
    const fraction = index / 4;
    const y = top + plotHeight * fraction;
    ctx.strokeStyle = index === 4 ? "#c9d6dc" : "#e2eaee";
    ctx.lineWidth = 1 * ratio;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "right";
    ctx.fillText(formatNumber(powerMax - (powerMax - powerMin) * fraction), left - 8 * ratio, y + 4 * ratio);
    ctx.fillStyle = "#76549b";
    ctx.textAlign = "left";
    ctx.fillText(`${formatNumber(100 - fraction * 100)}%`, width - right + 8 * ratio, y + 4 * ratio);
  }
  ctx.fillStyle = "#63717a";
  ctx.textAlign = "left";
  ctx.fillText("功率/kW", 8 * ratio, 16 * ratio);
  ctx.fillStyle = "#76549b";
  ctx.textAlign = "right";
  ctx.fillText("SOC/%", width - 8 * ratio, 16 * ratio);

  const xTicks = measurementTraceAxisTicks(range, width / ratio);
  xTicks.forEach((minute, tickIndex) => {
    const x = left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? "#c9d6dc" : "#edf2f4";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.font = `${11 * ratio}px Consolas, Microsoft YaHei, Arial`;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 || tickIndex === xTicks.length - 1 ? 0 : 4 * ratio;
    ctx.fillText(
      measurementTraceTimeLabel(minute, range, tickIndex, xTicks.length - 1),
      x + textOffset,
      height - 11 * ratio,
    );
  });

  const summary = $("renewableTrendSummary");
  if (summary) summary.textContent = `${points.length} 点 · 左轴功率 / 右轴SOC`;
  if (!points.length || !visibleSeries.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    ctx.fillText(!visibleSeries.length ? "所有曲线已隐藏" : "暂无综合趋势数据", width / 2, height / 2);
    return;
  }

  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
  const powerY = (value) => top + plotHeight - ((value - powerMin) / (powerMax - powerMin)) * plotHeight;
  const socY = (value) => top + plotHeight - (clamp(value, 0, 100) / 100) * plotHeight;
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const hitData = [];
  visibleSeries.forEach((series) => {
    const sampled = sampleCurvePointsForCanvas(
      points.map((point) => Number.isFinite(point[series.field]) ? point[series.field] : Number.NaN),
      plotWidth / ratio,
      1.4,
    );
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeries ? 3.2 : 2.2) * ratio;
    ctx.setLineDash(series.dashed ? [7 * ratio, 5 * ratio] : []);
    ctx.beginPath();
    let started = false;
    sampled.forEach(({ index, value }) => {
      if (!Number.isFinite(value)) return;
      const point = points[index];
      if (!point) return;
      const x = xForMinute(point.minute);
      const y = series.axis === "right" ? socY(value) : powerY(value);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    if (started) ctx.stroke();
    ctx.setLineDash([]);
    if (pixelPoints.length === 1) {
      ctx.fillStyle = series.color;
      ctx.beginPath();
      ctx.arc(pixelPoints[0].x, pixelPoints[0].y, 3.5 * ratio, 0, Math.PI * 2);
      ctx.fill();
    }
    hitData.push({ ...series, points: pixelPoints });
  });
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    maxSeries: 8,
    timeLabel: (point) => measurementTraceTimeLabel(point.minute, range, 0, 1),
    valueFormatter: formatNumber,
  });
}

function renderRenewableControl(snapshot = state.snapshot || {}) {
  const control = state.renewableControl;
  const loopMode = renewableLoopMode(control);
  const loopModeLabel = renewableLoopModeLabel(loopMode);
  const plan = control.lastPlan;
  const button = $("renewableAutoToggle");
  if (!button) return;
  const sendOnce = $("renewableSendOnce");
  const stateNode = $("renewableControlState");
  const summary = $("renewableCommandSummary");
  const lastActionLabel = $("renewableLastActionLabel");
  const hasDecisionSnapshot = Boolean(plan);
  button.textContent = control.enabled ? "停止实时控制" : "启动实时控制";
  button.classList.toggle("is-running", control.enabled);
  button.disabled = control.sending || control.actionActive;
  if (sendOnce) {
    sendOnce.disabled = control.sending || control.actionActive;
    sendOnce.textContent = loopMode === "closed" ? "单次计算下发" : "单次计算";
  }
  document.querySelectorAll("[data-renewable-loop-mode]").forEach((modeButton) => {
    const active = modeButton.dataset.renewableLoopMode === loopMode;
    modeButton.classList.toggle("is-active", active);
    modeButton.setAttribute("aria-pressed", String(active));
    modeButton.disabled = control.sending || control.actionActive;
  });
  const periodInput = $("renewableControlPeriod");
  if (periodInput && document.activeElement !== periodInput) periodInput.value = String(control.intervalSeconds || 2);
  const ratioInputs = {
    renewableStepRatio: control.stepCoefficient,
    converterStepRatio: control.converterStepRatio,
    dieselDeadbandRatio: control.dieselDeadbandRatio,
    socDeadband: control.socDeadband,
  };
  Object.entries(ratioInputs).forEach(([id, value]) => {
    const input = $(id);
    if (input && document.activeElement !== input) input.value = String(Number(value || 0) * 100);
  });
  [periodInput, ...Object.keys(ratioInputs).map((id) => $(id))].forEach((input) => {
    if (input) input.disabled = control.actionActive;
  });
  const socLimitButton = $("converterSocLimitButton");
  if (socLimitButton) socLimitButton.disabled = control.actionActive;
  const socLimitDialog = $("converterSocLimitDialog");
  if (socLimitDialog?.open) {
    const saveButton = $("converterSocLimitSave");
    if (saveButton) saveButton.disabled = control.actionActive;
    socLimitDialog.querySelectorAll("select[data-converter-soc-limit-index]").forEach((select) => {
      select.disabled = control.actionActive;
    });
  }
  if (lastActionLabel) lastActionLabel.textContent = loopMode === "closed" ? "最近下发" : "最近计算";
  if (stateNode) {
    stateNode.textContent = control.enabled
      ? `${loopModeLabel}运行`
      : hasDecisionSnapshot
        ? `${loopModeLabel}待命`
        : "等待数据";
  }
  const metrics = plan?.metrics || {};
  const metricPowerText = (value) => Number.isFinite(value) ? `${formatNumber(value)} kW` : "--";
  const metricText = {
    renewableCurrentKw: `${formatNumber(metrics.renewableCurrentKw)} kW`,
    renewableTargetKw: `${formatNumber(metrics.renewableTarget)} kW`,
    renewableDieselCurrentKw: metricPowerText(metrics.dieselCurrentKw),
    renewableDieselMinKw: metricPowerText(metrics.dieselMinKw),
    renewableDieselTargetKw: metricPowerText(metrics.dieselTargetKw),
    renewableStorageCurrentKw: metricPowerText(metrics.storageCurrentKw),
    renewableStorageSoc: Number.isFinite(metrics.storageSoc) ? `${formatOverviewNumber(metrics.storageSoc * 100)}%` : "--",
    renewableAcdcCurrentKw: metricPowerText(metrics.acdcCurrentKw),
    renewableAcdcTargetKw: metricPowerText(metrics.acdcTargetKw),
    renewableLoadKw: metricPowerText(metrics.loadKw),
    renewableLastSent: loopMode === "closed" ? control.lastSentAt || "--" : control.lastCalculatedAt || "--",
  };
  Object.entries(metricText).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
  const status = $("renewableControlStatus");
  if (status) {
    status.textContent = control.sending || control.actionActive ? "学员台后台正在执行控制操作..." : control.lastStatus;
    status.classList.toggle("is-ok", control.enabled || Boolean(control.lastCalculatedAt) || Boolean(control.lastSentAt));
    status.classList.toggle("is-error", !hasDecisionSnapshot && control.enabled);
  }
  if (summary) summary.textContent = `${plan?.commands?.length || 0} 条 · ${plan?.time || "--"} · ${loopModeLabel}`;
  renderRenewableDetailTabs();
  renderRenewableStrategyTabs(plan);
  const table = $("renewableCommandTable");
  if (!table) return;
  const rows = renewableStrategyRows(plan);
  if (!rows.length) {
    const tabLabel = RENEWABLE_STRATEGY_TABS[control.strategyTab]?.label || "当前分类";
    table.innerHTML = `<div class="empty-state compact">暂无${escapeHtml(tabLabel)}设备</div>`;
    return;
  }
  table.innerHTML = `
    <table class="runtime-device-table renewable-command-table">
      <thead><tr><th>设备名称</th><th>遥调点名称</th><th>状态</th><th>当前值</th><th>可用边界</th><th>目标值</th><th>SOC</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr class="${row.online ? "" : "is-muted"}">
            <td>${escapeHtml(row.dev_name)}</td>
            <td class="renewable-control-point" title="${escapeHtml(renewableRemoteAdjustmentPointName(row))}">${escapeHtml(renewableRemoteAdjustmentPointName(row))}</td>
            <td><span class="status-pill ${row.online ? "is-ok" : "is-off"}">${escapeHtml(row.statusLabel || (row.online ? "可控" : "停用"))}</span></td>
            <td class="numeric-cell">${Number.isFinite(row.currentKw) ? `${formatNumber(row.currentKw)} kW` : "--"}</td>
            <td class="numeric-cell">${row.category === "柴油发电"
              ? `下限 ${formatNumber(row.minKw)} / 容量 ${formatNumber(row.capacityKw)}`
              : row.category === "储能平衡源"
                ? `充 ${formatNumber(row.chargePower)} / 放 ${formatNumber(row.dischargePower)}`
                : Number.isFinite(row.availableKw)
                  ? `${formatNumber(row.availableKw)} kW`
                  : Number.isFinite(row.capacityKw)
                    ? `${formatNumber(row.capacityKw)} kW`
                    : "--"}</td>
            <td class="numeric-cell">${Number.isFinite(row.commandKw) ? `${formatNumber(row.commandKw)} kW` : "--"}</td>
            <td>${row.soc === undefined ? "--" : formatNumber(row.soc)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

async function toggleRenewableAuto() {
  const action = state.renewableControl.enabled ? "stop" : "start";
  await runRenewableControlAction(action);
}

async function runRenewableControlOnce() {
  await runRenewableControlAction("run_once");
}

async function setRenewableLoopMode(mode) {
  const nextMode = mode === "closed" ? "closed" : "open";
  if (renewableLoopMode() === nextMode) {
    renderRenewableControl(state.snapshot || {});
    return;
  }
  await runRenewableControlAction("set_loop_mode", { loop_mode: nextMode });
}

async function updateRenewableSettings() {
  const intervalSeconds = Math.max(1, toNumber($("renewableControlPeriod")?.value, 2));
  const ratio = (id, fallbackPercent) => Math.max(0, toNumber($(id)?.value, fallbackPercent)) / 100;
  await runRenewableControlAction("update_settings", {
    settings: {
      intervalSeconds,
      largeStepThresholdKw: state.renewableControl.largeStepThresholdKw,
      renewableStepRatio: ratio("renewableStepRatio", 3),
      converterStepRatio: ratio("converterStepRatio", 3),
      dieselDeadbandRatio: ratio("dieselDeadbandRatio", 3),
      socDeadband: ratio("socDeadband", 5),
    },
  });
}

function setConverterSocLimitMessage(message = "", level = "") {
  const node = $("converterSocLimitMessage");
  if (!node) return;
  node.textContent = message;
  node.className = "model-management-message";
  if (level === "error") node.classList.add("is-error");
  if (level === "ok") node.classList.add("is-ok");
}

function renderConverterSocLimitRows(limits = state.renewableControl.converterSocPowerLimits) {
  const rows = $("converterSocLimitRows");
  if (!rows) return;
  const normalized = normalizeConverterSocPowerLimits(limits);
  const options = Array.from({ length: 11 }, (_value, optionIndex) => optionIndex * 10);
  rows.innerHTML = Array.from({ length: 10 }, (_value, index) => {
    const lower = index * 10;
    const upper = (index + 1) * 10;
    const selectedPercent = Math.round(normalized[index] * 100);
    return `
      <label class="converter-soc-limit-row" role="row" data-converter-soc-limit-row="${index}">
        <span role="cell">${lower}%-${upper}%</span>
        <select role="cell" data-converter-soc-limit-index="${index}" aria-label="SOC ${lower}%至${upper}%变流器功率上限">
          ${options.map((percent) => `<option value="${percent}"${percent === selectedPercent ? " selected" : ""}>${percent}%</option>`).join("")}
        </select>
      </label>`;
  }).join("");
}

function readConverterSocLimitDraft() {
  const rows = $("converterSocLimitRows");
  const selects = Array.from(rows?.querySelectorAll("select[data-converter-soc-limit-index]") || []);
  rows?.querySelectorAll("[data-converter-soc-limit-row]").forEach((row) => row.classList.remove("is-invalid"));
  if (selects.length !== 10) {
    return { limits: null, message: "SOC分段配置不完整，请重新打开设置窗口。" };
  }
  const limits = selects.map((select) => Number(select.value) / 100);
  for (let index = 0; index < limits.length; index += 1) {
    const percent = limits[index] * 100;
    if (!Number.isFinite(limits[index]) || percent < 0 || percent > 100 || Math.round(percent) % 10 !== 0) {
      rows?.querySelector(`[data-converter-soc-limit-row="${index}"]`)?.classList.add("is-invalid");
      return { limits: null, message: `SOC ${index * 10}%-${(index + 1) * 10}% 的功率上限不是有效的10%档位。` };
    }
    if (index > 0 && limits[index] < limits[index - 1]) {
      rows?.querySelector(`[data-converter-soc-limit-row="${index}"]`)?.classList.add("is-invalid");
      return {
        limits: null,
        message: `SOC ${index * 10}%-${(index + 1) * 10}% 的功率上限不能低于前一档。`,
      };
    }
  }
  return { limits, message: "" };
}

function openConverterSocLimitDialog() {
  const dialog = $("converterSocLimitDialog");
  if (!dialog) return;
  renderConverterSocLimitRows(state.renewableControl.converterSocPowerLimits);
  setConverterSocLimitMessage("");
  $("converterSocLimitSave").disabled = Boolean(state.renewableControl.actionActive);
  if (!dialog.open) dialog.showModal();
  dialog.querySelector("select[data-converter-soc-limit-index]")?.focus();
}

function closeConverterSocLimitDialog() {
  const dialog = $("converterSocLimitDialog");
  if (dialog?.open) dialog.close();
}

async function saveConverterSocLimits() {
  if (state.renewableControl.actionActive) return;
  const { limits, message } = readConverterSocLimitDraft();
  if (!limits) {
    setConverterSocLimitMessage(message, "error");
    return;
  }
  const saveButton = $("converterSocLimitSave");
  if (saveButton) saveButton.disabled = true;
  setConverterSocLimitMessage("正在保存变流器SOC分段功率限额...");
  const response = await runRenewableControlAction("update_settings", {
    settings: { converterSocPowerLimits: limits },
  });
  if (response) {
    closeConverterSocLimitDialog();
    return;
  }
  if (saveButton) saveButton.disabled = false;
  setConverterSocLimitMessage(state.renewableControl.lastStatus || "保存失败。", "error");
}

function renderClock(clock) {
  $("simTime").textContent = clock.time || "00:00:00";
  $("simState").textContent = clock.state || "stopped";
  $("simSpeed").textContent = `x${clock.speed ?? 1}`;
  const readout = document.querySelector(".clock-readout");
  if (readout) readout.dataset.clockState = clock.state || "stopped";
}

function deviceKey(dev) {
  return `${dev.dev_type || dev.type || ""}|${dev.dev_name || dev.name || ""}`;
}

function deviceName(dev) {
  return String(dev.dev_name || dev.name || "");
}

function deviceType(dev) {
  return String(dev.dev_type || dev.type || "Unknown");
}

function deviceIndex(dev) {
  return dev.idx ?? dev.raw?.idx ?? "";
}

function statusText(value) {
  return Number(value) ? "投入" : "退出";
}

function deviceTreeBadge(dev) {
  const run = dev.run_stat ?? dev.raw?.run_stat;
  const status = dev.status ?? dev.raw?.status;
  if (status !== undefined && status !== "") return Number(status) ? "闭合" : "断开";
  if (run !== undefined && run !== "") return Number(run) ? "投入" : "退出";
  return dev.mode || "--";
}

function devicesByType(devices) {
  const groups = new Map();
  devices.forEach((dev) => {
    const type = deviceType(dev);
    if (!groups.has(type)) groups.set(type, []);
    groups.get(type).push(dev);
  });
  return Array.from(groups.entries()).sort((a, b) => {
    if (a[0] === "Environment" && b[0] !== "Environment") return -1;
    if (a[0] !== "Environment" && b[0] === "Environment") return 1;
    return a[0].localeCompare(b[0], "zh-Hans-CN");
  });
}

function isDeviceTreeGroupCollapsed(scope, groupKey) {
  return Boolean(state.collapsedDeviceTreeGroups?.[scope]?.[groupKey]);
}

function toggleDeviceTreeGroup(scope, groupKey) {
  if (!scope || !groupKey || groupKey === "all") return;
  if (!state.collapsedDeviceTreeGroups[scope]) state.collapsedDeviceTreeGroups[scope] = {};
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
  const name = deviceName(item);
  if ((devType || deviceType(item)) === "Environment" && name === "weather") return "气象";
  return name;
}

function deviceTreeSearchFields(item, devType = "") {
  const raw = item?.raw || {};
  return [
    devType,
    deviceType(item),
    deviceName(item),
    deviceTreeVisibleName(item, devType),
    deviceIndex(item),
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
  if (scope === "model") renderTraineeModelDeviceTree();
  if (scope === "measurement") renderDeviceTree("measurementDeviceTree", "measurementTreeSummary", measurementDevices(), state.measurementFilter, "measurement", "measurement");
  if (scope === "control") renderDeviceTree("commandDeviceTree", "commandTreeSummary", controlDefinitionDevices(), state.controlFilter, "control", "control");
}

function renderDeviceTree(containerId, summaryId, devices, filter, scope, dataPrefix) {
  const container = $(containerId);
  if (!container) return;
  const groups = devicesByType(devices);
  const treeResult = filterDeviceTreeGroups(groups, scope);
  const total = devices.length;
  $(summaryId).textContent = deviceTreeSummary(treeResult);
  const rootActive = isDeviceTreeNodeActive(filter, "all", "");
  const rootAttr = `data-${dataPrefix}-tree-type="all" data-${dataPrefix}-tree-name=""`;
  const groupHtml = treeResult.groupEntries.map(([devType, items]) => {
    const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed(scope, devType);
    const typeActive = isDeviceTreeNodeActive(filter, devType, "");
    const parentActive = isDeviceTreeParentActive(filter, devType);
    return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${typeActive ? "is-active" : ""} ${parentActive ? "is-parent-active" : ""} ${isCollapsed ? "is-collapsed" : ""}"
          data-${dataPrefix}-tree-type="${escapeHtml(devType)}"
          data-${dataPrefix}-tree-name=""
          ${deviceTreeTypeAttrs(scope, devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => {
          const name = deviceName(dev);
          const displayName = devType === "Environment" && name === "weather" ? "气象" : name;
          const isActive = isDeviceTreeNodeActive(filter, devType, name);
          return `
            <button
              type="button"
              class="tree-node tree-child ${isActive ? "is-active" : ""}"
              data-${dataPrefix}-tree-type="${escapeHtml(devType)}"
              data-${dataPrefix}-tree-name="${escapeHtml(name)}"
            >
              <span>${escapeHtml(displayName)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>`;
        }).join(""))}
      </div>`;
  }).join("");
  const treeHtml = `
    <button type="button" class="tree-node tree-root ${rootActive ? "is-active" : ""}" ${rootAttr}>
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : total}</strong>
    </button>
    ${groupHtml || renderDeviceTreeFilterEmpty(treeResult.query)}`;
  updateDeviceTreeHtml(container, treeHtml);
}

function selectTreeFilter(filterName, devType, devName = "", event = null, button = null, dataPrefix = "") {
  state[filterName] = updateDeviceTreeFilterSelection(
    filterName,
    devType,
    devName,
    event,
    dataPrefix,
    button,
  );
  if (filterName === "measurementFilter") renderMeasurements(state.snapshot || {});
  if (filterName === "controlFilter") renderCombinedControlPage();
}

function filteredDevices(devices, filter) {
  return (devices || []).filter((dev) => deviceFilterMatches(dev, filter));
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

function formatModelParamValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function compareModelRowsByIndex(left, right) {
  const leftIndex = Number(left.idx ?? left.raw?.idx);
  const rightIndex = Number(right.idx ?? right.raw?.idx);
  const indexCompare = (Number.isFinite(leftIndex) ? leftIndex : Number.POSITIVE_INFINITY)
    - (Number.isFinite(rightIndex) ? rightIndex : Number.POSITIVE_INFINITY);
  if (indexCompare) return indexCompare;
  return deviceName(left).localeCompare(deviceName(right), "zh-Hans-CN");
}

function modelAttributeRecordForDevice(dev) {
  const raw = dev.raw || {};
  const headers = Array.isArray(dev.__headers) ? dev.__headers : Object.keys(raw);
  const record = {
    dev_type: deviceType(dev),
    dev_name: deviceName(dev),
    idx: formatModelParamValue(raw.idx ?? deviceIndex(dev)),
    name: formatModelParamValue(raw.name || deviceName(dev)),
    __headers: headers,
  };
  headers.forEach((key) => {
    if (["idx", "name", "dev_name", "dev_type"].includes(key)) return;
    record[key] = formatModelParamValue(raw[key]);
  });
  return record;
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
  records.forEach((record) => (record.__headers || Object.keys(record)).forEach(appendKey));
  return [...fixed, ...keys].map((key) => ({ key, label: key === "name" ? "名称" : key }));
}

function groupedModelAttributeRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const devType = record.dev_type || "未分类";
    if (!groups.has(devType)) groups.set(devType, []);
    groups.get(devType).push(record);
  });
  return Array.from(groups.entries())
    .map(([devType, rows]) => [devType, rows.sort(compareModelRowsByIndex)])
    .sort(([left], [right]) => left.localeCompare(right, "zh-Hans-CN"));
}

function renderModelAttributeTable(rows) {
  const columns = modelAttributeColumns(rows);
  return `<table class="model-param-table">
    <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${columns.map((column) => (
      `<td class="attr-value">${escapeHtml(row[column.key] ?? "--")}</td>`
    )).join("")}</tr>`).join("")}</tbody>
  </table>`;
}

function modelFilterLabel() {
  return deviceFilterLabel(state.modelFilter);
}

function renderTraineeModelDeviceTree(snapshot = state.snapshot || {}) {
  const container = $("modelDeviceTree");
  if (!container) return;
  const devices = definedModelDevices(snapshot);
  const groups = devicesByType(devices).map(([devType, items]) => [devType, [...items].sort(compareModelRowsByIndex)]);
  const treeResult = filterDeviceTreeGroups(groups, "model");
  $("modelTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button type="button" class="tree-node tree-root ${isDeviceTreeNodeActive(state.modelFilter, "all", "") ? "is-active" : ""}"
      data-model-tree-type="all" data-model-tree-name="">
      <span>全部设备</span><strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("model", devType);
      return `<div class="tree-group">
        <button type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(state.modelFilter, devType, "") ? "is-active" : isDeviceTreeParentActive(state.modelFilter, devType) ? "is-parent-active" : ""}"
          data-model-tree-type="${escapeHtml(devType)}" data-model-tree-name=""
          ${deviceTreeTypeAttrs("model", devType, isCollapsed)}>
          ${deviceTreeTypeLabel(devType)}<strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
          <button type="button"
            class="tree-node tree-child model-tree-child ${isDeviceTreeNodeActive(state.modelFilter, devType, deviceName(dev)) ? "is-active" : ""}"
            data-model-tree-type="${escapeHtml(devType)}" data-model-tree-name="${escapeHtml(deviceName(dev))}">
            <span class="model-tree-idx">${escapeHtml(formatModelParamValue(deviceIndex(dev)))}</span>
            <span class="model-tree-name">${escapeHtml(deviceName(dev))}</span>
          </button>`).join(""))}
      </div>`;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}`;
  updateDeviceTreeHtml(container, treeHtml);
}

function renderTraineeModelParamTable(snapshot = state.snapshot || {}) {
  const container = $("modelParamTable");
  if (!container) return;
  const devices = definedModelDevices(snapshot);
  const filtered = filteredDevices(devices, state.modelFilter);
  const groups = groupedModelAttributeRecords(filtered.map(modelAttributeRecordForDevice));
  const availableTabs = groups.map(([devType]) => devType);
  if (!availableTabs.includes(state.activeModelParamTab)) state.activeModelParamTab = availableTabs[0] || "";
  const activeGroup = groups.find(([devType]) => devType === state.activeModelParamTab) || groups[0];
  const activeColumns = activeGroup ? modelAttributeColumns(activeGroup[1]).length : 0;
  $("modelParamSummary").textContent = groups.length > 1
    ? `${modelFilterLabel()} · ${filtered.length}/${devices.length} 台 · ${groups.length} 个分页`
    : `${modelFilterLabel()} · ${filtered.length}/${devices.length} 台 · ${activeColumns} 列属性`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无电网模型数据</div>';
    return;
  }
  if (!activeGroup) {
    container.innerHTML = '<div class="empty-state">当前筛选无模型参数</div>';
    return;
  }
  const [activeType, activeRows] = activeGroup;
  container.innerHTML = `
    <div class="model-param-tabs" role="tablist" aria-label="设备类型参数表">
      ${groups.map(([devType, rows]) => `<button type="button" role="tab"
        class="model-param-tab ${devType === activeType ? "is-active" : ""}"
        data-model-param-tab="${escapeHtml(devType)}" aria-selected="${devType === activeType}">
        <span>${escapeHtml(devType)}</span><strong>${rows.length}</strong>
      </button>`).join("")}
    </div>
    <section class="model-param-tab-page" role="tabpanel">${renderModelAttributeTable(activeRows)}</section>`;
}

function renderTraineeModelPage(snapshot = state.snapshot || {}) {
  renderTraineeModelDeviceTree(snapshot);
  renderTraineeModelParamTable(snapshot);
}

function setTraineeModelFilter(devType, devName = "", event = null, button = null) {
  state.modelFilter = updateDeviceTreeFilterSelection(
    "modelFilter",
    devType,
    devName,
    event,
    "model",
    button,
  );
  if (devType && devType !== "all" && !devName) state.activeModelParamTab = devType;
  renderTraineeModelPage();
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
  return isWeatherMeasurement(row) ? "气象" : row.dev_name || "";
}

function measurementTypeDisplay(row) {
  if (isSignalMeasurement(row)) return signalMeasurementLabel(row);
  return isWeatherMeasurement(row) ? weatherMeasurementLabel(row) : row.meas_type || "";
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

function measurementRows(snapshot = state.snapshot || {}) {
  return measurementDisplayRows(snapshot);
}

function measurementDisplayRows(snapshot = state.snapshot || {}) {
  const measurements = snapshot.measurements || {};
  const definitions = snapshot.definitions?.measurement || snapshot.measurements?.definitions || measurements.definitions || [];
  const primaryRows = definitions.length
    ? definitions
    : (measurements.scada?.length ? measurements.scada : measurements.real || []);
  const scadaByKey = new Map((measurements.scada || []).map((row) => [measurementKey(row), row]));
  const realByKey = new Map((measurements.real || []).map((row) => [measurementKey(row), row]));
  return sortMeasurementsForDisplay(primaryRows.map((definition) => {
    const key = measurementKey(definition);
    const scada = scadaByKey.get(key);
    const real = realByKey.get(key);
    return {
      ...definition,
      value: scada?.value ?? real?.value ?? definition.value,
      valid: scada?.valid ?? real?.valid ?? definition.valid,
      weight: definition.weight,
    };
  }));
}

function measurementsDevices(snapshot = state.snapshot || {}) {
  const devices = new Map();
  measurementRows(snapshot).forEach((row) => {
    const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
    if (!devices.has(key)) {
      devices.set(key, {
        dev_type: row.dev_type || "Measurement",
        dev_name: row.dev_name || row.name || "",
        run_stat: row.valid,
      });
    }
  });
  return Array.from(devices.values());
}

function measurementKey(meas) {
  return `${meas.idx ?? ""}|${meas.name || ""}|${meas.dev_type || ""}|${meas.dev_name || ""}|${meas.meas_type || ""}`;
}

function filteredMeasurements(rows, filter) {
  return (rows || []).filter((row) => deviceFilterMatches(row, filter));
}

function measurementTypeFilterLabel(row) {
  return measurementTypeDisplay(row) || row?.meas_type || "";
}

function measurementTableFilterFields(row) {
  return [
    measurementDisplayName(row),
    measurementDeviceDisplay(row),
    measurementTypeFilterLabel(row),
    row?.name,
    row?.idx,
    row?.dev_type,
    row?.dev_name,
    row?.meas_type,
  ];
}

function syncMeasurementTypeFilter(rows) {
  syncTableKeywordFilter("measurementKeywordFilter", state.measurementKeywordFilter);
  syncTableTypeFilter(
    "measurementTypeFilter",
    "measurementTypeFilter",
    tableFilterTypeOptions(rows, measurementTypeFilterLabel),
  );
}

function applyMeasurementTableFilters(rows) {
  const keyword = state.measurementKeywordFilter || "";
  const type = state.measurementTypeFilter || "all";
  return (rows || []).filter((row) => {
    if (!tableFilterMatchesKeyword(measurementTableFilterFields(row), keyword)) return false;
    if (type !== "all" && measurementTypeFilterLabel(row) !== type) return false;
    return true;
  });
}

function measurementTelemetryRows(rows) {
  return (rows || []).filter((row) => !isSignalMeasurement(row));
}

function measurementSignalRows(rows) {
  return (rows || []).filter((row) => isSignalMeasurement(row));
}

function setMeasurementTab(tabName) {
  state.activeMeasurementTab = tabName === "signal" ? "signal" : "telemetry";
  renderMeasurements(state.snapshot || {});
  drawMeasurementTraceChart();
}

function activeMeasurementRows(rows) {
  return state.activeMeasurementTab === "signal"
    ? measurementSignalRows(rows)
    : measurementTelemetryRows(rows);
}

function renderMeasurementTabs(telemetryRows, signalRows) {
  const activeTab = state.activeMeasurementTab === "signal" ? "signal" : "telemetry";
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
          data-measurement-tab="${tab.key}"
          aria-selected="${activeTab === tab.key ? "true" : "false"}"
        >
          <span>${tab.label}</span>
          <strong>${tab.count}</strong>
        </button>
      `).join("")}
    </div>
  `;
}

function ensureSelectedMeasurement(rows) {
  const keys = new Set(rows.map((row) => measurementKey(row)));
  if (!state.selectedMeasurementKey || !keys.has(state.selectedMeasurementKey)) {
    state.selectedMeasurementKey = rows.length ? measurementKey(rows[0]) : "";
  }
}

function measurementTableStructureKey(rows) {
  return [
    state.activeMeasurementTab || "telemetry",
    deviceTreeFilterSelection(state.measurementFilter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.measurementKeywordFilter || "",
    state.measurementTypeFilter || "all",
    rows.map((row) => measurementKey(row)).join("||"),
  ].join("::");
}

function measurementLiveCellHtml(row, field) {
  if (field === "value") return formatNumber(row.value);
  if (field === "status") {
    const valid = Number(row.valid) ? true : false;
    return `<span class="status-pill ${valid ? "is-ok" : "is-off"}">${valid ? "可用" : "停用"}</span>`;
  }
  return "";
}

function updateMeasurementTableLiveCells(rows) {
  const tableRows = Array.from(document.querySelectorAll("#measurementTable [data-measurement-row-key]"));
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [measurementKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.measurementRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    tableRow.classList.toggle("is-selected", key === state.selectedMeasurementKey);
    tableRow.querySelectorAll("[data-measurement-live-field]").forEach((cell) => {
      const field = cell.dataset.measurementLiveField || "";
      cell.innerHTML = measurementLiveCellHtml(row, field);
      if (field === "value") {
        const value = Number(row.value || 0);
        cell.classList.toggle("value-bad", Math.abs(value) > 10000);
        cell.classList.toggle("value-warn", Math.abs(value) > 1000 && Math.abs(value) <= 10000);
      }
    });
  }
  return true;
}

function renderMeasurements(snapshot = state.snapshot || {}) {
  const container = $("measurementTable");
  if (!container) return;
  const devices = measurementsDevices(snapshot);
  renderDeviceTree("measurementDeviceTree", "measurementTreeSummary", devices, state.measurementFilter, "measurement", "measurement");
  const allRows = measurementRows(snapshot);
  const filteredRows = filteredMeasurements(allRows, state.measurementFilter);
  syncMeasurementTypeFilter(filteredRows);
  const tableFilteredRows = applyMeasurementTableFilters(filteredRows);
  const telemetryRows = measurementTelemetryRows(tableFilteredRows);
  const signalRows = measurementSignalRows(tableFilteredRows);
  const rows = activeMeasurementRows(tableFilteredRows);
  ensureSelectedMeasurement(rows);
  const validCount = rows.filter((item) => Number(item.valid) === 1).length;
  const activeLabel = state.activeMeasurementTab === "signal" ? "遥信" : "遥测";
  const filterActive = tableFilterIsActive(state.measurementKeywordFilter, state.measurementTypeFilter);
  $("measurementValidCount").textContent = filterActive
    ? `${activeLabel} ${rows.length}/${tableFilteredRows.length} 点 · 有效 ${validCount} 点 · 过滤 ${tableFilteredRows.length}/${filteredRows.length} 点`
    : `${activeLabel} ${rows.length}/${filteredRows.length} 点 · 有效 ${validCount} 点`;
  const tabHtml = renderMeasurementTabs(telemetryRows, signalRows);
  if (!allRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">暂无量测数据</div></div>`;
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
  const virtualRows = virtualTableWindow("measurement", rows);
  const structureKey = [
    measurementTableStructureKey(rows),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  if (
    container.dataset.measurementStructureKey === structureKey
    && updateMeasurementTableLiveCells(rows)
  ) {
    drawMeasurementTraceChart();
    return;
  }
  container.dataset.measurementStructureKey = structureKey;
  container.innerHTML = `
    ${tabHtml}
    <div class="measurement-type-tab-page is-active">
    <div class="virtual-table-scroll" data-virtual-table="measurement">
    <table class="measurement-compare-table">
      <thead><tr><th>idx</th><th>量测名</th><th>设备</th><th>类型</th><th>量测值</th><th>状态</th></tr></thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 6)}
        ${virtualRows.rows.map((item) => {
          const key = measurementKey(item);
          const valueClass = Math.abs(Number(item.value || 0)) > 10000 ? "value-bad" : Math.abs(Number(item.value || 0)) > 1000 ? "value-warn" : "";
          return `<tr class="${key === state.selectedMeasurementKey ? "is-selected" : ""}" data-measurement-row-key="${escapeHtml(key)}" data-measurement-select-key="${escapeHtml(key)}">
            <td>${escapeHtml(item.idx ?? "")}</td>
            <td>${escapeHtml(measurementDisplayName(item) || "")}</td>
            <td>${escapeHtml(measurementDeviceDisplay(item))}</td>
            <td>${escapeHtml(measurementTypeDisplay(item))}</td>
            <td class="numeric-cell ${valueClass}" data-measurement-live-field="value">${formatNumber(item.value)}</td>
            <td data-measurement-live-field="status"><span class="status-pill ${Number(item.valid) ? "is-ok" : "is-off"}">${Number(item.valid) ? "可用" : "停用"}</span></td>
          </tr>`;
        }).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 6)}
      </tbody>
    </table>
    </div>
    </div>`;
  restoreVirtualTableScroll(container, "measurement");
  drawMeasurementTraceChart();
}

function appendMeasurementTrace(snapshot) {
  const clock = snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.measurementTraceHistory.length) || 0,
    time: clock.time || "--",
    measurements: {},
  };
  measurementRows(snapshot).forEach((row) => {
    point.measurements[measurementKey(row)] = {
      value: Number(row.value),
      label: `${measurementDeviceDisplay(row) || row.name || ""} ${measurementTypeDisplay(row) || ""}`.trim(),
    };
  });
  state.measurementTraceHistory.push(point);
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
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
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  const alignmentMinutes = traceWindowAlignmentMinutes(minutes);
  const latestMinute = history.length ? history[history.length - 1].minute : fallbackMinute;
  const startMinute = Math.floor(latestMinute / alignmentMinutes) * alignmentMinutes;
  return {
    startMinute,
    endMinute: startMinute + minutes,
    latestMinute,
    windowMinutes: minutes,
    alignmentMinutes,
    axisStepMinutes: traceAxisStepMinutes(minutes),
  };
}

function measurementTraceWindowRange() {
  const history = state.measurementTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.measurementTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  return alignedTraceWindowRange(history, windowMinutes, fallbackMinute);
}

function measurementTraceWindowPoints() {
  const history = state.measurementTraceHistory || [];
  if (!history.length || !state.selectedMeasurementKey) return [];
  const range = measurementTraceWindowRange();
  return history
    .filter((point) => point.minute >= range.startMinute && point.minute <= range.endMinute)
    .map((point) => {
      const item = point.measurements[state.selectedMeasurementKey];
      if (!item || !Number.isFinite(item.value)) return null;
      return { minute: point.minute, time: point.time, value: item.value, label: item.label };
    })
    .filter(Boolean);
}

function formatTraceClockMinute(minute) {
  const total = ((Math.round(Number(minute) || 0) % 1440) + 1440) % 1440;
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

function measurementTraceTimeLabel(minute, range, index, lastIndex) {
  const targetMinute = index === lastIndex ? range.endMinute : minute;
  if (range.windowMinutes <= 1440) return formatTraceClockMinute(targetMinute);
  if (range.windowMinutes >= 525600) return formatYearTraceTickLabel(targetMinute);
  const absolute = Math.max(0, Math.round(Number(targetMinute) || 0));
  const day = Math.floor(absolute / 1440);
  const clock = formatTraceClockMinute(absolute).slice(0, 5);
  return absolute % 1440 === 0 ? `第${day + 1}天` : `第${day + 1}天 ${clock}`;
}

function measurementTraceAxisTicks(range, canvasWidth) {
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

function resizeCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const { width: renderedWidth, height: renderedHeight } = canvasRenderedSize(canvas, 900, 320);
  const width = Math.floor(renderedWidth * ratio);
  const height = Math.floor(renderedHeight * ratio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return { width, height, ratio };
}

function drawMeasurementTraceChart() {
  const canvas = $("measurementTraceChart");
  if (!canvas) return;
  const chartKey = "measurementTrace";
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  const left = 62 * ratio;
  const right = 24 * ratio;
  const top = 34 * ratio;
  const bottom = 38 * ratio;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1 * ratio;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + (plotHeight * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  const range = measurementTraceWindowRange();
  const xTicks = measurementTraceAxisTicks(range, width / ratio);
  xTicks.forEach((minute, tickIndex) => {
    const x = left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4 * ratio;
    ctx.fillText(measurementTraceTimeLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12 * ratio);
  });
  ctx.textAlign = "left";
  const points = measurementTraceWindowPoints();
  const seriesDefs = [
    { key: "value", field: "value", label: "量测值", color: "#c93a3a" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  if (!points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    ctx.fillText(!visibleSeries.length ? "所有曲线已隐藏" : "暂无测点跟踪数据", width / 2, height / 2);
    ctx.textAlign = "left";
    $("measurementTraceSummary").textContent = "未选择测点";
    return;
  }
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = Math.max(1e-6, maxValue - minValue);
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const hitData = [];
  visibleSeries.forEach((series) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeries ? 3.2 : 2.4) * ratio;
    ctx.beginPath();
    let started = false;
    points.forEach((point) => {
      const value = Number(point[series.field]);
      if (!Number.isFinite(value)) return;
      const x = left + ((point.minute - range.startMinute) / range.windowMinutes) * plotWidth;
      const y = top + plotHeight - ((value - minValue) / span) * plotHeight;
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit: "", points: pixelPoints });
  });
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    timeLabel: (point) => measurementTraceTimeLabel(point.minute, range, 0, 0),
    valueFormatter: formatNumber,
  });
  ctx.fillStyle = "#63717a";
  ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
  ctx.fillText(formatNumber(maxValue), 8 * ratio, top + 4 * ratio);
  ctx.fillText(formatNumber(minValue), 8 * ratio, top + plotHeight);
  $("measurementTraceSummary").textContent = `${points[points.length - 1].label || "测点"} · ${points.length} 点`;
}

function commandTraceRunKey(dev, commandType = "run_stat") {
  return `remote-control|${deviceKey(dev)}|${commandType}`;
}

function commandTraceAdjustmentKey(dev, setType) {
  return `remote-adjustment|${deviceKey(dev)}|${setType}`;
}

function commandTraceNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function selectedCommandTraceLabel() {
  const latest = [...(state.commandTraceHistory || [])].reverse()
    .map((point) => point.commands?.[state.selectedCommandTraceKey])
    .find(Boolean);
  return latest?.label || state.selectedCommandTraceLabel || "请选择指令";
}

function commandTraceWindowRange() {
  const history = state.commandTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.commandTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  return alignedTraceWindowRange(history, windowMinutes, fallbackMinute);
}

function commandTraceWindowPoints() {
  const history = state.commandTraceHistory || [];
  if (!history.length || !state.selectedCommandTraceKey) return [];
  const range = commandTraceWindowRange();
  return history
    .filter((point) => point.minute >= range.startMinute && point.minute <= range.endMinute)
    .map((point) => {
      const item = point.commands?.[state.selectedCommandTraceKey];
      if (!item) return null;
      const control = commandTraceNumber(item.control);
      const actual = commandTraceNumber(item.actual);
      return {
        minute: point.minute,
        time: point.time,
        control,
        actual,
        label: item.label,
        unit: item.unit || "",
      };
    })
    .filter(Boolean);
}

function appendCommandTrace(snapshot) {
  const clock = snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return;
  const devices = controlDefinitionDevices(snapshot);
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.commandTraceHistory.length) || 0,
    time: clock.time || "--",
    commands: {},
  };
  selectedControlRows("RunStat", devices, snapshot).forEach((row) => {
    const dev = controlDeviceFromRow(row, snapshot);
    const runKey = commandTraceRunKey(dev, "run_stat");
    const pendingRun = pending.run_status.get(`${deviceKey(dev)}|run_stat`);
    const control = pendingRun ? pendingRun.run_stat : dev.run_stat;
    point.commands[runKey] = {
      control: commandTraceNumber(control),
      actual: commandTraceNumber(dev.run_stat),
      label: `${deviceName(dev)}.遥控投退`,
      unit: "",
    };
  });
  selectedControlRows("CbOpenStat", devices, snapshot).forEach((row) => {
    const dev = controlDeviceFromRow(row, snapshot);
    const statusKey = commandTraceRunKey(dev, "status");
    const pendingStatus = pending.run_status.get(`${deviceKey(dev)}|status`);
    const control = pendingStatus ? pendingStatus.status : dev.status;
    point.commands[statusKey] = {
      control: commandTraceNumber(control),
      actual: commandTraceNumber(dev.status),
      label: `${deviceName(dev)}.遥控开合`,
      unit: "",
    };
  });
  remoteAdjustmentRows(devices, snapshot).forEach((row) => {
    point.commands[row.traceKey] = {
      control: commandTraceNumber(row.controlValue),
      actual: commandTraceNumber(row.measurement),
      label: row.name,
      unit: "",
    };
  });
  state.commandTraceHistory.push(point);
  state.commandTraceHistory = compactTraceHistory(state.commandTraceHistory, state.commandTraceWindowMinutes);
}

function drawCommandTraceChart() {
  const canvas = $("commandTraceChart");
  if (!canvas) return;
  const chartKey = "commandTrace";
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  const left = 62 * ratio;
  const right = 24 * ratio;
  const top = 30 * ratio;
  const bottom = 36 * ratio;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1 * ratio;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + (plotHeight * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  const range = commandTraceWindowRange();
  const xTicks = measurementTraceAxisTicks(range, width / ratio);
  xTicks.forEach((minute, tickIndex) => {
    const x = left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4 * ratio;
    ctx.fillText(measurementTraceTimeLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12 * ratio);
  });
  ctx.textAlign = "left";
  const points = commandTraceWindowPoints();
  const seriesDefs = [
    { key: "control", field: "control", label: "控制值", color: "#c98820" },
    { key: "actual", field: "actual", label: "实时值", color: "#008c8c" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  $("commandTraceSummary").textContent = `${selectedCommandTraceLabel()} · ${points.length} 点`;
  if (!state.selectedCommandTraceKey || !points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    ctx.fillText(
      !visibleSeries.length ? "所有曲线已隐藏" : state.selectedCommandTraceKey ? "暂无指令跟踪数据" : "请选择控制指令",
      width / 2,
      height / 2,
    );
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
  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
  const yForValue = (value) => top + plotHeight - ((value - minValue) / (maxValue - minValue)) * plotHeight;
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const hitData = [];
  const unit = points.find((point) => point.unit)?.unit || "";
  const drawSeries = (series, widthScale) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeries ? widthScale + 1 : widthScale) * ratio;
    ctx.beginPath();
    let started = false;
    points.forEach((point) => {
      const value = point[series.field];
      if (value === null || !Number.isFinite(value)) return;
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
  visibleSeries.forEach((series) => drawSeries(series, series.key === "control" ? 2.4 : 2.2));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    timeLabel: (point) => measurementTraceTimeLabel(point.minute, range, 0, 0),
    valueFormatter: formatNumber,
  });
  ctx.fillStyle = "#63717a";
  ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
  ctx.fillText(formatNumber(maxValue), 8 * ratio, top + 4 * ratio);
  ctx.fillText(formatNumber(minValue), 8 * ratio, top + plotHeight);
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

function snapshotDevice(devType, devName, snapshot = state.snapshot || {}) {
  return (snapshot.devices || []).find((dev) => deviceType(dev) === devType && deviceName(dev) === devName) || null;
}

function controlDeviceFromRow(row, snapshot = state.snapshot || {}) {
  const live = snapshotDevice(row.dev_type, row.dev_name, snapshot) || {};
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
    const device = devices.get(key) || controlDeviceFromRow(row, snapshot);
    device.__control_rows = device.__control_rows || [];
    device.__control_rows.push(row);
    if (row.__control_block === "RunStat") device.run_stat = device.run_stat ?? row.run_stat;
    if (row.__control_block === "CbOpenStat") device.status = device.status ?? row.status;
    if (row.__control_block === "SetValue" && row.set_type) {
      device.set_values = { ...(device.set_values || {}) };
      if (device.set_values[row.set_type] === undefined) device.set_values[row.set_type] = row.set_value;
    }
    devices.set(key, device);
  });
  return Array.from(devices.values());
}

function selectedControlRows(blockName, devices, snapshot = state.snapshot || {}) {
  const selectedKeys = new Set((devices || []).map((dev) => deviceKey(dev)));
  return definedControlRows(blockName, snapshot).filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
}

function remoteControlIssuedTimeInfo(dev, commandType = "run_stat", snapshot = state.snapshot || {}) {
  const history = activeCommandHistory(snapshot).reverse();
  for (const entry of history) {
    const items = entry.normalized?.run_status || entry.payload?.run_status || [];
    const match = items.find((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
      && (commandType === "status"
        ? Object.prototype.hasOwnProperty.call(item, "status")
        : item.run_stat !== undefined && item.run_stat !== "")
    ));
    if (match) return commandSentTimeInfo(entry, snapshot);
  }
  return { wall_time: "--", simu_time: "--" };
}

function remoteControlIssuedAt(dev, commandType = "run_stat", snapshot = state.snapshot || {}) {
  return remoteControlIssuedTimeInfo(dev, commandType, snapshot).wall_time;
}

function remoteControlValueText(commandType, value) {
  if (commandType === "status") return Number(value) ? "闭合" : "断开";
  return statusText(value);
}

function remoteControlLabel(commandType) {
  return commandType === "status" ? "开关开合" : "设备投退";
}

function activeCommandCancelName(dev, commandType, setType = "", snapshot = state.snapshot || {}, issuedTime = null) {
  if (!dev) return "";
  const fieldName = commandType === "set_value" ? setType : (commandType === "status" ? "status" : "run_stat");
  if (!fieldName) return "";
  const activeIssuedTime = issuedTime || (commandType === "set_value"
    ? remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot)
    : remoteControlIssuedTimeInfo(dev, fieldName, snapshot));
  if (!activeIssuedTime || activeIssuedTime.wall_time === "--") return "";
  return `${deviceType(dev)}.${deviceName(dev)}.${fieldName}`;
}

async function sendCommandCancel(commandName, label = "") {
  const name = String(commandName || "").trim();
  if (!name || state.commandCancelSending.has(name)) return;
  const displayLabel = label || name;
  if (!window.confirm(`确认取消当前有效指令：${displayLabel}？`)) return;
  const body = withCommandSendTime({
    source: "trainee-ui",
    cancel_commands: [{ name: commandName }],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  state.commandCancelSending.add(name);
  addRuntimeLog("人工取消", targetName, "取消请求", displayLabel);
  renderCombinedControlPage();
  try {
    const result = await postTeacherCommand(body);
    const cancelled = result.cancelled || result;
    const count = Number(cancelled.remote_controls || 0) + Number(cancelled.remote_adjustments || 0);
    addRuntimeLog(
      "模拟台响应",
      targetName,
      count ? "取消成功" : "无可取消指令",
      `${displayLabel}；取消 ${count} 条，缺失 ${cancelled.missing || 0} 条`,
      count ? "ok" : "warn",
    );
    await refresh();
  } catch (error) {
    addRuntimeLog("模拟台响应", targetName, "取消失败", apiErrorText(error), "error");
  } finally {
    state.commandCancelSending.delete(name);
    renderCombinedControlPage();
  }
}

function remoteControlCommandRows(devices, snapshot = state.snapshot || {}) {
  return [
    ...selectedControlRows("RunStat", devices, snapshot).map((row) => ({
      definition: row,
      dev: controlDeviceFromRow(row, snapshot),
      commandType: "run_stat",
      valueKey: "run_stat",
      typeLabel: remoteControlLabel("run_stat"),
    })),
    ...selectedControlRows("CbOpenStat", devices, snapshot).map((row) => ({
      definition: row,
      dev: controlDeviceFromRow(row, snapshot),
      commandType: "status",
      valueKey: "status",
      typeLabel: remoteControlLabel("status"),
    })),
  ].map((row) => {
    const issuedTime = remoteControlIssuedTimeInfo(row.dev, row.commandType, snapshot);
    const cancelName = activeCommandCancelName(row.dev, row.commandType, "", snapshot, issuedTime);
    return {
      ...row,
      key: `${deviceKey(row.dev)}|${row.commandType}`,
      traceKey: commandTraceRunKey(row.dev, row.commandType),
      name: `${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`,
      category: "遥控",
      issuedTime,
      cancelName,
      active: Boolean(cancelName),
    };
  });
  drawRenewableTrendChart();
}

function commandTableTypeLabel(row) {
  if (row?.typeLabel) return row.typeLabel;
  if (row?.commandType) return remoteControlLabel(row.commandType);
  if (row?.setType) return remoteAdjustmentTypeLabel(row.setType);
  return row?.category || "";
}

function commandTableName(row) {
  if (row?.name) return row.name;
  if (row?.commandType) return `${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`;
  if (row?.setType) return remoteAdjustmentName(row.dev, row.setType);
  return "";
}

function commandTableFilterFields(row) {
  return [
    commandTableName(row),
    commandTableTypeLabel(row),
    row?.category,
    row?.commandType,
    row?.setType,
    row?.key,
    row?.traceKey,
    row?.definition?.idx,
    deviceType(row?.dev || {}),
    deviceName(row?.dev || {}),
  ];
}

function syncCommandTypeFilter(rows) {
  syncTableKeywordFilter("commandKeywordFilter", state.commandKeywordFilter);
  syncTableTypeFilter(
    "commandTypeFilter",
    "commandTypeFilter",
    tableFilterTypeOptions(rows, commandTableTypeLabel),
  );
}

function applyCommandTableFilters(rows) {
  const keyword = state.commandKeywordFilter || "";
  const type = state.commandTypeFilter || "all";
  return (rows || []).filter((row) => {
    if (state.commandOnlyActive && !row.active) return false;
    if (!tableFilterMatchesKeyword(commandTableFilterFields(row), keyword)) return false;
    if (type !== "all" && commandTableTypeLabel(row) !== type) return false;
    return true;
  });
}

function syncCommandOnlyActiveControl() {
  const input = $("commandOnlyActive");
  const text = $("commandOnlyActiveText");
  if (input) input.checked = Boolean(state.commandOnlyActive);
  if (text) text.textContent = state.commandOnlyActive ? "是" : "否";
}

function traineeCommandTraceKey(row) {
  return String(row?.traceKey || row?.key || "");
}

function traineeCommandColumnCount(activeTab) {
  return activeTab === "remote-adjustment" ? 6 : 9;
}

function traineeCommandTableStructureKey(rows, activeTab = state.activeControlTab) {
  const filter = state.controlFilter || { dev_type: "all", dev_name: "" };
  return [
    activeTab,
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.commandKeywordFilter || "",
    state.commandTypeFilter || "all",
    state.commandOnlyActive ? "active" : "all",
    rows.map((row) => traineeCommandTraceKey(row)).join("||"),
  ].join("::");
}

function traineeCommandCancelButtonHtml(cancelName, cancelLabel) {
  const sending = cancelName && state.commandCancelSending.has(cancelName);
  return `
    <button type="button" class="command-cancel-button" data-command-cancel-name="${escapeHtml(cancelName)}" data-command-cancel-label="${escapeHtml(cancelLabel)}" ${cancelName && !sending ? "" : "disabled"}>
      ${sending ? "取消中" : "取消指令"}
    </button>
  `;
}

function traineeRemoteControlLiveValue(row, field) {
  const key = `${deviceKey(row.dev)}|${row.commandType}`;
  if (field === "status") {
    return `<span class="status-pill ${Number(row.dev[row.valueKey]) ? "is-ok" : "is-off"}">${remoteControlValueText(row.commandType, row.dev[row.valueKey])}</span>`;
  }
  if (field === "control") {
    const pendingCommand = pending.run_status.get(key);
    const currentValue = Number(pendingCommand ? pendingCommand[row.valueKey] : row.dev[row.valueKey]);
    return `
      <label class="inline-toggle">
        <input type="checkbox" data-run-key="${escapeHtml(key)}" data-command-type="${escapeHtml(row.commandType)}" ${currentValue ? "checked" : ""} />
        <span>${remoteControlValueText(row.commandType, currentValue)}</span>
      </label>
    `;
  }
  if (field === "wall_time") return escapeHtml(row.issuedTime?.wall_time || "--");
  if (field === "simu_time") return escapeHtml(row.issuedTime?.simu_time || "--");
  if (field === "cancel") {
    return traineeCommandCancelButtonHtml(
      row.cancelName || "",
      `${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`,
    );
  }
  return "";
}

function traineeRemoteAdjustmentLiveValue(row, field) {
  if (field === "measurement") return escapeHtml(formatRemoteAdjustmentValue(row.measurement));
  if (field === "control") return escapeHtml(formatRemoteAdjustmentValue(row.controlValue));
  if (field === "wall_time") return escapeHtml(row.issuedTime?.wall_time || row.issuedAt || "--");
  if (field === "simu_time") return escapeHtml(row.issuedTime?.simu_time || "--");
  if (field === "cancel") return traineeCommandCancelButtonHtml(row.cancelName, row.name);
  return "";
}

function traineeCommandLiveCellHtml(row, field, activeTab = state.activeControlTab) {
  return activeTab === "remote-adjustment"
    ? traineeRemoteAdjustmentLiveValue(row, field)
    : traineeRemoteControlLiveValue(row, field);
}

function updateTraineeCommandTableLiveCells(container, rows, activeTab = state.activeControlTab) {
  const tableRows = Array.from(container?.querySelectorAll?.("[data-trainee-command-row-key]") || []);
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [traineeCommandTraceKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.traineeCommandRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    tableRow.classList.toggle("is-selected", key === state.selectedCommandTraceKey);
    tableRow.dataset.commandTraceLabel = row.name || "";
    tableRow.querySelectorAll("[data-trainee-command-live-field]").forEach((cell) => {
      cell.innerHTML = traineeCommandLiveCellHtml(row, cell.dataset.traineeCommandLiveField || "", activeTab);
    });
  }
  return true;
}

function renderTraineeCommandRows(rows, activeTab = state.activeControlTab) {
  if (activeTab === "remote-adjustment") {
    return rows.map((row) => `<tr class="${row.traceKey === state.selectedCommandTraceKey ? "is-selected" : ""}" data-trainee-command-row-key="${escapeHtml(row.traceKey)}" data-command-trace-key="${escapeHtml(row.traceKey)}" data-command-trace-label="${escapeHtml(row.name)}" data-remote-adjustment-key="${escapeHtml(row.key)}" title="单击选中曲线，双击进行遥调操作">
      <td><span class="remote-adjustment-name-cell"><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(deviceType(row.dev))}</small></span></td>
      <td class="numeric-cell" data-trainee-command-live-field="measurement">${traineeCommandLiveCellHtml(row, "measurement", activeTab)}</td>
      <td class="numeric-cell" data-trainee-command-live-field="control">${traineeCommandLiveCellHtml(row, "control", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="wall_time">${traineeCommandLiveCellHtml(row, "wall_time", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="simu_time">${traineeCommandLiveCellHtml(row, "simu_time", activeTab)}</td>
      <td data-trainee-command-live-field="cancel">${traineeCommandLiveCellHtml(row, "cancel", activeTab)}</td>
    </tr>`).join("");
  }
  return rows.map((row) => {
    const key = `${deviceKey(row.dev)}|${row.commandType}`;
    const traceKey = commandTraceRunKey(row.dev, row.commandType);
    const classes = [
      pending.run_status.has(key) ? "is-pending" : "",
      traceKey === state.selectedCommandTraceKey ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    return `<tr class="${classes}" data-trainee-command-row-key="${escapeHtml(traceKey)}" data-command-trace-key="${escapeHtml(traceKey)}" data-command-trace-label="${escapeHtml(`${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`)}" data-run-status-command="${escapeHtml(key)}" title="单击选中曲线，双击进行遥控操作">
      <td>${escapeHtml(deviceIndex(row.dev))}</td>
      <td>${escapeHtml(`${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`)}</td>
      <td>${escapeHtml(deviceName(row.dev))}</td>
      <td>${escapeHtml(deviceType(row.dev))}</td>
      <td class="run-status-command-cell" title="双击进行遥控操作" data-trainee-command-live-field="status">${traineeCommandLiveCellHtml(row, "status", activeTab)}</td>
      <td data-trainee-command-live-field="control">${traineeCommandLiveCellHtml(row, "control", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="wall_time">${traineeCommandLiveCellHtml(row, "wall_time", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="simu_time">${traineeCommandLiveCellHtml(row, "simu_time", activeTab)}</td>
      <td data-trainee-command-live-field="cancel">${traineeCommandLiveCellHtml(row, "cancel", activeTab)}</td>
    </tr>`;
  }).join("");
}

function renderTraineeCommandTable(rows, activeTab, emptyText, virtualRows = { beforeHeight: 0, afterHeight: 0 }) {
  if (!rows.length) return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  const columnCount = traineeCommandColumnCount(activeTab);
  if (activeTab === "remote-adjustment") {
    return `
      <table class="runtime-device-table remote-adjustment-table">
        <colgroup>
          <col class="remote-adjustment-name-col" />
          <col class="remote-adjustment-value-col" />
          <col class="remote-adjustment-value-col" />
          <col class="remote-adjustment-time-col" />
          <col class="remote-adjustment-time-col" />
          <col class="remote-adjustment-action-col" />
        </colgroup>
        <thead><tr><th>遥调名称</th><th>量测值</th><th>控制值</th><th>下发本机时刻</th><th>下发仿真时刻</th><th>操作</th></tr></thead>
        <tbody>
          ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
          ${renderTraineeCommandRows(rows, activeTab)}
          ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
        </tbody>
      </table>`;
  }
  return `
    <table class="runtime-device-table">
      <thead><tr><th>idx</th><th>遥控名称</th><th>设备名称</th><th>类型</th><th>当前状态</th><th>下发状态</th><th>下发本机时刻</th><th>下发仿真时刻</th><th>操作</th></tr></thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
        ${renderTraineeCommandRows(rows, activeTab)}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
      </tbody>
    </table>`;
}

function renderTraineeCommandTableContainer(container, activeTab, rows, allRows, emptyText) {
  if (!container) return;
  const key = `traineeCommand:${activeTab}`;
  const activeRows = rows;
  const virtualRows = virtualTableWindow(`traineeCommand:${activeTab}`, activeRows);
  const structureKey = [
    traineeCommandTableStructureKey(activeRows, activeTab),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  container.classList.add("virtual-table-scroll");
  container.setAttribute("data-virtual-table", `traineeCommand:${activeTab}`);
  if (!rows.length) {
    container.dataset.traineeCommandStructureKey = "";
    container.innerHTML = `<div class="empty-state">${allRows.length ? escapeHtml(emptyText.filtered) : escapeHtml(emptyText.empty)}</div>`;
    return;
  }
  if (
    container.dataset.traineeCommandStructureKey === structureKey
    && updateTraineeCommandTableLiveCells(container, virtualRows.rows, activeTab)
  ) {
    return;
  }
  container.dataset.traineeCommandStructureKey = structureKey;
  container.innerHTML = renderTraineeCommandTable(virtualRows.rows, activeTab, allRows.length ? emptyText.filtered : emptyText.empty, virtualRows);
  restoreVirtualTableScroll(container, key);
}

function renderRunControls(devices, options = {}) {
  const visibleDevices = filteredDevices(devices, state.controlFilter);
  const allRows = options.rows || remoteControlCommandRows(visibleDevices);
  const rows = applyCommandTableFilters(allRows);
  renderTraineeCommandTableContainer($("runControlTable"), "remote-control", rows, allRows, {
    filtered: "当前过滤无遥控指令",
    empty: "当前筛选无遥控指令",
  });
}

function currentSetValue(dev, setType) {
  const key = `${deviceKey(dev)}|${setType}`;
  if (pending.set_values.has(key)) return pending.set_values.get(key).set_value;
  const exact = dev.set_values?.[setType];
  if (exact !== undefined) return exact;
  const raw = dev.raw || {};
  if (setType === "p_set") return raw.p_set ?? raw.p_ac_set ?? raw.pv0 ?? "";
  if (setType === "q_set") return raw.q_set ?? raw.q_ac_set ?? raw.qv0 ?? "";
  if (setType === "v_set") return raw.v_set ?? raw.v_ac_set ?? "";
  return "";
}

function remoteAdjustmentTypeLabel(setType) {
  return {
    p_set: "P有功设定",
    q_set: "Q无功设定",
    v_set: "V电压设定",
  }[setType] || setType;
}

function remoteAdjustmentName(dev, setType) {
  return `${deviceName(dev)}.${remoteAdjustmentTypeLabel(setType)}`;
}

function remoteAdjustmentMeasTypeMatchesSetType(measType, setType) {
  const type = String(measType || "").toUpperCase();
  const setKey = String(setType || "").toLowerCase();
  if (!type || !setKey) return false;
  if (setKey.startsWith("p") || setKey.includes("_p")) return type === "P" || type.startsWith("P_");
  if (setKey.startsWith("q") || setKey.includes("_q")) return type === "Q" || type.startsWith("Q_");
  if (setKey.startsWith("v") || setKey.includes("_v")) return type === "V" || type.startsWith("V_");
  if (setKey.startsWith("i") || setKey.includes("_i")) return type === "I" || type.startsWith("I_");
  if (setKey.includes("soc")) return type === "SOC";
  return type === setKey.toUpperCase();
}

function remoteAdjustmentMeasurement(dev, setType, snapshot = state.snapshot || {}) {
  const match = measurementDisplayRows(snapshot).find((row) => (
    row.dev_type === deviceType(dev)
    && row.dev_name === deviceName(dev)
    && remoteAdjustmentMeasTypeMatchesSetType(row.meas_type, setType)
  ));
  return match?.value ?? null;
}

function remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot = state.snapshot || {}) {
  const history = activeCommandHistory(snapshot).reverse();
  for (const entry of history) {
    const items = entry.normalized?.set_values || entry.payload?.set_values || [];
    const match = items.find((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
      && item.set_type === setType
    ));
    if (match) return commandSentTimeInfo(entry, snapshot);
  }
  return { wall_time: "--", simu_time: "--" };
}

function remoteAdjustmentIssuedAt(dev, setType, snapshot = state.snapshot || {}) {
  return remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot).wall_time;
}

function remoteAdjustmentRows(devices, snapshot = state.snapshot || {}, options = {}) {
  return selectedControlRows("SetValue", devices, snapshot).map((definitionRow) => {
    const dev = controlDeviceFromRow(definitionRow, snapshot);
    const setType = definitionRow.set_type || "";
    const issuedTime = remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot);
    const cancelName = activeCommandCancelName(dev, "set_value", setType, snapshot, issuedTime);
    return {
      key: `${deviceKey(dev)}|${setType}`,
      traceKey: commandTraceAdjustmentKey(dev, setType),
      dev,
      setType,
      name: remoteAdjustmentName(dev, setType),
      typeLabel: remoteAdjustmentTypeLabel(setType),
      category: "遥调",
      measurement: options.includeMeasurements === false ? null : remoteAdjustmentMeasurement(dev, setType, snapshot),
      controlValue: (() => {
        const current = currentSetValue(dev, setType);
        return current === "" || current === undefined || current === null ? definitionRow.set_value : current;
      })(),
      issuedAt: issuedTime.wall_time,
      issuedTime,
      cancelName,
      active: Boolean(cancelName),
      cancelSending: state.commandCancelSending.has(cancelName),
    };
  });
}

function formatRemoteAdjustmentValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  return formatNumber(value);
}

function renderSetpointControls(devices, options = {}) {
  const visibleDevices = filteredDevices(devices || [], state.controlFilter);
  const allRows = options.rows || remoteAdjustmentRows(visibleDevices);
  const rows = applyCommandTableFilters(allRows);
  renderTraineeCommandTableContainer($("setpointControlTable"), "remote-adjustment", rows, allRows, {
    filtered: "当前过滤无遥调指令",
    empty: "当前筛选无遥调指令",
  });
}

function commandTraceRowsForActiveTab(devices = controlDefinitionDevices()) {
  const visibleDevices = filteredDevices(devices || [], state.controlFilter);
  if (state.activeControlTab === "remote-adjustment") {
    return applyCommandTableFilters(remoteAdjustmentRows(visibleDevices)).map((row) => ({
      key: row.traceKey,
      label: row.name,
    }));
  }
  return applyCommandTableFilters(remoteControlCommandRows(visibleDevices)).map((row) => ({
    key: row.traceKey,
    label: row.name,
  }));
}

function ensureSelectedCommandTrace(devices = controlDefinitionDevices()) {
  const rows = commandTraceRowsForActiveTab(devices);
  if (!rows.length) {
    state.selectedCommandTraceKey = "";
    state.selectedCommandTraceLabel = "";
    return;
  }
  if (!rows.some((row) => row.key === state.selectedCommandTraceKey)) {
    state.selectedCommandTraceKey = rows[0].key;
    state.selectedCommandTraceLabel = rows[0].label;
  } else {
    const selected = rows.find((row) => row.key === state.selectedCommandTraceKey);
    state.selectedCommandTraceLabel = selected?.label || state.selectedCommandTraceLabel;
  }
}

function renderControlTabs() {
  document.querySelectorAll("[data-command-tab]").forEach((button) => {
    const isActive = button.dataset.commandTab === state.activeControlTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  });
  document.querySelectorAll("[data-command-tab-page]").forEach((page) => {
    page.classList.toggle("is-active", page.dataset.commandTabPage === state.activeControlTab);
  });
}

function renderCombinedControlPage(devices = controlDefinitionDevices()) {
  syncCommandOnlyActiveControl();
  renderDeviceTree("commandDeviceTree", "commandTreeSummary", devices, state.controlFilter, "control", "control");
  const visibleDevices = filteredDevices(devices || [], state.controlFilter);
  const activeTab = state.activeControlTab === "remote-adjustment" ? "remote-adjustment" : "remote-control";
  state.activeControlTab = activeTab;
  const remoteControlRows = remoteControlCommandRows(visibleDevices);
  const remoteAdjustmentRowsForFilter = remoteAdjustmentRows(visibleDevices, state.snapshot || {}, {
    includeMeasurements: activeTab === "remote-adjustment",
  });
  const activeRows = activeTab === "remote-adjustment"
    ? remoteAdjustmentRowsForFilter
    : remoteControlRows;
  syncCommandTypeFilter([...remoteControlRows, ...remoteAdjustmentRowsForFilter]);
  ensureSelectedCommandTrace(devices);
  if (activeTab === "remote-adjustment") {
    const runContainer = $("runControlTable");
    if (runContainer) {
      runContainer.dataset.traineeCommandStructureKey = "";
      runContainer.removeAttribute("data-virtual-table");
      runContainer.innerHTML = "";
    }
    renderSetpointControls(devices, { rows: activeRows });
  } else {
    const setpointContainer = $("setpointControlTable");
    if (setpointContainer) {
      setpointContainer.dataset.traineeCommandStructureKey = "";
      setpointContainer.removeAttribute("data-virtual-table");
      setpointContainer.innerHTML = "";
    }
    renderRunControls(devices, { rows: activeRows });
  }
  renderControlTabs();
  drawCommandTraceChart();
}

function selectCommandTraceRow(commandTraceRow) {
  state.selectedCommandTraceKey = commandTraceRow.dataset.commandTraceKey || "";
  state.selectedCommandTraceLabel = commandTraceRow.dataset.commandTraceLabel || "";
  document.querySelectorAll("[data-command-trace-key]").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.commandTraceKey === state.selectedCommandTraceKey);
  });
  drawCommandTraceChart();
}

function commandHistoryKey(item) {
  const accepted = item.accepted || {};
  return [
    item.time || "",
    item.source || "",
    accepted.run_status || 0,
    accepted.set_values || 0,
    JSON.stringify(item.payload || {}).slice(0, 240),
  ].join("|");
}

function syncCommandHistoryLogs(history = []) {
  history.slice(-30).forEach((item) => {
    const key = commandHistoryKey(item);
    if (state.seenCommandHistoryKeys.has(key)) return;
    state.seenCommandHistoryKeys.add(key);
    addRuntimeLog(
      "模拟台响应",
      "模拟台命令历史",
      "记录同步",
      [
        `来源 ${item.source || "student"}`,
        `接受投退 ${item.accepted?.run_status || 0} 条`,
        `接受设值 ${item.accepted?.set_values || 0} 条`,
        `模拟台记录 ${item.time || "--"}`,
      ],
      "ok",
      false,
      runtimeLogSimTimeFromCommandHistory(item),
    );
  });
}

function renderHistory() {
  const historyCount = $("historyCount");
  const commandHistory = $("commandHistory");
  if (!historyCount || !commandHistory) return;
  syncTraineeRuntimeLogTypeFilter();
  const allLogs = filteredTraineeRuntimeLogs();
  const logs = pagedTraineeRuntimeLogs(allLogs);
  renderTraineeRuntimeLogPager(allLogs);
  historyCount.textContent = state.runtimeLogTypeFilter === "all"
    ? `${state.runtimeLogs.length} 条`
    : `${allLogs.length}/${state.runtimeLogs.length} 条`;
  if (!allLogs.length) {
    commandHistory.innerHTML = '<div class="empty-state">暂无运行日志</div>';
    return;
  }
  commandHistory.innerHTML = `
    <table class="runtime-log-table">
      <thead><tr><th>本机时刻</th><th>仿真时刻</th><th>类型</th><th>对象</th><th>结果</th><th>详情</th></tr></thead>
      <tbody>
        ${logs.map((item) => `
          <tr class="runtime-log-row is-${escapeHtml(item.level || "info")}">
            <td>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time || "--")}</td>
            <td>${escapeHtml(item.type || "")}</td>
            <td>${escapeHtml(item.target || "")}</td>
            <td>${escapeHtml(item.result || "")}</td>
            <td class="runtime-log-detail">${escapeHtml(runtimeLogDetailText(item.detail))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renderHistoryIfMounted() {
  if (!$("historyCount") || !$("commandHistory")) return;
  renderHistory();
}

function traineeRuntimeLogTypes() {
  return Array.from(new Set(state.runtimeLogs.map((item) => String(item.type || "")).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncTraineeRuntimeLogTypeFilter() {
  const select = $("traineeRuntimeLogTypeFilter");
  if (!select) return;
  const types = traineeRuntimeLogTypes();
  if (state.runtimeLogTypeFilter !== "all" && !types.includes(state.runtimeLogTypeFilter)) {
    state.runtimeLogTypeFilter = "all";
  }
  select.innerHTML = ["<option value=\"all\">全部类型</option>", ...types.map((type) => (
    `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`
  ))].join("");
  select.value = state.runtimeLogTypeFilter;
}

function filteredTraineeRuntimeLogs() {
  if (state.runtimeLogTypeFilter === "all") return state.runtimeLogs;
  return state.runtimeLogs.filter((item) => item.type === state.runtimeLogTypeFilter);
}

function traineeRuntimeLogPageCount(logs = filteredTraineeRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  return Math.max(1, Math.ceil((logs || []).length / pageSize));
}

function pagedTraineeRuntimeLogs(logs = filteredTraineeRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const pageCount = traineeRuntimeLogPageCount(logs);
  state.runtimeLogPage = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (state.runtimeLogPage - 1) * pageSize;
  return logs.slice(start, start + pageSize);
}

function renderTraineeRuntimeLogPager(logs = filteredTraineeRuntimeLogs()) {
  const pager = $("traineeRuntimeLogPager");
  if (!pager) return;
  if (!logs.length) {
    pager.innerHTML = "";
    return;
  }
  const pageCount = traineeRuntimeLogPageCount(logs);
  const page = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (page - 1) * state.runtimeLogPageSize + 1;
  const end = Math.min(logs.length, page * state.runtimeLogPageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${logs.length} 条</span>
    <button type="button" data-trainee-runtime-log-page="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <strong>第 ${page} / ${pageCount} 页</strong>
    <button type="button" data-trainee-runtime-log-page="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

function clearTraineeRuntimeLogs() {
  state.runtimeLogs = [];
  state.runtimeLogSeq = 0;
  state.runtimeLogPage = 1;
  state.runtimeLogTypeFilter = "all";
  state.renewableControl.logPage = 1;
  state.renewableControl.lastControlLogRenderKey = "";
  renderHistoryIfMounted();
  renderRenewableControlLogs();
}

function activeCommandPreviewRows(snapshot = state.snapshot || {}) {
  const rows = [];
  const seenCommandKeys = new Set();
  [...activeCommandHistory(snapshot)].reverse().forEach((entry) => {
    const timeInfo = commandSentTimeInfo(entry, snapshot);
    const normalized = entry.normalized || {};
    const runItems = normalized.run_status || entry.payload?.run_status || [];
    const setItems = normalized.set_values || entry.payload?.set_values || [];
    runItems.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const isStatus = Object.prototype.hasOwnProperty.call(item, "status");
      const commandType = isStatus ? "status" : "run_stat";
      const value = isStatus ? item.status : item.run_stat;
      if (value === undefined || value === "") return;
      const devType = String(item.dev_type || "").trim();
      const devName = String(item.dev_name || item.name || "").trim();
      if (!devType || !devName) return;
      const commandKey = ["remote_control", devType, devName, commandType].join("|");
      if (seenCommandKeys.has(commandKey)) return;
      seenCommandKeys.add(commandKey);
      const liveDev = snapshotDevice(devType, devName, snapshot) || {};
      const actualValue = isStatus ? liveDev.status : liveDev.run_stat;
      rows.push({
        type: `遥控 · ${remoteControlLabel(commandType)}`,
        name: devName,
        value: remoteControlValueText(commandType, value),
        actual_value: actualValue === undefined || actualValue === ""
          ? "--"
          : remoteControlValueText(commandType, actualValue),
        wall_time: timeInfo.wall_time || "--",
        time: timeInfo.simu_time || "--",
      });
    });
    setItems.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const devType = String(item.dev_type || "").trim();
      const devName = String(item.dev_name || item.name || "").trim();
      const setType = String(item.set_type || "").trim();
      if (!devType || !devName || !setType || item.set_value === undefined || item.set_value === "") return;
      const commandKey = ["remote_adjustment", devType, devName, setType].join("|");
      if (seenCommandKeys.has(commandKey)) return;
      seenCommandKeys.add(commandKey);
      const liveDev = snapshotDevice(devType, devName, snapshot)
        || { dev_type: devType, dev_name: devName };
      const actualValue = remoteAdjustmentMeasurement(liveDev, setType, snapshot);
      rows.push({
        type: `遥调 · ${remoteAdjustmentTypeLabel(setType)}`,
        name: devName,
        value: formatNumber(item.set_value),
        actual_value: formatRemoteAdjustmentValue(actualValue),
        wall_time: timeInfo.wall_time || "--",
        time: timeInfo.simu_time || "--",
      });
    });
  });
  return rows;
}

function renderActiveCommandPreview(snapshot = state.snapshot || {}) {
  const pendingSummary = $("pendingSummary");
  const pendingPreview = $("pendingPreview");
  if (!pendingSummary || !pendingPreview) return;
  const rows = activeCommandPreviewRows(snapshot);
  pendingSummary.textContent = `${rows.length} 项`;
  pendingPreview.innerHTML = rows.length ? `
    <table class="active-command-preview-table">
      <thead>
        <tr>
          <th>下发本机时刻</th>
          <th>设备</th>
          <th>指令</th>
          <th>指令值</th>
          <th>实时值</th>
          <th>仿真时刻</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((item) => `
          <tr>
            <td title="${escapeHtml(item.wall_time)}">${escapeHtml(item.wall_time)}</td>
            <td title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</td>
            <td title="${escapeHtml(item.type)}">${escapeHtml(item.type)}</td>
            <td title="${escapeHtml(item.value)}">${escapeHtml(item.value)}</td>
            <td title="${escapeHtml(item.actual_value)}">${escapeHtml(item.actual_value)}</td>
            <td title="${escapeHtml(item.time)}">${escapeHtml(item.time)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  ` : '<div class="empty-state compact">暂无当前有效指令</div>';
}

function updatePendingCount() {
  const total = pending.run_status.size + pending.set_values.size;
  setOptionalText("pendingCount", total);
  setOptionalText("runPendingCount", `${pending.run_status.size} 待发`);
  setOptionalText("setpointPendingCount", `${pending.set_values.size} 待发`);
  setOptionalText("commandPendingCount", `${total} 待发`);
  setOptionalText("commandState", total ? "待发送" : "待命");
  renderActiveCommandPreview();
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 100) return number.toFixed(1);
  return number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function findDeviceByKey(key) {
  const [devType = "", devName = ""] = String(key || "").split("|");
  return controlDefinitionDevices().find((dev) => deviceKey(dev) === `${devType}|${devName}`)
    || null;
}

function closeRemoteControlDialog() {
  const dialog = $("remoteControlDialog");
  if (dialog?.open) dialog.close();
  state.remoteControlDevice = null;
  state.remoteControlSending = false;
}

function openRemoteControlDialog(dev, commandType = dev?.__command_type || "run_stat") {
  const dialog = $("remoteControlDialog");
  if (!dialog || !dev) return;
  state.remoteControlDevice = { ...dev, __command_type: commandType };
  state.remoteControlSending = false;
  const valueKey = commandType === "status" ? "status" : "run_stat";
  const currentRun = Number(dev[valueKey]) ? 1 : 0;
  $("remoteControlDevice").textContent = deviceName(dev);
  $("remoteControlType").textContent = `${deviceType(dev)} / ${remoteControlLabel(commandType)}`;
  $("remoteControlCurrent").innerHTML = `<span class="status-pill ${currentRun ? "is-ok" : "is-off"}">${remoteControlValueText(commandType, currentRun)}</span>`;
  $("remoteControlHint").textContent = "确认后将立即向模拟台下发遥控指令。";
  $("remoteControlHint").className = "remote-control-hint";
  document.querySelectorAll('input[name="remoteControlState"]').forEach((input) => {
    input.checked = Number(input.value) === (currentRun ? 0 : 1);
    const label = input.closest("label");
    const strong = label?.querySelector("strong");
    const small = label?.querySelector("small");
    if (strong) strong.textContent = remoteControlValueText(commandType, Number(input.value));
    if (small) small.textContent = commandType === "status"
      ? (Number(input.value) ? "闭合开关或断路器" : "断开开关或断路器")
      : (Number(input.value) ? "使设备进入运行状态" : "使设备退出运行状态");
  });
  $("remoteControlConfirm").disabled = false;
  $("remoteControlConfirm").textContent = "确认下发";
  dialog.showModal();
}

async function sendRemoteControlCommand() {
  const dev = state.remoteControlDevice;
  if (!dev || state.remoteControlSending) return;
  const selected = document.querySelector('input[name="remoteControlState"]:checked');
  if (!(selected instanceof HTMLInputElement)) return;
  const commandType = dev.__command_type === "status" ? "status" : "run_stat";
  const command = {
    dev_type: deviceType(dev),
    dev_name: deviceName(dev),
  };
  command[commandType] = Number(selected.value) ? 1 : 0;
  const body = withCommandSendTime({
    source: "trainee-ui",
    ...manualCommandHoldPayload(),
    run_status: [command],
    set_values: [],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  state.remoteControlSending = true;
  $("remoteControlConfirm").disabled = true;
  $("remoteControlConfirm").textContent = "下发中";
  $("remoteControlHint").textContent = `${deviceName(dev)}：${remoteControlValueText(commandType, command[commandType])}`;
  addRuntimeLog("人工遥控", targetName, "下发请求", `${deviceName(dev)} → ${remoteControlValueText(commandType, command[commandType])}`);
  try {
    const result = await postTeacherCommand(body);
    addRuntimeLog(
      "模拟台响应",
      targetName,
      "遥控成功",
      `${deviceName(dev)} → ${remoteControlValueText(commandType, command[commandType])}；接受 ${result.run_status || 0} 条`,
      "ok",
    );
    pending.run_status.delete(`${deviceKey(dev)}|${commandType}`);
    closeRemoteControlDialog();
    updatePendingCount();
    await refresh();
  } catch (error) {
    state.remoteControlSending = false;
    $("remoteControlConfirm").disabled = false;
    $("remoteControlConfirm").textContent = "重新下发";
    $("remoteControlHint").textContent = apiErrorText(error);
    $("remoteControlHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥控失败", apiErrorText(error), "error");
  }
}

function findRemoteAdjustmentByKey(key) {
  return remoteAdjustmentRows(controlDefinitionDevices()).find((row) => row.key === key) || null;
}

function closeRemoteAdjustmentDialog() {
  const dialog = $("remoteAdjustmentDialog");
  if (dialog?.open) dialog.close();
  state.remoteAdjustment = null;
  state.remoteAdjustmentSending = false;
}

function openRemoteAdjustmentDialog(row) {
  const dialog = $("remoteAdjustmentDialog");
  if (!dialog || !row) return;
  state.remoteAdjustment = row;
  state.remoteAdjustmentSending = false;
  $("remoteAdjustmentName").textContent = row.name;
  $("remoteAdjustmentDevice").textContent = `${deviceType(row.dev)} / ${deviceName(row.dev)}`;
  $("remoteAdjustmentMeasurement").textContent = formatRemoteAdjustmentValue(row.measurement);
  $("remoteAdjustmentCurrent").textContent = formatRemoteAdjustmentValue(row.controlValue);
  $("remoteAdjustmentIssuedAt").textContent = row.issuedTime?.wall_time || row.issuedAt || "--";
  if ($("remoteAdjustmentIssuedSimAt")) $("remoteAdjustmentIssuedSimAt").textContent = row.issuedTime?.simu_time || "--";
  $("remoteAdjustmentValue").value = row.controlValue === null || row.controlValue === undefined ? "" : row.controlValue;
  $("remoteAdjustmentHint").textContent = "确认后将立即向模拟台下发一条遥调指令。";
  $("remoteAdjustmentHint").className = "remote-control-hint";
  $("remoteAdjustmentConfirm").disabled = false;
  $("remoteAdjustmentConfirm").textContent = "确认下发";
  dialog.showModal();
  $("remoteAdjustmentValue").focus();
  $("remoteAdjustmentValue").select();
}

async function sendRemoteAdjustmentCommand() {
  const row = state.remoteAdjustment;
  if (!row || state.remoteAdjustmentSending) return;
  const setValue = Number($("remoteAdjustmentValue").value);
  if (!Number.isFinite(setValue)) {
    $("remoteAdjustmentHint").textContent = "请输入有效的控制值。";
    $("remoteAdjustmentHint").className = "remote-control-hint is-error";
    return;
  }
  const command = {
    dev_type: deviceType(row.dev),
    dev_name: deviceName(row.dev),
    set_type: row.setType,
    set_value: setValue,
  };
  const body = withCommandSendTime({
    source: "trainee-ui",
    ...manualCommandHoldPayload(),
    run_status: [],
    set_values: [command],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  state.remoteAdjustmentSending = true;
  $("remoteAdjustmentConfirm").disabled = true;
  $("remoteAdjustmentConfirm").textContent = "下发中";
  $("remoteAdjustmentHint").textContent = `${row.name}：${formatNumber(setValue)}`;
  addRuntimeLog("人工遥调", targetName, "下发请求", `${row.name} → ${formatNumber(setValue)}`);
  try {
    const result = await postTeacherCommand(body);
    addRuntimeLog(
      "模拟台响应",
      targetName,
      "遥调成功",
      `${row.name} → ${formatNumber(setValue)}；接受 ${result.set_values || 0} 条`,
      "ok",
    );
    pending.set_values.delete(row.key);
    closeRemoteAdjustmentDialog();
    updatePendingCount();
    await refresh();
  } catch (error) {
    state.remoteAdjustmentSending = false;
    $("remoteAdjustmentConfirm").disabled = false;
    $("remoteAdjustmentConfirm").textContent = "重新下发";
    $("remoteAdjustmentHint").textContent = apiErrorText(error);
    $("remoteAdjustmentHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥调失败", apiErrorText(error), "error");
  }
}

function handleTreeClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const button = target.closest("[data-model-tree-type], [data-measurement-tree-type], [data-control-tree-type]");
  if (!button) return;
  event.preventDefault();
  const toggleScope = button.dataset.treeToggleScope;
  const toggleGroup = button.dataset.treeToggleGroup || "";
  const selection =
    button.dataset.modelTreeType !== undefined
      ? ["modelFilter", button.dataset.modelTreeType, button.dataset.modelTreeName || ""]
      : button.dataset.measurementTreeType !== undefined
      ? ["measurementFilter", button.dataset.measurementTreeType, button.dataset.measurementTreeName || ""]
      : button.dataset.controlTreeType !== undefined
        ? ["controlFilter", button.dataset.controlTreeType, button.dataset.controlTreeName || ""]
          : null;
  requestAnimationFrame(() => {
    if (toggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) toggleDeviceTreeGroup(toggleScope, toggleGroup);
    if (selection?.[0] === "modelFilter") setTraineeModelFilter(selection[1], selection[2], event, button);
    else if (selection) selectTreeFilter(selection[0], selection[1], selection[2], event, button, selection[0] === "measurementFilter" ? "measurement" : "control");
  });
}

function handleTraineeTableFilterControl(target) {
  if (!(target instanceof Element)) return false;
  const control = target.closest("[data-table-filter-scope]");
  if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return false;
  const scope = control.dataset.tableFilterScope || "";
  const field = control.dataset.tableFilterField || "";
  if (scope === "measurement") {
    if (field === "type") state.measurementTypeFilter = control.value || "all";
    else state.measurementKeywordFilter = control.value || "";
    renderMeasurements(state.snapshot || {});
    drawMeasurementTraceChart();
    return true;
  }
  if (scope === "command") {
    if (field === "type") state.commandTypeFilter = control.value || "all";
    else state.commandKeywordFilter = control.value || "";
    renderCombinedControlPage();
    drawCommandTraceChart();
    return true;
  }
  return false;
}

document.addEventListener("input", (event) => {
  if (handleTraineeTableFilterControl(event.target)) return;
  const input = event.target.closest?.("[data-device-tree-filter-scope]");
  if (!input) return;
  const scope = input.dataset.deviceTreeFilterScope || "";
  state.deviceTreeSearch[scope] = input.value || "";
  refreshDeviceTreeFilterScope(scope);
});
document.addEventListener("change", (event) => {
  if (!(event.target instanceof Element)) return;
  const target = event.target;
  const onlyActiveToggle = target.closest("#commandOnlyActive");
  if (!(onlyActiveToggle instanceof HTMLInputElement)) return;
  state.commandOnlyActive = onlyActiveToggle.checked;
  syncCommandOnlyActiveControl();
  renderCombinedControlPage();
});
document.addEventListener("scroll", handleVirtualTableScroll, true);

document.addEventListener("click", (event) => {
  handleTreeClick(event);
  const target = event.target instanceof Element ? event.target : null;
  const chartToggle = target?.closest("[data-chart-toggle][data-chart-series]");
  if (chartToggle) {
    event.preventDefault();
    const chartKey = chartToggle.dataset.chartToggle || "";
    const seriesKey = chartToggle.dataset.chartSeries || "";
    const drawFn = chartKey === "measurementTrace" ? drawMeasurementTraceChart
      : chartKey === "commandTrace" ? drawCommandTraceChart
        : chartKey === "renewableTrend" ? drawRenewableTrendChart
          : null;
    toggleChartSeriesVisibility(chartKey, seriesKey, drawFn);
    return;
  }
  if (target?.closest("#clearRuntimeLogs")) {
    event.preventDefault();
    clearTraineeRuntimeLogs();
    return;
  }
  const modelParamTab = target?.closest("[data-model-param-tab]");
  if (modelParamTab) {
    requestAnimationFrame(() => {
      state.activeModelParamTab = modelParamTab.dataset.modelParamTab || "";
      renderTraineeModelParamTable();
    });
  }
  const curveDisplayButton = target?.closest("[data-curve-display-tree-type]");
  if (curveDisplayButton) {
    event.preventDefault();
    requestAnimationFrame(() => selectCurveDisplayButton(curveDisplayButton));
    return;
  }
  const commandTab = target?.closest("[data-command-tab]");
  if (commandTab) {
    state.activeControlTab = commandTab.dataset.commandTab || "remote-control";
    ensureSelectedCommandTrace(controlDefinitionDevices());
    renderCombinedControlPage();
    return;
  }
  const commandCancelButton = target?.closest("[data-command-cancel-name]");
  if (commandCancelButton) {
    event.preventDefault();
    event.stopPropagation();
    const commandName = commandCancelButton.dataset.commandCancelName || "";
    const commandLabel = commandCancelButton.dataset.commandCancelLabel || commandName;
    sendCommandCancel(commandName, commandLabel);
    return;
  }
  const commandTraceRow = target?.closest("[data-command-trace-key]");
  if (commandTraceRow) {
    selectCommandTraceRow(commandTraceRow);
    return;
  }
  const measurementTab = target?.closest("[data-measurement-tab]");
  if (measurementTab) {
    setMeasurementTab(measurementTab.dataset.measurementTab || "telemetry");
    return;
  }
  const measurementRow = target?.closest("[data-measurement-select-key]");
  if (measurementRow) {
    const key = measurementRow.dataset.measurementSelectKey || "";
    requestAnimationFrame(() => {
      state.selectedMeasurementKey = key;
      renderMeasurements(state.snapshot || {});
    });
  }
});

document.addEventListener("dblclick", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const adjustmentRow = target?.closest("[data-remote-adjustment-key]");
  if (adjustmentRow) {
    event.preventDefault();
    const adjustment = findRemoteAdjustmentByKey(adjustmentRow.dataset.remoteAdjustmentKey || "");
    if (adjustment) openRemoteAdjustmentDialog(adjustment);
    return;
  }
  const statusCell = target?.closest("[data-run-status-command]");
  if (!statusCell) return;
  event.preventDefault();
  const commandKey = statusCell.dataset.runStatusCommand || "";
  const dev = findDeviceByKey(statusCell.dataset.runStatusCommand || "");
  const commandType = commandKey.split("|")[2] || "run_stat";
  if (dev) {
    dev.__command_type = commandType;
    openRemoteControlDialog(dev);
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  if (handleTraineeTableFilterControl(target)) return;
  const runKey = target.dataset.runKey;
  if (runKey) {
    const [dev_type, dev_name, commandType = "run_stat"] = runKey.split("|");
    const item = { dev_type, dev_name };
    item[commandType === "status" ? "status" : "run_stat"] = target.checked ? 1 : 0;
    pending.run_status.set(runKey, item);
    updatePendingCount();
    renderRunControls(controlDefinitionDevices());
    drawCommandTraceChart();
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const setKey = target.dataset.setKey;
  if (setKey) {
    const [dev_type, dev_name] = setKey.split("|");
    const set_type = target.dataset.setType;
    pending.set_values.set(`${setKey}|${set_type}`, {
      dev_type,
      dev_name,
      set_type,
      set_value: Number(target.value),
    });
    target.classList.add("is-pending");
    updatePendingCount();
    drawCommandTraceChart();
  }
});

async function toggleReceiveMode() {
  if (state.receiveMode) {
    state.receiveMode = false;
    state.frozen = true;
    state.receiveEpoch += 1;
    state.receiveReconnectAttempts = 0;
    state.receiveRequestActive = false;
    persistActiveModelContext({ receiveMode: false, frozen: true });
    addRuntimeLog("接收模式", "模拟台实时数据", "停止接收", `冻结于 ${state.lastReceiveAt || "--"}`, "warn");
    noteRenewableReceiveInterruption("连续接收已停止，新能源优先策略保持运行，继续使用最近一次有效数据。");
    try {
      await saveTraineeReceiveState(state.activeModelId, { active: false, frozen: true });
    } catch (error) {
      addRuntimeLog("接收模式", "学员台服务端", "保存停止状态失败", apiErrorText(error), "warn");
    }
    renderReceiveMode();
    return;
  }
  openReceiveLinkDialog();
}

$("modelManagementButton").addEventListener("click", openModelManagementDialog);
$("closeModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("cancelModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("modelManagementDialog").addEventListener("click", (event) => {
  if (event.target === $("modelManagementDialog")) closeModelManagementDialog();
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
$("importDefinitionsButton").addEventListener("click", () => $("definitionArchiveInput").click());
$("definitionArchiveInput").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) openImportModelDialog(file);
});
$("newModelButton").addEventListener("click", openNewModelDialog);
$("closeNewModelDialog").addEventListener("click", closeNewModelDialog);
$("cancelNewModel").addEventListener("click", closeNewModelDialog);
$("newModelDialog").addEventListener("click", (event) => {
  if (event.target === $("newModelDialog")) closeNewModelDialog();
});
$("selectNewModelFile").addEventListener("click", () => $("newModelFileInput").click());
$("newModelFileInput").addEventListener("change", handleNewModelFileSelected);
$("newModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createNewModelFromArchive();
});
$("newModelName").addEventListener("input", () => validateNewModelForm());
$("closeImportModelDialog").addEventListener("click", closeImportModelDialog);
$("cancelImportModel").addEventListener("click", closeImportModelDialog);
$("importModelDialog").addEventListener("click", (event) => {
  if (event.target === $("importModelDialog")) closeImportModelDialog();
});
$("importModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  importDefinitionModel();
});
$("importModelName").addEventListener("input", () => validateImportModelName());
$("closeUpdateModelDialog").addEventListener("click", closeUpdateModelDialog);
$("cancelUpdateModel").addEventListener("click", closeUpdateModelDialog);
$("updateModelDialog").addEventListener("click", (event) => {
  if (event.target === $("updateModelDialog")) closeUpdateModelDialog();
});
$("selectUpdateModelFile").addEventListener("click", () => $("updateModelFileInput").click());
$("updateModelFileInput").addEventListener("change", handleUpdateModelFileSelected);
$("updateModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  updateModelFromArchive();
});
$("closeCloneModelDialog").addEventListener("click", closeCloneModelDialog);
$("cancelCloneModel").addEventListener("click", closeCloneModelDialog);
$("cloneModelDialog").addEventListener("click", (event) => {
  if (event.target === $("cloneModelDialog")) closeCloneModelDialog();
});
$("cloneModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  cloneManagedModel();
});
$("cloneModelName").addEventListener("input", () => validateCloneModelName());
$("traineeRunToggle").addEventListener("click", toggleReceiveMode);
$("receiveLinkClose").addEventListener("click", closeReceiveLinkDialog);
$("receiveLinkCancel").addEventListener("click", closeReceiveLinkDialog);
$("confirmReceiveLink").addEventListener("click", startReceiveModeFromLink);
$("receiveLinkDialog").addEventListener("click", (event) => {
  if (event.target === $("receiveLinkDialog")) closeReceiveLinkDialog();
});
$("receiveWarningClose").addEventListener("click", closeReceiveWarningDialog);
$("receiveWarningConfirm").addEventListener("click", closeReceiveWarningDialog);
$("receiveWarningDialog").addEventListener("click", (event) => {
  if (event.target === $("receiveWarningDialog")) closeReceiveWarningDialog();
});
$("remoteControlClose").addEventListener("click", closeRemoteControlDialog);
$("remoteControlCancel").addEventListener("click", closeRemoteControlDialog);
$("remoteControlConfirm").addEventListener("click", sendRemoteControlCommand);
$("remoteControlDialog").addEventListener("click", (event) => {
  if (event.target === $("remoteControlDialog")) closeRemoteControlDialog();
});
$("remoteAdjustmentClose").addEventListener("click", closeRemoteAdjustmentDialog);
$("remoteAdjustmentCancel").addEventListener("click", closeRemoteAdjustmentDialog);
$("remoteAdjustmentConfirm").addEventListener("click", sendRemoteAdjustmentCommand);
$("remoteAdjustmentDialog").addEventListener("click", (event) => {
  if (event.target === $("remoteAdjustmentDialog")) closeRemoteAdjustmentDialog();
});
$("renewableAutoToggle").addEventListener("click", toggleRenewableAuto);
$("renewableSendOnce").addEventListener("click", runRenewableControlOnce);
$("converterSocLimitButton").addEventListener("click", openConverterSocLimitDialog);
$("converterSocLimitClose").addEventListener("click", closeConverterSocLimitDialog);
$("converterSocLimitCancel").addEventListener("click", closeConverterSocLimitDialog);
$("converterSocLimitSave").addEventListener("click", saveConverterSocLimits);
$("converterSocLimitDialog").addEventListener("click", (event) => {
  if (event.target === $("converterSocLimitDialog")) closeConverterSocLimitDialog();
});
document.querySelectorAll("[data-renewable-loop-mode]").forEach((button) => {
  button.addEventListener("click", () => setRenewableLoopMode(button.dataset.renewableLoopMode));
});
$("renewableControlPeriod").addEventListener("change", updateRenewableSettings);
[
  "renewableStepRatio",
  "converterStepRatio",
  "dieselDeadbandRatio",
  "socDeadband",
].forEach((id) => $(id)?.addEventListener("change", updateRenewableSettings));
document.querySelectorAll("[data-renewable-strategy-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tabKey = button.dataset.renewableStrategyTab || "wind";
    if (!RENEWABLE_STRATEGY_TABS[tabKey]) return;
    state.renewableControl.strategyTab = tabKey;
    renderRenewableControl(state.snapshot || {});
  });
});
document.querySelectorAll("[data-renewable-detail-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    state.renewableControl.detailTab = button.dataset.renewableDetailTab === "logs" ? "logs" : "trend";
    renderRenewableDetailTabs();
  });
});
$("renewableControlLogPager")?.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-renewable-pager=\"logs\"]") : null;
  if (!button) return;
  const total = renewableControlLogs().length;
  const pageCount = Math.max(1, Math.ceil(total / RENEWABLE_CONTROL_LOG_PAGE_SIZE));
  const direction = button.dataset.renewablePageAction;
  state.renewableControl.logPage = direction === "prev"
    ? Math.max(1, state.renewableControl.logPage - 1)
    : Math.min(pageCount, state.renewableControl.logPage + 1);
  state.renewableControl.lastControlLogRenderKey = "";
  renderRenewableControlLogs();
});
$("clearRuntimeLogs").addEventListener("click", clearTraineeRuntimeLogs);
$("traineeRuntimeLogTypeFilter").addEventListener("change", (event) => {
  state.runtimeLogTypeFilter = event.target.value || "all";
  state.runtimeLogPage = 1;
  renderHistory();
});
$("traineeRuntimeLogPager").addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-trainee-runtime-log-page]") : null;
  if (!button) return;
  const direction = button.dataset.traineeRuntimeLogPage;
  const pageCount = traineeRuntimeLogPageCount(filteredTraineeRuntimeLogs());
  state.runtimeLogPage = direction === "prev"
    ? Math.max(1, state.runtimeLogPage - 1)
    : Math.min(pageCount, state.runtimeLogPage + 1);
  renderHistory();
});
const modelSelector = $("modelSelector");
if (modelSelector) {
  modelSelector.addEventListener("change", (event) => setActiveModel(event.target.value));
}
$("measurementTraceWindow").addEventListener("change", (event) => {
  state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
  drawMeasurementTraceChart();
});
const commandTraceWindow = $("commandTraceWindow");
if (commandTraceWindow) {
  commandTraceWindow.addEventListener("change", (event) => {
    state.commandTraceWindowMinutes = Number(event.target.value) || 60;
    drawCommandTraceChart();
  });
}
const renewableTrendWindow = $("renewableTrendWindow");
if (renewableTrendWindow) {
  renewableTrendWindow.addEventListener("change", (event) => {
    state.renewableTrendWindowMinutes = Number(event.target.value) || 60;
    drawRenewableTrendChart();
  });
}
initTraceChartInteractions("measurementTrace", "measurementTraceChart", drawMeasurementTraceChart);
initTraceChartInteractions("commandTrace", "commandTraceChart", drawCommandTraceChart);
initTraceChartInteractions("renewableTrend", "renewableTrendChart", drawRenewableTrendChart);
const curveDisplayChart = $("curveDisplayChart");
if (curveDisplayChart) {
  let lastCurveDisplayPointerDownAt = 0;
  let lastCurveDisplayHandledAt = 0;
  const handleCurveDisplaySelection = (event) => {
    if (event.button !== undefined && event.button !== 0) return false;
    const legendKey = curveDisplayLegendKeyAtPointer(event);
    if (legendKey) {
      event.preventDefault();
      toggleCurveDisplaySeriesVisibility(legendKey, true);
      return true;
    }
    const hitKey = curveDisplayKeyAtPointer(event);
    if (hitKey) {
      event.preventDefault();
      state.activeCurveDisplayKey = hitKey;
      drawCurveDisplay(state.snapshot || {});
      return true;
    }
    return false;
  };
  const handleCurveDisplayPointerDown = (event) => {
    if (event.type === "pointerdown") {
      lastCurveDisplayPointerDownAt = Date.now();
    } else if (Date.now() - lastCurveDisplayPointerDownAt < 80) {
      return;
    }
    if (handleCurveDisplaySelection(event)) {
      lastCurveDisplayHandledAt = Date.now();
    }
  };
  curveDisplayChart.addEventListener("pointermove", (event) => setCurveDisplayCursorFromEvent(event));
  curveDisplayChart.addEventListener("mousemove", (event) => setCurveDisplayCursorFromEvent(event));
  curveDisplayChart.addEventListener("pointerleave", hideCurveDisplayCursor);
  curveDisplayChart.addEventListener("mouseleave", hideCurveDisplayCursor);
  curveDisplayChart.addEventListener("pointerdown", handleCurveDisplayPointerDown);
  curveDisplayChart.addEventListener("mousedown", handleCurveDisplayPointerDown);
  curveDisplayChart.addEventListener("click", (event) => {
    if (Date.now() - lastCurveDisplayHandledAt < 160) return;
    handleCurveDisplaySelection(event);
  });
}
window.addEventListener("resize", () => {
  drawMeasurementTraceChart();
  drawCommandTraceChart();
  drawRenewableTrendChart();
  drawCurveDisplay(state.snapshot || {});
});

initOverviewBottomSplitter();
initOverviewBottomColumnSplitter();
initVerticalSplitters();
renderReceiveMode();
renderHistory();
initPageNavigation();
loadModels().finally(refresh);
setInterval(refresh, 1000);
