import React, { useEffect, useMemo, useRef, useState } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

const SESSION_STORAGE_KEY = "multi_agent_team.session_id";
const MODULE_MOUNT_OVERRIDES_KEY = "multi_agent_team.module_mount_overrides";
const LLM_MODULE_SLOT_COUNT = 12;
const FALLBACK_MODEL = "gpt-5.1-chat";
const DEFAULT_SETTINGS = {
  model: FALLBACK_MODEL,
  max_output_tokens: 128000,
  max_context_turns: 2000,
  enable_tools: true,
  response_style: "normal",
};

function nowTime() {
  return new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function createLog(type, text) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type,
    text,
    time: nowTime(),
  };
}

function createMessage(role, text, options = {}) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    pending: Boolean(options.pending),
    error: Boolean(options.error),
  };
}

function statusText(status) {
  const key = String(status || "unknown").toLowerCase();
  if (key === "active" || key === "healthy") return "正常";
  if (key === "fallback") return "回退";
  if (key === "degraded") return "降级";
  if (key === "unhealthy" || key === "error") return "异常";
  return "未知";
}

function statusTone(status) {
  const key = String(status || "unknown").toLowerCase();
  if (key === "active" || key === "healthy") return "ok";
  if (key === "fallback" || key === "degraded") return "warn";
  return "bad";
}

function moduleHasIssue(module) {
  if (module && module.mounted === false) return true;
  const s = String(module.status || "").toLowerCase();
  if (s === "unknown") return true;
  if (["degraded", "fallback", "unhealthy", "error"].includes(s)) return true;
  if (Number(module.failureCount || 0) > 0) return true;
  return Boolean(String(module.lastError || "").trim());
}

function defaultModuleMounted(module) {
  return String(module?.status || "").toLowerCase() !== "unknown";
}

function uniqueStrings(values) {
  const out = [];
  const seen = new Set();
  values.forEach((raw) => {
    const value = String(raw || "").trim();
    if (!value) return;
    const key = value.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push(value);
  });
  return out;
}

function titleFromAgentKey(key) {
  const normalized = String(key || "").trim().replace(/-/g, "_");
  if (!normalized) return "LLM Agent";
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeAgentPluginModules(health, pluginRegistry) {
  const topology = health && typeof health.control_panel_topology === "object" ? health.control_panel_topology : {};
  const topologyPlugins = Array.isArray(topology.agent_plugins) ? topology.agent_plugins : [];
  const registryPlugins = Array.isArray(pluginRegistry?.plugins) ? pluginRegistry.plugins : [];
  const registryById = new Map(
    registryPlugins
      .map((item) => [String(item?.plugin_id || "").trim(), item])
      .filter(([pluginId]) => Boolean(pluginId)),
  );
  const sourcePlugins = topologyPlugins.length
    ? topologyPlugins
    : registryPlugins.map((item) => ({
        key: item?.plugin_id,
        title: item?.title,
        path: item?.source_path,
        exists: true,
        sprite_role: item?.sprite_role,
        supports_swarm: item?.supports_swarm,
        swarm_mode: item?.swarm_mode,
        capability_tags: item?.capability_tags,
        summary: item?.description,
        tool_profile: item?.tool_profile,
        allowed_tools: item?.allowed_tools,
        max_tool_rounds: item?.max_tool_rounds,
        independent_runnable: item?.independent_runnable,
      }));
  return sourcePlugins.map((item, index) => {
    const moduleId = String(item?.key || item?.plugin_id || "").trim() || `llm_agent_${String(index + 1).padStart(2, "0")}`;
    const registryItem = registryById.get(moduleId) || null;
    const sourcePath = String(item?.path || registryItem?.source_path || "").trim();
    const exists = "exists" in (item || {}) ? Boolean(item?.exists) : true;
    const rawTags = Array.isArray(item?.capability_tags) ? item.capability_tags : Array.isArray(registryItem?.capability_tags) ? registryItem.capability_tags : [];
    const capabilityTags = rawTags.map((tag) => String(tag || "").trim()).filter(Boolean);
    const spriteRole = String(item?.sprite_role || registryItem?.sprite_role || "").trim() || moduleId.replace(/_agent$/i, "");
    const allowedToolsRaw = Array.isArray(item?.allowed_tools)
      ? item.allowed_tools
      : Array.isArray(registryItem?.allowed_tools)
        ? registryItem.allowed_tools
        : [];
    const allowedTools = uniqueStrings(allowedToolsRaw.map((toolName) => String(toolName || "").trim()).filter(Boolean));
    const toolProfile = String(item?.tool_profile || registryItem?.tool_profile || "none").trim() || "none";
    const maxToolRounds = Number(item?.max_tool_rounds ?? registryItem?.max_tool_rounds ?? 0);
    return {
      key: moduleId,
      title: String(item?.title || registryItem?.title || "").trim() || titleFromAgentKey(moduleId),
      status: exists ? "active" : "unknown",
      selectedRef: sourcePath || moduleId,
      failureCount: exists ? 0 : 1,
      lastError: exists ? "" : "插件文件未发现",
      roles: [],
      profiles: [],
      sourcePath,
      description: String(item?.summary || registryItem?.description || "").trim(),
      supportsSwarm: Boolean(item?.supports_swarm ?? registryItem?.supports_swarm),
      swarmMode: String(item?.swarm_mode || registryItem?.swarm_mode || "none").trim() || "none",
      capabilityTags,
      spriteRole,
      toolProfile,
      allowedTools,
      maxToolRounds: Number.isFinite(maxToolRounds) ? Math.max(0, Math.floor(maxToolRounds)) : 0,
      independentRunnable: Boolean(item?.independent_runnable ?? registryItem?.independent_runnable),
    };
  });
}

function spriteRoleForModule(module) {
  const raw = String(module?.spriteRole || module?.key || "")
    .trim()
    .replace(/-/g, "_")
    .replace(/_agent$/i, "");
  if (!raw || /^llm_module_\d+$/i.test(raw)) return "worker";
  return raw;
}

function buildModuleTopology(health, pluginRegistry) {
  const topology = health && typeof health.control_panel_topology === "object" ? health.control_panel_topology : {};
  const kernelSource = topology && typeof topology.kernel === "object" ? topology.kernel : {};
  const routerSource = topology && typeof topology.central_router === "object" ? topology.central_router : {};
  const sourceModules = normalizeAgentPluginModules(health, pluginRegistry);

  const kernelCore = {
    key: "kernel_core",
    title: "主核",
    kindLabel: "Kernel Core",
    status: health && health.ok ? "active" : "error",
    selectedRef: String(kernelSource?.path || (health && health.product_title) || "app/kernel/host.py"),
    failureCount: 0,
    lastError: "",
    sourcePath: String(kernelSource?.path || "app/kernel/host.py"),
    roles: [],
    toolProfile: "kernel-core",
    allowedTools: [],
    maxToolRounds: 0,
    independentRunnable: false,
    supportsSwarm: false,
    swarmMode: "none",
    capabilityTags: [],
    description: "系统主核（启动、上下文与状态管理）",
    spriteRole: "kernel",
  };

  const routerExists = Boolean(routerSource?.exists);
  const centralLlm = {
    key: "llm_central_router",
    title: "LLM 中央调度",
    kindLabel: "LLM Router",
    status: routerExists ? "active" : "unknown",
    selectedRef: String(routerSource?.path || "app/kernel/llm_router.py"),
    failureCount: routerExists ? 0 : 1,
    lastError: routerExists ? "" : "未找到 app/kernel/llm_router.py",
    sourcePath: String(routerSource?.path || "app/kernel/llm_router.py"),
    roles: [],
    toolProfile: "route-only",
    allowedTools: [],
    maxToolRounds: 0,
    independentRunnable: false,
    supportsSwarm: true,
    swarmMode: "fanout-router",
    capabilityTags: ["routing", "policy-gate"],
    description: "LLM 中央调度器（意图路由、插件分发）",
    spriteRole: "router",
  };

  const llmModules = Array.from({ length: LLM_MODULE_SLOT_COUNT }, (_, idx) => {
    const source = sourceModules[idx];
    const slot = String(idx + 1).padStart(2, "0");
    if (source) {
      return {
        ...source,
        kindLabel: `LLM 模块 ${slot}`,
      };
    }
    return {
      key: `llm_module_${slot}`,
      title: `LLM 模块 ${slot}`,
      kindLabel: `LLM 模块 ${slot}`,
      status: "unknown",
      selectedRef: `llm_module_${slot}`,
      failureCount: 0,
      lastError: "",
      sourcePath: "",
      roles: [],
      supportsSwarm: false,
      swarmMode: "none",
      capabilityTags: [],
      spriteRole: "worker",
      description: "",
      toolProfile: "none",
      allowedTools: [],
      maxToolRounds: 0,
      independentRunnable: false,
    };
  });

  return {
    kernelCore,
    centralLlm,
    llmModules,
    sourceAgentCount: sourceModules.length,
  };
}

function formatSessionTime(raw) {
  if (!raw) return "-";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function TeamLogo() {
  return html`
    <div className="team-logo">
      <svg className="team-logo-mark" viewBox="0 0 260 110" aria-hidden="true" role="img">
        <defs>
          <linearGradient id="logoShieldGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#113347" />
            <stop offset="100%" stopColor="#1f5f7f" />
          </linearGradient>
          <linearGradient id="logoOrbitGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#36c4e1" />
            <stop offset="100%" stopColor="#1787ad" />
          </linearGradient>
        </defs>
        <rect x="8" y="10" width="96" height="90" rx="20" fill="url(#logoShieldGrad)" stroke="#2c7ea3" strokeWidth="2.5" />
        <circle cx="56" cy="55" r="26" fill="none" stroke="url(#logoOrbitGrad)" strokeWidth="5" />
        <circle cx="56" cy="55" r="14" fill="#e8f7fc" />
        <path d="M56 38L68 55L56 72L44 55Z" fill="#1f5f7f" />
        <circle cx="34" cy="33" r="4.5" fill="#63d2e8" />
        <circle cx="78" cy="77" r="4.5" fill="#63d2e8" />
        <path d="M34 33L44 42" stroke="#63d2e8" strokeWidth="2" strokeLinecap="round" />
        <path d="M68 68L78 77" stroke="#63d2e8" strokeWidth="2" strokeLinecap="round" />
        <text x="120" y="42" fontSize="16" fontWeight="700" fill="#204d63">Multi Agent Team</text>
        <text x="120" y="63" fontSize="13" fill="#4d7080">LLM Orchestration System</text>
        <text x="120" y="82" fontSize="12" fill="#6a8795">Core + Central Control + 12 Modules</text>
      </svg>
      <div className="team-logo-copy">
        <div className="team-logo-title">Logo Style B</div>
        <div className="team-logo-sub">Shield + Orbit + Network Node</div>
      </div>
    </div>
  `;
}

function svgRect(x, y, color, size = 4) {
  return `<rect x="${x * size}" y="${y * size}" width="${size}" height="${size}" fill="${color}" />`;
}

function buildRoleSprite(roleId = "worker") {
  const palette = {
    router: { kindKey: "hybrid", accent: "#4f7eff", accent2: "#98b7ff" },
    coordinator: { kindKey: "processor", accent: "#2e9f6b", accent2: "#9ddfbe" },
    planner: { kindKey: "agent", accent: "#22a2ab", accent2: "#8edee5" },
    researcher: { kindKey: "agent", accent: "#4f7eff", accent2: "#98b7ff" },
    file_reader: { kindKey: "processor", accent: "#ff8f5e", accent2: "#ffd2b8" },
    summarizer: { kindKey: "agent", accent: "#6d7de2", accent2: "#b7c2ff" },
    fixer: { kindKey: "processor", accent: "#f58b37", accent2: "#fbd9ac" },
    worker: { kindKey: "agent", accent: "#1f86a3", accent2: "#67b9ce" },
    conflict_detector: { kindKey: "hybrid", accent: "#e46b5e", accent2: "#ffb4a8" },
    reviewer: { kindKey: "agent", accent: "#8b74de", accent2: "#c7bcf2" },
    revision: { kindKey: "agent", accent: "#308fb1", accent2: "#8fcae0" },
    structurer: { kindKey: "processor", accent: "#4e9b6f", accent2: "#99d1af" },
  };
  const meta = palette[roleId] || palette.worker;
  const outline = "#1f2f27";
  const shell = "#dcefe2";
  const shadow = "#a3c1b1";
  const eye = meta.kindKey === "processor" ? "#fff1c9" : "#f6fff6";
  const accent = meta.accent;
  const accent2 = meta.accent2;
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
    outline,
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
    shell,
  );
  add(
    [
      [4, 6], [5, 6], [6, 6], [7, 6],
      [4, 9], [5, 9], [6, 9], [7, 9],
    ],
    shadow,
  );
  add(roleId === "conflict_detector" ? [[4, 4]] : [[4, 4], [7, 4]], roleId === "conflict_detector" ? "#ffef78" : eye);
  if (roleId === "conflict_detector") add([[7, 4]], "#ff8872");

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

function App() {
  const [health, setHealth] = useState(null);
  const [pluginRegistry, setPluginRegistry] = useState({ ok: false, detail: "", plugins: [], tool_model: { profiles: {}, tools: [] } });
  const [logs, setLogs] = useState(() => [createLog("system", "UI 已启动，等待运行态数据。")]);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [chatSettings, setChatSettings] = useState(() => ({ ...DEFAULT_SETTINGS }));
  const [modelTouched, setModelTouched] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [avatarPanelOpen, setAvatarPanelOpen] = useState(false);
  const [selectedControlModuleKey, setSelectedControlModuleKey] = useState("");
  const [selectedAvatarModuleKey, setSelectedAvatarModuleKey] = useState("");
  const [pluginRunInput, setPluginRunInput] = useState("");
  const [pluginRunPending, setPluginRunPending] = useState(false);
  const [pluginRunResult, setPluginRunResult] = useState(null);
  const [moduleMountOverrides, setModuleMountOverrides] = useState(() => {
    try {
      const raw = window.localStorage.getItem(MODULE_MOUNT_OVERRIDES_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {};
      const safe = {};
      Object.entries(parsed).forEach(([k, v]) => {
        if (typeof k === "string" && typeof v === "boolean") safe[k] = v;
      });
      return safe;
    } catch {
      return {};
    }
  });
  const chatListRef = useRef(null);

  const moduleTopology = useMemo(() => buildModuleTopology(health, pluginRegistry), [health, pluginRegistry]);
  const topologyModules = useMemo(
    () => [moduleTopology.kernelCore, moduleTopology.centralLlm, ...moduleTopology.llmModules],
    [moduleTopology],
  );
  const runtimeModules = useMemo(
    () =>
      topologyModules.map((item) => {
        const override = moduleMountOverrides[item.key];
        const mounted = typeof override === "boolean" ? override : defaultModuleMounted(item);
        return { ...item, mounted };
      }),
    [topologyModules, moduleMountOverrides],
  );
  const selectedControlModule = useMemo(
    () => runtimeModules.find((item) => item.key === selectedControlModuleKey) || null,
    [runtimeModules, selectedControlModuleKey],
  );
  const agentModules = useMemo(
    () => runtimeModules.filter((item) => String(item.kindLabel || "").startsWith("LLM 模块")),
    [runtimeModules],
  );
  const selectedAvatarModule = useMemo(
    () => agentModules.find((item) => item.key === selectedAvatarModuleKey) || null,
    [agentModules, selectedAvatarModuleKey],
  );
  const toolDescriptionMap = useMemo(() => {
    const map = new Map();
    const toolModel = pluginRegistry && typeof pluginRegistry === "object" ? pluginRegistry.tool_model : null;
    const tools = Array.isArray(toolModel?.tools) ? toolModel.tools : [];
    tools.forEach((item) => {
      const name = String(item?.name || "").trim();
      if (!name) return;
      map.set(name, String(item?.description || "").trim());
    });
    return map;
  }, [pluginRegistry]);
  const providerName = useMemo(() => String((health && health.llm_provider) || "").trim().toLowerCase(), [health]);
  const modelOptions = useMemo(() => {
    const preferredQwen = providerName === "ollama" ? "qwen2.5:14b" : "qwen-plus";
    return uniqueStrings([
      health && health.model_default ? health.model_default : "",
      preferredQwen,
      "qwen2.5:7b",
      "qwen2.5-coder:14b",
      "qwen3:8b",
      "qwen3:14b",
      "llama3.2:3b",
      chatSettings.model,
    ]);
  }, [health, providerName, chatSettings.model]);
  const modelSelectValue = useMemo(() => {
    const current = String(chatSettings.model || "").trim();
    if (!current) return "";
    return modelOptions.includes(current) ? current : "__custom__";
  }, [chatSettings.model, modelOptions]);
  const hasModuleIssue = useMemo(() => runtimeModules.some(moduleHasIssue), [runtimeModules]);
  const kernelStable = useMemo(() => Boolean(health && health.ok) && !hasModuleIssue, [health, hasModuleIssue]);
  const toolBoundAgentCount = useMemo(
    () => agentModules.filter((item) => Array.isArray(item.allowedTools) && item.allowedTools.length > 0).length,
    [agentModules],
  );

  const pushLog = (type, text) => {
    setLogs((prev) => [createLog(type, text), ...prev].slice(0, 18));
  };

  useEffect(() => {
    const boot = async () => {
      await Promise.all([refreshHealth(), refreshSessions(), refreshPluginRegistry(true)]);
      const cached = window.localStorage.getItem(SESSION_STORAGE_KEY) || "";
      if (cached) {
        await loadSession(cached, { silentNotFound: true });
      }
    };
    boot();
  }, []);

  useEffect(() => {
    if (!chatListRef.current) return;
    chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (sessionId) {
      window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    } else {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  }, [sessionId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(MODULE_MOUNT_OVERRIDES_KEY, JSON.stringify(moduleMountOverrides));
    } catch {
      // ignore storage errors
    }
  }, [moduleMountOverrides]);

  useEffect(() => {
    const runtimeDefaultModel = String((health && health.model_default) || "").trim();
    if (!runtimeDefaultModel || modelTouched) return;
    setChatSettings((prev) => {
      if (String(prev.model || "").trim() === runtimeDefaultModel) return prev;
      return { ...prev, model: runtimeDefaultModel };
    });
  }, [health, modelTouched]);

  useEffect(() => {
    if (!runtimeModules.length) {
      if (selectedControlModuleKey) setSelectedControlModuleKey("");
      return;
    }
    if (!runtimeModules.some((item) => item.key === selectedControlModuleKey)) {
      setSelectedControlModuleKey(runtimeModules[0].key);
    }
  }, [runtimeModules, selectedControlModuleKey]);

  useEffect(() => {
    if (!agentModules.length) {
      if (selectedAvatarModuleKey) setSelectedAvatarModuleKey("");
      return;
    }
    if (!agentModules.some((item) => item.key === selectedAvatarModuleKey)) {
      setSelectedAvatarModuleKey(agentModules[0].key);
    }
  }, [agentModules, selectedAvatarModuleKey]);

  useEffect(() => {
    setPluginRunInput("");
    setPluginRunResult(null);
    setPluginRunPending(false);
  }, [selectedAvatarModuleKey, avatarPanelOpen]);

  async function refreshHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`health ${res.status}`);
      const data = await res.json();
      setHealth(data);
    } catch (err) {
      pushLog("error", `刷新 health 失败：${String(err.message || err)}`);
    }
  }

  async function refreshPluginRegistry(silent = false) {
    try {
      const res = await fetch("/api/agent-plugins");
      if (!res.ok) throw new Error(`agent-plugins ${res.status}`);
      const data = await res.json();
      setPluginRegistry(data);
      return data;
    } catch (err) {
      if (!silent) {
        pushLog("error", `刷新插件注册表失败：${String(err.message || err)}`);
      }
      return null;
    }
  }

  async function refreshSessions() {
    try {
      const res = await fetch("/api/sessions?limit=80");
      if (!res.ok) throw new Error(`sessions ${res.status}`);
      const data = await res.json();
      const list = Array.isArray(data.sessions) ? data.sessions : [];
      setSessions(list);
      return list;
    } catch (err) {
      pushLog("error", `刷新会话列表失败：${String(err.message || err)}`);
      return [];
    }
  }

  async function loadSession(targetSessionId, options = {}) {
    const sid = String(targetSessionId || "").trim();
    if (!sid) return false;
    setLoadingSession(true);
    try {
      const res = await fetch(`/api/session/${encodeURIComponent(sid)}?max_turns=120`);
      if (!res.ok) {
        if (res.status === 404 && options.silentNotFound) {
          return false;
        }
        throw new Error(`session ${res.status}`);
      }
      const data = await res.json();
      const turns = Array.isArray(data.turns) ? data.turns : [];
      const normalized = turns.map((turn) => {
        const roleRaw = String(turn.role || "assistant").toLowerCase();
        const role = roleRaw === "user" ? "user" : roleRaw === "system" ? "system" : "assistant";
        return createMessage(role, String(turn.text || ""));
      });
      setMessages(normalized);
      setSessionId(sid);
      pushLog("system", `已载入会话 ${sid.slice(0, 8)}。`);
      await refreshSessions();
      return true;
    } catch (err) {
      pushLog("error", `载入会话失败：${String(err.message || err)}`);
      return false;
    } finally {
      setLoadingSession(false);
    }
  }

  async function createSession() {
    const res = await fetch("/api/session/new", { method: "POST" });
    if (!res.ok) throw new Error(`create session ${res.status}`);
    const data = await res.json();
    const sid = String(data.session_id || "").trim();
    if (!sid) throw new Error("session_id empty");
    setSessionId(sid);
    setMessages([]);
    await refreshSessions();
    pushLog("system", `已创建新会话 ${sid.slice(0, 8)}。`);
    return sid;
  }

  async function handleNewSession() {
    try {
      await createSession();
    } catch (err) {
      pushLog("error", `新建会话失败：${String(err.message || err)}`);
    }
  }

  async function handleSend() {
    const messageText = draft.trim();
    if (!messageText || sending) return;

    setDraft("");
    setSending(true);

    let sid = sessionId;
    try {
      if (!sid) sid = await createSession();
      const userMessage = createMessage("user", messageText);
      const pendingMessage = createMessage("assistant", "正在思考中...", { pending: true });
      setMessages((prev) => [...prev, userMessage, pendingMessage]);
      pushLog("request", `发送消息（${messageText.length} 字）到会话 ${sid.slice(0, 8)}。`);

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sid,
          message: messageText,
          settings: {
            ...DEFAULT_SETTINGS,
            ...chatSettings,
            model: String(chatSettings.model || (health && health.model_default) || FALLBACK_MODEL).trim(),
          },
        }),
      });

      if (!res.ok) {
        let detail = `chat ${res.status}`;
        try {
          const errData = await res.json();
          if (typeof errData.detail === "string" && errData.detail.trim()) {
            detail = errData.detail;
          }
        } catch {
          // ignore json parse errors
        }
        throw new Error(detail);
      }

      const data = await res.json();
      const answerText = String(data.text || "(空响应)");
      setMessages((prev) => {
        const copy = [...prev];
        const index = copy.findIndex((item) => item.id === pendingMessage.id);
        const finalMessage = createMessage("assistant", answerText);
        if (index >= 0) {
          copy[index] = finalMessage;
        } else {
          copy.push(finalMessage);
        }
        return copy;
      });

      pushLog("response", `收到回复（${answerText.length} 字）。`);
      await Promise.all([refreshSessions(), refreshHealth()]);
    } catch (err) {
      const failText = `请求失败：${String(err.message || err)}`;
      setMessages((prev) => {
        const withoutPending = prev.filter((item) => !item.pending);
        return [...withoutPending, createMessage("system", failText, { error: true })];
      });
      pushLog("error", failText);
      await refreshHealth();
    } finally {
      setSending(false);
    }
  }

  function handleToggleModuleMounted(module, mounted) {
    if (!module || !module.key) return;
    const mountedValue = Boolean(mounted);
    setModuleMountOverrides((prev) => {
      const next = { ...prev };
      const defaultMounted = defaultModuleMounted(module);
      if (defaultMounted === mountedValue) {
        delete next[module.key];
      } else {
        next[module.key] = mountedValue;
      }
      return next;
    });
    pushLog("system", `${module.title} 已${mountedValue ? "装载" : "卸载"}。`);
  }

  function handleOpenControlPanel() {
    setPanelOpen(true);
    refreshPluginRegistry(true);
  }

  function handleOpenAvatarPanel() {
    setAvatarPanelOpen(true);
    refreshPluginRegistry(true);
  }

  async function handleRunSelectedPlugin() {
    if (!selectedAvatarModule || !selectedAvatarModule.independentRunnable || pluginRunPending) return;
    const pluginId = String(selectedAvatarModule.key || "").trim();
    if (!pluginId) return;
    const prompt = String(pluginRunInput || "").trim() || "请输出该插件职责、可执行步骤和当前限制。";
    setPluginRunPending(true);
    setPluginRunResult(null);
    try {
      const res = await fetch("/api/agent-plugins/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plugin_id: pluginId,
          message: prompt,
          context: {
            source: "avatar_panel",
            session_id: sessionId || "",
            selected_tools: selectedAvatarModule.allowedTools || [],
          },
          settings: {
            ...DEFAULT_SETTINGS,
            ...chatSettings,
            model: String(chatSettings.model || (health && health.model_default) || FALLBACK_MODEL).trim(),
          },
        }),
      });
      if (!res.ok) {
        let detail = `agent-plugin-run ${res.status}`;
        try {
          const payload = await res.json();
          if (typeof payload.detail === "string" && payload.detail.trim()) detail = payload.detail;
        } catch {
          // ignore parse errors
        }
        throw new Error(detail);
      }
      const data = await res.json();
      setPluginRunResult(data);
      pushLog("response", `${selectedAvatarModule.title} 独立运行完成，返回 ${String(data.text || "").length} 字。`);
    } catch (err) {
      const detail = String(err.message || err);
      setPluginRunResult({ ok: false, text: "", error: detail });
      pushLog("error", `插件独立运行失败：${detail}`);
    } finally {
      setPluginRunPending(false);
    }
  }

  function handleModelSelectChange(event) {
    const value = String(event.currentTarget.value || "").trim();
    if (!value || value === "__custom__") return;
    setModelTouched(true);
    setChatSettings((prev) => ({ ...prev, model: value }));
    pushLog("system", `模型已切换到 ${value}。`);
  }

  function handleModelInputChange(event) {
    const value = String(event.currentTarget.value || "");
    setModelTouched(true);
    setChatSettings((prev) => ({ ...prev, model: value }));
  }

  function handleComposerKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  }

  const recentLogs = logs.length
    ? logs.slice(0, 6)
    : [{ id: "empty-log", type: "system", time: nowTime(), text: "暂无日志。" }];
  const totalSlots = runtimeModules.length;
  const healthyCount = runtimeModules.filter((item) => item.mounted && !moduleHasIssue(item)).length;
  const mountedCount = runtimeModules.filter((item) => item.mounted).length;
  const issueCount = totalSlots - healthyCount;
  const healthPercent = totalSlots ? Math.round((healthyCount / totalSlots) * 100) : 0;
  const issuePercent = totalSlots ? Math.round((issueCount / totalSlots) * 100) : 0;
  const centralRuntimeModule = runtimeModules.find((item) => item.key === moduleTopology.centralLlm.key) || null;
  const swarmEnabledCount = agentModules.filter((item) => item.supportsSwarm).length;

  return html`
    <div className="app-bg">
      <div className="app-shell">
        <section className="top-grid">
          <article className="card top-card logo-card">
            <div className="card-kicker">Logo</div>
            <div className="card-title">品牌标识</div>
            <${TeamLogo} />
          </article>

          <button className="card top-card control-preview" type="button" onClick=${handleOpenControlPanel}>
            <div className="card-kicker">Control Panel</div>
            <div className="card-title">点击放大查看</div>
            <div className="dashboard-mini">
              <div className="gauge-mini-shell">
                <div
                  className=${`gauge-mini-ring ${kernelStable ? "ok" : "warn"}`}
                  style=${{ "--gauge-value": `${healthPercent}%` }}
                >
                  <span>${healthPercent}%</span>
                </div>
                <div className="gauge-mini-label">${kernelStable ? "主核稳定" : "需要检查"}</div>
              </div>
              <div className="dashboard-mini-metrics">
                <div className="dashboard-metric-row">
                  <span>主核</span>
                  <span className=${`lamp ${kernelStable ? "ok" : "warn"}`}></span>
                </div>
                <div className="dashboard-metric-row">
                  <span>中央调控</span>
                  <span className=${`lamp ${moduleHasIssue(centralRuntimeModule) ? "warn" : "ok"}`}></span>
                </div>
                <div className="dashboard-metric-row">
                  <span>LLM 模块</span>
                  <span>${LLM_MODULE_SLOT_COUNT}</span>
                </div>
              </div>
            </div>
            <div className="control-preview-row muted">仪表盘视图：1 主核 + 1 中央调控 + 12 Agent 插件</div>
          </button>

          <button className="card top-card pixel-card agent-preview-card" type="button" onClick=${handleOpenAvatarPanel}>
            <div className="card-kicker">Avatar Modules</div>
            <div className="card-title">像素人缩略图</div>
            <div className="agent-wall-mini" aria-hidden="true">
              ${agentModules.slice(0, LLM_MODULE_SLOT_COUNT).map(
                (mod) => html`
                  <div key=${mod.key} className=${`agent-mini-tile ${mod.supportsSwarm ? "swarm" : ""}`}>
                    <div
                      className=${`legacy-sprite-wrap mini ${mod.mounted ? "active" : ""}`}
                      dangerouslySetInnerHTML=${{ __html: buildRoleSprite(spriteRoleForModule(mod)) }}
                    ></div>
                    <span className=${`lamp tiny ${mod.mounted ? statusTone(mod.status) : "bad"}`}></span>
                  </div>
                `,
              )}
            </div>
            <div className="agent-preview-meta">
              ${agentModules.length} modules · ${swarmEnabledCount} swarm-enabled · ${toolBoundAgentCount} tool-bound · 点击放大查看详情
            </div>
          </button>
        </section>

        <section className="main-grid">
          <aside className="left-rail">
            <article className="card quick-card">
              <div className="card-kicker">Session</div>
              <div className="card-title">会话控制</div>
              <button className="primary" type="button" onClick=${handleNewSession} disabled=${sending || loadingSession}>
                新建会话
              </button>
              <button className="ghost" type="button" onClick=${refreshSessions} disabled=${sending || loadingSession}>
                刷新列表
              </button>
              <div className="session-current">当前会话：${sessionId ? sessionId : "(未创建)"}</div>
              <div className="mini-log-head">模型选择</div>
              <div className="model-config">
                <div className="model-config-row">
                  <label htmlFor="modelPreset">预设</label>
                  <select id="modelPreset" value=${modelSelectValue} onChange=${handleModelSelectChange} disabled=${sending}>
                    ${modelOptions.map((name) => html`<option key=${name} value=${name}>${name}</option>`)}
                    <option value="__custom__">自定义</option>
                  </select>
                </div>
                <div className="model-config-row">
                  <label htmlFor="modelInput">模型名</label>
                  <input
                    id="modelInput"
                    type="text"
                    value=${chatSettings.model}
                    onInput=${handleModelInputChange}
                    placeholder="例如 qwen2.5:14b / qwen-plus / gpt-5.1-chat"
                    disabled=${sending}
                  />
                </div>
                <div className="model-config-meta">
                  provider=${providerName || "unknown"} · auth=${health && health.auth_mode ? health.auth_mode : "unknown"} ·
                  default=${health && health.model_default ? health.model_default : FALLBACK_MODEL}
                </div>
              </div>
              <div className="mini-log-head">Log</div>
              <div className="mini-log-list">
                ${recentLogs.map(
                  (item) => html`
                    <div key=${item.id} className=${`mini-log-row log-${item.type}`}>
                      <span className="mini-log-time">${item.time}</span>
                      <span className="mini-log-text">${item.text}</span>
                    </div>
                  `,
                )}
              </div>
            </article>

            <article className="card history-card">
              <div className="card-kicker">History</div>
              <div className="card-title">历史聊天记录</div>
              <div className="history-list">
                ${sessions.length
                  ? sessions.map(
                      (item) => html`
                        <button
                          key=${item.session_id}
                          type="button"
                          className=${`history-item ${item.session_id === sessionId ? "active" : ""}`}
                          onClick=${() => loadSession(item.session_id)}
                          disabled=${loadingSession || sending}
                        >
                          <div className="history-title">${item.title || "新会话"}</div>
                          <div className="history-meta">${formatSessionTime(item.updated_at)} · ${item.turn_count || 0} turns</div>
                          <div className="history-preview">${item.preview || "暂无预览"}</div>
                        </button>
                      `,
                    )
                  : html`<div className="history-empty">还没有历史会话</div>`}
              </div>
            </article>
          </aside>

          <section className="card chat-card">
            <div className="chat-head">
              <div>
                <div className="card-kicker">Chat</div>
                <div className="card-title">主聊天区</div>
              </div>
              <div className="chat-status ${sending ? "sending" : ""}">${sending ? "发送中..." : "在线"}</div>
            </div>

            <div className="chat-list" ref=${chatListRef}>
              ${messages.length
                ? messages.map(
                    (msg) => html`
                      <div
                        key=${msg.id}
                        className=${`bubble-row role-${msg.role} ${msg.pending ? "pending" : ""} ${msg.error ? "error" : ""}`}
                      >
                        <div className="bubble">${msg.text}</div>
                      </div>
                    `,
                  )
                : html`<div className="chat-empty">发一条消息开始聊天。</div>`}
            </div>

            <div className="composer">
              <textarea
                value=${draft}
                onInput=${(e) => setDraft(e.currentTarget.value)}
                onKeyDown=${handleComposerKeyDown}
                placeholder="输入消息。Enter 发送，Shift+Enter 换行。"
                disabled=${sending}
              ></textarea>
              <button className="primary send-btn" type="button" onClick=${handleSend} disabled=${sending || !draft.trim()}>
                发送
              </button>
            </div>
          </section>
        </section>
      </div>

      ${panelOpen
        ? html`
            <div className="modal-overlay" onClick=${() => setPanelOpen(false)}>
              <div className="modal-card" onClick=${(e) => e.stopPropagation()}>
                <div className="modal-head">
                  <div>
                    <div className="card-kicker">Control Panel</div>
                    <div className="card-title">系统总览</div>
                  </div>
                  <button className="ghost close-btn" type="button" onClick=${() => setPanelOpen(false)}>关闭</button>
                </div>

                <div className="modal-grid">
                  <section className="modal-section">
                    <div className="section-title">主核稳定</div>
                    <div className="dashboard-panel-grid">
                      <article className="dashboard-panel">
                        <div
                          className=${`gauge-ring ${kernelStable ? "ok" : "warn"}`}
                          style=${{ "--gauge-value": `${healthPercent}%` }}
                        >
                          <span>${healthPercent}%</span>
                        </div>
                        <div className="dashboard-panel-title">总体健康度</div>
                      </article>
                      <article className="dashboard-panel">
                        <div
                          className=${`gauge-ring ${issueCount ? "warn" : "ok"}`}
                          style=${{ "--gauge-value": `${issuePercent}%` }}
                        >
                          <span>${issueCount}</span>
                        </div>
                        <div className="dashboard-panel-title">异常模块数</div>
                      </article>
                    </div>
                    <div className="kernel-status-row dashboard-inline">
                      <span className=${`lamp xl ${kernelStable ? "ok" : "warn"}`}></span>
                      <div>
                        <div className="kernel-title">${kernelStable ? "主核稳定" : "主核存在风险"}</div>
                        <div className="kernel-meta">
                          auth=${health && health.auth_mode ? health.auth_mode : "unknown"} · exec=${
                            health && health.execution_mode_default ? health.execution_mode_default : "unknown"
                          }
                        </div>
                      </div>
                    </div>
                    <ul className="kernel-facts">
                      <li>健康接口：${health && health.ok ? "正常" : "异常"}</li>
                      <li>固定拓扑：1 + 1 + ${LLM_MODULE_SLOT_COUNT}</li>
                      <li>已识别 Agent 插件：${moduleTopology.sourceAgentCount}</li>
                      <li>已装载模块：${mountedCount}</li>
                      <li>异常模块：${issueCount}</li>
                    </ul>
                  </section>

                  <section className="modal-section">
                    <div className="section-title">模块列表（主核 + 中央 + 12 Agent 插件）</div>
                    <div className="module-list">
                      ${runtimeModules.map(
                        (mod) => html`
                          <button
                            key=${mod.key}
                            type="button"
                            className=${`module-item module-item-button ${selectedControlModuleKey === mod.key ? "is-selected" : ""}`}
                            onClick=${() => setSelectedControlModuleKey(mod.key)}
                          >
                            <span className=${`lamp ${mod.mounted ? statusTone(mod.status) : "bad"}`}></span>
                            <div className="module-main">
                              <div className="module-key">${mod.title}</div>
                              <div className="module-ref">${mod.sourcePath || mod.key}</div>
                              ${mod.kindLabel ? html`<div className="module-tags">${mod.kindLabel}</div>` : null}
                              ${mod.roles && mod.roles.length ? html`<div className="module-tags">roles: ${mod.roles.join(" / ")}</div>` : null}
                              <div className="module-tags">
                                tool profile: ${mod.toolProfile || "none"} · tools: ${(mod.allowedTools || []).length} · rounds: ${mod.maxToolRounds || 0}
                              </div>
                            </div>
                            <div className="module-status-stack">
                              <div className=${`module-mount-chip ${mod.mounted ? "mounted" : "unmounted"}`}>
                                ${mod.mounted ? "已装载" : "未装载"}
                              </div>
                              <div className="module-status">${mod.mounted ? statusText(mod.status) : "离线"}</div>
                            </div>
                          </button>
                        `,
                      )}
                    </div>
                    ${selectedControlModule
                      ? html`
                          <div className="module-action-panel">
                            <div className="module-action-head">
                              <div className="module-action-title">${selectedControlModule.title}</div>
                              <div className="module-action-sub">${selectedControlModule.key}</div>
                            </div>
                            <div className="module-action-meta-grid">
                              <div className="module-action-meta-row">
                                <span>Tool Profile</span>
                                <code>${selectedControlModule.toolProfile || "none"}</code>
                              </div>
                              <div className="module-action-meta-row">
                                <span>Round Limit</span>
                                <strong>${selectedControlModule.maxToolRounds || 0}</strong>
                              </div>
                              <div className="module-action-meta-row">
                                <span>Allowed Tools</span>
                                <strong>${(selectedControlModule.allowedTools || []).length}</strong>
                              </div>
                              <div className="module-action-meta-row">
                                <span>独立运行</span>
                                <strong>${selectedControlModule.independentRunnable ? "支持" : "不支持"}</strong>
                              </div>
                            </div>
                            ${(selectedControlModule.allowedTools || []).length
                              ? html`
                                  <div className="module-tool-list">
                                    ${(selectedControlModule.allowedTools || []).map((toolName) => {
                                      const toolDescription = toolDescriptionMap.get(toolName) || "";
                                      return html`<span key=${`${selectedControlModule.key}-${toolName}`} className="capability-chip" title=${toolDescription || toolName}>${toolName}</span>`;
                                    })}
                                  </div>
                                `
                              : html`<div className="module-empty">此模块未绑定工具。</div>`}
                            <div className="module-action-row">
                              <button
                                className="ghost"
                                type="button"
                                disabled=${selectedControlModule.mounted}
                                onClick=${() => handleToggleModuleMounted(selectedControlModule, true)}
                              >
                                装载
                              </button>
                              <button
                                className="danger"
                                type="button"
                                disabled=${!selectedControlModule.mounted}
                                onClick=${() => handleToggleModuleMounted(selectedControlModule, false)}
                              >
                                卸载
                              </button>
                            </div>
                          </div>
                        `
                      : null}
                  </section>
                </div>
              </div>
            </div>
          `
        : null}
      ${avatarPanelOpen
        ? html`
            <div className="modal-overlay" onClick=${() => setAvatarPanelOpen(false)}>
              <div className="modal-card avatar-modal" onClick=${(e) => e.stopPropagation()}>
                <div className="modal-head">
                  <div>
                    <div className="card-kicker">Agent Modules</div>
                    <div className="card-title">像素人模块详情</div>
                  </div>
                  <button className="ghost close-btn" type="button" onClick=${() => setAvatarPanelOpen(false)}>关闭</button>
                </div>

                <div className="avatar-modal-grid">
                  <section className="modal-section">
                    <div className="section-title">模块缩略图</div>
                    <div className="avatar-module-list">
                      ${agentModules.map(
                        (mod, idx) => html`
                          <button
                            key=${mod.key}
                            type="button"
                            className=${`avatar-module-item ${selectedAvatarModule && selectedAvatarModule.key === mod.key ? "is-selected" : ""}`}
                            onClick=${() => setSelectedAvatarModuleKey(mod.key)}
                          >
                            <div
                              className=${`legacy-sprite-wrap avatar-sprite ${mod.mounted ? "active" : ""}`}
                              dangerouslySetInnerHTML=${{ __html: buildRoleSprite(spriteRoleForModule(mod)) }}
                            ></div>
                            <div className="avatar-module-main">
                              <div className="avatar-module-title">${`#${String(idx + 1).padStart(2, "0")} ${mod.title}`}</div>
                              <div className="avatar-module-sub">${mod.sourcePath || mod.key}</div>
                              <div className="avatar-module-tags">
                                <span className=${`capability-chip ${mod.supportsSwarm ? "swarm" : "plain"}`}>
                                  ${mod.supportsSwarm ? `Swarm · ${mod.swarmMode || "enabled"}` : "Single Agent"}
                                </span>
                                <span className=${`lamp tiny ${mod.mounted ? statusTone(mod.status) : "bad"}`}></span>
                              </div>
                            </div>
                          </button>
                        `,
                      )}
                    </div>
                  </section>

                  <section className="modal-section">
                    <div className="section-title">模块信息</div>
                    ${selectedAvatarModule
                      ? html`
                          <div className="avatar-detail-head">
                            <div className="avatar-detail-title">${selectedAvatarModule.title}</div>
                            <div className="avatar-detail-sub">${selectedAvatarModule.key}</div>
                          </div>
                          <div className="avatar-detail-grid">
                            <div className="avatar-detail-row">
                              <span>文件</span>
                              <code>${selectedAvatarModule.sourcePath || "-"}</code>
                            </div>
                            <div className="avatar-detail-row">
                              <span>状态</span>
                              <strong>${selectedAvatarModule.mounted ? statusText(selectedAvatarModule.status) : "离线"}</strong>
                            </div>
                            <div className="avatar-detail-row">
                              <span>Swarm</span>
                              <strong>${selectedAvatarModule.supportsSwarm ? "支持" : "不支持"}</strong>
                            </div>
                            <div className="avatar-detail-row">
                              <span>Swarm 模式</span>
                              <code>${selectedAvatarModule.supportsSwarm ? selectedAvatarModule.swarmMode || "generic" : "none"}</code>
                            </div>
                            <div className="avatar-detail-row">
                              <span>Tool Profile</span>
                              <code>${selectedAvatarModule.toolProfile || "none"}</code>
                            </div>
                            <div className="avatar-detail-row">
                              <span>Tool Rounds</span>
                              <strong>${selectedAvatarModule.maxToolRounds || 0}</strong>
                            </div>
                            <div className="avatar-detail-row">
                              <span>Tools</span>
                              <strong>${(selectedAvatarModule.allowedTools || []).length}</strong>
                            </div>
                          </div>
                          <div className="avatar-detail-note">调度入口：app/kernel/llm_router.py</div>
                          ${(selectedAvatarModule.allowedTools || []).length
                            ? html`
                                <div className="avatar-capability-list">
                                  ${(selectedAvatarModule.allowedTools || []).map((toolName) => {
                                    const toolDescription = toolDescriptionMap.get(toolName) || "";
                                    return html`<span key=${`${selectedAvatarModule.key}-tool-${toolName}`} className="capability-chip" title=${toolDescription || toolName}>${toolName}</span>`;
                                  })}
                                </div>
                              `
                            : html`<div className="module-empty">此插件未绑定工具。</div>`}
                          <div className="avatar-capability-list">
                            ${(selectedAvatarModule.capabilityTags || []).length
                              ? selectedAvatarModule.capabilityTags.map(
                                  (tag) => html`<span key=${`${selectedAvatarModule.key}-${tag}`} className="capability-chip">${tag}</span>`,
                                )
                              : html`<span className="capability-chip plain">暂无标签</span>`}
                          </div>
                          ${selectedAvatarModule.description
                            ? html`<div className="avatar-detail-desc">${selectedAvatarModule.description}</div>`
                            : null}
                          <div className="plugin-run-box">
                            <div className="plugin-run-title">独立运行插件</div>
                            <textarea
                              className="plugin-run-input"
                              value=${pluginRunInput}
                              onInput=${(event) => setPluginRunInput(event.currentTarget.value)}
                              placeholder="输入一条测试指令，例如：请给出你的执行计划。"
                              disabled=${pluginRunPending || !selectedAvatarModule.independentRunnable}
                            ></textarea>
                            <button
                              className="ghost"
                              type="button"
                              onClick=${handleRunSelectedPlugin}
                              disabled=${pluginRunPending || !selectedAvatarModule.independentRunnable}
                            >
                              ${pluginRunPending ? "运行中..." : "运行该插件"}
                            </button>
                            ${!selectedAvatarModule.independentRunnable
                              ? html`<div className="module-empty">当前模块不支持独立运行。</div>`
                              : null}
                            ${pluginRunResult
                              ? html`
                                  <div className="plugin-run-result ${pluginRunResult.ok ? "ok" : "bad"}">
                                    <div className="plugin-run-result-head">
                                      model=${pluginRunResult.effective_model || "-"} · tools=${(pluginRunResult.tool_events || []).length}
                                    </div>
                                    <div className="plugin-run-result-text">${pluginRunResult.ok ? String(pluginRunResult.text || "") : String(pluginRunResult.error || "运行失败")}</div>
                                  </div>
                                `
                              : null}
                          </div>
                        `
                      : html`<div className="module-empty">暂无模块信息</div>`}
                  </section>
                </div>
              </div>
            </div>
          `
        : null}
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
