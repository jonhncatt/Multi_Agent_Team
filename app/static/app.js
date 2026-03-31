const state = {
  sessionId: null,
  uploading: false,
  sendingSessionIds: new Set(),
  attachments: [],
  drilling: false,
  evaluating: false,
  runtimeViewMode: null,
  lastHealth: null,
  operationsOverview: null,
  lastBusinessResponse: null,
  latestExecutionPlan: [],
  latestAgentPanels: [],
  latestActiveRoles: new Set(),
  latestCurrentRole: null,
  latestRoleStates: new Map(),
  executionLogEntries: [],
  executionLogFilter: "all",
  executionLogAutoScroll: true,
  commandPaletteOpen: false,
  commandPaletteQuery: "",
  commandPaletteIndex: 0,
  recentCommands: [],
  workspaceView: null,
  chatInfoOpen: false,
  sidebarSessionsOpen: false,
  panelLayout: { leftWidth: 280, rightWidth: 320, leftCollapsed: false, rightCollapsed: false },
};
const SESSION_STORAGE_KEY = "officetool.session_id";
const RUNTIME_VIEW_STORAGE_KEY = "officetool.runtime_view";
const WORKSPACE_VIEW_STORAGE_KEY = "officetool.workspace_view";
const CHAT_INFO_STORAGE_KEY = "officetool.chat_info_open";
const PANEL_LAYOUT_STORAGE_KEY = "officetool.panel_layout";
const RECENT_COMMANDS_STORAGE_KEY = "officetool.recent_commands";

const chatList = document.getElementById("chatList");
const fileInput = document.getElementById("fileInput");
const fileList = document.getElementById("fileList");
const dropZone = document.getElementById("dropZone");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const newSessionBtn = document.getElementById("newSessionBtn");
const sandboxDrillBtn = document.getElementById("sandboxDrillBtn");
const evalHarnessBtn = document.getElementById("evalHarnessBtn");
const sessionIdView = document.getElementById("sessionIdView");
const sessionHistoryView = document.getElementById("sessionHistoryView");
const refreshSessionsBtn = document.getElementById("refreshSessionsBtn");
const deleteSessionBtn = document.getElementById("deleteSessionBtn");
const sidebarSessionShell = document.getElementById("sidebarSessionShell");
const sidebarSessionBody = document.getElementById("sidebarSessionBody");
const sidebarSessionsToggleBtn = document.getElementById("sidebarSessionsToggleBtn");
const sidebarSessionsToggleIcon = document.getElementById("sidebarSessionsToggleIcon");
const tokenStatsView = document.getElementById("tokenStatsView");
const clearStatsBtn = document.getElementById("clearStatsBtn");
const appShell = document.getElementById("appShell");
const controlRail = document.getElementById("controlRail");
const workspaceShell = document.getElementById("workspaceShell");
const opsRail = document.getElementById("opsRail");
const leftRailResizer = document.getElementById("leftRailResizer");
const rightRailResizer = document.getElementById("rightRailResizer");
const appVersionView = document.getElementById("appVersionView");
const productTitleView = document.getElementById("productTitle");
const productHintView = document.getElementById("productHint");
const workspaceCurrentLabel = document.getElementById("workspaceCurrentLabel");
const commandPaletteBtn = document.getElementById("commandPaletteBtn");
const chatInfoToggleBtn = document.getElementById("chatInfoToggleBtn");
const chatInfoCloseBtn = document.getElementById("chatInfoCloseBtn");
const chatInfoPanel = document.getElementById("chatInfoPanel");
const chatInfoBackdrop = document.getElementById("chatInfoBackdrop");
const commandPalette = document.getElementById("commandPalette");
const commandPaletteInput = document.getElementById("commandPaletteInput");
const commandPaletteList = document.getElementById("commandPaletteList");
const workspaceNavButtons = Array.from(document.querySelectorAll("[data-workspace-target]"));
const workspaceViews = Array.from(document.querySelectorAll("[data-workspace-view]"));
const chatWorkspaceView = document.querySelector('.workspace-view[data-workspace-view="chat"]');
const platformStatusHeadline = document.getElementById("platformStatusHeadline");
const platformStatusMeta = document.getElementById("platformStatusMeta");
const platformStatusSignals = document.getElementById("platformStatusSignals");
const moduleRouteHeadline = document.getElementById("moduleRouteHeadline");
const moduleRouteMeta = document.getElementById("moduleRouteMeta");
const moduleRouteTags = document.getElementById("moduleRouteTags");
const qualityOverviewHeadline = document.getElementById("qualityOverviewHeadline");
const qualityOverviewMeta = document.getElementById("qualityOverviewMeta");
const qualityOverviewGrid = document.getElementById("qualityOverviewGrid");
const resultModuleView = document.getElementById("resultModuleView");
const resultGradeView = document.getElementById("resultGradeView");
const resultStrategyView = document.getElementById("resultStrategyView");
const resultModelView = document.getElementById("resultModelView");
const resultReliabilityView = document.getElementById("resultReliabilityView");
const resultContextView = document.getElementById("resultContextView");
const gateSummaryGrid = document.getElementById("gateSummaryGrid");
const replaySummaryView = document.getElementById("replaySummaryView");
const smokeSummaryView = document.getElementById("smokeSummaryView");
const operationsIndexView = document.getElementById("operationsIndexView");

const modelInput = document.getElementById("modelInput");
const execModeInput = document.getElementById("execModeInput");
const tokenInput = document.getElementById("tokenInput");
const ctxInput = document.getElementById("ctxInput");
const styleInput = document.getElementById("styleInput");
const toolInput = document.getElementById("toolInput");
const panelDebugInput = document.getElementById("panelDebugInput");
const rawDebugInput = document.getElementById("rawDebugInput");
const presetGeneralBtn = document.getElementById("presetGeneralBtn");
const presetCodingBtn = document.getElementById("presetCodingBtn");
const modeStatus = document.getElementById("modeStatus");
const runtimeViewModulesBtn = document.getElementById("runtimeViewModulesBtn");
const runtimeViewRolesBtn = document.getElementById("runtimeViewRolesBtn");
const runtimeViewSplitBtn = document.getElementById("runtimeViewSplitBtn");
const runtimeViewStatus = document.getElementById("runtimeViewStatus");
const milestoneSidebarView = document.getElementById("milestoneSidebarView");
const backendPolicyView = document.getElementById("backendPolicyView");
const runStageBadge = document.getElementById("runStageBadge");
const runStageText = document.getElementById("runStageText");
const runStepList = document.getElementById("runStepList");
const executionDagView = document.getElementById("executionDagView");
const executionDagMeta = document.getElementById("executionDagMeta");
const executionDagLegend = document.getElementById("executionDagLegend");
const executionLogFilters = document.getElementById("executionLogFilters");
const executionLogMeta = document.getElementById("executionLogMeta");
const executionLogView = document.getElementById("executionLogView");
const executionLogAutoBtn = document.getElementById("executionLogAutoBtn");
const runPayloadView = document.getElementById("runPayloadView");
const runTraceView = document.getElementById("runTraceView");
const runAgentPanelsView = document.getElementById("runAgentPanelsView");
const runAnswerBundleView = document.getElementById("runAnswerBundleView");
const runLlmFlowView = document.getElementById("runLlmFlowView");
const runRoleBoard = document.getElementById("runRoleBoard");
const kernelLiveLabel = document.getElementById("kernelLiveLabel");
const kernelLiveMeta = document.getElementById("kernelLiveMeta");
const systemFlowRibbon = document.getElementById("systemFlowRibbon");
const kernelCoreMetrics = document.getElementById("kernelCoreMetrics");
const shadowLabMetrics = document.getElementById("shadowLabMetrics");
const evolutionMetrics = document.getElementById("evolutionMetrics");
const moduleBay = document.getElementById("moduleBay");
const moduleBayMeta = document.getElementById("moduleBayMeta");
const evolutionFeed = document.getElementById("evolutionFeed");
const evolutionFeedMeta = document.getElementById("evolutionFeedMeta");
const milestoneRoadmap = document.getElementById("milestoneRoadmap");
const milestoneRoadmapMeta = document.getElementById("milestoneRoadmapMeta");
const kernelConsoleSection = document.getElementById("kernelConsoleSection");
const kernelConsoleTitle = document.getElementById("kernelConsoleTitle");
const kernelConsoleSubtitle = document.getElementById("kernelConsoleSubtitle");
const roleBoardSection = document.getElementById("roleBoardSection");
const roleBoardTitle = document.getElementById("roleBoardTitle");
const roleBoardLegend = document.getElementById("roleBoardLegend");
const roleLabRuntimeMeta = document.getElementById("roleLabRuntimeMeta");
const roleLabRuntimeMetrics = document.getElementById("roleLabRuntimeMetrics");
const roleLabRegistry = document.getElementById("roleLabRegistry");
const roleLabRunGraph = document.getElementById("roleLabRunGraph");
const roleLabRunFailures = document.getElementById("roleLabRunFailures");
const runtimeDebugSections = Array.from(document.querySelectorAll(".debug-only"));

const RUN_FLOW_STEPS = [
  { id: "prepare", label: "1. 准备请求" },
  { id: "send", label: "2. 发送请求" },
  { id: "wait", label: "3. 模型处理中" },
  { id: "parse", label: "4. 整理结果" },
  { id: "done", label: "5. 完成" },
];
const PANEL_DEBUG_STORAGE_KEY = "officetool.panel_debug";
const LAYOUT_DEFAULTS = {
  leftWidth: 280,
  rightWidth: 320,
  leftCollapsed: false,
  rightCollapsed: false,
};
const LOG_FILTERS = [
  { id: "all", label: "全部" },
  { id: "routing", label: "Routing" },
  { id: "planning", label: "Planning" },
  { id: "tool", label: "Tool" },
  { id: "review", label: "Review" },
  { id: "swarm", label: "Swarm" },
  { id: "system", label: "System" },
];
const WORKSPACE_VIEWS = {
  chat: { label: "聊天", meta: "默认极简对话视图" },
  control: { label: "控制", meta: "模型、模式与请求设置" },
  runtime: { label: "运行", meta: "执行链路与日志" },
  modules: { label: "模块", meta: "主核、模块与角色运行态" },
  operations: { label: "运营", meta: "业务结果与运营摘要" },
  system: { label: "系统", meta: "里程碑、路径策略与统计" },
  debug: { label: "调试", meta: "仅在 Debug 模式下显示" },
};
let currentRunStepId = null;
let currentRunTone = "idle";

const LLM_FLOW_STAGE_LABELS = {
  frontend_prepare: "前端组包",
  frontend_error: "前端错误",
  backend_ingress: "后端接收输入",
  backend_router: "规则 Router 判定",
  backend_to_llm: "Processor -> Agent",
  llm_to_backend: "Agent -> Processor",
  backend_tool: "Coordinator 执行工具",
  backend_prefetch: "Coordinator 预取",
  backend_coordinator: "Coordinator 状态更新",
  llm_final: "Agent 输出",
  llm_error: "Agent 错误",
  backend_warning: "后端告警",
  backend_pricing: "计费处理",
  multi_agent_planner: "Planner",
  multi_agent_worker: "Worker",
  multi_agent_reviewer: "Reviewer",
  multi_agent_revision: "Revision",
  multi_agent_specialist: "Specialist",
};

const MODE_PRESETS = {
  general: {
    label: "通用模式",
    model: "gpt-5.1-chat",
    maxOutputTokens: 128000,
    maxContextTurns: 2000,
    responseStyle: "normal",
    enableTools: true,
  },
  coding: {
    label: "编码模式",
    model: "gpt-5.1-codex-mini",
    maxOutputTokens: 128000,
    maxContextTurns: 2000,
    responseStyle: "normal",
    enableTools: true,
  },
};

const AGENT_OS_MILESTONES = [
  {
    id: "M1",
    title: "平台边界与基线指标",
    status: "done",
    summary: "边界规则、shim 台账、platform metrics 和 workflow 雏形已经落地。",
    tags: ["boundary gate", "shim inventory", "metrics artifact"],
  },
  {
    id: "M2",
    title: "第二模块选择",
    status: "done",
    summary: "已完成候选对比，当前默认第二正式模块为 research_module。",
    tags: ["research_module", "candidate matrix", "no office pseudo-split"],
  },
  {
    id: "M3",
    title: "第二正式模块交付",
    status: "done",
    summary: "research_module 已可独立 dispatch、独立 demo、独立测试。",
    tags: ["kernel dispatch", "independent demo", "integration tests"],
  },
  {
    id: "M4",
    title: "Swarm 合同冻结",
    status: "done",
    summary: "branch/join/aggregator contract 已冻结，默认退化策略已明确为 serial_replay + mark_only。",
    tags: ["branch/join", "aggregator", "serial_replay", "mark_only"],
  },
  {
    id: "M5",
    title: "Swarm MVP",
    status: "done",
    summary: "research_module 已交付多输入并行 + 最小聚合的 Swarm MVP，并带串行补跑退化与可读 demo。",
    tags: ["parallel inputs", "serial replay", "minimal aggregation", "demo readability"],
  },
  {
    id: "M6",
    title: "门禁与 shim 退场",
    status: "done",
    summary: "module/swarm/shim 门禁已经在 workflow 中收口，且 kernel_host 在内的兼容主阻塞已正式退场。",
    tags: ["workflow gates", "shim retirement", "regression guard", "kernel_host retired"],
  },
  {
    id: "M7",
    title: "Kernel Host 退场决策",
    status: "done",
    summary: "kernel_host 已完成 class-level retirement；runtime assembly 改由显式 legacy facade/helper bindings 承接。",
    tags: ["class retirement", "legacy facade", "boundary gate", "runtime detached"],
  },
];

const ROLE_DEFS = [
  {
    id: "router",
    title: "Router",
    kindKey: "hybrid",
    kindLabel: "Agent + Processor",
    blurb: "为当前请求分诊，决定后续链路。",
    colors: { accent: "#4f7eff", accent2: "#98b7ff" },
  },
  {
    id: "coordinator",
    title: "Coordinator",
    kindKey: "processor",
    kindLabel: "Processor",
    blurb: "维护运行时状态，推动工具链与纠偏。",
    colors: { accent: "#c66c2d", accent2: "#f3b170" },
  },
  {
    id: "planner",
    title: "Planner",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "提炼目标、限制与执行计划。",
    colors: { accent: "#2d9f6f", accent2: "#8dd6b1" },
  },
  {
    id: "researcher",
    title: "Researcher",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "生成联网搜索与取证简报。",
    colors: { accent: "#2e77bb", accent2: "#89bde9" },
  },
  {
    id: "file_reader",
    title: "FileReader",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "为文档和附件生成阅读定位策略。",
    colors: { accent: "#7e5cff", accent2: "#c7b7ff" },
  },
  {
    id: "summarizer",
    title: "Summarizer",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "把大段内容压成高信息量摘要。",
    colors: { accent: "#20a2a5", accent2: "#8ad9da" },
  },
  {
    id: "fixer",
    title: "Fixer",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "聚焦修复动作与补丁方向。",
    colors: { accent: "#d98a1f", accent2: "#f5c06c" },
  },
  {
    id: "worker",
    title: "Worker",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "执行主任务，必要时调用工具链。",
    colors: { accent: "#137a58", accent2: "#60c79f" },
  },
  {
    id: "conflict_detector",
    title: "Conflict Detector",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "报警明显冲突与高风险确定性。",
    colors: { accent: "#c94a4a", accent2: "#f0a35c" },
  },
  {
    id: "reviewer",
    title: "Reviewer",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "审查覆盖度、证据链和交付风险。",
    colors: { accent: "#2c8b4b", accent2: "#8cd2a1" },
  },
  {
    id: "revision",
    title: "Revision",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "按审阅结论做最后修订。",
    colors: { accent: "#a45ad1", accent2: "#e3b8ff" },
  },
  {
    id: "structurer",
    title: "Structurer",
    kindKey: "agent",
    kindLabel: "Agent",
    blurb: "整理结构化证据包与 assertions（关键结论）。",
    colors: { accent: "#3f7f9b", accent2: "#9fcbe0" },
  },
];

const ROLE_DEF_MAP = new Map(ROLE_DEFS.map((item) => [item.id, item]));
const ROLE_KIND_LABELS = {
  agent: "Agent",
  processor: "Processor",
  hybrid: "Agent + Processor",
};
const ROLE_TOKEN_MAP = new Map([
  ["router", "router"],
  ["coordinator", "coordinator"],
  ["planner", "planner"],
  ["researcher", "researcher"],
  ["file_reader", "file_reader"],
  ["file reader", "file_reader"],
  ["summarizer", "summarizer"],
  ["fixer", "fixer"],
  ["worker", "worker"],
  ["reviewer", "reviewer"],
  ["revision", "revision"],
  ["structurer", "structurer"],
  ["conflict_detector", "conflict_detector"],
  ["conflict detector", "conflict_detector"],
]);

function normalizeRoleId(value) {
  const raw = String(value || "").trim().toLowerCase();
  return ROLE_TOKEN_MAP.get(raw) || raw.replace(/\s+/g, "_");
}

function normalizeRoleKind(value, fallback = "agent") {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "agent" || raw === "processor" || raw === "hybrid") return raw;
  return fallback;
}

function normalizeRoleSet(value) {
  const roles = new Set();
  (Array.isArray(value) ? value : []).forEach((item) => {
    const roleId = normalizeRoleId(item);
    if (roleId) roles.add(roleId);
  });
  return roles;
}

function normalizeRoleStateMap(value) {
  const states = new Map();
  (Array.isArray(value) ? value : []).forEach((item) => {
    const roleId = normalizeRoleId(item?.role);
    if (!roleId) return;
    states.set(roleId, {
      role: roleId,
      status: String(item?.status || "").trim().toLowerCase(),
      phase: String(item?.phase || "").trim(),
      detail: String(item?.detail || "").trim(),
    });
  });
  return states;
}

function detectRolesFromText(text) {
  const lower = String(text || "").toLowerCase();
  const roles = new Set();
  ROLE_TOKEN_MAP.forEach((roleId, token) => {
    if (lower.includes(token)) roles.add(roleId);
  });
  if (lower.includes("specialist")) {
    ["researcher", "file_reader", "summarizer", "fixer"].forEach((roleId) => {
      if (lower.includes(roleId.replace("_", " ")) || lower.includes(roleId)) roles.add(roleId);
    });
  }
  return roles;
}

function inferActiveRolesFromDebugItem(item) {
  const roles = detectRolesFromText(`${String(item?.title || "")}\n${String(item?.detail || "")}`);
  const stage = String(item?.stage || "").trim().toLowerCase();
  if (stage === "backend_router") {
    roles.add("router");
    roles.add("coordinator");
  }
  if (stage === "backend_tool" || stage === "backend_prefetch" || stage === "backend_coordinator") {
    roles.add("coordinator");
  }
  if (stage === "backend_to_llm" || stage === "llm_to_backend" || stage === "llm_final" || stage === "llm_error") {
    if (roles.size) roles.add("coordinator");
  }
  return roles;
}

function svgRect(x, y, color, size = 4) {
  return `<rect x="${x * size}" y="${y * size}" width="${size}" height="${size}" fill="${color}" />`;
}

function buildRoleSprite(roleId) {
  const meta = ROLE_DEF_MAP.get(roleId) || ROLE_DEFS[0];
  const outline = "#1f2f27";
  const shell = "#dcefe2";
  const shadow = "#a3c1b1";
  const eye = meta.kindKey === "processor" ? "#fff1c9" : "#f6fff6";
  const accent = meta.colors.accent;
  const accent2 = meta.colors.accent2;
  const px = [];
  const add = (cells, color) => {
    cells.forEach(([x, y]) => px.push(svgRect(x, y, color)));
  };

  add(
    [
      [3, 1], [4, 1], [5, 1], [6, 1], [7, 1], [8, 1],
      [2, 2], [9, 2], [2, 3], [9, 3], [1, 3], [10, 3],
      [2, 4], [9, 4], [1, 4], [10, 4],
      [2, 5], [9, 5],
      [2, 6], [9, 6],
      [3, 7], [4, 7], [5, 7], [6, 7], [7, 7], [8, 7],
      [3, 8], [8, 8], [3, 9], [8, 9],
      [4, 10], [5, 10], [6, 10], [7, 10],
      [4, 11], [7, 11],
    ],
    outline
  );
  add(
    [
      [3, 2], [4, 2], [5, 2], [6, 2], [7, 2], [8, 2],
      [3, 3], [4, 3], [5, 3], [6, 3], [7, 3], [8, 3],
      [3, 4], [4, 4], [5, 4], [6, 4], [7, 4], [8, 4],
      [3, 5], [4, 5], [5, 5], [6, 5], [7, 5], [8, 5],
      [3, 6], [4, 6], [5, 6], [6, 6], [7, 6], [8, 6],
      [4, 8], [5, 8], [6, 8], [7, 8],
      [4, 9], [5, 9], [6, 9], [7, 9],
      [5, 11], [6, 11],
    ],
    shell
  );
  add(
    [
      [4, 6], [5, 6], [6, 6], [7, 6],
      [4, 9], [5, 9], [6, 9], [7, 9],
    ],
    shadow
  );
  add(
    roleId === "conflict_detector" ? [[4, 4]] : [[4, 4], [7, 4]],
    roleId === "conflict_detector" ? "#ffef78" : eye
  );
  if (roleId === "conflict_detector") {
    add([[7, 4]], "#ff8872");
  }

  switch (roleId) {
    case "router":
      add([[2, 0], [3, 0], [8, 0], [9, 0], [5, 8], [6, 9]], accent);
      add([[4, 0], [7, 0], [5, 9], [6, 8]], accent2);
      break;
    case "coordinator":
      add([[4, 0], [5, 0], [6, 0], [7, 0], [5, 3], [6, 3], [5, 8], [6, 8]], accent);
      add([[5, 1], [6, 1], [4, 8], [7, 8]], accent2);
      break;
    case "planner":
      add([[2, 0], [3, 0], [4, 0], [5, 0], [6, 0], [7, 0], [8, 0], [9, 0]], accent);
      add([[4, 8], [5, 8], [6, 8], [7, 8], [4, 9], [7, 9]], accent2);
      break;
    case "researcher":
      add([[6, 0], [6, 1], [10, 2], [10, 3], [8, 8], [8, 9]], accent);
      add([[7, 1], [9, 2], [9, 3], [5, 8], [6, 8]], accent2);
      break;
    case "file_reader":
      add([[4, 8], [4, 9], [5, 8], [5, 9]], accent);
      add([[6, 8], [6, 9], [7, 8], [7, 9]], accent2);
      add([[5, 9], [6, 9]], outline);
      break;
    case "summarizer":
      add([[4, 5], [5, 5], [6, 5], [7, 5], [3, 9], [5, 8], [7, 9]], accent);
      add([[4, 8], [6, 8], [8, 9]], accent2);
      break;
    case "fixer":
      add([[0, 8], [1, 8], [2, 8], [8, 9], [9, 8], [10, 7]], accent);
      add([[1, 7], [2, 9], [9, 7], [10, 8]], accent2);
      break;
    case "worker":
      add([[3, 3], [4, 3], [5, 3], [6, 3], [7, 3], [8, 3], [4, 9], [5, 9], [6, 9], [7, 9]], accent);
      add([[3, 4], [8, 4], [4, 8], [7, 8]], accent2);
      break;
    case "conflict_detector":
      add([[5, 0], [6, 0], [5, 8], [6, 8]], accent);
      add([[4, 0], [7, 0], [4, 8], [7, 8]], accent2);
      break;
    case "reviewer":
      add([[5, 8], [6, 8], [4, 9], [5, 9], [6, 9], [7, 9], [5, 10], [6, 10]], accent);
      add([[5, 1], [6, 1], [5, 2], [6, 2]], accent2);
      break;
    case "revision":
      add([[3, 0], [4, 1], [5, 2], [6, 3], [7, 4], [8, 5], [4, 9], [5, 8], [6, 9], [7, 8]], accent);
      add([[4, 0], [5, 1], [6, 2], [7, 3], [8, 4]], accent2);
      break;
    case "structurer":
      add([[4, 8], [5, 8], [6, 8], [7, 8], [4, 9], [7, 9], [4, 10], [5, 10], [6, 10], [7, 10]], accent);
      add([[5, 9], [6, 9]], accent2);
      break;
    default:
      add([[5, 8], [6, 8], [5, 9], [6, 9]], accent);
      break;
  }

  return `<svg class="role-sprite" viewBox="0 0 48 48" aria-hidden="true">${px.join("")}</svg>`;
}

function renderRoleBoard(panels = [], activeRoles = new Set(), currentRole = null, roleStates = new Map()) {
  if (!runRoleBoard) return;
  const panelMap = new Map();
  (Array.isArray(panels) ? panels : []).forEach((panel) => {
    const roleId = normalizeRoleId(panel?.role);
    if (roleId) panelMap.set(roleId, panel);
  });

  runRoleBoard.innerHTML = "";
  ROLE_DEFS.forEach((meta) => {
    const panel = panelMap.get(meta.id);
    const roleState = roleStates instanceof Map ? roleStates.get(meta.id) : null;
    const runtimeStatus = String(roleState?.status || "").trim().toLowerCase();
    const isActive = activeRoles instanceof Set ? activeRoles.has(meta.id) : false;
    const isCurrent = normalizeRoleId(currentRole) === meta.id;
    const hasRuntimeState = ["seen", "active", "current", "done", "skipped", "failed"].includes(runtimeStatus);
    const isSeen = Boolean(panel) || isActive || hasRuntimeState;
    const card = document.createElement("article");
    card.className = `role-card${isSeen ? " is-seen" : ""}${isActive ? " is-active" : ""}${isCurrent ? " is-current" : ""}`;
    if (runtimeStatus === "failed") card.classList.add("is-failed");
    if (runtimeStatus === "done") card.classList.add("is-done");
    if (runtimeStatus === "skipped") card.classList.add("is-skipped");
    const kindKey = normalizeRoleKind(panel?.kind, meta.kindKey);
    const kindLabel = ROLE_KIND_LABELS[kindKey] || meta.kindLabel;

    const head = document.createElement("div");
    head.className = "role-card-head";

    const spriteWrap = document.createElement("div");
    spriteWrap.className = "role-sprite-wrap";
    spriteWrap.innerHTML = buildRoleSprite(meta.id);
    head.appendChild(spriteWrap);

    const metaNode = document.createElement("div");
    metaNode.className = "role-meta";

    const nameNode = document.createElement("div");
    nameNode.className = "role-name";
    nameNode.textContent = meta.title;
    metaNode.appendChild(nameNode);

    const kindRow = document.createElement("div");
    kindRow.className = "role-kind-row";

    const kindNode = document.createElement("span");
    kindNode.className = `role-kind ${kindKey}`;
    kindNode.textContent = kindLabel;
    kindRow.appendChild(kindNode);

    const stateNode = document.createElement("span");
    let stateClass = "idle";
    let stateLabel = "待命";
    if (isCurrent || runtimeStatus === "current") {
      stateClass = "current";
      stateLabel = "主工作中";
    } else if (isActive || runtimeStatus === "active") {
      stateClass = "active";
      stateLabel = "协同中";
    } else if (runtimeStatus === "failed") {
      stateClass = "failed";
      stateLabel = "失败";
    } else if (runtimeStatus === "done") {
      stateClass = "done";
      stateLabel = "已完成";
    } else if (runtimeStatus === "skipped") {
      stateClass = "skipped";
      stateLabel = "已跳过";
    } else if (runtimeStatus === "seen" || isSeen) {
      stateClass = "seen";
      stateLabel = "已参与";
    }
    stateNode.className = `role-state ${stateClass}`;
    stateNode.textContent = stateLabel;
    kindRow.appendChild(stateNode);

    metaNode.appendChild(kindRow);
    head.appendChild(metaNode);
    card.appendChild(head);

    const summaryNode = document.createElement("div");
    summaryNode.className = "role-summary";
    const baseSummary = String(meta?.blurb || "").trim();
    const liveSummary = String(panel?.summary || "").trim();
    summaryNode.textContent = isPanelDebugEnabled() ? (liveSummary || baseSummary) : (baseSummary || liveSummary);
    card.appendChild(summaryNode);

    const phaseText = String(roleState?.phase || "").trim();
    const detailText = String(roleState?.detail || "").trim();
    if (phaseText || detailText) {
      const phaseNode = document.createElement("div");
      phaseNode.className = "role-phase";
      phaseNode.textContent = phaseText ? `${phaseText}${detailText ? ` · ${detailText}` : ""}` : detailText;
      card.appendChild(phaseNode);
    }

    const bullets = Array.isArray(panel?.bullets) ? panel.bullets.slice(0, 2) : [];
    if (bullets.length) {
      const list = document.createElement("ul");
      list.className = "role-bullets";
      bullets.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = String(item || "");
        list.appendChild(li);
      });
      card.appendChild(list);
    }

    runRoleBoard.appendChild(card);
  });
}

function applyModePreset(mode, announce = true) {
  const preset = MODE_PRESETS[mode];
  if (!preset) return;

  modelInput.value = preset.model;
  tokenInput.value = String(preset.maxOutputTokens);
  ctxInput.value = String(preset.maxContextTurns);
  styleInput.value = preset.responseStyle;
  toolInput.checked = Boolean(preset.enableTools);

  if (modeStatus) {
    modeStatus.textContent = `当前模式：${preset.label}`;
  }
  if (presetGeneralBtn) {
    presetGeneralBtn.classList.toggle("preset-active", mode === "general");
  }
  if (presetCodingBtn) {
    presetCodingBtn.classList.toggle("preset-active", mode === "coding");
  }
  if (announce) {
    addBubble(
      "system",
      `已切换到${preset.label}：model=${preset.model}，max_tokens=${preset.maxOutputTokens}，context=${preset.maxContextTurns}`
    );
  }
}

function isPanelDebugEnabled() {
  return Boolean(panelDebugInput?.checked);
}

function applyPanelDebugMode(enabled, { persist = true } = {}) {
  const value = Boolean(enabled);
  if (panelDebugInput) {
    panelDebugInput.checked = value;
  }
  document.body.classList.toggle("panel-debug-on", value);
  document.body.classList.toggle("panel-debug-off", !value);
  runtimeDebugSections.forEach((node) => {
    node.hidden = !value;
    if (!value && "open" in node) node.open = false;
  });
  if (persist) {
    try {
      window.localStorage.setItem(PANEL_DEBUG_STORAGE_KEY, value ? "1" : "0");
    } catch {}
  }
  if (!value && state.workspaceView === "debug") {
    setWorkspaceView("chat");
  } else {
    setWorkspaceView(state.workspaceView || getStoredWorkspaceView(), { persist: false });
  }
  renderCommandPalette();
  renderRunSteps(currentRunStepId, currentRunTone === "error");
}

function restorePanelDebugMode() {
  let enabled = false;
  try {
    const raw = String(window.localStorage.getItem(PANEL_DEBUG_STORAGE_KEY) || "").trim().toLowerCase();
    enabled = raw === "1" || raw === "true" || raw === "yes" || raw === "on";
  } catch {}
  applyPanelDebugMode(enabled, { persist: false });
}

function normalizeWorkspaceView(value) {
  const raw = String(value || "").trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(WORKSPACE_VIEWS, raw) ? raw : "chat";
}

function isWorkspaceViewEnabled(view) {
  const normalized = normalizeWorkspaceView(view);
  if (normalized === "debug") return isPanelDebugEnabled();
  return true;
}

function getStoredWorkspaceView() {
  try {
    const raw = window.localStorage.getItem(WORKSPACE_VIEW_STORAGE_KEY);
    if (!raw) return "chat";
    const next = normalizeWorkspaceView(raw);
    return isWorkspaceViewEnabled(next) ? next : "chat";
  } catch {
    return "chat";
  }
}

function persistWorkspaceView(view) {
  try {
    window.localStorage.setItem(WORKSPACE_VIEW_STORAGE_KEY, normalizeWorkspaceView(view));
  } catch {
    // Ignore storage failures.
  }
}

function getStoredChatInfoOpen() {
  return false;
}

function persistChatInfoOpen(open) {
  try {
    window.localStorage.setItem(CHAT_INFO_STORAGE_KEY, open ? "1" : "0");
  } catch {
    // Ignore storage failures.
  }
}

function setChatInfoOpen(open, { persist = true } = {}) {
  const next = Boolean(open);
  state.chatInfoOpen = next;
  const panelVisible = next && state.workspaceView === "chat";

  if (chatWorkspaceView) {
    chatWorkspaceView.classList.toggle("is-info-open", next);
  }
  if (chatInfoPanel) {
    chatInfoPanel.hidden = !panelVisible;
    chatInfoPanel.setAttribute("aria-hidden", panelVisible ? "false" : "true");
  }
  if (chatInfoBackdrop) {
    chatInfoBackdrop.hidden = !panelVisible;
  }
  if (chatInfoToggleBtn) {
    chatInfoToggleBtn.hidden = state.workspaceView !== "chat";
    chatInfoToggleBtn.classList.toggle("is-active", next);
    chatInfoToggleBtn.setAttribute("aria-expanded", next ? "true" : "false");
    chatInfoToggleBtn.textContent = next ? "收起信息" : "侧面信息";
  }

  if (persist) {
    persistChatInfoOpen(next);
  }
}

function setSidebarSessionsOpen(open) {
  const next = Boolean(open);
  state.sidebarSessionsOpen = next;

  if (sidebarSessionShell) {
    sidebarSessionShell.classList.toggle("is-open", next);
  }
  if (sidebarSessionBody) {
    sidebarSessionBody.hidden = !next;
  }
  if (sidebarSessionsToggleBtn) {
    sidebarSessionsToggleBtn.setAttribute("aria-expanded", next ? "true" : "false");
  }
  if (sidebarSessionsToggleIcon) {
    sidebarSessionsToggleIcon.textContent = next ? "-" : "+";
  }
}

function setWorkspaceView(view, { persist = true } = {}) {
  const next = isWorkspaceViewEnabled(view) ? normalizeWorkspaceView(view) : "chat";
  state.workspaceView = next;
  document.body.dataset.workspaceView = next;

  workspaceNavButtons.forEach((button) => {
    const target = normalizeWorkspaceView(button.dataset.workspaceTarget);
    const active = target === next;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });

  workspaceViews.forEach((section) => {
    const active = normalizeWorkspaceView(section.dataset.workspaceView) === next;
    section.hidden = !active;
    section.classList.toggle("is-active", active);
  });

  if (workspaceCurrentLabel) {
    workspaceCurrentLabel.textContent = WORKSPACE_VIEWS[next]?.label || "聊天";
  }

  if (chatInfoToggleBtn) {
    chatInfoToggleBtn.hidden = next !== "chat";
  }
  if (chatInfoBackdrop) {
    chatInfoBackdrop.hidden = next !== "chat" || !state.chatInfoOpen;
  }
  if (chatInfoPanel) {
    chatInfoPanel.hidden = next !== "chat" || !state.chatInfoOpen;
  }
  if (next === "chat") {
    setChatInfoOpen(state.chatInfoOpen, { persist: false });
  } else {
    setChatInfoOpen(false, { persist: false });
  }

  if (persist) {
    persistWorkspaceView(next);
  }
}

function hasAnswerBundleContent(bundle) {
  if (!bundle || typeof bundle !== "object") return false;
  return Boolean(
    String(bundle.summary || "").trim() ||
      (Array.isArray(bundle.claims) && bundle.claims.length) ||
      (Array.isArray(bundle.citations) && bundle.citations.length) ||
      (Array.isArray(bundle.warnings) && bundle.warnings.length)
  );
}

function normalizeCitationIds(rawIds) {
  const seen = new Set();
  const out = [];
  (Array.isArray(rawIds) ? rawIds : []).forEach((item) => {
    const id = String(item || "").trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    out.push(id);
  });
  return out;
}

function normalizeMatchText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\u3400-\u9fff\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function collectLatinTokens(text) {
  const matches = normalizeMatchText(text).match(/[a-z0-9_]{2,}/g) || [];
  return Array.from(new Set(matches));
}

function collectCjkBigrams(text) {
  const cjkChars = (String(text || "").match(/[\u3400-\u9fff]/g) || []).join("");
  if (cjkChars.length < 2) return [];
  const out = [];
  for (let i = 0; i < cjkChars.length - 1; i += 1) {
    out.push(cjkChars.slice(i, i + 2));
  }
  return Array.from(new Set(out));
}

function overlapRatio(sourceTokens, targetTokenSet) {
  const tokens = Array.isArray(sourceTokens) ? sourceTokens : [];
  if (!tokens.length) return 0;
  let hit = 0;
  tokens.forEach((token) => {
    if (targetTokenSet.has(token)) hit += 1;
  });
  return hit / tokens.length;
}

function scoreClaimToNode(claimText, nodeText) {
  const claimJoined = normalizeMatchText(claimText).replace(/\s+/g, "");
  const nodeJoined = normalizeMatchText(nodeText).replace(/\s+/g, "");
  if (!claimJoined || !nodeJoined) return { score: 0, matched: false };

  let containmentScore = 0;
  if (claimJoined.length >= 12 && nodeJoined.includes(claimJoined)) {
    containmentScore = 1;
  } else if (nodeJoined.length >= 12 && claimJoined.includes(nodeJoined)) {
    containmentScore = 0.82;
  }

  const claimLatin = collectLatinTokens(claimText);
  const claimCjk = collectCjkBigrams(claimText);
  const nodeLatinSet = new Set(collectLatinTokens(nodeText));
  const nodeCjkSet = new Set(collectCjkBigrams(nodeText));
  const latinScore = overlapRatio(claimLatin, nodeLatinSet);
  const cjkScore = overlapRatio(claimCjk, nodeCjkSet);

  const lexicalScore =
    claimLatin.length && claimCjk.length
      ? latinScore * 0.55 + cjkScore * 0.45
      : claimLatin.length
      ? latinScore
      : cjkScore;
  const score = Math.max(containmentScore, lexicalScore);
  const matched =
    containmentScore >= 0.82 ||
    latinScore >= 0.5 ||
    cjkScore >= 0.45 ||
    (score >= 0.42 && (claimLatin.length >= 2 || claimCjk.length >= 3));
  return { score, matched };
}

function annotateAssistantInlineCitations(contentNode, bundle) {
  if (!contentNode || !bundle || typeof bundle !== "object") return;
  const claims = Array.isArray(bundle.claims) ? bundle.claims : [];
  if (!claims.length) return;

  let targetNodes = Array.from(
    contentNode.querySelectorAll("p, li, blockquote, h1, h2, h3, h4, h5, h6")
  ).filter((node) => {
    const text = String(node?.textContent || "").trim();
    return text.length >= 8;
  });
  if (!targetNodes.length) {
    const fallbackText = String(contentNode.textContent || "").trim();
    if (fallbackText.length >= 12) targetNodes = [contentNode];
  }
  if (!targetNodes.length) return;

  const nodeCitations = new Map();
  claims.forEach((claim) => {
    const ids = normalizeCitationIds(claim?.citation_ids);
    const statement = String(claim?.statement || "").trim();
    if (!ids.length || !statement) return;

    let bestNode = null;
    let bestScore = 0;
    targetNodes.forEach((node) => {
      const text = String(node?.textContent || "").trim();
      if (!text) return;
      const match = scoreClaimToNode(statement, text);
      if (!match.matched) return;
      if (match.score > bestScore) {
        bestScore = match.score;
        bestNode = node;
      }
    });

    if (!bestNode || bestScore < 0.42) return;
    if (!nodeCitations.has(bestNode)) nodeCitations.set(bestNode, new Set());
    const holder = nodeCitations.get(bestNode);
    ids.forEach((id) => holder.add(id));
  });

  nodeCitations.forEach((idSet, node) => {
    const merged = Array.from(idSet).filter(Boolean);
    if (!merged.length) return;
    const oldMarker = node.querySelector(".inline-citation-tag[data-generated='1']");
    if (oldMarker) oldMarker.remove();

    const marker = document.createElement("span");
    marker.className = "inline-citation-tag";
    marker.setAttribute("data-generated", "1");
    marker.textContent = ` [${merged.join(", ")}]`;
    node.appendChild(marker);
  });
}

function partitionAnswerCitations(citations) {
  const evidence = [];
  const candidates = [];
  (Array.isArray(citations) ? citations : []).forEach((citation) => {
    const kind = String(citation?.kind || "").trim().toLowerCase();
    if (kind === "candidate") {
      candidates.push(citation);
    } else {
      evidence.push(citation);
    }
  });
  return { evidence, candidates };
}

function appendCitationSection(wrap, titleText, citations, noteText = "") {
  if (!Array.isArray(citations) || !citations.length) return;
  const section = document.createElement("div");
  section.className = "answer-bundle-section";
  const title = document.createElement("div");
  title.className = "answer-bundle-title";
  title.textContent = titleText;
  section.appendChild(title);

  if (noteText) {
    const note = document.createElement("div");
    note.className = "answer-bundle-meta";
    note.textContent = noteText;
    section.appendChild(note);
  }

  citations.slice(0, 8).forEach((citation) => {
    const item = document.createElement("div");
    item.className = "answer-bundle-item";
    const heading = document.createElement("div");
    heading.className = "answer-bundle-statement";
    const label = String(citation?.label || citation?.title || citation?.url || citation?.path || citation?.id || "source").trim();
    heading.textContent = `${String(citation?.id || "").trim() || "-"} · ${label}`;
    item.appendChild(heading);

    const meta = [];
    if (citation?.tool) meta.push(`tool: ${citation.tool}`);
    if (citation?.domain) meta.push(`domain: ${citation.domain}`);
    if (citation?.locator) meta.push(`locator: ${citation.locator}`);
    if (citation?.published_at) meta.push(`published: ${citation.published_at}`);
    if (meta.length) {
      const metaNode = document.createElement("div");
      metaNode.className = "answer-bundle-meta";
      metaNode.textContent = meta.join(" | ");
      item.appendChild(metaNode);
    }

    const excerpt = String(citation?.excerpt || "").trim();
    if (excerpt) {
      const excerptNode = document.createElement("div");
      excerptNode.className = "answer-bundle-excerpt";
      excerptNode.textContent = excerpt;
      item.appendChild(excerptNode);
    }

    const link = String(citation?.url || "").trim();
    if (link) {
      const linkNode = document.createElement("a");
      linkNode.className = "answer-bundle-link";
      linkNode.href = link;
      linkNode.target = "_blank";
      linkNode.rel = "noreferrer noopener";
      linkNode.textContent = link;
      item.appendChild(linkNode);
    } else if (citation?.path) {
      const pathNode = document.createElement("div");
      pathNode.className = "answer-bundle-meta";
      pathNode.textContent = `path: ${citation.path}`;
      item.appendChild(pathNode);
    }

    const warning = String(citation?.warning || "").trim();
    if (warning) {
      const warningNode = document.createElement("div");
      warningNode.className = "answer-bundle-warning";
      warningNode.textContent = `warning（风险提示）: ${warning}`;
      item.appendChild(warningNode);
    }
    section.appendChild(item);
  });

  wrap.appendChild(section);
}

function buildAnswerBundleNode(bundle, options = {}) {
  const showSummary = Boolean(options?.showSummary);
  const showAssertions = Boolean(options?.showAssertions);
  const wrap = document.createElement("div");
  wrap.className = "answer-bundle";

  const summary = String(bundle?.summary || "").trim();
  if (showSummary && summary) {
    const summaryNode = document.createElement("div");
    summaryNode.className = "answer-bundle-summary";
    summaryNode.textContent = summary;
    wrap.appendChild(summaryNode);
  }

  const claims = Array.isArray(bundle?.claims) ? bundle.claims : [];
  if (showAssertions && claims.length) {
    const section = document.createElement("div");
    section.className = "answer-bundle-section";
    const title = document.createElement("div");
    title.className = "answer-bundle-title";
    title.textContent = "Assertions（关键结论）";
    section.appendChild(title);
    claims.slice(0, 5).forEach((claim, idx) => {
      const item = document.createElement("div");
      item.className = "answer-bundle-item";
      const statement = document.createElement("div");
      statement.className = "answer-bundle-statement";
      statement.textContent = `${idx + 1}. ${String(claim?.statement || "").trim()}`;
      item.appendChild(statement);

      const meta = [];
      const citationIds = Array.isArray(claim?.citation_ids) ? claim.citation_ids.filter(Boolean) : [];
      if (citationIds.length) meta.push(`sources: ${citationIds.join(", ")}`);
      if (claim?.status) meta.push(`status: ${claim.status}`);
      if (claim?.confidence) meta.push(`confidence: ${claim.confidence}`);
      if (meta.length) {
        const metaNode = document.createElement("div");
        metaNode.className = "answer-bundle-meta";
        metaNode.textContent = meta.join(" | ");
        item.appendChild(metaNode);
      }
      section.appendChild(item);
    });
    wrap.appendChild(section);
  }

  const citations = Array.isArray(bundle?.citations) ? bundle.citations : [];
  const { evidence, candidates } = partitionAnswerCitations(citations);
  appendCitationSection(wrap, "Citations（证据来源）", evidence);
  appendCitationSection(wrap, "Search Candidates（候选来源）", candidates, "这些链接仅是搜索候选，尚未抓取正文。");

  const warnings = Array.isArray(bundle?.warnings) ? bundle.warnings : [];
  if (warnings.length) {
    const section = document.createElement("div");
    section.className = "answer-bundle-section";
    const title = document.createElement("div");
    title.className = "answer-bundle-title";
    title.textContent = "Warnings（风险提示）";
    section.appendChild(title);
    warnings.slice(0, 5).forEach((warning) => {
      const item = document.createElement("div");
      item.className = "answer-bundle-warning";
      item.textContent = String(warning || "");
      section.appendChild(item);
    });
    wrap.appendChild(section);
  }

  return wrap.childElementCount ? wrap : null;
}

function addBubble(role, text, answerBundle = null) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  const value = typeof text === "string" ? text : String(text ?? "");
  if (role === "assistant") {
    const content = document.createElement("div");
    content.innerHTML = renderAssistantMarkdown(value);
    annotateAssistantInlineCitations(content, answerBundle);
    bubble.appendChild(content);
    if (hasAnswerBundleContent(answerBundle)) {
      const bundleNode = buildAnswerBundleNode(answerBundle, { showSummary: false, showAssertions: true });
      if (bundleNode) {
        bubble.appendChild(bundleNode);
      }
    }
  } else {
    bubble.textContent = value;
  }

  chatList.appendChild(bubble);
  chatList.scrollTop = chatList.scrollHeight;
}

function escapeHtml(raw) {
  return String(raw)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeTableLikeTextToMarkdown(rawText) {
  const source = String(rawText ?? "");
  if (!source.trim()) return source;

  const codeBlocks = [];
  const tokenized = source.replace(/```[\s\S]*?```/g, (block) => {
    const token = `__MD_CODE_PRESERVE_${codeBlocks.length}__`;
    codeBlocks.push({ token, block: String(block) });
    return token;
  });

  const isMdTableSeparator = (line) =>
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(String(line || ""));

  const lines = tokenized.replace(/\r\n/g, "\n").split("\n");
  const codeTokenSet = new Set(codeBlocks.map((item) => item.token));
  const output = [];

  const shouldSkipTableNormalization = (blockLines) => {
    const codeHints = (
      /\b(function|class|def|import|const|let|var|return|public|private)\b/i
    );
    return blockLines.some((line) => {
      const t = String(line || "").trim();
      if (!t) return false;
      if (/^[-*+]\s+/.test(t) || /^\d+\.\s+/.test(t) || /^>\s*/.test(t) || /^#{1,6}\s+/.test(t)) return true;
      if (/[{};]/.test(t)) return true;
      return codeHints.test(t);
    });
  };

  const splitColumns = (line) => {
    const text = String(line || "").trim();
    if (!text) return null;
    if (text.includes("\t")) {
      const parts = text.split(/\t+/).map((item) => item.trim()).filter(Boolean);
      if (parts.length >= 2) return { mode: "tab", parts };
    }
    if (!/\s{2,}/.test(text)) return null;
    const parts = text.split(/\s{2,}/).map((item) => item.trim()).filter(Boolean);
    if (parts.length >= 2) return { mode: "space", parts };
    return null;
  };

  const normalizeBlockToTable = (blockLines) => {
    if (!Array.isArray(blockLines) || blockLines.length < 2) return null;
    if (shouldSkipTableNormalization(blockLines)) return null;
    for (let idx = 0; idx < blockLines.length - 1; idx += 1) {
      const cur = String(blockLines[idx] || "").trim();
      const next = String(blockLines[idx + 1] || "").trim();
      if (cur.includes("|") && isMdTableSeparator(next)) {
        return null;
      }
    }

    const rows = [];
    const modes = [];
    for (const line of blockLines) {
      const parsed = splitColumns(line);
      if (!parsed) return null;
      rows.push(parsed.parts);
      modes.push(parsed.mode);
    }
    const colCount = rows[0]?.length || 0;
    if (colCount < 2 || colCount > 12) return null;
    if (rows.some((row) => row.length !== colCount)) return null;

    const hasTabRow = modes.includes("tab");
    if (!hasTabRow && rows.length < 3) return null;

    const esc = (cell) => String(cell ?? "").replace(/\|/g, "\\|");
    const out = [];
    out.push(`| ${rows[0].map(esc).join(" | ")} |`);
    out.push(`| ${rows[0].map(() => "---").join(" | ")} |`);
    rows.slice(1).forEach((row) => out.push(`| ${row.map(esc).join(" | ")} |`));
    return out;
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = String(line || "").trim();
    if (!trimmed) {
      output.push(line);
      i += 1;
      continue;
    }
    if (codeTokenSet.has(trimmed)) {
      output.push(line);
      i += 1;
      continue;
    }

    let j = i;
    while (j < lines.length) {
      const t = String(lines[j] || "").trim();
      if (!t || codeTokenSet.has(t)) break;
      j += 1;
    }
    const block = lines.slice(i, j);
    const normalized = normalizeBlockToTable(block);
    if (normalized) {
      output.push(...normalized);
    } else {
      output.push(...block);
    }
    i = j;
  }

  let result = output.join("\n");
  codeBlocks.forEach((item) => {
    result = result.replace(item.token, item.block);
  });
  return result;
}

function renderAssistantMarkdown(text) {
  const source = normalizeTableLikeTextToMarkdown(text);
  const markedApi = window.marked;
  const purifyApi = window.DOMPurify;

  if (markedApi && purifyApi && typeof markedApi.parse === "function") {
    try {
      const html = markedApi.parse(source, {
        gfm: true,
        breaks: true,
      });
      const sanitized = purifyApi.sanitize(html, { USE_PROFILES: { html: true } });
      const sourceCompactLen = source.replace(/\s+/g, "").length;
      if (sourceCompactLen >= 24) {
        const probe = document.createElement("div");
        probe.innerHTML = sanitized;
        const renderedCompactLen = String(probe.textContent || "").replace(/\s+/g, "").length;
        if (!renderedCompactLen || renderedCompactLen < Math.max(8, Math.floor(sourceCompactLen * 0.45))) {
          return renderMarkdownLite(source);
        }
      }
      return sanitized;
    } catch {}
  }

  return renderMarkdownLite(source);
}

function renderMarkdownLite(text) {
  const source = String(text ?? "");
  const codeBlocks = [];
  const withCodeTokens = source.replace(/```([\s\S]*?)```/g, (_, code) => {
    const token = `__MD_CODE_BLOCK_${codeBlocks.length}__`;
    const codeHtml = `<pre><code>${escapeHtml(String(code).replace(/^\n+|\n+$/g, ""))}</code></pre>`;
    codeBlocks.push({ token, html: codeHtml });
    return token;
  });

  const renderInlineMarkdownLite = (raw) => {
    let html = escapeHtml(String(raw ?? ""));
    html = html.replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    return html;
  };

  const lines = withCodeTokens.replace(/\r\n/g, "\n").split("\n");
  const chunks = [];
  let i = 0;
  const codeTokenSet = new Set(codeBlocks.map((item) => item.token));
  const isCodeTokenLine = (line) => codeTokenSet.has(String(line || "").trim());
  const parseTableRow = (line) => {
    const raw = String(line || "").trim().replace(/^\|/, "").replace(/\|$/, "");
    return raw.split("|").map((cell) => cell.trim());
  };
  const isTableSeparator = (line) =>
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(String(line || ""));

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = String(line || "").trim();
    if (!trimmed) {
      i += 1;
      continue;
    }

    if (isCodeTokenLine(trimmed)) {
      chunks.push(trimmed);
      i += 1;
      continue;
    }

    if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headerCells = parseTableRow(lines[i]);
      i += 2;
      const bodyRows = [];
      while (i < lines.length) {
        const rowLine = String(lines[i] || "").trim();
        if (!rowLine || !rowLine.includes("|") || isCodeTokenLine(rowLine)) break;
        bodyRows.push(parseTableRow(rowLine));
        i += 1;
      }
      const thead = `<thead><tr>${headerCells
        .map((cell) => `<th>${renderInlineMarkdownLite(cell)}</th>`)
        .join("")}</tr></thead>`;
      const tbody = bodyRows.length
        ? `<tbody>${bodyRows
            .map((row) => {
              const normalized = row.slice(0, headerCells.length);
              while (normalized.length < headerCells.length) normalized.push("");
              return `<tr>${normalized
                .map((cell) => `<td>${renderInlineMarkdownLite(cell)}</td>`)
                .join("")}</tr>`;
            })
            .join("")}</tbody>`
        : "";
      chunks.push(`<table>${thead}${tbody}</table>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      const items = [];
      while (i < lines.length) {
        const row = String(lines[i] || "").trim();
        const matched = row.match(/^\d+\.\s+(.+)$/);
        if (!matched) break;
        items.push(matched[1]);
        i += 1;
      }
      chunks.push(`<ol>${items.map((item) => `<li>${renderInlineMarkdownLite(item)}</li>`).join("")}</ol>`);
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      const items = [];
      while (i < lines.length) {
        const row = String(lines[i] || "").trim();
        const matched = row.match(/^[-*+]\s+(.+)$/);
        if (!matched) break;
        items.push(matched[1]);
        i += 1;
      }
      chunks.push(`<ul>${items.map((item) => `<li>${renderInlineMarkdownLite(item)}</li>`).join("")}</ul>`);
      continue;
    }

    const paraLines = [];
    while (i < lines.length) {
      const row = String(lines[i] || "");
      const rowTrimmed = row.trim();
      if (!rowTrimmed) break;
      if (isCodeTokenLine(rowTrimmed)) break;
      if (rowTrimmed.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) break;
      if (/^\d+\.\s+/.test(rowTrimmed)) break;
      if (/^[-*+]\s+/.test(rowTrimmed)) break;
      paraLines.push(rowTrimmed);
      i += 1;
    }
    if (paraLines.length) {
      const paraHtml = renderInlineMarkdownLite(paraLines.join("\n")).replace(/\n/g, "<br>");
      chunks.push(`<p>${paraHtml}</p>`);
      continue;
    }

    i += 1;
  }

  let html = chunks.join("");
  if (!html) {
    html = renderInlineMarkdownLite(withCodeTokens).replace(/\n/g, "<br>");
  }

  codeBlocks.forEach((item) => {
    html = html.replace(item.token, item.html);
  });
  return html;
}

function formatNumberedLines(title, items) {
  if (!Array.isArray(items) || !items.length) return null;
  const lines = items.map((item, idx) => `${idx + 1}. ${item}`);
  return `${title}\n${lines.join("\n")}`;
}

function renderBackendPolicy(health = {}) {
  if (!backendPolicyView) return;

  const allowAnyPath = Boolean(health.allow_any_path);
  const platformName = String(health.platform_name || "Unknown").trim();
  const workspaceRoot = String(health.workspace_root || "").trim() || "(unknown)";
  const allowedRoots = Array.isArray(health.allowed_roots) ? health.allowed_roots : [];
  const siblingRoot = String(health.workspace_sibling_root || "").trim();
  const allowSiblingAccess = Boolean(health.allow_workspace_sibling_access) && Boolean(siblingRoot);
  const defaultExtraRoots = Array.isArray(health.default_extra_allowed_roots) ? health.default_extra_allowed_roots : [];
  const source = String(health.extra_allowed_roots_source || "platform_default").trim().toLowerCase();
  const sourceLabel = source === "env_override" ? "环境变量覆盖" : "平台默认";

  const lines = [
    `平台: ${platformName}`,
    `路径策略: ${allowAnyPath ? "不限制（ALLOW_ANY_PATH）" : "只允许已配置根目录"}`,
    `同级工程访问: ${allowSiblingAccess ? `允许（根=${siblingRoot}）` : "关闭"}`,
    `额外根目录来源: ${sourceLabel}`,
    `工作区根目录: ${workspaceRoot}`,
    "当前允许读取根目录:",
  ];

  if (allowedRoots.length) {
    allowedRoots.forEach((item, idx) => lines.push(`${idx + 1}. ${String(item || "")}`));
  } else {
    lines.push("(空)");
  }

  lines.push("");
  lines.push("平台默认额外根目录:");
  if (defaultExtraRoots.length) {
    defaultExtraRoots.forEach((item, idx) => lines.push(`${idx + 1}. ${String(item || "")}`));
  } else {
    lines.push("(空)");
  }

  backendPolicyView.textContent = lines.join("\n");
}

function renderAppVersion(health = {}) {
  if (!appVersionView) return;
  const buildVersion = String(health.build_version || "").trim();
  const appVersion = String(health.app_version || "").trim();
  appVersionView.textContent = buildVersion || (appVersion ? `v${appVersion}` : "版本未知");
  appVersionView.title = buildVersion || appVersion || "版本未知";
}

function renderProductProfile(health = {}) {
  const profile = String(health.product_profile || "multi_agent_robot").trim() || "multi_agent_robot";
  const productTitle = String(health.product_title || "Multi_Agent_Robot").trim() || "Multi_Agent_Robot";
  const productTagline = String(health.product_tagline || "").trim();
  const kernelTitle = String(health.product_kernel_title || "主核 / 模块舱 / 影子实验台").trim();
  const kernelSubtitle = String(health.product_kernel_subtitle || "").trim();
  const roleTitleText = String(health.product_role_title || "Role 视图").trim();
  const roleLegendText = String(health.product_role_legend || "").trim();
  const buildVersion = String(health.build_version || "").trim();

  document.body.dataset.productProfile = profile;
  document.title = buildVersion ? `${productTitle} · ${buildVersion}` : productTitle || "Multi_Agent_Robot";

  if (productTitleView) productTitleView.textContent = productTitle;
  if (productHintView) {
    productHintView.textContent = productTagline || "共享 runtime-core，按产品画像切换不同入口。";
  }
  if (kernelConsoleTitle) kernelConsoleTitle.textContent = kernelTitle || "主核 / 模块舱 / 影子实验台";
  if (kernelConsoleSubtitle) kernelConsoleSubtitle.textContent = kernelSubtitle || "";
  if (roleBoardTitle) roleBoardTitle.textContent = roleTitleText || "像素小人 / 角色执行视图";
  if (roleBoardLegend) roleBoardLegend.textContent = roleLegendText || "";
  applyRuntimeViewMode(health);
}

function getStoredRuntimeViewMode() {
  try {
    const raw = String(window.localStorage.getItem(RUNTIME_VIEW_STORAGE_KEY) || "").trim().toLowerCase();
    if (raw === "modules" || raw === "roles" || raw === "split") return raw;
  } catch {
    return null;
  }
  return null;
}

function defaultRuntimeViewMode(health = {}) {
  const profile = String(health.product_profile || "multi_agent_robot").trim().toLowerCase();
  if (profile === "role_agent_lab") return "roles";
  return "modules";
}

function updateRuntimeViewButtons(mode) {
  const isModules = mode === "modules";
  const isRoles = mode === "roles";
  const isSplit = mode === "split";
  if (runtimeViewModulesBtn) runtimeViewModulesBtn.classList.toggle("preset-active", isModules);
  if (runtimeViewRolesBtn) runtimeViewRolesBtn.classList.toggle("preset-active", isRoles);
  if (runtimeViewSplitBtn) runtimeViewSplitBtn.classList.toggle("preset-active", isSplit);
  if (runtimeViewStatus) {
    const label = isRoles ? "像素小人" : isSplit ? "双视图" : "模块";
    runtimeViewStatus.textContent = `当前视图：${label}`;
  }
}

function applyRuntimeViewMode(health = {}, forcedMode = null) {
  const mode = forcedMode || state.runtimeViewMode || getStoredRuntimeViewMode() || defaultRuntimeViewMode(health);
  const showKernelConsole = mode === "modules" || mode === "split";
  const showRoleBoard = mode === "roles" || mode === "split";
  if (kernelConsoleSection) {
    kernelConsoleSection.hidden = !showKernelConsole;
    kernelConsoleSection.style.display = showKernelConsole ? "" : "none";
  }
  if (roleBoardSection) {
    roleBoardSection.hidden = !showRoleBoard;
    roleBoardSection.style.display = showRoleBoard ? "" : "none";
  }
  updateRuntimeViewButtons(mode);
}

function setRuntimeViewMode(mode) {
  if (!["modules", "roles", "split"].includes(mode)) return;
  state.runtimeViewMode = mode;
  try {
    window.localStorage.setItem(RUNTIME_VIEW_STORAGE_KEY, mode);
  } catch {
    // Ignore storage failures.
  }
  applyRuntimeViewMode(state.lastHealth || {}, mode);
}

function normalizePanelLayout(raw = {}) {
  const leftWidth = Number(raw?.leftWidth || LAYOUT_DEFAULTS.leftWidth);
  const rightWidth = Number(raw?.rightWidth || LAYOUT_DEFAULTS.rightWidth);
  return {
    leftWidth: Math.max(220, Math.min(420, Number.isFinite(leftWidth) ? leftWidth : LAYOUT_DEFAULTS.leftWidth)),
    rightWidth: Math.max(260, Math.min(420, Number.isFinite(rightWidth) ? rightWidth : LAYOUT_DEFAULTS.rightWidth)),
    leftCollapsed: Boolean(raw?.leftCollapsed),
    rightCollapsed: Boolean(raw?.rightCollapsed),
  };
}

function getStoredPanelLayout() {
  try {
    const raw = window.localStorage.getItem(PANEL_LAYOUT_STORAGE_KEY);
    if (!raw) return { ...LAYOUT_DEFAULTS };
    return normalizePanelLayout(JSON.parse(raw));
  } catch {
    return { ...LAYOUT_DEFAULTS };
  }
}

function persistPanelLayout() {
  try {
    window.localStorage.setItem(PANEL_LAYOUT_STORAGE_KEY, JSON.stringify(normalizePanelLayout(state.panelLayout)));
  } catch {
    // Ignore storage failures.
  }
}

function applyPanelLayout() {
  if (!appShell) return;
  const layout = normalizePanelLayout(state.panelLayout || LAYOUT_DEFAULTS);
  state.panelLayout = layout;
  appShell.style.setProperty("--left-rail-width", layout.leftCollapsed ? "0px" : `${layout.leftWidth}px`);
  appShell.style.setProperty("--right-rail-width", layout.rightCollapsed ? "0px" : `${layout.rightWidth}px`);
  appShell.classList.toggle("left-collapsed", layout.leftCollapsed);
  appShell.classList.toggle("right-collapsed", layout.rightCollapsed);
}

function setRailCollapsed(side, collapsed) {
  if (!state.panelLayout) state.panelLayout = { ...LAYOUT_DEFAULTS };
  if (side === "left") {
    state.panelLayout.leftCollapsed = Boolean(collapsed);
  } else if (side === "right") {
    state.panelLayout.rightCollapsed = Boolean(collapsed);
  }
  applyPanelLayout();
  persistPanelLayout();
}

function setRailWidth(side, width) {
  if (!state.panelLayout) state.panelLayout = { ...LAYOUT_DEFAULTS };
  if (side === "left") {
    state.panelLayout.leftWidth = Math.max(220, Math.min(420, Number(width || LAYOUT_DEFAULTS.leftWidth)));
    state.panelLayout.leftCollapsed = false;
  } else if (side === "right") {
    state.panelLayout.rightWidth = Math.max(260, Math.min(420, Number(width || LAYOUT_DEFAULTS.rightWidth)));
    state.panelLayout.rightCollapsed = false;
  }
  applyPanelLayout();
  persistPanelLayout();
}

function setupRailResizer(handle, side) {
  if (!handle || !appShell) return;

  const adjustByKey = (delta) => {
    const layout = normalizePanelLayout(state.panelLayout || LAYOUT_DEFAULTS);
    const next = side === "left" ? layout.leftWidth + delta : layout.rightWidth - delta;
    setRailWidth(side, next);
  };

  handle.addEventListener("dblclick", () => {
    const layout = normalizePanelLayout(state.panelLayout || LAYOUT_DEFAULTS);
    const collapsed = side === "left" ? layout.leftCollapsed : layout.rightCollapsed;
    setRailCollapsed(side, !collapsed);
  });

  handle.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      adjustByKey(-24);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      adjustByKey(24);
    } else if (event.key === "Enter") {
      event.preventDefault();
      handle.dispatchEvent(new MouseEvent("dblclick"));
    }
  });

  handle.addEventListener("pointerdown", (event) => {
    if (window.innerWidth <= 1180) return;
    event.preventDefault();
    const layout = normalizePanelLayout(state.panelLayout || LAYOUT_DEFAULTS);
    if (side === "left" && layout.leftCollapsed) setRailCollapsed("left", false);
    if (side === "right" && layout.rightCollapsed) setRailCollapsed("right", false);
    const latestLayout = normalizePanelLayout(state.panelLayout || LAYOUT_DEFAULTS);
    const startX = event.clientX;
    const startWidth = side === "left" ? latestLayout.leftWidth : latestLayout.rightWidth;
    handle.classList.add("is-dragging");
    handle.setPointerCapture?.(event.pointerId);

    const onMove = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      const nextWidth = side === "left" ? startWidth + delta : startWidth - delta;
      setRailWidth(side, nextWidth);
    };

    const finish = () => {
      handle.classList.remove("is-dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", finish, { once: true });
    window.addEventListener("pointercancel", finish, { once: true });
  });
}

function loadRecentCommands() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(RECENT_COMMANDS_STORAGE_KEY) || "[]");
    state.recentCommands = Array.isArray(raw) ? raw.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 8) : [];
  } catch {
    state.recentCommands = [];
  }
}

function rememberCommandUse(commandId) {
  const id = String(commandId || "").trim();
  if (!id) return;
  state.recentCommands = [id, ...state.recentCommands.filter((item) => item !== id)].slice(0, 8);
  try {
    window.localStorage.setItem(RECENT_COMMANDS_STORAGE_KEY, JSON.stringify(state.recentCommands));
  } catch {
    // Ignore storage failures.
  }
}

const MODULE_LABELS = {
  router: { title: "Router", desc: "全局语义分诊与最小链路选择。" },
  policy: { title: "Policy", desc: "执行策略与 gate（闸门）配置。" },
  attachment_context: { title: "Attachment", desc: "附件上下文、自动关联与 scoped route state。" },
  finalizer: { title: "Finalizer", desc: "最终输出整理、表格/邮件/证据包收口。" },
  tool_registry: { title: "Tools", desc: "工具注册表与执行能力描述。" },
  "provider:api_key": { title: "Provider / API", desc: "公司 API 或标准 OpenAI API 通道。" },
  "provider:codex_auth": { title: "Provider / Codex", desc: "本地 Codex auth 调试通道。" },
};

function moduleLabel(moduleId) {
  const value = String(moduleId || "").trim();
  if (value === "research_module") return "Research Module";
  if (value === "office_module") return "Office Module";
  if (value === "coding_module") return "Coding Module";
  if (value === "adaptation_module") return "Adaptation Module";
  return value || "等待请求";
}

function summarizeGateLine(item) {
  const label = String(item?.label || "Gate");
  const passed = Number(item?.passed || 0);
  const total = Number(item?.total || 0);
  const status = String(item?.status || "missing");
  const prefix = status === "pass" ? "通过" : status === "fail" ? "失败" : "缺失";
  return `${label}: ${prefix} ${passed}/${total}`;
}

function createChip(text, className = "hero-chip") {
  const node = document.createElement("span");
  node.className = className;
  node.textContent = String(text || "");
  return node;
}

function executionLogTimestamp() {
  return new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function classifyExecutionText(text, fallback = "system") {
  const value = String(text || "").toLowerCase();
  if (!value) return fallback;
  if (
    value.includes("swarm") ||
    value.includes("branch") ||
    value.includes("merge") ||
    value.includes("join") ||
    value.includes("serial_replay") ||
    value.includes("conflict")
  ) {
    return "swarm";
  }
  if (
    value.includes("route") ||
    value.includes("router") ||
    value.includes("module") ||
    value.includes("policy") ||
    value.includes("selection")
  ) {
    return "routing";
  }
  if (
    value.includes("plan") ||
    value.includes("planner") ||
    value.includes("prepare") ||
    value.includes("payload") ||
    value.includes("coordinator")
  ) {
    return "planning";
  }
  if (
    value.includes("review") ||
    value.includes("revision") ||
    value.includes("final") ||
    value.includes("answer bundle") ||
    value.includes("structurer")
  ) {
    return "review";
  }
  if (
    value.includes("tool") ||
    value.includes("search") ||
    value.includes("fetch") ||
    value.includes("upload") ||
    value.includes("sandbox")
  ) {
    return "tool";
  }
  return fallback;
}

function clearExecutionLog() {
  state.executionLogEntries = [];
  state.executionLogFilter = "all";
  state.executionLogAutoScroll = true;
  renderExecutionLog();
}

function pushExecutionLogEntry(entry = {}) {
  const item = {
    time: executionLogTimestamp(),
    category: String(entry.category || "system").trim().toLowerCase() || "system",
    title: String(entry.title || "System").trim() || "System",
    detail: String(entry.detail || "").trim(),
    tags: (Array.isArray(entry.tags) ? entry.tags : []).map((tag) => String(tag || "").trim()).filter(Boolean),
  };
  state.executionLogEntries.push(item);
  if (state.executionLogEntries.length > 240) {
    state.executionLogEntries = state.executionLogEntries.slice(-240);
  }
  renderExecutionLog();
}

function ensureExecutionLogFilters() {
  if (!executionLogFilters || executionLogFilters.childElementCount) return;
  executionLogFilters.innerHTML = "";
  LOG_FILTERS.forEach((filter) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "log-filter-chip";
    button.textContent = filter.label;
    button.dataset.filterId = filter.id;
    button.addEventListener("click", () => {
      state.executionLogFilter = filter.id;
      renderExecutionLog();
    });
    executionLogFilters.appendChild(button);
  });
}

function renderExecutionLog() {
  ensureExecutionLogFilters();
  if (!executionLogView || !executionLogMeta) return;
  const filterId = String(state.executionLogFilter || "all");
  const entries = Array.isArray(state.executionLogEntries) ? state.executionLogEntries : [];
  const filtered = filterId === "all" ? entries : entries.filter((item) => item.category === filterId);

  if (executionLogFilters) {
    executionLogFilters.querySelectorAll(".log-filter-chip").forEach((node) => {
      node.classList.toggle("is-active", node.dataset.filterId === filterId);
    });
  }

  if (executionLogAutoBtn) {
    executionLogAutoBtn.textContent = state.executionLogAutoScroll ? "自动滚动中" : "恢复自动滚动";
  }
  executionLogMeta.textContent =
    filtered.length > 0
      ? `当前显示 ${filtered.length} 条 ${filterId === "all" ? "事件" : `${filterId} 事件`}。`
      : "等待执行事件。";

  const shouldStickToBottom =
    state.executionLogAutoScroll &&
    executionLogView.scrollHeight - executionLogView.scrollTop - executionLogView.clientHeight < 48;

  executionLogView.innerHTML = "";
  if (!filtered.length) {
    executionLogView.textContent = filterId === "all" ? "当前没有执行日志。" : "当前筛选条件下没有执行日志。";
    return;
  }

  filtered.forEach((item) => {
    const node = document.createElement("article");
    node.className = `log-entry category-${item.category}`;
    node.innerHTML = `
      <div class="log-entry-head">
        <div class="log-entry-title">${escapeHtml(item.title)}</div>
        <div class="log-entry-time">${escapeHtml(item.time)}</div>
      </div>
      <div class="log-entry-detail">${escapeHtml(item.detail || "无附加细节。")}</div>
      <div class="log-entry-tags">${item.tags.map((tag) => `<span class="log-entry-tag">${escapeHtml(tag)}</span>`).join("")}</div>
    `;
    executionLogView.appendChild(node);
  });

  if (shouldStickToBottom || state.executionLogAutoScroll) {
    executionLogView.scrollTop = executionLogView.scrollHeight;
  }
}

function renderExecutionDag() {
  if (!executionDagView || !executionDagMeta || !executionDagLegend) return;
  const response = state.lastBusinessResponse || {};
  const selectedModule = String(response?.selected_business_module || "").trim();
  const routing = response?.kernel_routing || {};
  const businessResult = response?.business_result || {};
  const businessOutput = businessResult?.business_output || {};
  const branchEvidence = Array.isArray(businessOutput?.per_branch_evidence) ? businessOutput.per_branch_evidence : [];
  const notes = businessOutput?.conflict_and_degradation_notes || {};
  const grade = String(businessResult?.result_grade || "").trim().toLowerCase() || "idle";
  const strategy = String(businessResult?.return_strategy || "").trim();

  executionDagView.innerHTML = "";

  if (!selectedModule && !state.latestAgentPanels.length) {
    executionDagMeta.textContent = "等待本轮执行图";
    executionDagLegend.textContent = "当前没有执行节点。";
    executionDagView.textContent = "等待本轮请求后显示模块选择、角色链路或 Swarm 分支。";
    return;
  }

  const selectionSummary = String(routing?.selection_summary || "").trim() || "显式 module_id / task_type 优先，通用 chat 走智能模块选择。";

  const routerRow = document.createElement("div");
  routerRow.className = "dag-flow-row";
  routerRow.innerHTML = `
    <div class="dag-node status-success">
      <div class="dag-node-label">Kernel Router</div>
      <div class="dag-node-meta">${escapeHtml(selectionSummary)}</div>
    </div>
    <div class="dag-node-arrow">→</div>
    <div class="dag-node status-${escapeHtml(grade || "active")}">
      <div class="dag-node-label">${escapeHtml(moduleLabel(selectedModule || "office_module"))}</div>
      <div class="dag-node-meta">${escapeHtml(strategy || "等待本轮返回策略")}</div>
    </div>
  `;
  executionDagView.appendChild(routerRow);

  if (branchEvidence.length) {
    executionDagMeta.textContent = `${moduleLabel(selectedModule)} · ${branchEvidence.length} 个 branch`;
    executionDagLegend.textContent = "Swarm DAG：先 fan-out，再 join / deduplicate，失败分支会标记降级或未参与合并。";

    const branchGrid = document.createElement("div");
    branchGrid.className = "dag-branch-grid";
    branchEvidence.forEach((branch) => {
      const status = String(branch?.branch_status || "success").trim().toLowerCase() || "success";
      const node = document.createElement("article");
      node.className = `dag-branch-card status-${status}`;
      const included = Boolean(branch?.included_in_final_merge);
      const evidenceCount = Number(branch?.branch_evidence_count || 0);
      const reason = String(branch?.not_included_reason || "").trim();
      node.innerHTML = `
        <div class="dag-status-row">
          <span class="dag-badge status-${status}">${escapeHtml(status)}</span>
          <span class="dag-badge">${included ? "已合并" : "未合并"}</span>
        </div>
        <div class="dag-branch-title">${escapeHtml(String(branch?.branch_label || branch?.branch_id || "branch"))}</div>
        <div class="dag-branch-meta">${escapeHtml(String(branch?.branch_summary || "暂无 branch 摘要"))}</div>
        <div class="dag-chip-row">
          <span class="dag-badge">证据 ${evidenceCount}</span>
          ${branch?.result_grade ? `<span class="dag-badge">${escapeHtml(String(branch.result_grade))}</span>` : ""}
          ${branch?.evidence_completeness ? `<span class="dag-badge">${escapeHtml(String(branch.evidence_completeness))}</span>` : ""}
        </div>
        ${!included && reason ? `<div class="dag-branch-reason">${escapeHtml(reason)}</div>` : ""}
      `;
      branchGrid.appendChild(node);
    });
    executionDagView.appendChild(branchGrid);

    const joinRow = document.createElement("div");
    joinRow.className = "dag-flow-row";
    joinRow.innerHTML = `
      <div class="dag-node status-${escapeHtml(grade)}">
        <div class="dag-node-label">Join / Merge</div>
        <div class="dag-node-meta">${escapeHtml(String(notes?.final_merge_decision || "执行 merge / deduplicate / conflict marking"))}</div>
      </div>
      <div class="dag-node-arrow">→</div>
      <div class="dag-node status-${escapeHtml(grade)}">
        <div class="dag-node-label">Business Result</div>
        <div class="dag-node-meta">${escapeHtml(String(notes?.reliability_note || businessResult?.reliability_note || "等待业务可靠性说明"))}</div>
      </div>
    `;
    executionDagView.appendChild(joinRow);
    return;
  }

  const panels = Array.isArray(state.latestAgentPanels) ? state.latestAgentPanels : [];
  const activeRoles = state.latestActiveRoles instanceof Set ? state.latestActiveRoles : new Set();
  const currentRole = normalizeRoleId(state.latestCurrentRole);
  const orderedPanels = panels.length
    ? panels
    : (Array.from(activeRoles).length ? Array.from(activeRoles).map((role) => ({ role, title: role })) : []);

  executionDagMeta.textContent = `${moduleLabel(selectedModule || "office_module")} · ${orderedPanels.length || 1} 个执行节点`;
  executionDagLegend.textContent = "线性执行链：显示当前模块的主要角色流与当前激活节点。";

  const flow = document.createElement("div");
  flow.className = "dag-flow-row";
  orderedPanels.forEach((panel, index) => {
    const roleId = normalizeRoleId(panel?.role);
    const stateClass =
      currentRole && roleId === currentRole
        ? "active"
        : activeRoles.has(roleId)
        ? "active"
        : "success";
    const node = document.createElement("div");
    node.className = `dag-node status-${stateClass}`;
    node.innerHTML = `
      <div class="dag-node-label">${escapeHtml(String(panel?.title || roleId || `step-${index + 1}`))}</div>
      <div class="dag-node-meta">${escapeHtml(String(panel?.summary || "当前角色正在参与执行。"))}</div>
    `;
    flow.appendChild(node);
    if (index < orderedPanels.length - 1) {
      const arrow = document.createElement("div");
      arrow.className = "dag-node-arrow";
      arrow.textContent = "→";
      flow.appendChild(arrow);
    }
  });
  executionDagView.appendChild(flow);
}

function buildCommandPaletteItems() {
  const items = [
    { id: "new-session", title: "新建会话", meta: "创建新 session 并清空当前聊天区", run: () => newSessionBtn?.click() },
    { id: "send-message", title: "发送当前输入", meta: "立即发送输入框中的内容", run: () => sendMessage() },
    { id: "refresh-sessions", title: "刷新会话列表", meta: "重新拉取历史 sessions", run: () => refreshSessionsBtn?.click() },
    { id: "sandbox-drill", title: "运行沙盒演练", meta: "调用 /api/sandbox/drill", run: () => sandboxDrillBtn?.click() },
    { id: "eval-harness", title: "运行回归测试", meta: "调用 /api/evals/run", run: () => evalHarnessBtn?.click() },
    { id: "clear-stats", title: "清除 Token 统计", meta: "重置本地累计 token 统计", run: () => clearStatsBtn?.click() },
    { id: "open-chat", title: "打开聊天视图", meta: "回到默认极简对话页", run: () => setWorkspaceView("chat") },
    {
      id: "toggle-chat-info",
      title: state.chatInfoOpen ? "收起侧面信息" : "打开侧面信息",
      meta: "在聊天页查看平台、路由和质量摘要",
      run: () => {
        setWorkspaceView("chat");
        setChatInfoOpen(!state.chatInfoOpen);
      },
    },
    { id: "open-control", title: "打开控制视图", meta: "查看模型、模式与请求参数", run: () => setWorkspaceView("control") },
    { id: "open-runtime", title: "打开运行视图", meta: "查看执行链路与结构化日志", run: () => setWorkspaceView("runtime") },
    { id: "open-modules", title: "打开模块视图", meta: "查看主核、模块与角色运行态", run: () => setWorkspaceView("modules") },
    { id: "open-operations", title: "打开运营视图", meta: "查看业务结果与运营摘要", run: () => setWorkspaceView("operations") },
    { id: "open-system", title: "打开系统视图", meta: "查看里程碑、路径策略与统计", run: () => setWorkspaceView("system") },
    { id: "view-modules", title: "切换到模块视图", meta: "只显示主核 / 模块舱", run: () => setRuntimeViewMode("modules") },
    { id: "view-roles", title: "切换到角色视图", meta: "只显示像素小人 / Role 视图", run: () => setRuntimeViewMode("roles") },
    { id: "view-split", title: "切换到双视图", meta: "同时显示模块与角色运行态", run: () => setRuntimeViewMode("split") },
    { id: "preset-general", title: "切换到通用模式", meta: "恢复通用模型与参数预设", run: () => applyModePreset("general") },
    { id: "preset-coding", title: "切换到编码模式", meta: "恢复编码模型与参数预设", run: () => applyModePreset("coding") },
    { id: "refresh-overview", title: "刷新运营总览", meta: "重新加载 gate / smoke / replay 摘要", run: () => refreshOperationsOverview() },
    { id: "open-health", title: "打开 /api/health", meta: "新标签页打开健康检查接口", run: () => window.open("/api/health", "_blank", "noopener") },
    { id: "open-role-lab", title: "打开 8081 Role Lab", meta: "跳转到本地角色实验台", run: () => window.open("http://localhost:8081", "_blank", "noopener") },
  ];
  if (isPanelDebugEnabled()) {
    items.push({
      id: "open-debug",
      title: "打开调试视图",
      meta: "查看 payload、trace 与 LLM 交换记录",
      run: () => setWorkspaceView("debug"),
    });
  }
  return items;
}

function fuzzyMatchCommand(command, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return true;
  const hay = `${command.title} ${command.meta} ${command.id}`.toLowerCase();
  return hay.includes(needle);
}

function getVisibleCommandPaletteCommands() {
  return buildCommandPaletteItems()
    .map((command) => ({
      ...command,
      score: state.recentCommands.includes(command.id) ? 1 : 0,
    }))
    .filter((command) => fuzzyMatchCommand(command, state.commandPaletteQuery))
    .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title, "zh-CN"));
}

function renderCommandPalette() {
  if (!commandPalette || !commandPaletteList || !commandPaletteInput) return;
  const commands = getVisibleCommandPaletteCommands();

  if (state.commandPaletteIndex >= commands.length) {
    state.commandPaletteIndex = Math.max(0, commands.length - 1);
  }

  commandPaletteList.innerHTML = "";
  if (!commands.length) {
    commandPaletteList.textContent = "没有匹配的命令。";
    commandPalette.dataset.commandCount = "0";
    return;
  }

  commands.forEach((command, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `command-item${index === state.commandPaletteIndex ? " is-active" : ""}`;
    button.dataset.commandId = command.id;
    button.innerHTML = `
      <div>${escapeHtml(command.title)}</div>
      <div class="command-item-meta">${escapeHtml(command.meta)}</div>
    `;
    button.addEventListener("click", async () => {
      closeCommandPalette();
      rememberCommandUse(command.id);
      await Promise.resolve(command.run());
      renderCommandPalette();
    });
    commandPaletteList.appendChild(button);
  });
  commandPalette.dataset.commandCount = String(commands.length);
  const activeButton = commandPaletteList.querySelector(".command-item.is-active");
  activeButton?.scrollIntoView?.({ block: "nearest" });
}

function openCommandPalette() {
  if (!commandPalette || !commandPaletteInput) return;
  state.commandPaletteOpen = true;
  state.commandPaletteQuery = "";
  state.commandPaletteIndex = 0;
  commandPalette.hidden = false;
  commandPalette.setAttribute("aria-hidden", "false");
  renderCommandPalette();
  window.setTimeout(() => commandPaletteInput.focus(), 0);
}

function closeCommandPalette() {
  if (!commandPalette) return;
  state.commandPaletteOpen = false;
  commandPalette.hidden = true;
  commandPalette.setAttribute("aria-hidden", "true");
}

function renderPlatformStatusSummary(health = {}) {
  if (!platformStatusHeadline || !platformStatusMeta || !platformStatusSignals) return;
  const hostRuntime = health?.kernel_host_runtime || {};
  const blackboard = hostRuntime?.blackboard || {};
  const selected = health?.kernel_selected_modules || {};
  const executionMode = String(health?.execution_mode_default || "host").trim();
  const authMode = String(health?.auth_mode || "unknown").trim();
  const primaryAgent = String(hostRuntime?.primary_agent_module?.module_id || "-");
  const primaryTool = String(hostRuntime?.primary_tool_module?.module_id || "-");
  const activeCount = Array.isArray(blackboard?.active_module_ids) ? blackboard.active_module_ids.length : 0;
  const product = String(health?.product_title || "Multi_Agent_Robot").trim();
  platformStatusHeadline.textContent = Object.keys(selected).length ? `${product} 已在线` : `${product} 待机`;
  platformStatusMeta.textContent = `auth=${authMode} · exec=${executionMode} · blackboard=${String(blackboard?.status || "idle")} · active_modules=${activeCount}`;
  platformStatusSignals.innerHTML = "";
  [
    `primary agent: ${primaryAgent}`,
    `primary tool: ${primaryTool}`,
    `docker: ${health?.docker_available ? "ready" : "not ready"}`,
  ].forEach((item) => platformStatusSignals.appendChild(createChip(item)));
}

function renderOperationsOverview(overview = {}) {
  state.operationsOverview = overview || {};
  const gates = Array.isArray(overview?.gates) ? overview.gates : [];
  const greenCount = gates.filter((item) => String(item?.status || "") === "pass").length;

  if (qualityOverviewHeadline) {
    qualityOverviewHeadline.textContent = overview?.headline || `运营摘要待生成`;
  }
  if (qualityOverviewMeta) {
    qualityOverviewMeta.textContent =
      overview?.subheadline || `gate / smoke / replay 样本库尚未加载。`;
  }
  if (qualityOverviewGrid) {
    qualityOverviewGrid.innerHTML = "";
    gates.forEach((item) => {
      const node = document.createElement("div");
      node.className = `hero-mini-card status-${String(item?.status || "missing")}`;
      node.innerHTML = `
        <span>${String(item?.label || "Gate")}</span>
        <strong>${Number(item?.passed || 0)}/${Number(item?.total || 0)}</strong>
      `;
      qualityOverviewGrid.appendChild(node);
    });
    if (!gates.length) {
      qualityOverviewGrid.textContent = "当前没有 gate 摘要。";
    }
  }

  if (gateSummaryGrid) {
    gateSummaryGrid.innerHTML = "";
    gates.forEach((item) => {
      const node = document.createElement("div");
      node.className = `ops-gate-card status-${String(item?.status || "missing")}`;
      node.innerHTML = `
        <span>${String(item?.label || "Gate")}</span>
        <strong>${Number(item?.passed || 0)}/${Number(item?.total || 0)}</strong>
        <div class="ops-note">${String(item?.artifact_path || "")}</div>
      `;
      gateSummaryGrid.appendChild(node);
    });
    if (!gates.length) {
      gateSummaryGrid.textContent = "当前没有 gate 数据。";
    }
  }

  if (replaySummaryView) {
    const replay = overview?.replay || {};
    const families = replay?.families || {};
    replaySummaryView.textContent = `root=${String(replay?.root || "evals/replay_samples")} · total=${Number(replay?.total_samples || 0)} · office=${Number(families.office || 0)} · research=${Number(families.research || 0)} · swarm=${Number(families.swarm || 0)}`;
  }

  if (smokeSummaryView) {
    const smokeLayers = Array.isArray(overview?.smoke_layers) ? overview.smoke_layers : [];
    smokeSummaryView.textContent = smokeLayers.map((item) => `${String(item?.label || "-")}${item?.ci ? " (CI)" : " (release-only)"}`).join(" · ") || "未加载 smoke 分层";
  }

  if (operationsIndexView) {
    operationsIndexView.innerHTML = "";
    const entries = Array.isArray(overview?.docs_index) ? overview.docs_index : [];
    entries.forEach((item) => {
      const node = document.createElement("div");
      node.className = "ops-entry";
      node.innerHTML = `
        <div class="ops-entry-label">${escapeHtml(String(item?.label || "Entry"))}</div>
        <div class="ops-entry-path">${escapeHtml(String(item?.path || ""))}</div>
      `;
      operationsIndexView.appendChild(node);
    });
    if (!entries.length) {
      operationsIndexView.textContent = "当前没有运营入口索引。";
    }
  }

  if (!moduleRouteTags?.childElementCount && gates.length) {
    moduleRouteTags.innerHTML = "";
    moduleRouteTags.appendChild(createChip(`${greenCount}/${gates.length} gates green`));
    gates.forEach((item) => moduleRouteTags.appendChild(createChip(summarizeGateLine(item))));
  }
}

function renderBusinessResultSummary(data = {}) {
  state.lastBusinessResponse = data || {};
  const selectedModule = String(data?.selected_business_module || "").trim();
  const routing = data?.kernel_routing || {};
  const businessResult = data?.business_result || {};
  const grade = String(businessResult?.result_grade || "").trim();
  const strategy = String(businessResult?.return_strategy || "").trim();
  const reliability = String(businessResult?.reliability_note || "").trim();
  const effectiveModel = String(data?.effective_model || "").trim();
  const selectionSummary = String(routing?.selection_summary || "").trim();
  const conflictDetected = Boolean(businessResult?.conflict_detected);
  const degraded = grade === "degraded";
  const sourceCount = Number(businessResult?.source_count || 0);
  const branchCount = Number(businessResult?.branch_count || 0);
  const mergedFindingCount = Number(businessResult?.merged_finding_count || 0);

  if (moduleRouteHeadline) {
    moduleRouteHeadline.textContent = selectedModule ? `${moduleLabel(selectedModule)} 已接管本轮请求` : "等待本轮模块选择";
  }
  if (moduleRouteMeta) {
    moduleRouteMeta.textContent =
      selectionSummary ||
      "显式 module_id / task_type 优先；通用 chat 会在 office 与 research 间选择。";
  }
  if (moduleRouteTags) {
    moduleRouteTags.innerHTML = "";
    if (selectedModule) moduleRouteTags.appendChild(createChip(moduleLabel(selectedModule)));
    if (effectiveModel) moduleRouteTags.appendChild(createChip(`model: ${effectiveModel}`));
    if (grade) moduleRouteTags.appendChild(createChip(`grade: ${grade}`));
    if (strategy) moduleRouteTags.appendChild(createChip(`strategy: ${strategy}`));
    if (sourceCount) moduleRouteTags.appendChild(createChip(`sources: ${sourceCount}`));
    if (branchCount) moduleRouteTags.appendChild(createChip(`branches: ${branchCount}`));
    if (mergedFindingCount) moduleRouteTags.appendChild(createChip(`merged: ${mergedFindingCount}`));
    if (conflictDetected) moduleRouteTags.appendChild(createChip("conflict detected"));
    if (degraded) moduleRouteTags.appendChild(createChip("degraded path"));
  }

  if (resultModuleView) resultModuleView.textContent = moduleLabel(selectedModule);
  if (resultGradeView) resultGradeView.textContent = grade || "-";
  if (resultStrategyView) resultStrategyView.textContent = strategy || "-";
  if (resultModelView) resultModelView.textContent = effectiveModel || "-";
  if (resultReliabilityView) {
    resultReliabilityView.textContent =
      reliability ||
      (selectedModule ? "本轮未返回额外可靠性说明。" : "等待首轮响应后显示可靠性说明与降级信息。");
  }
  if (resultContextView) {
    resultContextView.innerHTML = "";
    const contextChips = [];
    if (String(data?.attachment_context_mode || "").trim()) contextChips.push(`attachments: ${String(data.attachment_context_mode)}`);
    if (Number(data?.queue_wait_ms || 0) > 0) contextChips.push(`queue: ${Number(data.queue_wait_ms)} ms`);
    if (String(data?.route_state_scope || "").trim()) contextChips.push(`route_state: ${String(data.route_state_scope)}`);
    if (businessResult?.evidence_completeness) contextChips.push(`evidence: ${String(businessResult.evidence_completeness)}`);
    if (businessResult?.provider_fallback_used) contextChips.push("provider fallback");
    if (businessResult?.partial_results) contextChips.push("partial results");
    contextChips.forEach((item) => resultContextView.appendChild(createChip(item, "ops-chip")));
  }
  renderExecutionDag();
}

async function refreshOperationsOverview() {
  try {
    const res = await fetch("/api/operations/overview");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderOperationsOverview(data);
    return data;
  } catch {
    renderOperationsOverview({});
    return {};
  }
}

function formatRelativeTime(raw) {
  const value = String(raw || "").trim();
  if (!value) return "未知";
  try {
    const ts = new Date(value);
    if (Number.isNaN(ts.getTime())) return value;
    const diffSec = Math.max(0, Math.floor((Date.now() - ts.getTime()) / 1000));
    if (diffSec < 60) return `${diffSec}s 前`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m 前`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h 前`;
    return `${Math.floor(diffSec / 86400)}d 前`;
  } catch {
    return value;
  }
}

function normalizeCounterItems(items) {
  return (Array.isArray(items) ? items : [])
    .map((item) => ({
      name: String(item?.name || "").trim(),
      count: Number(item?.count || 0),
    }))
    .filter((item) => item.name);
}

function pickTopCounterName(items, fallback = "none") {
  const normalized = normalizeCounterItems(items);
  return normalized.length ? `${normalized[0].name} · ${normalized[0].count}` : fallback;
}

function renderKernelStatGrid(container, items) {
  if (!container) return;
  container.innerHTML = "";
  (Array.isArray(items) ? items : []).forEach((item) => {
    const cell = document.createElement("div");
    cell.className = "kernel-stat";

    const label = document.createElement("div");
    label.className = "kernel-stat-label";
    label.textContent = String(item?.label || "");
    cell.appendChild(label);

    const value = document.createElement("div");
    value.className = "kernel-stat-value";
    value.textContent = String(item?.value || "-");
    cell.appendChild(value);

    const meta = String(item?.meta || "").trim();
    if (meta) {
      const metaNode = document.createElement("div");
      metaNode.className = "kernel-stat-meta";
      metaNode.textContent = meta;
      cell.appendChild(metaNode);
    }

    container.appendChild(cell);
  });
}

function toBadgeClass(value) {
  return String(value || "module")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
}

function buildModuleCard(item, options = {}) {
  const node = document.createElement("article");
  const isPrimary = Boolean(options?.primary);
  const isActive = Boolean(options?.active);
  const isSupport = Boolean(options?.support);
  const badgeLabel = String(options?.badge || item?.kind || "MODULE");
  const badgeClass = toBadgeClass(badgeLabel);
  const status = String(options?.status || "active").trim().toLowerCase() || "active";
  node.className = `module-card status-${status}${isPrimary ? " is-primary" : ""}${isActive ? " is-active" : ""}${isSupport ? " support-card" : ""}`;
  node.innerHTML = `
    <div class="module-card-head">
      <div>
        <div class="module-card-title">${String(item?.title || item?.module_id || item?.key || "Module")}</div>
        <div class="module-card-ref">${String(item?.module_id || item?.ref || item?.key || "-")}</div>
      </div>
      <span class="module-status-badge kind-${badgeClass}">${badgeLabel}</span>
    </div>
    <div class="module-card-desc">${String(item?.description || "模块描述缺失。")}</div>
    <div class="module-card-stats">
      ${(Array.isArray(item?.stats) ? item.stats : []).map((stat) => `<span>${stat}</span>`).join("")}
    </div>
    <div class="module-card-signals">
      ${(Array.isArray(item?.signals) ? item.signals : []).map((signal) => `<span class="signal-chip">${String(signal)}</span>`).join("")}
      ${isPrimary ? `<span class="signal-chip primary-chip">primary</span>` : ""}
      ${isActive ? `<span class="signal-chip active-chip">active</span>` : ""}
    </div>
    ${String(item?.error || "").trim() ? `<div class="module-card-error">${String(item.error).trim()}</div>` : ""}
  `;
  return node;
}

function renderSystemFlow(health = {}) {
  if (!systemFlowRibbon) return;
  const hostRuntime = health?.kernel_host_runtime || {};
  const blackboard = hostRuntime?.blackboard || {};
  const activeModules = Array.isArray(blackboard?.active_module_ids) ? blackboard.active_module_ids : [];
  const flowItems = [
    { label: "KernelHost", value: "host", meta: String(blackboard?.status || "idle").trim() || "idle", tone: "host" },
    { label: "AgentModule", value: String(hostRuntime?.primary_agent_module?.module_id || "-"), meta: String(hostRuntime?.primary_agent_module?.title || "未装载"), tone: "agent" },
    { label: "ToolModule", value: String(hostRuntime?.primary_tool_module?.module_id || "-"), meta: String(hostRuntime?.primary_tool_module?.title || "未装载"), tone: "tool" },
    { label: "OutputModule", value: String(hostRuntime?.primary_output_module?.module_id || "-"), meta: String(hostRuntime?.primary_output_module?.title || "未装载"), tone: "output" },
    { label: "MemoryModule", value: String(hostRuntime?.primary_memory_module?.module_id || "-"), meta: String(hostRuntime?.primary_memory_module?.title || "未装载"), tone: "memory" },
    { label: "Blackboard", value: String(blackboard?.request_id || "waiting").slice(0, 16), meta: activeModules.length ? `${activeModules.length} active modules` : String(blackboard?.selected_agent_module_id || "等待请求"), tone: "blackboard" },
  ];

  systemFlowRibbon.innerHTML = "";
  flowItems.forEach((item) => {
    const node = document.createElement("div");
    node.className = `system-flow-node tone-${item.tone}`;
    node.innerHTML = `
      <div class="system-flow-label">${item.label}</div>
      <div class="system-flow-value">${item.value}</div>
      <div class="system-flow-meta">${item.meta}</div>
    `;
    systemFlowRibbon.appendChild(node);
  });
}

function renderModuleBay(health = {}) {
  if (!moduleBay) return;
  const selected = health?.kernel_selected_modules || {};
  const moduleHealth = health?.kernel_module_health || {};
  const hostRuntime = health?.kernel_host_runtime || {};
  const blackboard = hostRuntime?.blackboard || {};
  const activeIds = new Set(Array.isArray(blackboard?.active_module_ids) ? blackboard.active_module_ids : []);
  const toolModuleUsage = blackboard?.tool_module_usage || {};
  const agentModules = Array.isArray(hostRuntime?.agent_modules) ? hostRuntime.agent_modules : [];
  const toolModules = Array.isArray(hostRuntime?.tool_modules) ? hostRuntime.tool_modules : [];
  const outputModules = Array.isArray(hostRuntime?.output_modules) ? hostRuntime.output_modules : [];
  const memoryModules = Array.isArray(hostRuntime?.memory_modules) ? hostRuntime.memory_modules : [];
  const overlay = health?.assistant_overlay_profile || {};
  const moduleAffinity = overlay?.module_affinity || {};
  const entries = Object.entries(selected);
  const primaryIds = new Set(
    [
      hostRuntime?.primary_agent_module?.module_id,
      hostRuntime?.primary_tool_module?.module_id,
      hostRuntime?.primary_output_module?.module_id,
      hostRuntime?.primary_memory_module?.module_id,
    ].filter(Boolean)
  );

  moduleBay.innerHTML = "";
  if (!entries.length && !agentModules.length && !toolModules.length && !outputModules.length && !memoryModules.length) {
    moduleBay.textContent = "模块舱为空。";
    if (moduleBayMeta) moduleBayMeta.textContent = "0 modules";
    return;
  }

  if (moduleBayMeta) {
    const capabilityCount = agentModules.length + toolModules.length + outputModules.length + memoryModules.length;
    moduleBayMeta.textContent = `${capabilityCount} 个能力模块 · ${entries.length} 个支撑模块`;
  }

  const supportEntries = entries.map(([key, ref]) => {
    const meta = MODULE_LABELS[key] || { title: key, desc: "未命名模块。" };
    const healthItem = moduleHealth?.[key] || {};
    const status = String(healthItem?.status || "active").trim().toLowerCase() || "active";
    const failureCount = Number(healthItem?.failure_count || 0);
    const overlayItems = normalizeCounterItems(moduleAffinity?.[key.replace("provider:", "")] || moduleAffinity?.[key] || []);
    return {
      title: meta.title,
      key,
      ref: String(ref || "-"),
      description: meta.desc,
      stats: [
        `status=${status}`,
        `failure=${failureCount}`,
        `selected=${String(healthItem?.selected_ref || ref || "-")}`,
      ],
      signals: overlayItems.slice(0, 3).map((item) => `${item.name} · ${item.count}`),
      error: String(healthItem?.last_error || "").trim(),
      status,
    };
  });

  const groups = [
    {
      title: "Agent Modules",
      meta: "会思考、会规划、会驱动内部多 agent 流程。",
      items: agentModules.map((item) => ({
        kind: "Agent",
        primary: primaryIds.has(item?.module_id),
        active: activeIds.has(item?.module_id),
        badge: "AGENT",
        card: {
          title: String(item?.title || "Agent Module"),
          module_id: String(item?.module_id || "-"),
          description: String(item?.description || "未填写描述。"),
          stats: [`roles=${Array.isArray(item?.roles) ? item.roles.length : 0}`, `profiles=${Array.isArray(item?.profiles) ? item.profiles.length : 0}`],
          signals: Array.isArray(item?.profiles) ? item.profiles : [],
        },
      })),
    },
    {
      title: "Tool Modules",
      meta: "动作能力分舱。当前请求已经按 ToolModule 路由执行。",
      items: toolModules.map((item) => ({
        kind: "Tool",
        primary: primaryIds.has(item?.module_id),
        active: activeIds.has(item?.module_id),
        badge: "TOOL",
        card: {
          title: String(item?.title || "Tool Module"),
          module_id: String(item?.module_id || "-"),
          description: String(item?.description || "未填写描述。"),
          stats: [
            `tools=${Array.isArray(item?.tool_names) ? item.tool_names.length : 0}`,
            `used=${Number(toolModuleUsage?.[String(item?.module_id || "")] || 0)}`,
          ],
          signals: Array.isArray(item?.tool_names) ? item.tool_names.slice(0, 5) : [],
        },
      })),
    },
    {
      title: "Output & Memory",
      meta: "输出收口与长期个体覆层。",
      items: [
        ...outputModules.map((item) => ({
          kind: "Output",
          primary: primaryIds.has(item?.module_id),
          active: activeIds.has(item?.module_id),
          badge: "OUTPUT",
          card: {
            title: String(item?.title || "Output Module"),
            module_id: String(item?.module_id || "-"),
            description: String(item?.description || "未填写描述。"),
            stats: [`outputs=${Array.isArray(item?.output_kinds) ? item.output_kinds.length : 0}`],
            signals: Array.isArray(item?.output_kinds) ? item.output_kinds : [],
          },
        })),
        ...memoryModules.map((item) => ({
          kind: "Memory",
          primary: primaryIds.has(item?.module_id),
          active: activeIds.has(item?.module_id),
          badge: "MEMORY",
          card: {
            title: String(item?.title || "Memory Module"),
            module_id: String(item?.module_id || "-"),
            description: String(item?.description || "未填写描述。"),
            stats: [`signals=${Array.isArray(item?.signal_kinds) ? item.signal_kinds.length : 0}`],
            signals: Array.isArray(item?.signal_kinds) ? item.signal_kinds : [],
          },
        })),
      ],
    },
    {
      title: "Kernel Support",
      meta: "主核级支撑模块，负责路由、策略、provider、registry 与降级。",
      items: supportEntries.map((item) => ({
        kind: "Support",
        primary: false,
        badge: "SUPPORT",
        status: item.status,
        support: true,
        card: {
          title: item.title,
          module_id: item.key,
          ref: item.ref,
          description: item.description,
          stats: item.stats,
          signals: item.signals,
          error: item.error,
        },
      })),
    },
  ];

  groups
    .filter((group) => Array.isArray(group.items) && group.items.length)
    .forEach((group) => {
      const section = document.createElement("section");
      section.className = "module-group";

      const head = document.createElement("div");
      head.className = "module-group-head";
      head.innerHTML = `
        <div class="module-group-title">${group.title}</div>
        <div class="module-group-meta">${group.meta}</div>
      `;
      section.appendChild(head);

      const grid = document.createElement("div");
      grid.className = "module-group-grid";
      group.items.forEach((item) => {
        grid.appendChild(
          buildModuleCard(item.card, {
            primary: item.primary,
            active: item.active,
            badge: item.badge,
            status: item.status,
            support: item.support,
          })
        );
      });
      section.appendChild(grid);
      moduleBay.appendChild(section);
    });
}

function renderEvolutionFeed(events = []) {
  if (!evolutionFeed) return;
  const items = Array.isArray(events) ? events : [];
  evolutionFeed.innerHTML = "";
  if (!items.length) {
    evolutionFeed.textContent = "还没有进化记录。";
    if (evolutionFeedMeta) evolutionFeedMeta.textContent = "0 events";
    return;
  }
  if (evolutionFeedMeta) {
    evolutionFeedMeta.textContent = `${items.length} 条最近记录`;
  }
  items.slice(0, 8).forEach((item) => {
    const node = document.createElement("article");
    node.className = "evolution-event";
    const terms = Array.isArray(item?.domain_terms) ? item.domain_terms.filter(Boolean).slice(0, 4) : [];
    node.innerHTML = `
      <div class="evolution-event-head">
        <span class="evolution-event-title">${String(item?.primary_intent || "standard")}</span>
        <span class="evolution-event-time">${formatRelativeTime(item?.created_at)}</span>
      </div>
      <div class="evolution-event-summary">${String(item?.summary || "").trim() || "本轮记录了新的适应信号。"}</div>
      <div class="evolution-event-meta">profile=${String(item?.runtime_profile || "-")} · task=${String(item?.task_type || "-")}</div>
      <div class="module-card-signals">${terms.map((term) => `<span class="signal-chip">${term}</span>`).join("")}</div>
    `;
    evolutionFeed.appendChild(node);
  });
}

function milestoneStatusLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  if (key === "done") return "完成";
  if (key === "active") return "当前";
  return "待启动";
}

function renderMilestones() {
  const milestones = Array.isArray(AGENT_OS_MILESTONES) ? AGENT_OS_MILESTONES : [];
  const completedCount = milestones.filter((item) => String(item?.status || "") === "done").length;
  const current =
    milestones.find((item) => String(item?.status || "") === "active") ||
    milestones[completedCount] ||
    milestones[milestones.length - 1] ||
    milestones[0];

  if (milestoneSidebarView) {
    const lines = [
      `当前阶段: ${String(current?.id || "-")} ${String(current?.title || "")}`.trim(),
      `已完成: ${completedCount}/${milestones.length}`,
      `下一重点: ${String(current?.summary || "等待路线图").trim() || "等待路线图"}`,
      "路线: M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7",
    ];
    milestoneSidebarView.textContent = lines.join("\n");
  }

  if (milestoneRoadmapMeta) {
    milestoneRoadmapMeta.textContent = `已完成 ${completedCount}/${milestones.length} · 当前阶段 ${String(current?.id || "-")}`;
  }

  if (!milestoneRoadmap) return;
  milestoneRoadmap.innerHTML = "";
  milestones.forEach((item) => {
    const node = document.createElement("article");
    const status = String(item?.status || "queued").trim().toLowerCase() || "queued";
    node.className = `milestone-card status-${status}`;
    node.innerHTML = `
      <div class="milestone-card-head">
        <div>
          <div class="milestone-card-id">${String(item?.id || "-")}</div>
          <div class="milestone-card-title">${String(item?.title || "Milestone")}</div>
        </div>
        <span class="milestone-status-badge status-${status}">${milestoneStatusLabel(status)}</span>
      </div>
      <div class="milestone-card-summary">${String(item?.summary || "").trim() || "暂无说明。"}</div>
      <div class="milestone-card-tags">
        ${(Array.isArray(item?.tags) ? item.tags : []).map((tag) => `<span class="signal-chip">${String(tag)}</span>`).join("")}
      </div>
    `;
    milestoneRoadmap.appendChild(node);
  });
}

function renderRoleLabRunGraph(lastRun = {}) {
  if (!roleLabRunGraph || !roleLabRunFailures) return;
  const nodes = Array.isArray(lastRun?.nodes) ? lastRun.nodes : [];
  const instances = Array.isArray(lastRun?.instances) ? lastRun.instances : [];
  const events = Array.isArray(lastRun?.events) ? lastRun.events : [];
  roleLabRunGraph.innerHTML = "";
  roleLabRunFailures.innerHTML = "";

  if (!nodes.length) {
    roleLabRunGraph.textContent = "最近还没有运行图。";
    roleLabRunFailures.textContent = "最近还没有局部失败。";
    return;
  }

  const nodeMap = new Map();
  const children = new Map();
  nodes.forEach((node) => {
    const id = String(node?.node_id || "").trim();
    if (!id) return;
    nodeMap.set(id, node);
    const parentId = String(node?.parent_node_id || "").trim();
    if (!children.has(parentId)) children.set(parentId, []);
    children.get(parentId).push(node);
  });

  const instanceMap = new Map();
  instances.forEach((item) => {
    const nodeId = String(item?.node_id || "").trim();
    if (!nodeId) return;
    const list = instanceMap.get(nodeId) || [];
    list.push(item);
    instanceMap.set(nodeId, list);
  });

  const preferredRoots = nodes.filter((node) => {
    const parentId = String(node?.parent_node_id || "").trim();
    return !parentId || !nodeMap.has(parentId);
  });
  const roots = preferredRoots.length ? preferredRoots : nodes.slice(0, 1);

  const labelForNode = (node) => {
    const nodeType = String(node?.node_type || "role").trim();
    const meta = node?.meta || {};
    if (nodeType === "join") return "join";
    if (nodeType === "branch") {
      const toolName = String(meta?.tool_name || "").trim();
      return toolName ? `tool:${toolName}` : String(node?.phase || "branch");
    }
    return String(node?.role || "-");
  };

  const renderNode = (node, depth = 0) => {
    const nodeType = String(node?.node_type || "role").trim();
    const status = String(node?.status || "pending").trim();
    const attempts = Number(node?.attempts || 0);
    const meta = node?.meta || {};
    const item = document.createElement("article");
    item.className = `runtime-graph-node ${nodeType} ${status}`;
    item.style.setProperty("--depth", String(depth));
    const tags = [];
    if (attempts > 1) tags.push(`retry=${attempts - 1}`);
    if (meta?.synthetic) tags.push("synthetic");
    if (meta?.batch_index) tags.push(`slot=${meta.batch_index}`);
    if (meta?.failed_branches > 0) tags.push(`failed=${meta.failed_branches}`);
    const relatedInstances = instanceMap.get(String(node?.node_id || "").trim()) || [];
    if (relatedInstances.length) {
      const lastInstance = relatedInstances[relatedInstances.length - 1] || {};
      tags.push(String(lastInstance?.instance_id || "").trim());
    }
    item.innerHTML = `
      <div class="runtime-graph-line">
        <span class="runtime-graph-dot ${status}"></span>
        <span class="runtime-graph-label">${labelForNode(node)}</span>
        <span class="runtime-graph-phase">${String(node?.phase || "-")}</span>
      </div>
      <div class="runtime-graph-meta">
        <span>${status}</span>
        ${tags.map((tag) => `<span>${tag}</span>`).join("")}
      </div>
      ${
        String(node?.summary || "").trim()
          ? `<div class="runtime-graph-summary">${String(node.summary).trim()}</div>`
          : ""
      }
      ${
        String(node?.error || "").trim()
          ? `<div class="runtime-graph-error">${String(node.error).trim()}</div>`
          : ""
      }
    `;
    roleLabRunGraph.appendChild(item);
    (children.get(String(node?.node_id || "").trim()) || []).forEach((child) => renderNode(child, depth + 1));
  };

  roots.forEach((node) => renderNode(node, 0));

  const failureEvents = events.filter((item) => {
    const kind = String(item?.kind || "").trim();
    return kind === "worker_tool_retry_scheduled" || kind === "node_failed" || kind === "role_failed";
  });
  if (!failureEvents.length) {
    roleLabRunFailures.textContent = "最近还没有局部失败。";
    return;
  }
  failureEvents.slice(-8).reverse().forEach((event) => {
    const row = document.createElement("div");
    row.className = "runtime-failure-row";
    const kind = String(event?.kind || "").trim();
    const label =
      kind === "worker_tool_retry_scheduled"
        ? `retry · ${String(event?.tool_name || "-")}`
        : `${kind} · ${String(event?.role || event?.tool_name || "-")}`;
    row.innerHTML = `
      <div class="runtime-failure-head">
        <span>${label}</span>
        <span>${formatRelativeTime(event?.ts)}</span>
      </div>
      <div class="runtime-failure-detail">${String(event?.error || event?.summary || event?.branch_group || "-")}</div>
    `;
    roleLabRunFailures.appendChild(row);
  });
}

function renderRoleLabRuntime(health = {}) {
  if (!roleLabRuntimeMetrics || !roleLabRegistry) return;
  const runtime = health?.role_lab_runtime || {};
  const registry = runtime?.registry || {};
  const readiness = runtime?.stage4_readiness || {};
  const lastRun = runtime?.last_run || {};
  const runMeta = lastRun?.run || {};
  const registryRoles = Array.isArray(registry?.roles) ? registry.roles : [];

  if (roleLabRuntimeMeta) {
    roleLabRuntimeMeta.textContent = `${Number(registry?.registered_roles || 0)} registered · ${Number(readiness?.controller_backed_role_count || 0)} controller-backed`;
  }

  renderKernelStatGrid(roleLabRuntimeMetrics, [
    { label: "Stage 4 Trial", value: readiness?.ready_for_stage4_trial ? "READY" : "PREP", meta: String(readiness?.next_focus || "runtime abstraction") },
    { label: "Coverage", value: `${Number(readiness?.controller_backed_role_count || 0)}/${Number(registry?.registered_roles || 0)}`, meta: "controller-backed / registered" },
    { label: "Multi Instance", value: String(readiness?.multi_instance_role_count || 0), meta: "roles can spawn same-type instances" },
    { label: "Parent/Child", value: String(readiness?.parent_child_role_count || 0), meta: "roles support task parent-child graph" },
    { label: "Last Run", value: String(runMeta?.status || "-").toUpperCase(), meta: `instances=${Number(runMeta?.instance_count || 0)} · nodes=${Number(runMeta?.node_count || 0)}` },
    { label: "Current Role", value: String(lastRun?.current_role || "-"), meta: String((lastRun?.active_roles || []).join(", ") || "idle") },
  ]);
  renderRoleLabRunGraph(lastRun);

  roleLabRegistry.innerHTML = "";
  if (!registryRoles.length) {
    roleLabRegistry.textContent = "role registry 为空。";
    return;
  }
  registryRoles.forEach((item) => {
    const role = String(item?.role || "").trim();
    const title = String(item?.title || role).trim();
    const kind = String(item?.kind || "agent").trim();
    const executable = Boolean(item?.executable);
    const multiInstance = Boolean(item?.multi_instance_ready);
    const parentChild = Boolean(item?.supports_parent_child);
    const card = document.createElement("article");
    card.className = `module-card ${executable ? "status-active" : "status-idle"}`;
    card.innerHTML = `
      <div class="module-card-head">
        <div>
          <div class="module-card-title">${title}</div>
          <div class="module-card-ref">${role}</div>
        </div>
        <span class="module-status-badge">${executable ? "ACTIVE" : "META"}</span>
      </div>
      <div class="module-card-desc">${String(item?.description || "").trim() || "未填写描述。"}</div>
      <div class="module-card-stats">
        <span>kind=${kind}</span>
        <span>multi=${multiInstance ? "yes" : "no"}</span>
      </div>
      <div class="module-card-signals">
        <span class="signal-chip">${parentChild ? "parent-child ready" : "flat only"}</span>
        ${(Array.isArray(item?.runtime_profiles) ? item.runtime_profiles : []).slice(0, 3).map((profile) => `<span class="signal-chip">${String(profile)}</span>`).join("")}
      </div>
    `;
    roleLabRegistry.appendChild(card);
  });
}

function renderKernelConsole(health = {}) {
  const selected = health?.kernel_selected_modules || {};
  const hostRuntime = health?.kernel_host_runtime || {};
  const primaryAgent = hostRuntime?.primary_agent_module || {};
  const primaryTool = hostRuntime?.primary_tool_module || {};
  const primaryOutput = hostRuntime?.primary_output_module || {};
  const primaryMemory = hostRuntime?.primary_memory_module || {};
  const blackboard = hostRuntime?.blackboard || {};
  const toolUsage = blackboard?.tool_usage || {};
  const toolModuleUsage = blackboard?.tool_module_usage || {};
  const activeModules = Array.isArray(blackboard?.active_module_ids) ? blackboard.active_module_ids : [];
  const overlay = health?.assistant_overlay_profile || {};
  const recentEvents = health?.assistant_evolution_recent || [];
  const validation = health?.kernel_shadow_validation || {};
  const promoteCheck = health?.kernel_shadow_promote_check || {};
  const lastUpgrade = health?.kernel_last_upgrade_run || {};
  const lastRepair = health?.kernel_last_repair_run || {};
  const lastPatch = health?.kernel_last_patch_worker_run || {};
  const lastPackage = health?.kernel_last_package_run || {};
  const toolRegistry = health?.kernel_tool_registry || {};
  const authMode = String(health?.auth_mode || "").trim() || "unknown";
  const turnCount = Number(overlay?.turns_observed || 0);
  const capabilityCount =
    (Array.isArray(hostRuntime?.agent_modules) ? hostRuntime.agent_modules.length : 0) +
    (Array.isArray(hostRuntime?.tool_modules) ? hostRuntime.tool_modules.length : 0) +
    (Array.isArray(hostRuntime?.output_modules) ? hostRuntime.output_modules.length : 0) +
    (Array.isArray(hostRuntime?.memory_modules) ? hostRuntime.memory_modules.length : 0);
  const topToolModule = Object.entries(toolModuleUsage)
    .sort((a, b) => Number(b?.[1] || 0) - Number(a?.[1] || 0))[0]?.[0] || "none";
  const topTool = Object.entries(toolUsage)
    .sort((a, b) => Number(b?.[1] || 0) - Number(a?.[1] || 0))[0]?.[0] || "none";

  if (kernelLiveLabel) {
    kernelLiveLabel.textContent = Object.keys(selected).length ? "主核在线" : "主核待机";
  }
  if (kernelLiveMeta) {
    kernelLiveMeta.textContent =
      `agent=${String(primaryAgent?.module_id || "-")} · tool=${String(primaryTool?.module_id || "-")} · blackboard=${String(blackboard?.status || "idle")}`;
  }

  renderSystemFlow(health);

  renderKernelStatGrid(kernelCoreMetrics, [
    { label: "Host State", value: String(Object.keys(selected).length ? "ONLINE" : "IDLE"), meta: `build=${String(health?.build_version || "runtime")}` },
    { label: "Capability Bundles", value: String((hostRuntime?.loaded_capability_bundles || []).length || 0), meta: (hostRuntime?.loaded_capability_bundles || []).join(", ") || "none" },
    { label: "Primary Agent", value: String(primaryAgent?.module_id || "-"), meta: String(primaryAgent?.title || "未装载") },
    { label: "Primary Tool Bus", value: String(primaryTool?.module_id || "-"), meta: `${Number(toolRegistry?.tool_count || 0)} tools registered` },
    { label: "Primary Output", value: String(primaryOutput?.module_id || "-"), meta: String(primaryOutput?.title || "未装载") },
    { label: "Primary Memory", value: String(primaryMemory?.module_id || "-"), meta: `${capabilityCount} capability modules` },
  ]);

  renderKernelStatGrid(shadowLabMetrics, [
    { label: "Status", value: String(blackboard?.status || "idle").toUpperCase(), meta: String(blackboard?.request_id || "waiting") },
    { label: "Agent Slot", value: String(blackboard?.selected_agent_module_id || "-"), meta: String(blackboard?.selected_capability_modules?.join(", ") || "no request yet") },
    { label: "Tool Slot", value: String(blackboard?.selected_tool_module_id || "-"), meta: `events=${Number(blackboard?.tool_event_count || 0)} · top=${topToolModule}` },
    { label: "Output Slot", value: String(blackboard?.selected_output_module_id || "-"), meta: `${String(blackboard?.selected_memory_module_id || "memory=-")} · tool=${topTool}` },
    { label: "Plan", value: String((blackboard?.execution_plan || []).length || 0), meta: String((blackboard?.execution_plan || [])[0] || "暂无执行计划") },
    { label: "Active Modules", value: String(activeModules.length || 0), meta: activeModules.slice(0, 3).join(", ") || "等待模块激活" },
    { label: "Last Error", value: String(blackboard?.last_error ? "YES" : "NO"), meta: String(blackboard?.last_error || blackboard?.answer_bundle_summary || "暂无错误，等待输出摘要") },
  ]);

  renderKernelStatGrid(evolutionMetrics, [
    { label: "Validate", value: validation?.ok ? "PASS" : "CHECK", meta: String(validation?.reason || validation?.detail || "shadow validation") },
    { label: "Promote Gate", value: promoteCheck?.ok ? "OPEN" : "HOLD", meta: String(promoteCheck?.reason || "compatibility gate") },
    { label: "Overlay Turns", value: String(turnCount), meta: `updated=${formatRelativeTime(overlay?.updated_at)}` },
    { label: "Top Terms", value: pickTopCounterName(overlay?.domain_terms || [], "none"), meta: "长期对话累积的领域词" },
    { label: "Patch Worker", value: String(lastPatch?.stop_reason || (lastPatch?.ok ? "pipeline_ok" : "-")), meta: `rounds=${Number(lastPatch?.round_count || 0)}` },
    { label: "Last Upgrade", value: String(lastUpgrade?.run_id || "-").slice(0, 12) || "-", meta: formatRelativeTime(lastUpgrade?.finished_at || lastUpgrade?.started_at) },
  ]);

  renderModuleBay(health);
  renderEvolutionFeed(recentEvents);
  renderMilestones();
}

async function refreshSystemDashboard() {
  const health = await fetch("/api/health").then((r) => r.json());
  state.lastHealth = health;
  renderProductProfile(health);
  renderAppVersion(health);
  renderBackendPolicy(health);
  renderKernelConsole(health);
  renderRoleLabRuntime(health);
  renderPlatformStatusSummary(health);
  return health;
}

function currentSessionKey() {
  return String(state.sessionId || "").trim();
}

function isSessionSending(sessionId) {
  const key = String(sessionId || "").trim();
  if (!key) return false;
  return state.sendingSessionIds.has(key);
}

function updateSendAvailability() {
  if (!sendBtn) return;
  const sid = currentSessionKey();
  const disabled = Boolean(state.uploading || (sid && isSessionSending(sid)));
  sendBtn.disabled = disabled;
}

function updateDrillAvailability() {
  if (!sandboxDrillBtn) return;
  sandboxDrillBtn.disabled = Boolean(state.drilling);
}

function updateEvalAvailability() {
  if (!evalHarnessBtn) return;
  evalHarnessBtn.disabled = Boolean(state.evaluating);
}

function refreshSession() {
  sessionIdView.textContent = state.sessionId || "(未创建)";
  if (deleteSessionBtn) {
    deleteSessionBtn.disabled = !state.sessionId;
  }
  try {
    if (state.sessionId) {
      window.localStorage.setItem(SESSION_STORAGE_KEY, state.sessionId);
    } else {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  } catch {}
  updateSendAvailability();
}

function getStoredSessionId() {
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    const val = (raw || "").trim();
    return val || null;
  } catch {
    return null;
  }
}

function clearChat() {
  if (!chatList) return;
  chatList.innerHTML = "";
}

function formatSessionTime(raw) {
  const s = String(raw || "").trim();
  if (!s) return "-";
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleString();
  } catch {
    return s;
  }
}

async function refreshSessionHistory() {
  if (!sessionHistoryView) return [];
  sessionHistoryView.textContent = "加载中...";

  try {
    const res = await fetch("/api/sessions?limit=80");
    if (!res.ok) {
      sessionHistoryView.textContent = "历史会话加载失败";
      return [];
    }
    const data = await res.json();
    const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
    sessionHistoryView.innerHTML = "";
    if (!sessions.length) {
      const empty = document.createElement("div");
      empty.className = "session-history-empty";
      empty.textContent = "暂无历史会话";
      sessionHistoryView.appendChild(empty);
      return [];
    }

    sessions.forEach((item) => {
      const sid = String(item?.session_id || "");
      if (!sid) return;
      const isCustomTitle = Boolean(item?.has_custom_title);
      const sessionTitle = String(item?.title || "新会话");

      const row = document.createElement("div");
      row.className = "session-history-row";

      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.className = "session-history-item";
      if (sid === state.sessionId) openBtn.classList.add("active");

      const title = document.createElement("div");
      title.className = "session-history-title";
      title.textContent = sessionTitle;
      if (isCustomTitle) {
        title.title = "已使用自定义会话名";
      }
      openBtn.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "session-history-meta";
      meta.textContent = `turns ${item?.turn_count || 0} · ${formatSessionTime(item?.updated_at)}`;
      openBtn.appendChild(meta);

      const preview = String(item?.preview || "").trim();
      if (preview) {
        const previewNode = document.createElement("div");
        previewNode.className = "session-history-preview";
        previewNode.textContent = preview;
        openBtn.appendChild(previewNode);
      }

      openBtn.addEventListener("click", async () => {
        await loadSessionById(sid, { announceMode: "switch" });
        setSidebarSessionsOpen(false);
      });

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "session-history-rename";
      renameBtn.textContent = "改名";
      renameBtn.title = "自定义会话标题（留空恢复自动标题）";
      renameBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        await renameSessionById(sid, sessionTitle);
      });

      row.appendChild(openBtn);
      row.appendChild(renameBtn);
      sessionHistoryView.appendChild(row);
    });
    return sessions;
  } catch {
    sessionHistoryView.textContent = "历史会话加载失败";
    return [];
  }
}

async function renameSessionById(sessionId, currentTitle = "") {
  const sid = String(sessionId || "").trim();
  if (!sid) return;

  const raw = window.prompt("请输入新的会话名称（留空恢复自动标题）", String(currentTitle || ""));
  if (raw === null) return;

  const title = String(raw || "").trim().slice(0, 120);
  try {
    const res = await fetch(`/api/session/${encodeURIComponent(sid)}/title`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!res.ok) {
      let detail = `改名失败: ${res.status}`;
      try {
        const data = await res.json();
        if (data?.detail) detail = `改名失败: ${data.detail}`;
      } catch {}
      throw new Error(detail);
    }

    await refreshSessionHistory();
    addBubble("system", title ? `会话已改名：${title}` : "已清除自定义会话名，恢复自动标题。");
  } catch (err) {
    addBubble("system", String(err));
  }
}

async function deleteSessionById(sessionId) {
  const sid = String(sessionId || "").trim();
  if (!sid) return;
  const yes = window.confirm(`确认删除这个会话吗？\n${sid}\n删除后无法恢复。`);
  if (!yes) return;

  try {
    const res = await fetch(`/api/session/${encodeURIComponent(sid)}`, { method: "DELETE" });
    if (!res.ok) {
      let detail = `删除失败: ${res.status}`;
      try {
        const data = await res.json();
        if (data?.detail) detail = `删除失败: ${data.detail}`;
      } catch {}
      throw new Error(detail);
    }

    const deletingCurrent = sid === state.sessionId;
    if (deletingCurrent) {
      state.sessionId = null;
      refreshSession();
      clearChat();
    }

    const sessions = await refreshSessionHistory();
    if (deletingCurrent) {
      if (Array.isArray(sessions) && sessions.length) {
        await loadSessionById(String(sessions[0].session_id || ""), { announceMode: "switch" });
      } else {
        addBubble("system", `会话已删除：${sid}。当前无历史会话。`);
      }
    } else {
      addBubble("system", `会话已删除：${sid}`);
    }
  } catch (err) {
    addBubble("system", String(err));
  }
}

async function loadSessionById(sessionId, { announceMode = "none" } = {}) {
  const sid = String(sessionId || "").trim();
  if (!sid) return false;

  state.sessionId = sid;
  refreshSession();

  try {
    const res = await fetch(`/api/session/${encodeURIComponent(sid)}?max_turns=120`);
    if (!res.ok) {
      if (res.status === 404) {
        state.sessionId = null;
        refreshSession();
      }
      await refreshSessionHistory();
      return false;
    }
    const data = await res.json();
    const turns = Array.isArray(data?.turns) ? data.turns : [];
    clearChat();
    if (announceMode === "restore") {
      addBubble("system", `已恢复会话：${sid}（历史 ${data?.turn_count || turns.length} 条）`);
    } else if (announceMode === "switch") {
      addBubble("system", `已切换会话：${sid}（历史 ${data?.turn_count || turns.length} 条）`);
    }
    turns.forEach((turn) => {
      const role = turn?.role === "assistant" ? "assistant" : "user";
      const text = String(turn?.text || "").trim();
      if (text) addBubble(role, text, role === "assistant" ? turn?.answer_bundle || null : null);
    });
    await refreshTokenStatsFromServer();
    await refreshSessionHistory();
    return true;
  } catch {
    await refreshSessionHistory();
    return false;
  }
}

async function restoreSessionIfPossible() {
  const cached = getStoredSessionId();
  if (!cached) return false;
  return loadSessionById(cached, { announceMode: "restore" });
}

function renderRunSteps(activeStepId, isError = false) {
  if (!runStepList) return;

  const activeIndex = RUN_FLOW_STEPS.findIndex((step) => step.id === String(activeStepId || "").trim());
  runStepList.innerHTML = "";

  RUN_FLOW_STEPS.forEach((step, index) => {
    const node = document.createElement("div");
    node.className = "runtime-step";
    if (activeIndex >= 0 && index < activeIndex) {
      node.classList.add("is-done");
    }
    if (activeIndex === index) {
      node.classList.add(isError ? "is-error" : "is-active");
    }
    node.textContent = step.label;
    runStepList.appendChild(node);
  });
}

function setRunStage(stageLabel, text, stepId = null, tone = "idle") {
  currentRunStepId = String(stepId || "").trim() || null;
  currentRunTone = String(tone || "idle").trim() || "idle";
  if (runStageBadge) {
    runStageBadge.textContent = stageLabel;
    runStageBadge.className = `stage-badge stage-${tone}`;
  }
  if (runStageText) {
    runStageText.textContent = text;
  }
  renderRunSteps(currentRunStepId, currentRunTone === "error");
}

function formatJsonPreview(value, maxChars = 10000) {
  const raw = JSON.stringify(value, null, 2);
  if (raw.length <= maxChars) return raw;
  return `${raw.slice(0, maxChars)}\n\n...[truncated ${raw.length - maxChars} chars]`;
}

function formatBytes(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB"];
  let idx = 0;
  let cur = num;
  while (cur >= 1024 && idx < units.length - 1) {
    cur /= 1024;
    idx += 1;
  }
  if (idx === 0) return `${Math.round(cur)} ${units[idx]}`;
  return `${cur.toFixed(2)} ${units[idx]}`;
}

function startWaitStageTicker(totalAttachmentBytes = 0) {
  const startedAt = Date.now();
  const sizeHint =
    totalAttachmentBytes > 0 ? `（附件总大小 ${formatBytes(totalAttachmentBytes)}）` : "";
  let notifiedSlow = false;

  const update = () => {
    const elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    let text = `模型处理中，已等待 ${elapsedSec}s${sizeHint}`;
    if (elapsedSec >= 60) {
      text = `仍在处理中，已等待 ${elapsedSec}s${sizeHint}。大文件分析通常会更久。`;
    } else if (elapsedSec >= 20) {
      text = `处理中（可能在读取附件/执行工具），已等待 ${elapsedSec}s${sizeHint}`;
    }
    setRunStage("进行中", text, "wait", "working");
    if (!notifiedSlow && elapsedSec >= 45) {
      notifiedSlow = true;
      renderRunTrace(
        [
          "请求已发送，后端仍在处理中。",
          "如果本轮包含大文件，模型会分段读取并分析，耗时会明显增加。",
        ],
        []
      );
    }
  };

  update();
  const timer = window.setInterval(update, 1000);
  return () => window.clearInterval(timer);
}

function parseSseEventBlock(rawBlock) {
  const block = String(rawBlock || "").trim();
  if (!block) return null;
  const lines = block.split("\n");
  let event = "message";
  const dataLines = [];
  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim() || "message";
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });
  if (!dataLines.length) return null;
  const rawData = dataLines.join("\n");
  let data = rawData;
  try {
    data = JSON.parse(rawData);
  } catch {}
  return { event, data };
}

async function streamChatRequest(body, handlers = {}) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) detail = String(data.detail);
    } catch {}
    throw new Error(detail);
  }

  const contentType = String(res.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes("text/event-stream") || !res.body) {
    return await res.json();
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalResponse = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    while (true) {
      const splitAt = buffer.indexOf("\n\n");
      if (splitAt < 0) break;
      const block = buffer.slice(0, splitAt);
      buffer = buffer.slice(splitAt + 2);
      const parsed = parseSseEventBlock(block);
      if (!parsed) continue;

      const event = parsed.event;
      const payload = parsed.data && typeof parsed.data === "object" ? parsed.data : { detail: String(parsed.data || "") };

      if (event === "stage") {
        handlers.onStage?.(payload);
        continue;
      }
      if (event === "trace") {
        handlers.onTrace?.(payload);
        continue;
      }
      if (event === "debug") {
        handlers.onDebug?.(payload);
        continue;
      }
      if (event === "tool_event") {
        handlers.onToolEvent?.(payload);
        continue;
      }
      if (event === "agent_state") {
        handlers.onAgentState?.(payload);
        continue;
      }
      if (event === "heartbeat") {
        handlers.onHeartbeat?.(payload);
        continue;
      }
      if (event === "error") {
        throw new Error(String(payload?.detail || "stream error"));
      }
      if (event === "final") {
        finalResponse = payload?.response || null;
        handlers.onFinal?.(finalResponse);
        continue;
      }
      if (event === "done") {
        return finalResponse;
      }
    }
  }

  if (finalResponse) return finalResponse;
  throw new Error("流式响应中断：未收到最终结果。");
}

function applyBackendStage(payload) {
  const code = String(payload?.code || "").trim();
  const detail = String(payload?.detail || "").trim();
  if (!code) return;
  pushExecutionLogEntry({
    category: classifyExecutionText(`${code} ${detail}`, "system"),
    title: `Stage · ${code}`,
    detail: detail || code,
    tags: [code],
  });

  if (code === "backend_start" || code === "session_ready" || code === "attachments_ready") {
    setRunStage("进行中", detail || "后端处理中", "prepare", "working");
    return;
  }
  if (code === "agent_run_start") {
    setRunStage("进行中", detail || "模型推理中", "wait", "working");
    return;
  }
  if (code === "agent_run_done" || code === "session_saved" || code === "stats_saved" || code === "ready") {
    setRunStage("进行中", detail || "后处理中", "parse", "working");
  }
}

function renderRunPayload(body, attachmentNames) {
  if (!runPayloadView) return;
  const settings = body?.settings || {};
  const header = [
    `session_id: ${body?.session_id || "(new session)"}`,
    `message_chars: ${String(body?.message || "").length}`,
    `attachments: ${attachmentNames.length ? attachmentNames.join("，") : "(none)"}`,
    `model: ${settings.model || "(default)"}`,
    `max_output_tokens: ${settings.max_output_tokens}`,
    `max_context_turns: ${settings.max_context_turns}`,
    `enable_tools: ${settings.enable_tools}`,
    `execution_mode: ${settings.execution_mode || "(backend default)"}`,
    `debug_raw: ${settings.debug_raw}`,
    `response_style: ${settings.response_style}`,
    "",
    "payload json:",
  ];
  runPayloadView.textContent = `${header.join("\n")}\n${formatJsonPreview(body)}`;
}

function renderRunTrace(traceItems = [], toolEvents = []) {
  if (!runTraceView) return;

  const lines = [];
  if (Array.isArray(traceItems) && traceItems.length) {
    traceItems.forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
  } else {
    lines.push("暂无执行轨迹");
  }

  if (Array.isArray(toolEvents) && toolEvents.length) {
    lines.push("");
    lines.push("工具调用:");
    toolEvents.forEach((tool, idx) => {
      const args = tool?.input ? JSON.stringify(tool.input) : "{}";
      const moduleBits = [];
      if (String(tool?.module_id || "").trim()) moduleBits.push(String(tool.module_id).trim());
      if (String(tool?.module_group || "").trim()) moduleBits.push(String(tool.module_group).trim());
      const moduleSuffix = moduleBits.length ? ` <${moduleBits.join(" / ")}>` : "";
      let modeSuffix = "";
      try {
        const raw = String(tool?.output_preview || "").trim();
        if (raw.startsWith("{")) {
          const parsed = JSON.parse(raw);
          const mode = String(parsed?.execution_mode || "").trim().toLowerCase();
          if (mode === "host" || mode === "docker") {
            modeSuffix = ` [${mode}]`;
          }
        }
      } catch {}
      lines.push(`${idx + 1}. ${tool?.name || "unknown"}${moduleSuffix}(${args})${modeSuffix}`);
    });
  }

  runTraceView.textContent = lines.join("\n");
}

function renderAgentPanels(panels = [], plan = [], activeRoles = new Set(), currentRole = null, roleStates = new Map()) {
  state.latestAgentPanels = Array.isArray(panels) ? panels : [];
  state.latestExecutionPlan = Array.isArray(plan) ? plan : [];
  state.latestActiveRoles = activeRoles instanceof Set ? activeRoles : new Set();
  state.latestCurrentRole = currentRole || null;
  state.latestRoleStates = roleStates instanceof Map ? roleStates : new Map();
  renderRoleBoard(panels, activeRoles, currentRole, roleStates);
  renderExecutionDag();
  if (!runAgentPanelsView) return;

  const lines = [];
  const specialistRoles = new Set(["researcher", "file_reader", "summarizer", "fixer"]);
  if (Array.isArray(plan) && plan.length) {
    lines.push("Execution Plan:");
    plan.forEach((item, idx) => {
      lines.push(`${idx + 1}. ${String(item || "")}`);
    });
    lines.push("");
  }

  if (Array.isArray(panels) && panels.length) {
    const fixedPanels = [];
    const dynamicPanels = [];
    panels.forEach((panel, idx) => {
      const role = String(panel?.role || `agent_${idx + 1}`);
      if (specialistRoles.has(role)) {
        dynamicPanels.push({ panel, idx });
      } else {
        fixedPanels.push({ panel, idx });
      }
    });

    lines.push("Core Roles:");
    if (!fixedPanels.length) {
      lines.push("(none)");
    }
    fixedPanels.forEach(({ panel, idx }) => {
      const role = String(panel?.role || `agent_${idx + 1}`);
      const title = String(panel?.title || role);
      const kind = normalizeRoleKind(panel?.kind, "agent");
      const summary = String(panel?.summary || "").trim();
      const bullets = Array.isArray(panel?.bullets) ? panel.bullets : [];
      lines.push(`[${idx + 1}] ${title} (${role}, ${kind})`);
      if (summary) lines.push(summary);
      bullets.forEach((item) => lines.push(`- ${String(item || "")}`));
      lines.push("");
    });

    lines.push("Specialist Roles:");
    if (!dynamicPanels.length) {
      lines.push("(none this run)");
      lines.push("");
    } else {
      dynamicPanels.forEach(({ panel, idx }) => {
        const role = String(panel?.role || `agent_${idx + 1}`);
        const title = String(panel?.title || role);
        const kind = normalizeRoleKind(panel?.kind, "agent");
        const summary = String(panel?.summary || "").trim();
        const bullets = Array.isArray(panel?.bullets) ? panel.bullets : [];
        lines.push(`[${idx + 1}] ${title} (${role}, ${kind})`);
        if (summary) lines.push(summary);
        bullets.forEach((item) => lines.push(`- ${String(item || "")}`));
        lines.push("");
      });
    }
  }

  if (!lines.length) {
    runAgentPanelsView.textContent = "暂无多 Role 摘要";
    return;
  }
  runAgentPanelsView.textContent = lines.join("\n").trim();
}

function renderAnswerBundle(bundle = {}) {
  if (!runAnswerBundleView) return;
  if (!hasAnswerBundleContent(bundle)) {
    runAnswerBundleView.textContent = "暂无结构化证据包";
    return;
  }

  const lines = [];
  const summary = String(bundle?.summary || "").trim();
  if (summary) {
    lines.push(`summary: ${summary}`);
    lines.push("");
  }

  const claims = Array.isArray(bundle?.claims) ? bundle.claims : [];
  if (claims.length) {
    lines.push("assertions（关键结论）:");
    claims.slice(0, 5).forEach((claim, idx) => {
      const ids = Array.isArray(claim?.citation_ids) ? claim.citation_ids.join(", ") : "";
      lines.push(`${idx + 1}. ${String(claim?.statement || "").trim()}`);
      lines.push(
        `   status=${String(claim?.status || "supported")} confidence=${String(claim?.confidence || "medium")} citations（证据来源）=${ids || "(none)"}`
      );
    });
    lines.push("");
  }

  const citations = Array.isArray(bundle?.citations) ? bundle.citations : [];
  const { evidence, candidates } = partitionAnswerCitations(citations);
  const appendCitationLines = (title, items, note = "") => {
    if (!items.length) return;
    lines.push(`${title}:`);
    if (note) lines.push(`- note: ${note}`);
    items.slice(0, 8).forEach((citation) => {
      lines.push(`- ${String(citation?.id || "-")} | ${String(citation?.tool || "")} | ${String(citation?.label || citation?.title || citation?.url || citation?.path || "")}`);
      if (citation?.locator) lines.push(`  locator: ${citation.locator}`);
      if (citation?.domain) lines.push(`  domain: ${citation.domain}`);
      if (citation?.published_at) lines.push(`  published_at: ${citation.published_at}`);
      if (citation?.url) lines.push(`  url: ${citation.url}`);
      if (citation?.path) lines.push(`  path: ${citation.path}`);
      if (citation?.excerpt) lines.push(`  excerpt: ${String(citation.excerpt).trim()}`);
      if (citation?.warning) lines.push(`  warning（风险提示）: ${citation.warning}`);
    });
    lines.push("");
  };
  appendCitationLines("citations（证据来源）", evidence);
  appendCitationLines("search_candidates（候选来源）", candidates, "候选链接，尚未抓取正文");

  const warnings = Array.isArray(bundle?.warnings) ? bundle.warnings : [];
  if (warnings.length) {
    lines.push("warnings（风险提示）:");
    warnings.slice(0, 5).forEach((warning, idx) => lines.push(`${idx + 1}. ${String(warning || "")}`));
  }

  runAnswerBundleView.textContent = lines.join("\n").trim();
}

function renderLlmFlow(items = []) {
  if (!runLlmFlowView) return;
  if (!Array.isArray(items) || !items.length) {
    runLlmFlowView.textContent = "暂无交换记录";
    return;
  }

  const lines = [];
  items.forEach((item, idx) => {
    const step = item?.step ?? idx + 1;
    const stage = item?.stage || "unknown";
    const stageLabel = LLM_FLOW_STAGE_LABELS[stage] || stage;
    const title = item?.title || "未命名步骤";
    const detail = item?.detail || "";
    lines.push(`[${step}] ${title} (${stageLabel})`);
    lines.push(detail);
    lines.push("");
  });

  runLlmFlowView.textContent = lines.join("\n").trim();
}

function formatUsd(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num <= 0) return "0.000000";
  return num.toFixed(6);
}

function formatPrice(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(2);
}

function renderTokenStats(payload) {
  if (!tokenStatsView) return;
  const last = payload?.last || {};
  const session = payload?.session || {};
  const global = payload?.global || {};
  const pricingLine = last.pricing_known
    ? `计费模型: ${last.pricing_model || "-"} (in $${formatPrice(last.input_price_per_1m)}/1M, out $${formatPrice(last.output_price_per_1m)}/1M)`
    : `计费模型: ${last.pricing_model || "-"} (未匹配价格表，仅统计 token)`;
  tokenStatsView.textContent =
    `请求: ${global.requests || 0}\n` +
    `说明: 输入=你发给模型的 tokens，输出=模型回复的 tokens\n` +
    `本轮: in ${last.input_tokens || 0} / out ${last.output_tokens || 0} / total ${last.total_tokens || 0}\n` +
    `本轮费用(USD): ${formatUsd(last.estimated_cost_usd)}\n` +
    `${pricingLine}\n` +
    `本会话累计: req ${session.requests || 0} / total ${session.total_tokens || 0}\n` +
    `本会话累计费用(USD): ${formatUsd(session.estimated_cost_usd)}\n` +
    `全局累计: req ${global.requests || 0} / total ${global.total_tokens || 0}\n` +
    `全局累计费用(USD): ${formatUsd(global.estimated_cost_usd)}`;
}

async function refreshTokenStatsFromServer() {
  if (!tokenStatsView) return;
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const data = await res.json();
    const sessionTotals = state.sessionId ? (data.sessions?.[state.sessionId] || {}) : {};
    renderTokenStats({
      last: {},
      session: sessionTotals,
      global: data.totals || {},
    });
  } catch {}
}

function refreshFileList() {
  fileList.innerHTML = "";
  state.attachments.forEach((att, idx) => {
    const chip = document.createElement("div");
    chip.className = "file-chip";
    chip.innerHTML = `<span>${att.name}</span>`;

    const removeBtn = document.createElement("button");
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      state.attachments.splice(idx, 1);
      refreshFileList();
    });
    chip.appendChild(removeBtn);

    fileList.appendChild(chip);
  });
}

function inferFileExtensionFromMime(mime) {
  const raw = String(mime || "").toLowerCase();
  if (raw.includes("png")) return "png";
  if (raw.includes("jpeg") || raw.includes("jpg")) return "jpg";
  if (raw.includes("webp")) return "webp";
  if (raw.includes("gif")) return "gif";
  if (raw.includes("bmp")) return "bmp";
  if (raw.includes("heic")) return "heic";
  return "png";
}

function buildClipboardImageName(file, index = 0) {
  const now = new Date();
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
    String(now.getSeconds()).padStart(2, "0"),
  ].join("");
  const ext = inferFileExtensionFromMime(file?.type);
  const suffix = index > 0 ? `-${index + 1}` : "";
  return `clipboard-image-${stamp}${suffix}.${ext}`;
}

function resolveUploadFileName(file, index = 0) {
  const raw = String(file?.name || "").trim();
  if (raw) return raw;
  return buildClipboardImageName(file, index);
}

function extractPastedImageFiles(event) {
  const clipboard = event?.clipboardData;
  if (!clipboard) return [];

  const files = Array.from(clipboard.files || []).filter((file) =>
    String(file?.type || "").toLowerCase().startsWith("image/")
  );
  if (files.length) return files;

  const items = Array.from(clipboard.items || []);
  const fromItems = [];
  items.forEach((item) => {
    if (String(item?.kind || "").toLowerCase() !== "file") return;
    if (!String(item?.type || "").toLowerCase().startsWith("image/")) return;
    const file = item.getAsFile();
    if (file) fromItems.push(file);
  });
  return fromItems;
}

function clipboardLooksLikeTableText(clipboard) {
  if (!clipboard || typeof clipboard.getData !== "function") return false;
  const plain = String(clipboard.getData("text/plain") || "");
  const html = String(clipboard.getData("text/html") || "").toLowerCase();
  if (html && (html.includes("<table") || html.includes("mso-"))) return true;
  if (!plain.trim()) return false;
  const lines = plain.split(/\r?\n/).filter((line) => String(line || "").trim());
  return plain.includes("\t") && lines.length >= 1;
}

async function createSession() {
  const res = await fetch("/api/session/new", { method: "POST" });
  if (!res.ok) throw new Error(`create session failed: ${res.status}`);
  const data = await res.json();
  state.sessionId = data.session_id;
  refreshSession();
  await refreshTokenStatsFromServer();
  await refreshSessionHistory();
}

async function uploadSingle(file, fileName = "") {
  const form = new FormData();
  const safeName = String(fileName || file?.name || "upload.bin").trim() || "upload.bin";
  form.append("file", file, safeName);

  const res = await fetch("/api/upload", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`上传失败 ${safeName}: ${res.status} ${text}`);
  }
  return res.json();
}

async function handleFiles(files) {
  if (!files || !files.length) return;
  const preparedFiles = Array.from(files)
    .map((file, idx) => ({
      file,
      name: resolveUploadFileName(file, idx),
    }))
    .filter((item) => item.file instanceof Blob);
  if (!preparedFiles.length) return;

  state.uploading = true;
  updateSendAvailability();
  addBubble("system", `正在上传 ${preparedFiles.length} 个文件...`);

  try {
    for (const item of preparedFiles) {
      const uploaded = await uploadSingle(item.file, item.name);
      state.attachments.push(uploaded);
    }
    refreshFileList();
    const names = state.attachments.map((x) => x.name).join("，");
    addBubble("system", `上传完成，共 ${preparedFiles.length} 个文件。\n当前附件：${names}`);
  } catch (err) {
    addBubble("system", String(err));
  } finally {
    state.uploading = false;
    updateSendAvailability();
    fileInput.value = "";
  }
}

function getSettings() {
  const mode = String(execModeInput?.value || "").trim().toLowerCase();
  return {
    model: modelInput.value.trim() || null,
    max_output_tokens: Number(tokenInput.value || 128000),
    max_context_turns: Number(ctxInput.value || 2000),
    enable_tools: toolInput.checked,
    execution_mode: mode === "host" || mode === "docker" ? mode : null,
    debug_raw: Boolean(rawDebugInput?.checked),
    response_style: styleInput.value,
  };
}

async function runSandboxDrill() {
  if (state.drilling) return;

  const settings = getSettings();
  const payload = {
    execution_mode: settings.execution_mode || null,
  };
  const modeLabel = payload.execution_mode || "(backend default)";

  state.drilling = true;
  updateDrillAvailability();
  clearExecutionLog();
  pushExecutionLogEntry({
    category: "system",
    title: "Sandbox Drill",
    detail: `开始沙盒演练，execution_mode=${modeLabel}`,
    tags: ["sandbox", modeLabel],
  });
  setRunStage("进行中", `开始沙盒演练，执行环境 ${modeLabel}`, "prepare", "working");
  if (runPayloadView) {
    runPayloadView.textContent = `sandbox drill payload:\n${formatJsonPreview(payload)}`;
  }
  renderRunTrace(["沙盒演练请求已发送。"], []);
  renderAgentPanels([], [], new Set(), null, new Map());
  renderAnswerBundle({});
  renderLlmFlow([
    {
      step: 1,
      stage: "frontend_prepare",
      title: "前端发起沙盒演练",
      detail: `POST /api/sandbox/drill\nexecution_mode=${modeLabel}`,
    },
  ]);

  try {
    const res = await fetch("/api/sandbox/drill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        if (data?.detail) detail = String(data.detail);
      } catch {}
      throw new Error(detail);
    }

    const data = await res.json();
    const steps = Array.isArray(data?.steps) ? data.steps : [];
    const trace = [
      `run_id: ${data?.run_id || "-"}`,
      `execution_mode: ${data?.execution_mode || "-"}`,
      `summary: ${data?.summary || "-"}`,
      "",
      "steps:",
    ];
    steps.forEach((step, idx) => {
      const okText = step?.ok ? "OK" : "FAIL";
      const ms = Number(step?.duration_ms || 0);
      trace.push(
        `${idx + 1}. [${okText}] ${step?.name || "unnamed"} (${ms} ms) - ${String(step?.detail || "")}`
      );
    });
    renderRunTrace(trace, []);
    pushExecutionLogEntry({
      category: data?.ok ? "tool" : "system",
      title: "Sandbox Drill Result",
      detail: String(data?.summary || "沙盒演练完成"),
      tags: [data?.ok ? "pass" : "fail", `steps=${steps.length}`],
    });
    renderAgentPanels([], [], new Set(), null, new Map());
    renderAnswerBundle({});
    renderLlmFlow([
      {
        step: 1,
        stage: data?.ok ? "backend_tool" : "backend_warning",
        title: "沙盒演练结果",
        detail: formatJsonPreview(data),
      },
    ]);

    if (data?.ok) {
      setRunStage("完成", data?.summary || "沙盒演练通过", "done", "done");
      addBubble("system", `沙盒演练通过。\n${data?.summary || ""}`);
    } else {
      const failedNames = steps
        .filter((step) => !step?.ok)
        .map((step) => String(step?.name || "").trim())
        .filter(Boolean);
      setRunStage("失败", data?.summary || "沙盒演练失败", "parse", "error");
      addBubble(
        "system",
        `沙盒演练失败。\n${data?.summary || ""}${
          failedNames.length ? `\n失败步骤：${failedNames.join("，")}` : ""
        }`
      );
    }
  } catch (err) {
    const msg = `沙盒演练请求失败: ${String(err)}`;
    pushExecutionLogEntry({
      category: "system",
      title: "Sandbox Drill Error",
      detail: msg,
      tags: ["error"],
    });
    renderRunTrace([msg], []);
    renderAgentPanels([], [], new Set(), null, new Map());
    renderAnswerBundle({});
    renderLlmFlow([
      {
        step: 1,
        stage: "frontend_error",
        title: "沙盒演练失败",
        detail: msg,
      },
    ]);
    setRunStage("失败", "沙盒演练失败，请检查错误信息", "parse", "error");
    addBubble("system", msg);
  } finally {
    state.drilling = false;
    updateDrillAvailability();
  }
}

function summarizeEvalResult(item) {
  const name = String(item?.name || "unnamed");
  const kind = String(item?.kind || "tool");
  const status = String(item?.status || "unknown").toUpperCase();
  const elapsed = Number(item?.payload?.elapsed_sec || 0);
  const suffix = elapsed > 0 ? ` (${elapsed.toFixed(3)}s)` : "";
  if (item?.status === "failed") {
    const errors = Array.isArray(item?.errors) ? item.errors : [];
    return `[${status}] ${name} [${kind}]${suffix} - ${errors.join("; ") || "unknown error"}`;
  }
  if (item?.status === "skipped") {
    return `[${status}] ${name} [${kind}] - ${String(item?.reason || "")}`;
  }
  return `[${status}] ${name} [${kind}]${suffix}`;
}

async function runEvalHarness() {
  if (state.evaluating) return;

  const payload = {
    include_optional: false,
    name_filter: "",
  };

  state.evaluating = true;
  updateEvalAvailability();
  clearExecutionLog();
  pushExecutionLogEntry({
    category: "system",
    title: "Eval Harness",
    detail: "开始执行默认回归测试集。",
    tags: ["eval", "gate"],
  });
  setRunStage("进行中", "开始回归测试（默认非 optional 用例）", "prepare", "working");
  if (runPayloadView) {
    runPayloadView.textContent = `eval harness payload:\n${formatJsonPreview(payload)}`;
  }
  renderRunTrace(["回归测试请求已发送。"], []);
  renderAgentPanels([], [], new Set(), null, new Map());
  renderAnswerBundle({});
  renderLlmFlow([
    {
      step: 1,
      stage: "frontend_prepare",
      title: "前端发起回归测试",
      detail: "POST /api/evals/run\ninclude_optional=false",
    },
  ]);

  try {
    const res = await fetch("/api/evals/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        if (data?.detail) detail = String(data.detail);
      } catch {}
      throw new Error(detail);
    }

    const data = await res.json();
    const results = Array.isArray(data?.results) ? data.results : [];
    const failed = results.filter((item) => item?.status === "failed");
    const skipped = results.filter((item) => item?.status === "skipped");
    const trace = [
      `run_id: ${data?.run_id || "-"}`,
      `summary: ${data?.summary || "-"}`,
      `duration_ms: ${Number(data?.duration_ms || 0)}`,
      `cases_path: ${data?.cases_path || "-"}`,
      "",
      "results:",
      ...results.map((item) => summarizeEvalResult(item)),
    ];
    renderRunTrace(trace, []);
    pushExecutionLogEntry({
      category: failed.length ? "review" : "system",
      title: "Eval Result",
      detail: String(data?.summary || "回归测试完成"),
      tags: [`passed=${Number(data?.passed || 0)}`, `failed=${failed.length}`, `skipped=${skipped.length}`],
    });

    const panels = [
      {
        role: "eval_harness",
        title: "Regression Evals",
        summary: data?.summary || "回归测试已完成。",
        bullets: [
          `passed=${Number(data?.passed || 0)}`,
          `failed=${Number(data?.failed || 0)}`,
          `skipped=${Number(data?.skipped || 0)}`,
          `total=${Number(data?.total || 0)}`,
        ],
      },
    ];
    if (failed.length) {
      panels.push({
        role: "eval_failures",
        title: "Failed Cases",
        summary: `失败用例 ${failed.length} 个。`,
        bullets: failed.slice(0, 6).map((item) => summarizeEvalResult(item)),
      });
    }
    if (skipped.length) {
      panels.push({
        role: "eval_skips",
        title: "Skipped Cases",
        summary: `跳过用例 ${skipped.length} 个。`,
        bullets: skipped.slice(0, 6).map((item) => summarizeEvalResult(item)),
      });
    }
    renderAgentPanels(panels, [], new Set(), null, new Map());
    renderAnswerBundle({});
    renderLlmFlow([
      {
        step: 1,
        stage: data?.ok ? "backend_tool" : "backend_warning",
        title: "回归测试结果",
        detail: formatJsonPreview(data),
      },
    ]);

    if (data?.ok) {
      setRunStage("完成", data?.summary || "回归测试通过", "done", "done");
      addBubble("system", `${data?.summary || "回归测试通过。"}\n可在运行面板查看逐条用例结果。`);
    } else {
      setRunStage("失败", data?.summary || "回归测试失败", "parse", "error");
      addBubble("system", `${data?.summary || "回归测试失败。"}\n请查看运行面板中的 Failed Cases。`);
    }
  } catch (err) {
    const msg = `回归测试请求失败: ${String(err)}`;
    pushExecutionLogEntry({
      category: "system",
      title: "Eval Error",
      detail: msg,
      tags: ["error"],
    });
    renderRunTrace([msg], []);
    renderAgentPanels([], [], new Set(), null, new Map());
    renderAnswerBundle({});
    renderLlmFlow([
      {
        step: 1,
        stage: "frontend_error",
        title: "回归测试失败",
        detail: msg,
      },
    ]);
    setRunStage("失败", "回归测试失败，请检查错误信息", "parse", "error");
    addBubble("system", msg);
  } finally {
    state.evaluating = false;
    updateEvalAvailability();
    refreshOperationsOverview().catch(() => {});
  }
}

async function sendMessage() {
  const message = messageInput.value.trim();
  if (!message) return;
  setWorkspaceView("chat");
  let requestSessionId = currentSessionKey();
  if (requestSessionId && isSessionSending(requestSessionId)) return;
  let stopWaitTicker = null;
  const isForegroundSession = () => currentSessionKey() === requestSessionId;

  setRunStage("进行中", "正在准备本轮请求参数", "prepare", "working");
  clearExecutionLog();

  if (!requestSessionId) {
    try {
      setRunStage("进行中", "正在创建新会话", "prepare", "working");
      await createSession();
    } catch (err) {
      setRunStage("失败", "创建会话失败，请检查错误信息", "prepare", "error");
      addBubble("system", `创建会话失败: ${String(err)}`);
      return;
    }
    requestSessionId = currentSessionKey();
  }
  if (!requestSessionId) {
    setRunStage("失败", "创建会话失败，请重试", "prepare", "error");
    addBubble("system", "创建会话失败，请重试。");
    return;
  }
  if (isSessionSending(requestSessionId)) {
    return;
  }

  addBubble("user", message);
  if (state.attachments.length) {
    const names = state.attachments.map((x) => x.name).join("，");
    addBubble("system", `本轮将携带 ${state.attachments.length} 个附件：${names}`);
  }
  messageInput.value = "";
  state.sendingSessionIds.add(requestSessionId);
  updateSendAvailability();

  try {
    const body = {
      session_id: requestSessionId,
      message,
      attachment_ids: state.attachments.map((x) => x.id),
      settings: getSettings(),
    };
    pushExecutionLogEntry({
      category: "planning",
      title: "Request Prepared",
      detail: `session=${requestSessionId} · chars=${message.length} · attachments=${state.attachments.length}`,
      tags: [
        body?.settings?.model || "default-model",
        body?.settings?.execution_mode || "backend-default",
        body?.settings?.enable_tools ? "tools-on" : "tools-off",
      ],
    });
    renderRunPayload(
      body,
      state.attachments.map((x) => x.name)
    );
    const liveTrace = ["客户端已组装请求，等待发送。"];
    const liveToolEvents = [];
    let liveExecutionPlan = [];
    let liveAgentPanels = [];
    let liveActiveRoles = new Set();
    let liveRoleStates = new Map();
    const liveFlow = [
      {
        step: 1,
        stage: "frontend_prepare",
        title: "前端准备请求",
        detail: "已生成 payload，正在调用 /api/chat/stream",
      },
    ];
    let heartbeatCount = 0;
    renderRunTrace(liveTrace, liveToolEvents);
    renderAgentPanels([], [], liveActiveRoles, null, liveRoleStates);
    renderAnswerBundle({});
    renderLlmFlow(liveFlow);
    setRunStage("进行中", "请求已发往后端，等待模型处理", "send", "working");
    const totalAttachmentBytes = state.attachments.reduce((sum, item) => {
      const size = Number(item?.size || 0);
      return sum + (Number.isFinite(size) ? size : 0);
    }, 0);
    stopWaitTicker = startWaitStageTicker(totalAttachmentBytes);
    const data = await streamChatRequest(body, {
      onStage: (payload) => {
        if (!isForegroundSession()) return;
        const code = String(payload?.code || "");
        if (
          typeof stopWaitTicker === "function" &&
          (code === "agent_run_done" || code === "session_saved" || code === "stats_saved" || code === "ready")
        ) {
          stopWaitTicker();
          stopWaitTicker = null;
        }
        applyBackendStage(payload);
      },
      onTrace: (payload) => {
        if (!isForegroundSession()) return;
        const line = String(payload?.message || "").trim();
        if (!line) return;
        pushExecutionLogEntry({
          category: classifyExecutionText(line, "system"),
          title: "Trace",
          detail: line,
        });
        liveTrace.push(line);
        renderRunTrace(liveTrace, liveToolEvents);
      },
      onDebug: (payload) => {
        if (!isForegroundSession()) return;
        const item = payload?.item;
        if (!item || typeof item !== "object") return;
        pushExecutionLogEntry({
          category: classifyExecutionText(`${item?.stage || ""} ${item?.title || ""} ${item?.detail || ""}`, "planning"),
          title: String(item?.title || item?.stage || "Debug Event"),
          detail: String(item?.detail || "").trim() || String(item?.stage || "").trim(),
          tags: [String(item?.stage || "").trim()].filter(Boolean),
        });
        liveFlow.push(item);
        if (!liveActiveRoles.size) {
          liveActiveRoles = inferActiveRolesFromDebugItem(item);
          renderRoleBoard(liveAgentPanels, liveActiveRoles, null, liveRoleStates);
        }
        renderLlmFlow(liveFlow);
      },
      onToolEvent: (payload) => {
        if (!isForegroundSession()) return;
        const item = payload?.item;
        if (!item || typeof item !== "object") return;
        pushExecutionLogEntry({
          category: "tool",
          title: String(item?.name || "Tool Event"),
          detail: String(item?.output_preview || item?.detail || "工具事件已记录。").trim(),
          tags: [
            String(item?.module_id || "").trim(),
            String(item?.module_group || "").trim(),
          ].filter(Boolean),
        });
        liveToolEvents.push(item);
        renderRunTrace(liveTrace, liveToolEvents);
      },
      onAgentState: (payload) => {
        if (!isForegroundSession()) return;
        liveExecutionPlan = Array.isArray(payload?.execution_plan) ? payload.execution_plan : liveExecutionPlan;
        liveAgentPanels = Array.isArray(payload?.panels) ? payload.panels : liveAgentPanels;
        liveActiveRoles = normalizeRoleSet(payload?.active_roles);
        const liveCurrentRole = normalizeRoleId(payload?.current_role);
        liveRoleStates = normalizeRoleStateMap(payload?.role_states);
        if (liveCurrentRole) liveActiveRoles.add(liveCurrentRole);
        pushExecutionLogEntry({
          category: classifyExecutionText(`${liveCurrentRole} ${(liveExecutionPlan || []).join(" ")}`, "planning"),
          title: liveCurrentRole ? `Role State · ${liveCurrentRole}` : "Role State",
          detail: liveExecutionPlan.length
            ? `execution_plan=${liveExecutionPlan.join(" | ")}`
            : "已收到最新角色状态。",
          tags: Array.from(liveActiveRoles).slice(0, 4),
        });
        renderAgentPanels(liveAgentPanels, liveExecutionPlan, liveActiveRoles, liveCurrentRole || null, liveRoleStates);
      },
      onHeartbeat: () => {
        if (!isForegroundSession()) return;
        heartbeatCount += 1;
        pushExecutionLogEntry({
          category: "system",
          title: "Heartbeat",
          detail: `连接正常，后端仍在处理中（约 ${heartbeatCount * 10}s 无新事件）。`,
          tags: ["heartbeat"],
        });
        if (heartbeatCount === 1 || heartbeatCount % 3 === 0) {
          liveTrace.push(
            `后端心跳：仍在处理中（约 ${heartbeatCount * 10}s 无新事件，连接正常）`
          );
          renderRunTrace(liveTrace, liveToolEvents);
        }
      },
      onFinal: (payload) => {
        if (!isForegroundSession() || !payload || typeof payload !== "object") return;
        pushExecutionLogEntry({
          category: classifyExecutionText(
            `${payload?.selected_business_module || ""} ${payload?.kernel_routing?.selection_summary || ""} ${payload?.business_result?.result_grade || ""}`,
            "system"
          ),
          title: "Final Response",
          detail:
            String(payload?.kernel_routing?.selection_summary || "").trim() ||
            `module=${String(payload?.selected_business_module || "unknown")}`,
          tags: [
            String(payload?.selected_business_module || "").trim(),
            String(payload?.business_result?.result_grade || "").trim(),
            String(payload?.business_result?.return_strategy || "").trim(),
          ].filter(Boolean),
        });
      },
    });
    if (typeof stopWaitTicker === "function") {
      stopWaitTicker();
      stopWaitTicker = null;
    }
    setRunStage("进行中", "收到最终结果，正在整理展示", "parse", "working");
    if (!data || typeof data !== "object") {
      throw new Error("流式响应异常：未收到最终结果。");
    }

    const responseSessionId = String(data.session_id || requestSessionId);
    if (isForegroundSession()) {
      state.sessionId = responseSessionId;
      refreshSession();
      const selectedModel = String(body?.settings?.model || "").trim();
      const effectiveModel = String(data?.effective_model || "").trim();
      const queueWaitMs = Number(data?.queue_wait_ms || 0);
      if (effectiveModel && (!selectedModel || selectedModel !== effectiveModel)) {
        addBubble("system", `本轮模型自动切换：${selectedModel || "(默认)"} -> ${effectiveModel}`);
      }
      if (queueWaitMs >= 1000) {
        addBubble("system", `本轮排队等待 ${queueWaitMs} ms 后开始执行。`);
      }

      if (data.summarized) {
        addBubble("system", "历史上下文已自动压缩摘要，避免窗口过长。", null);
      }
      if (Array.isArray(data.missing_attachment_ids) && data.missing_attachment_ids.length) {
        addBubble(
          "system",
          `有 ${data.missing_attachment_ids.length} 个附件未找到，请重新上传后重试。\nIDs: ${data.missing_attachment_ids.join(", ")}`,
          null
        );
        const missing = new Set(data.missing_attachment_ids);
        state.attachments = state.attachments.filter((x) => !missing.has(x.id));
        refreshFileList();
      }
      const autoLinkedNames = Array.isArray(data.auto_linked_attachment_names)
        ? data.auto_linked_attachment_names.filter((x) => String(x || "").trim())
        : [];
      if (autoLinkedNames.length) {
        addBubble("system", `已自动关联历史附件：${autoLinkedNames.join("，")}`, null);
      } else if (String(data.attachment_context_mode || "") === "cleared") {
        addBubble("system", "已按你的指令忽略历史附件。", null);
      }

      renderRunTrace(data.execution_trace || [], data.tool_events || []);
      liveActiveRoles = normalizeRoleSet(data.active_roles);
      const finalCurrentRole = normalizeRoleId(data.current_role);
      liveRoleStates = normalizeRoleStateMap(data.role_states);
      renderAgentPanels(data.agent_panels || [], data.execution_plan || [], liveActiveRoles, finalCurrentRole || null, liveRoleStates);
      renderAnswerBundle(data.answer_bundle || {});
      renderLlmFlow(data.debug_flow || []);
      renderBusinessResultSummary(data);
      addBubble("assistant", data.text, data.answer_bundle || null);
    }
    await refreshSessionHistory();
    if (isForegroundSession()) {
      renderTokenStats({
        last: data.token_usage || {},
        session: data.session_token_totals || {},
        global: data.global_token_totals || {},
      });
      await refreshSystemDashboard().catch(() => {});
      setRunStage("完成", "本轮已完成", "done", "done");
    }
  } catch (err) {
    if (typeof stopWaitTicker === "function") {
      stopWaitTicker();
      stopWaitTicker = null;
    }
    pushExecutionLogEntry({
      category: "system",
      title: "Request Error",
      detail: String(err),
      tags: ["error"],
    });
    if (isForegroundSession()) {
      renderRunTrace([`请求失败: ${String(err)}`], []);
      renderAgentPanels([], [], new Set(), null, new Map());
      renderAnswerBundle({});
      renderLlmFlow([
        {
          step: 1,
          stage: "frontend_error",
          title: "前端请求失败",
          detail: String(err),
        },
      ]);
      setRunStage("失败", "请求失败，请检查错误信息", "parse", "error");
      addBubble("system", `请求失败: ${String(err)}`);
    }
  } finally {
    if (typeof stopWaitTicker === "function") {
      stopWaitTicker();
      stopWaitTicker = null;
    }
    state.sendingSessionIds.delete(requestSessionId);
    updateSendAvailability();
  }
}

fileInput.addEventListener("change", (e) => {
  const files = Array.from(e.target.files || []);
  handleFiles(files);
});

["dragenter", "dragover"].forEach((evt) => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((evt) => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("dragging");
  });
});

dropZone.addEventListener("drop", (e) => {
  const files = Array.from(e.dataTransfer?.files || []);
  handleFiles(files);
});

sendBtn.addEventListener("click", sendMessage);

if (panelDebugInput) {
  panelDebugInput.addEventListener("change", () => {
    applyPanelDebugMode(Boolean(panelDebugInput.checked));
  });
}

if (presetGeneralBtn) {
  presetGeneralBtn.addEventListener("click", () => applyModePreset("general"));
}

if (presetCodingBtn) {
  presetCodingBtn.addEventListener("click", () => applyModePreset("coding"));
}

if (runtimeViewModulesBtn) {
  runtimeViewModulesBtn.addEventListener("click", () => setRuntimeViewMode("modules"));
}

if (runtimeViewRolesBtn) {
  runtimeViewRolesBtn.addEventListener("click", () => setRuntimeViewMode("roles"));
}

if (runtimeViewSplitBtn) {
  runtimeViewSplitBtn.addEventListener("click", () => setRuntimeViewMode("split"));
}

workspaceNavButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const target = normalizeWorkspaceView(button.dataset.workspaceTarget);
    setWorkspaceView(target);
  });
});

if (sandboxDrillBtn) {
  sandboxDrillBtn.addEventListener("click", runSandboxDrill);
}

if (evalHarnessBtn) {
  evalHarnessBtn.addEventListener("click", runEvalHarness);
}

messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

document.addEventListener("paste", (e) => {
  const target = e.target;
  const isInputLike =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    Boolean(target && typeof target === "object" && "isContentEditable" in target && target.isContentEditable);
  if (isInputLike && target !== messageInput) return;

  const clipboard = e.clipboardData;
  const imageFiles = extractPastedImageFiles(e);
  if (!imageFiles.length) return;
  if (clipboardLooksLikeTableText(clipboard)) return;

  e.preventDefault();
  handleFiles(imageFiles);
});

newSessionBtn.addEventListener("click", async () => {
  await createSession();
  state.attachments = [];
  refreshFileList();
  clearChat();
  setWorkspaceView("chat");
  setSidebarSessionsOpen(false);
  addBubble("system", "已新建会话。", null);
});

if (clearStatsBtn) {
  clearStatsBtn.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/stats/clear", { method: "POST" });
      if (!res.ok) throw new Error(`clear failed: ${res.status}`);
      await refreshTokenStatsFromServer();
      addBubble("system", "Token 统计已清除。");
    } catch (err) {
      addBubble("system", `清除统计失败: ${String(err)}`);
    }
  });
}

if (executionLogView) {
  executionLogView.addEventListener("scroll", () => {
    const nearBottom =
      executionLogView.scrollHeight - executionLogView.scrollTop - executionLogView.clientHeight < 24;
    state.executionLogAutoScroll = nearBottom;
    if (executionLogAutoBtn) {
      executionLogAutoBtn.textContent = state.executionLogAutoScroll ? "自动滚动中" : "恢复自动滚动";
    }
  });
}

if (executionLogAutoBtn) {
  executionLogAutoBtn.addEventListener("click", () => {
    state.executionLogAutoScroll = !state.executionLogAutoScroll;
    if (state.executionLogAutoScroll && executionLogView) {
      executionLogView.scrollTop = executionLogView.scrollHeight;
    }
    renderExecutionLog();
  });
}

if (commandPaletteBtn) {
  commandPaletteBtn.addEventListener("click", () => openCommandPalette());
}

if (chatInfoToggleBtn) {
  chatInfoToggleBtn.addEventListener("click", () => {
    setWorkspaceView("chat");
    setChatInfoOpen(!state.chatInfoOpen);
  });
}

if (chatInfoCloseBtn) {
  chatInfoCloseBtn.addEventListener("click", () => setChatInfoOpen(false));
}

if (chatInfoBackdrop) {
  chatInfoBackdrop.addEventListener("click", () => setChatInfoOpen(false));
}

if (sidebarSessionsToggleBtn) {
  sidebarSessionsToggleBtn.addEventListener("click", () => {
    setSidebarSessionsOpen(!state.sidebarSessionsOpen);
  });
}

if (commandPalette) {
  commandPalette.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.closePalette === "1") {
      closeCommandPalette();
    }
  });
}

if (commandPaletteInput) {
  commandPaletteInput.addEventListener("input", () => {
    state.commandPaletteQuery = String(commandPaletteInput.value || "");
    state.commandPaletteIndex = 0;
    renderCommandPalette();
  });
  commandPaletteInput.addEventListener("keydown", async (event) => {
    const commands = getVisibleCommandPaletteCommands();
    if (event.key === "ArrowDown") {
      event.preventDefault();
      state.commandPaletteIndex = Math.min(state.commandPaletteIndex + 1, Math.max(commands.length - 1, 0));
      renderCommandPalette();
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      state.commandPaletteIndex = Math.max(state.commandPaletteIndex - 1, 0);
      renderCommandPalette();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const command = commands[state.commandPaletteIndex];
      if (!command) return;
      closeCommandPalette();
      rememberCommandUse(command.id);
      await Promise.resolve(command.run());
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeCommandPalette();
    }
  });
}

document.addEventListener("keydown", (event) => {
  const isPaletteShortcut = (event.metaKey || event.ctrlKey) && String(event.key || "").toLowerCase() === "k";
  if (isPaletteShortcut) {
    event.preventDefault();
    if (state.commandPaletteOpen) {
      closeCommandPalette();
    } else {
      openCommandPalette();
    }
    return;
  }
  if (state.commandPaletteOpen && event.key === "Escape") {
    event.preventDefault();
    closeCommandPalette();
  }
});

if (refreshSessionsBtn) {
  refreshSessionsBtn.addEventListener("click", async () => {
    await refreshSessionHistory();
    addBubble("system", "历史会话列表已刷新。");
  });
}

if (deleteSessionBtn) {
  deleteSessionBtn.addEventListener("click", async () => {
    if (!state.sessionId) {
      addBubble("system", "当前没有可删除的会话。");
      return;
    }
    await deleteSessionById(state.sessionId);
  });
}

(async function boot() {
  applyModePreset("general", false);
  restorePanelDebugMode();
  state.chatInfoOpen = false;
  setChatInfoOpen(state.chatInfoOpen, { persist: false });
  setSidebarSessionsOpen(false);
  state.panelLayout = getStoredPanelLayout();
  applyPanelLayout();
  loadRecentCommands();
  setupRailResizer(leftRailResizer, "left");
  setupRailResizer(rightRailResizer, "right");
  setRunStage("空闲", "等待发送请求", null, "idle");
  updateDrillAvailability();
  updateEvalAvailability();
  renderExecutionDag();
  renderExecutionLog();
  renderCommandPalette();
  renderBusinessResultSummary({});
  renderRunPayload(
    {
      session_id: null,
      message: "",
      attachment_ids: [],
      settings: getSettings(),
    },
    []
  );
  renderRunTrace([], []);
  renderAgentPanels([], [], new Set(), null, new Map());
  renderLlmFlow([]);
  try {
    const health = await refreshSystemDashboard();
    await refreshOperationsOverview();
    modelInput.placeholder = health.model_default || MODE_PRESETS.general.model;
    if (!modelInput.value) {
      modelInput.value = health.model_default || MODE_PRESETS.general.model;
    }
    const backendExecMode = String(health.execution_mode_default || "host").toLowerCase();
    const dockerMsg = String(health.docker_message || "").trim();
    renderBackendPolicy(health);
    if (execModeInput) {
      execModeInput.value = "";
      const dockerOption = execModeInput.querySelector('option[value="docker"]');
      if (dockerOption) {
        const dockerReady = Boolean(health.docker_available);
        dockerOption.disabled = !dockerReady;
        dockerOption.textContent = dockerReady ? "Docker（沙盒）" : "Docker（未就绪）";
        dockerOption.title = dockerMsg || (dockerReady ? "Docker is available" : "Docker is not available");
      }
      execModeInput.title = `后端默认执行环境: ${backendExecMode}`;
    }
    await refreshSessionHistory();
    const restored = await restoreSessionIfPossible();
    if (!restored) {
      const dockerTip = health.docker_available ? "Docker 可用" : "Docker 未就绪";
      const buildLabel = String(health.build_version || health.app_version || "unknown");
      addBubble(
        "system",
        `Multi_Agent_Robot 已就绪。版本 ${buildLabel}，默认模型 ${health.model_default}，执行环境 ${backendExecMode}，${dockerTip}。详细环境信息已收进“系统”视图。`
      );
    }
    await refreshTokenStatsFromServer();
    window.setInterval(() => {
      refreshSystemDashboard().catch(() => {});
    }, 15000);
  } catch {
    addBubble("system", "健康检查失败，请确认后端已运行。", null);
  }
})();
