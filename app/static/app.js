const ReactRuntime = window.React;
const ReactDomRuntime = window.ReactDOM;
const htmRuntime = window.htm;

if (!ReactRuntime || !ReactDomRuntime || !htmRuntime) {
  const root = document.getElementById("root");
  if (root) {
    root.innerHTML = `
      <div style="padding:24px;font:14px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;color:#1f2328;">
        前端资源加载失败。请刷新页面；如果问题持续，请检查 /static/vendor 下的本地脚本是否可访问。
      </div>
    `;
  }
  throw new Error("Local frontend vendor scripts are unavailable.");
}

const { useEffect, useMemo, useRef, useState } = ReactRuntime;
const { createRoot } = ReactDomRuntime;
const html = htmRuntime.bind(ReactRuntime.createElement);

const SESSION_STORAGE_KEY = "vintage_programmer.session_id";
const PROJECT_STORAGE_KEY = "vintage_programmer.project_id";
const PROVIDER_STORAGE_KEY = "vintage_programmer.last_provider";
const MODEL_STORAGE_KEY = "vintage_programmer.last_model";
const CUSTOM_MODEL_VALUE = "__custom__";
const STARTER_PROMPTS = [
  "帮我梳理这个仓库的主链路",
  "把这个页面继续改得更像 Codex",
  "给我一个针对当前工作区的重构计划",
];
const WORKBENCH_TABS = ["run", "tools", "skills", "agent", "settings"];
const DEFAULT_SETTINGS = {
  provider: "",
  model: "",
  max_output_tokens: 128000,
  max_context_turns: 2000,
  enable_tools: true,
  response_style: "normal",
};

function createMessage(role, text, options = {}) {
  return {
    id: options.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    pending: Boolean(options.pending),
    error: Boolean(options.error),
    createdAt: options.createdAt || "",
  };
}

function createLog(type, text) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type,
    text,
    createdAt: new Date().toISOString(),
  };
}

function sessionStorageKeyForProject(projectId) {
  const normalized = String(projectId || "").trim() || "__default__";
  return `${SESSION_STORAGE_KEY}:${normalized}`;
}

function modelStorageKeyForProvider(provider) {
  const normalized = String(provider || "").trim() || "__default__";
  return `${MODEL_STORAGE_KEY}:${normalized}`;
}

function dedupeStrings(values) {
  const result = [];
  const seen = new Set();
  (Array.isArray(values) ? values : []).forEach((value) => {
    const normalized = String(value || "").trim();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    result.push(normalized);
  });
  return result;
}

function resolvePresetModelValue(model, modelOptions, allowCustomModel) {
  const normalizedModel = String(model || "").trim();
  const options = dedupeStrings(modelOptions);
  if (normalizedModel && options.includes(normalizedModel)) return normalizedModel;
  if (normalizedModel && allowCustomModel) return CUSTOM_MODEL_VALUE;
  return options[0] || (allowCustomModel ? CUSTOM_MODEL_VALUE : "");
}

function pushLogWithLimit(setter, type, text) {
  setter((prev) => [createLog(type, text), ...prev].slice(0, 32));
}

function formatTime(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parseSseChunk(chunk) {
  const lines = String(chunk || "").split("\n");
  let event = "message";
  const dataLines = [];
  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim() || "message";
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  });
  if (!dataLines.length) return null;
  try {
    return { event, payload: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { event, payload: { raw: dataLines.join("\n") } };
  }
}

function roleLabel(role) {
  if (role === "user") return "You";
  if (role === "assistant") return "Vintage Programmer";
  return "System";
}

function fileNameFromHealth(health) {
  const label = String(((health || {}).runtime_status || {}).workspace_label || "").trim();
  if (label) return label;
  const path = String((health && health.workspace_root) || "").trim();
  if (!path) return "workspace";
  const parts = path.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || "workspace";
}

function compactPath(path) {
  const text = String(path || "").trim();
  if (!text) return "";
  if (text.length <= 64) return text;
  return `${text.slice(0, 24)} … ${text.slice(-32)}`;
}

function stringifyErrorDetail(detail) {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  try {
    return JSON.stringify(detail, null, 2);
  } catch {
    return String(detail);
  }
}

function normalizeUiError(source, fallbackSummary = "请求失败，请稍后重试。", fallback = {}) {
  if (source && typeof source === "object" && source.uiError) {
    return { ...source.uiError };
  }
  let payload = source;
  if (payload && typeof payload === "object" && payload.detail && typeof payload.detail === "object" && !payload.kind && !payload.summary) {
    payload = payload.detail;
  }
  const detail = stringifyErrorDetail(
    payload && typeof payload === "object" && Object.prototype.hasOwnProperty.call(payload, "detail")
      ? payload.detail
      : payload,
  );
  const provider =
    String(
      (payload && typeof payload === "object" && (
        payload.provider ||
        payload.provider_name ||
        ((payload.metadata || {}).provider_name) ||
        (((payload.error || {}).metadata || {}).provider_name)
      )) ||
      fallback.provider ||
      "",
    ).trim();
  const explicitStatus =
    Number(
      (payload && typeof payload === "object" && (
        payload.status_code ||
        payload.statusCode ||
        payload.code ||
        ((payload.error || {}).code)
      )) ||
      fallback.status_code ||
      fallback.statusCode ||
      0,
    ) || 0;
  const lowered = `${detail}\n${provider}`.toLowerCase();
  let kind = String((payload && typeof payload === "object" && payload.kind) || fallback.kind || "").trim();
  if (!kind) {
    if (explicitStatus === 429 || lowered.includes("rate limit") || lowered.includes("rate-limit") || lowered.includes("temporarily rate-limited upstream") || lowered.includes("too many requests")) {
      kind = "rate_limit";
    } else if ([401, 403].includes(explicitStatus) || lowered.includes("unauthorized") || lowered.includes("forbidden") || lowered.includes("api key") || lowered.includes("credentials") || lowered.includes("authentication")) {
      kind = "auth";
    } else if ([502, 503, 504].includes(explicitStatus) || lowered.includes("temporarily unavailable") || lowered.includes("timeout") || lowered.includes("timed out") || lowered.includes("upstream")) {
      kind = "upstream";
    } else {
      kind = "unknown";
    }
  }
  const status_code =
    explicitStatus ||
    (kind === "rate_limit" ? 429 : kind === "auth" ? 401 : kind === "upstream" ? 503 : 500);
  const summary =
    String((payload && typeof payload === "object" && payload.summary) || "").trim() ||
    (kind === "rate_limit"
      ? "模型提供方限流，请稍后重试。"
      : kind === "auth"
        ? "认证失败，请检查 OpenRouter / OpenAI-compatible key。"
        : kind === "upstream"
          ? "模型提供方暂时不可用，请稍后重试。"
          : fallbackSummary);
  const retryable =
    typeof (payload && typeof payload === "object" && payload.retryable) === "boolean"
      ? Boolean(payload.retryable)
      : ["rate_limit", "upstream"].includes(kind);
  return {
    kind,
    status_code,
    summary,
    detail: detail || summary,
    retryable,
    provider,
  };
}

function errorWithUiError(uiError) {
  const error = new Error(String((uiError && uiError.summary) || "请求失败，请稍后重试。"));
  error.uiError = uiError;
  return error;
}

function projectLabel(project, fallbackHealth) {
  if (project && project.title) return String(project.title);
  return fileNameFromHealth(fallbackHealth);
}

function extractSessionMessages(data) {
  const turns = Array.isArray(data.turns) ? data.turns : [];
  return turns.map((turn) =>
    createMessage(
      String(turn.role || "").toLowerCase() === "user" ? "user" : "assistant",
      String(turn.text || ""),
      { createdAt: String(turn.created_at || "") },
    ),
  );
}

function defaultSkillTemplate() {
  return [
    "---",
    "id: new_skill",
    "title: New Skill",
    "enabled: false",
    "bind_to:",
    "  - vintage_programmer",
    "summary: One-line summary for this skill.",
    "---",
    "",
    "# New Skill",
    "",
    "适用场景：",
    "- 说明什么时候使用这个 skill。",
    "",
    "执行要求：",
    "- 列出这个 skill 的步骤和边界。",
    "",
  ].join("\n");
}

function sessionTitleFromList(sessions, sessionId) {
  const hit = sessions.find((item) => item.session_id === sessionId);
  return hit ? hit.title || "新线程" : "开始构建";
}

function shallowSkillList(skills) {
  return Array.isArray(skills) ? skills : [];
}

function groupTools(tools) {
  const grouped = {};
  (Array.isArray(tools) ? tools : []).forEach((item) => {
    const group = String(item.group || "other");
    if (!grouped[group]) grouped[group] = [];
    grouped[group].push(item);
  });
  return grouped;
}

function starterPromptChips(setDraft, handleSend) {
  return STARTER_PROMPTS.map((text) =>
    html`
      <button
        key=${text}
        className="starter-chip"
        type="button"
        onClick=${() => {
          setDraft(text);
          setTimeout(() => handleSend(text), 0);
        }}
      >
        ${text}
      </button>
    `,
  );
}

function App() {
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [sessionAgentState, setSessionAgentState] = useState({});
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [drawerView, setDrawerView] = useState("");
  const [logs, setLogs] = useState([]);
  const [lastResponse, setLastResponse] = useState(null);
  const [pendingUploads, setPendingUploads] = useState([]);
  const [chatSettings, setChatSettings] = useState(DEFAULT_SETTINGS);
  const [modelTouched, setModelTouched] = useState(false);
  const [selectedPresetModel, setSelectedPresetModel] = useState("");
  const [uiError, setUiError] = useState(null);
  const [toolTimeline, setToolTimeline] = useState([]);
  const [stageTimeline, setStageTimeline] = useState([]);
  const [workbenchTools, setWorkbenchTools] = useState([]);
  const [skills, setSkills] = useState([]);
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [skillEditor, setSkillEditor] = useState("");
  const [specs, setSpecs] = useState([]);
  const [selectedSpecName, setSelectedSpecName] = useState("soul.md");
  const [specEditor, setSpecEditor] = useState("");
  const [savingWorkbench, setSavingWorkbench] = useState(false);
  const [mobileThreadsOpen, setMobileThreadsOpen] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectPathDraft, setProjectPathDraft] = useState("");
  const [projectTitleDraft, setProjectTitleDraft] = useState("");
  const [projectFormError, setProjectFormError] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const fileInputRef = useRef(null);
  const chatListRef = useRef(null);
  const bootReadyRef = useRef(false);
  const providerOptions = useMemo(
    () => (Array.isArray((health && health.provider_options)) ? health.provider_options : []).filter((item) => item && item.provider),
    [health],
  );
  const availableProviders = useMemo(
    () => dedupeStrings([
      ...providerOptions.map((item) => String(item.provider || "").trim()),
      String((health && health.llm_provider) || "").trim(),
    ]),
    [health, providerOptions],
  );
  const activeProvider = String(
    chatSettings.provider ||
    (availableProviders.includes(String((health && health.llm_provider) || "").trim()) ? String((health && health.llm_provider) || "").trim() : "") ||
    availableProviders[0] ||
    "default",
  ).trim() || "default";
  const activeProviderProfile =
    providerOptions.find((item) => String(item.provider || "").trim() === activeProvider) ||
    providerOptions[0] ||
    null;
  const modelOptions = useMemo(
    () => dedupeStrings([
      ...(Array.isArray(activeProviderProfile && activeProviderProfile.model_options) ? activeProviderProfile.model_options : []),
      String((activeProviderProfile && activeProviderProfile.default_model) || (health && health.default_model) || "").trim(),
    ]),
    [activeProviderProfile, health],
  );
  const allowCustomModel = !health || health.allow_custom_model !== false;

  useEffect(() => {
    if (!bootReadyRef.current) return;
    if (!projectId) {
      window.localStorage.removeItem(PROJECT_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId);
  }, [projectId]);

  useEffect(() => {
    if (!bootReadyRef.current) return;
    if (!projectId) return;
    const storageKey = sessionStorageKeyForProject(projectId);
    if (!sessionId) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(storageKey, sessionId);
  }, [projectId, sessionId]);

  useEffect(() => {
    if (!health) return;
    const storedProvider = window.localStorage.getItem(PROVIDER_STORAGE_KEY) || "";
    const currentProvider = String(chatSettings.provider || "").trim();
    const preferredProvider =
      (storedProvider && availableProviders.includes(storedProvider) ? storedProvider : "") ||
      (currentProvider && availableProviders.includes(currentProvider) ? currentProvider : "") ||
      String((health && health.llm_provider) || "").trim() ||
      availableProviders[0] ||
      "";
    if (!preferredProvider) return;
    setChatSettings((prev) => (
      String(prev.provider || "").trim() === preferredProvider
        ? prev
        : { ...prev, provider: preferredProvider }
    ));
  }, [health, availableProviders, chatSettings.provider]);

  useEffect(() => {
    if (!bootReadyRef.current) return;
    const resolvedProvider = String(chatSettings.provider || "").trim();
    if (!resolvedProvider) {
      window.localStorage.removeItem(PROVIDER_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(PROVIDER_STORAGE_KEY, resolvedProvider);
  }, [chatSettings.provider]);

  useEffect(() => {
    if (!health || modelTouched) return;
    const storedModel = window.localStorage.getItem(modelStorageKeyForProvider(activeProvider)) || "";
    const preferredModel = String(
      storedModel ||
      chatSettings.model ||
      (activeProviderProfile && activeProviderProfile.default_model) ||
      (health && health.default_model) ||
      modelOptions[0] ||
      "",
    ).trim();
    if (!preferredModel) return;
    setChatSettings((prev) => (
      String(prev.model || "").trim() === preferredModel
        ? prev
        : { ...prev, model: preferredModel }
    ));
    setSelectedPresetModel(resolvePresetModelValue(preferredModel, modelOptions, allowCustomModel));
  }, [health, modelTouched, activeProvider, activeProviderProfile, allowCustomModel, modelOptions, chatSettings.model]);

  useEffect(() => {
    const resolvedModel = String(chatSettings.model || "").trim();
    const storageKey = modelStorageKeyForProvider(activeProvider);
    if (!resolvedModel) {
      window.localStorage.removeItem(storageKey);
      setSelectedPresetModel(resolvePresetModelValue("", modelOptions, allowCustomModel));
      return;
    }
    window.localStorage.setItem(storageKey, resolvedModel);
    setSelectedPresetModel((prev) => {
      const nextValue = resolvePresetModelValue(resolvedModel, modelOptions, allowCustomModel);
      return prev === nextValue ? prev : nextValue;
    });
  }, [activeProvider, allowCustomModel, chatSettings.model, modelOptions]);

  useEffect(() => {
    if (!chatListRef.current) return;
    chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
  }, [messages, drawerView]);

  useEffect(() => {
    async function boot() {
      const [healthData, projectsList] = await Promise.all([
        refreshHealth(),
        refreshProjects(),
        refreshWorkbenchTools(),
        refreshSkills(),
        refreshSpecs(),
      ]);
      const storedProjectId = window.localStorage.getItem(PROJECT_STORAGE_KEY) || "";
      const storedProjectExists = (projectsList || []).some((item) => String(item.project_id || "") === storedProjectId);
      const initialProjectId =
        (storedProjectExists ? storedProjectId : "") ||
        String((healthData && healthData.default_project_id) || "").trim() ||
        String(((projectsList || [])[0] || {}).project_id || "").trim();
      bootReadyRef.current = true;
      if (initialProjectId) {
        await selectProject(initialProjectId, { silentNotFound: true, fromBoot: true });
      }
    }
    boot();
  }, []);

  useEffect(() => {
    if (drawerView === "tools") refreshWorkbenchTools();
    if (drawerView === "skills") refreshSkills();
    if (drawerView === "agent") refreshSpecs();
  }, [drawerView]);

  function clearUiError() {
    setUiError(null);
  }

  function applyUiError(errorLike, fallbackSummary = "请求失败，请稍后重试。", fallback = {}) {
    const normalized = normalizeUiError(errorLike, fallbackSummary, fallback);
    setUiError(normalized);
    return normalized;
  }

  function updateModelSelection(nextModel, options = {}) {
    const normalized = String(nextModel || "").trim();
    if (options.markTouched !== false) setModelTouched(true);
    setChatSettings((prev) => ({ ...prev, model: normalized }));
    setSelectedPresetModel(resolvePresetModelValue(normalized, modelOptions, allowCustomModel));
  }

  function updateProviderSelection(nextProvider) {
    const normalized = String(nextProvider || "").trim();
    if (!normalized) return;
    const nextProfile =
      providerOptions.find((item) => String(item.provider || "").trim() === normalized) ||
      null;
    const nextModelOptions = dedupeStrings([
      ...(Array.isArray(nextProfile && nextProfile.model_options) ? nextProfile.model_options : []),
      String((nextProfile && nextProfile.default_model) || "").trim(),
    ]);
    const storedModel = window.localStorage.getItem(modelStorageKeyForProvider(normalized)) || "";
    const nextModel = String(storedModel || (nextProfile && nextProfile.default_model) || nextModelOptions[0] || "").trim();
    setModelTouched(false);
    setChatSettings((prev) => ({ ...prev, provider: normalized, model: nextModel }));
    setSelectedPresetModel(resolvePresetModelValue(nextModel, nextModelOptions, allowCustomModel));
  }

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
      let payload = null;
      try {
        payload = await res.json();
      } catch {
        payload = { detail: `${res.status}` };
      }
      const uiError = normalizeUiError(
        payload && Object.prototype.hasOwnProperty.call(payload, "detail") ? payload.detail : payload,
        "请求失败，请稍后重试。",
        { status_code: res.status },
      );
      throw errorWithUiError(uiError);
    }
    return res.json();
  }

  async function refreshHealth() {
    try {
      const data = await fetchJson("/api/health");
      clearUiError();
      setHealth(data);
      return data;
    } catch (err) {
      const nextError = applyUiError(err, "刷新状态失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `刷新状态失败：${nextError.summary}`);
      return null;
    }
  }

  async function refreshProjects() {
    try {
      const data = await fetchJson("/api/projects");
      const list = Array.isArray(data.projects) ? data.projects : [];
      clearUiError();
      setProjects(list);
      return list;
    } catch (err) {
      const nextError = applyUiError(err, "刷新项目失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `刷新项目失败：${nextError.summary}`);
      return [];
    }
  }

  async function refreshSessions(targetProjectId = projectId) {
    try {
      const suffix = targetProjectId ? `&project_id=${encodeURIComponent(targetProjectId)}` : "";
      const data = await fetchJson(`/api/sessions?limit=80${suffix}`);
      const list = Array.isArray(data.sessions) ? data.sessions : [];
      clearUiError();
      setSessions(list);
      return list;
    } catch (err) {
      const nextError = applyUiError(err, "刷新线程失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `刷新线程失败：${nextError.summary}`);
      return [];
    }
  }

  async function selectProject(nextProjectId, options = {}) {
    const targetProjectId = String(nextProjectId || "").trim();
    if (!targetProjectId) return false;
    setProjectId(targetProjectId);
    setSessionId("");
    setMessages([]);
    setLastResponse(null);
    setSessionAgentState({});
    setToolTimeline([]);
    setStageTimeline([]);
    setMobileThreadsOpen(false);
    clearUiError();
    const list = await refreshSessions(targetProjectId);
    const storedSessionId = window.localStorage.getItem(sessionStorageKeyForProject(targetProjectId)) || "";
    const preferredSessionId =
      storedSessionId && list.some((item) => item.session_id === storedSessionId)
        ? storedSessionId
        : String(((list || [])[0] || {}).session_id || "").trim();
    if (preferredSessionId) {
      await loadSession(preferredSessionId, { silentNotFound: Boolean(options.silentNotFound), projectIdOverride: targetProjectId });
      return true;
    }
    if (!options.fromBoot) {
      pushLogWithLimit(setLogs, "system", `已切换项目 ${targetProjectId.slice(0, 8)}`);
    }
    return true;
  }

  async function refreshWorkbenchTools() {
    try {
      const data = await fetchJson("/api/workbench/tools");
      clearUiError();
      setWorkbenchTools(Array.isArray(data.tools) ? data.tools : []);
      return data;
    } catch (err) {
      const nextError = applyUiError(err, "刷新工具库存失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `刷新工具库存失败：${nextError.summary}`);
      return null;
    }
  }

  async function refreshSkills() {
    try {
      const data = await fetchJson("/api/workbench/skills");
      const list = shallowSkillList(data.skills);
      clearUiError();
      setSkills(list);
      if (!selectedSkillId && list.length) {
        setSelectedSkillId(String(list[0].id || ""));
        setSkillEditor(String(list[0].content || ""));
      }
      if (selectedSkillId) {
        const hit = list.find((item) => item.id === selectedSkillId);
        if (hit) setSkillEditor(String(hit.content || ""));
      }
      return list;
    } catch (err) {
      const nextError = applyUiError(err, "刷新技能失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `刷新技能失败：${nextError.summary}`);
      return [];
    }
  }

  async function refreshSpecs() {
    try {
      const data = await fetchJson("/api/workbench/specs");
      const list = Array.isArray(data.specs) ? data.specs : [];
      clearUiError();
      setSpecs(list);
      const preferred = list.find((item) => item.name === selectedSpecName) || list[0];
      if (preferred) {
        await loadSpecDetail(String(preferred.name || ""));
      }
      return list;
    } catch (err) {
      const nextError = applyUiError(err, "刷新 agent 规范失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `刷新 agent 规范失败：${nextError.summary}`);
      return [];
    }
  }

  async function createProjectFromDraft() {
    const rootPath = String(projectPathDraft || "").trim();
    const title = String(projectTitleDraft || "").trim();
    if (!rootPath) {
      setProjectFormError("请输入本地绝对路径。");
      return;
    }
    setSavingProject(true);
    setProjectFormError("");
    try {
      const payload = await fetchJson("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root_path: rootPath, title }),
      });
      await refreshHealth();
      await refreshProjects();
      clearUiError();
      setProjectDialogOpen(false);
      setProjectPathDraft("");
      setProjectTitleDraft("");
      await selectProject(String(payload.project_id || ""));
      pushLogWithLimit(setLogs, "system", `已添加项目：${payload.title || payload.project_id}`);
    } catch (err) {
      const nextError = applyUiError(err, "添加项目失败，请检查项目路径。");
      setProjectFormError(nextError.summary);
      pushLogWithLimit(setLogs, "error", `添加项目失败：${nextError.summary}`);
    } finally {
      setSavingProject(false);
    }
  }

  async function createSession(targetProjectId = projectId) {
    const data = await fetchJson("/api/session/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: targetProjectId || "" }),
    });
    const sid = String(data.session_id || "").trim();
    const resolvedProjectId = String(data.project_id || targetProjectId || "").trim();
    if (!sid) throw new Error("session id missing");
    if (resolvedProjectId) setProjectId(resolvedProjectId);
    setSessionId(sid);
    setMessages([]);
    setLastResponse(null);
    setSessionAgentState({});
    setToolTimeline([]);
    setStageTimeline([]);
    clearUiError();
    await refreshSessions(resolvedProjectId || targetProjectId);
    pushLogWithLimit(setLogs, "system", `已创建新线程 ${sid.slice(0, 8)}`);
    return sid;
  }

  async function loadSession(targetSessionId, options = {}) {
    const sid = String(targetSessionId || "").trim();
    if (!sid) return false;
    setLoadingSession(true);
    setMobileThreadsOpen(false);
    try {
      const data = await fetchJson(`/api/session/${encodeURIComponent(sid)}?max_turns=120`);
      setMessages(extractSessionMessages(data));
      setSessionAgentState((data && data.agent_state) || {});
      setSessionId(sid);
      if (data && data.project_id) {
        setProjectId(String(data.project_id || ""));
      } else if (options.projectIdOverride) {
        setProjectId(String(options.projectIdOverride || ""));
      }
      setLastResponse(null);
      setToolTimeline([]);
      setStageTimeline([]);
      clearUiError();
      pushLogWithLimit(setLogs, "system", `已载入线程 ${sid.slice(0, 8)}`);
      return true;
    } catch (err) {
      if (options.silentNotFound && String(err.message || "").includes("404")) return false;
      const nextError = applyUiError(err, "载入线程失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `载入线程失败：${nextError.summary}`);
      return false;
    } finally {
      setLoadingSession(false);
    }
  }

  async function handleNewSession() {
    try {
      await createSession(projectId);
    } catch (err) {
      const nextError = applyUiError(err, "新线程创建失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `新线程失败：${nextError.summary}`);
    }
  }

  async function uploadFiles(files) {
    const uploaded = [];
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      uploaded.push(await fetchJson("/api/upload", { method: "POST", body: form }));
    }
    return uploaded;
  }

  async function handleSelectFiles(event) {
    const files = Array.from(event.currentTarget.files || []);
    if (!files.length) return;
    try {
      const uploaded = await uploadFiles(files);
      clearUiError();
      setPendingUploads((prev) => [...prev, ...uploaded]);
      pushLogWithLimit(setLogs, "system", `已添加 ${uploaded.length} 个附件`);
    } catch (err) {
      const nextError = applyUiError(err, "附件上传失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `附件上传失败：${nextError.summary}`);
    } finally {
      event.currentTarget.value = "";
    }
  }

  function removeUpload(fileId) {
    setPendingUploads((prev) => prev.filter((item) => item.id !== fileId));
  }

  async function handleSend(overrideText) {
    const messageText = String(overrideText != null ? overrideText : draft).trim();
    if (!messageText || sending) return;

    setSending(true);
    clearUiError();
    setToolTimeline([]);
    setStageTimeline([]);

    let sid = sessionId;
    let pendingMessage = null;
    try {
      if (!sid) sid = await createSession(projectId);

      const userMessage = createMessage("user", messageText);
      pendingMessage = createMessage("assistant", "正在准备上下文...", { pending: true });
      setMessages((prev) => [...prev, userMessage, pendingMessage]);
      if (overrideText == null) setDraft("");

      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sid,
          project_id: projectId,
          message: messageText,
          attachment_ids: pendingUploads.map((item) => item.id),
          settings: {
            ...chatSettings,
            provider: activeProvider,
            model: String(
              chatSettings.model ||
              (activeProviderProfile && activeProviderProfile.default_model) ||
              (health && health.default_model) ||
              "",
            ).trim(),
          },
        }),
      });
      if (!res.ok) {
        let payload = null;
        try {
          payload = await res.json();
        } catch {
          payload = { detail: `stream ${res.status}` };
        }
        throw errorWithUiError(
          normalizeUiError(
            payload && Object.prototype.hasOwnProperty.call(payload, "detail") ? payload.detail : payload,
            "请求失败，请稍后重试。",
            { status_code: res.status },
          ),
        );
      }
      if (!res.body) {
        throw errorWithUiError(normalizeUiError({ detail: "stream body unavailable" }, "请求失败，请稍后重试。"));
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload = null;

      const replacePendingText = (text) => {
        setMessages((prev) =>
          prev.map((item) => (item.id === pendingMessage.id ? { ...item, text } : item)),
        );
      };

      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        let splitIndex = buffer.indexOf("\n\n");
        while (splitIndex >= 0) {
          const chunk = buffer.slice(0, splitIndex);
          buffer = buffer.slice(splitIndex + 2);
          const parsed = parseSseChunk(chunk);
          if (parsed) {
            const { event, payload } = parsed;
            if (event === "stage") {
              const detail = String(payload.detail || payload.label || payload.code || "处理中...");
              replacePendingText(detail);
              setStageTimeline((prev) => [
                {
                  id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                  phase: String(payload.phase || payload.code || ""),
                  label: String(payload.label || payload.phase || payload.code || "stage"),
                  status: String(payload.status || "running"),
                  detail,
                },
                ...prev,
              ].slice(0, 20));
              pushLogWithLimit(setLogs, "stage", detail);
            } else if (event === "trace") {
              const detail = String(payload.message || payload.raw || "");
              if (detail) pushLogWithLimit(setLogs, "trace", detail);
            } else if (event === "tool") {
              const item = payload.item || {};
              const name = String(item.name || "tool");
              const summary = String(payload.summary || item.summary || item.output_preview || "工具调用");
              setToolTimeline((prev) => [item, ...prev].slice(0, 24));
              pushLogWithLimit(setLogs, "tool", `${name}: ${summary}`);
            } else if (event === "final") {
              finalPayload = payload.response || null;
            } else if (event === "error") {
              throw errorWithUiError(normalizeUiError(payload, "请求失败，请稍后重试。"));
            }
          }
          splitIndex = buffer.indexOf("\n\n");
        }
        if (done) break;
      }

      if (!finalPayload) throw new Error("missing final payload");
      setMessages((prev) =>
        prev.map((item) =>
          item.id === pendingMessage.id
            ? createMessage("assistant", String(finalPayload.text || "(empty response)"))
            : item,
        ),
      );
      setLastResponse(finalPayload);
      setPendingUploads([]);
      clearUiError();
      setSessionAgentState({
        ...(finalPayload.inspector || {}).run_state,
        ...(finalPayload.inspector || {}).evidence,
        ...(finalPayload.inspector || {}).session,
        ...{
          agent_id: finalPayload.agent_id || "vintage_programmer",
          goal: String((((finalPayload.inspector || {}).run_state || {}).goal) || messageText),
          current_goal: String((((finalPayload.inspector || {}).run_state || {}).goal) || messageText),
          phase: String((((finalPayload.inspector || {}).run_state || {}).phase) || "report"),
          last_run_id: String(finalPayload.run_id || ""),
          last_model: String(finalPayload.effective_model || ""),
          tool_hits: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events : [],
          tool_count: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0,
          evidence_status: String((((finalPayload.inspector || {}).evidence || {}).status) || "not_needed"),
          enabled_skill_ids: Array.isArray((finalPayload.inspector || {}).loaded_skills)
            ? finalPayload.inspector.loaded_skills.map((item) => item.id)
            : [],
        },
      });
      pushLogWithLimit(
        setLogs,
        "response",
        `收到回复，工具 ${Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0} 次`,
      );
      await Promise.all([refreshSessions(projectId), refreshHealth(), refreshWorkbenchTools(), refreshSkills(), refreshProjects()]);
    } catch (err) {
      const nextError = applyUiError(err, "请求失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `发送失败：${nextError.summary}`);
      setMessages((prev) => prev.filter((item) => !(pendingMessage && item.id === pendingMessage.id)));
    } finally {
      setSending(false);
    }
  }

  async function loadSkillDetail(skillId) {
    const sid = String(skillId || "").trim();
    if (!sid) return;
    try {
      const payload = await fetchJson(`/api/workbench/skills/${encodeURIComponent(sid)}`);
      clearUiError();
      setSelectedSkillId(sid);
      setSkillEditor(String(payload.content || ""));
    } catch (err) {
      const nextError = applyUiError(err, "读取技能失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `读取技能失败：${nextError.summary}`);
    }
  }

  async function loadSpecDetail(name) {
    const specName = String(name || "").trim();
    if (!specName) return;
    try {
      const payload = await fetchJson(`/api/workbench/specs/${encodeURIComponent(specName)}`);
      clearUiError();
      setSelectedSpecName(specName);
      setSpecEditor(String(payload.content || ""));
    } catch (err) {
      const nextError = applyUiError(err, "读取规范失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `读取规范失败：${nextError.summary}`);
    }
  }

  async function saveSkill() {
    if (!skillEditor.trim()) return;
    setSavingWorkbench(true);
    try {
      const method = selectedSkillId ? "PUT" : "POST";
      const url = selectedSkillId
        ? `/api/workbench/skills/${encodeURIComponent(selectedSkillId)}`
        : "/api/workbench/skills";
      const payload = await fetchJson(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: skillEditor }),
      });
      setSelectedSkillId(String(payload.id || ""));
      setSkillEditor(String(payload.content || ""));
      await Promise.all([refreshSkills(), refreshHealth()]);
      clearUiError();
      pushLogWithLimit(setLogs, "system", `技能已保存：${payload.id || selectedSkillId || "new_skill"}`);
    } catch (err) {
      const nextError = applyUiError(err, "保存技能失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `保存技能失败：${nextError.summary}`);
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function toggleSelectedSkill(nextEnabled) {
    if (!selectedSkillId) return;
    setSavingWorkbench(true);
    try {
      const payload = await fetchJson(`/api/workbench/skills/${encodeURIComponent(selectedSkillId)}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      setSkillEditor(String(payload.content || ""));
      await Promise.all([refreshSkills(), refreshHealth()]);
      clearUiError();
      pushLogWithLimit(setLogs, "system", `技能已${payload.enabled ? "启用" : "停用"}：${selectedSkillId}`);
    } catch (err) {
      const nextError = applyUiError(err, "切换技能失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `切换技能失败：${nextError.summary}`);
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function saveSpec() {
    if (!selectedSpecName || !specEditor.trim()) return;
    setSavingWorkbench(true);
    try {
      const payload = await fetchJson(`/api/workbench/specs/${encodeURIComponent(selectedSpecName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: specEditor }),
      });
      setSpecEditor(String(payload.content || ""));
      await Promise.all([refreshSpecs(), refreshHealth()]);
      clearUiError();
      pushLogWithLimit(setLogs, "system", `规范已保存：${selectedSpecName}`);
    } catch (err) {
      const nextError = applyUiError(err, "保存规范失败，请稍后重试。");
      pushLogWithLimit(setLogs, "error", `保存规范失败：${nextError.summary}`);
    } finally {
      setSavingWorkbench(false);
    }
  }

  function handleComposerKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  }

  const runtimeStatus = (health && health.runtime_status) || {};
  const currentProject =
    projects.find((item) => String(item.project_id || "") === String(projectId || "")) ||
    projects[0] ||
    null;
  const workspaceLabel = projectLabel(currentProject, health);
  const currentProjectRoot = String((currentProject && currentProject.root_path) || runtimeStatus.project_root || "").trim();
  const currentProjectBranch = String((currentProject && currentProject.git_branch) || runtimeStatus.git_branch || "").trim();
  const agentInfo = (lastResponse && lastResponse.inspector && lastResponse.inspector.agent) || (health && health.agent) || {};
  const loadedSkills = Array.isArray((lastResponse && lastResponse.inspector && lastResponse.inspector.loaded_skills))
    ? lastResponse.inspector.loaded_skills
    : Array.isArray((health && health.agent && health.agent.loaded_skills))
      ? health.agent.loaded_skills
      : [];
  const lastInspector = (lastResponse && lastResponse.inspector) || {};
  const runState = lastInspector.run_state || {};
  const evidence = lastInspector.evidence || {};
  const activeToolTimeline = Array.isArray(lastInspector.tool_timeline) && lastInspector.tool_timeline.length
    ? lastInspector.tool_timeline
    : toolTimeline;
  const activeProviderAuthReady =
    activeProviderProfile && Object.prototype.hasOwnProperty.call(activeProviderProfile, "auth_ready")
      ? Boolean(activeProviderProfile.auth_ready)
      : Boolean(runtimeStatus.auth_ready);
  const activeProviderAuthMode = String(
    (activeProviderProfile && activeProviderProfile.auth_mode) ||
    runtimeStatus.auth_mode ||
    "",
  ).trim();
  const activeModel = String(
    (lastResponse && lastResponse.effective_model) ||
    chatSettings.model ||
    (activeProviderProfile && activeProviderProfile.default_model) ||
    (health && health.default_model) ||
    "",
  ).trim();
  const activeProviderLabel = String((activeProviderProfile && activeProviderProfile.label) || activeProvider || "").trim();
  const groupedTools = useMemo(() => groupTools(workbenchTools), [workbenchTools]);
  const selectedSkill = skills.find((item) => item.id === selectedSkillId) || null;
  const headTitle = sessionId ? sessionTitleFromList(sessions, sessionId) : (workspaceLabel || "开始构建");
  const headBreadcrumb = [
    workspaceLabel || "",
    currentProjectRoot ? compactPath(currentProjectRoot) : "",
    currentProjectBranch || "",
    loadedSkills.length ? `skills:${loadedSkills.length}` : "no skills",
  ].filter(Boolean).join(" · ");
  const statusSummary = [
    workspaceLabel || "-",
    activeProviderLabel || activeProvider || "-",
    activeModel || "-",
  ].filter(Boolean).join(" · ");

  return html`
    <div className="workspace-shell" id="appShell">
      <aside className=${`thread-rail ${mobileThreadsOpen ? "mobile-open" : ""}`} id="threadSidebar">
        <div className="rail-brand">
          <div className="brand-mark">VP</div>
          <div>
            <div className="brand-title">Vintage Programmer</div>
            <div className="brand-sub">${workspaceLabel || "选择一个项目开始工作"}</div>
          </div>
          <button className="rail-close mobile-only" type="button" onClick=${() => setMobileThreadsOpen(false)}>×</button>
        </div>

        <div className="rail-actions">
          <button className="solid-btn" type="button" onClick=${handleNewSession} disabled=${loadingSession || sending}>新线程</button>
          <button className="ghost-btn" type="button" onClick=${() => refreshSessions(projectId)} disabled=${loadingSession || sending}>刷新</button>
        </div>

        <section className="rail-section" id="projectSection">
          <div className="section-head">
            <span>Projects</span>
            <button className="ghost-btn compact-btn" type="button" onClick=${() => setProjectDialogOpen(true)}>添加</button>
          </div>
          <div className="project-list">
            ${projects.length
              ? projects.map(
                  (item) => html`
                    <button
                      key=${item.project_id}
                      className=${`project-row ${item.project_id === projectId ? "active" : ""}`}
                      type="button"
                      onClick=${() => selectProject(item.project_id)}
                      disabled=${loadingSession || sending}
                    >
                      <div className="project-row-title">${item.title || item.project_id}</div>
                      <div className="project-row-meta">
                        ${compactPath(item.root_path)}
                        ${item.git_branch ? ` · ${item.git_branch}` : ""}
                        ${item.is_worktree ? " · worktree" : ""}
                      </div>
                    </button>
                  `,
                )
              : html`<div className="thread-empty">还没有项目，先添加一个本地文件夹。</div>`}
          </div>
        </section>

        <section className="rail-section rail-section-fill">
          <div className="section-head">
            <span>Threads</span>
            <span className="section-meta">${workspaceLabel || "-"}</span>
          </div>
          <div className="thread-list">
            ${sessions.length
              ? sessions.map(
                  (item) => html`
                    <button
                      key=${item.session_id}
                      className=${`thread-row ${item.session_id === sessionId ? "active" : ""}`}
                      type="button"
                      onClick=${() => loadSession(item.session_id)}
                      disabled=${loadingSession || sending}
                    >
                      <div className="thread-row-title">${item.title || "新线程"}</div>
                      <div className="thread-row-meta">${formatTime(item.updated_at)} · ${item.turn_count || 0} 轮</div>
                    </button>
                  `,
                )
              : html`<div className="thread-empty">${workspaceLabel ? `项目 ${workspaceLabel} 还没有线程。` : "先选择一个项目。"}</div>`}
          </div>
        </section>
      </aside>

      <main className="workspace-main" id="chatPane">
        <header className="workspace-head">
          <div className="head-left">
            <button className="ghost-btn mobile-only" type="button" onClick=${() => setMobileThreadsOpen(true)}>线程</button>
            <div className="head-stack">
              <div className="main-head-title">${headTitle}</div>
              <div className="main-head-sub" title=${currentProjectRoot || workspaceLabel || ""}>
                ${agentInfo.title || "Vintage Programmer"}
                ${headBreadcrumb ? ` · ${headBreadcrumb}` : ""}
              </div>
            </div>
          </div>
          <div className="head-actions">
            <button className=${`mini-btn ${drawerView === "run" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "run" ? "" : "run")}>Run</button>
            <button className=${`mini-btn ${drawerView === "tools" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "tools" ? "" : "tools")}>Tools</button>
            <button className=${`mini-btn ${drawerView === "skills" ? "active" : ""}`} type="button" onClick=${() => {
              setDrawerView(drawerView === "skills" ? "" : "skills");
              if (!skills.length) refreshSkills();
            }}>Skills</button>
            <button className=${`mini-btn ${drawerView === "agent" ? "active" : ""}`} type="button" onClick=${() => {
              setDrawerView(drawerView === "agent" ? "" : "agent");
              if (!specs.length) refreshSpecs();
            }}>Agent</button>
            <button className=${`mini-btn ${drawerView === "settings" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "settings" ? "" : "settings")}>Settings</button>
          </div>
        </header>

        <section className="conversation-plane" id="messageList" ref=${chatListRef}>
          ${messages.length
            ? messages.map(
                (item) => html`
                  <article key=${item.id} className=${`message-article role-${item.role} ${item.pending ? "pending" : ""} ${item.error ? "error" : ""}`}>
                    <div className="message-meta">
                      <span className="message-role">${roleLabel(item.role)}</span>
                      ${item.createdAt ? html`<span className="message-time">${formatTime(item.createdAt)}</span>` : null}
                    </div>
                    <div className="message-card">${item.text}</div>
                  </article>
                `,
              )
            : html`
                <section className="empty-panel">
                  <div className="empty-kicker">OpenClaw-first Tools · Codex-style Workspace</div>
                  <div className="empty-title" id="emptyPromptLine">已选择项目后可直接开线程，输入框始终在底部。</div>
                  <p className="empty-copy">
                    当前项目：
                    <strong>${workspaceLabel || "未选择"}</strong>
                    ${currentProjectRoot ? ` · ${compactPath(currentProjectRoot)}` : ""}
                    。主 agent 为 <strong>vintage_programmer</strong>，Workbench 负责 Run、Tools、Skills、Agent 和 Settings。
                  </p>
                  <div className="starter-list">${starterPromptChips(setDraft, handleSend)}</div>
                </section>
              `}
        </section>

        <section className="composer-shell" id="composerShell">
          ${pendingUploads.length
            ? html`
                <div className="attachment-strip">
                  ${pendingUploads.map(
                    (item) => html`
                      <div key=${item.id} className="attachment-chip">
                        <span>${item.name}</span>
                        <button type="button" onClick=${() => removeUpload(item.id)}>×</button>
                      </div>
                    `,
                  )}
                </div>
              `
            : null}

          ${uiError
            ? html`
                <div className=${`composer-error tone-error kind-${uiError.kind || "unknown"}`} id="composerError">
                  <div className="composer-error-main">
                    <div className="composer-error-summary">${uiError.summary}</div>
                    <div className="composer-error-meta">
                      ${uiError.status_code ? `HTTP ${uiError.status_code}` : ""}
                      ${uiError.provider ? ` · ${uiError.provider}` : ""}
                      ${uiError.retryable ? " · 可重试" : ""}
                    </div>
                  </div>
                  <div className="composer-error-actions">
                    ${uiError.detail
                      ? html`
                          <button
                            className="ghost-btn compact-btn"
                            type="button"
                            onClick=${() => {
                              if (navigator.clipboard && navigator.clipboard.writeText) {
                                navigator.clipboard.writeText(uiError.detail).catch(() => {});
                              }
                            }}
                          >
                            复制详情
                          </button>
                        `
                      : null}
                    ${uiError.detail
                      ? html`
                          <details className="composer-error-details">
                            <summary>详情</summary>
                            <pre>${uiError.detail}</pre>
                          </details>
                        `
                      : null}
                  </div>
                </div>
              `
            : null}

          <div className="composer-toolbar">
            <div className="composer-toolbar-left">
              <button className="icon-btn" type="button" onClick=${() => fileInputRef.current && fileInputRef.current.click()} disabled=${sending}>+</button>
              <input ref=${fileInputRef} type="file" multiple hidden onChange=${handleSelectFiles} />
            </div>
            <button className="ghost-btn" type="button" onClick=${() => setDrawerView(drawerView ? "" : "run")}>Workbench</button>
          </div>

          <div className="composer-frame">
            <textarea
              value=${draft}
              onInput=${(event) => setDraft(event.currentTarget.value)}
              onKeyDown=${handleComposerKeyDown}
              placeholder="给 Vintage Programmer 一个清晰任务。也可以直接贴代码、配置或长文本。Enter 发送，Shift+Enter 换行。"
              disabled=${sending}
            ></textarea>
            <button className="send-btn" type="button" onClick=${() => handleSend()} disabled=${sending || !draft.trim()}>
              ${sending ? "运行中" : "发送"}
            </button>
          </div>
          <div className="status-bar status-inline" id="statusBar">
            <div className="status-summary">${statusSummary}</div>
            <div className="status-right">
              ${currentProjectBranch ? html`<span>${currentProjectBranch}</span>` : null}
              ${!activeProviderAuthReady ? html`<span className="status-inline-note">auth missing</span>` : null}
            </div>
            ${uiError ? html`<span className="status-alert" title=${uiError.summary}>error</span>` : null}
          </div>
        </section>
      </main>

      ${projectDialogOpen
        ? html`
            <div className="project-modal-backdrop" id="projectModal">
              <div className="project-modal">
                <div className="panel-title">添加项目</div>
                <label className="form-field">
                  <span>本地绝对路径</span>
                  <input
                    className="drawer-input"
                    type="text"
                    value=${projectPathDraft}
                    placeholder="/Users/name/Desktop/my-repo"
                    onInput=${(event) => setProjectPathDraft(event.currentTarget.value)}
                    disabled=${savingProject}
                  />
                </label>
                <label className="form-field">
                  <span>显示名称（可选）</span>
                  <input
                    className="drawer-input"
                    type="text"
                    value=${projectTitleDraft}
                    placeholder="目录名将作为默认标题"
                    onInput=${(event) => setProjectTitleDraft(event.currentTarget.value)}
                    disabled=${savingProject}
                  />
                </label>
                <div className="path-hint">v1 采用路径输入 + 最近项目，不依赖系统文件夹选择器。</div>
                ${projectFormError ? html`<div className="status-error">${projectFormError}</div>` : null}
                <div className="modal-actions">
                  <button className="ghost-btn" type="button" onClick=${() => setProjectDialogOpen(false)} disabled=${savingProject}>取消</button>
                  <button className="solid-btn" type="button" onClick=${createProjectFromDraft} disabled=${savingProject}>${savingProject ? "添加中" : "添加项目"}</button>
                </div>
              </div>
            </div>
          `
        : null}

      ${drawerView
        ? html`<aside className="workbench-drawer open" id="workbenchDrawer">
        <div className="workbench-head">
          <div className="workbench-title">Workbench</div>
          <div className="workbench-tabs">
            ${WORKBENCH_TABS.map(
              (tab) => html`
                <button
                  key=${tab}
                  className=${`tab-btn ${drawerView === tab ? "active" : ""}`}
                  type="button"
                  onClick=${() => setDrawerView(tab)}
                >
                  ${tab}
                </button>
              `,
            )}
          </div>
          <button className="drawer-close" type="button" onClick=${() => setDrawerView("")}>关闭</button>
        </div>

        ${drawerView === "run"
          ? html`
              <div className="workbench-scroll">
                <section className="panel-card">
                  <div className="panel-title">Run State</div>
                  <div className="meta-line">goal: ${runState.goal || sessionAgentState.goal || sessionAgentState.current_goal || "-"}</div>
                  <div className="meta-line">phase: ${runState.phase || sessionAgentState.phase || "idle"}</div>
                  <div className="meta-line">inline_document: ${String(Boolean(runState.inline_document))}</div>
                  <div className="meta-line">evidence: ${evidence.status || sessionAgentState.evidence_status || "not_needed"}</div>
                </section>

                <section className="panel-card">
                  <div className="panel-title">Stage Timeline</div>
                  <div className="timeline-list">
                    ${stageTimeline.length
                      ? stageTimeline.map(
                          (item) => html`
                            <div key=${item.id} className="timeline-row">
                              <div className="timeline-head">
                                <span>${item.label}</span>
                                <span>${item.status}</span>
                              </div>
                              <div className="timeline-detail">${item.detail}</div>
                            </div>
                          `,
                        )
                      : html`<div className="empty-inline">本轮还没有阶段记录。</div>`}
                  </div>
                </section>

                <section className="panel-card">
                  <div className="panel-title">Recent Tools</div>
                  <div className="timeline-list">
                    ${activeToolTimeline.length
                      ? activeToolTimeline.map(
                          (item, index) => html`
                            <div key=${`${item.name || "tool"}-${index}`} className="timeline-row">
                              <div className="timeline-head">
                                <span>${item.name || "tool"}</span>
                                <span>${item.group || item.module_group || "tool"}</span>
                              </div>
                              <div className="timeline-detail">${item.summary || item.output_preview || "无摘要"}</div>
                            </div>
                          `,
                        )
                      : html`<div className="empty-inline">这一轮没有工具调用。</div>`}
                  </div>
                </section>

                <section className="panel-card">
                  <div className="panel-title">Logs</div>
                  <div className="timeline-list">
                    ${logs.length
                      ? logs.map((item) => html`<div key=${item.id} className=${`log-row tone-${item.type}`}>${item.text}</div>`)
                      : html`<div className="empty-inline">暂无额外日志。</div>`}
                  </div>
                </section>
              </div>
            `
          : null}

        ${drawerView === "tools"
          ? html`
              <div className="workbench-scroll">
                ${Object.entries(groupedTools).map(
                  ([group, items]) => html`
                    <section key=${group} className="panel-card">
                      <div className="panel-title">${group}</div>
                      <div className="tool-catalog">
                        ${items.map(
                          (item) => html`
                            <div key=${item.name} className="tool-item">
                              <div className="tool-item-head">
                                <span className="tool-name">${item.name}</span>
                                <span className="tool-source">${item.source}</span>
                              </div>
                              <div className="tool-summary">${item.summary || "无摘要"}</div>
                              <div className="tool-flags">
                                <span>${item.read_only ? "read-only" : "write"}</span>
                                <span>${item.requires_evidence ? "evidence" : "no-evidence"}</span>
                              </div>
                            </div>
                          `,
                        )}
                      </div>
                    </section>
                  `,
                )}
              </div>
            `
          : null}

        ${drawerView === "skills"
          ? html`
              <div className="workbench-scroll">
                <section className="panel-card">
                  <div className="editor-toolbar">
                    <div className="panel-title">Skills</div>
                    <div className="editor-actions">
                      <button className="ghost-btn" type="button" onClick=${() => {
                        setSelectedSkillId("");
                        setSkillEditor(defaultSkillTemplate());
                      }}>新建</button>
                      <button className="solid-btn" type="button" onClick=${saveSkill} disabled=${savingWorkbench || !skillEditor.trim()}>保存</button>
                      ${selectedSkill
                        ? html`
                            <button
                              className="ghost-btn"
                              type="button"
                              onClick=${() => toggleSelectedSkill(!selectedSkill.enabled)}
                              disabled=${savingWorkbench}
                            >
                              ${selectedSkill.enabled ? "停用" : "启用"}
                            </button>
                          `
                        : null}
                    </div>
                  </div>

                  <div className="resource-list">
                    ${skills.length
                      ? skills.map(
                          (item) => html`
                            <button
                              key=${item.id}
                              className=${`resource-row ${selectedSkillId === item.id ? "active" : ""}`}
                              type="button"
                              onClick=${() => loadSkillDetail(item.id)}
                            >
                              <div className="resource-row-title">${item.title || item.id}</div>
                              <div className="resource-row-meta">${item.enabled ? "enabled" : "disabled"} · ${item.validation_status}</div>
                            </button>
                          `,
                        )
                      : html`<div className="empty-inline">还没有本地 skill，点“新建”开始。</div>`}
                  </div>

                  <textarea
                    className="editor-textarea"
                    value=${skillEditor}
                    onInput=${(event) => setSkillEditor(event.currentTarget.value)}
                    placeholder="完整编辑 SKILL.md 内容"
                  ></textarea>
                </section>
              </div>
            `
          : null}

        ${drawerView === "agent"
          ? html`
              <div className="workbench-scroll">
                <section className="panel-card">
                  <div className="editor-toolbar">
                    <div className="panel-title">Agent Specs</div>
                    <div className="editor-actions">
                      <button className="solid-btn" type="button" onClick=${saveSpec} disabled=${savingWorkbench || !specEditor.trim()}>保存</button>
                    </div>
                  </div>

                  <div className="resource-list">
                    ${specs.map(
                      (item) => html`
                        <button
                          key=${item.name}
                          className=${`resource-row ${selectedSpecName === item.name ? "active" : ""}`}
                          type="button"
                          onClick=${() => loadSpecDetail(item.name)}
                        >
                          <div className="resource-row-title">${item.name}</div>
                          <div className="resource-row-meta">${item.validation_status}</div>
                        </button>
                      `,
                    )}
                  </div>

                  <textarea
                    className="editor-textarea"
                    value=${specEditor}
                    onInput=${(event) => setSpecEditor(event.currentTarget.value)}
                    placeholder="完整编辑 agent 规范 markdown"
                  ></textarea>
                </section>
              </div>
            `
          : null}

        ${drawerView === "settings"
          ? html`
              <div className="workbench-scroll" id="settingsPanel">
                <section className="panel-card">
                  <div className="panel-title">Chat Settings</div>
                  ${availableProviders.length
                    ? html`
                        <label className="form-field">
                          <span>Provider</span>
                          <select
                            className="drawer-input"
                            id="providerSelect"
                            value=${activeProvider}
                            onChange=${(event) => updateProviderSelection(event.currentTarget.value)}
                          >
                            ${providerOptions.map((item) => html`
                              <option key=${item.provider} value=${item.provider}>
                                ${item.label || item.provider}
                              </option>
                            `)}
                          </select>
                        </label>
                      `
                    : null}
                  <label className="form-field">
                    <span>模型预设</span>
                    <select
                      className="drawer-input"
                      id="modelPresetSelect"
                      value=${selectedPresetModel || resolvePresetModelValue(chatSettings.model, modelOptions, allowCustomModel)}
                      onChange=${(event) => {
                        const nextValue = String(event.currentTarget.value || "");
                        setModelTouched(true);
                        setSelectedPresetModel(nextValue);
                        if (nextValue === CUSTOM_MODEL_VALUE) return;
                        updateModelSelection(nextValue);
                      }}
                    >
                      ${modelOptions.map((item) => html`<option key=${item} value=${item}>${item}</option>`)}
                      ${allowCustomModel ? html`<option value=${CUSTOM_MODEL_VALUE}>Custom</option>` : null}
                    </select>
                  </label>
                  <label className="form-field">
                    <span>模型名称</span>
                    <input
                      className="drawer-input"
                      id="modelInput"
                      type="text"
                      value=${chatSettings.model}
                      onInput=${(event) => updateModelSelection(event.currentTarget.value)}
                    />
                  </label>
                  <label className="form-field">
                    <span>响应风格</span>
                    <select
                      className="drawer-input"
                      value=${chatSettings.response_style}
                      onChange=${(event) => setChatSettings((prev) => ({ ...prev, response_style: event.currentTarget.value }))}
                    >
                      <option value="short">简短</option>
                      <option value="normal">正常</option>
                      <option value="long">详细</option>
                    </select>
                  </label>
                  <label className="tool-toggle drawer-toggle">
                    <input
                      type="checkbox"
                      checked=${chatSettings.enable_tools}
                      onChange=${(event) => setChatSettings((prev) => ({ ...prev, enable_tools: event.currentTarget.checked }))}
                    />
                    Tools
                  </label>
                  <label className="form-field">
                    <span>输出上限</span>
                    <input
                      className="drawer-input"
                      type="number"
                      value=${chatSettings.max_output_tokens}
                      onInput=${(event) => setChatSettings((prev) => ({ ...prev, max_output_tokens: Number(event.currentTarget.value || 0) || 1024 }))}
                    />
                  </label>
                  <label className="form-field">
                    <span>上下文轮数</span>
                    <input
                      className="drawer-input"
                      type="number"
                      value=${chatSettings.max_context_turns}
                      onInput=${(event) => setChatSettings((prev) => ({ ...prev, max_context_turns: Number(event.currentTarget.value || 0) || 20 }))}
                    />
                  </label>
                </section>
              </div>
            `
          : null}
      </aside>`
        : null}
    </div>
  `;
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");
createRoot(root).render(html`<${App} />`);
