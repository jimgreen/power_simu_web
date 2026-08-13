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
const STATIC_CACHE_STORAGE_KEY = "polarTraineeStaticCacheV2";
const STATIC_CACHE_MODEL_LIMIT = 4;
const CURVE_DISPLAY_TREE_COLLAPSE_KEY = "polarTraineeCurveTreeCollapsedGroups";
const RUNTIME_LOG_COLUMN_WIDTHS_KEY = "polarTraineeRuntimeLogColumnWidths";
const RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS = Object.freeze([104, 104, 112, 190, 104, 640]);
const RUNTIME_LOG_COLUMN_MIN_WIDTHS = Object.freeze([82, 82, 78, 110, 78, 180]);
const HIDDEN_REFRESH_INTERVAL_MS = 10000;
const MODEL_CONTEXT_PERSIST_INTERVAL_MS = 5000;
const WEB_RUNTIME_FALLBACKS = {
  frontend_refresh_seconds: 1,
  frontend_request_timeout_seconds: 30,
  runtime_log_page_size: 20,
  runtime_log_cache_limit: 300,
  backend_refresh_seconds: 1,
  backend_request_timeout_seconds: 8,
  frame_age_limit_seconds: 15,
  same_frame_limit_seconds: 30,
  receive_state_sync_seconds: 5,
  receive_max_reconnect_attempts: 3,
  measurement_delta_history_limit: 200,
  diagram_flow_electric_threshold_kw: 0.1,
  diagram_flow_hydrogen_threshold_nm3_h: 0.1,
};
const WEB_RUNTIME_CURRENT_IDS = {
  frontend_refresh_seconds: "currentWebRuntimeFrontendRefresh",
  frontend_request_timeout_seconds: "currentWebRuntimeFrontendRequestTimeout",
  runtime_log_page_size: "currentWebRuntimeLogPageSize",
  runtime_log_cache_limit: "currentWebRuntimeLogCacheLimit",
  backend_refresh_seconds: "currentBackendRuntimeRefresh",
  backend_request_timeout_seconds: "currentBackendRuntimeRequestTimeout",
  frame_age_limit_seconds: "currentBackendRuntimeFrameAgeLimit",
  same_frame_limit_seconds: "currentBackendRuntimeSameFrameLimit",
  receive_state_sync_seconds: "currentWebRuntimeReceiveStateSync",
  receive_max_reconnect_attempts: "currentBackendRuntimeReconnectAttempts",
  measurement_delta_history_limit: "currentBackendRuntimeMeasurementDeltaHistoryLimit",
  diagram_flow_electric_threshold_kw: "currentWebRuntimeDiagramElectricFlowThreshold",
  diagram_flow_hydrogen_threshold_nm3_h: "currentWebRuntimeDiagramHydrogenFlowThreshold",
};
const RUNTIME_PARAMETER_GROUPS = Object.freeze({
  backend: Object.freeze([
    "backend_refresh_seconds",
    "backend_request_timeout_seconds",
    "frame_age_limit_seconds",
    "same_frame_limit_seconds",
    "receive_max_reconnect_attempts",
    "measurement_delta_history_limit",
  ]),
  web: Object.freeze([
    "frontend_refresh_seconds",
    "frontend_request_timeout_seconds",
    "runtime_log_page_size",
    "runtime_log_cache_limit",
    "receive_state_sync_seconds",
    "diagram_flow_electric_threshold_kw",
    "diagram_flow_hydrogen_threshold_nm3_h",
  ]),
});
const DEFAULT_STORAGE_CHARGE_DERATING_CURVE = Object.freeze([
  { soc: 0.60, powerRatio: 1.00 },
  { soc: 0.70, powerRatio: 0.50 },
  { soc: 0.80, powerRatio: 0.30 },
  { soc: 0.85, powerRatio: 0.15 },
  { soc: 0.90, powerRatio: 0.00 },
]);
const DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE = Object.freeze([
  { soc: 0.10, powerRatio: 0.00 },
  { soc: 0.15, powerRatio: 0.15 },
  { soc: 0.20, powerRatio: 0.30 },
  { soc: 0.30, powerRatio: 0.50 },
  { soc: 0.40, powerRatio: 1.00 },
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
  modelInitialized: false,
  modelInitializedAt: "",
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
  teacherDefinitionArchivePath: "",
  localDefinitionSnapshot: null,
  localDefinitionModelId: "",
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
  receiveReconnectAttempts: 0,
  receiveTransportFailureCount: 0,
  receiveTransportInterrupted: false,
  refreshRequestActive: false,
  receiveRequestActive: false,
  receiveStateSyncActive: false,
  lastReceiveStateSyncAtMs: 0,
  definitionMismatchLastKey: "",
  runtimeLogs: [],
  runtimeLogColumnWidths: readStoredRuntimeLogColumnWidths(),
  runtimeLogTypeFilter: "all",
  runtimeLogPage: 1,
  runtimeLogPageSize: 20,
  runtimeLogSeq: 0,
  seenCommandHistoryKeys: new Set(),
  selectedManagementModelId: "",
  cloneSourceModelId: "",
  modelFilter: { dev_type: "all", dev_name: "" },
  activeModelParamTab: "",
  activeCurveDisplayKey: "wind_speed_mps",
  selectedCurveDisplayKeys: ["wind_speed_mps"],
  hiddenCurveDisplayKeys: [],
  curveDisplayTreeGroupCollapsed: readStoredCurveDisplayTreeCollapsedGroups(),
  curveDisplayCursor: { visible: false, x: 0, y: 0, index: 0 },
  curveDisplayLegendHitBoxes: [],
  lastCurveDisplayRenderKey: "",
  lastCurveDisplayTableKey: "",
  remoteControlDevice: null,
  remoteControlSending: false,
  remoteAdjustment: null,
  remoteAdjustmentSending: false,
  diagramDeviceCommandContext: null,
  commandCancelSending: new Set(),
  measurementFilter: { dev_type: "all", dev_name: "" },
  measurementKeywordFilter: "",
  measurementTypeFilter: "all",
  measurementDeltaSeq: 0,
  measurementDeltaRequestActive: false,
  embeddedMeasurementDeltaReceived: false,
  measurementArrayWarning: "",
  controlFilter: { dev_type: "all", dev_name: "" },
  commandKeywordFilter: "",
  commandTypeFilter: "all",
  commandOriginFilter: "all",
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
  chartPeriodOffsets: { measurementTrace: 0, commandTrace: 0, renewableTrend: 0 },
  collapsedDeviceTreeGroups: {},
  deviceTreeSearch: {},
  activeMeasurementTab: "telemetry",
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
  measurementHistoryLoaded: {},
  measurementHistoryRequests: {},
  measurementHistoryGeneration: 0,
  renewableTrendHistory: [],
  renewableTrendWindowMinutes: 60,
  renewableTrendSeriesFilter: "",
  renewableTrendSelectedOnly: false,
  chartLegendSeriesHidden: {},
  traceRunId: null,
  traceStepCount: null,
  renewableControl: {
    modelId: "",
    controllerInstanceId: "",
    enabled: false,
    desiredEnabled: false,
    resumePending: false,
    runState: "stopped",
    controlFrozen: false,
    simulationPaused: false,
    receiveActive: false,
    canRun: false,
    prerequisiteStatus: "请先启动接收。",
    loopMode: "open",
    intervalSeconds: 2,
    largeStepThresholdKw: 10,
    stepCoefficient: 0.03,
    storageStepRatio: 0.03,
    storageSocCorrectionStepScale: 0.2,
    gridFormingStorageProtectionRatio: 0.05,
    dieselPowerProtectionRatio: 0.03,
    socDeadband: 0.05,
    hydrogenClosedLoopEnabled: false,
    hydrogenPressureDeadbandRatio: 0.05,
    electrolyzerPowerMinRatio: 0.02,
    electrolyzerPowerMaxRatio: 0.50,
    electrolyzerPowerDeadbandRatio: 0,
    electrolyzerPowerStepRatio: 0.02,
    electrolyzerDieselPowerLimitRatio: 0.80,
    electrolyzerDieselPowerDeadbandRatio: 0.05,
    electrolyzerStorageSocLowerLimit: 0.4,
    electrolyzerStorageSocUpperLimit: 0.8,
    electrolyzerHydrogenStorageSocUpperLimit: 0.9,
    fuelCellPowerMinRatio: 0.03,
    fuelCellPowerMaxRatio: 0.15,
    fuelCellPowerDeadbandRatio: 0,
    fuelCellPowerStepRatio: 0.03,
    fuelCellDieselPowerLimitRatio: 0.80,
    fuelCellStorageSocLimit: 0.4,
    fuelCellHydrogenStorageSocUpperLimit: 0.8,
    fuelCellHydrogenStorageSocLowerLimit: 0.2,
    optimizationRenewableCurtailmentWeight: 1,
    optimizationDieselOutputWeight: 1,
    optimizationCurtailmentSquareWeight: 0.000001,
    optimizationSourceStorageAdjustmentSquareWeight: 0.000001,
    optimizationBalanceDeltaSquareWeight: 10000,
    optimizationBalanceDeltaWarningKw: 1,
    optimizationBalanceToleranceKw: 0.1,
    optimizationBoundToleranceKw: 0.1,
    optimizationFtol: 0.001,
    optimizationMaxIterations: 100,
    commandValidMinutes: 120,
    storageChargeDeratingCurve: DEFAULT_STORAGE_CHARGE_DERATING_CURVE.map((point) => ({ ...point })),
    storageDischargeDeratingCurve: DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE.map((point) => ({ ...point })),
    sending: false,
    requestActive: false,
    actionActive: false,
    revision: -1,
    planRevision: -1,
    performanceRevision: -1,
    lastPlan: null,
    performanceDiagnostics: null,
    lastCalculatedAt: "",
    lastSentAt: "",
    lastStatus: "请选择单次计算或启动实时控制。",
    logs: [],
    metricTab: "ac",
    parameterTab: "runtime",
    strategyTab: "ac-wind",
    detailTab: "trend",
    logPage: 1,
    selectedLogSeq: 0,
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
  webRuntimeSettings: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeDefaults: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeConstraints: {},
  webRuntimeDraft: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeUpdatedAt: "",
  webRuntimeLoadedModelId: "",
  webRuntimeLoading: false,
  webRuntimeSavingGroup: "",
  webRuntimeDirtyGroups: { backend: false, web: false },
  webRuntimeErrors: { load: "", backend: "", web: "" },
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
    renewableRenderCount: 0,
  },
};
window.__polarFrontendDiagnostics = state.frontendDiagnostics;
const pending = { run_status: new Map(), set_values: new Map() };
let modelContextPersistTimerId = null;
let lastModelContextPersistAtMs = 0;
let lastPersistedModelContextsJson = localStorage.getItem(MODEL_CONTEXTS_STORAGE_KEY) || "";
const RENEWABLE_CONTROL_LOG_PAGE_SIZE = 8;
const RENEWABLE_STRATEGY_TABS = {
  "ac-wind": { label: "交流风电", categories: new Set(["交流风电"]) },
  "dc-wind": { label: "直流风电", categories: new Set(["直流风电"]) },
  "ac-pv": { label: "交流光伏", categories: new Set(["交流光伏"]) },
  "dc-pv": { label: "直流光伏", categories: new Set(["直流光伏"]) },
  "ac-grid-storage": { label: "交流跟网储能", categories: new Set(["交流跟网储能"]) },
  "dc-grid-storage": { label: "直流跟网储能", categories: new Set(["直流跟网储能"]) },
  "ac-balance-storage": { label: "交流平衡储能", categories: new Set(["交流平衡储能"]) },
  "dc-balance-storage": { label: "直流平衡储能", categories: new Set(["直流平衡储能"]) },
  diesel: { label: "柴发", categories: new Set(["柴油发电"]) },
  converter: { label: "ACDC变流", categories: new Set(["交直流变流器"]) },
  hydrogen: { label: "氢能", categories: new Set(["氢能"]) },
};
const RENEWABLE_TREND_SCOPE_DEFS = [
  { key: "ac", label: "交流" },
  { key: "dc", label: "直流" },
  { key: "hydrogen", label: "氢能" },
  { key: "system", label: "系统" },
];
const RENEWABLE_TREND_SERIES_DEFS = [
  { key: "acRenewableCurrent", metricId: "renewableAcCurrentKw", field: "acRenewableCurrentKw", label: "交流新能源当前值", scope: "ac", device: "renewable", deviceLabel: "新能源", curveLabel: "功率", group: "ac-renewable", color: "#23854a", axis: "left", unit: "kW", style: "power" },
  { key: "acRenewableTarget", metricId: "renewableAcTargetKw", field: "acRenewableTargetKw", label: "交流新能源目标值", scope: "ac", device: "renewable", deviceLabel: "新能源", curveLabel: "目标", group: "ac-renewable", color: "#23854a", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acRenewableMaxAvailable", metricId: "renewableAcMaxAvailableKw", field: "acRenewableMaxAvailableKw", label: "交流新能源最大可发", scope: "ac", device: "renewable", deviceLabel: "新能源", curveLabel: "最大可发", group: "ac-renewable", color: "#23854a", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "acWindCurrent", metricId: "renewableAcWindCurrentKw", field: "acWindCurrentKw", label: "交流风电当前值", scope: "ac", device: "wind", deviceLabel: "风电", curveLabel: "功率", group: "ac-wind", color: "#137c72", axis: "left", unit: "kW", style: "power" },
  { key: "acWindTarget", metricId: "renewableAcWindTargetKw", field: "acWindTargetKw", label: "交流风电目标值", scope: "ac", device: "wind", deviceLabel: "风电", curveLabel: "目标", group: "ac-wind", color: "#137c72", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acWindMaxAvailable", metricId: "renewableAcWindMaxAvailableKw", field: "acWindMaxAvailableKw", label: "交流风电最大可发", scope: "ac", device: "wind", deviceLabel: "风电", curveLabel: "最大可发", group: "ac-wind", color: "#137c72", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "acPvCurrent", metricId: "renewableAcPvCurrentKw", field: "acPvCurrentKw", label: "交流光伏当前值", scope: "ac", device: "pv", deviceLabel: "光伏", curveLabel: "功率", group: "ac-pv", color: "#c17a00", axis: "left", unit: "kW", style: "power" },
  { key: "acPvTarget", metricId: "renewableAcPvTargetKw", field: "acPvTargetKw", label: "交流光伏目标值", scope: "ac", device: "pv", deviceLabel: "光伏", curveLabel: "目标", group: "ac-pv", color: "#c17a00", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acPvMaxAvailable", metricId: "renewableAcPvMaxAvailableKw", field: "acPvMaxAvailableKw", label: "交流光伏最大可发", scope: "ac", device: "pv", deviceLabel: "光伏", curveLabel: "最大可发", group: "ac-pv", color: "#c17a00", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "acGridFollowingStorageCurrent", metricId: "renewableAcGridFollowingStorageCurrentKw", field: "acGridFollowingStorageCurrentKw", label: "交流跟网储能当前值", scope: "ac", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "功率", group: "ac-grid-following-storage", color: "#315aa6", axis: "left", unit: "kW", style: "power" },
  { key: "acGridFollowingStorageTarget", metricId: "renewableAcGridFollowingStorageTargetKw", field: "acGridFollowingStorageTargetKw", label: "交流跟网储能目标值", scope: "ac", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "目标", group: "ac-grid-following-storage", color: "#315aa6", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acGridFollowingStorageSoc", metricId: "renewableAcGridFollowingStorageSoc", field: "acGridFollowingStorageSocPercent", label: "交流跟网储能SOC", scope: "ac", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "SOC", group: "ac-grid-following-storage", color: "#315aa6", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "acGridFormingStorageCurrent", metricId: "renewableAcGridFormingStorageCurrentKw", field: "acGridFormingStorageCurrentKw", label: "交流构网储能当前值", scope: "ac", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "功率", group: "ac-grid-forming-storage", color: "#7a4fb3", axis: "left", unit: "kW", style: "power" },
  { key: "acGridFormingStorageTarget", metricId: "renewableAcGridFormingStorageTargetKw", field: "acGridFormingStorageTargetKw", label: "交流构网储能目标值", scope: "ac", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "目标", group: "ac-grid-forming-storage", color: "#7a4fb3", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acGridFormingStorageSoc", metricId: "renewableAcGridFormingStorageSoc", field: "acGridFormingStorageSocPercent", label: "交流构网储能SOC", scope: "ac", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "SOC", group: "ac-grid-forming-storage", color: "#7a4fb3", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "acDieselCurrent", metricId: "renewableAcDieselCurrentKw", field: "acDieselCurrentKw", label: "交流柴发当前值", scope: "ac", device: "diesel", deviceLabel: "柴发", curveLabel: "功率", group: "ac-diesel", color: "#a76500", axis: "left", unit: "kW", style: "power" },
  { key: "acDieselMin", metricId: "renewableAcDieselMinKw", field: "acDieselMinKw", label: "交流柴发下限值", scope: "ac", device: "diesel", deviceLabel: "柴发", curveLabel: "下限", group: "ac-diesel", color: "#a76500", axis: "left", unit: "kW", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "acDieselTarget", metricId: "renewableAcDieselTargetKw", field: "acDieselTargetKw", label: "交流柴发目标值", scope: "ac", device: "diesel", deviceLabel: "柴发", curveLabel: "目标", group: "ac-diesel", color: "#a76500", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acLoad", metricId: "renewableAcLoadKw", field: "acLoadKw", label: "交流负荷功率", scope: "ac", device: "load", deviceLabel: "负荷", curveLabel: "功率", group: "ac-load", color: "#c93a3a", axis: "left", unit: "kW", style: "power" },
  { key: "dcRenewableCurrent", metricId: "renewableDcCurrentKw", field: "dcRenewableCurrentKw", label: "直流新能源当前值", scope: "dc", device: "renewable", deviceLabel: "新能源", curveLabel: "功率", group: "dc-renewable", color: "#118b78", axis: "left", unit: "kW", style: "power" },
  { key: "dcRenewableTarget", metricId: "renewableDcTargetKw", field: "dcRenewableTargetKw", label: "直流新能源目标值", scope: "dc", device: "renewable", deviceLabel: "新能源", curveLabel: "目标", group: "dc-renewable", color: "#118b78", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcRenewableMaxAvailable", metricId: "renewableDcMaxAvailableKw", field: "dcRenewableMaxAvailableKw", label: "直流新能源最大可发", scope: "dc", device: "renewable", deviceLabel: "新能源", curveLabel: "最大可发", group: "dc-renewable", color: "#118b78", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "dcWindCurrent", metricId: "renewableDcWindCurrentKw", field: "dcWindCurrentKw", label: "直流风电当前值", scope: "dc", device: "wind", deviceLabel: "风电", curveLabel: "功率", group: "dc-wind", color: "#087f89", axis: "left", unit: "kW", style: "power" },
  { key: "dcWindTarget", metricId: "renewableDcWindTargetKw", field: "dcWindTargetKw", label: "直流风电目标值", scope: "dc", device: "wind", deviceLabel: "风电", curveLabel: "目标", group: "dc-wind", color: "#087f89", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcWindMaxAvailable", metricId: "renewableDcWindMaxAvailableKw", field: "dcWindMaxAvailableKw", label: "直流风电最大可发", scope: "dc", device: "wind", deviceLabel: "风电", curveLabel: "最大可发", group: "dc-wind", color: "#087f89", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "dcPvCurrent", metricId: "renewableDcPvCurrentKw", field: "dcPvCurrentKw", label: "直流光伏当前值", scope: "dc", device: "pv", deviceLabel: "光伏", curveLabel: "功率", group: "dc-pv", color: "#d66f3c", axis: "left", unit: "kW", style: "power" },
  { key: "dcPvTarget", metricId: "renewableDcPvTargetKw", field: "dcPvTargetKw", label: "直流光伏目标值", scope: "dc", device: "pv", deviceLabel: "光伏", curveLabel: "目标", group: "dc-pv", color: "#d66f3c", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcPvMaxAvailable", metricId: "renewableDcPvMaxAvailableKw", field: "dcPvMaxAvailableKw", label: "直流光伏最大可发", scope: "dc", device: "pv", deviceLabel: "光伏", curveLabel: "最大可发", group: "dc-pv", color: "#d66f3c", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "dcGridFollowingStorageCurrent", metricId: "renewableDcGridFollowingStorageCurrentKw", field: "dcGridFollowingStorageCurrentKw", label: "直流跟网储能当前值", scope: "dc", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "功率", group: "dc-grid-following-storage", color: "#2f80c4", axis: "left", unit: "kW", style: "power" },
  { key: "dcGridFollowingStorageTarget", metricId: "renewableDcGridFollowingStorageTargetKw", field: "dcGridFollowingStorageTargetKw", label: "直流跟网储能目标值", scope: "dc", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "目标", group: "dc-grid-following-storage", color: "#2f80c4", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcGridFollowingStorageSoc", metricId: "renewableDcGridFollowingStorageSoc", field: "dcGridFollowingStorageSocPercent", label: "直流跟网储能SOC", scope: "dc", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "SOC", group: "dc-grid-following-storage", color: "#2f80c4", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dcGridFormingStorageCurrent", metricId: "renewableDcGridFormingStorageCurrentKw", field: "dcGridFormingStorageCurrentKw", label: "直流构网储能当前值", scope: "dc", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "功率", group: "dc-grid-forming-storage", color: "#a15ca8", axis: "left", unit: "kW", style: "power" },
  { key: "dcGridFormingStorageTarget", metricId: "renewableDcGridFormingStorageTargetKw", field: "dcGridFormingStorageTargetKw", label: "直流构网储能目标值", scope: "dc", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "目标", group: "dc-grid-forming-storage", color: "#a15ca8", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcGridFormingStorageSoc", metricId: "renewableDcGridFormingStorageSoc", field: "dcGridFormingStorageSocPercent", label: "直流构网储能SOC", scope: "dc", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "SOC", group: "dc-grid-forming-storage", color: "#a15ca8", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dcDieselCurrent", metricId: "renewableDcDieselCurrentKw", field: "dcDieselCurrentKw", label: "直流柴发当前值", scope: "dc", device: "diesel", deviceLabel: "柴发", curveLabel: "功率", group: "dc-diesel", color: "#8d6500", axis: "left", unit: "kW", style: "power" },
  { key: "dcDieselMin", metricId: "renewableDcDieselMinKw", field: "dcDieselMinKw", label: "直流柴发下限值", scope: "dc", device: "diesel", deviceLabel: "柴发", curveLabel: "下限", group: "dc-diesel", color: "#8d6500", axis: "left", unit: "kW", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "dcDieselTarget", metricId: "renewableDcDieselTargetKw", field: "dcDieselTargetKw", label: "直流柴发目标值", scope: "dc", device: "diesel", deviceLabel: "柴发", curveLabel: "目标", group: "dc-diesel", color: "#8d6500", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcLoad", metricId: "renewableDcLoadKw", field: "dcLoadKw", label: "直流负荷功率", scope: "dc", device: "load", deviceLabel: "负荷", curveLabel: "功率", group: "dc-load", color: "#d66f3c", axis: "left", unit: "kW", style: "power" },
  { key: "totalRenewableCurrent", metricId: "renewableTotalCurrentKw", field: "totalRenewableCurrentKw", label: "总新能源当前值", scope: "system", device: "renewable", deviceLabel: "新能源", curveLabel: "功率", group: "system-renewable", color: "#1f7a46", axis: "left", unit: "kW", style: "power" },
  { key: "totalRenewableTarget", metricId: "renewableTotalTargetKw", field: "totalRenewableTargetKw", label: "总新能源目标值", scope: "system", device: "renewable", deviceLabel: "新能源", curveLabel: "目标", group: "system-renewable", color: "#1f7a46", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalRenewableMaxAvailable", metricId: "renewableTotalMaxAvailableKw", field: "totalRenewableMaxAvailableKw", label: "总新能源最大可发", scope: "system", device: "renewable", deviceLabel: "新能源", curveLabel: "最大可发", group: "system-renewable", color: "#1f7a46", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "totalWindCurrent", metricId: "renewableTotalWindCurrentKw", field: "totalWindCurrentKw", label: "总风电当前值", scope: "system", device: "wind", deviceLabel: "风电", curveLabel: "功率", group: "system-wind", color: "#0a7774", axis: "left", unit: "kW", style: "power" },
  { key: "totalWindTarget", metricId: "renewableTotalWindTargetKw", field: "totalWindTargetKw", label: "总风电目标值", scope: "system", device: "wind", deviceLabel: "风电", curveLabel: "目标", group: "system-wind", color: "#0a7774", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalWindMaxAvailable", metricId: "renewableTotalWindMaxAvailableKw", field: "totalWindMaxAvailableKw", label: "总风电最大可发", scope: "system", device: "wind", deviceLabel: "风电", curveLabel: "最大可发", group: "system-wind", color: "#0a7774", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "totalPvCurrent", metricId: "renewableTotalPvCurrentKw", field: "totalPvCurrentKw", label: "总光伏当前值", scope: "system", device: "pv", deviceLabel: "光伏", curveLabel: "功率", group: "system-pv", color: "#ba7200", axis: "left", unit: "kW", style: "power" },
  { key: "totalPvTarget", metricId: "renewableTotalPvTargetKw", field: "totalPvTargetKw", label: "总光伏目标值", scope: "system", device: "pv", deviceLabel: "光伏", curveLabel: "目标", group: "system-pv", color: "#ba7200", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalPvMaxAvailable", metricId: "renewableTotalPvMaxAvailableKw", field: "totalPvMaxAvailableKw", label: "总光伏最大可发", scope: "system", device: "pv", deviceLabel: "光伏", curveLabel: "最大可发", group: "system-pv", color: "#ba7200", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "totalGridFollowingStorageCurrent", metricId: "renewableTotalGridFollowingStorageCurrentKw", field: "totalGridFollowingStorageCurrentKw", label: "总跟网储能当前值", scope: "system", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "功率", group: "system-grid-following-storage", color: "#294f95", axis: "left", unit: "kW", style: "power" },
  { key: "totalGridFollowingStorageTarget", metricId: "renewableTotalGridFollowingStorageTargetKw", field: "totalGridFollowingStorageTargetKw", label: "总跟网储能目标值", scope: "system", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "目标", group: "system-grid-following-storage", color: "#294f95", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalGridFollowingStorageSoc", metricId: "renewableTotalGridFollowingStorageSoc", field: "totalGridFollowingStorageSocPercent", label: "总跟网储能SOC", scope: "system", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "SOC", group: "system-grid-following-storage", color: "#294f95", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "totalGridFormingStorageCurrent", metricId: "renewableTotalGridFormingStorageCurrentKw", field: "totalGridFormingStorageCurrentKw", label: "总构网储能当前值", scope: "system", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "功率", group: "system-grid-forming-storage", color: "#674493", axis: "left", unit: "kW", style: "power" },
  { key: "totalGridFormingStorageTarget", metricId: "renewableTotalGridFormingStorageTargetKw", field: "totalGridFormingStorageTargetKw", label: "总构网储能目标值", scope: "system", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "目标", group: "system-grid-forming-storage", color: "#674493", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalGridFormingStorageSoc", metricId: "renewableTotalGridFormingStorageSoc", field: "totalGridFormingStorageSocPercent", label: "总构网储能SOC", scope: "system", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "SOC", group: "system-grid-forming-storage", color: "#674493", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dieselCurrent", metricId: "renewableTotalDieselCurrentKw", field: "totalDieselCurrentKw", label: "总柴发当前值", scope: "system", device: "diesel", deviceLabel: "柴发", curveLabel: "功率", group: "system-diesel", color: "#b87500", axis: "left", unit: "kW", style: "power" },
  { key: "dieselMin", metricId: "renewableTotalDieselMinKw", field: "totalDieselMinKw", label: "总柴发下限值", scope: "system", device: "diesel", deviceLabel: "柴发", curveLabel: "下限", group: "system-diesel", color: "#b87500", axis: "left", unit: "kW", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "dieselTarget", metricId: "renewableTotalDieselTargetKw", field: "totalDieselTargetKw", label: "总柴发目标值", scope: "system", device: "diesel", deviceLabel: "柴发", curveLabel: "目标", group: "system-diesel", color: "#b87500", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalLoad", metricId: "renewableTotalLoadKw", field: "totalLoadKw", label: "总负荷功率", scope: "system", device: "load", deviceLabel: "负荷", curveLabel: "功率", group: "system-load", color: "#a93434", axis: "left", unit: "kW", style: "power" },
  { key: "acdcCurrent", metricId: "renewableAcdcCurrentKw", field: "acdcCurrentKw", label: "AC/DC变流当前值", scope: "system", device: "acdc", deviceLabel: "AC/DC变流器", curveLabel: "功率", group: "system-acdc", color: "#0a8b8b", axis: "left", unit: "kW", style: "power" },
  { key: "acdcTarget", metricId: "renewableAcdcTargetKw", field: "acdcTargetKw", label: "AC/DC变流目标值", scope: "system", device: "acdc", deviceLabel: "AC/DC变流器", curveLabel: "目标", group: "system-acdc", color: "#0a8b8b", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "observedWindSpeed", metricId: "renewableObservedWindSpeed", field: "observedWindSpeed", label: "实时风速", scope: "system", device: "environment", deviceLabel: "环境", curveLabel: "风速", group: "system-environment", color: "#3278b5", axis: "right", unit: "m/s", style: "weather" },
  { key: "observedSolarIrradiance", metricId: "renewableObservedSolarIrradiance", field: "observedSolarIrradiance", label: "实时太阳辐照度", scope: "system", device: "environment", deviceLabel: "环境", curveLabel: "太阳辐照度", group: "system-environment", color: "#d28b16", axis: "right", unit: "W/m²", style: "weather" },
  { key: "electrolyzerCurrent", metricId: "renewableElectrolyzerCurrentKw", field: "electrolyzerCurrentKw", label: "电制氢实时功率", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "功率", group: "hydrogen-electrolyzer", color: "#008678", axis: "left", unit: "kW", style: "power" },
  { key: "electrolyzerTarget", metricId: "renewableElectrolyzerTargetKw", field: "electrolyzerTargetKw", label: "电制氢目标功率", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "目标", group: "hydrogen-electrolyzer", color: "#008678", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "electrolyzerFlowCurrent", metricId: "renewableElectrolyzerFlowCurrentNm3h", field: "electrolyzerFlowCurrentNm3h", label: "实时产氢流量", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "产氢流量", group: "hydrogen-electrolyzer", color: "#18a899", axis: "right", unit: "Nm³/h", style: "flow" },
  { key: "electrolyzerFlowTarget", metricId: "renewableElectrolyzerFlowTargetNm3h", field: "electrolyzerFlowTargetNm3h", label: "目标产氢流量", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "流量目标", group: "hydrogen-electrolyzer", color: "#18a899", axis: "right", unit: "Nm³/h", style: "target", dashed: true },
  { key: "fuelCellCurrent", metricId: "renewableFuelCellCurrentKw", field: "fuelCellCurrentKw", label: "燃料电池实时功率", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "功率", group: "hydrogen-fuel-cell", color: "#c06e00", axis: "left", unit: "kW", style: "power" },
  { key: "fuelCellTarget", metricId: "renewableFuelCellTargetKw", field: "fuelCellTargetKw", label: "燃料电池目标功率", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "目标", group: "hydrogen-fuel-cell", color: "#c06e00", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "fuelCellFlowCurrent", metricId: "renewableFuelCellFlowCurrentNm3h", field: "fuelCellFlowCurrentNm3h", label: "实时耗氢流量", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "耗氢流量", group: "hydrogen-fuel-cell", color: "#e0932f", axis: "right", unit: "Nm³/h", style: "flow" },
  { key: "fuelCellFlowTarget", metricId: "renewableFuelCellFlowTargetNm3h", field: "fuelCellFlowTargetNm3h", label: "目标耗氢流量", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "流量目标", group: "hydrogen-fuel-cell", color: "#e0932f", axis: "right", unit: "Nm³/h", style: "target", dashed: true },
  { key: "hydrogenStoragePressure", metricId: "renewableHydrogenStoragePressureMpa", field: "hydrogenStoragePressureMpa", label: "储氢罐平均压力", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "平均压力", group: "hydrogen-storage", color: "#6358a9", axis: "right", unit: "MPa", style: "pressure" },
  { key: "hydrogenStoragePressureLowGuard", metricId: "renewableHydrogenStoragePressureLowGuardMpa", field: "hydrogenStoragePressureLowGuardMpa", label: "储氢罐平均压力下限保护值", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "压力下限", group: "hydrogen-storage", color: "#6358a9", axis: "right", unit: "MPa", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "hydrogenStoragePressureHighGuard", metricId: "renewableHydrogenStoragePressureHighGuardMpa", field: "hydrogenStoragePressureHighGuardMpa", label: "储氢罐平均压力上限保护值", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "压力上限", group: "hydrogen-storage", color: "#8b55a4", axis: "right", unit: "MPa", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "hydrogenStorageGasQuantity", metricId: "renewableHydrogenStorageGasQuantityNm3", field: "hydrogenStorageGasQuantityNm3", label: "储氢罐总储气量", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "总储气量", group: "hydrogen-storage", color: "#3b6fa1", axis: "right", unit: "Nm³", style: "quantity" },
  { key: "hydrogenStorageSoc", metricId: "renewableHydrogenStorageSoc", field: "hydrogenStorageSocPercent", label: "储氢罐平均SOC", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "平均SOC", group: "hydrogen-storage", color: "#8b55a4", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "hydrogenStorageFlow", metricId: "renewableHydrogenStorageFlowNm3h", field: "hydrogenStorageFlowNm3h", label: "储氢罐净流量", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "净流量", group: "hydrogen-storage", color: "#2d8ba4", axis: "right", unit: "Nm³/h", style: "flow" },
];
const RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES = new Set([
  "acLoad",
  "dcLoad",
  "dieselCurrent",
  "acRenewableCurrent",
  "dcRenewableCurrent",
  "acGridFollowingStorageCurrent",
  "dcGridFollowingStorageCurrent",
  "acGridFormingStorageCurrent",
  "dcGridFormingStorageCurrent",
  "acdcCurrent",
  "totalRenewableMaxAvailable",
]);
const VIRTUAL_TABLE_ROW_HEIGHT = 34;
const VIRTUAL_TABLE_MIN_ROWS = 220;
const VIRTUAL_TABLE_BUFFER_ROWS = 12;
const CURVE_DISPLAY_MODES = {
  hour: { key: "hour", label: "时仿真", pointCount: 3600, stepMinutes: 1 / 60, durationMinutes: 60, tableTitle: "时曲线数据表", tableSummary: "1秒间隔 · 只读" },
  day: { key: "day", label: "日仿真", pointCount: 1440, stepMinutes: 1, durationMinutes: 24 * 60, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 只读" },
  week: { key: "week", label: "周仿真", pointCount: 10080, stepMinutes: 1, durationMinutes: 7 * 24 * 60, tableTitle: "周曲线数据表", tableSummary: "1分钟间隔 · 只读" },
  month: { key: "month", label: "月仿真", pointCount: 720, stepMinutes: 60, durationMinutes: 30 * 24 * 60, tableTitle: "月曲线数据表", tableSummary: "1小时间隔 · 只读" },
  year: { key: "year", label: "年仿真", pointCount: 8760, stepMinutes: 60, durationMinutes: 365 * 24 * 60, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 只读" },
};
const CURVE_DISPLAY_ENV_KEYS = ["wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"];
const CURVE_DISPLAY_META = [
  { key: "wind_speed_mps", label: "风速", color: "#008c8c", min: 0, max: 50, digits: 2, unit: "m/s" },
  { key: "solar_irradiance_w_m2", label: "太阳辐照", color: "#b87500", min: 0, max: 1100, digits: 1, unit: "W/m2" },
  { key: "air_temp_c", label: "气温", color: "#2b6b7f", min: -60, max: 20, digits: 2, unit: "℃" },
];
const CURVE_DISPLAY_LOAD_META = { label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" };
const CURVE_DISPLAY_LOAD_COLORS = ["#c93a3a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_DISPLAY_LOAD_FAMILIES = [
  { key: "electric", label: "电负荷曲线", blocks: ["ACLoad", "DCLoad"], unit: "kW", valueKey: "p_kw" },
  { key: "hydrogen", label: "氢负荷曲线", blocks: ["HydroLoad"], unit: "Nm³/h", valueKey: "flow_set" },
  { key: "heat", label: "热负荷曲线", blocks: ["HeatLoad"], unit: "kW", valueKey: "heat_power" },
];
const CURVE_DISPLAY_SOURCE_FAMILIES = [
  { key: "electric", label: "电源曲线" },
  { key: "hydrogen", label: "氢源曲线" },
  { key: "heat", label: "热源曲线" },
];
const CURVE_DISPLAY_SOURCE_COLORS = ["#126f8a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
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
const RECEIVE_WARNING_LIMIT = 40;

const $ = (id) => document.getElementById(id);
const deviceTreeRenderKeys = new WeakMap();

function activeRuntimeSetting(name) {
  const value = Number(state.webRuntimeSettings?.[name]);
  if (Number.isFinite(value)) return value;
  const configuredDefault = Number(state.webRuntimeDefaults?.[name]);
  if (Number.isFinite(configuredDefault)) return configuredDefault;
  return Number(WEB_RUNTIME_FALLBACKS[name]) || 0;
}

function runtimeParameterGroup(name) {
  return Object.entries(RUNTIME_PARAMETER_GROUPS)
    .find(([, names]) => names.includes(name))?.[0] || "";
}

function runtimeParameterGroupDirty(group) {
  return Boolean(state.webRuntimeDirtyGroups?.[group]);
}

function runtimeParameterGroupValues(values, group) {
  return Object.fromEntries(
    (RUNTIME_PARAMETER_GROUPS[group] || []).map((name) => [name, values?.[name]]),
  );
}

function frontendRefreshIntervalMs() {
  return Math.max(200, activeRuntimeSetting("frontend_refresh_seconds") * 1000);
}

function backendDataRefreshIntervalMs() {
  return Math.max(100, activeRuntimeSetting("backend_refresh_seconds") * 1000);
}

function renewableSimulationControlIntervalError(controlSeconds) {
  const control = Number(controlSeconds);
  if (!Number.isFinite(control) || control < 1) return "自动控制周期必须不少于 1 仿真秒。";
  return "";
}

function syncRenewableControlPeriodConstraints() {
  const input = $("renewableControlPeriod");
  if (!input) return;
  input.min = "1";
  input.step = "0.1";
  input.setCustomValidity(renewableSimulationControlIntervalError(input.value));
}

function frontendRequestTimeoutMs() {
  return Math.max(1000, activeRuntimeSetting("frontend_request_timeout_seconds") * 1000);
}

function receiveStateSyncIntervalMs() {
  return Math.max(500, activeRuntimeSetting("receive_state_sync_seconds") * 1000);
}

function receiveMaxReconnectAttempts() {
  return Math.max(1, Math.round(activeRuntimeSetting("receive_max_reconnect_attempts")));
}

function pageIsHidden() {
  return document.visibilityState === "hidden";
}

function refreshSchedulerIntervalMs() {
  if (pageIsHidden()) return HIDDEN_REFRESH_INTERVAL_MS;
  return state.receiveMode
    ? backendDataRefreshIntervalMs()
    : frontendRefreshIntervalMs();
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
    await refresh();
  } finally {
    const elapsedMs = Date.now() - startedAtMs;
    scheduleNextRefresh(Math.max(0, refreshSchedulerIntervalMs() - elapsedMs));
  }
}

function contextKey(modelId = state.activeModelId) {
  return String(modelId || "__default__");
}

function defaultModelContext(modelId = state.activeModelId) {
  return {
    modelId: contextKey(modelId),
    modelInitialized: false,
    modelInitializedAt: "",
    receiveMode: false,
    frozen: false,
    interactionLink: "",
    teacherApiBase: "",
    teacherModelId: "",
    teacherModelName: "",
    teacherSnapshotPath: "",
    teacherCommandPath: "",
    teacherMeasurementDeltaPath: "",
    teacherDefinitionArchivePath: "",
    lastReceiveAt: "",
    snapshotSource: "",
    lastTeacherSnapshotLogKey: "",
    receiveReconnectAttempts: 0,
    measurementDeltaSeq: 0,
    measurementArrayWarning: "",
    runtimeLogSeq: 0,
    runtimeLogs: [],
    snapshot: null,
    measurementTraceHistory: [],
    lastMeasurementTraceKey: "",
    commandTraceHistory: [],
    renewableTrendHistory: [],
    traceRunId: null,
    traceStepCount: null,
  };
}

function storedContextInitialized(context = {}) {
  if (Object.prototype.hasOwnProperty.call(context, "modelInitialized")) {
    return Boolean(context.modelInitialized);
  }
  return Boolean(
    context.interactionLink
    && (
      context.teacherModelId
      || context.teacherModelName
      || context.teacherApiBase
      || context.teacherSnapshotPath
    )
  );
}

function activeModelContext(modelId = state.activeModelId) {
  const key = contextKey(modelId);
  const stored = state.modelContexts[key] || {};
  return {
    ...defaultModelContext(modelId),
    ...stored,
    modelInitialized: storedContextInitialized(stored),
  };
}

function serializableModelContext(context) {
  return {
    modelInitialized: Boolean(context.modelInitialized),
    modelInitializedAt: context.modelInitializedAt || "",
    receiveMode: Boolean(context.receiveMode),
    frozen: Boolean(context.frozen),
    interactionLink: context.interactionLink || "",
    teacherApiBase: context.teacherApiBase || "",
    teacherModelId: context.teacherModelId || "",
    teacherModelName: context.teacherModelName || "",
    teacherSnapshotPath: context.teacherSnapshotPath || "",
    teacherCommandPath: context.teacherCommandPath || "",
    teacherMeasurementDeltaPath: context.teacherMeasurementDeltaPath || "",
    teacherDefinitionArchivePath: context.teacherDefinitionArchivePath || "",
    lastReceiveAt: context.lastReceiveAt || "",
  };
}

function persistModelContextsToStorage() {
  const payload = {};
  Object.entries(state.modelContexts || {}).forEach(([key, context]) => {
    payload[key] = serializableModelContext(context || {});
  });
  const serialized = JSON.stringify(payload);
  if (serialized === lastPersistedModelContextsJson) return false;
  localStorage.setItem(MODEL_CONTEXTS_STORAGE_KEY, serialized);
  lastPersistedModelContextsJson = serialized;
  return true;
}

function captureActiveModelContext(overrides = {}) {
  return {
    ...activeModelContext(),
    modelInitialized: state.modelInitialized,
    modelInitializedAt: state.modelInitializedAt,
    receiveMode: state.receiveMode,
    frozen: state.frozen,
    interactionLink: state.interactionLink,
    teacherApiBase: state.teacherApiBase,
    teacherModelId: state.teacherModelId,
    teacherModelName: state.teacherModelName,
    teacherSnapshotPath: state.teacherSnapshotPath,
    teacherCommandPath: state.teacherCommandPath,
    teacherMeasurementDeltaPath: state.teacherMeasurementDeltaPath,
    teacherDefinitionArchivePath: state.teacherDefinitionArchivePath,
    lastReceiveAt: state.lastReceiveAt,
    snapshotSource: state.snapshotSource,
    lastTeacherSnapshotLogKey: state.lastTeacherSnapshotLogKey,
    receiveReconnectAttempts: state.receiveReconnectAttempts,
    measurementDeltaSeq: state.measurementDeltaSeq,
    measurementArrayWarning: state.measurementArrayWarning,
    runtimeLogSeq: state.runtimeLogSeq,
    runtimeLogs: state.runtimeLogs,
    snapshot: state.snapshot,
    measurementTraceHistory: state.measurementTraceHistory,
    lastMeasurementTraceKey: state.lastMeasurementTraceKey,
    commandTraceHistory: state.commandTraceHistory,
    renewableTrendHistory: state.renewableTrendHistory,
    traceRunId: state.traceRunId,
    traceStepCount: state.traceStepCount,
    ...overrides,
  };
}

function flushModelContextPersistence() {
  if (modelContextPersistTimerId !== null) {
    window.clearTimeout(modelContextPersistTimerId);
    modelContextPersistTimerId = null;
  }
  persistModelContextsToStorage();
  lastModelContextPersistAtMs = Date.now();
}

function persistActiveModelContext(overrides = {}, immediate = false) {
  if (!state.activeModelId) return;
  state.modelContexts[contextKey()] = captureActiveModelContext(overrides);
  if (immediate) {
    flushModelContextPersistence();
    return;
  }
  if (modelContextPersistTimerId !== null) return;
  const elapsed = Date.now() - lastModelContextPersistAtMs;
  const delay = Math.max(0, MODEL_CONTEXT_PERSIST_INTERVAL_MS - elapsed);
  modelContextPersistTimerId = window.setTimeout(flushModelContextPersistence, delay);
}

window.addEventListener("pagehide", flushModelContextPersistence);

function restoreModelContext(modelId = state.activeModelId) {
  const context = activeModelContext(modelId);
  state.modelInitialized = Boolean(context.modelInitialized);
  state.modelInitializedAt = context.modelInitializedAt || "";
  state.receiveMode = Boolean(context.receiveMode);
  state.frozen = Boolean(context.frozen);
  state.interactionLink = context.interactionLink || "";
  state.teacherApiBase = (context.teacherApiBase || "").replace(/\/$/, "");
  state.teacherModelId = context.teacherModelId || "";
  state.teacherModelName = context.teacherModelName || "";
  state.teacherSnapshotPath = context.teacherSnapshotPath || "";
  state.teacherCommandPath = context.teacherCommandPath || "";
  state.teacherMeasurementDeltaPath = context.teacherMeasurementDeltaPath || "";
  state.teacherDefinitionArchivePath = context.teacherDefinitionArchivePath || "";
  state.lastReceiveAt = context.lastReceiveAt || "";
  state.snapshotSource = context.snapshotSource || "";
  state.lastTeacherSnapshotLogKey = context.lastTeacherSnapshotLogKey || "";
  state.receiveReconnectAttempts = Number(context.receiveReconnectAttempts) || 0;
  state.measurementDeltaSeq = Number(context.measurementDeltaSeq) || 0;
  state.measurementArrayWarning = context.measurementArrayWarning || "";
  state.runtimeLogSeq = Number(context.runtimeLogSeq) || 0;
  state.runtimeLogs = Array.isArray(context.runtimeLogs) ? context.runtimeLogs : [];
  state.snapshot = traineeMeasurementOnlySnapshot(context.snapshot || null);
  state.measurementTraceHistory = traineeMeasurementOnlyTraceHistory(context.measurementTraceHistory);
  state.lastMeasurementTraceKey = context.lastMeasurementTraceKey || "";
  state.commandTraceHistory = Array.isArray(context.commandTraceHistory) ? context.commandTraceHistory : [];
  state.renewableTrendHistory = Array.isArray(context.renewableTrendHistory) ? context.renewableTrendHistory : [];
  state.traceRunId = context.traceRunId ?? null;
  state.traceStepCount = context.traceStepCount ?? null;
}

function receiveContextFromBackend(payload = {}) {
  return {
    modelInitialized: Boolean(payload.initialized ?? payload.model_initialized ?? payload.modelInitialized),
    modelInitializedAt: payload.initialized_at || payload.initializedAt || "",
    receiveMode: Boolean(payload.active ?? payload.receiveMode),
    frozen: Boolean(payload.frozen),
    interactionLink: payload.interaction_link || payload.interactionLink || "",
    teacherApiBase: (payload.teacher_api_base || payload.teacherApiBase || "").replace(/\/$/, ""),
    teacherModelId: payload.teacher_model_id || payload.teacherModelId || "",
    teacherModelName: payload.teacher_model_name || payload.teacherModelName || "",
    teacherSnapshotPath: payload.snapshot_path || payload.snapshotPath || "",
    teacherCommandPath: payload.command_path || payload.commandPath || "",
    teacherMeasurementDeltaPath: payload.measurement_delta_path || payload.measurementDeltaPath || "",
    teacherDefinitionArchivePath: payload.definition_archive_path || payload.definitionArchivePath || "",
    lastReceiveAt: payload.last_receive_at || payload.lastReceiveAt || "",
  };
}

function receiveStatePayloadFromContext(context, overrides = {}) {
  const merged = { ...context, ...overrides };
  return {
    initialized: Boolean(merged.initialized ?? merged.modelInitialized),
    initialized_at: merged.initializedAt || merged.modelInitializedAt || merged.initialized_at || "",
    active: Boolean(merged.active ?? merged.receiveMode),
    frozen: Boolean(merged.frozen),
    interaction_link: merged.interactionLink || merged.interaction_link || "",
    teacher_api_base: merged.teacherApiBase || merged.teacher_api_base || "",
    teacher_model_id: merged.teacherModelId || merged.teacher_model_id || state.activeModelId || "",
    teacher_model_name: merged.teacherModelName || merged.teacher_model_name || merged.teacherModelName || "",
    snapshot_path: merged.teacherSnapshotPath || merged.snapshot_path || "",
    command_path: merged.teacherCommandPath || merged.command_path || "",
    measurement_delta_path: merged.teacherMeasurementDeltaPath || merged.measurement_delta_path || "",
    definition_archive_path: merged.teacherDefinitionArchivePath || merged.definition_archive_path || "",
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
  if (!force && Date.now() - state.lastReceiveStateSyncAtMs < receiveStateSyncIntervalMs()) return;
  state.receiveStateSyncActive = true;
  state.lastReceiveStateSyncAtMs = Date.now();
  const previousReceiveMode = state.receiveMode;
  const previousLink = state.interactionLink;
  const previousInitialized = state.modelInitialized;
  const previousInitializedAt = state.modelInitializedAt;
  try {
    await syncActiveReceiveStateFromBackend(state.activeModelId);
    if (
      state.modelInitialized !== previousInitialized
      || state.modelInitializedAt !== previousInitializedAt
    ) {
      state.localDefinitionSnapshot = null;
      state.localDefinitionModelId = "";
      state.snapshot = null;
      state.measurementDeltaSeq = 0;
      invalidateManualDefinitionChanges();
      clearStaticSnapshotCacheForModel(state.activeModelId);
    }
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

function chartLegendHiddenSet(chartKey) {
  const hidden = state.chartLegendSeriesHidden?.[chartKey] || [];
  return new Set(hidden);
}

function isChartLegendSeriesHidden(chartKey, seriesKey) {
  return chartLegendHiddenSet(chartKey).has(seriesKey);
}

function visibleChartLegendSeries(chartKey, seriesDefs) {
  return (seriesDefs || []).filter((series) => !isChartLegendSeriesHidden(chartKey, series.key));
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

function setChartSeriesVisibility(chartKey, seriesKey, visible, drawFn) {
  if (!chartKey || !seriesKey) return;
  const hidden = chartHiddenSet(chartKey);
  if (visible) hidden.delete(seriesKey);
  else hidden.add(seriesKey);
  state.chartSeriesHidden = { ...(state.chartSeriesHidden || {}), [chartKey]: Array.from(hidden) };
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function toggleChartSeriesVisibility(chartKey, seriesKey, drawFn) {
  setChartSeriesVisibility(chartKey, seriesKey, isChartSeriesHidden(chartKey, seriesKey), drawFn);
}

function setChartLegendSeriesVisibility(chartKey, seriesKey, visible, drawFn) {
  if (!chartKey || !seriesKey) return;
  const hidden = chartLegendHiddenSet(chartKey);
  if (visible) hidden.delete(seriesKey);
  else hidden.add(seriesKey);
  state.chartLegendSeriesHidden = {
    ...(state.chartLegendSeriesHidden || {}),
    [chartKey]: Array.from(hidden),
  };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function toggleChartLegendSeriesVisibility(chartKey, seriesKey, drawFn) {
  setChartLegendSeriesVisibility(
    chartKey,
    seriesKey,
    isChartLegendSeriesHidden(chartKey, seriesKey),
    drawFn,
  );
}

function syncChartLegendButtons(chartKey) {
  document.querySelectorAll(`[data-chart-toggle="${chartKey}"]`).forEach((control) => {
    const seriesKey = control.dataset.chartSeries || "";
    const isLegendVisibilityControl = control.dataset.chartLegendVisibility === "true";
    const hidden = isLegendVisibilityControl
      ? isChartLegendSeriesHidden(chartKey, seriesKey)
      : isChartSeriesHidden(chartKey, seriesKey);
    const selected = !isLegendVisibilityControl && selectedChartSeriesKey(chartKey) === seriesKey;
    if (control.matches('input[type="checkbox"]')) {
      control.checked = !hidden;
      const item = control.closest(".renewable-trend-series-item");
      item?.classList.toggle("is-hidden", hidden);
      item?.classList.toggle("is-selected", selected);
      return;
    }
    control.classList.toggle("is-hidden", hidden);
    control.classList.toggle("is-selected", selected);
    control.setAttribute("aria-pressed", hidden ? "false" : "true");
    const legendLabel = control.dataset.chartLegendLabel || "";
    if (legendLabel) {
      const actionLabel = hidden ? "点击显示曲线" : "点击隐藏曲线";
      control.title = `${legendLabel}：${actionLabel}`;
      control.setAttribute("aria-label", `${legendLabel}，${actionLabel}`);
    }
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

function drawInlineChartCursorLabels(ctx, canvas, plot, x, samples, options = {}) {
  const ratio = options.ratio || 1;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const valueFormatter = options.valueFormatter || formatNumber;
  const maxSeries = Math.max(1, Number(options.maxSeries) || 10);
  const labelHeight = 18 * ratio;
  const labelGap = 12 * ratio;
  const laneGap = 8 * ratio;
  ctx.font = `${11 * ratio}px Microsoft YaHei, Arial`;
  const labels = samples.slice(0, maxSeries).map(({ series, point }) => {
    const valueText = `${valueFormatter(point.value)}${series.unit ? ` ${series.unit}` : ""}`;
    const text = `${series.label}: ${valueText}`;
    return {
      series,
      point,
      text,
      width: ctx.measureText(text).width + 18 * ratio,
    };
  });
  if (!labels.length) return;

  const maxLabelWidth = Math.max(...labels.map((label) => label.width));
  const laneStride = maxLabelWidth + laneGap;
  const rightSpace = right - x - labelGap;
  const leftSpace = x - left - labelGap;
  const occupiedLanes = { left: [], right: [] };

  const findPlacement = (label, side) => {
    const availableSpace = side === "right" ? rightSpace : leftSpace;
    if (availableSpace < label.width) return null;
    const laneCount = Math.max(1, Math.floor((availableSpace + laneGap) / laneStride));
    for (let lane = 0; lane < laneCount; lane += 1) {
      const laneYs = occupiedLanes[side][lane] || [];
      if (laneYs.some((previousY) => Math.abs(previousY - label.point.y) < labelHeight + 2 * ratio)) continue;
      const labelX = side === "right"
        ? x + labelGap + lane * laneStride
        : x - labelGap - label.width - lane * laneStride;
      if (labelX < left + 2 * ratio || labelX + label.width > right - 2 * ratio) continue;
      occupiedLanes[side][lane] = [...laneYs, label.point.y];
      return { side, labelX };
    }
    return null;
  };

  const placements = labels.map((label) => {
    const rightFits = rightSpace >= label.width;
    const leftFits = leftSpace >= label.width;
    const preferredSide = rightFits && !leftFits
      ? "right"
      : leftFits && !rightFits
        ? "left"
        : rightSpace >= leftSpace
          ? "right"
          : "left";
    const secondarySide = preferredSide === "right" ? "left" : "right";
    const placement = findPlacement(label, preferredSide) || findPlacement(label, secondarySide);
    if (placement) return { ...label, ...placement };
    const fallbackSide = rightSpace >= label.width || rightSpace >= leftSpace ? "right" : "left";
    const unclampedX = fallbackSide === "right" ? x + labelGap : x - labelGap - label.width;
    return {
      ...label,
      side: fallbackSide,
      labelX: clamp(unclampedX, left + 2 * ratio, right - label.width - 2 * ratio),
    };
  });

  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  placements.forEach(({ series, point, text, side, labelX }) => {
    const connectorStartX = point.x + (side === "right" ? 6 : -6) * ratio;
    const connectorEndX = side === "right" ? labelX - 3 * ratio : labelX + ctx.measureText(text).width + 17 * ratio;
    ctx.strokeStyle = series.color;
    ctx.globalAlpha = 0.72;
    ctx.lineWidth = 1 * ratio;
    ctx.beginPath();
    ctx.moveTo(connectorStartX, point.y);
    ctx.lineTo(connectorEndX, point.y);
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.fillStyle = series.color;
    ctx.beginPath();
    ctx.arc(labelX + 5 * ratio, point.y, 3 * ratio, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = 3 * ratio;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.96)";
    ctx.strokeText(text, labelX + 12 * ratio, point.y);
    ctx.fillStyle = "#24373f";
    ctx.fillText(text, labelX + 12 * ratio, point.y);
  });

  const timeLabel = String(options.timeLabel || "").trim();
  if (timeLabel) {
    const text = `时刻: ${timeLabel}`;
    ctx.font = `${11 * ratio}px Consolas, Microsoft YaHei, Arial`;
    const textWidth = ctx.measureText(text).width;
    const preferredX = x + labelGap + textWidth <= right ? x + labelGap : x - labelGap - textWidth;
    const textX = clamp(preferredX, left + 2 * ratio, right - textWidth - 2 * ratio);
    const textY = top + 11 * ratio;
    ctx.lineWidth = 3 * ratio;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.98)";
    ctx.strokeText(text, textX, textY);
    ctx.fillStyle = "#344b54";
    ctx.fillText(text, textX, textY);
  }
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
  const selectedKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const snapshot = chartCursorSnapshot(visibleSeries, selectedKey, clamp(cursor.x, left, right));
  if (!snapshot) return;
  const { anchorPoint: mainPoint, samples } = snapshot;
  const x = clamp(mainPoint.x, left, right);
  const y = clamp(mainPoint.y, top, bottom);
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
  if (!options.inlineSeriesLabels) {
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
  }
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

  if (options.inlineSeriesLabels) {
    drawInlineChartCursorLabels(ctx, canvas, plot, x, samples, {
      ratio,
      maxSeries,
      timeLabel,
      valueFormatter,
    });
    ctx.restore();
    return;
  }

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
  "/manual-changes": "manual-changes",
  "/parameters": "parameters",
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
    if (target === "renewable") refreshRenewableControlState({ preview: false });
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

function recordFrontendRequestDiagnostics(path, response, durationMs) {
  const diagnostics = state.frontendDiagnostics;
  const responseBytes = Math.max(0, Number(response?.headers?.get?.("Content-Length")) || 0);
  diagnostics.requestCount += 1;
  diagnostics.responseBytes += responseBytes;
  diagnostics.requestDurationMs += Math.max(0, Number(durationMs) || 0);
  if (/\/api\/(?:trainee\/)?snapshot(?:\?|$)/.test(String(path || ""))) {
    diagnostics.snapshotRequestCount += 1;
    diagnostics.snapshotResponseBytes += responseBytes;
  }
}

async function api(path, options = {}) {
  const {
    modelScoped = true,
    timeoutMs = frontendRequestTimeoutMs(),
    signal: callerSignal,
    ...fetchOptions
  } = options;
  const targetPath = modelScoped ? modelScopedPath(path) : path;
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
    const response = await fetch(`${apiBase}${targetPath}`, {
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
  state.webRuntimeSavingGroup = "";
  state.webRuntimeDirtyGroups = { backend: false, web: false };
  state.webRuntimeErrors = { load: "", backend: "", web: "" };
}

function runtimeSettingDisplay(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(3)));
}

function runtimeParameterGroupStatus(group) {
  if (state.webRuntimeLoading) return "加载中";
  if (state.webRuntimeSavingGroup === group) return "保存中";
  const error = state.webRuntimeErrors?.[group] || state.webRuntimeErrors?.load || "";
  if (error) return `失败：${error}`;
  return runtimeParameterGroupDirty(group) ? "有未保存修改" : "已生效";
}

function renderWebRuntimeSettings() {
  const root = state.pageSections?.parameters || document;
  root.querySelectorAll?.("[data-runtime-setting]").forEach((input) => {
    const name = input.dataset.runtimeSetting || "";
    const group = runtimeParameterGroup(name);
    const values = runtimeParameterGroupDirty(group) ? state.webRuntimeDraft : state.webRuntimeSettings;
    const value = Number(values?.[name]);
    if (Number.isFinite(value) && document.activeElement !== input) input.value = String(value);
    const constraint = state.webRuntimeConstraints?.[name] || {};
    if (constraint.min !== undefined) input.min = String(constraint.min);
    if (constraint.max !== undefined) input.max = String(constraint.max);
    input.disabled = state.webRuntimeLoading || Boolean(state.webRuntimeSavingGroup);
  });
  Object.entries(WEB_RUNTIME_CURRENT_IDS).forEach(([name, id]) => {
    const node = runtimeParameterElement(id);
    if (node) node.textContent = runtimeSettingDisplay(state.webRuntimeSettings?.[name]);
  });
  const activeModel = state.models.find((model) => model.id === state.activeModelId);
  const modelName = activeModel?.name || state.snapshot?.model?.name || state.activeModelId || "--";
  const valuesById = {
    runtimeParameterModelName: modelName,
    runtimeParameterUpdatedAt: state.webRuntimeUpdatedAt || "尚未保存（使用默认值）",
    runtimeParameterFrontendRefreshState: `${runtimeSettingDisplay(activeRuntimeSetting("frontend_refresh_seconds"))} s`,
    runtimeParameterBackendRefreshState: `${runtimeSettingDisplay(activeRuntimeSetting("backend_refresh_seconds"))} s`,
    runtimeParameterFrontendTimeoutState: `${runtimeSettingDisplay(activeRuntimeSetting("frontend_request_timeout_seconds"))} s`,
    runtimeParameterBackendTimeoutState: `${runtimeSettingDisplay(activeRuntimeSetting("backend_request_timeout_seconds"))} s`,
    runtimeParameterReceiveState: state.receiveMode ? "正在接收" : "未启动接收",
  };
  Object.entries(valuesById).forEach(([id, text]) => {
    const node = runtimeParameterElement(id);
    if (node) node.textContent = text;
  });
  const backendStatus = runtimeParameterGroupStatus("backend");
  const webStatus = runtimeParameterGroupStatus("web");
  const backendSummary = runtimeParameterElement("backendRuntimeParameterSummary");
  const webSummary = runtimeParameterElement("runtimeParameterSummary");
  if (backendSummary) backendSummary.textContent = backendStatus;
  if (webSummary) webSummary.textContent = webStatus;
  const backendState = runtimeParameterElement("backendRuntimeParameterState");
  const webState = runtimeParameterElement("webRuntimeParameterState");
  if (backendState) backendState.textContent = backendStatus;
  if (webState) webState.textContent = webStatus;
  const stateNode = runtimeParameterElement("runtimeParameterState");
  if (stateNode) stateNode.textContent = `后台：${backendStatus} · WEB：${webStatus}`;

  const saving = Boolean(state.webRuntimeSavingGroup);
  const buttonGroups = {
    backend: {
      save: "saveBackendRuntimeParameters",
      undo: "undoBackendRuntimeParameters",
      defaults: "restoreBackendRuntimeParameterDefaults",
    },
    web: {
      save: "saveRuntimeParameters",
      undo: "undoRuntimeParameters",
      defaults: "restoreRuntimeParameterDefaults",
    },
  };
  Object.entries(buttonGroups).forEach(([group, ids]) => {
    const dirty = runtimeParameterGroupDirty(group);
    const saveButton = runtimeParameterElement(ids.save);
    const undoButton = runtimeParameterElement(ids.undo);
    const defaultsButton = runtimeParameterElement(ids.defaults);
    if (saveButton) saveButton.disabled = !dirty || state.webRuntimeLoading || saving;
    if (undoButton) undoButton.disabled = !dirty || state.webRuntimeLoading || saving;
    if (defaultsButton) defaultsButton.disabled = state.webRuntimeLoading || saving;
  });
}

function applyWebRuntimeSettings() {
  state.runtimeLogPageSize = Math.max(5, Math.round(activeRuntimeSetting("runtime_log_page_size")));
  const logLimit = Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit")));
  state.runtimeLogs = state.runtimeLogs.slice(0, logLimit);
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
  state.commandTraceHistory = compactTraceHistory(state.commandTraceHistory, state.commandTraceWindowMinutes);
  state.renewableTrendHistory = compactTraceHistory(state.renewableTrendHistory, state.renewableTrendWindowMinutes);
  restartRefreshScheduler();
}

async function loadWebRuntimeSettings(force = false) {
  const modelId = state.activeModelId;
  if (!modelId) return null;
  if (!force && state.webRuntimeLoadedModelId === modelId) {
    renderWebRuntimeSettings();
    return state.webRuntimeSettings;
  }
  state.webRuntimeLoading = true;
  state.webRuntimeErrors = { load: "", backend: "", web: "" };
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
    state.webRuntimeDirtyGroups = { backend: false, web: false };
    applyWebRuntimeSettings();
    return payload;
  } catch (error) {
    if (modelId === state.activeModelId) state.webRuntimeErrors.load = apiErrorText(error);
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
  const group = runtimeParameterGroup(name);
  if (!name || !group) return;
  const value = Number(input.value);
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    [name]: Number.isFinite(value) ? value : input.value,
  };
  state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: true };
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
}

async function saveWebRuntimeSettings(group = "web") {
  if (!RUNTIME_PARAMETER_GROUPS[group] || state.webRuntimeSavingGroup || !runtimeParameterGroupDirty(group)) return;
  const pendingDraft = { ...state.webRuntimeDraft };
  state.webRuntimeSavingGroup = group;
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
  try {
    const payload = await api("/api/runtime-settings", {
      method: "POST",
      body: JSON.stringify({ settings: runtimeParameterGroupValues(pendingDraft, group) }),
    });
    state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS, ...(payload.settings || {}) };
    state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS, ...(payload.defaults || {}) };
    state.webRuntimeConstraints = payload.constraints || {};
    state.webRuntimeDraft = { ...state.webRuntimeSettings };
    Object.keys(RUNTIME_PARAMETER_GROUPS).forEach((otherGroup) => {
      if (otherGroup === group || !runtimeParameterGroupDirty(otherGroup)) return;
      Object.assign(
        state.webRuntimeDraft,
        runtimeParameterGroupValues(pendingDraft, otherGroup),
      );
    });
    state.webRuntimeUpdatedAt = payload.updatedAt || "";
    state.webRuntimeLoadedModelId = state.activeModelId;
    state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: false };
    applyWebRuntimeSettings();
  } catch (error) {
    state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: apiErrorText(error) };
  } finally {
    state.webRuntimeSavingGroup = "";
    renderWebRuntimeSettings();
  }
}

function undoWebRuntimeSettings(group = "web") {
  if (!RUNTIME_PARAMETER_GROUPS[group]) return;
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    ...runtimeParameterGroupValues(state.webRuntimeSettings, group),
  };
  state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: false };
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
}

function restoreWebRuntimeDefaults(group = "web") {
  if (!RUNTIME_PARAMETER_GROUPS[group]) return;
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    ...runtimeParameterGroupValues(state.webRuntimeDefaults, group),
  };
  state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: true };
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
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
            <input type="checkbox" data-manual-change-select-all aria-label="选择全部人工修改" ${allSelected ? "checked" : ""} />
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
                <input type="checkbox" data-manual-change-id="${escapeHtml(changeId)}" aria-label="选择 ${escapeHtml(change.object_label || change.object_name || changeId)}" ${checked ? "checked" : ""} />
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
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
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
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
    renderSnapshot(state.snapshot || {});
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
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
    renderSnapshot(state.snapshot || {});
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
  "diagram": ["files", "source_files", "work_files", "definitions", "diagram"],
  "curves": ["files", "source_files", "work_files", "definitions", "curves"],
  "measurements": ["files", "source_files", "work_files", "definitions"],
  "commands": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "renewable": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "manual-changes": ["definitions", "device_parameters"],
  "parameters": [],
  "history": [],
};
const CACHEABLE_STATIC_KEYS = STATIC_SNAPSHOT_KEYS.filter((key) => key !== "curves");
let staticCacheStoreMemory = null;

function staticSnapshotKeysForPage(page = currentPageName()) {
  return STATIC_SNAPSHOT_KEYS_BY_PAGE[page] || STATIC_SNAPSHOT_KEYS;
}

function hasStaticSnapshotPayload(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return Boolean(snapshot && requiredKeys.every((key) => snapshot[key] !== undefined));
}

function frozenSnapshotNeedsBootstrap(snapshot, page = currentPageName()) {
  return Boolean(
    state.frozen
    && !hasStaticSnapshotPayload(snapshot, staticSnapshotKeysForPage(page))
  );
}

function staticMetaSignature(meta) {
  return JSON.stringify(meta || null);
}

function staticMetaMatches(left, right) {
  return staticMetaSignature(left) === staticMetaSignature(right);
}

function staticCacheModelKey(snapshot = state.snapshot || {}) {
  const modelId = String(state.activeModelId || snapshot?.model?.id || "");
  if (!modelId) return "";
  return `local|${modelId}`;
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

function clearStaticSnapshotCacheForModel(modelId = state.activeModelId) {
  const key = `local|${String(modelId || "")}`;
  if (key === "local|") return;
  const store = readStaticCacheStore();
  if (!(key in store)) return;
  delete store[key];
  writeStaticCacheStore(store);
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

function traineeMeasurementOnlySnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return snapshot;
  const projected = { ...snapshot };
  if (snapshot.measurements && typeof snapshot.measurements === "object") {
    projected.measurements = {
      ...snapshot.measurements,
      value_channels: ["scada"],
    };
    delete projected.measurements.real;
  }
  if (snapshot.measurement_delta && typeof snapshot.measurement_delta === "object") {
    projected.measurement_delta = {
      ...snapshot.measurement_delta,
      value_channels: ["scada"],
    };
    delete projected.measurement_delta.real_values;
    if (Array.isArray(projected.measurement_delta.items)) {
      projected.measurement_delta.items = projected.measurement_delta.items.map((rawItem) => {
        if (!rawItem || typeof rawItem !== "object") return rawItem;
        const item = { ...rawItem, value: rawItem.scada_value };
        delete item.real_value;
        return item;
      });
    }
  }
  if (snapshot.measurement_history && typeof snapshot.measurement_history === "object") {
    projected.measurement_history = {
      ...snapshot.measurement_history,
      value_channels: ["scada"],
      frames: Array.isArray(snapshot.measurement_history.frames)
        ? snapshot.measurement_history.frames.map((rawFrame) => {
          if (!rawFrame || typeof rawFrame !== "object") return rawFrame;
          const frame = { ...rawFrame };
          delete frame.real_values;
          return frame;
        })
        : snapshot.measurement_history.frames,
    };
    delete projected.measurement_history.real_values;
  }
  return projected;
}

function traineeMeasurementOnlyTraceHistory(history) {
  if (!Array.isArray(history)) return [];
  return history.map((rawPoint) => {
    if (!rawPoint || typeof rawPoint !== "object") return rawPoint;
    const measurements = Object.fromEntries(
      Object.entries(rawPoint.measurements || {}).map(([key, rawMeasurement]) => {
        if (!rawMeasurement || typeof rawMeasurement !== "object") return [key, rawMeasurement];
        const measurement = {
          ...rawMeasurement,
          value: rawMeasurement.scada ?? null,
          scada: rawMeasurement.scada ?? null,
        };
        delete measurement.real;
        delete measurement.real_value;
        return [key, measurement];
      }),
    );
    return { ...rawPoint, measurements };
  });
}

function mergeSnapshot(previous, incoming) {
  const safePrevious = traineeMeasurementOnlySnapshot(previous);
  const safeIncoming = traineeMeasurementOnlySnapshot(incoming);
  if (!safePrevious || !safeIncoming) return safeIncoming;
  const merged = { ...safePrevious, ...safeIncoming };
  const previousModelId = String(safePrevious.model?.id || "");
  const incomingModelId = String(safeIncoming.model?.id || "");
  const modelChanged = Boolean(previousModelId && incomingModelId && previousModelId !== incomingModelId);
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (safeIncoming[key] !== undefined) return;
    const incomingMeta = safeIncoming.static_meta?.[key];
    const previousMeta = safePrevious.static_meta?.[key];
    const revisionChanged = Boolean(
      incomingMeta
      && previousMeta
      && !staticMetaMatches(incomingMeta, previousMeta)
    );
    if (modelChanged || revisionChanged) {
      delete merged[key];
      return;
    }
    if (safePrevious[key] !== undefined) merged[key] = safePrevious[key];
  });
  if (modelChanged && safeIncoming.device_states === undefined) delete merged.device_states;
  if (safeIncoming.runtime_logs === undefined) delete merged.runtime_logs;
  return merged;
}

function pageNeedsRuntimeLogs(page = currentPageName()) {
  return ["overview", "history"].includes(page);
}

function snapshotLogLimit(page = currentPageName()) {
  return page === "history" ? 300 : 20;
}

function pageNeedsMeasurementDelta(page = currentPageName()) {
  return ["overview", "diagram", "commands", "measurements", "renewable"].includes(page);
}

function pageNeedsDevices(page = currentPageName()) {
  return ["overview", "model", "diagram", "commands", "renewable"].includes(page);
}

function pageNeedsDeviceStates(page = currentPageName()) {
  return page === "diagram";
}

function pageNeedsCommands(page = currentPageName()) {
  return ["overview", "diagram", "commands", "renewable"].includes(page);
}

function pageNeedsCommandHistory(page = currentPageName()) {
  return page === "commands";
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
  const compactDeviceRuntime = !Array.isArray(forceStaticKeys) && canUseCompactDeviceRuntime(page);
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
  return "/api/snapshot";
}

function teacherReceiveAddress() {
  if (state.interactionLink) return state.interactionLink;
  const base = state.teacherApiBase || "";
  const path = teacherSnapshotPath();
  if (!base) return path;
  return connectionApiUrl({ teacherApiBase: base }, path);
}

function teacherSnapshotPollAddress(page = currentPageName(), forceStaticKeys = null) {
  void forceStaticKeys;
  const params = new URLSearchParams();
  const compactDeviceRuntime = canUseCompactDeviceRuntime(page);
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("device_states", pageNeedsDeviceStates(page) ? "1" : "0");
  if (compactDeviceRuntime) {
    params.set("devices", "1");
    params.set("device_states", "1");
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
  if (pageNeedsRuntimeLogs(page)) params.set("log_limit", String(snapshotLogLimit(page)));
  else params.set("logs", "0");
  params.set("static", "0");
  params.set("static_meta", "0");
  params.set("lite", "1");
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
  return appendUrlQuery("/api/trainee/measurements/delta", {
    after_seq: state.measurementDeltaSeq,
    compact: 1,
  });
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
      + `量测=${payload.scada_values?.length ?? "非数组"}，`
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
  const currentScada = Array.isArray(measurements.scada) ? measurements.scada : [];
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
  delete measurements.real;
  measurements.value_channels = ["scada"];
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
    measurements.scada = [];
    delete measurements.real;
  }
  const definitionsByName = new Map(definitions.map((row) => [measurementNameKey(row), row]));
  const channelIndexes = { scada: measurementChannelIndex(measurements.scada || []) };
  let changed = false;
  compactMeasurementDeltaItems(payload).forEach((item) => {
    if (!item?.name) return;
    const definition = definitionsByName.get(item.name);
    if (item.deleted) {
      ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada);
      changed = true;
      return;
    }
    const scadaRow = item.scada_value !== undefined && item.scada_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada)
      : null;
    if (scadaRow) {
      scadaRow.value = item.scada_value;
      scadaRow.valid = definition?.valid ?? item.valid ?? scadaRow.valid;
      scadaRow.weight = definition?.weight ?? item.weight ?? scadaRow.weight;
      scadaRow.updated_simu_time = item.updated_simu_time;
      scadaRow.updated_wall_time = item.updated_wall_time;
      scadaRow.updated_absolute_minute = item.updated_absolute_minute;
      changed = true;
    }
  });
  measurements.scada = Array.from(channelIndexes.scada.values());
  measurements.value_channels = ["scada"];
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
    const payload = state.receiveMode
      ? await api(teacherMeasurementDeltaAddress())
      : await api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}&compact=1`);
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
  return Boolean(state.modelInitialized && state.interactionLink && state.teacherCommandPath && state.teacherApiBase);
}

async function postTeacherCommand(body) {
  if (!hasTeacherCommandConnection()) {
    throw new Error("请先完成顶部“模型初始化”并启动接收后再下发指令。");
  }
  return await teacherCommandApi({ method: "POST", body: JSON.stringify(body) });
}

function commandCycleMinutes(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const pointCount = Number(curves.point_count);
  const stepMinutes = Number(curves.time_step_minutes || CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)].stepMinutes);
  const curvePeriod = pointCount * stepMinutes;
  if (Number.isFinite(curvePeriod) && curvePeriod > 0) return curvePeriod;
  return CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)]?.durationMinutes || CURVE_DISPLAY_MODES.day.durationMinutes;
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

const DIAGRAM_DISPLAY_PREFERENCES_KEY = "trainee.svgDisplayPreferences.v1";
const DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS = Object.freeze({
  measurements: true,
  labels: true,
  flowArrows: true,
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
  };
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
  const kind = String(targetKind || "").trim();
  if (kind === "device") return "command";
  return kind ? "ignore" : "fit";
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
  return [point?.value, point?.scada].some((value) => (
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
  const scadaByDevice = new Map();
  (measurements.scada || []).forEach((row) => {
    addDiagramMeasurementAliases(scada, row);
    addDiagramDeviceMeasurement(scadaByDevice, row);
  });
  return {
    scada,
    scadaByDevice,
    couplingEndpoints: diagramCouplingMeasurementEndpoints(snapshot),
  };
}

function diagramMetricBindingValue(binding, maps) {
  const measurementDevice = diagramCouplingMeasurementEndpoint(binding, maps, binding?.metricType);
  if (!measurementDevice) return null;
  const candidates = diagramMetricMeasurementTypes(measurementDevice?.devType, binding?.metricType);
  for (const measType of candidates) {
    const key = diagramDeviceMeasurementKey(measurementDevice.devType, measurementDevice.devName, measType);
    if (maps.scadaByDevice?.has(key)) return maps.scadaByDevice.get(key);
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
  if (channel === "control") return maps.controls.get(key) || null;
  return maps.scada.get(key) || null;
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
  const namedMetric = target.closest("[data-meas-name], [data-scada-name]");
  if (namedMetric && container.contains(namedMetric)) {
    const name = namedMetric.getAttribute("data-meas-name")
      || namedMetric.getAttribute("data-scada-name")
      || "";
    if (name) {
      return {
        kind: "metric",
        key: `named-metric:scada:${name}`,
        element: namedMetric,
        channel: "scada",
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
  "isl", "run_stat", "status", "pv0", "qv0",
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
    && !name.startsWith("idx_")
    && !name.endsWith("_set");
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
      return [...rows.scada, ...rows.definitions]
        .some((row) => diagramMeasurementIdentityMatches(row, candidateIdentity));
    }) || candidates[0] || hover.binding.metricType;
    identity = {
      devType: hover.binding.devType,
      devName: hover.binding.devName,
      measType,
    };
  }
  const scadaRow = rows.scada.find((row) => diagramMeasurementIdentityMatches(row, identity)) || null;
  const channelRow = scadaRow;
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
  const weightNumber = Number(definition?.weight ?? channelRow?.weight);
  const validNumber = Number(definition?.valid ?? channelRow?.valid ?? 1);
  const weight = Number.isFinite(weightNumber) ? weightNumber : null;
  const status = diagramMeasurementStatus(
    definition?.status ?? channelRow?.status,
    validNumber,
  );
  const fixedValueNumber = Number(definition?.fixed_value ?? channelRow?.fixed_value);
  return {
    definition,
    scadaRow,
    row: scadaRow || definition,
    name: String(definition?.name || channelRow?.name || identity?.name || ""),
    devType: String(definition?.dev_type || channelRow?.dev_type || identity?.devType || ""),
    devName: String(definition?.dev_name || channelRow?.dev_name || identity?.devName || ""),
    measType: String(definition?.meas_type || channelRow?.meas_type || identity?.measType || ""),
    scadaValue,
    valid: validNumber === 0 ? 0 : 1,
    status,
    fixedValue: Number.isFinite(fixedValueNumber) ? fixedValueNumber : null,
    weight,
    errorSigma: diagramDefinitionSigmaFromWeight(weight),
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
    ["definitions", "scada"].forEach((channel) => {
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
  [snapshot?.measurements?.scada].forEach((rows) => {
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
  invalidateManualDefinitionChanges();
  const record = result.record;
  const patchSnapshot = (snapshot) => {
    if (!snapshot) return false;
    const changed = record.block_name
      ? patchDiagramModelDefinitionRecord(snapshot, record)
      : patchDiagramMeasurementDefinitionRecord(snapshot, record);
    const runtimeChanged = patchDiagramRuntimeControlRecord(snapshot, result.runtime_control);
    if (result.static_meta) {
      snapshot.static_meta = {
        ...(snapshot.static_meta || {}),
        ...result.static_meta,
      };
    }
    return changed || runtimeChanged;
  };
  const changed = patchSnapshot(state.snapshot);
  if (state.localDefinitionSnapshot && state.localDefinitionSnapshot !== state.snapshot) {
    patchSnapshot(state.localDefinitionSnapshot);
  }
  persistStaticSnapshotCache(state.snapshot, currentPageName());
  return changed;
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
  const runStatValue = traineeRuntimeSignalDisplayValue(live, "run_stat", live?.run_stat ?? raw.run_stat);
  const switchStatusValue = traineeRuntimeSignalDisplayValue(live, "status", live?.status ?? raw.status);
  const statusRows = [
    ["运行状态", runStatValue, "status:run_stat", runStatBinding],
    ...(hasSwitchStatus
      ? [["开关状态", switchStatusValue, "status:status", statusBinding]]
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
    <div class="diagram-definition-actions diagram-definition-inline-actions" data-diagram-definition-actions="device">
      <button type="button" data-diagram-definition-cancel>取消</button>
      <button type="button" class="primary" data-diagram-definition-save="device" ${canSave ? "" : "disabled"}>
        ${interaction?.definitionSaving ? "保存中" : "保存"}
      </button>
    </div>
    ${diagramDefinitionEditorMessageHtml(interaction)}`;
}

function renderDiagramDeviceDefinitionValueRow(record, field, activeEditor, interaction) {
  const key = `definition:${record.blockName}:${record.rowIndex}:${field}`;
  const fieldEditable = diagramDeviceParameterEditable(field);
  const editable = Boolean(activeEditor && fieldEditable);
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
  const editor = interaction?.definitionEditor?.kind === "device"
    ? interaction.definitionEditor
    : null;
  const activeRecord = editor
    ? records.find((record) => diagramDeviceDefinitionRecordEditor(editor, record))
    : null;
  const content = activeRecord
    ? renderDiagramDeviceDefinitionEditor(activeRecord, editor, interaction)
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
      <span>设备参数</span>
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
  const requestedModelId = state.activeModelId;
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
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
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
        ? `${completed} 个参数块及运行控制覆盖已保存，新能源控制将从下一轮采用新参数`
        : `${completed} 个参数块的人工覆盖已保存，新能源控制将从下一轮采用新参数`);
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
  const dynamicBody = tooltip.querySelector("[data-diagram-device-dynamic-body]");
  if (!dynamicBody) return false;
  const title = tooltip.querySelector("[data-diagram-tooltip-device-name]");
  if (title) title.textContent = data.title;
  const dynamicUpdated = syncDiagramTooltipSections(dynamicBody, data.dynamicSections);
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
    const identitySection = dynamicBody.querySelector('[data-diagram-tooltip-section="identity"]');
    const definitionHtml = renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction);
    if (definitionHtml) {
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
    if (scada === null) return null;
    return {
      minute: Number(point.minute),
      time: point.sim_time || point.time || "--",
      scada,
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
    const hasScada = scada !== null;
    if (!hasScada) return null;
    return {
      minute: Number(point.minute),
      time: point.time || "--",
      x: xForMinute(point.minute),
      scada: hasScada ? scada : null,
      scadaY: hasScada ? yForValue(scada) : null,
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
    </div>
    <svg class="diagram-trend-chart" data-diagram-trend-chart viewBox="0 0 ${model.width} ${model.height}" role="img" aria-label="${model.period === "day" ? "日曲线" : "小时曲线"}"${model.empty ? " hidden" : ""}>
      <text x="${model.plot.left}" y="12" class="diagram-trend-axis-unit" data-diagram-trend-unit>${escapeHtml(model.unit)}</text>
      <g data-diagram-trend-axis-ticks>${diagramTrendAxisTicksHtml(model)}</g>
      <line x1="${model.plot.left}" y1="${model.plot.top}" x2="${model.plot.left}" y2="${model.height - model.plot.bottom}" class="diagram-trend-y-axis"></line>
      <polyline class="diagram-trend-series is-scada" data-diagram-trend-series="scada" points="${model.series.scada.polyline}" fill="none" vector-effect="non-scaling-stroke"></polyline>
      <line x1="0" y1="${model.plot.top}" x2="0" y2="${model.height - model.plot.bottom}" class="diagram-trend-cursor diagram-trend-cursor-line" data-diagram-trend-cursor data-diagram-trend-cursor-line visibility="hidden"></line>
      <circle cx="0" cy="0" r="3.5" class="diagram-trend-cursor diagram-trend-cursor-point is-scada" data-diagram-trend-cursor data-diagram-trend-cursor-point="scada" visibility="hidden"></circle>
      <g class="diagram-trend-cursor diagram-trend-cursor-label" data-diagram-trend-cursor data-diagram-trend-cursor-label visibility="hidden">
        <rect width="136" height="34" rx="4" ry="4"></rect>
        <text x="7" y="13" data-diagram-trend-cursor-time>--</text>
        <text x="7" y="27" data-diagram-trend-cursor-value="scada">--</text>
      </g>
    </svg>
    <div class="diagram-trend-range" data-diagram-trend-range${model.empty ? " hidden" : ""}><span data-diagram-trend-range-start>${escapeHtml(model.labels.start)}</span><span data-diagram-trend-range-end>${escapeHtml(model.labels.end)}</span></div>
    <div class="diagram-trend-stats" data-diagram-trend-stats${model.empty ? " hidden" : ""}>
      <div><span class="diagram-trend-stat-label is-scada">量测值</span><span>最小 <strong data-diagram-trend-stat-scada-min>${model.series.scada.min === null ? "--" : diagramNumberText(model.series.scada.min)}</strong></span><span>最大 <strong data-diagram-trend-stat-scada-max>${model.series.scada.max === null ? "--" : diagramNumberText(model.series.scada.max)}</strong></span><span>最新 <strong data-diagram-trend-stat-scada-latest>${model.series.scada.latest === null ? "--" : diagramNumberText(model.series.scada.latest)}</strong></span></div>
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
  const labelHeight = 34;
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
  const unit = row?.unit || diagramMeasurementUnit(row?.meas_type || metricType);
  const period = interaction.trendPeriod === "day" ? "day" : "hour";
  const history = diagramTrendHistorySeries(pair.scadaRow || row, metricType);
  const endMinute = Number(snapshot?.clock?.absolute_minute ?? snapshot?.clock?.minute);
  const requestedOffset = Number(interaction?.trendPeriodOffsets?.[period]) || 0;
  const trendRange = diagramTrendNavigationRange(
    history,
    period,
    Number.isFinite(endMinute) ? endMinute : null,
    requestedOffset,
    curveDisplayModeDurationMinutes(),
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
    valid: pair.valid,
    status: pair.status,
    statusText: validText,
    fixedValue: pair.fixedValue,
    fixedValueText: pair.fixedValue === null ? "--" : diagramNumberText(pair.fixedValue),
    unit: String(unit || ""),
    validText,
    weight: pair.weight,
    weightText: pair.weight === null ? "--" : String(pair.weight),
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
  const row = pair.scadaRow || pair.row || diagramMetricCurrentRow(container, hover, snapshot);
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

function renderDiagramMeasurementStatusOptions(selected) {
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
  const weightValue = editing
    ? `<input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="weight" data-diagram-measurement-weight type="number" min="0" step="any" value="${escapeHtml(editor.draft.weight)}" ${interaction?.definitionSaving ? "disabled" : ""}>`
    : `<span data-diagram-measurement-weight>${escapeHtml(data.weightText)}</span>`;
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
        <dt>量测状态</dt>
        <dd data-diagram-tooltip-validity ${measurementEditableAttr}>${statusValue}</dd>
      </div>
      <div>
        <dt>误差 σ</dt>
        <dd ${measurementEditableAttr}>${sigmaValue}</dd>
      </div>
      <div>
        <dt>权重</dt>
        <dd ${measurementEditableAttr}>${weightValue}</dd>
      </div>
      ${fixedValueCell}
    </dl>
    ${editing ? renderDiagramMeasurementDefinitionEditor(editor, interaction) : ""}`;
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
  const nextStatus = diagramMeasurementStatus(editor.draft.status, editor.original?.valid);
  editor.draft.status = nextStatus;
  const nextFixedValue = Number(editor.draft.fixedValue);
  let error = "";
  if (!Number.isFinite(nextSigma) || nextSigma <= 0) error = "误差 σ 必须大于 0";
  else if (!Number.isFinite(nextWeight) || nextWeight <= 0) error = "权重必须大于 0";
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
    <div class="diagram-definition-actions diagram-measurement-definition-editor" data-diagram-definition-actions="measurement">
      <button type="button" data-diagram-definition-cancel>取消</button>
      <button type="button" class="primary" data-diagram-definition-save="measurement" ${canSave ? "" : "disabled"}>
        ${interaction?.definitionSaving ? "保存中" : "保存"}
      </button>
    </div>
    ${diagramDefinitionEditorMessageHtml(interaction, editor.validationError)}`;
}

function beginDiagramMeasurementDefinitionEdit(container) {
  const interaction = diagramInteractionState(container);
  const snapshot = interaction.snapshot || state.snapshot || {};
  const data = diagramMetricTooltipData(container, interaction.hover, snapshot, interaction);
  if (!data.definition || !data.measurementName) return false;
  const originalWeight = data.weight === null ? String(data.definition.weight ?? "") : String(data.weight);
  const originalSigma = data.errorSigma === null ? "" : String(data.errorSigma);
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
      status: data.status,
      fixedValue: data.fixedValue === null ? "" : String(data.fixedValue),
      valid: String(data.valid),
    },
    draft: {
      weight: originalWeight,
      errorSigma: originalSigma,
      status: data.status,
      fixedValue: data.fixedValue === null ? "" : String(data.fixedValue),
      valid: String(data.valid),
    },
    dirtyFields: new Set(),
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
  if (!["errorSigma", "weight", "status", "fixedValue"].includes(field)) return false;
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
  const requestedModelId = state.activeModelId;
  interaction.definitionSaving = true;
  interaction.definitionMessage = "正在更新学员台后台定义并保存人工覆盖层";
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
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
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
      interaction.definitionMessage = result.warning || "学员台后台定义已更新，但人工覆盖层保存未完成，请重试";
      interaction.definitionMessageWarning = true;
      renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
      return false;
    }
    interaction.definitionEditor = null;
    interaction.definitionMessage = resultWarning
      ? (result.warning || "学员台后台定义已更新，但人工覆盖层保存未完成，请重试")
      : "学员台后台定义及人工覆盖层已保存";
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
      <span data-diagram-tooltip-metric-label>${escapeHtml(data.metricLabel)}</span>
    </div>
    <div class="diagram-metric-current" data-diagram-measurement-summary>
      ${renderDiagramMeasurementSummary(data, editor, interaction)}
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
    ["[data-diagram-measurement-valid]", data.validText],
    ["[data-diagram-measurement-sigma]", data.errorSigmaText],
    ["[data-diagram-measurement-weight]", data.weightText],
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
    if (action === "ignore") return;
    hideDiagramTooltip(container);
    if (action === "command") {
      const devId = diagramTargetDeviceId(container, target);
      openDiagramDeviceCommandForSvgDevice(container, devId);
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (!fitDiagramViewport(viewport)) return;
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
    const nextValue = !diagramDisplayPreferences[key];
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
      diagramBindingValue(name, maps, "scada"),
    );
  });
  bindings.scada.forEach(({ element, name }) => {
    setDiagramElementValue(element, diagramBindingValue(name, maps, "scada"));
  });
  bindings.real.forEach(({ element, name }) => {
    setDiagramElementValue(element, null);
  });
  bindings.controls.forEach(({ element, name }) => {
    setDiagramElementValue(element, diagramBindingValue(name, maps, "control"));
  });
  bindings.metrics.forEach((binding) => {
    setDiagramElementValue(
      binding.element,
      diagramMetricBindingValue(binding, maps),
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
  if (state.receiveMode) return;
  const dialog = $("receiveLinkDialog");
  const input = $("receiveLinkInput");
  if (!dialog || !input) return;
  input.value = state.interactionLink || localStorage.getItem("polarTeacherInteractionLink") || "";
  setReceiveLinkMessage(`远端定义将覆盖当前本地模型：${state.activeModelId || "--"}。`);
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

function teacherConnectionFromPayload(payload = {}, fallbackLink = "") {
  const connection = payload.connection || payload.receive_state || payload;
  const fallbackUrl = fallbackLink ? normalizeConnectionUrl(fallbackLink) : null;
  const modelId = connection.model_id || connection.teacher_model_id || connection.modelId || connection.teacherModelId
    || fallbackUrl?.searchParams.get("model_id") || "";
  return {
    link: connection.link || connection.interaction_link || fallbackUrl?.href || "",
    teacherApiBase: String(
      connection.teacher_api_base || connection.teacherApiBase || fallbackUrl?.origin || "",
    ).replace(/\/$/, ""),
    modelId: String(modelId),
    modelName: String(connection.model_name || connection.teacher_model_name || connection.modelName || modelId),
    snapshotPath: String(connection.snapshot_path || connection.snapshotPath || `/api/snapshot?model_id=${encodeURIComponent(modelId)}`),
    commandPath: String(connection.command_path || connection.commandPath || `/api/student/commands?model_id=${encodeURIComponent(modelId)}`),
    measurementDeltaPath: String(
      connection.measurement_delta_path || connection.measurementDeltaPath || measurementDeltaPathFromSnapshotPath(
        connection.snapshot_path || connection.snapshotPath || `/api/snapshot?model_id=${encodeURIComponent(modelId)}`,
      ),
    ),
    definitionArchivePath: String(
      connection.definition_archive_path
      || connection.definitionArchivePath
      || `/api/export-definitions?format=json&model_id=${encodeURIComponent(modelId)}`,
    ),
  };
}

function connectionApiUrl(connection, path) {
  const target = String(path || "");
  if (/^https?:\/\//i.test(target)) return target;
  const normalized = target.startsWith("/") ? target : `/${target}`;
  return `${connection.teacherApiBase}${normalized}`;
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

async function ensureLocalDefinitionSnapshot(modelId = state.activeModelId) {
  const targetModelId = String(modelId || "");
  if (state.localDefinitionSnapshot && state.localDefinitionModelId === targetModelId) {
    return { modelId: targetModelId, snapshot: state.localDefinitionSnapshot };
  }
  const local = await fetchLocalDefinitionSnapshot(targetModelId);
  state.localDefinitionSnapshot = local.snapshot;
  state.localDefinitionModelId = local.modelId;
  return local;
}

async function reloadLocalDefinitionSnapshotAfterEdit(modelId = state.activeModelId) {
  const requestedModelId = String(modelId || state.activeModelId || "");
  const runtimeSnapshot = state.snapshot;
  const local = await fetchLocalDefinitionSnapshot(requestedModelId);
  if (requestedModelId !== String(state.activeModelId || "")) return false;
  state.localDefinitionSnapshot = local.snapshot;
  state.localDefinitionModelId = local.modelId;
  state.snapshot = state.receiveMode && runtimeSnapshot
    ? mergeTeacherSnapshotWithLocalDefinitions(runtimeSnapshot, runtimeSnapshot)
    : mergeSnapshot(runtimeSnapshot, local.snapshot);
  clearStaticSnapshotCacheForModel(requestedModelId);
  persistStaticSnapshotCache(state.snapshot, currentPageName());
  return true;
}

function traineeRuntimeSignalKey(devType, devName, measType = "") {
  return [
    normalizeDiagramMeasurementToken(devType),
    String(devName || "").trim(),
    normalizeDiagramMeasurementToken(measType),
  ].join("\u0000");
}

function traineeRuntimeSignalField(measType) {
  const token = normalizeDiagramMeasurementToken(measType);
  if (token === "RUN_STAT") return "run_stat";
  if (token === "STATUS") return "status";
  return "";
}

function traineeRuntimeSignalValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? (number > 0.5 ? 1 : 0) : null;
}

function traineeRuntimeSignalDisplayValue(device, field, fallback = "--") {
  const signal = device?.runtime_signals?.[field];
  if (!signal) return fallback;
  const value = traineeRuntimeSignalValue(signal.value);
  if (value === null) return signal.valid === false ? "--（遥信无效）" : fallback;
  return signal.valid === false || signal.stale ? `${value}（遥信无效）` : value;
}

function applyTraineeObservedRuntimeSignals(snapshot = {}) {
  const devices = Array.isArray(snapshot.devices) ? snapshot.devices : [];
  const deviceStates = Array.isArray(snapshot.device_states) ? snapshot.device_states : [];
  const scadaRows = Array.isArray(snapshot.measurements?.scada) ? snapshot.measurements.scada : [];
  const observedByKey = new Map();

  scadaRows.forEach((row) => {
    const field = traineeRuntimeSignalField(row?.meas_type);
    const devType = String(row?.dev_type || "").trim();
    const devName = String(row?.dev_name || "").trim();
    if (!field || !devType || !devName) return;
    const value = traineeRuntimeSignalValue(row?.value);
    const valid = Number(row?.valid ?? 1) !== 0 && value !== null;
    observedByKey.set(traineeRuntimeSignalKey(devType, devName, row.meas_type), {
      field,
      value,
      valid,
      stale: !valid,
      updated_simu_time: row?.updated_simu_time ?? null,
      updated_wall_time: row?.updated_wall_time ?? null,
      updated_absolute_minute: row?.updated_absolute_minute ?? null,
    });
  });

  const deviceByKey = new Map();
  devices.forEach((device) => {
    const devType = String(device?.dev_type || "").trim();
    const devName = String(device?.dev_name || device?.name || "").trim();
    if (!devType || !devName) return;
    const deviceKey = traineeRuntimeSignalKey(devType, devName);
    deviceByKey.set(deviceKey, device);
    const runtimeSignals = { ...(device.runtime_signals || {}) };

    ["RUN_STAT", "STATUS"].forEach((measType) => {
      const field = traineeRuntimeSignalField(measType);
      const observed = observedByKey.get(traineeRuntimeSignalKey(devType, devName, measType));
      const previous = runtimeSignals[field];
      if (observed?.valid) {
        runtimeSignals[field] = observed;
        device[field] = observed.value;
        return;
      }
      if (observed && previous && traineeRuntimeSignalValue(previous.value) !== null) {
        runtimeSignals[field] = {
          ...previous,
          valid: false,
          stale: true,
          updated_simu_time: observed.updated_simu_time,
          updated_wall_time: observed.updated_wall_time,
          updated_absolute_minute: observed.updated_absolute_minute,
        };
        device[field] = traineeRuntimeSignalValue(previous.value);
        return;
      }
      if (observed) {
        runtimeSignals[field] = observed;
        return;
      }
      if (previous && traineeRuntimeSignalValue(previous.value) !== null) {
        device[field] = traineeRuntimeSignalValue(previous.value);
      }
    });

    if (Object.keys(runtimeSignals).length) device.runtime_signals = runtimeSignals;
  });

  deviceStates.forEach((deviceState) => {
    const devType = String(deviceState?.dev_type || "").trim();
    const devName = String(deviceState?.dev_name || deviceState?.name || "").trim();
    if (!devType || !devName) return;
    const device = deviceByKey.get(traineeRuntimeSignalKey(devType, devName));
    const cached = device?.runtime_signals?.run_stat;
    const observed = observedByKey.get(traineeRuntimeSignalKey(devType, devName, "RUN_STAT"));
    if (observed?.valid) {
      deviceState.run_stat = observed.value;
      return;
    }
    const cachedValue = traineeRuntimeSignalValue(cached?.value);
    if (cachedValue !== null) deviceState.run_stat = cachedValue;
  });

  return snapshot;
}

function mergeTeacherRuntimeDevices(localDevices = [], remoteDevices = []) {
  const remoteByKey = new Map((remoteDevices || []).map((device) => ([
    `${String(device?.dev_type || "").trim()}\u0000${String(device?.dev_name || device?.name || "").trim()}`,
    device,
  ])));
  const runtimeFields = ["run_stat", "status", "mode", "set_values", "soc_curr", "runtime_signals"];
  return (localDevices || []).map((localDevice) => {
    const key = `${String(localDevice?.dev_type || "").trim()}\u0000${String(localDevice?.dev_name || localDevice?.name || "").trim()}`;
    const remoteDevice = remoteByKey.get(key);
    if (!remoteDevice) return localDevice;
    const mergedDevice = { ...localDevice };
    runtimeFields.forEach((field) => {
      if (remoteDevice[field] !== undefined) mergedDevice[field] = remoteDevice[field];
    });
    return mergedDevice;
  });
}

function mergeTeacherMeasurementsWithLocalDefinitions(remoteMeasurements = {}, localDefinitionRows = []) {
  const typedKey = (item) => [
    String(item?.dev_type || "").trim().toUpperCase(),
    String(item?.dev_name || "").trim(),
    String(item?.meas_type || "").trim().toUpperCase(),
  ].join("\u0000");
  const localByName = new Map();
  const localByType = new Map();
  (localDefinitionRows || []).forEach((definition) => {
    const name = String(definition?.name || "").trim();
    const key = typedKey(definition);
    if (name) localByName.set(name, definition);
    if (key !== "\u0000\u0000") localByType.set(key, definition);
  });
  const mergeChannel = (rows) => (rows || []).map((item) => {
    const name = String(item?.name || "").trim();
    const definition = (name ? localByName.get(name) : null) || localByType.get(typedKey(item));
    if (!definition) return item;
    return {
      ...item,
      valid: definition?.valid ?? item.valid,
      weight: definition?.weight ?? item.weight,
    };
  });
  const merged = {
    ...(remoteMeasurements || {}),
    definitions: localDefinitionRows || [],
    scada: mergeChannel(remoteMeasurements?.scada),
    value_channels: ["scada"],
  };
  delete merged.real;
  return merged;
}

function mergeTeacherSnapshotWithLocalDefinitions(previousSnapshot, remoteSnapshot) {
  const localDefinitions = state.localDefinitionSnapshot || {};
  const merged = mergeSnapshot(previousSnapshot || localDefinitions, remoteSnapshot || {});
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (localDefinitions[key] !== undefined) merged[key] = localDefinitions[key];
  });
  if (localDefinitions.model) merged.model = localDefinitions.model;
  if (localDefinitions.devices) {
    merged.devices = mergeTeacherRuntimeDevices(localDefinitions.devices, merged.devices);
  }
  const localMeasurementDefinitions = localDefinitions.definitions?.measurement
    || localDefinitions.measurements?.definitions
    || [];
  merged.measurements = mergeTeacherMeasurementsWithLocalDefinitions(
    merged.measurements,
    localMeasurementDefinitions,
  );
  if (localDefinitions.static_meta) merged.static_meta = localDefinitions.static_meta;
  return merged;
}

function applyTeacherConnection(connection) {
  state.interactionLink = connection.link;
  state.teacherApiBase = (connection.teacherApiBase || "").replace(/\/$/, "");
  state.teacherModelId = connection.modelId;
  state.teacherModelName = connection.modelName;
  state.teacherSnapshotPath = connection.snapshotPath;
  state.teacherCommandPath = connection.commandPath;
  state.teacherMeasurementDeltaPath = connection.measurementDeltaPath;
  state.teacherDefinitionArchivePath = connection.definitionArchivePath;
  state.measurementDeltaSeq = 0;
  persistActiveModelContext({}, true);
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
  state.receiveTransportFailureCount = 0;
  state.receiveTransportInterrupted = false;
}

function isTraineeWebTransportError(error) {
  const name = String(error?.name || "").trim().toLowerCase();
  const message = String(error?.message || error || "").trim().toLowerCase();
  return name === "typeerror" && (
    message.includes("failed to fetch")
    || message.includes("networkerror")
    || message.includes("network error")
    || message.includes("network request failed")
    || message.includes("load failed")
  );
}

function recordTraineeWebTransportIssue(error) {
  state.receiveTransportFailureCount += 1;
  state.receiveTransportInterrupted = true;
  const attempt = state.receiveTransportFailureCount;
  const logInterval = receiveMaxReconnectAttempts();
  if (attempt === 1 || attempt % logInterval === 0) {
    addRuntimeLog(
      "实时交互",
      "学员台WEB后台 /api/trainee/snapshot",
      "后台重连",
      [
        `本机学员台WEB后台暂不可用：${apiErrorText(error)}`,
        `已连续重试 ${attempt} 次；不主动停止接收，后台恢复后自动续接`,
      ],
      "warn",
      true,
    );
  }
  renderReceiveMode(`后台重连中 ${attempt}`);
}

function finishTraineeWebTransportRecovery(simTime = "") {
  if (!state.receiveTransportInterrupted) return;
  const attempts = state.receiveTransportFailureCount;
  state.receiveTransportFailureCount = 0;
  state.receiveTransportInterrupted = false;
  addRuntimeLog(
    "实时交互",
    "学员台WEB后台 /api/trainee/snapshot",
    "后台恢复",
    [`本机WEB后台访问已恢复`, `中断期间自动重试 ${attempts} 次，接收状态未被主动关闭`],
    "ok",
    true,
    simTime,
  );
}

function stopReceiveAfterPersistentIssue(result, detail = [], simTime = "") {
  const detailItems = Array.isArray(detail) ? detail.filter(Boolean) : [detail].filter(Boolean);
  const maxAttempts = receiveMaxReconnectAttempts();
  state.receiveMode = false;
  state.frozen = true;
  state.receiveEpoch += 1;
  state.receiveRequestActive = false;
  persistActiveModelContext({ receiveMode: false, frozen: true }, true);
  setTraineeReceiveActive(state.activeModelId, false).catch((error) => {
    addRuntimeLog("接收模式", "学员台服务端", "保存保护状态失败", apiErrorText(error), "warn");
  });
  addRuntimeLog(
    "实时交互",
    "接收保护",
    "停止接收",
    [`连续 ${maxAttempts} 次接收异常`, ...detailItems],
    "error",
    true,
    simTime,
  );
  noteRenewableReceiveInterruption("连续接收异常，新能源实时控制已暂停，接收恢复后将自动恢复。");
  renderReceiveMode(result || "接收异常");
  openReceiveWarningDialog(
    `${result || "接收异常"}，已停止接收`,
    [`已连续 ${maxAttempts} 次发现接收异常。`, ...detailItems],
    "请检查模拟台仿真状态、交互链接和定义文件一致性。",
  );
}

function recordReceiveIssue(type, target, result, detail = "", simTime = "") {
  state.receiveReconnectAttempts += 1;
  const attempt = state.receiveReconnectAttempts;
  const maxAttempts = receiveMaxReconnectAttempts();
  const detailItems = Array.isArray(detail) ? detail.filter(Boolean) : [detail].filter(Boolean);
  addRuntimeLog(
    type,
    target,
    result,
    [`连续告警 ${attempt}/${maxAttempts}`, ...detailItems],
    "warn",
    true,
    simTime,
  );
  if (attempt >= maxAttempts) {
    stopReceiveAfterPersistentIssue(result, detailItems, simTime);
    return false;
  }
  renderReceiveMode(`告警 ${attempt}/${maxAttempts}`);
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

function isSimulationFrozenSnapshot(snapshot = state.snapshot) {
  const simulationState = String(snapshot?.clock?.state || "").trim().toLowerCase();
  return ["paused", "stopped"].includes(simulationState);
}

function acceptTeacherSnapshot(snapshot, epoch = state.receiveEpoch) {
  if (!state.receiveMode || epoch !== state.receiveEpoch) return false;
  state.snapshotSource = "teacher";
  const clock = snapshot.clock || {};
  finishTraineeWebTransportRecovery(clock.time || "--");
  if (isSimulationFrozenSnapshot(snapshot)) {
    resetReceiveIssueStreak();
    state.lastReceiveAt = new Date().toLocaleTimeString();
    renderSnapshot(snapshot);
    renderReceiveMode();
    return true;
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
  const maxAttempts = receiveMaxReconnectAttempts();
  renderReceiveMode(`重连中 ${attempt}/${maxAttempts}`);
  try {
    await ensureLocalDefinitionSnapshot(state.activeModelId);
    const remoteSnapshot = applyDeviceRuntimePayload(
      state.snapshot,
      await teacherSnapshotApi(currentPageName()),
    );
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    state.embeddedMeasurementDeltaReceived = false;
    const embeddedMeasurementDelta = remoteSnapshot?.measurement_delta || null;
    if (remoteSnapshot?.measurement_delta) delete remoteSnapshot.measurement_delta;
    const snapshot = mergeTeacherSnapshotWithLocalDefinitions(state.snapshot, remoteSnapshot);
    state.snapshot = snapshot;
    if (embeddedMeasurementDelta) {
      snapshot.measurement_delta = embeddedMeasurementDelta;
      applyEmbeddedMeasurementDelta(snapshot);
    }
    if (pageNeedsMeasurementDelta(currentPageName()) && !state.embeddedMeasurementDeltaReceived) {
      await refreshMeasurementDelta(false);
    }
    if (acceptTeacherSnapshot(snapshot, epoch)) {
      addRuntimeLog("实时交互", "模拟台实时链路", "重连成功", `模型 ${state.teacherModelName}`, "ok");
    }
  } catch (error) {
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    if (isTraineeWebTransportError(error)) {
      recordTraineeWebTransportIssue(error);
      return;
    }
    renderReceiveMode(`重连等待 ${attempt}/${maxAttempts}`);
  }
}

async function setTraineeReceiveActive(modelId, active) {
  const result = await api("/api/trainee/receive", {
    method: "POST",
    modelScoped: false,
    body: JSON.stringify({ model_id: modelId, active }),
  });
  mergeBackendReceiveState(modelId, result, contextKey(modelId) === contextKey());
  return result;
}

async function startReceiveMode() {
  if (!state.modelInitialized) {
    addRuntimeLog("接收模式", "当前本地模型", "启动接收失败", "请先完成模型初始化。", "warn");
    renderReceiveMode("等待模型初始化");
    return;
  }
  const activeModelIdBeforeReceive = state.activeModelId;
  try {
    const local = await ensureLocalDefinitionSnapshot(activeModelIdBeforeReceive);
    state.snapshot = local.snapshot;
    state.measurementDeltaSeq = 0;
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
    state.commandTraceHistory = [];
    resetChartPeriodOffsets("commandTrace");
    state.renewableTrendHistory = [];
    resetChartPeriodOffsets("renewableTrend");
    state.lastReceiveAt = "";
    state.snapshotSource = "";
    state.lastTeacherSnapshotLogKey = "";
    persistActiveModelContext({}, true);
    drawMeasurementTraceChart();
    drawCommandTraceChart();
    drawRenewableTrendChart();
    await setTraineeReceiveActive(activeModelIdBeforeReceive, true);
    state.receiveMode = true;
    state.frozen = false;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    persistActiveModelContext({}, true);
    addRuntimeLog(
      "接收模式",
      "模拟台实时链路",
      "启动接收",
      `模型 ${state.teacherModelName || state.teacherModelId}；接收地址 ${teacherReceiveAddress()}`,
      "ok",
    );
    renderReceiveMode();
    await refreshRenewableControlState({ preview: false, render: currentPageName() === "renewable" });
    await refreshFromTeacher(state.receiveEpoch);
  } catch (error) {
    addRuntimeLog("接收模式", "模拟台实时链路", "启动接收失败", apiErrorText(error), "warn");
    renderReceiveMode(apiErrorText(error));
  }
}

async function initializeModelFromLink() {
  const input = $("receiveLinkInput");
  const confirmButton = $("confirmReceiveLink");
  if (!input || !confirmButton) return;
  const activeModelIdBeforeInitialize = state.activeModelId;
  confirmButton.disabled = true;
  setReceiveLinkMessage("正在下载并覆盖当前本地模型定义。");
  try {
    const normalizedLink = normalizeConnectionUrl(input.value).href;
    const result = await api("/api/trainee/model-initialize", {
      method: "POST",
      modelScoped: false,
      body: JSON.stringify({
        model_id: activeModelIdBeforeInitialize,
        link: normalizedLink,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : state.models);
    mergeBackendReceiveState(activeModelIdBeforeInitialize, result.receive_state || {}, true);
    const connection = teacherConnectionFromPayload(result, normalizedLink);
    applyTeacherConnection(connection);
    state.activeModelId = activeModelIdBeforeInitialize;
    localStorage.setItem("polarTraineeModelId", activeModelIdBeforeInitialize);
    state.modelInitialized = true;
    state.modelInitializedAt = result.receive_state?.initialized_at || state.modelInitializedAt;
    state.receiveMode = false;
    state.frozen = false;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    state.measurementDeltaSeq = 0;
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
    state.commandTraceHistory = [];
    resetChartPeriodOffsets("commandTrace");
    state.renewableTrendHistory = [];
    resetChartPeriodOffsets("renewableTrend");
    state.lastReceiveAt = "";
    state.snapshot = null;
    state.snapshotSource = "local";
    state.localDefinitionSnapshot = null;
    state.localDefinitionModelId = "";
    invalidateManualDefinitionChanges();
    state.lastTeacherSnapshotLogKey = "";
    clearStaticSnapshotCacheForModel(activeModelIdBeforeInitialize);
    persistActiveModelContext({}, true);
    renderModelSelector();
    if ($("modelManagementDialog")?.open) renderModelManagementList();
    const localSnapshot = await refreshLocalSnapshotPayload(currentPageName());
    state.snapshotSource = "local";
    renderSnapshot(localSnapshot);
    closeReceiveLinkDialog();
    addRuntimeLog(
      "模型初始化",
      "模拟台定义下载",
      "初始化成功",
      `本地模型 ${activeModelIdBeforeInitialize} ← 远端模型 ${connection.modelName || connection.modelId}`,
      "ok",
    );
    setImportStatus(`模型初始化完成：${activeModelIdBeforeInitialize}`, "ok");
    renderReceiveMode();
  } catch (error) {
    addRuntimeLog("模型初始化", "模拟台定义下载", "初始化失败", apiErrorText(error), "warn");
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
  const mode = curveDisplayMode(snapshot);
  const dayCount = curveDisplayModeDayCount(mode);
  if (dayCount <= 1) return timeText;
  let dayOfCycle = Math.floor(Math.max(0, numericMinute) / 1440) % dayCount;
  if (mode !== "year") return `第${dayOfCycle + 1}天 ${timeText}`;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfCycle >= monthDays[month]) {
    dayOfCycle -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(dayOfCycle + 1).padStart(2, "0")} ${timeText}`;
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
  const origin = commandOrigin(entry);
  const source = String(entry.source || payload.source || "");
  if (explicitSimTime) {
    return {
      wall_time: wallTime,
      simu_time: explicitSimTime,
      source,
      command_origin: origin,
      origin_text: commandOriginLabel(origin),
    };
  }
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
    source,
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

function allActiveCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const history = Array.isArray(snapshot.commands?.history) ? snapshot.commands.history : [];
  const effective = Array.isArray(snapshot.commands?.effective) ? snapshot.commands.effective : [];
  return [...history, ...effective].filter((entry) => {
    if (!entry?.eligible_source || entry.cancelled) return false;
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
  state.runtimeLogs = state.runtimeLogs.slice(
    0,
    Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit"))),
  );
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
  if (!context.modelInitialized) return "uninitialized";
  if (context.frozen) return "frozen";
  return String(model?.clock_state || "stopped");
}

function modelManagementStateText(value) {
  return {
    receiving: "接收中",
    uninitialized: "未初始化",
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
  const deleteButton = menu?.querySelector('[data-model-context-action="delete"]');
  if (exportButton) exportButton.disabled = !hasSelected;
  if (cloneButton) cloneButton.disabled = !hasSelected;
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
    setModelManagementMessage("可新建待初始化模型；右键模型节点可导出、复制或删除。", "ok");
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
  setModelManagementMessage("可新建待初始化模型；右键模型节点可导出、复制或删除。", "ok");
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
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "新建中" : "新建";
  }
  if (input) input.disabled = isBusy;
  if (button) button.disabled = isBusy;
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
  if (confirm) confirm.disabled = false;
  setNewModelMessage("");
  return true;
}

function openNewModelDialog() {
  const dialog = $("newModelDialog");
  const input = $("newModelName");
  if (!dialog || !input) return;
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
  setNewModelMessage("");
  setNewModelBusy(false);
}

async function createNewModelSlot() {
  const input = $("newModelName");
  const name = String(input?.value || "").trim();
  if (!validateNewModelForm(true)) {
    input?.focus();
    return;
  }
  setNewModelBusy(true);
  setNewModelMessage("正在创建待初始化的本地模型...");
  addRuntimeLog("模型管理", "学员台 /api/trainee/models/create", "新建请求", name);
  try {
    const result = await api("/api/trainee/models/create", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.selected_model_id || name;
    state.modelContexts[contextKey(newModelId)] = defaultModelContext(newModelId);
    persistModelContextsToStorage();
    closeNewModelDialog();
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage(`已新建待初始化模型：${name}`, "ok");
    setImportStatus(`已新建待初始化模型：${name}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/trainee/models/create", "新建成功", `模型 ${name}`, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setNewModelMessage(message.includes("已存在") ? `${message}，请输入新的模型名称。` : message, "error");
    setImportStatus(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/trainee/models/create", "新建失败", message, "error");
  } finally {
    setNewModelBusy(false);
    if ($("newModelDialog")?.open) validateNewModelForm();
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
    const modelOptionsKey = JSON.stringify(models.map((model) => [model.id, model.name || model.id]));
    if (selector.dataset.modelOptionsKey !== modelOptionsKey) {
      selector.innerHTML = models.map((model) => `
        <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
      `).join("");
      selector.dataset.modelOptionsKey = modelOptionsKey;
    }
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

async function setActiveModel(modelId, shouldRefresh = true) {
  persistActiveModelContext({}, true);
  const nextId = modelId || state.models[0]?.id || "";
  state.activeModelId = nextId;
  state.deviceRuntimeSignature = "";
  state.deviceRuntimeNeedsFullRefresh = false;
  state.deviceRuntimeWarning = "";
  localStorage.setItem("polarTraineeModelId", nextId);
  restoreModelContext(nextId);
  resetMeasurementHistoryHydration();
  resetReceiveIssueStreak();
  pending.run_status.clear();
  pending.set_values.clear();
  if (!state.receiveMode) state.frozen = false;
  state.localDefinitionSnapshot = null;
  state.localDefinitionModelId = "";
  invalidateManualDefinitionChanges();
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
  state.chartLegendSeriesHidden = {};
  state.chartCursors = {};
  state.chartSeriesHitData = {};
  state.chartPlotInfo = {};
  resetChartPeriodOffsets("measurementTrace");
  resetChartPeriodOffsets("commandTrace");
  resetChartPeriodOffsets("renewableTrend");
  state.measurementFilter = { dev_type: "all", dev_name: "" };
  state.controlFilter = { dev_type: "all", dev_name: "" };
  state.activeControlTab = "remote-control";
  state.deviceTreeSelectionAnchors = {};
  resetWebRuntimeSettingsState();
  restartRefreshScheduler();
  resetRenewableControlView(nextId);
  renderModelSelector();
  if ($("modelManagementDialog")?.open) renderModelManagementList();
  updatePendingCount();
  await loadWebRuntimeSettings();
  if (shouldRefresh) await refresh();
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
    await setActiveModel(exists ? preferred : state.models[0]?.id || "", false);
    if ($("modelManagementDialog")?.open) renderModelManagementList();
  } catch (_error) {
    state.models = [];
    renderModelSelector();
    if ($("modelManagementDialog")?.open) renderModelManagementList();
  }
}

async function refreshLocalSnapshotPayload(page = currentPageName()) {
  state.embeddedMeasurementDeltaReceived = false;
  let snapshot = mergeSnapshot(
    state.snapshot,
    applyDeviceRuntimePayload(state.snapshot, await api(snapshotPollPath(page))),
  );
  let embeddedMeasurementDelta = snapshot?.measurement_delta || null;
  if (snapshot?.measurement_delta) delete snapshot.measurement_delta;
  snapshot = restoreStaticSnapshotCache(snapshot, page);
  let missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  if (missingStaticKeys.length) {
    const staticIncoming = applyDeviceRuntimePayload(
      snapshot,
      await api(snapshotPollPath(page, missingStaticKeys)),
    );
    if (staticIncoming?.measurement_delta) {
      embeddedMeasurementDelta = staticIncoming.measurement_delta;
      delete staticIncoming.measurement_delta;
    }
    snapshot = mergeSnapshot(snapshot, staticIncoming);
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  }
  state.snapshot = snapshot;
  if (embeddedMeasurementDelta) {
    snapshot.measurement_delta = embeddedMeasurementDelta;
    applyEmbeddedMeasurementDelta(snapshot);
  }
  if (!missingStaticKeys.length) persistStaticSnapshotCache(state.snapshot, page);
  return snapshot;
}

async function refresh() {
  await syncActiveReceiveStateBeforeRefresh();
  if (state.receiveMode) {
    await refreshFromTeacher(state.receiveEpoch);
    return;
  }
  const page = currentPageName();
  const bootstrapFrozenSnapshot = frozenSnapshotNeedsBootstrap(state.snapshot, page);
  if (state.frozen && !bootstrapFrozenSnapshot) {
    renderReceiveMode();
    if (currentPageName() === "renewable") await refreshRenewableControlState({ preview: false });
    return;
  }
  if (state.refreshRequestActive) return;
  state.refreshRequestActive = true;
  try {
    const snapshot = await refreshLocalSnapshotPayload(page);
    if (
      !bootstrapFrozenSnapshot
      && pageNeedsMeasurementDelta(page)
      && !state.embeddedMeasurementDeltaReceived
    ) {
      await refreshMeasurementDelta(false);
    }
    $("connectionDot").className = "ok";
    $("connectionText").textContent = "在线";
    state.snapshotSource = "local";
    if (page === "renewable") {
      await refreshRenewableControlState({ preview: false, render: false });
    }
    renderSnapshot(snapshot);
  } catch (_error) {
    $("connectionDot").className = "off";
    $("connectionText").textContent = "离线";
    if (page === "renewable") await refreshRenewableControlState({ preview: false });
  } finally {
    state.refreshRequestActive = false;
  }
}

async function refreshFromTeacher(epoch = state.receiveEpoch) {
  if (state.receiveRequestActive) return;
  state.receiveRequestActive = true;
  try {
    const page = currentPageName();
    await ensureLocalDefinitionSnapshot(state.activeModelId);
    const remoteSnapshot = applyDeviceRuntimePayload(
      state.snapshot,
      await teacherSnapshotApi(page),
    );
    state.embeddedMeasurementDeltaReceived = false;
    const embeddedMeasurementDelta = remoteSnapshot?.measurement_delta || null;
    if (remoteSnapshot?.measurement_delta) delete remoteSnapshot.measurement_delta;
    const snapshot = mergeTeacherSnapshotWithLocalDefinitions(state.snapshot, remoteSnapshot);
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    state.snapshot = snapshot;
    if (embeddedMeasurementDelta) {
      snapshot.measurement_delta = embeddedMeasurementDelta;
      applyEmbeddedMeasurementDelta(snapshot);
    }
    if (pageNeedsMeasurementDelta(page) && !state.embeddedMeasurementDeltaReceived) {
      await refreshMeasurementDelta(false);
    }
    if (page === "renewable") {
      await refreshRenewableControlState({ preview: false, render: false });
    }
    acceptTeacherSnapshot(state.snapshot, epoch);
  } catch (_error) {
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    $("connectionDot").className = "off";
    if (isTraineeWebTransportError(_error)) {
      $("connectionText").textContent = "后台重连";
      recordTraineeWebTransportIssue(_error);
      return;
    }
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
  state.frontendDiagnostics.snapshotRenderCount += 1;
  applyTraineeObservedRuntimeSignals(snapshot);
  state.snapshot = snapshot;
  if (state.snapshotSource !== "teacher" && snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock || {});
  renderPowerFlowFailureAlert(snapshot);
  const runId = Number(snapshot.clock?.run_id ?? 0);
  const stepCount = Number(snapshot.clock?.step_count ?? 0);
  const traceLifecycleChanged = state.traceRunId !== null && (
    runId !== state.traceRunId
    || (state.traceStepCount !== null && stepCount < state.traceStepCount)
  );
  if (traceLifecycleChanged) {
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
    state.commandTraceHistory = [];
    resetChartPeriodOffsets("commandTrace");
    state.renewableTrendHistory = [];
    resetChartPeriodOffsets("renewableTrend");
    state.selectedMeasurementKey = "";
  }
  state.traceRunId = runId;
  state.traceStepCount = stepCount;
  renderReceiveMode();
  appendMeasurementTrace(snapshot);
  appendCommandTrace(snapshot);
  syncCommandHistoryLogs(snapshot.commands?.history || []);
  updatePendingCount();
  renderActiveTraineePage(snapshot);
  ensureSelectedMeasurementHistory();
  refreshDiagramDeviceCommandDialog(snapshot);
  refreshRemoteControlDialog(snapshot);
  refreshRemoteAdjustmentDialog(snapshot);
  persistActiveModelContext();
}

function renderReceiveMode(extraText = "") {
  const button = $("traineeRunToggle");
  const initializeButton = $("modelInitializeButton");
  const stateText = $("receiveStateText");
  const sourceText = $("teacherSourceText");
  const teacherModelDisplayName = $("teacherModelDisplayName");
  const connectionDot = $("connectionDot");
  const connectionText = $("connectionText");
  const simulationPaused = Boolean(state.receiveMode && isSimulationFrozenSnapshot(state.snapshot));
  if (button) {
    button.textContent = state.receiveMode ? "停止接收" : "启动接收";
    button.disabled = !state.receiveMode && !state.modelInitialized;
    button.classList.toggle("is-running", state.receiveMode);
    button.title = !state.receiveMode && !state.modelInitialized ? "请先完成当前模型的模型初始化" : "";
  }
  if (initializeButton) {
    initializeButton.disabled = state.receiveMode;
    initializeButton.title = state.receiveMode ? "停止接收后才能重新初始化模型" : "";
  }
  if (connectionDot && connectionText) {
    connectionDot.className = extraText ? "off" : simulationPaused ? "frozen" : state.receiveMode ? "ok" : state.frozen ? "" : "ok";
    connectionText.textContent = extraText || (simulationPaused ? "模拟台暂停，已冻结" : state.receiveMode ? "接收中" : state.frozen ? "已冻结" : "在线");
  }
  if (stateText) {
    const label = simulationPaused
      ? "已冻结"
      : state.receiveMode
        ? "运行接收"
      : state.frozen
        ? "已冻结"
        : state.modelInitialized
          ? "已初始化"
          : "待初始化";
    stateText.textContent = extraText || label;
  }
  if (sourceText) {
    const receiveAddress = teacherReceiveAddress();
    const receiveAddressText = displayReceiveAddress(receiveAddress);
    sourceText.title = receiveAddress;
    sourceText.textContent = receiveAddressText || "--";
  }
  if (teacherModelDisplayName) {
    teacherModelDisplayName.textContent = state.teacherModelName || state.teacherModelId || "--";
  }
}

function curveMinute(snapshot) {
  const clock = snapshot.clock || {};
  const absoluteMinute = Number(clock.absolute_minute ?? clock.minute ?? 0) || 0;
  const durationMinutes = curveDisplayConfig(snapshot).durationMinutes;
  return durationMinutes > 0 ? ((absoluteMinute % durationMinutes) + durationMinutes) % durationMinutes : absoluteMinute;
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
  const row = (measurements.scada || []).find((item) => (
    item.dev_type === "Environment"
    && item.dev_name === "weather"
    && String(item.meas_type || "").toUpperCase() === measType
  ));
  if (row) {
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
  const windSpeed = windMeasurement.valid && Number.isFinite(windMeasurement.value)
    ? windMeasurement.value
    : weather.length
      ? interpolateCurve(weather, minute, "wind_speed_mps", null)
      : optionalNumber(boundaryPoint.wind_speed_mps);
  const solarIrradiance = solarMeasurement.valid && Number.isFinite(solarMeasurement.value)
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
  const liveSoc = averageStorageSocRatio(snapshot);
  const logSoc = storageSocPercentFromText(text);
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
  power.flowGroups = normalizeOverviewFlowGroups(summary.flowGroups, power);
  return power;
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
  const mode = curveDisplayMode(snapshot);
  const dayCount = curveDisplayModeDayCount(mode);
  if (dayCount <= 1) return timeText;
  const dayIndex = Math.floor((Number(clock.absolute_minute ?? clock.minute ?? 0) || 0) / 1440) % dayCount;
  if (mode !== "year") return `第${dayIndex + 1}天 ${timeText}`;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  let day = dayIndex;
  while (month < monthDays.length - 1 && day >= monthDays[month]) {
    day -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(day + 1).padStart(2, "0")} ${timeText}`;
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
  setOverviewText("overviewMode", curveDisplayModeLabel(snapshot));
  const effectiveStepSeconds = Number(
    clock.effective_step_seconds
      ?? snapshot.system_parameters?.effective_step_seconds
      ?? ((clock.step_seconds ?? 1) * (clock.speed ?? 1)),
  );
  setOverviewText("overviewStep", formatTraineeClockDuration(effectiveStepSeconds));
  setOverviewText("measureCount", `${totalMeasurements} 点`);
  setOverviewText("validCount", `${validCount} 可用`);

  setOverviewText("teacherWind", Number.isFinite(weather.windSpeed) ? `${formatOverviewNumber(weather.windSpeed)} m/s` : "--");
  setOverviewText("teacherSolar", Number.isFinite(weather.solarIrradiance) ? `${formatOverviewNumber(weather.solarIrradiance)} W/m²` : "--");
  setOverviewText("teacherTemp", `${formatOverviewNumber(weather.airTemp)} ℃`);
  setOverviewText("teacherLoad", overviewPowerText(weather.loadKw));
  setOverviewText("teacherWeatherTime", overviewClockText(snapshot));

  const { greenPower, greenPowerShare } = overviewGreenMetrics(power);
  setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderOverviewFlowGroups(power);
  renderTraineeOverviewEvents();
}

function renderActiveTraineePage(snapshot = state.snapshot || {}, force = false) {
  const activePage = currentPageName();
  if (activePage !== "diagram") {
    hideDiagramTooltip(state.pageSections?.diagram?.querySelector?.("#modelDiagramCanvas") || null);
  }
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
  if (activePage === "parameters") {
    renderWebRuntimeSettings();
    if (state.webRuntimeLoadedModelId !== state.activeModelId && !state.webRuntimeLoading) {
      loadWebRuntimeSettings();
    }
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
  if (pointCount === CURVE_DISPLAY_MODES.hour.pointCount) return "hour";
  if (pointCount === CURVE_DISPLAY_MODES.week.pointCount) return "week";
  if (pointCount === CURVE_DISPLAY_MODES.month.pointCount) return "month";
  if (pointCount === CURVE_DISPLAY_MODES.year.pointCount) return "year";
  return "day";
}

function curveDisplayModeDayCount(mode = curveDisplayMode()) {
  if (mode === "week") return 7;
  if (mode === "month") return 30;
  if (mode === "year") return 365;
  return 1;
}

function curveDisplayModeDurationMinutes(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  return CURVE_DISPLAY_MODES[mode]?.durationMinutes || CURVE_DISPLAY_MODES.day.durationMinutes;
}

function curveDisplayModeLabel(snapshot = state.snapshot || {}) {
  return CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)]?.label || CURVE_DISPLAY_MODES.day.label;
}

function formatTraineeClockDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value >= 3600 && value % 3600 === 0) return `${formatOverviewNumber(value / 3600)} h`;
  if (value >= 60 && value % 60 === 0) return `${formatOverviewNumber(value / 60)} min`;
  return `${formatOverviewNumber(value)} s`;
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
  const rawStepMinutes = Number(curves.time_step_minutes || boundary.time_step_minutes || defaults.stepMinutes);
  const stepMinutes = Number.isFinite(rawStepMinutes) && rawStepMinutes > 0 ? rawStepMinutes : defaults.stepMinutes;
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

function curveDisplayLoadFamilyConfig(family) {
  return CURVE_DISPLAY_LOAD_FAMILIES.find((item) => item.key === family) || null;
}

function curveDisplayLoadFamilyForBlock(blockName) {
  const block = String(blockName || "").trim();
  return CURVE_DISPLAY_LOAD_FAMILIES.find((item) => item.blocks.includes(block))?.key || "other";
}

function curveDisplayLoads(snapshot = state.snapshot || {}) {
  const names = new Map(Object.keys(snapshot.curves?.loads || {}).map((name) => [name, {
    name,
    devType: "",
    family: "other",
    unit: "",
    valueKey: "value",
    min: null,
    max: null,
    defaultValue: 0,
  }]));
  const supportedBlocks = new Set(CURVE_DISPLAY_LOAD_FAMILIES.flatMap((item) => item.blocks));
  (snapshot.devices || []).forEach((dev) => {
    if ((
      deviceFamily(dev) === "load"
      || supportedBlocks.has(deviceModelBlock(dev))
    ) && deviceName(dev)) {
      const name = deviceName(dev);
      const devType = deviceModelBlock(dev);
      const family = curveDisplayLoadFamilyForBlock(devType);
      const config = curveDisplayLoadFamilyConfig(family);
      const setType = family === "hydrogen" ? "flow_set" : family === "heat" ? "heat_power" : "p_set";
      names.set(name, {
        name,
        devType,
        family,
        unit: config?.unit || "",
        valueKey: config?.valueKey || "value",
        min: Number(dev.raw?.[`${setType.replace(/_set$/, "")}_min`]),
        max: Number(dev.raw?.[`${setType.replace(/_set$/, "")}_max`]),
        defaultValue: Number(dev.raw?.[setType] ?? 0),
      });
    }
  });
  return Array.from(names.values()).sort((left, right) => left.name.localeCompare(right.name, "zh-Hans-CN"));
}

function curveDisplayLoadKeys(snapshot = state.snapshot || {}) {
  return curveDisplayLoads(snapshot).map((load) => curveDisplayLoadKey(load.name));
}

function curveDisplayLoadForKey(key, snapshot = state.snapshot || {}) {
  const name = curveDisplayLoadName(key);
  return curveDisplayLoads(snapshot).find((load) => load.name === name) || null;
}

function curveDisplayLoadFamilyKeys(family, snapshot = state.snapshot || {}) {
  return curveDisplayLoads(snapshot)
    .filter((load) => load.family === family)
    .map((load) => curveDisplayLoadKey(load.name));
}

function curveDisplaySourceCatalog(snapshot = state.snapshot || {}) {
  const sources = snapshot.curves?.sources;
  return Array.isArray(sources) ? sources.filter((item) => item?.key && item?.family) : [];
}

function curveDisplaySourceKeys(snapshot = state.snapshot || {}) {
  return curveDisplaySourceCatalog(snapshot).map((item) => item.key);
}

function curveDisplayAllKeys(snapshot = state.snapshot || {}) {
  return [...CURVE_DISPLAY_ENV_KEYS, ...curveDisplayLoadKeys(snapshot), ...curveDisplaySourceKeys(snapshot)];
}

function curveDisplayRawPoints(key, snapshot = state.snapshot || {}) {
  if (String(key).startsWith("load:")) {
    const loadName = curveDisplayLoadName(key);
    const points = snapshot.curves?.loads?.[loadName];
    return Array.isArray(points) ? points : [];
  }
  if (String(key).startsWith("source:")) {
    const source = curveDisplaySourceCatalog(snapshot).find((item) => item.key === key);
    return Array.isArray(source?.points) ? source.points : [];
  }
  return Array.isArray(snapshot.curves?.weather) ? snapshot.curves.weather : [];
}

function curveDisplayPointValue(point, key, snapshot = state.snapshot || {}) {
  if (!point) return null;
  if (String(key).startsWith("load:")) {
    const load = curveDisplayLoadForKey(key, snapshot);
    return Number(
      point[load?.valueKey || "value"]
      ?? point.value
      ?? point.p_kw
      ?? point.load_kw
      ?? point.flow_set
      ?? point.heat_power,
    );
  }
  if (String(key).startsWith("source:")) return Number(point.value ?? point.set_value);
  return Number(point[key]);
}

function curveDisplayMetaForKey(key, snapshot = state.snapshot || {}) {
  const meta = CURVE_DISPLAY_META.find((item) => item.key === key);
  if (meta) return meta;
  if (String(key).startsWith("source:")) {
    const source = curveDisplaySourceCatalog(snapshot).find((item) => item.key === key) || {};
    const sourceIndex = Math.max(0, curveDisplaySourceKeys(snapshot).indexOf(key));
    const values = curveDisplayRawPoints(key, snapshot)
      .map((point) => curveDisplayPointValue(point, key, snapshot))
      .filter((value) => Number.isFinite(value));
    const defaultValue = Number(source.default_value);
    const lower = Number(source.min);
    const upper = Number(source.max);
    const minimum = Number.isFinite(lower) ? lower : Math.min(0, ...(values.length ? values : [defaultValue || 0]));
    const dynamicMax = Math.max(...(values.length ? values : [defaultValue || 0, 1]));
    return {
      key,
      label: source.name || source.dev_name || key,
      color: CURVE_DISPLAY_SOURCE_COLORS[sourceIndex % CURVE_DISPLAY_SOURCE_COLORS.length],
      min: minimum,
      max: Number.isFinite(upper) ? upper : Math.max(1, dynamicMax * 1.12),
      digits: 3,
      unit: source.unit || "",
      family: source.family || "electric",
    };
  }
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const load = curveDisplayLoadForKey(key, snapshot);
  const loadIndex = Math.max(0, loadKeys.indexOf(key));
  const values = curveDisplayRawPoints(key, snapshot)
    .map((point) => curveDisplayPointValue(point, key, snapshot))
    .filter((value) => Number.isFinite(value));
  const dynamicMax = values.length ? Math.max(...values) * 1.12 : CURVE_DISPLAY_LOAD_META.max;
  const lower = Number(load?.min);
  const upper = Number(load?.max);
  return {
    ...CURVE_DISPLAY_LOAD_META,
    key,
    label: curveDisplayLoadName(key),
    color: CURVE_DISPLAY_LOAD_COLORS[loadIndex % CURVE_DISPLAY_LOAD_COLORS.length],
    unit: load?.unit || CURVE_DISPLAY_LOAD_META.unit,
    family: load?.family || "other",
    min: Number.isFinite(lower) ? lower : 0,
    max: Number.isFinite(upper) && upper > (Number.isFinite(lower) ? lower : 0)
      ? upper
      : Math.max(dynamicMax, Number(load?.defaultValue) || 0, 1),
  };
}

function curveDisplayRoundValue(key, value, snapshot = state.snapshot || {}) {
  const meta = curveDisplayMetaForKey(key, snapshot);
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Number(numeric.toFixed(meta.digits));
}

function interpolateCurveDisplay(points, minute, key, defaultValue = 0, snapshot = state.snapshot || {}) {
  const pairs = (points || [])
    .map((point, index) => ({
      minute: Number(point.minute ?? index),
      value: curveDisplayPointValue(point, key, snapshot),
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
    return points.map((point) => curveDisplayRoundValue(key, curveDisplayPointValue(point, key, snapshot) ?? meta.min, snapshot));
  }
  return Array.from({ length: config.pointCount }, (_unused, index) => (
    curveDisplayRoundValue(key, interpolateCurveDisplay(points, curveDisplayPointMinute(index, snapshot), key, meta.min, snapshot), snapshot)
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
  if (String(family).startsWith("load:")) return curveDisplayLoadFamilyKeys(String(family).slice(5), snapshot);
  if (family === "source") return curveDisplaySourceKeys(snapshot);
  if (String(family).startsWith("source:")) {
    const sourceFamily = String(family).slice(7);
    return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === sourceFamily).map((item) => item.key);
  }
  if (family === "electric") return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family).map((item) => item.key);
  if (family === "hydrogen") return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family).map((item) => item.key);
  if (family === "heat") return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family).map((item) => item.key);
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

function readStoredCurveDisplayTreeCollapsedGroups() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CURVE_DISPLAY_TREE_COLLAPSE_KEY) || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch (_error) {
    // Invalid local UI state falls back to the default expanded tree.
  }
  return {};
}

function curveDisplayTreeGroupCollapsed(groupKey) {
  return Boolean(state.curveDisplayTreeGroupCollapsed?.[groupKey]);
}

function toggleCurveDisplayTreeGroup(groupKey) {
  if (!groupKey) return;
  state.curveDisplayTreeGroupCollapsed = {
    ...(state.curveDisplayTreeGroupCollapsed || {}),
    [groupKey]: !curveDisplayTreeGroupCollapsed(groupKey),
  };
  localStorage.setItem(CURVE_DISPLAY_TREE_COLLAPSE_KEY, JSON.stringify(state.curveDisplayTreeGroupCollapsed));
  renderCurveDisplayTree(state.snapshot || {});
}

function curveDisplayTreeGroupHeader(groupKey, label, count, buttonAttrs, buttonClasses = "", toggleAttribute = "data-curve-display-tree-toggle") {
  const collapsed = curveDisplayTreeGroupCollapsed(groupKey);
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

function renderCurveDisplayTree(snapshot = state.snapshot || {}) {
  const container = $("curveDisplayTree");
  if (!container) return;
  const selected = selectedCurveDisplayKeys(snapshot);
  const selectedSet = new Set(selected);
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const loadDevices = curveDisplayLoads(snapshot);
  const loadGroups = [
    ...CURVE_DISPLAY_LOAD_FAMILIES.map((family) => ({
      ...family,
      loads: loadDevices.filter((load) => load.family === family.key),
    })),
    {
      key: "other",
      label: "其他负荷曲线",
      loads: loadDevices.filter((load) => !CURVE_DISPLAY_LOAD_FAMILIES.some((family) => family.key === load.family)),
    },
  ].filter((group) => group.key !== "other" || group.loads.length);
  const sourceGroups = CURVE_DISPLAY_SOURCE_FAMILIES.map((family) => ({
    ...family,
    sources: curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family.key),
  }));
  const envSelected = CURVE_DISPLAY_ENV_KEYS.every((key) => selectedSet.has(key))
    && selected.every((key) => CURVE_DISPLAY_ENV_KEYS.includes(key));
  const loadSelected = loadKeys.length && loadKeys.every((key) => selectedSet.has(key))
    && selected.every((key) => loadKeys.includes(key));
  const envPartial = CURVE_DISPLAY_ENV_KEYS.some((key) => selectedSet.has(key));
  const loadPartial = loadKeys.some((key) => selectedSet.has(key));
  const sourceKeys = curveDisplaySourceKeys(snapshot);
  const sourceSelected = sourceKeys.length && sourceKeys.every((key) => selectedSet.has(key))
    && selected.every((key) => sourceKeys.includes(key));
  const sourcePartial = sourceKeys.some((key) => selectedSet.has(key));
  $("curveDisplayTreeSummary").textContent = `${CURVE_DISPLAY_ENV_KEYS.length + loadKeys.length + curveDisplaySourceKeys(snapshot).length} 条`;
  container.innerHTML = `
    <div class="tree-group">
      ${curveDisplayTreeGroupHeader(
        "environment",
        "环境曲线",
        CURVE_DISPLAY_ENV_KEYS.length,
        `data-curve-display-tree-type="environment" data-curve-display-family="environment" aria-expanded="${curveDisplayTreeGroupCollapsed("environment") ? "false" : "true"}"`,
        envSelected ? "is-active" : envPartial ? "is-parent-active" : "",
        "data-curve-display-tree-toggle",
      )}
      <div class="tree-children" ${curveDisplayTreeGroupCollapsed("environment") ? "hidden" : ""}>
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
      ${curveDisplayTreeGroupHeader(
        "load",
        "负荷曲线",
        loadKeys.length,
        `data-curve-display-tree-type="load" data-curve-display-family="load" aria-expanded="${curveDisplayTreeGroupCollapsed("load") ? "false" : "true"}"`,
        loadSelected ? "is-active" : loadPartial ? "is-parent-active" : "",
        "data-curve-display-tree-toggle",
      )}
      <div class="tree-children" ${curveDisplayTreeGroupCollapsed("load") ? "hidden" : ""}>
        ${loadGroups.map((group) => {
          const groupKey = `load:${group.key}`;
          const keys = group.loads.map((load) => curveDisplayLoadKey(load.name));
          const groupSelected = keys.length && keys.every((key) => selectedSet.has(key))
            && selected.every((key) => keys.includes(key));
          const groupPartial = keys.some((key) => selectedSet.has(key));
          return `
            <div class="tree-subgroup">
              ${curveDisplayTreeGroupHeader(
                groupKey,
                group.label,
                keys.length,
                `data-curve-display-tree-type="load" data-curve-display-family="${escapeHtml(groupKey)}" aria-expanded="${curveDisplayTreeGroupCollapsed(groupKey) ? "false" : "true"}"`,
                groupSelected ? "is-active" : groupPartial ? "is-parent-active" : "",
              )}
              <div class="tree-children tree-grandchildren" ${curveDisplayTreeGroupCollapsed(groupKey) ? "hidden" : ""}>
                ${group.loads.map((load) => {
                  const key = curveDisplayLoadKey(load.name);
                  return `
                    <button
                      type="button"
                      class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""} ${isCurveDisplaySeriesHidden(key) ? "is-hidden-series" : ""}"
                      data-curve-display-tree-type="load"
                      data-curve-display-key="${escapeHtml(key)}"
                    >
                      <span>${escapeHtml(load.name)}</span>
                      <small>${escapeHtml(load.unit || load.devType)}</small>
                    </button>`;
                }).join("") || `<div class="empty-state compact">暂无${escapeHtml(group.label)}</div>`}
              </div>
            </div>`;
        }).join("") || '<div class="empty-state compact">暂无负荷曲线</div>'}
      </div>
    </div>
    <div class="tree-group">
      ${curveDisplayTreeGroupHeader(
        "source",
        "供能曲线",
        sourceKeys.length,
        `data-curve-display-tree-type="source" data-curve-display-family="source" aria-expanded="${curveDisplayTreeGroupCollapsed("source") ? "false" : "true"}"`,
        sourceSelected ? "is-active" : sourcePartial ? "is-parent-active" : "",
        "data-curve-display-tree-toggle",
      )}
      <div class="tree-children" ${curveDisplayTreeGroupCollapsed("source") ? "hidden" : ""}>
        ${sourceGroups.map((group) => {
          const groupKey = `source:${group.key}`;
          const keys = group.sources.map((source) => source.key);
          const groupSelected = keys.length && keys.every((key) => selectedSet.has(key))
            && selected.every((key) => keys.includes(key));
          const groupPartial = keys.some((key) => selectedSet.has(key));
          return `
            <div class="tree-subgroup">
              ${curveDisplayTreeGroupHeader(
                groupKey,
                group.label,
                keys.length,
                `data-curve-display-tree-type="source" data-curve-display-family="${escapeHtml(groupKey)}" aria-expanded="${curveDisplayTreeGroupCollapsed(groupKey) ? "false" : "true"}"`,
                groupSelected ? "is-active" : groupPartial ? "is-parent-active" : "",
              )}
              <div class="tree-children tree-grandchildren" ${curveDisplayTreeGroupCollapsed(groupKey) ? "hidden" : ""}>
                ${group.sources.map((source) => `
                  <button
                    type="button"
                    class="tree-node tree-child ${selectedSet.has(source.key) ? "is-active" : ""} ${isCurveDisplaySeriesHidden(source.key) ? "is-hidden-series" : ""}"
                    data-curve-display-tree-type="source"
                    data-curve-display-key="${escapeHtml(source.key)}"
                  >
                    <span>${escapeHtml(source.name || source.dev_name || source.key)}</span>
                    <small>${escapeHtml(source.unit || source.dev_type || "")}</small>
                  </button>`).join("") || `<div class="empty-state compact">暂无${escapeHtml(group.label)}</div>`}
              </div>
            </div>`;
        }).join("")}
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
  const mode = curveDisplayMode(snapshot);
  if (mode === "hour") {
    const totalSeconds = Math.max(0, Math.round(Number(minute) * 60));
    const minutePart = Math.floor(totalSeconds / 60);
    const secondPart = totalSeconds % 60;
    return `00:${String(minutePart).padStart(2, "0")}:${String(secondPart).padStart(2, "0")}`;
  }
  if (mode === "year") {
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
  if (mode === "week" || mode === "month") {
    const total = Math.max(0, Math.round(Number(minute)));
    const day = Math.floor(total / 1440) + 1;
    const minuteOfDay = total % 1440;
    const hour = Math.floor(minuteOfDay / 60);
    const minutePart = minuteOfDay % 60;
    return `第${day}天 ${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`;
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
  if (canvas.width < 640) return { left: 48, right: 12, top: 58, bottom: 30 };
  return CURVE_DISPLAY_PLOT;
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
  const mode = curveDisplayMode(snapshot);
  if (mode === "hour") {
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
  if (mode === "week" || mode === "month") {
    const dayCount = curveDisplayModeDayCount(mode);
    const dayStep = mode === "week" ? 1 : width < 560 ? 10 : width < 900 ? 5 : 3;
    for (let day = 0; day <= dayCount; day += dayStep) {
      const x = left + (day / dayCount) * (right - left);
      ctx.strokeStyle = day === 0 || day === dayCount ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      ctx.fillText(`第${Math.min(day + 1, dayCount)}天`, x - 16, height - 12);
    }
    if (dayCount % dayStep !== 0) {
      ctx.textAlign = "right";
      ctx.fillText(`第${dayCount}天`, right, height - 12);
      ctx.textAlign = "left";
    }
    return;
  }
  if (mode === "year") {
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
  const activeKey = isCurveDisplaySeriesHidden(state.activeCurveDisplayKey) ? "" : state.activeCurveDisplayKey;
  const axisMeta = curveYAxisMeta(metas, activeKey);
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
  drawCurveYAxis(ctx, canvas, plot, axisMeta);
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
    source: `${snapshot.curves?.weather?.length || 0}|${Object.values(snapshot.curves?.loads || {}).map((points) => points?.length || 0).join(",")}|${curveDisplaySourceCatalog(snapshot).map((item) => item.points?.length || 0).join(",")}`,
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
    const isLoad = deviceFamily(dev) === "load"
      || ["ACLoad", "DCLoad"].includes(deviceModelBlock(dev));
    if (!isLoad || !isDeviceOnline(dev)) return total;
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
    deviceModelBlock(dev) === devType && String(deviceIndex(dev)).trim() === target
  )) || null;
}

function measurementValuesByDevice(snapshot, measurementTypes) {
  const values = new Map();
  const measurements = snapshot.measurements || {};
  (measurementTypes || []).map((type) => String(type || "").toUpperCase()).forEach((measurementType) => {
    (measurements.scada || []).forEach((row) => {
      if (String(row.meas_type || "").toUpperCase() !== measurementType || Number(row.valid ?? 1) !== 1) return;
      const value = optionalNumber(row.value);
      if (!Number.isFinite(value)) return;
      const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
      if (!values.has(key)) values.set(key, value);
    });
  });
  return values;
}

function storageSocRatiosByDevice(snapshot) {
  const measured = measurementValuesByDevice(snapshot, ["SOC"]);
  const ratios = new Map();
  let linkedStorageCount = 0;
  parameterRows(snapshot, "ACStorageGen").forEach((param, index) => {
    linkedStorageCount += 1;
    const dev = indexedDevice(snapshot, "ACGenerator", param.idx_acgenerator);
    const name = deviceName(dev) || `ACGenerator_${param.idx_acgenerator ?? index + 1}`;
    const key = `ACGenerator|${name}`;
    const soc = liveStorageSocRatio(
      measured.get(key) ?? dev?.soc_curr ?? dev?.raw?.soc_curr,
      null,
    );
    if (Number.isFinite(soc)) ratios.set(key, soc);
  });
  parameterRows(snapshot, "DCStorageGen").forEach((param, index) => {
    linkedStorageCount += 1;
    const dev = indexedDevice(snapshot, "DCGenerator", param.idx_dcgenerator);
    const name = deviceName(dev) || `DCGenerator_${param.idx_dcgenerator ?? index + 1}`;
    const key = `DCGenerator|${name}`;
    const soc = liveStorageSocRatio(
      measured.get(key) ?? dev?.soc_curr ?? dev?.raw?.soc_curr,
      null,
    );
    if (Number.isFinite(soc)) ratios.set(key, soc);
  });
  if (linkedStorageCount) {
    return ratios;
  }
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

function renewableControlApiPath(preview = false) {
  const params = new URLSearchParams();
  if (preview) params.set("refresh", "1");
  params.set("compact", "1");
  const latestLogSeq = (state.renewableControl.logs || []).reduce(
    (latest, item) => Math.max(latest, Number(item?.seq) || 0),
    0,
  );
  if (latestLogSeq > 0) params.set("after_log_seq", String(latestLogSeq));
  const planRevision = Number(state.renewableControl.planRevision);
  const performanceRevision = Number(state.renewableControl.performanceRevision);
  const controllerInstanceId = String(state.renewableControl.controllerInstanceId || "");
  if (Number.isFinite(planRevision) && planRevision >= 0 && controllerInstanceId) {
    params.set("after_plan_revision", String(planRevision));
    params.set("after_controller_instance_id", controllerInstanceId);
  }
  if (Number.isFinite(performanceRevision) && performanceRevision >= 0 && controllerInstanceId) {
    params.set("after_performance_revision", String(performanceRevision));
  }
  const latestTrendSampleKey = String(
    state.renewableTrendHistory?.[state.renewableTrendHistory.length - 1]?.sampleKey || "",
  );
  if (latestTrendSampleKey) params.set("after_trend_sample_key", latestTrendSampleKey);
  return `/api/trainee/renewable-control?${params.toString()}`;
}

function storageDeratingRatio(value) {
  const number = toNumber(value, Number.NaN);
  if (!Number.isFinite(number)) return null;
  return clamp(number > 1 ? number / 100 : number, 0, 1);
}

function normalizeStorageDeratingCurve(points, fallback, direction) {
  const source = Array.isArray(points) && points.length >= 2 ? points : fallback;
  const parsed = source
    .map((point) => ({
      soc: storageDeratingRatio(point?.soc ?? point?.socRatio),
      powerRatio: storageDeratingRatio(point?.powerRatio ?? point?.power_ratio ?? point?.ratio),
    }))
    .filter((point) => Number.isFinite(point.soc) && Number.isFinite(point.powerRatio))
    .sort((left, right) => left.soc - right.soc);
  if (parsed.length < 2) return fallback.map((point) => ({ ...point }));
  const unique = [];
  parsed.forEach((point) => {
    const previous = unique[unique.length - 1];
    if (previous && Math.abs(previous.soc - point.soc) < 1e-9) previous.powerRatio = point.powerRatio;
    else unique.push({ ...point });
  });
  if (unique.length < 2) return fallback.map((point) => ({ ...point }));
  let previousRatio = direction === "discharge" ? 0 : 1;
  return unique.map((point) => {
    const powerRatio = direction === "discharge"
      ? Math.max(previousRatio, point.powerRatio)
      : Math.min(previousRatio, point.powerRatio);
    previousRatio = powerRatio;
    return { soc: point.soc, powerRatio };
  });
}

function resetRenewableControlView(modelId = state.activeModelId) {
  closeRenewableControlLogDetailDialog();
  const control = state.renewableControl;
  Object.assign(control, {
    modelId: modelId || "",
    controllerInstanceId: "",
    enabled: false,
    desiredEnabled: false,
    resumePending: false,
    runState: "stopped",
    controlFrozen: false,
    simulationPaused: false,
    receiveActive: false,
    canRun: false,
    prerequisiteStatus: "请先启动接收。",
    loopMode: "open",
    sending: false,
    requestActive: false,
    actionActive: false,
    revision: -1,
    planRevision: -1,
    performanceRevision: -1,
    lastPlan: null,
    performanceDiagnostics: null,
    lastCalculatedAt: "",
    lastSentAt: "",
    lastStatus: "正在读取学员台后台控制状态。",
    logs: [],
    metricTab: "ac",
    parameterTab: "runtime",
    strategyTab: "ac-wind",
    logPage: 1,
    selectedLogSeq: 0,
    lastControlLogRenderKey: "",
  });
  state.renewableTrendHistory = [];
  if (state.chartPeriodOffsets) state.chartPeriodOffsets.renewableTrend = 0;
}

function renewableDataSourceLabel(source = "") {
  return ({
    "trainee-live": "学员台实时数据",
    "trainee-cache": "学员台缓存数据",
  })[String(source || "")] || "等待实时数据";
}

function renewablePrerequisiteStatus(control = {}) {
  if (control.controlFrozen) {
    return "模拟台暂停，学员台保持冻结；恢复后将继续原运行状态。";
  }
  if (control.prerequisiteStatus) return control.prerequisiteStatus;
  return control.receiveActive
    ? "学员台正在等待第一份实时数据。"
    : "请先启动接收，再启动新能源实时控制。";
}

function renewableTrendLifecycleChanged(previous = {}, current = {}) {
  if (Number(previous.runId ?? 0) !== Number(current.runId ?? 0)) return true;
  const previousStep = Number(previous.stepCount);
  const currentStep = Number(current.stepCount);
  if (Number.isFinite(previousStep) && Number.isFinite(currentStep) && currentStep < previousStep) return true;
  const previousMinute = Number(previous.minute);
  const currentMinute = Number(current.minute);
  return Number.isFinite(previousMinute) && Number.isFinite(currentMinute) && currentMinute < previousMinute;
}

function latestRenewableTrendSegment(points = []) {
  const source = Array.isArray(points) ? points : [];
  let segmentStart = 0;
  for (let index = 1; index < source.length; index += 1) {
    if (renewableTrendLifecycleChanged(source[index - 1], source[index])) segmentStart = index;
  }
  return source.slice(segmentStart);
}

function mergeRenewableTrendDelta(current = [], incoming = [], reset = false) {
  const merged = reset ? [] : latestRenewableTrendSegment(current).slice();
  (Array.isArray(incoming) ? incoming : []).forEach((point) => {
    if (!point || typeof point !== "object") return;
    if (merged.length && renewableTrendLifecycleChanged(merged[merged.length - 1], point)) {
      merged.length = 0;
    }
    const sampleKey = String(point.sampleKey || "");
    const existingIndex = sampleKey
      ? merged.findIndex((candidate) => String(candidate?.sampleKey || "") === sampleKey)
      : -1;
    if (existingIndex >= 0) {
      merged.splice(existingIndex, merged.length - existingIndex, point);
    } else {
      merged.push(point);
    }
  });
  return latestRenewableTrendSegment(merged);
}

function mergeRenewableControlLogDelta(current = [], incoming = [], reset = false) {
  const merged = new Map();
  if (!reset) {
    (Array.isArray(current) ? current : []).forEach((item) => {
      const seq = Number(item?.seq) || 0;
      if (seq > 0) merged.set(seq, item);
    });
  }
  (Array.isArray(incoming) ? incoming : []).forEach((item) => {
    const seq = Number(item?.seq) || 0;
    if (seq > 0) merged.set(seq, item);
  });
  return Array.from(merged.values())
    .sort((left, right) => (Number(right?.seq) || 0) - (Number(left?.seq) || 0))
    .slice(0, 300);
}

function resetRenewableControlHistoryForLifecycle(control = state.renewableControl) {
  closeRenewableControlLogDetailDialog();
  control.logs = [];
  control.revision = -1;
  control.planRevision = -1;
  control.performanceRevision = -1;
  control.lastPlan = null;
  control.performanceDiagnostics = null;
  control.logPage = 1;
  control.selectedLogSeq = 0;
  control.lastControlLogRenderKey = "";
  state.renewableTrendHistory = [];
  if (state.chartPeriodOffsets) state.chartPeriodOffsets.renewableTrend = 0;
}

function applyRenewableControlState(payload = {}) {
  if (!payload || typeof payload !== "object") return false;
  const control = state.renewableControl;
  const incomingControllerInstanceId = String(
    payload.controllerInstanceId || control.controllerInstanceId || "",
  );
  const controllerLifecycleChanged = Boolean(
    incomingControllerInstanceId
    && control.controllerInstanceId
    && incomingControllerInstanceId !== control.controllerInstanceId,
  );
  const incomingRevision = Number(payload.revision);
  const incomingPlanRevision = Number(payload.planRevision);
  const incomingPerformanceRevision = Number(payload.performanceRevision);
  const hasLastPlan = Object.prototype.hasOwnProperty.call(payload, "lastPlan");
  const hasPerformanceDiagnostics = Object.prototype.hasOwnProperty.call(
    payload,
    "performanceDiagnostics",
  );
  if (
    !controllerLifecycleChanged
    &&
    payload.modelId
    && control.modelId === payload.modelId
    && Number.isFinite(incomingRevision)
    && incomingRevision < Number(control.revision ?? -1)
  ) {
    return false;
  }
  if (controllerLifecycleChanged) resetRenewableControlHistoryForLifecycle(control);
  const settings = payload.settings && typeof payload.settings === "object" ? payload.settings : {};
  Object.assign(control, {
    modelId: String(payload.modelId || state.activeModelId || ""),
    controllerInstanceId: incomingControllerInstanceId,
    enabled: Boolean(payload.enabled),
    desiredEnabled: Boolean(payload.desiredEnabled),
    resumePending: Boolean(payload.resumePending),
    runState: ["running", "frozen", "resume_pending", "stopped"].includes(payload.runState)
      ? payload.runState
      : payload.enabled
        ? "running"
        : payload.desiredEnabled
          ? "resume_pending"
          : "stopped",
    controlFrozen: Boolean(payload.controlFrozen),
    simulationPaused: Boolean(payload.simulationPaused),
    receiveActive: Boolean(payload.receiveActive),
    canRun: Boolean(payload.canRun),
    prerequisiteStatus: payload.prerequisiteStatus || "",
    loopMode: payload.loopMode === "closed" ? "closed" : "open",
    sending: Boolean(payload.sending),
    intervalSeconds: Math.max(1, toNumber(
      settings.simulationIntervalSeconds ?? settings.intervalSeconds,
      control.intervalSeconds || 2,
    )),
    largeStepThresholdKw: Math.max(0, toNumber(settings.largeStepThresholdKw, control.largeStepThresholdKw || 10)),
    stepCoefficient: Math.max(0, toNumber(
      settings.renewableStepRatio ?? settings.stepCoefficient,
      control.stepCoefficient || 0.03,
    )),
    storageStepRatio: Math.max(0, toNumber(
      settings.storageStepRatio,
      control.storageStepRatio || 0.03,
    )),
    storageSocCorrectionStepScale: Math.min(1, Math.max(0.1, toNumber(
      settings.storageSocCorrectionStepScale,
      control.storageSocCorrectionStepScale || 0.2,
    ))),
    gridFormingStorageProtectionRatio: Math.max(0, toNumber(
      settings.gridFormingStorageProtectionRatio
        ?? (Number.isFinite(Number(settings.storageSwitchDeadbandKw))
          ? Number(settings.storageSwitchDeadbandKw) / 100
          : undefined),
      control.gridFormingStorageProtectionRatio || 0.05,
    )),
    dieselPowerProtectionRatio: Math.max(0, toNumber(
      settings.dieselPowerProtectionRatio ?? settings.dieselDeadbandRatio,
      control.dieselPowerProtectionRatio || 0.03,
    )),
    socDeadband: Math.max(0, toNumber(settings.socDeadband, control.socDeadband || 0.05)),
    hydrogenClosedLoopEnabled: Boolean(settings.hydrogenClosedLoopEnabled),
    hydrogenPressureDeadbandRatio: Math.min(0.5, Math.max(0, toNumber(
      settings.hydrogenPressureDeadbandRatio,
      control.hydrogenPressureDeadbandRatio || 0.05,
    ))),
    electrolyzerPowerMinRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerPowerMinRatio, control.electrolyzerPowerMinRatio ?? 0.02))),
    electrolyzerPowerMaxRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerPowerMaxRatio, control.electrolyzerPowerMaxRatio ?? 0.50))),
    electrolyzerPowerDeadbandRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerPowerDeadbandRatio, control.electrolyzerPowerDeadbandRatio ?? 0))),
    electrolyzerPowerStepRatio: Math.min(1, Math.max(0.00001, toNumber(settings.electrolyzerPowerStepRatio, control.electrolyzerPowerStepRatio ?? 0.02))),
    electrolyzerDieselPowerLimitRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerDieselPowerLimitRatio, control.electrolyzerDieselPowerLimitRatio ?? 0.80))),
    electrolyzerDieselPowerDeadbandRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerDieselPowerDeadbandRatio, control.electrolyzerDieselPowerDeadbandRatio ?? 0.05))),
    electrolyzerStorageSocLowerLimit: Math.min(1, Math.max(0, toNumber(settings.electrolyzerStorageSocLowerLimit, control.electrolyzerStorageSocLowerLimit ?? 0.4))),
    electrolyzerStorageSocUpperLimit: Math.min(1, Math.max(0, toNumber(settings.electrolyzerStorageSocUpperLimit, control.electrolyzerStorageSocUpperLimit ?? 0.8))),
    electrolyzerHydrogenStorageSocUpperLimit: Math.min(1, Math.max(0, toNumber(settings.electrolyzerHydrogenStorageSocUpperLimit, control.electrolyzerHydrogenStorageSocUpperLimit ?? 0.9))),
    fuelCellPowerMinRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellPowerMinRatio, control.fuelCellPowerMinRatio ?? 0.03))),
    fuelCellPowerMaxRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellPowerMaxRatio, control.fuelCellPowerMaxRatio ?? 0.15))),
    fuelCellPowerDeadbandRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellPowerDeadbandRatio, control.fuelCellPowerDeadbandRatio ?? 0))),
    fuelCellPowerStepRatio: Math.min(1, Math.max(0.00001, toNumber(settings.fuelCellPowerStepRatio, control.fuelCellPowerStepRatio ?? 0.03))),
    fuelCellDieselPowerLimitRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellDieselPowerLimitRatio, control.fuelCellDieselPowerLimitRatio ?? 0.80))),
    fuelCellStorageSocLimit: Math.min(1, Math.max(0, toNumber(settings.fuelCellStorageSocLimit, control.fuelCellStorageSocLimit ?? 0.4))),
    fuelCellHydrogenStorageSocUpperLimit: Math.min(1, Math.max(0, toNumber(settings.fuelCellHydrogenStorageSocUpperLimit, control.fuelCellHydrogenStorageSocUpperLimit ?? 0.8))),
    fuelCellHydrogenStorageSocLowerLimit: Math.min(1, Math.max(0, toNumber(settings.fuelCellHydrogenStorageSocLowerLimit, control.fuelCellHydrogenStorageSocLowerLimit ?? 0.2))),
    optimizationRenewableCurtailmentWeight: Math.max(0, toNumber(settings.optimizationRenewableCurtailmentWeight, control.optimizationRenewableCurtailmentWeight || 1)),
    optimizationDieselOutputWeight: Math.max(0, toNumber(settings.optimizationDieselOutputWeight, control.optimizationDieselOutputWeight || 1)),
    optimizationCurtailmentSquareWeight: Math.max(0, toNumber(settings.optimizationCurtailmentSquareWeight, control.optimizationCurtailmentSquareWeight || 0.000001)),
    optimizationSourceStorageAdjustmentSquareWeight: Math.max(0, toNumber(settings.optimizationSourceStorageAdjustmentSquareWeight, control.optimizationSourceStorageAdjustmentSquareWeight || 0.000001)),
    optimizationBalanceDeltaSquareWeight: Math.max(0, toNumber(settings.optimizationBalanceDeltaSquareWeight, control.optimizationBalanceDeltaSquareWeight || 10000)),
    optimizationBalanceDeltaWarningKw: Math.max(0, toNumber(settings.optimizationBalanceDeltaWarningKw, control.optimizationBalanceDeltaWarningKw || 1)),
    optimizationBalanceToleranceKw: Math.max(0, toNumber(settings.optimizationBalanceToleranceKw, control.optimizationBalanceToleranceKw || 0.1)),
    optimizationBoundToleranceKw: Math.max(0, toNumber(settings.optimizationBoundToleranceKw, control.optimizationBoundToleranceKw || 0.1)),
    optimizationFtol: Math.max(0, toNumber(settings.optimizationFtol, control.optimizationFtol || 0.001)),
    optimizationMaxIterations: Math.max(1, Math.round(toNumber(settings.optimizationMaxIterations, control.optimizationMaxIterations || 100))),
    commandValidMinutes: Math.max(0.1, toNumber(settings.commandValidMinutes, control.commandValidMinutes || 120)),
    storageChargeDeratingCurve: normalizeStorageDeratingCurve(
      settings.storageChargeDeratingCurve,
      control.storageChargeDeratingCurve || DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
      "charge",
    ),
    storageDischargeDeratingCurve: normalizeStorageDeratingCurve(
      settings.storageDischargeDeratingCurve,
      control.storageDischargeDeratingCurve || DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
      "discharge",
    ),
    planRevision: Number.isFinite(incomingPlanRevision)
      ? incomingPlanRevision
      : control.planRevision,
    performanceRevision: Number.isFinite(incomingPerformanceRevision)
      ? incomingPerformanceRevision
      : control.performanceRevision,
    lastCalculatedAt: payload.lastCalculatedAt || "",
    lastSentAt: payload.lastSentAt || "",
    lastStatus: payload.status || "学员台后台控制状态已同步。",
    revision: Number.isFinite(incomingRevision) ? incomingRevision : control.revision,
    logs: mergeRenewableControlLogDelta(
      control.logs,
      payload.logs,
      payload.logsReset !== false,
    ),
  });
  if (hasLastPlan) control.lastPlan = payload.lastPlan || null;
  if (hasPerformanceDiagnostics) {
    control.performanceDiagnostics = payload.performanceDiagnostics || null;
  }
  if (control.selectedLogSeq && !renewableControlLogBySeq(control.selectedLogSeq)) {
    control.selectedLogSeq = 0;
    closeRenewableControlLogDetailDialog();
  }
  state.renewableTrendHistory = mergeRenewableTrendDelta(
    state.renewableTrendHistory,
    payload.trend,
    payload.trendReset !== false,
  );
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
  if (message) state.renewableControl.lastStatus = message;
  refreshRenewableControlState({
    preview: false,
    render: currentPageName() === "renewable",
  });
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

function renewableRowControlPointPower(row = {}, value = null) {
  const numeric = optionalNumber(value);
  if (numeric === null) return null;
  return row.set_type === "p_dc_set" ? -numeric : numeric;
}

function renewableTopologyCellText(value) {
  if (Array.isArray(value)) return value.length ? value.map((item) => renewableTopologyCellText(item)).join(" -> ") : "--";
  const text = String(value ?? "").trim();
  return text || "--";
}

function renewableConverterPathText(row = {}) {
  if (!Array.isArray(row.converterPath) || !row.converterPath.length) return "--";
  const names = row.converterPath.map((device) => (
    Array.isArray(device)
      ? device[1]
      : device?.dev_name ?? device?.devName ?? device?.name ?? device
  ));
  return names.map((name) => String(name ?? "").trim()).filter(Boolean).join(" -> ") || "--";
}

function renewableIndirectControlText(row = {}) {
  const devices = Array.isArray(row.indirectControlDevices) ? row.indirectControlDevices : [];
  if (!devices.length) return "--";
  return devices.map((device) => (
    Array.isArray(device)
      ? device[1]
      : device?.dev_name ?? device?.devName ?? device?.name ?? device
  )).map((name) => String(name ?? "").trim()).filter(Boolean).join(" -> ") || "--";
}

function renewableRowBoundaryText(row = {}) {
  if (row.category === "柴油发电") return `下限 ${formatNumber(row.minKw)} / 容量 ${formatNumber(row.capacityKw)}`;
  if (String(row.category || "").includes("储能")) return `充 ${formatNumber(row.chargePower)} / 放 ${formatNumber(row.dischargePower)}`;
  if (row.category === "交直流变流器") return Number.isFinite(row.transferCapacityKw)
    ? `${formatNumber(row.transferCapacityKw)} kW`
    : "--";
  if (Number.isFinite(row.availableKw)) return `${formatNumber(row.availableKw)} kW`;
  if (Number.isFinite(row.capacityKw)) return `${formatNumber(row.capacityKw)} kW`;
  return "--";
}

function renewableRowStatusLabel(row = {}) {
  if (row.connectionStatusLabel) return row.connectionStatusLabel;
  if (row.statusLabel) return row.statusLabel;
  if (row.online) return "可控";
  if (row.activelyConnected === false) return "当前断开";
  return "停用";
}

function renewableTopologyTitle(text) {
  return text === "--" ? "" : text;
}

function renewableStrategyRows(plan, tabKey = state.renewableControl.strategyTab) {
  const normalizedTab = RENEWABLE_STRATEGY_TABS[tabKey] ? tabKey : "ac-wind";
  const categories = RENEWABLE_STRATEGY_TABS[normalizedTab].categories;
  return (plan?.commandRows || []).filter((row) => categories.has(row.category));
}

function renderRenewableStrategyTabs(plan) {
  const requestedTab = state.renewableControl.strategyTab;
  const activeTab = RENEWABLE_STRATEGY_TABS[requestedTab] ? requestedTab : "ac-wind";
  state.renewableControl.strategyTab = activeTab;
  document.querySelectorAll("[data-renewable-strategy-tab]").forEach((button) => {
    const tabKey = button.dataset.renewableStrategyTab || "";
    const tab = RENEWABLE_STRATEGY_TABS[tabKey];
    if (!tab) return;
    const active = tabKey === activeTab;
    const count = renewableStrategyRows(plan, tabKey).length;
    button.textContent = tab.label;
    button.title = `${tab.label}：${count} 台设备`;
    button.setAttribute("aria-label", `${tab.label}，${count} 台设备`);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

function renewableControlLogs() {
  return Array.isArray(state.renewableControl.logs) ? state.renewableControl.logs : [];
}

function renewableControlLogBySeq(seq) {
  const normalizedSeq = Number(seq) || 0;
  return renewableControlLogs().find((item) => (Number(item?.seq) || 0) === normalizedSeq) || null;
}

function renewableControlLogSummaryText(item = {}) {
  const detail = runtimeLogDetailText(item.detail).trim();
  if (!detail) return "--";
  const parts = detail.split(/[；\n]+/).map((part) => part.trim()).filter(Boolean);
  const preferred = parts.find((part) => /^(控制结果|告警|指令|撤销|下发)/.test(part));
  const summary = preferred || parts[0] || detail;
  return summary.length > 140 ? `${summary.slice(0, 137)}...` : summary;
}

function renewableControlLogDetailLines(item = {}) {
  const source = Array.isArray(item.full_detail)
    ? item.full_detail
    : item.full_detail !== undefined && item.full_detail !== null
      ? [item.full_detail]
      : Array.isArray(item.detail)
        ? item.detail
        : String(item.detail || "").split(/[；\n]+/);
  const lines = source.map((line) => String(line || "").trim()).filter(Boolean);
  return lines.length ? lines : ["该条日志没有附加决策详情。"];
}

function selectRenewableControlLogRow(seq) {
  const normalizedSeq = Number(seq) || 0;
  if (!renewableControlLogBySeq(normalizedSeq)) return false;
  state.renewableControl.selectedLogSeq = normalizedSeq;
  document.querySelectorAll("#renewableControlLogTable [data-renewable-log-seq]").forEach((row) => {
    const selected = (Number(row.dataset.renewableLogSeq) || 0) === normalizedSeq;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", String(selected));
  });
  return true;
}

function openRenewableControlLogDetailDialog(seq) {
  const item = renewableControlLogBySeq(seq);
  const dialog = $("renewableControlLogDetailDialog");
  const meta = $("renewableControlLogDetailMeta");
  const body = $("renewableControlLogDetailBody");
  if (!item || !dialog || !meta || !body) return;
  selectRenewableControlLogRow(item.seq);
  $("renewableControlLogDetailSequence").textContent = `日志 #${Number(item.seq) || "--"}`;
  meta.innerHTML = `
    <div><dt>本机时刻</dt><dd>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</dd></div>
    <div><dt>仿真时刻</dt><dd>${escapeHtml(item.simu_time || "--")}</dd></div>
    <div><dt>类型</dt><dd>${escapeHtml(item.type || "--")}</dd></div>
    <div><dt>结果</dt><dd class="is-${escapeHtml(item.level || "info")}">${escapeHtml(item.result || "--")}</dd></div>`;
  body.innerHTML = renewableControlLogDetailLines(item)
    .map((line) => `<li><span>${escapeHtml(line)}</span></li>`)
    .join("");
  if (!dialog.open) dialog.showModal();
}

function closeRenewableControlLogDetailDialog() {
  const dialog = $("renewableControlLogDetailDialog");
  if (dialog?.open) dialog.close();
}

function renderRenewableMetricTabs() {
  const allowedTabs = new Set(["ac", "dc", "system", "hydrogen"]);
  const activeTab = allowedTabs.has(state.renewableControl.metricTab)
    ? state.renewableControl.metricTab
    : "ac";
  state.renewableControl.metricTab = activeTab;
  document.querySelectorAll("[data-renewable-metric-tab]").forEach((button) => {
    const active = button.dataset.renewableMetricTab === activeTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-renewable-metric-pane]").forEach((pane) => {
    const active = pane.dataset.renewableMetricPane === activeTab;
    pane.hidden = !active;
    pane.classList.toggle("is-active", active);
  });
}

function renderRenewableControlParameterTabs(requestedTab = "") {
  const allowedTabs = new Set(["runtime", "protection", "hydrogen", "optimization"]);
  const currentTab = state.renewableControl.parameterTab;
  const activeTab = allowedTabs.has(requestedTab)
    ? requestedTab
    : allowedTabs.has(currentTab)
      ? currentTab
      : "runtime";
  state.renewableControl.parameterTab = activeTab;
  document.querySelectorAll("[data-renewable-parameter-tab]").forEach((button) => {
    const active = button.dataset.renewableParameterTab === activeTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-renewable-parameter-pane]").forEach((pane) => {
    const active = pane.dataset.renewableParameterPane === activeTab;
    pane.hidden = !active;
    pane.classList.toggle("is-active", active);
    if (active) pane.scrollTop = 0;
  });
}

function renderRenewableDetailTabs() {
  const requestedTab = state.renewableControl.detailTab;
  const activeTab = ["trend", "logs", "performance"].includes(requestedTab)
    ? requestedTab
    : "trend";
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
  } else if (activeTab === "performance") {
    renderRenewablePerformanceDiagnostics();
  } else {
    requestAnimationFrame(drawRenewableTrendChart);
  }
}

function renewablePerformanceMsText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (number < 1) return `${number.toFixed(3)} ms`;
  if (number < 100) return `${number.toFixed(2)} ms`;
  return `${number.toFixed(1)} ms`;
}

function renderRenewablePerformanceDiagnostics() {
  const summary = $("renewablePerformanceSummary");
  const solverNode = $("renewableSolverDiagnostics");
  const tableNode = $("renewablePerformanceTable");
  if (!summary || !solverNode || !tableNode) return;
  const diagnostics = state.renewableControl.performanceDiagnostics;
  const sampleCount = Number(diagnostics?.sampleCount) || 0;
  summary.textContent = `${sampleCount} 个周期 · 窗口 ${Number(diagnostics?.historyLimit) || 120}`;
  if (!sampleCount || !diagnostics?.latest) {
    solverNode.innerHTML = "";
    tableNode.innerHTML = '<div class="empty-state compact">暂无控制周期性能数据</div>';
    return;
  }

  const latest = diagnostics.latest || {};
  const solver = latest.solver && typeof latest.solver === "object" ? latest.solver : {};
  const islandCount = Number(solver.islandCount) || 0;
  const solvedIslandCount = Number(solver.solvedIslandCount) || 0;
  const unassignedDeviceCount = Number(solver.unassignedDeviceCount) || 0;
  const dispatchText = !latest.dispatchAttempted
    ? "未下发"
    : latest.dispatchSuccess === true
      ? "成功"
      : latest.dispatchSuccess === false
        ? "失败"
        : "处理中";
  const solverStatus = unassignedDeviceCount > 0
    ? "存在未分配设备"
    : islandCount <= 0
    ? "无优化问题"
    : solver.success === false
      ? "失败"
      : "成功";
  solverNode.innerHTML = `
    <dl class="renewable-solver-diagnostic-grid">
      <div><dt>求解状态</dt><dd class="${solver.success === false ? "is-error" : "is-ok"}">${escapeHtml(solverStatus)}</dd></div>
      <div><dt>求解迭代</dt><dd>${Math.max(0, Number(solver.iterations) || 0)}</dd></div>
      <div><dt>拓扑岛</dt><dd>${solvedIslandCount} / ${islandCount}</dd></div>
      <div><dt>变量</dt><dd>${Math.max(0, Number(solver.variableCount) || 0)}</dd></div>
      <div><dt>约束</dt><dd>${Math.max(0, Number(solver.constraintCount) || 0)}</dd></div>
      <div><dt>边界</dt><dd>${Math.max(0, Number(solver.boundCount) || 0)}</dd></div>
      <div><dt>未分配设备</dt><dd class="${unassignedDeviceCount > 0 ? "is-error" : ""}">${Math.max(0, unassignedDeviceCount)}</dd></div>
      <div><dt>指令下发</dt><dd>${escapeHtml(dispatchText)}</dd></div>
      <div><dt>仿真时刻</dt><dd>${escapeHtml(latest.simulationTime || "--")}</dd></div>
    </dl>
  `;

  const labels = {
    exchangeRequestMs: "实时帧 HTTP 请求",
    exchangeProcessingMs: "实时帧合并处理",
    exchangePublishMs: "实时帧快照发布",
    exchangeTotalMs: "实时通信总耗时",
    snapshotReceiveMs: "快照接收",
    snapshotValidationMs: "快照校验与复制",
    inputProcessingMs: "量测与输入整理",
    topologyAnalysisMs: "拓扑分析",
    strategyPreparationMs: "优化前策略准备",
    optimizationBuildMs: "优化问题构建",
    optimizationSolveMs: "SciPy 求解",
    storageBalanceMs: "储能均衡",
    optimizationPostprocessMs: "优化结果后处理",
    optimizationTotalMs: "优化器总耗时",
    strategyPostprocessMs: "策略与指令后处理",
    strategyComputeMs: "控制计划计算总计",
    trendPostprocessMs: "趋势数据整理",
    commandSerializeMs: "指令序列化",
    commandDispatchMs: "指令下发通信",
    cycleTotalMs: "控制周期总耗时",
  };
  const order = Object.keys(labels);
  const phaseStats = diagnostics.phaseStats && typeof diagnostics.phaseStats === "object"
    ? diagnostics.phaseStats
    : {};
  const rows = order
    .filter((key) => phaseStats[key])
    .map((key) => {
      const item = phaseStats[key] || {};
      return `
        <tr class="${["exchangeTotalMs", "optimizationTotalMs", "strategyComputeMs", "cycleTotalMs"].includes(key) ? "is-total" : ""}">
          <th scope="row">${escapeHtml(labels[key])}</th>
          <td>${renewablePerformanceMsText(item.latestMs)}</td>
          <td>${renewablePerformanceMsText(item.p50Ms)}</td>
          <td>${renewablePerformanceMsText(item.p95Ms)}</td>
          <td>${renewablePerformanceMsText(item.maxMs)}</td>
        </tr>
      `;
    })
    .join("");
  tableNode.innerHTML = rows
    ? `
      <table class="renewable-performance-table">
        <thead><tr><th>阶段</th><th>最新</th><th>P50</th><th>P95</th><th>最大</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `
    : '<div class="empty-state compact">当前周期没有可统计的分项耗时</div>';
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
  const selectedLogSeq = Number(state.renewableControl.selectedLogSeq) || 0;
  const renderKey = `${page}|${logs.length}|${pageLogs.map((item) => item.seq).join(",")}|${selectedLogSeq}`;
  if (renderKey === state.renewableControl.lastControlLogRenderKey) return;
  state.renewableControl.lastControlLogRenderKey = renderKey;
  if (!pageLogs.length) {
    table.innerHTML = '<div class="empty-state compact">暂无新能源控制日志</div>';
    return;
  }
  table.innerHTML = `
    <table class="runtime-log-table renewable-control-log-table">
      <thead><tr><th>本机时刻</th><th>仿真时刻</th><th>类型</th><th>结果</th><th>决策摘要</th></tr></thead>
      <tbody>
        ${pageLogs.map((item) => `
          <tr class="runtime-log-row is-${escapeHtml(item.level || "info")}${Number(item.seq) === selectedLogSeq ? " is-selected" : ""}" data-renewable-log-seq="${escapeHtml(item.seq)}" tabindex="0" aria-selected="${Number(item.seq) === selectedLogSeq}" aria-label="日志 ${escapeHtml(item.seq)}，双击查看详细决策过程">
            <td>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time || "--")}</td>
            <td>${escapeHtml(item.type || "")}</td>
            <td>${escapeHtml(item.result || "")}</td>
            <td class="runtime-log-detail" title="${escapeHtml(renewableControlLogSummaryText(item))}">${escapeHtml(renewableControlLogSummaryText(item))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renewableTrendWindowRange() {
  const history = state.renewableTrendHistory || [];
  const windowMinutes = Math.max(1, Number(state.renewableTrendWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("renewableTrend"),
    curveDisplayModeDurationMinutes(),
  );
  setChartPeriodOffset("renewableTrend", range.windowOffset);
  return range;
}

function renewableTrendWindowPoints(range = renewableTrendWindowRange()) {
  return traceWindowRealPoints(state.renewableTrendHistory || [], range);
}

function renewableMetricCount(metrics = {}, keys = []) {
  for (const key of keys) {
    const raw = metrics?.[key];
    if (raw === null || raw === undefined || raw === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return Math.max(0, value);
  }
  return null;
}

function renewableMetricGroupCount(metrics = {}, group = "") {
  const directKeys = {
    "ac-renewable": ["onlineAcRenewableCount"],
    "dc-renewable": ["onlineDcRenewableCount"],
    "ac-wind": ["onlineAcWindCount"],
    "dc-wind": ["onlineDcWindCount"],
    "ac-pv": ["onlineAcPvCount"],
    "dc-pv": ["onlineDcPvCount"],
    "ac-grid-following-storage": ["onlineAcGridFollowingStorageCount"],
    "dc-grid-following-storage": ["onlineDcGridFollowingStorageCount"],
    "ac-grid-forming-storage": ["onlineAcGridFormingStorageCount", "onlineAcBalanceStorageCount"],
    "dc-grid-forming-storage": ["onlineDcGridFormingStorageCount", "onlineDcBalanceStorageCount"],
    "ac-diesel": ["onlineAcDieselCount"],
    "dc-diesel": ["onlineDcDieselCount"],
    "ac-load": ["onlineAcLoadCount"],
    "dc-load": ["onlineDcLoadCount"],
    "system-acdc": ["onlineAcdcConverterCount", "storageConverterCount"],
    "hydrogen-electrolyzer": ["onlineElectrolyzerCount"],
    "hydrogen-fuel-cell": ["onlineFuelCellCount"],
    "hydrogen-storage": ["onlineHydrogenStorageCount"],
  };
  if (directKeys[group]) return renewableMetricCount(metrics, directKeys[group]);
  const aggregateGroups = {
    "system-renewable": ["ac-renewable", "dc-renewable"],
    "system-wind": ["ac-wind", "dc-wind"],
    "system-pv": ["ac-pv", "dc-pv"],
    "system-grid-following-storage": ["ac-grid-following-storage", "dc-grid-following-storage"],
    "system-grid-forming-storage": ["ac-grid-forming-storage", "dc-grid-forming-storage"],
    "system-diesel": ["ac-diesel", "dc-diesel"],
    "system-load": ["ac-load", "dc-load"],
  };
  const childGroups = aggregateGroups[group];
  if (!childGroups) return null;
  const counts = childGroups
    .map((childGroup) => renewableMetricGroupCount(metrics, childGroup))
    .filter((count) => count !== null);
  return counts.length ? counts.reduce((sum, count) => sum + count, 0) : null;
}

function renewableMetricGroupConfiguredCount(metrics = {}, group = "") {
  const directKeys = {
    "ac-grid-following-storage": ["acGridFollowingStorageCount"],
    "dc-grid-following-storage": ["dcGridFollowingStorageCount"],
    "ac-grid-forming-storage": ["acGridFormingStorageCount"],
    "dc-grid-forming-storage": ["dcGridFormingStorageCount"],
  };
  if (directKeys[group]) return renewableMetricCount(metrics, directKeys[group]);
  const aggregateGroups = {
    "system-grid-following-storage": ["ac-grid-following-storage", "dc-grid-following-storage"],
    "system-grid-forming-storage": ["ac-grid-forming-storage", "dc-grid-forming-storage"],
  };
  const childGroups = aggregateGroups[group];
  if (!childGroups) return null;
  const counts = childGroups
    .map((childGroup) => renewableMetricGroupConfiguredCount(metrics, childGroup))
    .filter((count) => count !== null);
  return counts.length ? counts.reduce((sum, count) => sum + count, 0) : null;
}

function renewableMetricGroupAvailable(metrics = {}, group = "") {
  const count = renewableMetricGroupCount(metrics, group);
  return count === null || count > 0;
}

function renderRenewableMetricAvailability(metrics = {}) {
  document.querySelectorAll("[data-renewable-metric-group]").forEach((card) => {
    const alwaysVisible = card.dataset.renewableMetricAlways === "true";
    card.hidden = !alwaysVisible
      && !renewableMetricGroupAvailable(metrics, card.dataset.renewableMetricGroup || "");
  });
}

function renderRenewableTrendSeriesTree() {
  const container = $("renewableTrendSeriesGroups");
  if (!container || container.dataset.rendered === "true") return;
  const treeHtml = RENEWABLE_TREND_SCOPE_DEFS.map((scope) => {
    const devices = [];
    RENEWABLE_TREND_SERIES_DEFS
      .filter((series) => series.scope === scope.key)
      .forEach((series) => {
        let device = devices.find((candidate) => candidate.key === series.device);
        if (!device) {
          device = { key: series.device, label: series.deviceLabel, series: [] };
          devices.push(device);
        }
        device.series.push(series);
      });
    const deviceHtml = devices.map((device) => {
      const seriesHtml = device.series.map((series) => {
        const checked = RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES.has(series.key) ? " checked" : "";
        const styleClass = `is-${series.style || "power"}`;
        const searchText = [
          scope.label,
          device.label,
          series.curveLabel,
          series.label,
          series.key,
          series.metricId,
        ].filter(Boolean).join(" ");
        return `
          <label
            class="renewable-trend-series-item"
            data-renewable-series-group="${escapeHtml(series.group)}"
            data-renewable-series-metric="${escapeHtml(series.metricId)}"
            data-renewable-series-search="${escapeHtml(searchText)}"
            title="${escapeHtml(series.label)}"
          >
            <input type="checkbox" data-chart-toggle="renewableTrend" data-chart-series="${escapeHtml(series.key)}"${checked} />
            <i class="renewable-trend-series-swatch ${styleClass}" style="--renewable-series-color: ${escapeHtml(series.color)}"></i>
            <span>${escapeHtml(series.curveLabel)}</span>
          </label>
        `;
      }).join("");
      return `
        <details class="renewable-trend-series-device" data-renewable-series-device="${escapeHtml(device.key)}">
          <summary><span>${escapeHtml(device.label)}</span><small>${device.series.length}</small></summary>
          <div class="renewable-trend-series-list">${seriesHtml}</div>
        </details>
      `;
    }).join("");
    const open = scope.key === "ac" ? " open" : "";
    return `
      <details class="renewable-trend-series-group" data-renewable-series-scope="${escapeHtml(scope.key)}"${open}>
        <summary><span>${escapeHtml(scope.label)}</span><small>${devices.length}</small></summary>
        <div class="renewable-trend-series-devices">${deviceHtml}</div>
      </details>
    `;
  }).join("");
  container.innerHTML = `${treeHtml}
    <div id="renewableTrendSeriesEmpty" class="renewable-trend-series-empty" hidden>没有匹配的曲线</div>
  `;
  container.dataset.rendered = "true";
}

function ensureRenewableTrendSeriesSelection(seriesDefs = []) {
  const chartKey = "renewableTrend";
  if (Object.prototype.hasOwnProperty.call(state.chartSeriesHidden || {}, chartKey)) return;
  state.chartSeriesHidden = {
    ...(state.chartSeriesHidden || {}),
    [chartKey]: seriesDefs
      .filter((series) => !RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES.has(series.key))
      .map((series) => series.key),
  };
}

function renewableTrendSeriesAvailable(series = {}, metrics = {}) {
  return renewableMetricGroupAvailable(metrics, series.group || "");
}

function renewableTrendSeriesFilterText(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .trim()
    .toLocaleLowerCase("zh-CN");
}

function renewableTrendBatchSeriesInputs(metrics = {}) {
  renderRenewableTrendSeriesTree();
  const query = renewableTrendSeriesFilterText(state.renewableTrendSeriesFilter);
  return Array.from(document.querySelectorAll(".renewable-trend-series-item"))
    .map((item) => {
      const input = item.querySelector('input[data-chart-toggle="renewableTrend"]');
      const available = renewableMetricGroupAvailable(
        metrics,
        item.dataset.renewableSeriesGroup || "",
      );
      const searchText = renewableTrendSeriesFilterText(item.dataset.renewableSeriesSearch || "");
      const keywordMatches = !query || searchText.includes(query);
      return input && available && keywordMatches ? input : null;
    })
    .filter(Boolean);
}

function setRenewableTrendBatchSeriesVisibility(visible, metrics = {}) {
  const chartKey = "renewableTrend";
  const inputs = renewableTrendBatchSeriesInputs(metrics);
  if (!inputs.length) {
    applyRenewableTrendSeriesFilters(metrics);
    return;
  }
  const hidden = chartHiddenSet(chartKey);
  const legendHidden = chartLegendHiddenSet(chartKey);
  inputs.forEach((input) => {
    const seriesKey = input.dataset.chartSeries || "";
    if (!seriesKey) return;
    if (visible) hidden.delete(seriesKey);
    else hidden.add(seriesKey);
    legendHidden.delete(seriesKey);
  });
  state.chartSeriesHidden = {
    ...(state.chartSeriesHidden || {}),
    [chartKey]: Array.from(hidden),
  };
  state.chartLegendSeriesHidden = {
    ...(state.chartLegendSeriesHidden || {}),
    [chartKey]: Array.from(legendHidden),
  };

  const selectedKey = selectedChartSeriesKey(chartKey);
  if (visible && (!selectedKey || hidden.has(selectedKey))) {
    state.chartSeriesSelected = {
      ...(state.chartSeriesSelected || {}),
      [chartKey]: inputs[0].dataset.chartSeries || "",
    };
  } else if (!visible && inputs.some((input) => input.dataset.chartSeries === selectedKey)) {
    const fallback = RENEWABLE_TREND_SERIES_DEFS.find((series) => (
      renewableTrendSeriesAvailable(series, metrics) && !hidden.has(series.key)
    ));
    state.chartSeriesSelected = {
      ...(state.chartSeriesSelected || {}),
      [chartKey]: fallback?.key || "",
    };
  }
  syncChartLegendButtons(chartKey);
  drawRenewableTrendChart();
}

function applyRenewableTrendSeriesFilters(metrics = {}) {
  renderRenewableTrendSeriesTree();
  const filterInput = $("renewableTrendSeriesFilter");
  const selectedOnlyInput = $("renewableTrendSelectedOnly");
  const clearAllButton = $("renewableTrendClearAll");
  const selectAllButton = $("renewableTrendSelectAll");
  const query = renewableTrendSeriesFilterText(state.renewableTrendSeriesFilter);
  const selectedOnly = Boolean(state.renewableTrendSelectedOnly);
  if (filterInput && filterInput.value !== state.renewableTrendSeriesFilter) {
    filterInput.value = state.renewableTrendSeriesFilter;
  }
  if (selectedOnlyInput) selectedOnlyInput.checked = selectedOnly;

  const items = Array.from(document.querySelectorAll(".renewable-trend-series-item"));
  let visibleCount = 0;
  items.forEach((item) => {
    const input = item.querySelector('input[data-chart-toggle="renewableTrend"]');
    const available = renewableMetricGroupAvailable(
      metrics,
      item.dataset.renewableSeriesGroup || "",
    );
    const searchText = renewableTrendSeriesFilterText(item.dataset.renewableSeriesSearch || "");
    if (!input) {
      item.hidden = true;
      return;
    }
    const keywordMatches = !query || searchText.includes(query);
    const selectionMatches = !selectedOnly || input.checked;
    item.hidden = !available || !keywordMatches || !selectionMatches;
    if (!item.hidden) visibleCount += 1;
  });

  const batchInputs = renewableTrendBatchSeriesInputs(metrics);
  const batchSelectedCount = batchInputs.filter((input) => input.checked).length;
  if (clearAllButton) {
    clearAllButton.disabled = batchInputs.length === 0 || batchSelectedCount === 0;
  }
  if (selectAllButton) {
    selectAllButton.disabled = batchInputs.length === 0 || batchSelectedCount === batchInputs.length;
  }

  const filterActive = Boolean(query || selectedOnly);
  document.querySelectorAll(".renewable-trend-series-device").forEach((device) => {
    const hasVisibleSeries = Array.from(device.querySelectorAll(".renewable-trend-series-item"))
      .some((item) => !item.hidden);
    device.hidden = !hasVisibleSeries;
    if (hasVisibleSeries && filterActive) device.open = true;
  });
  document.querySelectorAll(".renewable-trend-series-group").forEach((scope) => {
    const hasVisibleDevice = Array.from(scope.querySelectorAll(".renewable-trend-series-device"))
      .some((device) => !device.hidden);
    scope.hidden = !hasVisibleDevice;
    if (hasVisibleDevice && filterActive) scope.open = true;
  });

  const empty = $("renewableTrendSeriesEmpty");
  if (empty) {
    empty.textContent = filterActive ? "没有匹配的曲线" : "暂无可用曲线";
    empty.hidden = visibleCount > 0;
  }
}

function renderRenewableTrendSeriesAvailability(metrics = {}) {
  renderRenewableTrendSeriesTree();
  const chartKey = "renewableTrend";
  const items = Array.from(document.querySelectorAll(".renewable-trend-series-item"));
  const availableInputs = [];
  items.forEach((item) => {
    const group = item.dataset.renewableSeriesGroup || "";
    const available = renewableMetricGroupAvailable(metrics, group);
    const input = item.querySelector(`input[data-chart-toggle="${chartKey}"]`);
    if (!input) return;
    input.disabled = !available;
    input.checked = !isChartSeriesHidden(chartKey, input.dataset.chartSeries || "");
    item.classList.toggle("is-hidden", !input.checked);
    item.classList.toggle(
      "is-selected",
      selectedChartSeriesKey(chartKey) === (input.dataset.chartSeries || ""),
    );
    if (available) availableInputs.push(input);
  });
  const selectedCount = availableInputs.filter((input) => input.checked).length;
  const summary = $("renewableTrendSeriesSummary");
  if (summary) summary.textContent = `${selectedCount} / ${availableInputs.length}`;
  applyRenewableTrendSeriesFilters(metrics);
}

function renewableTrendAxisScale(values = [], series = [], unit = "") {
  const numericValues = values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const onlySoc = unit === "%" && series.length > 0 && series.every((item) => item.style === "soc");
  if (onlySoc) return { min: 0, max: 100, tickSuffix: "%" };
  const includeZero = unit === "kW";
  if (!numericValues.length) {
    return includeZero
      ? { min: -1, max: 1, tickSuffix: "" }
      : { min: 0, max: 1, tickSuffix: unit === "%" ? "%" : "" };
  }
  let minimum = Math.min(...numericValues);
  let maximum = Math.max(...numericValues);
  if (Math.abs(maximum - minimum) < 1e-9) {
    const expansion = Math.max(Math.abs(maximum) * 0.08, includeZero ? 1 : 0.1);
    minimum -= expansion;
    maximum += expansion;
  }
  if (includeZero) {
    minimum = Math.min(0, minimum);
    maximum = Math.max(0, maximum);
  }
  const padding = Math.max((maximum - minimum) * 0.08, includeZero ? 1 : 0.01);
  minimum = !includeZero && minimum >= 0 ? Math.max(0, minimum - padding) : minimum - padding;
  maximum += padding;
  if (Math.abs(maximum - minimum) < 1e-9) maximum = minimum + 1;
  return { min: minimum, max: maximum, tickSuffix: unit === "%" ? "%" : "" };
}

function renewableTrendAxisGroups(points = [], visibleSeries = [], selectedSeriesKey = "") {
  const grouped = { left: [], right: [] };
  const byAxisKey = new Map();
  visibleSeries.forEach((series) => {
    const side = series.axis === "right" ? "right" : "left";
    const unit = String(series.unit || "数值").trim() || "数值";
    const key = `${side}|${unit}`;
    let group = byAxisKey.get(key);
    if (!group) {
      group = { key, side, unit, series: [] };
      byAxisKey.set(key, group);
      grouped[side].push(group);
    }
    group.series.push(series);
  });
  ["left", "right"].forEach((side) => {
    grouped[side].forEach((group) => {
      const values = points.flatMap((point) => group.series.map((series) => {
        const rawValue = point?.[series.field];
        return rawValue === null || rawValue === undefined || rawValue === ""
          ? Number.NaN
          : Number(rawValue);
      }))
        .filter((value) => Number.isFinite(value));
      const scale = renewableTrendAxisScale(values, group.series, group.unit);
      const selectedSeries = group.series.find((series) => series.key === selectedSeriesKey);
      Object.assign(group, scale, {
        values,
        seriesKeys: group.series.map((series) => series.key),
        active: Boolean(selectedSeries),
        color: selectedSeries?.color || group.series[0]?.color || "#63717a",
      });
    });
  });
  return grouped;
}

function renewableTrendChartLayout(leftAxisCount = 0, rightAxisCount = 0) {
  const axisSlot = 58;
  const edgePadding = 14;
  const left = leftAxisCount > 0 ? edgePadding + leftAxisCount * axisSlot : 24;
  const right = rightAxisCount > 0 ? edgePadding + rightAxisCount * axisSlot : 24;
  const minPlotWidth = 280;
  return {
    axisSlot,
    left,
    right,
    top: 30,
    bottom: 38,
    minCanvasWidth: Math.max(640, left + right + minPlotWidth),
  };
}

function renewableTrendAxisY(axis, value, top, plotHeight) {
  const span = Math.max(1e-9, axis.max - axis.min);
  const normalized = (clamp(value, axis.min, axis.max) - axis.min) / span;
  return top + plotHeight - normalized * plotHeight;
}

function drawRenewableTrendAxes(ctx, axisGroups, plotBounds, ratio) {
  const { left, right, top, plotHeight, axisSlot } = plotBounds;
  const maxAxisOffset = (side) => Math.max(0, ((axisGroups[side] || []).length - 1) * axisSlot);
  ["left", "right"].forEach((side) => {
    (axisGroups[side] || []).forEach((axis, index) => {
      const direction = side === "left" ? -1 : 1;
      const axisX = side === "left"
        ? left - maxAxisOffset(side) + index * axisSlot
        : right + maxAxisOffset(side) - index * axisSlot;
      const axisColor = axis.active ? axis.color : "#829198";
      ctx.save();
      ctx.globalAlpha = axis.active ? 1 : 0.58;
      ctx.strokeStyle = axisColor;
      ctx.fillStyle = axisColor;
      ctx.lineWidth = (axis.active ? 1.8 : 1) * ratio;
      ctx.beginPath();
      ctx.moveTo(axisX, top);
      ctx.lineTo(axisX, top + plotHeight);
      ctx.stroke();
      ctx.font = `${axis.active ? "700 " : ""}${10 * ratio}px Consolas, Microsoft YaHei, Arial`;
      ctx.textAlign = side === "left" ? "right" : "left";
      ctx.fillText(axis.unit, axisX + direction * 6 * ratio, top - 13 * ratio);
      for (let tickIndex = 0; tickIndex <= 4; tickIndex += 1) {
        const fraction = tickIndex / 4;
        const y = top + plotHeight * fraction;
        const value = axis.max - (axis.max - axis.min) * fraction;
        ctx.beginPath();
        ctx.moveTo(axisX, y);
        ctx.lineTo(axisX + direction * 5 * ratio, y);
        ctx.stroke();
        ctx.fillText(
          `${formatNumber(value)}${axis.tickSuffix}`,
          axisX + direction * 8 * ratio,
          y + 4 * ratio,
        );
      }
      ctx.restore();
    });
  });
}

function renewableTrendAxisSummary(axisGroups = { left: [], right: [] }) {
  const describe = (side) => (axisGroups[side] || []).map((axis) => axis.unit).join("、") || "无";
  const active = [...(axisGroups.left || []), ...(axisGroups.right || [])].find((axis) => axis.active);
  const activeText = active ? ` · 当前${active.side === "left" ? "左" : "右"}轴 ${active.unit}` : "";
  return `左轴 ${describe("left")} · 右轴 ${describe("right")}${activeText}`;
}

function renderRenewableTrendLegend(selectedSeries = []) {
  const legend = $("renewableTrendLegend");
  if (!legend) return;
  const seriesKeys = selectedSeries.map((series) => series.key).join("|");
  if (legend.dataset.seriesKeys !== seriesKeys) {
    const fragment = document.createDocumentFragment();
    selectedSeries.forEach((series) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "renewable-trend-inline-legend-item";
      item.dataset.chartToggle = "renewableTrend";
      item.dataset.chartSeries = series.key;
      item.dataset.chartLegendLabel = series.label;
      item.dataset.chartLegendVisibility = "true";
      item.style.setProperty("--renewable-series-color", series.color || "#23854a");
      const swatch = document.createElement("i");
      swatch.className = `renewable-trend-inline-legend-swatch${series.style ? ` is-${series.style}` : ""}`;
      swatch.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.textContent = series.label;
      item.append(swatch, label);
      fragment.appendChild(item);
    });
    legend.replaceChildren(fragment);
    legend.dataset.seriesKeys = seriesKeys;
  }
  legend.hidden = !selectedSeries.length;
  syncChartLegendButtons("renewableTrend");
}

function drawRenewableTrendChart() {
  const canvas = $("renewableTrendChart");
  if (!canvas) return;
  const chartKey = "renewableTrend";
  const range = renewableTrendWindowRange();
  syncChartPeriodNavigation("renewableTrend", range);
  const points = renewableTrendWindowPoints(range);
  ensureRenewableTrendSeriesSelection(RENEWABLE_TREND_SERIES_DEFS);
  const metrics = state.renewableControl.lastPlan?.metrics || {};
  const availableSeries = RENEWABLE_TREND_SERIES_DEFS.filter((series) => renewableTrendSeriesAvailable(series, metrics));
  const selectedSeries = visibleChartSeries(chartKey, availableSeries);
  const visibleSeries = visibleChartLegendSeries(chartKey, selectedSeries);
  const requestedSeriesKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const selectedSeriesKey = visibleSeries.some((series) => series.key === requestedSeriesKey)
    ? requestedSeriesKey
    : visibleSeries[0]?.key || "";
  if (selectedSeriesKey && requestedSeriesKey !== selectedSeriesKey) {
    state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: selectedSeriesKey };
  }
  const axisGroups = renewableTrendAxisGroups(points, visibleSeries, selectedSeriesKey);
  const layout = renewableTrendChartLayout(axisGroups.left.length, axisGroups.right.length);
  canvas.style.minWidth = `${layout.minCanvasWidth}px`;
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);

  const left = layout.left * ratio;
  const right = layout.right * ratio;
  const top = layout.top * ratio;
  const bottom = layout.bottom * ratio;
  const plotWidth = Math.max(1, width - left - right);
  const plotHeight = Math.max(1, height - top - bottom);
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };

  renderRenewableTrendLegend(selectedSeries);
  renderRenewableTrendSeriesAvailability(metrics);

  for (let index = 0; index <= 4; index += 1) {
    const fraction = index / 4;
    const y = top + plotHeight * fraction;
    ctx.strokeStyle = index === 4 ? "#c9d6dc" : "#e2eaee";
    ctx.lineWidth = 1 * ratio;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  drawRenewableTrendAxes(ctx, axisGroups, {
    left,
    right: width - right,
    top,
    plotHeight,
    axisSlot: layout.axisSlot * ratio,
  }, ratio);

  const xTicks = measurementTraceAxisTicks(range, plotWidth / ratio);
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
  if (summary) {
    const summaryText = `${traceWindowDataPointCount(points)} 点 · ${renewableTrendAxisSummary(axisGroups)}`;
    summary.textContent = summaryText;
    summary.title = summaryText;
  }
  if (!points.length || !visibleSeries.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    const emptyText = !selectedSeries.length
      ? "未选择曲线"
      : !visibleSeries.length
        ? "图例已隐藏全部曲线"
        : "暂无综合趋势数据";
    ctx.fillText(emptyText, width / 2, height / 2);
    return;
  }

  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
  const axisBySeriesKey = new Map();
  [...axisGroups.left, ...axisGroups.right].forEach((axis) => {
    axis.seriesKeys.forEach((seriesKey) => axisBySeriesKey.set(seriesKey, axis));
  });
  const hitData = [];
  visibleSeries.forEach((series) => {
    const seriesAxis = axisBySeriesKey.get(series.key);
    if (!seriesAxis) return;
    const sampled = sampleCurvePointsForCanvas(
      points.map((point) => Number.isFinite(point[series.field]) ? point[series.field] : Number.NaN),
      plotWidth / ratio,
      1.4,
    );
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeriesKey ? 3.2 : 2.2) * ratio;
    const dashPattern = Array.isArray(series.dashPattern)
      ? series.dashPattern.map((value) => value * ratio)
      : series.dashed
        ? [7 * ratio, 5 * ratio]
        : [];
    ctx.setLineDash(dashPattern);
    ctx.beginPath();
    let started = false;
    let previousY = Number.NaN;
    sampled.forEach(({ index, value }) => {
      if (!Number.isFinite(value)) return;
      const point = points[index];
      if (!point) return;
      const x = xForMinute(point.minute);
      const y = renewableTrendAxisY(seriesAxis, value, top, plotHeight);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else if (series.style === "target") {
        ctx.lineTo(x, previousY);
        if (Math.abs(y - previousY) > 1e-9) ctx.lineTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      previousY = y;
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
    maxSeries: 10,
    inlineSeriesLabels: true,
    timeLabel: (point) => measurementTracePointTimeLabel(point, range),
    valueFormatter: formatNumber,
  });
}

function renewableMetricTotal(metrics = {}, keys = []) {
  const values = keys
    .map((key) => metrics?.[key])
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function renewableMetricValue(metrics = {}, key = "", fallbackKeys = []) {
  const raw = metrics?.[key];
  if (raw !== null && raw !== undefined && raw !== "") {
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return renewableMetricTotal(metrics, fallbackKeys);
}

function renewableMetricPowerText(value) {
  return Number.isFinite(value) ? formatNumber(value) : "--";
}

function renewableMetricNumberText(value) {
  return Number.isFinite(value) ? formatNumber(value) : "--";
}

function renewableMetricSocText(value) {
  return Number.isFinite(value) ? formatOverviewNumber(value * 100) : "--";
}

function renewableStorageUnavailableMetricText(metrics = {}, group = "") {
  const onlineCount = renewableMetricGroupCount(metrics, group);
  if (onlineCount !== null && onlineCount > 0) return "";
  const configuredCount = renewableMetricGroupConfiguredCount(metrics, group);
  if (configuredCount === 0) return "无此类设备";
  if (configuredCount !== null && configuredCount > 0 && onlineCount === 0) return "无运行设备";
  return onlineCount === 0 ? "无设备" : "";
}

function renewableStoragePowerMetricText(value, metrics = {}, group = "") {
  return renewableStorageUnavailableMetricText(metrics, group) || renewableMetricPowerText(value);
}

function renewableStorageSocMetricText(value, metrics = {}, group = "") {
  return renewableStorageUnavailableMetricText(metrics, group) || renewableMetricSocText(value);
}

function populateRenewableControlParameters(control = state.renewableControl) {
  const periodInput = $("renewableControlPeriod");
  if (periodInput) periodInput.value = String(control.intervalSeconds || 2);
  const hydrogenClosedLoopInput = $("hydrogenClosedLoopEnabled");
  if (hydrogenClosedLoopInput && document.activeElement !== hydrogenClosedLoopInput) {
    hydrogenClosedLoopInput.checked = Boolean(control.hydrogenClosedLoopEnabled);
  }
  syncRenewableControlPeriodConstraints();
  const ratioInputs = {
    renewableStepRatio: control.stepCoefficient,
    storageStepRatio: control.storageStepRatio,
    storageSocCorrectionStepScale: control.storageSocCorrectionStepScale,
    gridFormingStorageProtectionRatio: control.gridFormingStorageProtectionRatio,
    dieselPowerProtectionRatio: control.dieselPowerProtectionRatio,
    socDeadband: control.socDeadband,
    hydrogenPressureDeadbandRatio: control.hydrogenPressureDeadbandRatio,
    electrolyzerPowerMinRatio: control.electrolyzerPowerMinRatio,
    electrolyzerPowerMaxRatio: control.electrolyzerPowerMaxRatio,
    electrolyzerPowerDeadbandRatio: control.electrolyzerPowerDeadbandRatio,
    electrolyzerPowerStepRatio: control.electrolyzerPowerStepRatio,
    electrolyzerDieselPowerLimitRatio: control.electrolyzerDieselPowerLimitRatio,
    electrolyzerDieselPowerDeadbandRatio: control.electrolyzerDieselPowerDeadbandRatio,
    electrolyzerStorageSocLowerLimit: control.electrolyzerStorageSocLowerLimit,
    electrolyzerStorageSocUpperLimit: control.electrolyzerStorageSocUpperLimit,
    electrolyzerHydrogenStorageSocUpperLimit: control.electrolyzerHydrogenStorageSocUpperLimit,
    fuelCellStorageSocLimit: control.fuelCellStorageSocLimit,
    fuelCellHydrogenStorageSocUpperLimit: control.fuelCellHydrogenStorageSocUpperLimit,
    fuelCellHydrogenStorageSocLowerLimit: control.fuelCellHydrogenStorageSocLowerLimit,
    fuelCellPowerMinRatio: control.fuelCellPowerMinRatio,
    fuelCellPowerMaxRatio: control.fuelCellPowerMaxRatio,
    fuelCellPowerDeadbandRatio: control.fuelCellPowerDeadbandRatio,
    fuelCellPowerStepRatio: control.fuelCellPowerStepRatio,
    fuelCellDieselPowerLimitRatio: control.fuelCellDieselPowerLimitRatio,
  };
  Object.entries(ratioInputs).forEach(([id, value]) => {
    const input = $(id);
    if (input) input.value = String(Number(value || 0) * 100);
  });
  const commandValidInput = $("renewableCommandValidMinutes");
  if (commandValidInput) commandValidInput.value = String(control.commandValidMinutes || 120);
  const numericInputs = {
    optimizationRenewableCurtailmentWeight: control.optimizationRenewableCurtailmentWeight,
    optimizationDieselOutputWeight: control.optimizationDieselOutputWeight,
    optimizationCurtailmentSquareWeight: control.optimizationCurtailmentSquareWeight,
    optimizationSourceStorageAdjustmentSquareWeight: control.optimizationSourceStorageAdjustmentSquareWeight,
    optimizationBalanceDeltaSquareWeight: control.optimizationBalanceDeltaSquareWeight,
    optimizationBalanceDeltaWarningKw: control.optimizationBalanceDeltaWarningKw,
    optimizationBalanceToleranceKw: control.optimizationBalanceToleranceKw,
    optimizationBoundToleranceKw: control.optimizationBoundToleranceKw,
    optimizationFtol: control.optimizationFtol,
    optimizationMaxIterations: control.optimizationMaxIterations,
  };
  Object.entries(numericInputs).forEach(([id, value]) => {
    const input = $(id);
    if (input) input.value = String(value ?? "");
  });
}

function openRenewableControlParametersDialog() {
  const dialog = $("renewableControlParametersDialog");
  if (dialog && !dialog.open) {
    populateRenewableControlParameters();
    renderRenewableControlParameterTabs("runtime");
    dialog.showModal();
  }
}

function closeRenewableControlParametersDialog() {
  const dialog = $("renewableControlParametersDialog");
  if (dialog?.open) dialog.close();
}

function renewableForegroundActionPending(control = state.renewableControl) {
  return Boolean(control?.actionActive);
}

function renderRenewableControl(snapshot = state.snapshot || {}) {
  state.frontendDiagnostics.renewableRenderCount += 1;
  const control = state.renewableControl;
  const actionPending = renewableForegroundActionPending(control);
  const receiveReady = Boolean(
    state.receiveMode
    && control.receiveActive
    && control.canRun
    && !control.controlFrozen
  );
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
  button.textContent = control.desiredEnabled ? "停止实时控制" : "启动实时控制";
  button.classList.toggle("is-running", control.enabled);
  button.classList.toggle("is-pending", control.resumePending);
  button.disabled = actionPending || (!receiveReady && !control.desiredEnabled);
  button.title = !receiveReady && !control.desiredEnabled ? "请先启动接收" : "";
  if (sendOnce) {
    sendOnce.disabled = actionPending || !receiveReady;
    sendOnce.title = !receiveReady ? "请先启动接收" : "";
    sendOnce.textContent = loopMode === "closed" ? "单次计算下发" : "单次计算";
  }
  document.querySelectorAll("[data-renewable-loop-mode]").forEach((modeButton) => {
    const active = modeButton.dataset.renewableLoopMode === loopMode;
    modeButton.classList.toggle("is-active", active);
    modeButton.setAttribute("aria-pressed", String(active));
    modeButton.disabled = actionPending;
  });
  const periodInput = $("renewableControlPeriod");
  const parameterDialogOpen = Boolean($("renewableControlParametersDialog")?.open);
  if (!parameterDialogOpen && periodInput && document.activeElement !== periodInput) {
    periodInput.value = String(control.intervalSeconds || 2);
    syncRenewableControlPeriodConstraints();
  }
  const ratioInputs = {
    renewableStepRatio: control.stepCoefficient,
    storageStepRatio: control.storageStepRatio,
    storageSocCorrectionStepScale: control.storageSocCorrectionStepScale,
    gridFormingStorageProtectionRatio: control.gridFormingStorageProtectionRatio,
    dieselPowerProtectionRatio: control.dieselPowerProtectionRatio,
    socDeadband: control.socDeadband,
    hydrogenPressureDeadbandRatio: control.hydrogenPressureDeadbandRatio,
    electrolyzerPowerMinRatio: control.electrolyzerPowerMinRatio,
    electrolyzerPowerMaxRatio: control.electrolyzerPowerMaxRatio,
    electrolyzerPowerDeadbandRatio: control.electrolyzerPowerDeadbandRatio,
    electrolyzerPowerStepRatio: control.electrolyzerPowerStepRatio,
    electrolyzerDieselPowerLimitRatio: control.electrolyzerDieselPowerLimitRatio,
    electrolyzerDieselPowerDeadbandRatio: control.electrolyzerDieselPowerDeadbandRatio,
    electrolyzerStorageSocLowerLimit: control.electrolyzerStorageSocLowerLimit,
    electrolyzerStorageSocUpperLimit: control.electrolyzerStorageSocUpperLimit,
    electrolyzerHydrogenStorageSocUpperLimit: control.electrolyzerHydrogenStorageSocUpperLimit,
    fuelCellStorageSocLimit: control.fuelCellStorageSocLimit,
    fuelCellHydrogenStorageSocUpperLimit: control.fuelCellHydrogenStorageSocUpperLimit,
    fuelCellHydrogenStorageSocLowerLimit: control.fuelCellHydrogenStorageSocLowerLimit,
    fuelCellPowerMinRatio: control.fuelCellPowerMinRatio,
    fuelCellPowerMaxRatio: control.fuelCellPowerMaxRatio,
    fuelCellPowerDeadbandRatio: control.fuelCellPowerDeadbandRatio,
    fuelCellPowerStepRatio: control.fuelCellPowerStepRatio,
    fuelCellDieselPowerLimitRatio: control.fuelCellDieselPowerLimitRatio,
  };
  Object.entries(ratioInputs).forEach(([id, value]) => {
    const input = $(id);
    if (!parameterDialogOpen && input && document.activeElement !== input) {
      input.value = String(Number(value || 0) * 100);
    }
  });
  const commandValidInput = $("renewableCommandValidMinutes");
  if (!parameterDialogOpen && commandValidInput && document.activeElement !== commandValidInput) {
    commandValidInput.value = String(control.commandValidMinutes || 120);
  }
  const numericInputs = {
    optimizationRenewableCurtailmentWeight: control.optimizationRenewableCurtailmentWeight,
    optimizationDieselOutputWeight: control.optimizationDieselOutputWeight,
    optimizationCurtailmentSquareWeight: control.optimizationCurtailmentSquareWeight,
    optimizationSourceStorageAdjustmentSquareWeight: control.optimizationSourceStorageAdjustmentSquareWeight,
    optimizationBalanceDeltaSquareWeight: control.optimizationBalanceDeltaSquareWeight,
    optimizationBalanceDeltaWarningKw: control.optimizationBalanceDeltaWarningKw,
    optimizationBalanceToleranceKw: control.optimizationBalanceToleranceKw,
    optimizationBoundToleranceKw: control.optimizationBoundToleranceKw,
    optimizationFtol: control.optimizationFtol,
    optimizationMaxIterations: control.optimizationMaxIterations,
  };
  Object.entries(numericInputs).forEach(([id, value]) => {
    const input = $(id);
    if (!parameterDialogOpen && input && document.activeElement !== input) {
      input.value = String(value ?? "");
    }
  });
  [
    periodInput,
    commandValidInput,
    ...Object.keys(ratioInputs).map((id) => $(id)),
    ...Object.keys(numericInputs).map((id) => $(id)),
  ].forEach((input) => {
    if (input) input.disabled = control.actionActive;
  });
  const storagePowerDeratingButton = $("storagePowerDeratingButton");
  if (storagePowerDeratingButton) storagePowerDeratingButton.disabled = control.actionActive;
  const saveControlParametersButton = $("saveRenewableControlParameters");
  if (saveControlParametersButton) saveControlParametersButton.disabled = control.actionActive;
  const controlParametersButton = $("renewableControlParametersButton");
  if (controlParametersButton) controlParametersButton.disabled = control.actionActive;
  if (lastActionLabel) lastActionLabel.textContent = loopMode === "closed" ? "最近下发" : "最近计算";
  if (stateNode) {
    const backendRunState = control.runState || (
      control.enabled ? "running" : control.desiredEnabled ? "resume_pending" : "stopped"
    );
    stateNode.dataset.state = backendRunState;
    stateNode.textContent = backendRunState === "running"
      ? `${loopModeLabel}实时控制运行中`
      : backendRunState === "frozen"
        ? "模拟台暂停，学员台已冻结"
      : backendRunState === "resume_pending"
        ? "等待接收后恢复"
        : "已停止";
  }
  const metrics = plan?.metrics || {};
  const planWeather = plan?.weather || {};
  const snapshotWeather = currentWeatherLoad(snapshot);
  const observedWindSpeed = optionalNumber(planWeather.observedWindSpeed) ?? snapshotWeather.windSpeed;
  const observedSolarIrradiance = optionalNumber(planWeather.observedSolarIrradiance) ?? snapshotWeather.solarIrradiance;
  const storagePowerText = (value, group) => renewableStoragePowerMetricText(value, metrics, group);
  const storageSocText = (value, group) => renewableStorageSocMetricText(value, metrics, group);
  const metricText = {
    renewableAcCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "acRenewableCurrentKw", ["acWindCurrentKw", "acPvCurrentKw"])),
    renewableAcTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "acRenewableTargetKw", ["acWindTargetKw", "acPvTargetKw"])),
    renewableAcMaxAvailableKw: renewableMetricPowerText(metrics.acRenewableMaxAvailableKw),
    renewableAcWindCurrentKw: renewableMetricPowerText(metrics.acWindCurrentKw),
    renewableAcWindTargetKw: renewableMetricPowerText(metrics.acWindTargetKw),
    renewableAcWindMaxAvailableKw: renewableMetricPowerText(metrics.acWindMaxAvailableKw),
    renewableAcPvCurrentKw: renewableMetricPowerText(metrics.acPvCurrentKw),
    renewableAcPvTargetKw: renewableMetricPowerText(metrics.acPvTargetKw),
    renewableAcPvMaxAvailableKw: renewableMetricPowerText(metrics.acPvMaxAvailableKw),
    renewableDcCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcRenewableCurrentKw", ["dcWindCurrentKw", "dcPvCurrentKw"])),
    renewableDcTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcRenewableTargetKw", ["dcWindTargetKw", "dcPvTargetKw"])),
    renewableDcMaxAvailableKw: renewableMetricPowerText(metrics.dcRenewableMaxAvailableKw),
    renewableDcWindCurrentKw: renewableMetricPowerText(metrics.dcWindCurrentKw),
    renewableDcWindTargetKw: renewableMetricPowerText(metrics.dcWindTargetKw),
    renewableDcWindMaxAvailableKw: renewableMetricPowerText(metrics.dcWindMaxAvailableKw),
    renewableDcPvCurrentKw: renewableMetricPowerText(metrics.dcPvCurrentKw),
    renewableDcPvTargetKw: renewableMetricPowerText(metrics.dcPvTargetKw),
    renewableDcPvMaxAvailableKw: renewableMetricPowerText(metrics.dcPvMaxAvailableKw),
    renewableAcGridFollowingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFollowingStorageCurrentKw", ["acGridStorageCurrentKw"]),
      "ac-grid-following-storage",
    ),
    renewableAcGridFollowingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFollowingStorageTargetKw", ["acGridStorageTargetKw"]),
      "ac-grid-following-storage",
    ),
    renewableAcGridFollowingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "acGridFollowingStorageSoc", ["acGridStorageSoc"]),
      "ac-grid-following-storage",
    ),
    renewableDcGridFollowingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFollowingStorageCurrentKw", ["dcGridStorageCurrentKw"]),
      "dc-grid-following-storage",
    ),
    renewableDcGridFollowingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFollowingStorageTargetKw", ["dcGridStorageTargetKw"]),
      "dc-grid-following-storage",
    ),
    renewableDcGridFollowingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "dcGridFollowingStorageSoc", ["dcGridStorageSoc"]),
      "dc-grid-following-storage",
    ),
    renewableAcGridFormingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFormingStorageCurrentKw", ["acBalanceStorageCurrentKw"]),
      "ac-grid-forming-storage",
    ),
    renewableAcGridFormingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFormingStorageTargetKw", ["acBalanceStorageTargetKw"]),
      "ac-grid-forming-storage",
    ),
    renewableAcGridFormingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "acGridFormingStorageSoc", ["acBalanceStorageSoc"]),
      "ac-grid-forming-storage",
    ),
    renewableDcGridFormingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFormingStorageCurrentKw", ["dcBalanceStorageCurrentKw"]),
      "dc-grid-forming-storage",
    ),
    renewableDcGridFormingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFormingStorageTargetKw", ["dcBalanceStorageTargetKw"]),
      "dc-grid-forming-storage",
    ),
    renewableDcGridFormingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "dcGridFormingStorageSoc", ["dcBalanceStorageSoc"]),
      "dc-grid-forming-storage",
    ),
    renewableAcDieselCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "acDieselCurrentKw", ["dieselCurrentKw"])),
    renewableAcDieselMinKw: renewableMetricPowerText(renewableMetricValue(metrics, "acDieselMinKw", ["dieselMinKw"])),
    renewableAcDieselTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "acDieselTargetKw", ["dieselTargetKw"])),
    renewableDcDieselCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcDieselCurrentKw")),
    renewableDcDieselMinKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcDieselMinKw")),
    renewableDcDieselTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcDieselTargetKw")),
    renewableAcLoadKw: renewableMetricPowerText(metrics.acLoadKw),
    renewableDcLoadKw: renewableMetricPowerText(metrics.dcLoadKw),
    renewableTotalCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalRenewableCurrentKw", ["renewableCurrentKw"])),
    renewableTotalTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalRenewableTargetKw", ["renewableTarget"])),
    renewableTotalMaxAvailableKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalRenewableMaxAvailableKw", ["renewableMaxAvailableKw"])),
    renewableTotalWindCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalWindCurrentKw", ["acWindCurrentKw", "dcWindCurrentKw"])),
    renewableTotalWindTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalWindTargetKw", ["acWindTargetKw", "dcWindTargetKw"])),
    renewableTotalWindMaxAvailableKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalWindMaxAvailableKw", ["windMaxAvailableKw"])),
    renewableTotalPvCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalPvCurrentKw", ["acPvCurrentKw", "dcPvCurrentKw"])),
    renewableTotalPvTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalPvTargetKw", ["acPvTargetKw", "dcPvTargetKw"])),
    renewableTotalPvMaxAvailableKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalPvMaxAvailableKw", ["pvMaxAvailableKw"])),
    renewableTotalGridFollowingStorageCurrentKw: storagePowerText(
      metrics.totalGridFollowingStorageCurrentKw,
      "system-grid-following-storage",
    ),
    renewableTotalGridFollowingStorageTargetKw: storagePowerText(
      metrics.totalGridFollowingStorageTargetKw,
      "system-grid-following-storage",
    ),
    renewableTotalGridFollowingStorageSoc: storageSocText(
      metrics.totalGridFollowingStorageSoc,
      "system-grid-following-storage",
    ),
    renewableTotalGridFormingStorageCurrentKw: storagePowerText(
      metrics.totalGridFormingStorageCurrentKw,
      "system-grid-forming-storage",
    ),
    renewableTotalGridFormingStorageTargetKw: storagePowerText(
      metrics.totalGridFormingStorageTargetKw,
      "system-grid-forming-storage",
    ),
    renewableTotalGridFormingStorageSoc: storageSocText(
      metrics.totalGridFormingStorageSoc,
      "system-grid-forming-storage",
    ),
    renewableTotalDieselCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalDieselCurrentKw", ["dieselCurrentKw"])),
    renewableTotalDieselMinKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalDieselMinKw", ["dieselMinKw"])),
    renewableTotalDieselTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalDieselTargetKw", ["dieselTargetKw"])),
    renewableTotalLoadKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalLoadKw", ["loadKw"])),
    renewableAcdcCurrentKw: renewableMetricPowerText(metrics.acdcCurrentKw),
    renewableAcdcTargetKw: renewableMetricPowerText(metrics.acdcTargetKw),
    renewableElectrolyzerCurrentKw: renewableMetricPowerText(metrics.electrolyzerCurrentKw),
    renewableElectrolyzerTargetKw: renewableMetricPowerText(metrics.electrolyzerTargetKw),
    renewableElectrolyzerFlowCurrentNm3h: renewableMetricNumberText(metrics.electrolyzerFlowCurrentNm3h),
    renewableElectrolyzerFlowTargetNm3h: renewableMetricNumberText(metrics.electrolyzerFlowTargetNm3h),
    renewableFuelCellCurrentKw: renewableMetricPowerText(metrics.fuelCellCurrentKw),
    renewableFuelCellTargetKw: renewableMetricPowerText(metrics.fuelCellTargetKw),
    renewableFuelCellFlowCurrentNm3h: renewableMetricNumberText(metrics.fuelCellFlowCurrentNm3h),
    renewableFuelCellFlowTargetNm3h: renewableMetricNumberText(metrics.fuelCellFlowTargetNm3h),
    renewableHydrogenStoragePressureMpa: renewableMetricNumberText(metrics.hydrogenStoragePressureMpa),
    renewableHydrogenStoragePressureLowGuardMpa: renewableMetricNumberText(metrics.hydrogenStoragePressureLowGuardMpa),
    renewableHydrogenStoragePressureHighGuardMpa: renewableMetricNumberText(metrics.hydrogenStoragePressureHighGuardMpa),
    renewableHydrogenStorageGasQuantityNm3: renewableMetricNumberText(metrics.hydrogenStorageGasQuantityNm3),
    renewableHydrogenStorageSoc: renewableMetricSocText(metrics.hydrogenStorageSoc),
    renewableHydrogenStorageFlowNm3h: renewableMetricNumberText(metrics.hydrogenStorageFlowNm3h),
    renewableObservedWindSpeed: Number.isFinite(observedWindSpeed) ? formatNumber(observedWindSpeed) : "--",
    renewableObservedSolarIrradiance: Number.isFinite(observedSolarIrradiance) ? formatNumber(observedSolarIrradiance) : "--",
    renewableLastSent: loopMode === "closed" ? control.lastSentAt || "--" : control.lastCalculatedAt || "--",
  };
  Object.entries(metricText).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
  renderRenewableMetricAvailability(metrics);
  const status = $("renewableControlStatus");
  if (status) {
    status.textContent = actionPending
      ? "正在提交本次新能源控制操作..."
      : !receiveReady
        ? control.resumePending
          ? control.lastStatus
          : renewablePrerequisiteStatus(control)
        : control.lastStatus;
    status.classList.toggle("is-ok", control.enabled);
    status.classList.toggle("is-warning", control.resumePending);
    status.classList.toggle("is-error", !hasDecisionSnapshot && control.enabled);
  }
  if (summary) {
    summary.textContent = `${plan?.commands?.length || 0} 条 · ${plan?.time || "--"} · ${loopModeLabel} · ${renewableDataSourceLabel(plan?.dataQuality?.source)}`;
  }
  renderRenewableMetricTabs();
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
      <thead>
        <tr>
          <th>设备名称</th>
          <th>遥调点名称</th>
          <th>并网侧</th>
          <th>接入状态</th>
          <th>接入母线</th>
          <th>传输组</th>
          <th>接入路径</th>
          <th>拓扑状态</th>
          <th>间接调节设备</th>
          <th>当前值</th>
          <th>可用边界</th>
          <th>目标值</th>
          <th>SOC</th>
          <th>执行</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => {
          const commandable = row.online && row.commandable !== false;
          const balanceStorage = row.category.includes("平衡储能");
          const disabledReason = !row.online
            ? renewableRowStatusLabel(row)
            : row.commandable === false
              ? renewableRowStatusLabel(row)
              : balanceStorage
                ? "平衡储能仅间接调节"
                : "";
          const pointName = renewableRemoteAdjustmentPointName(row);
          const gridSideText = renewableTopologyCellText(row.gridSide ?? row.connectionSide);
          const connectionText = row.connectionStatusLabel || (row.activelyConnected === false ? "当前断开" : renewableRowStatusLabel(row));
          const busText = renewableTopologyCellText(row.bus ?? row.busbarName ?? row.busbarNode);
          const transferGroupText = renewableTopologyCellText(row.transferGroup || row.dcTransferGroupId || "--");
          const converterPath = row.converterPath;
          const pathText = renewableConverterPathText({ converterPath });
          const topologyStatusText = renewableTopologyCellText(row.topologyStatusLabel);
          const indirectControlDevices = row.indirectControlDevices;
          const indirectText = renewableIndirectControlText({ indirectControlDevices });
          const boundaryText = renewableRowBoundaryText(row);
          const currentValue = renewableRowControlPointPower(row, row.currentKw);
          const targetValue = renewableRowControlPointPower(row, balanceStorage
            ? optionalNumber(row.projectedTargetKw)
            : optionalNumber(row.targetKw ?? row.commandKw));
          const actionDisabled = !commandable || balanceStorage;
          const previewOnly = row.dispatchEnabled === false;
          const executionText = previewOnly
            ? "仅预览"
            : control.loopMode === "closed"
              ? "随策略下发"
              : "开环不下发";
          return `
          <tr class="${commandable && !balanceStorage ? "" : "is-muted"}">
            <td class="renewable-topology-text" title="${escapeHtml(row.dev_name)}">${escapeHtml(row.dev_name)}</td>
            <td class="renewable-control-point" title="${escapeHtml(pointName)}">${escapeHtml(pointName)}</td>
            <td class="renewable-topology-text" title="${escapeHtml(renewableTopologyTitle(gridSideText))}">${escapeHtml(gridSideText)}</td>
            <td><span class="status-pill ${commandable ? "is-ok" : "is-off"}">${escapeHtml(connectionText)}</span></td>
            <td class="renewable-topology-text" title="${escapeHtml(renewableTopologyTitle(busText))}">${escapeHtml(busText)}</td>
            <td class="renewable-topology-text" title="${escapeHtml(renewableTopologyTitle(transferGroupText))}">${escapeHtml(transferGroupText)}</td>
            <td class="renewable-topology-text" title="${escapeHtml(renewableTopologyTitle(pathText))}">${escapeHtml(pathText)}</td>
            <td class="renewable-topology-text" title="${escapeHtml(renewableTopologyTitle(topologyStatusText))}">${escapeHtml(topologyStatusText)}</td>
            <td class="renewable-topology-text" title="${escapeHtml(renewableTopologyTitle(indirectText))}">${escapeHtml(indirectText)}</td>
            <td class="numeric-cell">${Number.isFinite(currentValue) ? `${formatNumber(currentValue)} kW` : "--"}</td>
            <td class="numeric-cell" title="${escapeHtml(boundaryText)}">${escapeHtml(boundaryText)}</td>
            <td class="numeric-cell">${Number.isFinite(targetValue) ? `${formatNumber(targetValue)} kW` : "--"}</td>
            <td class="numeric-cell">${row.soc === undefined ? "--" : formatNumber(row.soc)}</td>
            <td>${actionDisabled
              ? `<button type="button" class="renewable-row-action" disabled title="${escapeHtml(disabledReason || "不可直接下发")}">不可执行</button>`
              : `<span class="renewable-row-ready${previewOnly || control.loopMode !== "closed" ? " is-preview" : ""}">${executionText}</span>`}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

async function toggleRenewableAuto() {
  if (!state.renewableControl.desiredEnabled && !state.receiveMode) {
    state.renewableControl.lastStatus = "请先启动接收，再启动新能源实时控制。";
    renderRenewableControl(state.snapshot || {});
    return;
  }
  const action = state.renewableControl.desiredEnabled ? "stop" : "start";
  await runRenewableControlAction(action);
}

async function runRenewableControlOnce() {
  if (!state.receiveMode) {
    state.renewableControl.lastStatus = "请先启动接收，再执行单次计算。";
    renderRenewableControl(state.snapshot || {});
    return;
  }
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
  const periodInput = $("renewableControlPeriod");
  const intervalSeconds = toNumber(periodInput?.value, 2);
  const intervalError = renewableSimulationControlIntervalError(intervalSeconds);
  periodInput?.setCustomValidity?.(intervalError);
  if (intervalError) {
    state.renewableControl.lastStatus = intervalError;
    periodInput?.reportValidity?.();
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  const commandValidMinutes = Math.max(0.1, toNumber($("renewableCommandValidMinutes")?.value, 120));
  const ratio = (id, fallbackPercent, minimumPercent = 0, maximumPercent = 100) => (
    Math.min(
      maximumPercent,
      Math.max(minimumPercent, toNumber($(id)?.value, fallbackPercent)),
    ) / 100
  );
  const powerSettings = {
    electrolyzerPowerMinRatio: ratio("electrolyzerPowerMinRatio", 2),
    electrolyzerPowerMaxRatio: ratio("electrolyzerPowerMaxRatio", 50),
    electrolyzerPowerDeadbandRatio: ratio("electrolyzerPowerDeadbandRatio", 0),
    electrolyzerPowerStepRatio: ratio("electrolyzerPowerStepRatio", 2, 0.001, 100),
    fuelCellPowerMinRatio: ratio("fuelCellPowerMinRatio", 3),
    fuelCellPowerMaxRatio: ratio("fuelCellPowerMaxRatio", 15),
    fuelCellPowerDeadbandRatio: ratio("fuelCellPowerDeadbandRatio", 0),
    fuelCellPowerStepRatio: ratio("fuelCellPowerStepRatio", 3, 0.001, 100),
    electrolyzerDieselPowerLimitRatio: ratio("electrolyzerDieselPowerLimitRatio", 80),
    electrolyzerDieselPowerDeadbandRatio: ratio("electrolyzerDieselPowerDeadbandRatio", 5),
    fuelCellDieselPowerLimitRatio: ratio("fuelCellDieselPowerLimitRatio", 80),
  };
  const powerSettingError = [
    ["电制氢", powerSettings.electrolyzerPowerMinRatio, powerSettings.electrolyzerPowerMaxRatio, powerSettings.electrolyzerPowerDeadbandRatio],
    ["燃料电池", powerSettings.fuelCellPowerMinRatio, powerSettings.fuelCellPowerMaxRatio, powerSettings.fuelCellPowerDeadbandRatio],
  ].map(([label, minimum, maximum, deadband]) => {
    if (minimum > maximum) return `${label}功率下限不能大于上限。`;
    if (minimum + deadband > maximum) return `${label}启动功率（下限+死区）不能大于上限。`;
    return "";
  }).find(Boolean);
  if (powerSettingError) {
    state.renewableControl.lastStatus = powerSettingError;
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  const electrolyzerStorageSocLowerLimit = ratio("electrolyzerStorageSocLowerLimit", 40);
  const electrolyzerStorageSocUpperLimit = ratio("electrolyzerStorageSocUpperLimit", 80);
  const fuelCellHydrogenStorageSocLowerLimit = ratio("fuelCellHydrogenStorageSocLowerLimit", 20);
  const fuelCellHydrogenStorageSocUpperLimit = ratio("fuelCellHydrogenStorageSocUpperLimit", 80);
  const socSettingError = electrolyzerStorageSocLowerLimit > electrolyzerStorageSocUpperLimit
    ? "电制氢电储平均SOC下限不能大于上限。"
    : fuelCellHydrogenStorageSocLowerLimit > fuelCellHydrogenStorageSocUpperLimit
      ? "燃料电池氢储平均SOC下限不能大于上限。"
      : "";
  if (socSettingError) {
    state.renewableControl.lastStatus = socSettingError;
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  return runRenewableControlAction("update_settings", {
    settings: {
      simulationIntervalSeconds: intervalSeconds,
      commandValidMinutes,
      largeStepThresholdKw: state.renewableControl.largeStepThresholdKw,
      renewableStepRatio: ratio("renewableStepRatio", 3),
      storageStepRatio: ratio("storageStepRatio", 3),
      storageSocCorrectionStepScale: ratio("storageSocCorrectionStepScale", 20, 10, 100),
      gridFormingStorageProtectionRatio: ratio("gridFormingStorageProtectionRatio", 5, 0, 50),
      dieselPowerProtectionRatio: ratio("dieselPowerProtectionRatio", 3, 0, 50),
      socDeadband: ratio("socDeadband", 5),
      hydrogenClosedLoopEnabled: Boolean($("hydrogenClosedLoopEnabled")?.checked),
      hydrogenPressureDeadbandRatio: ratio("hydrogenPressureDeadbandRatio", 5, 0, 50),
      electrolyzerStorageSocLowerLimit,
      electrolyzerStorageSocUpperLimit,
      electrolyzerHydrogenStorageSocUpperLimit: ratio("electrolyzerHydrogenStorageSocUpperLimit", 90),
      fuelCellStorageSocLimit: ratio("fuelCellStorageSocLimit", 40),
      fuelCellHydrogenStorageSocUpperLimit,
      fuelCellHydrogenStorageSocLowerLimit,
      ...powerSettings,
      optimizationRenewableCurtailmentWeight: Math.max(0, toNumber($("optimizationRenewableCurtailmentWeight")?.value, 1)),
      optimizationDieselOutputWeight: Math.max(0, toNumber($("optimizationDieselOutputWeight")?.value, 1)),
      optimizationCurtailmentSquareWeight: Math.max(0, toNumber($("optimizationCurtailmentSquareWeight")?.value, 0.000001)),
      optimizationSourceStorageAdjustmentSquareWeight: Math.max(0, toNumber($("optimizationSourceStorageAdjustmentSquareWeight")?.value, 0.000001)),
      optimizationBalanceDeltaSquareWeight: Math.max(0, toNumber($("optimizationBalanceDeltaSquareWeight")?.value, 10000)),
      optimizationBalanceDeltaWarningKw: Math.max(0, toNumber($("optimizationBalanceDeltaWarningKw")?.value, 1)),
      optimizationBalanceToleranceKw: Math.max(0, toNumber($("optimizationBalanceToleranceKw")?.value, 0.1)),
      optimizationBoundToleranceKw: Math.max(0, toNumber($("optimizationBoundToleranceKw")?.value, 0.1)),
      optimizationFtol: Math.max(0, toNumber($("optimizationFtol")?.value, 0.001)),
      optimizationMaxIterations: Math.max(1, Math.round(toNumber($("optimizationMaxIterations")?.value, 100))),
      storageChargeDeratingCurve: state.renewableControl.storageChargeDeratingCurve,
      storageDischargeDeratingCurve: state.renewableControl.storageDischargeDeratingCurve,
    },
  });
}

async function saveRenewableControlParameters() {
  const response = await updateRenewableSettings();
  if (response) closeRenewableControlParametersDialog();
}

function storagePowerDeratingRowHtml(direction, point, index) {
  const directionLabel = direction === "charge" ? "充电" : "放电";
  return `
    <tr class="storage-power-derating-row" data-derating-direction="${direction}" data-derating-index="${index}">
      <td>
        <label class="storage-power-derating-input">
          <input type="number" min="0" max="100" step="0.1" value="${formatNumber(point.soc * 100)}" data-derating-field="soc" aria-label="${directionLabel} SOC 节点 ${index + 1}" />
          <span>%</span>
        </label>
      </td>
      <td>
        <label class="storage-power-derating-input">
          <input type="number" min="0" max="100" step="0.1" value="${formatNumber(point.powerRatio * 100)}" data-derating-field="powerRatio" aria-label="${directionLabel}功率上限节点 ${index + 1}" />
          <span>%</span>
        </label>
      </td>
    </tr>`;
}

function renderStoragePowerDeratingRows(
  chargeCurve = state.renewableControl.storageChargeDeratingCurve,
  dischargeCurve = state.renewableControl.storageDischargeDeratingCurve,
) {
  const chargeRows = $("storageChargeDeratingRows");
  const dischargeRows = $("storageDischargeDeratingRows");
  if (chargeRows) {
    chargeRows.innerHTML = normalizeStorageDeratingCurve(
      chargeCurve,
      DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
      "charge",
    ).map((point, index) => storagePowerDeratingRowHtml("charge", point, index)).join("");
  }
  if (dischargeRows) {
    dischargeRows.innerHTML = normalizeStorageDeratingCurve(
      dischargeCurve,
      DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
      "discharge",
    ).map((point, index) => storagePowerDeratingRowHtml("discharge", point, index)).join("");
  }
}

function readStoragePowerDeratingCurve(direction) {
  return Array.from(document.querySelectorAll(`[data-derating-direction="${direction}"]`)).map((row) => ({
    soc: Math.max(0, toNumber(row.querySelector('[data-derating-field="soc"]')?.value, 0)) / 100,
    powerRatio: Math.max(0, toNumber(row.querySelector('[data-derating-field="powerRatio"]')?.value, 0)) / 100,
  }));
}

function validateStoragePowerDeratingCurve(points, direction) {
  if (!Array.isArray(points) || points.length < 2) return "每条降额曲线至少需要两个节点。";
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    if (!Number.isFinite(point.soc) || point.soc < 0 || point.soc > 1) return "SOC 必须位于 0% 到 100% 之间。";
    if (!Number.isFinite(point.powerRatio) || point.powerRatio < 0 || point.powerRatio > 1) return "功率上限必须位于 0% 到 100% 之间。";
    if (index > 0 && point.soc <= points[index - 1].soc) return "SOC 节点必须严格递增，不能重复。";
    if (index > 0 && direction === "charge" && point.powerRatio > points[index - 1].powerRatio) {
      return "充电功率上限必须随 SOC 升高保持不变或下降。";
    }
    if (index > 0 && direction === "discharge" && point.powerRatio < points[index - 1].powerRatio) {
      return "放电功率上限必须随 SOC 升高保持不变或上升。";
    }
  }
  return "";
}

function validateStoragePowerDeratingCurves(chargeCurve, dischargeCurve) {
  return validateStoragePowerDeratingCurve(chargeCurve, "charge")
    || validateStoragePowerDeratingCurve(dischargeCurve, "discharge");
}

function setStoragePowerDeratingMessage(message = "", level = "") {
  const node = $("storagePowerDeratingMessage");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("is-error", level === "error");
  node.classList.toggle("is-ok", level === "ok");
}

function openStoragePowerDeratingDialog() {
  renderStoragePowerDeratingRows();
  setStoragePowerDeratingMessage("相邻 SOC 节点之间自动进行线性插值。", "");
  const dialog = $("storagePowerDeratingDialog");
  if (dialog && !dialog.open) dialog.showModal();
}

function closeStoragePowerDeratingDialog() {
  const dialog = $("storagePowerDeratingDialog");
  if (dialog?.open) dialog.close();
}

function resetStoragePowerDeratingCurves() {
  renderStoragePowerDeratingRows(
    DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
    DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
  );
  setStoragePowerDeratingMessage("已恢复默认节点，点击保存后生效。", "ok");
}

async function saveStoragePowerDeratingCurves() {
  const chargeCurve = readStoragePowerDeratingCurve("charge");
  const dischargeCurve = readStoragePowerDeratingCurve("discharge");
  const validationMessage = validateStoragePowerDeratingCurves(chargeCurve, dischargeCurve);
  if (validationMessage) {
    setStoragePowerDeratingMessage(validationMessage, "error");
    return;
  }
  setStoragePowerDeratingMessage("正在保存降额曲线...", "");
  const response = await runRenewableControlAction("update_settings", {
    settings: {
      storageChargeDeratingCurve: chargeCurve,
      storageDischargeDeratingCurve: dischargeCurve,
    },
  });
  if (!response) {
    setStoragePowerDeratingMessage(state.renewableControl.lastStatus || "降额曲线保存失败。", "error");
    return;
  }
  closeStoragePowerDeratingDialog();
}

function renderClock(clock) {
  $("simTime").textContent = clock.time || "00:00:00";
  $("simState").textContent = clock.state || "stopped";
  $("simSpeed").textContent = `x${clock.speed ?? 1}`;
  const readout = document.querySelector(".clock-readout");
  if (readout) readout.dataset.clockState = clock.state || "stopped";
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
      ? (timedOut ? "模拟台潮流计算超时，仿真已暂停" : "模拟台潮流计算失败，仿真已暂停")
      : (timedOut ? "模拟台潮流计算超时，本轮结果已丢弃" : "模拟台潮流计算失败，本轮结果已丢弃");
  }
  if (detail) {
    const staleFrameText = lastSuccessTime
      ? `当前画面量测为上一成功帧（${lastSuccessTime}）`
      : "当前画面没有成功潮流量测帧";
    detail.textContent = (
      `失败仿真时刻 ${simuTime}。${error}。`
      + `本轮潮流结果未采用，${staleFrameText}，请通知教员修正边界后${simulationPaused ? "再恢复运行" : "重新计算"}。`
    );
  }
}

function deviceKey(dev) {
  return `${dev.dev_type || dev.type || ""}|${dev.dev_name || dev.name || ""}`;
}

function deviceName(dev) {
  return String(dev?.dev_name || dev?.name || "");
}

function deviceType(dev) {
  return String(dev.dev_type || dev.type || "Unknown");
}

function deviceModelBlock(dev) {
  return String(dev?.model_block || dev?.raw?.model_block || "").trim();
}

function deviceFamily(dev) {
  return String(dev?.device_family || "").trim().toLowerCase();
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
    const type = deviceModelBlock(dev) || "Unknown";
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
  if ((devType || deviceModelBlock(item)) === "Environment" && name === "weather") return "气象";
  return name;
}

function deviceTreeSearchFields(item, devType = "") {
  const raw = item?.raw || {};
  return [
    devType,
    deviceModelBlock(item),
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
  if (scope === "measurement") renderDeviceTree("measurementDeviceTree", "measurementTreeSummary", measurementsDevices(state.snapshot || {}), state.measurementFilter, "measurement", "measurement");
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
        model_block: blockName,
        dev_name: String(name || `${blockName}_${index + 1}`),
        idx,
        raw,
        __headers: headers,
        __definition_index: index,
      };
    });
  });
}

function formatModelParamValue(value, field = "") {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (diagramDefinitionRatioField(field)) return diagramDefinitionDisplayValue(field, value);
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
    record[key] = formatModelParamValue(raw[key], key);
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

function measurementPresentationValue(value, row = null) {
  if (value === null || value === undefined || value === "") return value;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return String(row?.meas_type || "").toUpperCase() === "SOC" ? number * 100 : number;
}

function formatMeasurementDisplayValue(value, row = null, analogFormatter = formatNumber) {
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

function measurementCompareRows(
  measurements = state.snapshot?.measurements || {},
  definitionRows = null,
) {
  const definitions = definitionRows
    || state.snapshot?.definitions?.measurement
    || measurements.definitions
    || [];
  const primaryRows = definitions.length
    ? definitions
    : (measurements.scada || []);
  const scadaByKey = new Map((measurements.scada || []).map((row) => [measurementKey(row), row]));
  return sortMeasurementsForDisplay(primaryRows.map((definition) => {
    const key = measurementKey(definition);
    const scada = scadaByKey.get(key);
    const scadaValue = scada?.value;
    return {
      ...definition,
      value: scadaValue ?? definition.value,
      scada_value: scadaValue,
      valid: scada?.valid ?? definition.valid,
      weight: definition.weight,
    };
  }));
}

function measurementDisplayRows(snapshot = state.snapshot || {}) {
  const measurements = snapshot.measurements || {};
  const definitions = snapshot.definitions?.measurement
    || snapshot.measurements?.definitions
    || measurements.definitions
    || [];
  return measurementCompareRows(measurements, definitions);
}

function measurementDeviceMetadataIndex(snapshot = state.snapshot || {}) {
  const metadataByKey = new Map();
  const remember = (dev) => {
    const devType = String(dev?.dev_type || dev?.type || "").trim();
    const devName = String(dev?.dev_name || dev?.name || "").trim();
    const modelBlock = deviceModelBlock(dev);
    if (!devType || !devName || !modelBlock) return;
    const key = `${devType}|${devName}`;
    const metadata = {
      ...(metadataByKey.get(key) || {}),
      model_block: modelBlock,
    };
    const family = deviceFamily(dev);
    if (family) metadata.device_family = family;
    if (Array.isArray(dev?.terminal_domains)) metadata.terminal_domains = [...dev.terminal_domains];
    const technology = String(dev?.resource_technology || "").trim();
    if (technology) metadata.resource_technology = technology;
    metadataByKey.set(key, metadata);
  };

  definedModelDevices(snapshot).forEach(remember);
  (snapshot.devices || []).forEach(remember);
  metadataByKey.set("Environment|weather", {
    model_block: "Environment",
    device_family: "environment",
  });
  return metadataByKey;
}

function measurementsDevices(snapshot = state.snapshot || {}) {
  const devices = new Map();
  const metadataByKey = measurementDeviceMetadataIndex(snapshot);
  measurementRows(snapshot).forEach((row) => {
    const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
    if (!devices.has(key)) {
      devices.set(key, {
        ...(metadataByKey.get(key) || {}),
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
  if (field === "scada") return formatMeasurementDisplayValue(measurementPresentationValue(row.scada_value, row), row);
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
      if (field === "scada") {
        const value = Number(row.scada_value || 0);
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
          const valueClass = Math.abs(Number(item.scada_value || 0)) > 10000 ? "value-bad" : Math.abs(Number(item.scada_value || 0)) > 1000 ? "value-warn" : "";
          return `<tr class="${key === state.selectedMeasurementKey ? "is-selected" : ""}" data-measurement-row-key="${escapeHtml(key)}" data-measurement-select-key="${escapeHtml(key)}">
            <td>${escapeHtml(item.idx ?? "")}</td>
            <td>${escapeHtml(measurementDisplayName(item) || "")}</td>
            <td>${escapeHtml(measurementDeviceDisplay(item))}</td>
            <td>${escapeHtml(measurementTypeDisplay(item))}</td>
            <td class="numeric-cell ${valueClass}" data-measurement-live-field="scada">${formatMeasurementDisplayValue(measurementPresentationValue(item.scada_value, item), item)}</td>
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
  const sampledClock = snapshot.measurement_clock;
  const clock = sampledClock && Number(sampledClock.step_count ?? 0) > 0
    ? sampledClock
    : snapshot.clock || {};
  if (isSimulationFrozenSnapshot(snapshot)) return false;
  if (Number(clock.step_count ?? 0) <= 0) return false;
  const rows = measurementCompareRows(snapshot.measurements || {});
  if (!rows.some((row) => diagramTrendFiniteValue(row.scada_value) !== null)) {
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
    time: clock.time || "--",
    sim_time: clock.time || "--",
    run_id: Number(clock.run_id ?? 0) || 0,
    step_count: Number(clock.step_count ?? 0) || 0,
    measurements: {},
  };
  rows.forEach((row) => {
    const scada = diagramTrendFiniteValue(measurementPresentationValue(row.scada_value, row));
    point.measurements[measurementKey(row)] = {
      value: scada,
      scada,
      valid: Number(row.valid) === 1 ? 1 : 0,
      dev_type: row.dev_type || "",
      dev_name: row.dev_name || "",
      meas_type: row.meas_type || "",
      label: `${measurementDeviceDisplay(row) || row.name || ""} ${measurementTypeDisplay(row) || ""}`.trim(),
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
    const arrays = [frame.scada_values, frame.valid_values];
    if (arrays.some((values) => !Array.isArray(values) || values.length !== indices.length)) {
      throw new Error("历史量测数组长度不一致，历史帧已拒绝");
    }
    const minute = Number(frame.absolute_minute);
    if (!Number.isFinite(minute)) throw new Error("历史量测仿真时刻无效，历史帧已拒绝");
    const scada = diagramTrendFiniteValue(measurementPresentationValue(frame.scada_values[selectedPosition], row));
    const validValue = frame.valid_values[selectedPosition];
    return {
      minute,
      time: frame.simu_time || "--",
      sim_time: frame.simu_time || "--",
      record_time: frame.wall_time || "",
      run_id: Number(frame.run_id ?? payloadRunId) || payloadRunId,
      step_count: Number(frame.step_count ?? 0) || 0,
      history_seq: Number(frame.seq ?? 0) || 0,
      measurements: {
        [key]: {
          name: measurementDisplayName(row) || "",
          value: scada,
          scada,
          valid: validValue === null || validValue === undefined
            ? (Number(row.valid) === 1 ? 1 : 0)
            : (Number(validValue) === 1 ? 1 : 0),
          dev_type: row.dev_type || "",
          dev_name: row.dev_name || "",
          meas_type: row.meas_type || "",
          unit: diagramMeasurementUnit(row.meas_type),
          label: `${measurementDeviceDisplay(row) || row.name || ""} ${measurementTypeDisplay(row) || ""}`.trim(),
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
      if (!existing.time || existing.time === "--") existing.time = point.time;
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
  const historyPath = state.receiveMode
    ? `/api/trainee/measurement-history?indices=${definitionIndex}`
    : `/api/measurement-history?indices=${definitionIndex}`;
  const request = api(historyPath)
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

function selectedMeasurementHistoryRow() {
  if (!state.selectedMeasurementKey) return null;
  return measurementCompareRows(state.snapshot?.measurements || {}).find(
    (row) => measurementKey(row) === state.selectedMeasurementKey,
  ) || null;
}

function ensureSelectedMeasurementHistory() {
  const row = selectedMeasurementHistoryRow();
  if (!row) return;
  ensureMeasurementHistoryForRow(row).then((changed) => {
    if (changed && measurementKey(row) === state.selectedMeasurementKey) {
      drawMeasurementTraceChart();
    }
  });
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
    axisStepMinutes: traceAxisStepMinutes(minutes),
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

function measurementTraceWindowRange() {
  const history = state.measurementTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.measurementTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("measurementTrace"),
    curveDisplayModeDurationMinutes(),
  );
  setChartPeriodOffset("measurementTrace", range.windowOffset);
  return range;
}

function measurementTraceWindowPoints(range = measurementTraceWindowRange()) {
  const history = state.measurementTraceHistory || [];
  if (!history.length || !state.selectedMeasurementKey) return [];
  const points = history
    .map((point) => {
      const item = point.measurements[state.selectedMeasurementKey];
      if (!item || !Number.isFinite(item.value)) return null;
      return { minute: point.minute, time: point.time, value: item.value, label: item.label };
    })
    .filter(Boolean);
  return traceWindowRealPoints(points, range);
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

function measurementTracePointTimeLabel(point, range) {
  const time = String(point?.sim_time || point?.time || "").trim();
  if (time && time !== "--") return time;
  return measurementTraceTimeLabel(point?.minute, range, -1, 0);
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
  syncChartPeriodNavigation("measurementTrace", range);
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
  const points = measurementTraceWindowPoints(range);
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
    let previousMinute = null;
    points.forEach((point) => {
      const value = Number(point[series.field]);
      if (!Number.isFinite(value)) return;
      const x = left + ((point.minute - range.startMinute) / range.windowMinutes) * plotWidth;
      const y = top + plotHeight - ((value - minValue) / span) * plotHeight;
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
    hitData.push({ ...series, unit: "", points: pixelPoints });
  });
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    timeLabel: (point) => measurementTracePointTimeLabel(point, range),
    valueFormatter: formatNumber,
  });
  ctx.fillStyle = "#63717a";
  ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
  ctx.fillText(formatNumber(maxValue), 8 * ratio, top + 4 * ratio);
  ctx.fillText(formatNumber(minValue), 8 * ratio, top + plotHeight);
  $("measurementTraceSummary").textContent = `${points[points.length - 1].label || "测点"} · ${traceWindowDataPointCount(points)} 点`;
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
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("commandTrace"),
    curveDisplayModeDurationMinutes(),
  );
  setChartPeriodOffset("commandTrace", range.windowOffset);
  return range;
}

function commandTraceWindowPoints(range = commandTraceWindowRange()) {
  const history = state.commandTraceHistory || [];
  if (!history.length || !state.selectedCommandTraceKey) return [];
  const points = history
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
  return traceWindowRealPoints(points, range);
}

function appendCommandTrace(snapshot) {
  const clock = snapshot.clock || {};
  if (isSimulationFrozenSnapshot(snapshot)) return false;
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
      label: `${deviceType(dev)}.${deviceName(dev)}.遥控投退`,
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
      label: `${deviceType(dev)}.${deviceName(dev)}.遥控开合`,
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
  syncChartPeriodNavigation("commandTrace", range);
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
  const points = commandTraceWindowPoints(range);
  const seriesDefs = [
    { key: "control", field: "control", label: "控制值", color: "#c98820" },
    { key: "actual", field: "actual", label: "实时值", color: "#008c8c" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  $("commandTraceSummary").textContent = `${selectedCommandTraceLabel()} · ${traceWindowDataPointCount(points)} 点`;
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
    let previousY = Number.NaN;
    points.forEach((point) => {
      const value = point[series.field];
      if (value === null || !Number.isFinite(value)) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
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
  visibleSeries.forEach((series) => drawSeries(series, series.key === "control" ? 2.4 : 2.2));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    timeLabel: (point) => measurementTracePointTimeLabel(point, range),
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

function remoteControlMeasuredValue(devType, devName, commandType, snapshot = state.snapshot || {}) {
  const targetType = String(devType || "").trim().toUpperCase();
  const targetName = String(devName || "").trim();
  const measurementType = commandType === "status" ? "STATUS" : "RUN_STAT";
  const row = (snapshot.measurements?.scada || []).find((item) => (
    String(item?.dev_type || "").trim().toUpperCase() === targetType
    && String(item?.dev_name || "").trim() === targetName
    && String(item?.meas_type || "").trim().toUpperCase() === measurementType
  ));
  if (!row) return null;
  if (row.valid !== undefined && row.valid !== null && row.valid !== "" && Number(row.valid) === 0) return null;
  const value = Number(row.value);
  if (Number.isFinite(value)) return value > 0.5 ? 1 : 0;
  return null;
}

function remoteControlFeedbackValue(dev, commandType, snapshot = state.snapshot || {}) {
  if (!dev) return null;
  const devType = deviceType(dev);
  const devName = deviceName(dev);
  const measured = remoteControlMeasuredValue(devType, devName, commandType, snapshot);
  if (measured !== null) return measured;
  const fieldName = commandType === "status" ? "status" : "run_stat";
  const live = snapshotDevice(devType, devName, snapshot) || {};
  const rawValue = live[fieldName] ?? live.raw?.[fieldName] ?? dev[fieldName] ?? dev.raw?.[fieldName];
  if (rawValue === undefined || rawValue === null || rawValue === "") return null;
  const value = Number(rawValue);
  return Number.isFinite(value) ? (value > 0.5 ? 1 : 0) : null;
}

function remoteControlTargetAlreadyReached(dev, commandType, targetValue, snapshot = state.snapshot || {}) {
  const currentValue = remoteControlFeedbackValue(dev, commandType, snapshot);
  return currentValue !== null && currentValue === (Number(targetValue) ? 1 : 0);
}

function controlDeviceFromRow(row, snapshot = state.snapshot || {}) {
  const live = snapshotDevice(row.dev_type, row.dev_name, snapshot) || {};
  const measuredRunStat = remoteControlMeasuredValue(row.dev_type, row.dev_name, "run_stat", snapshot);
  const measuredStatus = remoteControlMeasuredValue(row.dev_type, row.dev_name, "status", snapshot);
  return {
    ...live,
    dev_type: row.dev_type,
    dev_name: row.dev_name,
    idx: live.idx ?? live.raw?.idx ?? row.idx ?? "",
    run_stat: measuredRunStat ?? live.run_stat ?? row.run_stat ?? 1,
    status: measuredStatus ?? live.status ?? row.status ?? 1,
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

function commandEntryMatchesControl(entry, dev, commandType, setType = "") {
  if (!entry || !dev) return false;
  if (commandType === "set_value") {
    const items = entry.normalized?.set_values || entry.payload?.set_values || [];
    return items.some((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
      && item.set_type === setType
    ));
  }
  const items = entry.normalized?.run_status || entry.payload?.run_status || [];
  return items.some((item) => (
    item.dev_type === deviceType(dev)
    && item.dev_name === deviceName(dev)
    && (commandType === "status"
      ? Object.prototype.hasOwnProperty.call(item, "status")
      : item.run_stat !== undefined && item.run_stat !== "")
  ));
}

function activeCommandEntryForControl(
  dev,
  commandType,
  setType = "",
  snapshot = state.snapshot || {},
  origin = "effective",
) {
  const entries = origin === "manual" ? allActiveCommandHistory(snapshot) : activeCommandHistory(snapshot);
  return [...entries].reverse().find((entry) => (
    (origin !== "manual" || commandOrigin(entry) === "manual")
    && commandEntryMatchesControl(entry, dev, commandType, setType)
  )) || null;
}

function emptyIssuedCommandInfo() {
  return { wall_time: "--", simu_time: "--", source: "", command_origin: "", origin_text: "--" };
}

function remoteControlIssuedTimeInfo(dev, commandType = "run_stat", snapshot = state.snapshot || {}) {
  const entry = activeCommandEntryForControl(dev, commandType, "", snapshot);
  return entry ? commandSentTimeInfo(entry, snapshot) : emptyIssuedCommandInfo();
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

function activeCommandCancelName(
  dev,
  commandType,
  setType = "",
  snapshot = state.snapshot || {},
  issuedTime = null,
  origin = "manual",
) {
  if (!dev) return "";
  const fieldName = commandType === "set_value" ? setType : (commandType === "status" ? "status" : "run_stat");
  if (!fieldName) return "";
  const entry = activeCommandEntryForControl(dev, commandType, setType, snapshot, origin);
  if (!entry) return "";
  return `${deviceType(dev)}.${deviceName(dev)}.${fieldName}`;
}

async function sendCommandCancel(commandName, label = "", origin = "manual") {
  const name = String(commandName || "").trim();
  const normalizedOrigin = origin === "automatic" ? "automatic" : "manual";
  const sendingKey = `${normalizedOrigin}|${name}`;
  if (!name || state.commandCancelSending.has(sendingKey)) return;
  const displayLabel = label || name;
  const actionLabel = normalizedOrigin === "manual" ? "退出人工指令" : "取消自动指令";
  if (!window.confirm(`确认${actionLabel}：${displayLabel}？`)) return;
  const body = withCommandSendTime({
    source: "trainee-ui",
    command_origin: origin,
    cancel_commands: [{ name: commandName }],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  state.commandCancelSending.add(sendingKey);
  addRuntimeLog("人工退出", targetName, "退出请求", `${displayLabel}；范围 ${commandOriginLabel(normalizedOrigin)}`);
  renderCombinedControlPage();
  try {
    const result = await postTeacherCommand(body);
    const cancelled = result.cancelled || result;
    const count = Number(cancelled.remote_controls || 0) + Number(cancelled.remote_adjustments || 0);
    addRuntimeLog(
      "模拟台响应",
      targetName,
      count ? "退出成功" : "无可退出指令",
      `${displayLabel}；退出 ${count} 条，缺失 ${cancelled.missing || 0} 条`,
      count ? "ok" : "warn",
    );
    await refresh();
  } catch (error) {
    addRuntimeLog("模拟台响应", targetName, "退出失败", apiErrorText(error), "error");
  } finally {
    state.commandCancelSending.delete(sendingKey);
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
    const cancelName = activeCommandCancelName(row.dev, row.commandType, "", snapshot, issuedTime, "manual");
    return {
      ...row,
      key: `${deviceKey(row.dev)}|${row.commandType}`,
      traceKey: commandTraceRunKey(row.dev, row.commandType),
      name: `${deviceType(row.dev)}.${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`,
      category: "遥控",
      issuedTime,
      commandOrigin: issuedTime.command_origin,
      commandOriginText: issuedTime.origin_text,
      cancelName,
      active: issuedTime.wall_time !== "--",
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

function commandTableRowOrigin(row) {
  const origin = String(row?.commandOrigin || row?.issuedTime?.command_origin || "").trim().toLowerCase();
  return ["manual", "automatic"].includes(origin) ? origin : "";
}

function commandTableName(row) {
  if (row?.name) return row.name;
  if (row?.commandType) return `${deviceType(row.dev)}.${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`;
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
  const originSelect = $("commandOriginFilter");
  if (originSelect) originSelect.value = state.commandOriginFilter || "all";
}

function applyCommandTableFilters(rows) {
  const keyword = state.commandKeywordFilter || "";
  const type = state.commandTypeFilter || "all";
  const origin = state.commandOriginFilter || "all";
  return (rows || []).filter((row) => {
    if (state.commandOnlyActive && !row.active) return false;
    if (!tableFilterMatchesKeyword(commandTableFilterFields(row), keyword)) return false;
    if (type !== "all" && commandTableTypeLabel(row) !== type) return false;
    if (origin !== "all" && commandTableRowOrigin(row) !== origin) return false;
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
  return activeTab === "remote-adjustment" ? 7 : 10;
}

function traineeCommandTableStructureKey(rows, activeTab = state.activeControlTab) {
  const filter = state.controlFilter || { dev_type: "all", dev_name: "" };
  return [
    activeTab,
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.commandKeywordFilter || "",
    state.commandTypeFilter || "all",
    state.commandOriginFilter || "all",
    state.commandOnlyActive ? "active" : "all",
    rows.map((row) => traineeCommandTraceKey(row)).join("||"),
  ].join("::");
}

function traineeCommandCancelButtonHtml(cancelName, cancelLabel, origin = "manual") {
  const sendingKey = `${origin}|${cancelName}`;
  const sending = cancelName && state.commandCancelSending.has(sendingKey);
  return `
    <button type="button" class="command-cancel-button" data-command-cancel-name="${escapeHtml(cancelName)}" data-command-cancel-label="${escapeHtml(cancelLabel)}" data-command-cancel-origin="${escapeHtml(origin)}" ${cancelName && !sending ? "" : "disabled"}>
      ${sending ? "退出中" : "退出人工"}
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
  if (field === "origin") return escapeHtml(row.commandOriginText || "--");
  if (field === "cancel") {
    return traineeCommandCancelButtonHtml(
      row.cancelName || "",
      row.name,
    );
  }
  return "";
}

function traineeRemoteAdjustmentLiveValue(row, field) {
  if (field === "measurement") return escapeHtml(formatRemoteAdjustmentValue(row.measurement));
  if (field === "control") return escapeHtml(formatRemoteAdjustmentValue(row.controlValue));
  if (field === "wall_time") return escapeHtml(row.issuedTime?.wall_time || row.issuedAt || "--");
  if (field === "simu_time") return escapeHtml(row.issuedTime?.simu_time || "--");
  if (field === "origin") return escapeHtml(row.commandOriginText || "--");
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
      <td data-trainee-command-live-field="origin">${traineeCommandLiveCellHtml(row, "origin", activeTab)}</td>
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
    return `<tr class="${classes}" data-trainee-command-row-key="${escapeHtml(traceKey)}" data-command-trace-key="${escapeHtml(traceKey)}" data-command-trace-label="${escapeHtml(row.name)}" data-run-status-command="${escapeHtml(key)}" title="单击选中曲线，双击进行遥控操作">
      <td>${escapeHtml(deviceIndex(row.dev))}</td>
      <td>${escapeHtml(row.name)}</td>
      <td>${escapeHtml(deviceName(row.dev))}</td>
      <td>${escapeHtml(deviceType(row.dev))}</td>
      <td class="run-status-command-cell" title="双击进行遥控操作" data-trainee-command-live-field="status">${traineeCommandLiveCellHtml(row, "status", activeTab)}</td>
      <td data-trainee-command-live-field="control">${traineeCommandLiveCellHtml(row, "control", activeTab)}</td>
      <td data-trainee-command-live-field="origin">${traineeCommandLiveCellHtml(row, "origin", activeTab)}</td>
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
          <col class="remote-adjustment-origin-col" />
          <col class="remote-adjustment-time-col" />
          <col class="remote-adjustment-time-col" />
          <col class="remote-adjustment-action-col" />
        </colgroup>
        <thead><tr><th>遥调名称</th><th>量测值</th><th>控制值</th><th>指令来源</th><th>下发本机时刻</th><th>下发仿真时刻</th><th>操作</th></tr></thead>
        <tbody>
          ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
          ${renderTraineeCommandRows(rows, activeTab)}
          ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
        </tbody>
      </table>`;
  }
  return `
    <table class="runtime-device-table">
      <thead><tr><th>idx</th><th>遥控名称</th><th>设备名称</th><th>类型</th><th>当前状态</th><th>下发状态</th><th>指令来源</th><th>下发本机时刻</th><th>下发仿真时刻</th><th>操作</th></tr></thead>
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

function effectiveRemoteAdjustmentValue(dev, setType, snapshot = state.snapshot || {}) {
  const entry = activeCommandEntryForControl(dev, "set_value", setType, snapshot);
  if (!entry) return undefined;
  const items = entry.normalized?.set_values
    || entry.payload?.set_values
    || entry.payload?.setValues
    || entry.payload?.setpoints
    || [];
  const match = items.find((item) => (
    item?.dev_type === deviceType(dev)
    && item?.dev_name === deviceName(dev)
    && item?.set_type === setType
  ));
  if (!match) return undefined;
  const value = match.set_value ?? match.value;
  return value === "" || value === undefined || value === null ? undefined : value;
}

function converterUsesDcPowerSetpoint(dev) {
  const raw = dev?.raw || {};
  const acControlType = String(raw.ac_control_type ?? dev?.ac_control_type ?? "").trim().toUpperCase();
  const dcControlType = String(raw.dc_control_type ?? dev?.dc_control_type ?? "").trim().toUpperCase();
  return dcControlType === "P"
    || (dcControlType === "NONE" && (!acControlType || acControlType === "NONE"));
}

function currentSetValue(dev, setType, snapshot = state.snapshot || {}) {
  const key = `${deviceKey(dev)}|${setType}`;
  if (pending.set_values.has(key)) return pending.set_values.get(key).set_value;
  const effective = effectiveRemoteAdjustmentValue(dev, setType, snapshot);
  if (effective !== undefined) return effective;
  const exact = dev.set_values?.[setType];
  if (exact !== undefined) return exact;
  const raw = dev.raw || {};
  if (setType === "p_set") {
    const dcPriority = converterUsesDcPowerSetpoint(dev);
    return dev.set_values?.p_set
      ?? (dcPriority ? dev.set_values?.p_dc_set : dev.set_values?.p_ac_set)
      ?? (dcPriority ? raw.p_dc_set : raw.p_ac_set)
      ?? raw.p_set
      ?? raw.pv0
      ?? "";
  }
  if (raw[setType] !== undefined) return raw[setType];
  if (setType === "q_set") return raw.q_set ?? raw.q_ac_set ?? raw.qv0 ?? "";
  if (setType === "v_set") return raw.v_set ?? raw.v_ac_set ?? "";
  return "";
}

function remoteAdjustmentTypeLabel(setType) {
  return {
    p_set: "P有功设定",
    p_ac_set: "ACP有功设定",
    p_dc_set: "DCP有功设定",
    q_set: "Q无功设定",
    v_set: "V电压设定",
    flow_set: "气流量设定",
  }[setType] || setType;
}

function remoteAdjustmentName(dev, setType) {
  return `${deviceType(dev)}.${deviceName(dev)}.${remoteAdjustmentTypeLabel(setType)}`;
}

function remoteAdjustmentMeasurementTypeCandidates(dev, setType) {
  const setKey = String(setType || "").trim().toLowerCase();
  if (!setKey) return [];
  const measurementKey = setKey.endsWith("_set") ? setKey.slice(0, -4) : setKey;
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

function remoteAdjustmentMeasTypeMatchesSetType(measType, setType, dev = null) {
  const type = String(measType || "").toUpperCase();
  const setKey = String(setType || "").trim().toUpperCase();
  if (!type || !setKey) return false;
  if (!setKey.endsWith("_SET")) return type === setKey;
  return remoteAdjustmentMeasurementTypeCandidates(dev, setType).includes(type);
}

function remoteAdjustmentMeasurementRowIsValid(row) {
  const valid = row?.valid;
  if (valid === undefined || valid === null || valid === "") return true;
  const numeric = Number(valid);
  return !Number.isFinite(numeric) || numeric !== 0;
}

function remoteAdjustmentMeasurement(dev, setType, snapshot = state.snapshot || {}) {
  const targetType = String(deviceType(dev) || "").trim().toUpperCase();
  const targetName = String(deviceName(dev) || "").trim();
  const measurements = snapshot.measurements || {};
  const candidates = remoteAdjustmentMeasurementTypeCandidates(dev, setType);
  for (const candidate of candidates) {
    const match = (measurements.scada || []).find((row) => (
      String(row?.dev_type || "").trim().toUpperCase() === targetType
      && String(row?.dev_name || "").trim() === targetName
      && remoteAdjustmentMeasTypeMatchesSetType(row?.meas_type, candidate)
      && remoteAdjustmentMeasurementRowIsValid(row)
      && row?.value !== undefined
      && row?.value !== null
      && String(row.value).trim() !== ""
      && Number.isFinite(Number(row.value))
    ));
    if (match) return Number(match.value);
  }
  return null;
}

function remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot = state.snapshot || {}) {
  const entry = activeCommandEntryForControl(dev, "set_value", setType, snapshot);
  return entry ? commandSentTimeInfo(entry, snapshot) : emptyIssuedCommandInfo();
}

function remoteAdjustmentIssuedAt(dev, setType, snapshot = state.snapshot || {}) {
  return remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot).wall_time;
}

function remoteAdjustmentRows(devices, snapshot = state.snapshot || {}, options = {}) {
  return selectedControlRows("SetValue", devices, snapshot).map((definitionRow) => {
    const dev = controlDeviceFromRow(definitionRow, snapshot);
    const setType = definitionRow.set_type || "";
    const issuedTime = remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot);
    const cancelName = activeCommandCancelName(dev, "set_value", setType, snapshot, issuedTime, "manual");
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
        const current = currentSetValue(dev, setType, snapshot);
        return current === "" || current === undefined || current === null ? definitionRow.set_value : current;
      })(),
      issuedAt: issuedTime.wall_time,
      issuedTime,
      commandOrigin: issuedTime.command_origin,
      commandOriginText: issuedTime.origin_text,
      cancelName,
      active: issuedTime.wall_time !== "--",
      cancelSending: state.commandCancelSending.has(`manual|${cancelName}`),
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
    <table class="runtime-log-table runtime-log-table-resizable">
      ${runtimeLogColgroupHtml()}
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
  enableRuntimeLogColumnResizing(commandHistory.querySelector(".runtime-log-table-resizable"));
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
      const measuredActualValue = remoteControlMeasuredValue(devType, devName, commandType, snapshot);
      const actualValue = measuredActualValue ?? (isStatus ? liveDev.status : liveDev.run_stat);
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

function diagramDeviceCommandContext(container, devId, snapshot = state.snapshot || {}) {
  const record = diagramDeviceRecord(container, devId);
  if (!record) return null;
  const dev = controlDefinitionDevices(snapshot).find((candidate) => (
    deviceType(candidate) === record.devType
    && deviceName(candidate) === record.devName
  )) || null;
  const remoteControls = dev ? remoteControlCommandRows([dev], snapshot) : [];
  const adjustments = dev ? diagramDeviceAdjustmentRows(dev, snapshot) : [];
  return {
    container,
    devId: record.devId,
    record,
    dev,
    options: [
      ...remoteControls.map((row) => ({ kind: "remote-control", row })),
      ...adjustments.map((row) => ({ kind: "remote-adjustment", row })),
    ],
  };
}

function diagramDeviceAdjustmentRows(dev, snapshot = state.snapshot || {}) {
  const bindings = Array.isArray(dev?.control_bindings) ? dev.control_bindings : [];
  if (!bindings.length) return remoteAdjustmentRows([dev], snapshot);
  const couplingControlSetType = {
    P: "p_set",
    FLOW: "flow_set",
  }[String(dev?.mode ?? dev?.raw?.control_type ?? "").trim().toUpperCase()] || "";
  const controlDevices = controlDefinitionDevices(snapshot);
  return bindings.flatMap((binding) => {
    const bindingSetType = String(binding?.set_type || binding?.target_set_type || "");
    const bindingIsActive = typeof binding?.active === "boolean"
      ? binding.active
      : Boolean(couplingControlSetType && bindingSetType === couplingControlSetType);
    if (!bindingIsActive) return [];
    const targetType = String(binding?.target_dev_type || "");
    const targetName = String(binding?.target_dev_name || "");
    const targetSetType = String(binding?.target_set_type || binding?.set_type || "");
    const target = controlDevices.find((candidate) => (
      deviceType(candidate) === targetType
      && deviceName(candidate) === targetName
    ));
    if (!target) return [];
    return remoteAdjustmentRows([target], snapshot).filter(
      (row) => row.setType === targetSetType,
    );
  });
}

function closeDiagramDeviceCommandDialog() {
  const dialog = $("diagramDeviceCommandDialog");
  if (dialog?.open) dialog.close();
  state.diagramDeviceCommandContext = null;
}

function diagramDeviceCommandOptionMarkup(option, index) {
  const row = option?.row || {};
  const isRemoteControl = option?.kind === "remote-control";
  const currentValue = isRemoteControl
    ? remoteControlValueText(row.commandType, row.dev?.[row.valueKey])
    : formatRemoteAdjustmentValue(row.controlValue);
  const detail = isRemoteControl
    ? `当前状态：${currentValue}`
    : `当前控制值：${currentValue}；量测值：${formatRemoteAdjustmentValue(row.measurement)}`;
  return `
    <button class="diagram-device-command-option" type="button" data-diagram-device-command-index="${index}">
      <span class="diagram-device-command-option-main">
        <strong>${escapeHtml(row.name || "设备操作")}</strong>
        <small>${escapeHtml(detail)}</small>
      </span>
      <span class="diagram-device-command-option-type">${isRemoteControl ? "遥控" : "遥调"}</span>
    </button>
  `;
}

function openDiagramDeviceCommandDialog(context) {
  const dialog = $("diagramDeviceCommandDialog");
  if (!dialog || !context) return;
  state.diagramDeviceCommandContext = context;
  $("diagramDeviceCommandTitle").textContent = "设备人工操作";
  $("diagramDeviceCommandDevice").textContent = context.record.devName || context.record.devId || "--";
  $("diagramDeviceCommandType").textContent = `${context.record.devType || "--"} / ${context.record.devId || "--"}`;
  $("diagramDeviceCommandList").innerHTML = context.options
    .map((option, index) => diagramDeviceCommandOptionMarkup(option, index))
    .join("");
  $("diagramDeviceCommandHint").textContent = context.options.length
    ? "请选择要执行的人工遥控或遥调操作。"
    : "当前设备未配置遥控或遥调点";
  $("diagramDeviceCommandHint").className = context.options.length
    ? "remote-control-hint"
    : "remote-control-hint is-error";
  if (!dialog.open) dialog.showModal();
}

function refreshDiagramDeviceCommandDialog(snapshot = state.snapshot || {}) {
  const dialog = $("diagramDeviceCommandDialog");
  const context = state.diagramDeviceCommandContext;
  if (!dialog?.open || !context) return;
  const refreshedContext = diagramDeviceCommandContext(context.container, context.devId, snapshot);
  if (!refreshedContext) {
    closeDiagramDeviceCommandDialog();
    return;
  }
  openDiagramDeviceCommandDialog(refreshedContext);
}

function activateDiagramDeviceCommandOption(option) {
  if (!option?.row) return;
  if (option.kind === "remote-control") {
    openRemoteControlDialog(option.row.dev, option.row.commandType);
    return;
  }
  if (option.kind === "remote-adjustment") openRemoteAdjustmentDialog(option.row);
}

function openDiagramDeviceCommandForSvgDevice(container, devId) {
  const context = diagramDeviceCommandContext(container, devId, state.snapshot || {});
  if (!context) return;
  setDiagramSelectedDevice(container, context.devId);
  if (context.options.length === 1) {
    activateDiagramDeviceCommandOption(context.options[0]);
    return;
  }
  openDiagramDeviceCommandDialog(context);
}

function closeRemoteControlDialog() {
  const dialog = $("remoteControlDialog");
  if (dialog?.open) dialog.close();
  state.remoteControlDevice = null;
  state.remoteControlSending = false;
}

function updateRemoteControlDialogSummary(dev, commandType = dev?.__command_type || "run_stat") {
  if (!dev) return 0;
  state.remoteControlDevice = { ...dev, __command_type: commandType };
  const valueKey = commandType === "status" ? "status" : "run_stat";
  const currentRun = Number(dev[valueKey]) ? 1 : 0;
  $("remoteControlDevice").textContent = deviceName(dev);
  $("remoteControlType").textContent = `${deviceType(dev)} / ${remoteControlLabel(commandType)}`;
  $("remoteControlCurrent").innerHTML = `<span class="status-pill ${currentRun ? "is-ok" : "is-off"}">${remoteControlValueText(commandType, currentRun)}</span>`;
  return currentRun;
}

function refreshRemoteControlDialog(snapshot = state.snapshot || {}) {
  const dialog = $("remoteControlDialog");
  const current = state.remoteControlDevice;
  if (!dialog?.open || !current) return;
  const commandType = current.__command_type === "status" ? "status" : "run_stat";
  const key = `${deviceKey(current)}|${commandType}`;
  const refreshed = remoteControlCommandRows(controlDefinitionDevices(snapshot), snapshot)
    .find((row) => row.key === key);
  if (!refreshed) {
    closeRemoteControlDialog();
    return;
  }
  updateRemoteControlDialogSummary(refreshed.dev, commandType);
}

function openRemoteControlDialog(dev, commandType = dev?.__command_type || "run_stat") {
  const dialog = $("remoteControlDialog");
  if (!dialog || !dev) return;
  state.remoteControlSending = false;
  const currentRun = updateRemoteControlDialogSummary(dev, commandType);
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
  if (!dialog.open) dialog.showModal();
}

function remoteControlCommandAcceptance(result = {}) {
  const wrapped = result?.accepted && typeof result.accepted === "object" ? result.accepted : {};
  const acceptedValue = result?.run_status ?? wrapped.run_status ?? wrapped.remote_controls ?? 0;
  const ignoredValue = result?.ignored ?? wrapped.ignored ?? 0;
  const accepted = Number.isFinite(Number(acceptedValue)) ? Math.max(0, Number(acceptedValue)) : 0;
  const ignored = Number.isFinite(Number(ignoredValue)) ? Math.max(0, Number(ignoredValue)) : 0;
  return { accepted, ignored, ok: accepted > 0 && ignored === 0 };
}

function remoteControlFeedbackSnapshotPath() {
  const params = new URLSearchParams({
    lite: "1",
    static: "0",
    logs: "0",
    measurements: "0",
    devices: "1",
    device_states: "0",
    commands: "0",
  });
  return `/api/trainee/snapshot?${params.toString()}`;
}

async function waitForRemoteControlFeedback(dev, commandType, targetValue, attempts = 4) {
  let latestSnapshot = null;
  let currentValue = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    latestSnapshot = await api(remoteControlFeedbackSnapshotPath());
    currentValue = remoteControlFeedbackValue(dev, commandType, latestSnapshot);
    if (currentValue === (Number(targetValue) ? 1 : 0)) {
      return { confirmed: true, value: currentValue, snapshot: latestSnapshot };
    }
    if (attempt + 1 < attempts) {
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
  }
  return { confirmed: false, value: currentValue, snapshot: latestSnapshot };
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
  const requestedText = remoteControlValueText(commandType, command[commandType]);
  const body = withCommandSendTime({
    source: "trainee-ui",
    ...manualCommandHoldPayload(),
    run_status: [command],
    set_values: [],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  if (remoteControlTargetAlreadyReached(dev, commandType, command[commandType], state.snapshot || {})) {
    $("remoteControlConfirm").disabled = false;
    $("remoteControlConfirm").textContent = "重新选择";
    $("remoteControlHint").textContent = `${deviceName(dev)} 当前已经是${requestedText}，未重复下发。`;
    $("remoteControlHint").className = "remote-control-hint is-warn";
    addRuntimeLog(
      "人工遥控",
      targetName,
      "未下发",
      `${deviceName(dev)} 当前已经是${requestedText}，目标状态没有变化`,
      "warn",
    );
    return;
  }
  state.remoteControlSending = true;
  $("remoteControlConfirm").disabled = true;
  $("remoteControlConfirm").textContent = "下发中";
  $("remoteControlHint").textContent = `${deviceName(dev)}：${requestedText}`;
  addRuntimeLog("人工遥控", targetName, "下发请求", `${deviceName(dev)} → ${requestedText}`);
  try {
    const result = await postTeacherCommand(body);
    const acceptance = remoteControlCommandAcceptance(result);
    if (!acceptance.ok) {
      throw new Error(`模拟台未接受遥控指令：接受 ${acceptance.accepted} 条，忽略 ${acceptance.ignored} 条`);
    }
    const feedback = await waitForRemoteControlFeedback(dev, commandType, command[commandType]);
    if (feedback.snapshot) {
      state.snapshot = mergeTeacherSnapshotWithLocalDefinitions(state.snapshot, feedback.snapshot);
      renderSnapshot(state.snapshot);
    }
    pending.run_status.delete(`${deviceKey(dev)}|${commandType}`);
    updatePendingCount();
    await refresh();
    addRuntimeLog(
      "模拟台响应",
      targetName,
      feedback.confirmed ? "遥控完成" : "已接受待反馈",
      feedback.confirmed
        ? `${deviceName(dev)} → ${requestedText}；模拟台状态反馈已一致`
        : `${deviceName(dev)} → ${requestedText}；接受 ${acceptance.accepted} 条，但状态反馈尚未到位`,
      feedback.confirmed ? "ok" : "warn",
    );
    closeRemoteControlDialog();
  } catch (error) {
    state.remoteControlSending = false;
    $("remoteControlConfirm").disabled = false;
    $("remoteControlConfirm").textContent = "重新下发";
    $("remoteControlHint").textContent = apiErrorText(error);
    $("remoteControlHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥控失败", apiErrorText(error), "error");
  }
}

function findRemoteAdjustmentByKey(key, snapshot = state.snapshot || {}) {
  return remoteAdjustmentRows(controlDefinitionDevices(snapshot), snapshot).find((row) => row.key === key) || null;
}

function closeRemoteAdjustmentDialog() {
  const dialog = $("remoteAdjustmentDialog");
  if (dialog?.open) dialog.close();
  state.remoteAdjustment = null;
  state.remoteAdjustmentSending = false;
}

function updateRemoteAdjustmentDialogSummary(row) {
  if (!row) return;
  state.remoteAdjustment = row;
  $("remoteAdjustmentName").textContent = row.name;
  $("remoteAdjustmentDevice").textContent = `${deviceType(row.dev)} / ${deviceName(row.dev)}`;
  $("remoteAdjustmentMeasurement").textContent = formatRemoteAdjustmentValue(row.measurement);
  $("remoteAdjustmentCurrent").textContent = formatRemoteAdjustmentValue(row.controlValue);
  $("remoteAdjustmentIssuedAt").textContent = row.issuedTime?.wall_time || row.issuedAt || "--";
  if ($("remoteAdjustmentIssuedSimAt")) {
    $("remoteAdjustmentIssuedSimAt").textContent = row.issuedTime?.simu_time || "--";
  }
}

function refreshRemoteAdjustmentDialog(snapshot = state.snapshot || {}) {
  const dialog = $("remoteAdjustmentDialog");
  const current = state.remoteAdjustment;
  if (!dialog?.open || !current) return;
  const refreshed = findRemoteAdjustmentByKey(current.key, snapshot);
  if (!refreshed) {
    closeRemoteAdjustmentDialog();
    return;
  }
  updateRemoteAdjustmentDialogSummary(refreshed);
}

function openRemoteAdjustmentDialog(row) {
  const dialog = $("remoteAdjustmentDialog");
  if (!dialog || !row) return;
  state.remoteAdjustmentSending = false;
  updateRemoteAdjustmentDialogSummary(row);
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
    updatePendingCount();
    await refresh();
    closeRemoteAdjustmentDialog();
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
    else if (field === "origin") state.commandOriginFilter = control.value || "all";
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
    if (chartToggle.matches('input[type="checkbox"]')) return;
    event.preventDefault();
    const chartKey = chartToggle.dataset.chartToggle || "";
    const seriesKey = chartToggle.dataset.chartSeries || "";
    const drawFn = chartKey === "measurementTrace" ? drawMeasurementTraceChart
      : chartKey === "commandTrace" ? drawCommandTraceChart
        : chartKey === "renewableTrend" ? drawRenewableTrendChart
          : null;
    if (chartToggle.dataset.chartLegendVisibility === "true") {
      toggleChartLegendSeriesVisibility(chartKey, seriesKey, drawFn);
    } else {
      toggleChartSeriesVisibility(chartKey, seriesKey, drawFn);
    }
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
  const curveDisplayTreeToggle = target?.closest("[data-curve-display-tree-toggle]");
  if (curveDisplayTreeToggle) {
    event.preventDefault();
    event.stopPropagation();
    requestAnimationFrame(() => toggleCurveDisplayTreeGroup(
      curveDisplayTreeToggle.dataset.curveDisplayTreeToggle || "",
    ));
    return;
  }
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
    const commandOrigin = commandCancelButton.dataset.commandCancelOrigin || "manual";
    sendCommandCancel(commandName, commandLabel, commandOrigin);
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
      ensureSelectedMeasurementHistory();
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
    try {
      await setTraineeReceiveActive(state.activeModelId, false);
    } catch (error) {
      addRuntimeLog("接收模式", "学员台服务端", "停止接收失败", apiErrorText(error), "warn");
      renderReceiveMode(apiErrorText(error));
      return;
    }
    state.receiveMode = false;
    state.frozen = true;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    state.receiveRequestActive = false;
    persistActiveModelContext({ receiveMode: false, frozen: true }, true);
    addRuntimeLog("接收模式", "模拟台实时数据", "停止接收", `冻结于 ${state.lastReceiveAt || "--"}`, "warn");
    noteRenewableReceiveInterruption("连续接收已停止，新能源实时控制已暂停，接收恢复后将自动恢复。");
    renderReceiveMode();
    return;
  }
  await startReceiveMode();
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
$("newModelButton").addEventListener("click", openNewModelDialog);
$("closeNewModelDialog").addEventListener("click", closeNewModelDialog);
$("cancelNewModel").addEventListener("click", closeNewModelDialog);
$("newModelDialog").addEventListener("click", (event) => {
  if (event.target === $("newModelDialog")) closeNewModelDialog();
});
$("newModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createNewModelSlot();
});
$("newModelName").addEventListener("input", () => validateNewModelForm());
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
$("modelInitializeButton").addEventListener("click", openReceiveLinkDialog);
$("traineeRunToggle").addEventListener("click", toggleReceiveMode);
$("receiveLinkClose").addEventListener("click", closeReceiveLinkDialog);
$("receiveLinkCancel").addEventListener("click", closeReceiveLinkDialog);
$("confirmReceiveLink").addEventListener("click", initializeModelFromLink);
$("receiveLinkDialog").addEventListener("click", (event) => {
  if (event.target === $("receiveLinkDialog")) closeReceiveLinkDialog();
});
$("receiveWarningClose").addEventListener("click", closeReceiveWarningDialog);
$("receiveWarningConfirm").addEventListener("click", closeReceiveWarningDialog);
$("receiveWarningDialog").addEventListener("click", (event) => {
  if (event.target === $("receiveWarningDialog")) closeReceiveWarningDialog();
});
$("diagramDeviceCommandClose").addEventListener("click", closeDiagramDeviceCommandDialog);
$("diagramDeviceCommandCancel").addEventListener("click", closeDiagramDeviceCommandDialog);
$("diagramDeviceCommandDialog").addEventListener("click", (event) => {
  if (event.target === $("diagramDeviceCommandDialog")) closeDiagramDeviceCommandDialog();
});
$("diagramDeviceCommandDialog").addEventListener("close", () => {
  state.diagramDeviceCommandContext = null;
});
$("diagramDeviceCommandList").addEventListener("click", (event) => {
  const button = event.target instanceof Element
    ? event.target.closest("[data-diagram-device-command-index]")
    : null;
  if (!button) return;
  const index = Number(button.dataset.diagramDeviceCommandIndex);
  const option = state.diagramDeviceCommandContext?.options?.[index];
  if (option) activateDiagramDeviceCommandOption(option);
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
$("renewableControlParametersButton")?.addEventListener("click", openRenewableControlParametersDialog);
$("closeRenewableControlParametersDialog")?.addEventListener("click", closeRenewableControlParametersDialog);
$("cancelRenewableControlParametersDialog")?.addEventListener("click", closeRenewableControlParametersDialog);
$("saveRenewableControlParameters")?.addEventListener("click", saveRenewableControlParameters);
$("renewableControlPeriod")?.addEventListener("input", syncRenewableControlPeriodConstraints);
$("renewableControlParametersDialog")?.addEventListener("click", (event) => {
  if (event.target === $("renewableControlParametersDialog")) closeRenewableControlParametersDialog();
});
const renewableControlLogTable = $("renewableControlLogTable");
renewableControlLogTable?.addEventListener("click", (event) => {
  const row = event.target.closest("[data-renewable-log-seq]");
  if (!row) return;
  selectRenewableControlLogRow(row.dataset.renewableLogSeq);
});
renewableControlLogTable?.addEventListener("dblclick", (event) => {
  const row = event.target.closest("[data-renewable-log-seq]");
  if (!row) return;
  openRenewableControlLogDetailDialog(row.dataset.renewableLogSeq);
});
renewableControlLogTable?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const row = event.target.closest("[data-renewable-log-seq]");
  if (!row) return;
  event.preventDefault();
  openRenewableControlLogDetailDialog(row.dataset.renewableLogSeq);
});
$("closeRenewableControlLogDetailDialog")?.addEventListener("click", closeRenewableControlLogDetailDialog);
$("confirmRenewableControlLogDetailDialog")?.addEventListener("click", closeRenewableControlLogDetailDialog);
$("renewableControlLogDetailDialog")?.addEventListener("click", (event) => {
  if (event.target === $("renewableControlLogDetailDialog")) closeRenewableControlLogDetailDialog();
});
$("storagePowerDeratingButton")?.addEventListener("click", openStoragePowerDeratingDialog);
$("closeStoragePowerDeratingDialog")?.addEventListener("click", closeStoragePowerDeratingDialog);
$("cancelStoragePowerDerating")?.addEventListener("click", closeStoragePowerDeratingDialog);
$("resetStoragePowerDerating")?.addEventListener("click", resetStoragePowerDeratingCurves);
$("saveStoragePowerDerating")?.addEventListener("click", saveStoragePowerDeratingCurves);
$("storagePowerDeratingDialog")?.addEventListener("click", (event) => {
  if (event.target === $("storagePowerDeratingDialog")) closeStoragePowerDeratingDialog();
});
$("storagePowerDeratingDialog")?.addEventListener("input", () => {
  setStoragePowerDeratingMessage("相邻 SOC 节点之间自动进行线性插值。", "");
});
document.querySelectorAll("[data-renewable-loop-mode]").forEach((button) => {
  button.addEventListener("click", () => setRenewableLoopMode(button.dataset.renewableLoopMode));
});
document.querySelectorAll("[data-renewable-strategy-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tabKey = button.dataset.renewableStrategyTab || "ac-wind";
    if (!RENEWABLE_STRATEGY_TABS[tabKey]) return;
    state.renewableControl.strategyTab = tabKey;
    renderRenewableControl(state.snapshot || {});
  });
});
document.querySelectorAll("[data-renewable-metric-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tabKey = button.dataset.renewableMetricTab || "ac";
    if (!["ac", "dc", "system", "hydrogen"].includes(tabKey)) return;
    state.renewableControl.metricTab = tabKey;
    renderRenewableMetricTabs();
  });
});
document.querySelectorAll("[data-renewable-parameter-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    renderRenewableControlParameterTabs(button.dataset.renewableParameterTab || "runtime");
  });
});
document.querySelectorAll("[data-renewable-detail-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.renewableDetailTab || "trend";
    state.renewableControl.detailTab = ["trend", "logs", "performance"].includes(tab)
      ? tab
      : "trend";
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
$("saveBackendRuntimeParameters").addEventListener("click", () => saveWebRuntimeSettings("backend"));
$("undoBackendRuntimeParameters").addEventListener("click", () => undoWebRuntimeSettings("backend"));
$("restoreBackendRuntimeParameterDefaults").addEventListener("click", () => restoreWebRuntimeDefaults("backend"));
$("saveRuntimeParameters").addEventListener("click", () => saveWebRuntimeSettings("web"));
$("undoRuntimeParameters").addEventListener("click", () => undoWebRuntimeSettings("web"));
$("restoreRuntimeParameterDefaults").addEventListener("click", () => restoreWebRuntimeDefaults("web"));
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
  resetChartPeriodOffsets("measurementTrace");
  drawMeasurementTraceChart();
});
const commandTraceWindow = $("commandTraceWindow");
if (commandTraceWindow) {
  commandTraceWindow.addEventListener("change", (event) => {
    state.commandTraceWindowMinutes = Number(event.target.value) || 60;
    resetChartPeriodOffsets("commandTrace");
    drawCommandTraceChart();
  });
}
const renewableTrendWindow = $("renewableTrendWindow");
if (renewableTrendWindow) {
  renewableTrendWindow.addEventListener("change", (event) => {
    state.renewableTrendWindowMinutes = Number(event.target.value) || 60;
    resetChartPeriodOffsets("renewableTrend");
    drawRenewableTrendChart();
  });
}
renderRenewableTrendSeriesTree();
const renewableTrendSeriesFilter = $("renewableTrendSeriesFilter");
if (renewableTrendSeriesFilter) {
  renewableTrendSeriesFilter.value = state.renewableTrendSeriesFilter;
  renewableTrendSeriesFilter.addEventListener("input", (event) => {
    state.renewableTrendSeriesFilter = event.target.value || "";
    applyRenewableTrendSeriesFilters(state.renewableControl.lastPlan?.metrics || {});
  });
}
const renewableTrendSelectedOnly = $("renewableTrendSelectedOnly");
if (renewableTrendSelectedOnly) {
  renewableTrendSelectedOnly.checked = state.renewableTrendSelectedOnly;
  renewableTrendSelectedOnly.addEventListener("change", (event) => {
    state.renewableTrendSelectedOnly = Boolean(event.target.checked);
    applyRenewableTrendSeriesFilters(state.renewableControl.lastPlan?.metrics || {});
  });
}
const renewableTrendClearAll = $("renewableTrendClearAll");
if (renewableTrendClearAll) {
  renewableTrendClearAll.addEventListener("click", () => {
    setRenewableTrendBatchSeriesVisibility(
      false,
      state.renewableControl.lastPlan?.metrics || {},
    );
  });
}
const renewableTrendSelectAll = $("renewableTrendSelectAll");
if (renewableTrendSelectAll) {
  renewableTrendSelectAll.addEventListener("click", () => {
    setRenewableTrendBatchSeriesVisibility(
      true,
      state.renewableControl.lastPlan?.metrics || {},
    );
  });
}
applyRenewableTrendSeriesFilters(state.renewableControl.lastPlan?.metrics || {});
const renewableTrendSeriesPanel = $("renewableTrendSeriesPanel");
if (renewableTrendSeriesPanel) {
  renewableTrendSeriesPanel.addEventListener("change", (event) => {
    const input = event.target instanceof HTMLInputElement
      ? event.target.closest('input[data-chart-toggle="renewableTrend"][data-chart-series]')
      : null;
    if (!input) return;
    setChartLegendSeriesVisibility(
      "renewableTrend",
      input.dataset.chartSeries || "",
      true,
    );
    setChartSeriesVisibility(
      "renewableTrend",
      input.dataset.chartSeries || "",
      input.checked,
      drawRenewableTrendChart,
    );
  });
}
initTraceChartInteractions("measurementTrace", "measurementTraceChart", drawMeasurementTraceChart);
initTraceChartInteractions("commandTrace", "commandTraceChart", drawCommandTraceChart);
initTraceChartInteractions("renewableTrend", "renewableTrendChart", drawRenewableTrendChart);
initChartPeriodNavigation("measurementTrace", measurementTraceWindowRange, drawMeasurementTraceChart);
initChartPeriodNavigation("commandTrace", commandTraceWindowRange, drawCommandTraceChart);
initChartPeriodNavigation("renewableTrend", renewableTrendWindowRange, drawRenewableTrendChart);
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
document.addEventListener("visibilitychange", () => {
  scheduleNextRefresh(pageIsHidden() ? HIDDEN_REFRESH_INTERVAL_MS : 0);
});

initOverviewBottomSplitter();
initOverviewBottomColumnSplitter();
initVerticalSplitters();
renderReceiveMode();
renderHistory();
initPageNavigation();
loadModels().finally(() => {
  refresh();
  restartRefreshScheduler();
});
