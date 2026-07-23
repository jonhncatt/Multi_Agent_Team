const ReactRuntime = window.React;
const ReactDomRuntime = window.ReactDOM;
const htmRuntime = window.htm;
const markedRuntime = window.marked;
const DOMPurifyRuntime = window.DOMPurify;
const I18nRuntime = window.VP_I18N;

if (!ReactRuntime || !ReactDomRuntime || !htmRuntime || !markedRuntime || !DOMPurifyRuntime || !I18nRuntime) {
  const root = document.getElementById("root");
  if (root) {
    root.innerHTML = `
      <div style="padding:24px;font:14px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;color:#1f2328;">
        Frontend resources failed to load. Refresh the page and verify local static files are reachable.
      </div>
    `;
  }
  throw new Error("Local frontend runtime scripts are unavailable.");
}

const { useEffect, useMemo, useReducer, useRef, useState } = ReactRuntime;
const { createRoot } = ReactDomRuntime;
const html = htmRuntime.bind(ReactRuntime.createElement);

if (typeof markedRuntime.setOptions === "function") {
  markedRuntime.setOptions({
    gfm: true,
    breaks: true,
  });
}

const SESSION_STORAGE_KEY = "vintage_programmer.session_id";
const PROJECT_STORAGE_KEY = "vintage_programmer.project_id";
const PROVIDER_STORAGE_KEY = "vintage_programmer.last_provider";
const MODEL_STORAGE_KEY = "vintage_programmer.last_model";
const LOCALE_STORAGE_KEY = "vintage_programmer.locale";
const THEME_COLOR_STORAGE_KEY = "vintage_programmer.theme_color";
const CUSTOM_MODEL_VALUE = "__custom__";
const WORKBENCH_TABS = ["run", "tools", "skills", "agent", "settings"];
const RUNTIME_STATUS_ACTIVE_INTERVAL_MS = 5_000;
const RUNTIME_STATUS_IDLE_INTERVAL_MS = 30_000;
const PROJECTS_REFRESH_STALE_MS = 60_000;
const MODEL_WAIT_SLOW_HINT_MS = 8_000;
const UPLOAD_CONCURRENCY = 3;
const THREAD_DETAIL_PAGE_SIZE = 40;
const THREAD_DETAIL_CACHE_LIMIT = 60;
const MESSAGE_HTML_CACHE_LIMIT = 300;
const TEMP_THREAD_PREFIX = "temp-thread-";
const MAIN_LIVE_CARD_LIMIT = 5;
const COMPACT_PLAN_ITEM_LIMIT = 6;
const MAIN_CARD_TRACE_EVENT_LIMIT = 50;
const LIVE_PROGRESS_STALE_AFTER_MS = 5_000;
const STREAM_UI_FLUSH_INTERVAL_MS = 100;
const CHAT_AUTO_SCROLL_THRESHOLD_PX = 100;
const NORMALIZED_ACTIVITY_MARKER = Symbol("normalizedActivity");
const THEME_COLOR_OPTIONS = [
  { id: "slate", accent: "#111827", accentInk: "#f9fafb", accentSoft: "#e9edf3", accentStrong: "#1f2937", accentDark: "#0f172a" },
  { id: "blue", accent: "#2563eb", accentInk: "#ffffff", accentSoft: "#dbeafe", accentStrong: "#1d4ed8", accentDark: "#1e40af" },
  { id: "emerald", accent: "#047857", accentInk: "#ffffff", accentSoft: "#d1fae5", accentStrong: "#059669", accentDark: "#065f46" },
  { id: "violet", accent: "#7c3aed", accentInk: "#ffffff", accentSoft: "#ede9fe", accentStrong: "#6d28d9", accentDark: "#5b21b6" },
  { id: "rose", accent: "#be123c", accentInk: "#ffffff", accentSoft: "#ffe4e6", accentStrong: "#e11d48", accentDark: "#9f1239" },
];
const messageHtmlCache = new Map();
const DEFAULT_SETTINGS = {
  provider: "",
  model: "",
  locale: "",
  max_output_tokens: 16384,
  max_context_turns: 2000,
  enable_tools: true,
  debug_raw: false,
  permission_profile: "auto",
  response_style: "normal",
};
const SLASH_COMMANDS = [
  { command: "/status", labelKey: "slash.status.label", descriptionKey: "slash.status.description" },
  { command: "/compact", labelKey: "slash.compact.label", descriptionKey: "slash.compact.description" },
];

function normalizeSlashCommandText(value) {
  const raw = String(value || "").trim();
  if (!raw.startsWith("/") || /\s/.test(raw)) return "";
  const command = raw.toLowerCase();
  return SLASH_COMMANDS.some((item) => item.command === command) ? command : "";
}

function slashCommandQueryFromDraft(value) {
  const raw = String(value || "").trimStart();
  if (!raw.startsWith("/") || /[\s]/.test(raw)) return "";
  return raw.toLowerCase();
}

function normalizePermissionProfile(raw) {
  const value = String(raw || "").trim().toLowerCase().replaceAll("-", "_");
  const aliases = {
    chat: "default",
    readonly: "default",
    read_only: "default",
    "read only": "default",
    default: "default",
    safe: "default",
    safe_default: "default",
    code: "auto",
    coding: "auto",
    auto: "auto",
    automatic: "auto",
    full_dev: "full_access",
    "full dev": "full_access",
    fulldev: "full_access",
    full: "full_access",
    dev: "full_access",
    full_access: "full_access",
    "full access": "full_access",
    danger_full_access: "full_access",
  };
  const normalized = aliases[value] || value;
  return ["default", "auto", "full_access"].includes(normalized) ? normalized : "auto";
}

function normalizeLocaleValue(raw, supportedLocales = I18nRuntime.SUPPORTED_LOCALES, fallbackLocale = "ja-JP") {
  return I18nRuntime.normalizeLocale(raw, supportedLocales, fallbackLocale);
}

function translateUi(locale, key, replacements = null) {
  return I18nRuntime.t(locale, key, replacements || undefined);
}

function translateUiList(locale, key) {
  return I18nRuntime.list(locale, key);
}

function detectBrowserLocale(supportedLocales, fallbackLocale) {
  const candidates = [];
  if (Array.isArray(navigator.languages)) candidates.push(...navigator.languages);
  candidates.push(navigator.language);
  for (const candidate of candidates) {
    const normalized = normalizeLocaleValue(candidate, supportedLocales, "");
    if (normalized) return normalized;
  }
  return fallbackLocale;
}

function readStoredLocale(supportedLocales) {
  const raw = window.localStorage.getItem(LOCALE_STORAGE_KEY) || "";
  const normalized = normalizeLocaleValue(raw, supportedLocales, "");
  if (raw && !normalized) {
    window.localStorage.removeItem(LOCALE_STORAGE_KEY);
  }
  return normalized;
}

function themeColorOptionById(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return THEME_COLOR_OPTIONS.find((item) => item.id === normalized) || THEME_COLOR_OPTIONS[0];
}

function readStoredThemeColor() {
  const raw = window.localStorage.getItem(THEME_COLOR_STORAGE_KEY) || "";
  const option = themeColorOptionById(raw);
  if (raw && raw !== option.id) {
    window.localStorage.removeItem(THEME_COLOR_STORAGE_KEY);
  }
  return option.id;
}

function applyThemeColor(value) {
  const option = themeColorOptionById(value);
  const root = document.documentElement;
  root.style.setProperty("--accent", option.accent);
  root.style.setProperty("--accent-ink", option.accentInk);
  root.style.setProperty("--accent-soft", option.accentSoft);
  root.style.setProperty("--accent-strong", option.accentStrong);
  root.style.setProperty("--accent-dark", option.accentDark);
  root.dataset.themeColor = option.id;
  return option;
}

function resolveInitialLocale({ supportedLocales, serverLocale, fallbackLocale }) {
  const storedLocale = readStoredLocale(supportedLocales);
  if (storedLocale) return storedLocale;
  const normalizedServerLocale = normalizeLocaleValue(serverLocale, supportedLocales, "");
  if (normalizedServerLocale) return normalizedServerLocale;
  const browserLocale = detectBrowserLocale(supportedLocales, "");
  if (browserLocale) return browserLocale;
  return normalizeLocaleValue(fallbackLocale, supportedLocales, "ja-JP");
}

function createMessage(role, text, options = {}) {
  return {
    id: options.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    pending: Boolean(options.pending),
    error: Boolean(options.error),
    createdAt: options.createdAt || "",
    activity: normalizeMessageActivity(options.activity || null),
    answerBundle: options.answerBundle && typeof options.answerBundle === "object" ? options.answerBundle : {},
    runArtifact: options.runArtifact && typeof options.runArtifact === "object" ? options.runArtifact : {},
    runActivityLoading: Boolean(options.runActivityLoading),
    runActivityError: String(options.runActivityError || ""),
    runDebugLoading: Boolean(options.runDebugLoading),
    runDebugError: String(options.runDebugError || ""),
  };
}

function createEmptyLiveHeartbeat() {
  return {
    status: "",
    tool: "",
    model: "",
    action: "",
    command: "",
    recentEvent: "",
    updatedAt: 0,
    connectionAt: 0,
    source: "",
  };
}

function normalizeLiveHeartbeat(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  return {
    ...createEmptyLiveHeartbeat(),
    ...item,
    status: String(item.status || "").trim(),
    tool: String(item.tool || "").trim(),
    model: String(item.model || "").trim(),
    action: String(item.action || "").trim(),
    command: String(item.command || "").trim(),
    recentEvent: String(item.recentEvent || item.recent_event || "").trim(),
    updatedAt: normalizeActivityTimestamp(item.updatedAt || item.updated_at || 0),
    connectionAt: normalizeActivityTimestamp(item.connectionAt || item.connection_at || 0),
    source: String(item.source || "").trim(),
  };
}

function createEmptyThreadActiveTurn() {
  return {
    sending: false,
    activeRunId: "",
    activeRunThreadId: "",
    startedAt: 0,
    lastLiveProgressAt: 0,
    liveHeartbeat: createEmptyLiveHeartbeat(),
    stoppingRun: false,
    lastResponse: null,
    toolTimeline: [],
    liveToolTimeline: [],
    liveTurnState: {},
    liveEvidence: {},
    liveRunLogs: [],
    stageTimeline: [],
    pendingGuidance: [],
  };
}

function normalizeThreadActiveTurn(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  const has = (key) => Object.prototype.hasOwnProperty.call(item, key);
  const sendingSource = has("sending")
    ? item.sending
    : (has("isSending") ? item.isSending : item.is_sending);
  const activeRunIdSource = has("activeRunId") ? item.activeRunId : item.active_run_id;
  const activeRunThreadIdSource = has("activeRunThreadId") ? item.activeRunThreadId : item.active_run_thread_id;
  const startedAtSource = has("startedAt")
    ? item.startedAt
    : (has("started_at") ? item.started_at : (has("runStartedAt") ? item.runStartedAt : item.run_started_at));
  const lastLiveProgressAtSource = has("lastLiveProgressAt") ? item.lastLiveProgressAt : item.last_live_progress_at;
  const stoppingRunSource = has("stoppingRun") ? item.stoppingRun : item.stopping_run;
  return {
    ...createEmptyThreadActiveTurn(),
    ...item,
    sending: Boolean(sendingSource),
    activeRunId: String(activeRunIdSource || ""),
    activeRunThreadId: String(activeRunThreadIdSource || ""),
    startedAt: normalizeActivityTimestamp(startedAtSource || 0),
    lastLiveProgressAt: normalizeActivityTimestamp(lastLiveProgressAtSource || 0),
    liveHeartbeat: normalizeLiveHeartbeat(item.liveHeartbeat || item.live_heartbeat || {}),
    stoppingRun: Boolean(stoppingRunSource),
    lastResponse: item.lastResponse && typeof item.lastResponse === "object" ? item.lastResponse : null,
    toolTimeline: Array.isArray(item.toolTimeline) ? item.toolTimeline : [],
    liveToolTimeline: Array.isArray(item.liveToolTimeline) ? item.liveToolTimeline : [],
    liveTurnState: item.liveTurnState && typeof item.liveTurnState === "object" ? item.liveTurnState : {},
    liveEvidence: item.liveEvidence && typeof item.liveEvidence === "object" ? item.liveEvidence : {},
    liveRunLogs: Array.isArray(item.liveRunLogs) ? item.liveRunLogs : [],
    stageTimeline: Array.isArray(item.stageTimeline) ? item.stageTimeline : [],
    pendingGuidance: Array.isArray(item.pendingGuidance)
      ? item.pendingGuidance
          .filter((entry) => entry && typeof entry === "object" && String(entry.message || "").trim())
          .map((entry) => ({
            id: String(entry.id || ""),
            message: String(entry.message || "").trim(),
            status: String(entry.status || "queued"),
            queuedAt: normalizeActivityTimestamp(entry.queuedAt || entry.queued_at || 0),
          }))
      : [],
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

function dragEventHasFiles(event) {
  const transfer = event && event.dataTransfer;
  if (!transfer) return false;
  if (transfer.files && transfer.files.length) return true;
  const types = Array.from(transfer.types || []);
  return types.includes("Files");
}

function clipboardEventFiles(event) {
  const transfer = event && event.clipboardData;
  if (!transfer) return [];
  const directFiles = Array.from(transfer.files || []).filter(Boolean);
  if (directFiles.length) return directFiles;
  return Array.from(transfer.items || [])
    .filter((item) => item && item.kind === "file")
    .map((item) => (typeof item.getAsFile === "function" ? item.getAsFile() : null))
    .filter(Boolean);
}

function extensionFromMime(mime) {
  const normalized = String(mime || "").trim().toLowerCase();
  if (normalized === "image/png") return "png";
  if (normalized === "image/jpeg") return "jpg";
  if (normalized === "image/webp") return "webp";
  if (normalized === "image/gif") return "gif";
  if (normalized === "image/heic") return "heic";
  if (normalized === "image/heif") return "heif";
  if (normalized === "application/pdf") return "pdf";
  return "bin";
}

function ensureNamedUploadFile(file, index = 0) {
  if (!file) return file;
  const normalizedName = String(file.name || "").trim();
  if (normalizedName) return file;
  const mime = String(file.type || "application/octet-stream").trim() || "application/octet-stream";
  const ext = extensionFromMime(mime);
  const stamp = new Date().toISOString().replaceAll(":", "").replaceAll(".", "").replace("T", "_").replace("Z", "");
  const generatedName = `pasted-${stamp}-${index + 1}.${ext}`;
  try {
    return new File([file], generatedName, {
      type: mime,
      lastModified: Date.now(),
    });
  } catch {
    file.name = generatedName;
    return file;
  }
}

function formatTime(raw, locale = "ja-JP") {
  const text = String(raw || "").trim();
  if (!text) return "";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString(locale, {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTokenCount(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return "0";
  if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(amount >= 10_000_000 ? 0 : 1)}M`;
  if (amount >= 1_000) return `${(amount / 1_000).toFixed(amount >= 100_000 ? 0 : 1)}k`;
  return String(Math.round(amount));
}

function normalizeReleaseVersion(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  return raw.startsWith("v") ? raw : `v${raw}`;
}

function normalizeContextMeter(raw) {
  const meter = raw && typeof raw === "object" ? raw : {};
  const estimated = Math.max(0, Number(meter.estimated_tokens || 0) || 0);
  const payload = Math.max(0, Number(meter.estimated_payload_tokens || 0) || 0);
  const overhead = Math.max(0, Number(meter.overhead_tokens || 0) || 0);
  const limit = Math.max(0, Number(meter.auto_compact_token_limit || 0) || 0);
  const contextWindow = Math.max(0, Number(meter.context_window || 0) || 0);
  const rawRatio = Number(meter.used_ratio || 0);
  const usedRatio = contextWindow > 0
    ? Math.min(1, Math.max(0, Number.isFinite(rawRatio) ? rawRatio : (estimated / contextWindow)))
    : 0;
  const remainingRatio = Math.max(0, 1 - usedRatio);
  const usedPercent = Math.max(0, Math.min(100, Math.round(Number(meter.used_percent || (usedRatio * 100)) || 0)));
  const remainingPercent = Math.max(0, Math.min(100, Math.round(Number(meter.remaining_percent || (remainingRatio * 100)) || 0)));
  return {
    estimated_tokens: estimated,
    estimated_payload_tokens: payload,
    overhead_tokens: overhead,
    auto_compact_token_limit: limit,
    danger_compact_token_limit: Math.max(0, Number(meter.danger_compact_token_limit || 0) || 0),
    history_soft_limit_tokens: Math.max(0, Number(meter.history_soft_limit_tokens || 0) || 0),
    history_noise_tokens: Math.max(0, Number(meter.history_noise_tokens || 0) || 0),
    remaining_tokens: Math.max(0, Number(meter.remaining_tokens || 0) || 0),
    context_window: contextWindow,
    model_max_context_window: Math.max(0, Number(meter.model_max_context_window || contextWindow) || 0),
    effective_context_window: Math.max(0, Number(meter.effective_context_window || contextWindow) || 0),
    used_ratio: usedRatio,
    remaining_ratio: remainingRatio,
    used_percent: usedPercent,
    remaining_percent: remainingPercent,
    threshold_source: String(meter.threshold_source || "").trim(),
    context_window_known: Boolean(meter.context_window_known),
    compaction_enabled: Boolean(meter.compaction_enabled),
    last_compacted_at: String(meter.last_compacted_at || "").trim(),
    estimate_mode: String(meter.estimate_mode || "").trim(),
    stale: Boolean(meter.stale),
    calculation_ms: Math.max(0, Number(meter.calculation_ms || 0) || 0),
    updated_at: String(meter.updated_at || "").trim(),
    exact_updated_at: String(meter.exact_updated_at || "").trim(),
    compact_recommendation: String(meter.compact_recommendation || "none").trim(),
    compact_reason: String(meter.compact_reason || "").trim(),
    warning: String(meter.warning || "").trim(),
  };
}

function normalizeCompactionStatus(raw) {
  const status = raw && typeof raw === "object" ? raw : {};
  return {
    enabled: Boolean(status.enabled),
    mode: String(status.mode || "").trim(),
    replacement_history_mode: Boolean(status.replacement_history_mode),
    generation: Math.max(0, Number(status.generation || 0) || 0),
    compacted_history_present: Boolean(status.compacted_history_present),
    compacted_history_chars: Math.max(0, Number(status.compacted_history_chars || 0) || 0),
    compacted_until_turn_id: String(status.compacted_until_turn_id || "").trim(),
    retained_turn_ids: Array.isArray(status.retained_turn_ids) ? status.retained_turn_ids : [],
    retained_turn_count: Math.max(0, Number(status.retained_turn_count || 0) || 0),
    estimated_context_tokens: Math.max(0, Number(status.estimated_context_tokens || 0) || 0),
    estimated_payload_tokens: Math.max(0, Number(status.estimated_payload_tokens || 0) || 0),
    model_max_context_window: Math.max(0, Number(status.model_max_context_window || 0) || 0),
    operational_context_window: Math.max(0, Number(status.operational_context_window || 0) || 0),
    effective_context_window: Math.max(0, Number(status.effective_context_window || 0) || 0),
    auto_compact_token_limit: Math.max(0, Number(status.auto_compact_token_limit || 0) || 0),
    danger_compact_token_limit: Math.max(0, Number(status.danger_compact_token_limit || 0) || 0),
    history_soft_limit_tokens: Math.max(0, Number(status.history_soft_limit_tokens || 0) || 0),
    history_noise_tokens: Math.max(0, Number(status.history_noise_tokens || 0) || 0),
    threshold_source: String(status.threshold_source || "").trim(),
    context_window_known: Boolean(status.context_window_known),
    last_compacted_at: String(status.last_compacted_at || "").trim(),
    last_compaction_reason: String(status.last_compaction_reason || "").trim(),
    last_compaction_phase: String(status.last_compaction_phase || "").trim(),
    estimate_mode: String(status.estimate_mode || "").trim(),
    context_estimate_updated_at: String(status.context_estimate_updated_at || "").trim(),
    context_exact_updated_at: String(status.context_exact_updated_at || "").trim(),
    calculation_ms: Math.max(0, Number(status.calculation_ms || 0) || 0),
    compact_recommendation: String(status.compact_recommendation || "none").trim(),
    compact_reason: String(status.compact_reason || "").trim(),
    warning: String(status.warning || "").trim(),
  };
}

function resolveContextMeterColor(meter) {
  const usedRatio = Number((meter && meter.used_ratio) || 0);
  if (usedRatio >= 0.92) return "var(--danger)";
  if (usedRatio >= 0.78) return "var(--warning)";
  return "var(--ink-faint)";
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

function roleLabel(role, locale) {
  if (role === "user") return translateUi(locale, "role.user");
  if (role === "assistant") return translateUi(locale, "role.assistant");
  if (role === "runtime") return translateUi(locale, "role.runtime");
  return translateUi(locale, "role.system");
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

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function isTempThreadId(value) {
  return String(value || "").startsWith(TEMP_THREAD_PREFIX);
}

function rememberMessageHtml(cacheKey, htmlValue) {
  if (!cacheKey) return;
  if (messageHtmlCache.has(cacheKey)) messageHtmlCache.delete(cacheKey);
  messageHtmlCache.set(cacheKey, htmlValue);
  while (messageHtmlCache.size > MESSAGE_HTML_CACHE_LIMIT) {
    const oldestKey = messageHtmlCache.keys().next().value;
    messageHtmlCache.delete(oldestKey);
  }
}

function renderMessageHtml(text, messageId = "") {
  const raw = String(text || "");
  if (!raw) return "";
  const cacheKey = `${String(messageId || "")}\n${raw}`;
  if (messageHtmlCache.has(cacheKey)) {
    const cached = messageHtmlCache.get(cacheKey);
    messageHtmlCache.delete(cacheKey);
    messageHtmlCache.set(cacheKey, cached);
    return cached;
  }
  let htmlValue = "";
  if (!markedRuntime || typeof markedRuntime.parse !== "function" || !DOMPurifyRuntime || typeof DOMPurifyRuntime.sanitize !== "function") {
    htmlValue = escapeHtml(raw).replaceAll("\n", "<br />");
    rememberMessageHtml(cacheKey, htmlValue);
    return htmlValue;
  }
  try {
    const rendered = markedRuntime.parse(raw);
    htmlValue = DOMPurifyRuntime.sanitize(rendered, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input", "button", "textarea", "select"],
      FORBID_ATTR: ["style", "onerror", "onload", "onclick"],
    });
  } catch {
    htmlValue = escapeHtml(raw).replaceAll("\n", "<br />");
  }
  rememberMessageHtml(cacheKey, htmlValue);
  return htmlValue;
}

function fallbackCopyText(text) {
  try {
    const textarea = document.createElement("textarea");
    textarea.value = String(text || "");
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const ok = document.execCommand("copy");
    textarea.remove();
    return Boolean(ok);
  } catch {
    return false;
  }
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return false;
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      return fallbackCopyText(value);
    }
  }
  return fallbackCopyText(value);
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

function normalizeUiError(locale, source, fallbackSummary = null, fallback = {}) {
  const fallbackText = String(fallbackSummary || translateUi(locale, "errors.request_failed")).trim();
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
      ? translateUi(locale, "errors.rate_limit")
      : kind === "auth"
        ? translateUi(locale, "errors.auth")
        : kind === "upstream"
          ? translateUi(locale, "errors.upstream")
          : fallbackText);
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
  const error = new Error(String((uiError && uiError.summary) || "Request failed."));
  error.uiError = uiError;
  return error;
}

function projectLabel(project, fallbackHealth) {
  if (project && project.title) return String(project.title);
  return fileNameFromHealth(fallbackHealth);
}

function extractSessionMessages(data) {
  const turns = Array.isArray(data.turns) ? data.turns : [];
  return turns.map((turn, index) => {
    const storedRole = String(turn.role || "").toLowerCase();
    const displayRole = ["user", "assistant", "runtime", "system"].includes(storedRole)
      ? storedRole
      : "system";
    return createMessage(
      displayRole,
      String(turn.text || ""),
      {
        id: String(turn.id || `${index}-${turn.role || "turn"}-${turn.created_at || ""}`),
        createdAt: String(turn.created_at || ""),
        activity: turn.activity || {},
        answerBundle: turn.answer_bundle || {},
        runArtifact: turn.run_artifact || {},
      },
    );
  });
}

function appendMessagesOnceById(previousMessages, incomingMessages) {
  const next = Array.isArray(previousMessages) ? [...previousMessages] : [];
  const knownIds = new Set(
    next.map((item) => String((item && item.id) || "").trim()).filter(Boolean),
  );
  (Array.isArray(incomingMessages) ? incomingMessages : []).forEach((message) => {
    if (!message || typeof message !== "object") return;
    const messageId = String(message.id || "").trim();
    if (messageId && knownIds.has(messageId)) return;
    next.push(message);
    if (messageId) knownIds.add(messageId);
  });
  return next;
}

function mergeAuthoritativeThreadMessages(authoritativeMessages, currentMessages, options = {}) {
  const authoritative = Array.isArray(authoritativeMessages)
    ? authoritativeMessages.filter((item) => item && typeof item === "object")
    : [];
  const optimisticMessageIds = new Set(
    (Array.isArray(options.optimisticMessageIds) ? options.optimisticMessageIds : [])
      .map((item) => String(item || "").trim())
      .filter(Boolean),
  );
  const rawCurrent = Array.isArray(currentMessages)
    ? currentMessages.filter((item) => item && typeof item === "object")
    : [];
  if (!authoritative.length) return rawCurrent;
  const current = rawCurrent.filter(
    (item) => !optimisticMessageIds.has(String(item.id || "").trim()),
  );

  const currentById = new Map(
    current
      .map((item) => [String(item.id || "").trim(), item])
      .filter(([id]) => Boolean(id)),
  );
  const authoritativeIds = new Set(
    authoritative.map((item) => String(item.id || "").trim()).filter(Boolean),
  );
  const mergedTail = authoritative.map((message) => {
    const previous = currentById.get(String(message.id || "").trim());
    if (!previous) return message;
    return {
      ...message,
      activity: mergeActivityState(message.activity || {}, previous.activity || {}),
      answerBundle:
        (previous.answerBundle && Object.keys(previous.answerBundle || {}).length)
          ? previous.answerBundle
          : message.answerBundle,
      runArtifact:
        (previous.runArtifact && Object.keys(previous.runArtifact || {}).length)
          ? previous.runArtifact
          : message.runArtifact,
      runActivityLoading: Boolean(previous.runActivityLoading),
      runActivityError: String(previous.runActivityError || ""),
      runDebugLoading: Boolean(previous.runDebugLoading),
      runDebugError: String(previous.runDebugError || ""),
    };
  });
  const firstAuthoritativeIndex = current.findIndex((item) => (
    authoritativeIds.has(String(item.id || "").trim())
  ));
  if (firstAuthoritativeIndex < 0) return mergedTail;

  const preservedPrefix = current
    .slice(0, firstAuthoritativeIndex)
    .filter((item) => !authoritativeIds.has(String(item.id || "").trim()));
  return [...preservedPrefix, ...mergedTail];
}

function normalizeActivityTimestamp(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return numeric > 1_000_000_000_000 ? Math.round(numeric) : Math.round(numeric * 1000);
}

function normalizeTraceEvent(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  return {
    id: String(item.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
    run_id: String(item.run_id || ""),
    type: String(item.type || ""),
    title: String(item.title || ""),
    detail: String(item.detail || ""),
    status: String(item.status || "running"),
    timestamp: normalizeActivityTimestamp(item.timestamp),
    duration_ms: item.duration_ms == null ? null : Math.max(0, Number(item.duration_ms) || 0),
    payload: item.payload && typeof item.payload === "object" ? item.payload : {},
    parent_id: item.parent_id ? String(item.parent_id) : null,
    visible: item.visible !== false,
  };
}

function normalizePlanChecklistItem(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  return {
    step: String(item.step || item.title || "").trim(),
    status: String(item.status || "pending").trim() || "pending",
    detail: String(item.detail || item.reason || "").trim(),
  };
}

function normalizePlanChecklist(raw) {
  return (Array.isArray(raw) ? raw : [])
    .map(normalizePlanChecklistItem)
    .filter((item) => item.step);
}

function normalizeActivityToolItem(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  const rawToolCall = item.raw_tool_call && typeof item.raw_tool_call === "object" ? item.raw_tool_call : {};
  const validationResult = item.validation_result && typeof item.validation_result === "object" ? item.validation_result : {};
  const normalizedArguments =
    item.normalized_arguments && typeof item.normalized_arguments === "object" ? item.normalized_arguments : {};
  const schemaValidation =
    item.schema_validation && typeof item.schema_validation === "object" ? item.schema_validation : {};
  const diagnostics = item.diagnostics && typeof item.diagnostics === "object" ? item.diagnostics : {};
  const resolvedId = toolCallIdentityFromSource(
    item,
    `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  );
  return {
    ...item,
    id: resolvedId,
    type: String(item.type || item.item_type || "").trim(),
    tool: String(item.tool || item.name || rawToolCall.name || "").trim(),
    name: String(item.name || item.tool || rawToolCall.name || "").trim(),
    status: String(item.status || "").trim(),
    summary: String(item.summary || "").trim(),
    raw_tool_call: rawToolCall,
    validation_result: validationResult,
    normalized_arguments: normalizedArguments,
    schema_validation: schemaValidation,
    diagnostics,
  };
}

function normalizeActivityToolItems(raw) {
  return (Array.isArray(raw) ? raw : [])
    .map(normalizeActivityToolItem)
    .filter((item) => item.id);
}

function mergeActivityToolItems(previousItems, nextItems) {
  const order = [];
  const map = new Map();
  normalizeActivityToolItems(previousItems).forEach((item) => {
    order.push(item.id);
    map.set(item.id, item);
  });
  normalizeActivityToolItems(nextItems).forEach((item) => {
    if (!map.has(item.id)) order.push(item.id);
    map.set(item.id, { ...(map.get(item.id) || {}), ...item });
  });
  return order.map((id) => map.get(id)).filter(Boolean).slice(-24);
}

function reconcileAuthoritativeActivityToolItems(previousItems, nextItems) {
  const authoritative = normalizeActivityToolItems(nextItems);
  if (!authoritative.length) return [];
  const authoritativeIds = new Set(authoritative.map((item) => item.id));
  return mergeActivityToolItems(previousItems, authoritative)
    .filter((item) => authoritativeIds.has(item.id));
}

function normalizeLiveRunItem(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  const rawItem = item.raw && typeof item.raw === "object" ? item.raw : {};
  const callId = String(item.call_id || item.tool_call_id || rawItem.call_id || rawItem.tool_call_id || rawItem.id || "").trim();
  const tool = String(item.tool || item.name || rawItem.tool || rawItem.name || "").trim();
  const type = String(item.type || rawItem.type || "").trim();
  const id = String(
    item.id
    || callId
    || [type, tool, item.startedAt || item.started_at || rawItem.startedAt || rawItem.started_at].filter(Boolean).join(":")
    || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  ).trim();
  return {
    id,
    type,
    status: normalizeProgressStatus(item.status || rawItem.status || "running"),
    label: String(item.label || rawItem.label || rawItem.summary || rawItem.title || "").trim(),
    label_key: String(item.label_key || item.labelKey || "").trim(),
    detail: String(item.detail || rawItem.detail || rawItem.summary || "").trim(),
    tool,
    call_id: callId,
    started_at: normalizeActivityTimestamp(item.started_at || item.startedAt || rawItem.started_at || rawItem.startedAt || 0),
    completed_at: normalizeActivityTimestamp(item.completed_at || item.completedAt || rawItem.completed_at || rawItem.completedAt || 0),
    raw: item.raw || rawItem || {},
  };
}

function normalizeLiveRunItems(raw) {
  return (Array.isArray(raw) ? raw : [])
    .map(normalizeLiveRunItem)
    .filter((item) => item.id);
}

function mergeLiveRunItems(previousItems, nextItems) {
  const order = [];
  const map = new Map();
  normalizeLiveRunItems(previousItems).forEach((item) => {
    order.push(item.id);
    map.set(item.id, item);
  });
  normalizeLiveRunItems(nextItems).forEach((item) => {
    if (!map.has(item.id)) order.push(item.id);
    map.set(item.id, { ...(map.get(item.id) || {}), ...item });
  });
  return order.map((id) => map.get(id)).filter(Boolean).slice(-32);
}

function liveRunItemFromStreamItem(streamItem, eventName = "") {
  const item = streamItem && typeof streamItem === "object" ? streamItem : {};
  const itemType = String(item.type || "").trim();
  const isCompleted = String(eventName || "").trim() === "item/completed";
  const tool = String(item.tool || item.name || "").trim();
  let labelKey = "";
  if (itemType === "agentMessage") {
    labelKey = isCompleted ? "activity.live.answer_done" : "activity.live.answer_streaming";
  } else if (itemType === "contextCompaction") {
    labelKey = isCompleted ? "activity.live.context_compacted" : "activity.live.context_compacting";
  } else if (itemType === "subagent") {
    labelKey = isCompleted ? "subagent.completed" : "subagent.running";
  } else if (itemType === "toolCall" || tool) {
    labelKey = isCompleted ? "activity.live.tool_finished" : "activity.live.tool_running";
  }
  return normalizeLiveRunItem({
    id: String(item.id || item.call_id || item.tool_call_id || "").trim(),
    type: itemType || "item",
    tool,
    status: item.status || (isCompleted ? "completed" : "inProgress"),
    label: item.summary || item.title || "",
    label_key: labelKey,
    detail: item.detail || item.summary || "",
    started_at: item.started_at || item.startedAt || 0,
    completed_at: isCompleted ? Date.now() : 0,
    raw: item,
  });
}

function liveRunItemFromTrace(trace) {
  const item = trace && typeof trace === "object" ? trace : {};
  const type = String(item.type || "").trim();
  const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
  const toolName = String(payload.tool_name || payload.tool || payload.name || ((payload.raw_tool_call || {}).name) || "").trim();
  const callId = toolCallIdentityFromSource(payload, String(item.id || ""));
  const traceId = String(item.id || [type, callId, item.timestamp].filter(Boolean).join(":"));
  const roundKey = String([payload.phase || payload.stream_stage || "llm", payload.tool_round ?? payload.round_idx ?? ""].filter((value) => String(value).trim()).join(":") || traceId);
  if (type === "llm.started") {
    return normalizeLiveRunItem({
      id: `llm-${roundKey}`,
      type,
      status: "waiting_model",
      label: item.title || "",
      label_key: "activity.live.model_thinking",
      detail: item.detail || "",
      started_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "llm.finished") {
    return normalizeLiveRunItem({
      id: `llm-${roundKey}`,
      type,
      status: "completed",
      label: item.title || "",
      label_key: "activity.live.model_finished",
      detail: item.detail || String(payload.model || ""),
      completed_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "llm.failed") {
    return normalizeLiveRunItem({
      id: `llm-${roundKey}`,
      type,
      status: "failed",
      label: item.title || "",
      label_key: "activity.live.model_failed",
      detail: item.detail || String(payload.message || ""),
      completed_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "answer.started" || type === "answer.delta") {
    return normalizeLiveRunItem({
      id: "answer-streaming",
      type,
      status: "running",
      label: item.title || "",
      label_key: "activity.live.answer_streaming",
      detail: item.detail || "",
      started_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "answer.done" || type === "answer.finished") {
    return normalizeLiveRunItem({
      id: "answer-streaming",
      type,
      status: "completed",
      label: item.title || "",
      label_key: "activity.live.answer_done",
      detail: item.detail || "",
      completed_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "tool_drain.started" || type === "tool_drain.progress" || type === "tool_drain.finished") {
    return normalizeLiveRunItem({
      id: `tool-drain-${String(payload.round_idx || payload.tool_round || "") || traceId}`,
      type,
      status: type === "tool_drain.finished" ? "waiting_model" : "waiting_tool",
      label: item.title || "",
      label_key: type === "tool_drain.finished" ? "activity.live.waiting_next_model" : "activity.live.tool_running",
      detail: item.detail || "",
      started_at: item.timestamp,
      completed_at: type === "tool_drain.finished" ? item.timestamp : 0,
      raw: item,
    });
  }
  if (type === "action.detected" || type === "tool.call_detected") {
    const target = toolCallTargetFromSource(payload);
    return normalizeLiveRunItem({
      id: callId || `action-${traceId}`,
      call_id: callId,
      type,
      tool: toolName,
      status: "waiting_tool",
      label: item.title || "",
      detail: target || item.detail || String(payload.summary || ""),
      started_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "action.validating") {
    const target = toolCallTargetFromSource(payload);
    return normalizeLiveRunItem({
      id: callId || `validation-${traceId}`,
      call_id: callId,
      type,
      tool: toolName,
      status: "validating",
      label: item.title || "",
      detail: target || item.detail || String(payload.summary || ""),
      started_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "action.allowed") {
    const target = toolCallTargetFromSource(payload);
    return normalizeLiveRunItem({
      id: callId || `allowed-${traceId}`,
      call_id: callId,
      type,
      tool: toolName,
      status: "waiting_tool",
      label: item.title || "",
      detail: target || item.detail || String(payload.summary || ""),
      started_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "action.blocked") {
    const target = toolCallTargetFromSource(payload);
    return normalizeLiveRunItem({
      id: callId || `blocked-${traceId}`,
      call_id: callId,
      type,
      tool: toolName,
      status: "failed",
      label: item.title || "",
      detail: target || item.detail || String(payload.summary || ""),
      completed_at: item.timestamp,
      raw: item,
    });
  }
  if (type === "tool.started" || type === "tool.finished" || type === "tool.failed") {
    const target = toolCallTargetFromSource(payload);
    return normalizeLiveRunItem({
      id: callId || `tool-${traceId}`,
      call_id: callId,
      type,
      tool: toolName,
      status: type === "tool.failed" ? "failed" : (type === "tool.finished" ? "completed" : "running"),
      label: "",
      label_key: type === "tool.finished" ? "activity.live.tool_finished" : "activity.live.tool_running",
      detail: target || item.detail || String(payload.summary || ""),
      started_at: type === "tool.started" ? item.timestamp : 0,
      completed_at: type === "tool.finished" || type === "tool.failed" ? item.timestamp : 0,
      raw: item,
    });
  }
  if (type === "observation.returned") {
    const target = toolCallTargetFromSource(payload);
    return normalizeLiveRunItem({
      id: callId || `observation-${traceId}`,
      call_id: callId,
      type,
      tool: toolName,
      status: "waiting_model",
      label: item.title || "",
      label_key: "activity.live.waiting_next_model",
      detail: target || item.detail || String(payload.summary || ""),
      completed_at: item.timestamp,
      raw: item,
    });
  }
  return null;
}

function isActivityTerminalStatus(status) {
  const normalized = normalizeProgressStatus(status);
  return normalized === "completed" || normalized === "failed" || normalized === "blocked" || normalized === "cancelled";
}

function normalizeMessageActivity(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  if (item[NORMALIZED_ACTIVITY_MARKER]) return item;
  const traceEvents = Array.isArray(item.trace_events) ? item.trace_events.map(normalizeTraceEvent) : [];
  const status = String(item.status || "");
  const startedAt = normalizeActivityTimestamp(item.started_at || (traceEvents[0] && traceEvents[0].timestamp) || 0);
  const turnStartedAt = normalizeActivityTimestamp(item.turn_started_at || item.turnStartedAt || startedAt || 0);
  const explicitFinishedAt = normalizeActivityTimestamp(item.finished_at || 0);
  const fallbackFinishedAt = isActivityTerminalStatus(status) && traceEvents.length
    ? normalizeActivityTimestamp(traceEvents[traceEvents.length - 1].timestamp || 0)
    : 0;
  const finishedAt = explicitFinishedAt || fallbackFinishedAt;
  const runDurationMs = Math.max(0, Number(item.run_duration_ms) || 0);
  const finalElapsedMs = isActivityTerminalStatus(status)
    ? Math.max(
      0,
      Number(item.final_elapsed_ms || 0) || 0,
      runDurationMs,
      turnStartedAt && finishedAt ? Math.max(0, finishedAt - turnStartedAt) : 0,
    )
    : Math.max(0, Number(item.final_elapsed_ms || 0) || 0);
  const normalizedActivity = {
    run_id: String(item.run_id || ""),
    status,
    summary: String(item.summary || ""),
    activity_loaded: Boolean(item.activity_loaded || item.activityLoaded || item.full_loaded || item.fullLoaded),
    debug_loaded: Boolean(item.debug_loaded || item.debugLoaded || item.full_loaded || item.fullLoaded),
    full_loaded: Boolean(item.full_loaded || item.fullLoaded || item.run_artifact_loaded || item.runArtifactLoaded),
    started_at: startedAt,
    turn_started_at: turnStartedAt,
    finished_at: finishedAt,
    run_duration_ms: runDurationMs,
    final_elapsed_ms: finalElapsedMs,
    activity_summary: String(item.activity_summary || ""),
    live_model_started: Boolean(item.live_model_started || item.liveModelStarted),
    live_model: String(item.live_model || item.liveModel || "").trim(),
    trace_ref: String(item.trace_ref || item.traceRef || ""),
    tool_count: Math.max(0, Number(item.tool_count || item.toolCount || 0) || 0),
    triggering_user_message: String(item.triggering_user_message || item.triggeringUserMessage || ""),
    triggering_user_turn_id: String(item.triggering_user_turn_id || item.triggeringUserTurnId || ""),
    session_id: String(item.session_id || item.sessionId || ""),
    thread_id: String(item.thread_id || item.threadId || ""),
    model_draft: String(item.model_draft || item.modelDraft || ""),
    final_answer: String(item.final_answer || item.finalAnswer || ""),
    runtime_error: normalizeRuntimeErrorPayload(item.runtime_error),
    runtime_outcome: item.runtime_outcome && typeof item.runtime_outcome === "object"
      ? item.runtime_outcome
      : {},
    runtime_inspector: item.runtime_inspector && typeof item.runtime_inspector === "object"
      ? item.runtime_inspector
      : {},
    tool_boundary_clean:
      typeof item.tool_boundary_clean === "boolean"
        ? item.tool_boundary_clean
        : null,
    llm_exchanges: Array.isArray(item.llm_exchanges) ? item.llm_exchanges : [],
    thread_items: Array.isArray(item.thread_items) ? item.thread_items : [],
    turn_trace: item.turn_trace && typeof item.turn_trace === "object" ? item.turn_trace : {},
    plan: normalizePlanChecklist(item.plan),
    plan_explanation: String(item.plan_explanation || ""),
    tool_items: normalizeActivityToolItems(item.tool_items),
    live_items: normalizeLiveRunItems(item.live_items),
    trace_events: traceEvents,
  };
  Object.defineProperty(normalizedActivity, NORMALIZED_ACTIVITY_MARKER, {
    value: true,
    enumerable: false,
  });
  return normalizedActivity;
}

function defaultSkillTemplate(locale) {
  return [
    "---",
    "name: new-skill",
    `description: ${translateUi(locale, "skill_template.summary")}`,
    "enabled: true",
    "---",
    "",
    `# ${translateUi(locale, "skill_template.title")}`,
    "",
    translateUi(locale, "skill_template.scenario"),
    translateUi(locale, "skill_template.scenario_item"),
    "",
    translateUi(locale, "skill_template.execution"),
    translateUi(locale, "skill_template.execution_item"),
    "",
  ].join("\n");
}

function sessionTitleFromList(sessions, sessionId, locale) {
  const hit = sessions.find((item) => item.session_id === sessionId);
  return hit
    ? hit.title || hit.display_title || translateUi(locale, "labels.new_thread")
    : translateUi(locale, "labels.start_building");
}

function translateUiOrFallback(locale, key, fallback, replacements = null) {
  const translated = translateUi(locale, key, replacements);
  const text = String(translated || "").trim();
  if (text && text !== key) return translated;
  if (replacements && typeof replacements === "object") {
    return String(fallback || "").replace(/\{([^}]+)\}/g, (match, name) => (
      Object.prototype.hasOwnProperty.call(replacements, name) ? String(replacements[name]) : match
    ));
  }
  return fallback;
}

function workbenchSpecUrl(specName, locale) {
  const base = specName
    ? `/api/workbench/specs/${encodeURIComponent(String(specName || "").trim())}`
    : "/api/workbench/specs";
  const normalizedLocale = String(locale || "").trim();
  if (!normalizedLocale) return base;
  return `${base}?locale=${encodeURIComponent(normalizedLocale)}`;
}

function shallowSkillList(skills) {
  return Array.isArray(skills) ? skills.map(normalizeSkillDescriptor) : [];
}

function normalizeTaskDescriptor(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  const status = ["active", "blocked", "completed", "archived"].includes(String(item.status || ""))
    ? String(item.status)
    : "active";
  const stringList = (value) => (Array.isArray(value) ? value.map((entry) => String(entry || "").trim()).filter(Boolean) : []);
  return {
    ...item,
    task_id: String(item.task_id || item.id || "").trim(),
    project_id: String(item.project_id || "").trim(),
    title: String(item.title || "").trim(),
    status,
    goal: String(item.goal || "").trim(),
    summary: String(item.summary || "").trim(),
    progress: stringList(item.progress),
    next_steps: stringList(item.next_steps),
    decisions: stringList(item.decisions),
    blockers: stringList(item.blockers),
    artifacts: stringList(item.artifacts),
    updated_at: String(item.updated_at || "").trim(),
  };
}

function normalizeSkillDescriptor(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  const rawScope = String(item.scope || item.source || "team").trim().toLowerCase() || "team";
  const scope = rawScope === "system" ? "builtin" : (rawScope === "workspace" ? "team" : rawScope);
  const name = String(item.name || item.id || "").trim();
  const key = String(item.key || (name ? `${scope}:${name}` : "")).trim();
  return {
    ...item,
    key,
    scope,
    name,
    description: String(item.description || item.summary || "").trim(),
    read_only: Boolean(item.read_only),
  };
}

function skillKey(item) {
  return String((item && (item.key || "")) || "").trim();
}

function skillName(item) {
  return String((item && (item.name || item.id || "")) || "").trim();
}

function skillScope(item) {
  const rawScope = String((item && (item.scope || item.source || "")) || "team").trim().toLowerCase() || "team";
  return rawScope === "system" ? "builtin" : (rawScope === "workspace" ? "team" : rawScope);
}

function workbenchSkillUrl(itemOrName, scope) {
  const name = typeof itemOrName === "string" ? itemOrName : skillName(itemOrName);
  const resolvedScope = scope || (typeof itemOrName === "string" ? "team" : skillScope(itemOrName));
  return `/api/workbench/skills/${encodeURIComponent(String(name || "").trim())}?scope=${encodeURIComponent(String(resolvedScope || "team").trim())}`;
}

function workbenchSkillActionUrl(itemOrName, scope, action) {
  const name = typeof itemOrName === "string" ? itemOrName : skillName(itemOrName);
  const resolvedScope = scope || (typeof itemOrName === "string" ? "team" : skillScope(itemOrName));
  const suffix = String(action || "").trim();
  return `/api/workbench/skills/${encodeURIComponent(String(name || "").trim())}/${encodeURIComponent(suffix)}?scope=${encodeURIComponent(String(resolvedScope || "team").trim())}`;
}

function groupSkillsByScope(skills) {
  const grouped = { builtin: [], team: [] };
  shallowSkillList(skills).forEach((item) => {
    const scope = skillScope(item) === "builtin" ? "builtin" : "team";
    grouped[scope].push(item);
  });
  return grouped;
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

function stringifyCompactJson(value) {
  if (!value || typeof value !== "object") return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function hasDisplayValue(value) {
  if (value == null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function displayValueText(value) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return stringifyCompactJson(value);
}

function normalizeRuntimeErrorPayload(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
  return {
    kind: String(item.kind || "").trim(),
    layer: String(item.layer || "").trim(),
    phase: String(item.phase || "").trim(),
    model: String(item.model || "").trim(),
    message: String(item.message || "").trim(),
    exception_type: String(item.exception_type || item.exceptionType || "").trim(),
    raw_message: String(item.raw_message || item.rawMessage || "").trim(),
    traceback_tail: String(item.traceback_tail || item.tracebackTail || "").trim(),
    tool_boundary_clean:
      typeof item.tool_boundary_clean === "boolean"
        ? item.tool_boundary_clean
        : null,
    last_successful_round: Math.max(0, Number(item.last_successful_round || 0) || 0),
    failed_round: Math.max(0, Number(item.failed_round || 0) || 0),
    tool_count_total: Math.max(0, Number(item.tool_count_total || 0) || 0),
  };
}

function formatValidationStatus(locale, status) {
  const normalized = String(status || "").trim();
  if (!normalized) return "-";
  return translateUiOrFallback(locale, `validation.${normalized}`, normalized);
}

function formatActivityTraceTitle(locale, trace) {
  const item = trace && typeof trace === "object" ? trace : {};
  const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
  const activity = payload.activity && typeof payload.activity === "object" ? payload.activity : {};
  const stage = String(activity.stage || "").trim();
  if (stage) {
    const label = translateUiOrFallback(locale, `activity.stage.${stage}`, "");
    if (label) return label;
  }
  return String(item.title || item.type || translateUi(locale, "labels.processing"));
}

function activityStageKeyFromTrace(trace, options = {}) {
  const item = trace && typeof trace === "object" ? trace : {};
  const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
  const activity = payload.activity && typeof payload.activity === "object" ? payload.activity : {};
  const stage = String(activity.stage || "").trim();
  const allowLegacy = Boolean(options.allowLegacy);
  const canonicalStages = new Set(["model_action", "action_validation", "execution", "loop.safeguard"]);
  if (canonicalStages.has(stage)) return stage;
  if (allowLegacy && stage) return stage;
  const type = String(item.type || "").trim();
  if (type.startsWith("answer.")) return "execution";
  if (allowLegacy && type.startsWith("tool.")) return "tool_decision";
  return "";
}

function activityStageStatusFromTrace(trace) {
  const item = trace && typeof trace === "object" ? trace : {};
  const type = String(item.type || "").trim();
  const status = String(item.status || "").trim();
  if (status === "failed" || status === "error" || type === "run.failed") return "failed";
  if (status === "blocked" || type === "blocked") return "blocked";
  if (status === "cancelled" || type === "cancelled") return "cancelled";
  if (
    status === "success"
    || status === "completed"
    || type === "activity.done"
    || type === "answer.done"
    || type === "answer.finished"
    || type === "run.finished"
  ) {
    return "completed";
  }
  return "running";
}

function buildActivityFlowStages(activity, locale) {
  const item = normalizeMessageActivity(activity || {});
  const traces = item.trace_events.filter((trace) => trace.visible !== false);
  const labelForTrace = (trace, stageKey) => {
    const entry = trace && typeof trace === "object" ? trace : {};
    const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : {};
    const modelAction = payload.model_action && typeof payload.model_action === "object"
      ? payload.model_action
      : {};
    const executionEntry = payload.execution_trace_entry && typeof payload.execution_trace_entry === "object"
      ? payload.execution_trace_entry
      : {};
    const validationResult = payload.validation_result && typeof payload.validation_result === "object" ? payload.validation_result : {};
    const actionType = String(
      executionEntry.action_type
      || modelAction.action_type
      || "",
    ).trim();
    const validationAllowed = Boolean(validationResult.allowed);
    const validationCode = String(validationResult.code || "").trim();
    const type = String(entry.type || "").trim();
    const stageStatus = activityStageStatusFromTrace(entry);
    const guardStatus = validationResult.allowed === false ? "rejected" : (validationAllowed ? "allowed" : "");
    if (stageKey === "model_action") {
      if (actionType === "tool_call") return translateUi(locale, "activity.status.tool_guard_pending");
      if (actionType === "final_answer") return translateUi(locale, "activity.status.direct_answer_no_tool");
      return translateUi(locale, "activity.status.request_understood");
    }
    if (stageKey === "action_validation") {
      if (validationAllowed && validationCode === "allowed") return translateUi(locale, "activity.status.tool_guard_normalized");
      if (!validationAllowed || stageStatus === "blocked") return translateUi(locale, "activity.status.tool_guard_rejected");
      if (actionType === "tool_call") return translateUi(locale, "activity.status.tool_guard_pending");
    }
    if (stageKey === "execution") {
      if (type === "answer.delta") return translateUi(locale, "activity.status.answer_streaming");
      if (type === "answer.done" || type === "answer.finished") return translateUi(locale, "activity.status.answer_ready");
      if (actionType === "tool_call") {
        if (guardStatus === "rejected" || stageStatus === "blocked") return translateUi(locale, "activity.status.tool_guard_rejected");
        if (stageStatus === "completed" || stageStatus === "success") return translateUi(locale, "activity.status.tool_completed");
        return translateUi(locale, "activity.status.tool_running");
      }
      if (actionType === "direct_answer") return translateUi(locale, "activity.status.answer_generating");
    }
    return translateUiOrFallback(locale, `activity.stage.${stageKey}`, stageKey);
  };
  const collectStages = (allowLegacy) => {
    const stages = new Map();
    traces.forEach((trace) => {
      const stageKey = activityStageKeyFromTrace(trace, { allowLegacy });
      if (!stageKey) return;
      stages.set(stageKey, {
        key: stageKey,
        label: labelForTrace(trace, stageKey),
        status: activityStageStatusFromTrace(trace),
      });
    });
    return Array.from(stages.values());
  };
  const canonicalStages = collectStages(false);
  return canonicalStages.length ? canonicalStages : collectStages(true);
}

function latestRevisionSummary(activity) {
  const item = normalizeMessageActivity(activity || {});
  const traces = [...item.trace_events].reverse();
  for (const trace of traces) {
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    const summary = payload.revision_summary && typeof payload.revision_summary === "object" ? payload.revision_summary : {};
    if (Array.isArray(summary.items) && summary.items.length) return summary;
  }
  return {};
}

function formatRevisionSummaryBadge(locale, summary) {
  const item = summary && typeof summary === "object" ? summary : {};
  const entries = Array.isArray(item.items) ? item.items : [];
  if (!entries.length) return "";
  const firstEntry = entries[0] && typeof entries[0] === "object" ? entries[0] : {};
  const firstLabel = String(firstEntry.label || "").trim();
  if (entries.length === 1 && firstLabel) {
    return `${translateUi(locale, "activity.revision_summary")} · ${firstLabel}`;
  }
  return translateUi(locale, "activity.revision_summary_count", { count: entries.length });
}

function normalizeProgressStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "pending";
  if (["completed", "success", "done", "ok"].includes(normalized)) return "completed";
  if (["in_progress", "inprogress", "running", "active", "working", "tooling", "answering"].includes(normalized)) return "running";
  if (["validating", "checking", "guarding"].includes(normalized)) return "validating";
  if (["waiting_model", "waiting-model", "model_wait", "thinking"].includes(normalized)) return "waiting_model";
  if (["waiting_tool", "waiting-tool", "tool_wait", "waiting_result"].includes(normalized)) return "waiting_tool";
  if (["background_running", "background-running"].includes(normalized)) return "background_running";
  if (["failed", "error"].includes(normalized)) return "failed";
  if (["blocked", "needs_user_input"].includes(normalized)) return "blocked";
  if (["cancelled", "canceled"].includes(normalized)) return "cancelled";
  return "pending";
}

function latestActivityPayloadValue(activity, keys, expectedKind = "object") {
  const item = normalizeMessageActivity(activity || {});
  const keyList = Array.isArray(keys) ? keys : [keys];
  const traces = [...item.trace_events].reverse();
  for (const trace of traces) {
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    for (const key of keyList) {
      const value = payload[key];
      if (expectedKind === "array") {
        if (Array.isArray(value) && value.length) return value;
        continue;
      }
      if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length) return value;
    }
  }
  return expectedKind === "array" ? [] : {};
}

function latestExecutionTrace(activity) {
  const fullTrace = latestActivityPayloadValue(activity, "execution_trace", "array");
  if (fullTrace.length) return fullTrace;
  const item = normalizeMessageActivity(activity || {});
  const entries = [];
  const seen = new Set();
  item.trace_events.forEach((trace, index) => {
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    const entry = payload.execution_trace_entry && typeof payload.execution_trace_entry === "object"
      ? payload.execution_trace_entry
      : null;
    if (!entry) return;
    const key = [
      entry.step_index,
      entry.action_type,
      entry.tool_name,
      entry.status,
      entry.result_summary,
      index,
    ].join(":");
    if (seen.has(key)) return;
    seen.add(key);
    entries.push(entry);
  });
  return entries;
}

function shortenActivityTarget(value, limit = 52) {
  const text = String(value || "").trim().replace(/\s+/g, " ");
  if (!text) return "";
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function toolCallIdentityFromSource(source, fallback = "") {
  const item = source && typeof source === "object" ? source : {};
  const rawToolCall = item.raw_tool_call && typeof item.raw_tool_call === "object" ? item.raw_tool_call : {};
  const validationResult = item.validation_result && typeof item.validation_result === "object" ? item.validation_result : {};
  const candidates = [
    item.tool_call_id,
    item.call_id,
    validationResult.call_id,
    validationResult.tool_call_id,
    rawToolCall.id,
    item.id,
    fallback,
  ];
  for (const candidate of candidates) {
    const resolved = String(candidate || "").trim();
    if (resolved && resolved !== "***") return resolved;
  }
  return "";
}

function toolCallTargetFromSource(source) {
  const item = source && typeof source === "object" ? source : {};
  const rawToolCall = item.raw_tool_call && typeof item.raw_tool_call === "object" ? item.raw_tool_call : {};
  const rawCallArguments = rawToolCall.arguments && typeof rawToolCall.arguments === "object" ? rawToolCall.arguments : {};
  const rawArguments = item.raw_arguments && typeof item.raw_arguments === "object" ? item.raw_arguments : {};
  const normalizedArguments =
    item.normalized_arguments && typeof item.normalized_arguments === "object" ? item.normalized_arguments : {};
  const candidates = [
    normalizedArguments.path,
    normalizedArguments.file,
    normalizedArguments.query,
    normalizedArguments.q,
    normalizedArguments.url,
    normalizedArguments.command,
    normalizedArguments.cmd,
    normalizedArguments.cwd,
    normalizedArguments.root,
    normalizedArguments.pattern,
    normalizedArguments.glob,
    normalizedArguments.patch,
    normalizedArguments.text,
    rawArguments.path,
    rawArguments.file,
    rawArguments.query,
    rawArguments.q,
    rawArguments.url,
    rawArguments.command,
    rawArguments.cmd,
    rawArguments.cwd,
    rawArguments.root,
    rawArguments.pattern,
    rawArguments.glob,
    rawCallArguments.path,
    rawCallArguments.file,
    rawCallArguments.query,
    rawCallArguments.q,
    rawCallArguments.url,
    rawCallArguments.command,
    rawCallArguments.cmd,
    rawCallArguments.cwd,
    rawCallArguments.root,
    rawCallArguments.pattern,
    rawCallArguments.glob,
    item.arguments_preview,
    item.detail,
    item.summary,
  ];
  for (const candidate of candidates) {
    const text = shortenActivityTarget(candidate);
    if (text) return text;
  }
  return "";
}

function formatToolTitle(locale, toolName) {
  const normalized = String(toolName || "").trim();
  if (!normalized) return translateUiOrFallback(locale, "activity.tool_title.use_tool", "调用工具");
  return translateUiOrFallback(
    locale,
    `activity.tool_title.${normalized}`,
    translateUiOrFallback(locale, "activity.tool_title.use_tool_named", `调用工具 ${normalized}`, { tool: normalized }),
    { tool: normalized },
  );
}

function toolProgressPhaseFromStatus(status, type) {
  const normalizedStatus = normalizeProgressStatus(status);
  const normalizedType = String(type || "").trim();
  if (["completed", "failed", "blocked", "cancelled", "waiting_model"].includes(normalizedStatus)) return "";
  if (
    normalizedStatus === "waiting_tool"
    || normalizedStatus === "validating"
    || normalizedType === "action.detected"
    || normalizedType === "tool.call_detected"
    || normalizedType === "action.validating"
    || normalizedType === "action.allowed"
  ) {
    return "preparing";
  }
  if (normalizedStatus === "running" || normalizedType === "tool.started") return "active";
  return "";
}

function formatToolProgressLabel(locale, group, options = {}) {
  const item = group && typeof group === "object" ? group : {};
  const toolName = String(item.tool_name || "").trim();
  const target = toolCallTargetFromSource(item);
  const labelValue = target || toolName || "tool";
  const readTools = new Set(["read_file", "read_section", "image_read", "image_inspect", "table_extract"]);
  const listTools = new Set(["list_dir"]);
  const globTools = new Set(["glob_file_search"]);
  const searchTools = new Set(["search_contents_in_file", "search_contents_in_file_multi", "search_codebase", "fact_check_file", "web_search", "web_fetch", "web_download"]);
  const commandTools = new Set(["exec_command", "run_command", "shell", "bash"]);
  const patchTools = new Set(["apply_patch"]);
  let label = "";
  if (readTools.has(toolName)) label = translateUi(locale, "activity.progress.read", { target: labelValue });
  else if (listTools.has(toolName)) label = translateUi(locale, "activity.progress.list_dir", { target: labelValue });
  else if (globTools.has(toolName)) label = translateUi(locale, "activity.progress.glob_file_search", { target: labelValue });
  else if (searchTools.has(toolName)) label = translateUi(locale, "activity.progress.search", { target: labelValue });
  else if (commandTools.has(toolName)) label = translateUi(locale, "activity.progress.execute_command", { target: labelValue });
  else if (patchTools.has(toolName)) label = translateUi(locale, "activity.progress.apply_patch", { target: labelValue });
  else label = translateUi(locale, "activity.progress.use_tool", { tool: labelValue });
  const phase = String(options.phase || toolProgressPhaseFromStatus(options.status || item.status, options.type || item.type)).trim();
  if (phase === "preparing") return translateUi(locale, "activity.progress.preparing", { label });
  if (phase === "active") return translateUi(locale, "activity.progress.active", { label });
  return label;
}

function formatLiveAgentToolActionText(locale, options = {}) {
  const item = options && typeof options === "object" ? options : {};
  const tool = String(item.tool || item.tool_name || "").trim();
  const type = String(item.type || "").trim();
  const status = normalizeProgressStatus(item.status || "");
  const target = String(item.target || item.detail || item.command || "").trim();
  const hasActualTool = Boolean(
    tool
    || type === "toolCall"
    || type === "commandExecution"
    || type === "fileChange"
    || type === "imageView"
    || type.startsWith("tool.")
    || type.startsWith("action.")
    || type === "observation.returned"
  );
  if (!hasActualTool) return "";
  const toolAction = formatToolProgressLabel(locale, {
    tool_name: tool,
    normalized_arguments: target ? { query: target } : {},
    arguments_preview: target,
    detail: target,
  });
  const phase = toolProgressPhaseFromStatus(status, type);
  if (phase === "preparing") {
    return toolAction
      ? translateUi(locale, "run.live_agent.tool_preparing_detail", { detail: toolAction })
      : (tool ? translateUi(locale, "run.live_agent.tool_preparing_named", { tool }) : translateUi(locale, "run.live_agent.tool_preparing"));
  }
  if (phase === "active") {
    return toolAction
      ? translateUi(locale, "run.live_agent.tool_running_detail", { detail: toolAction })
      : (tool ? translateUi(locale, "run.live_agent.tool_running_named", { tool }) : translateUi(locale, "run.live_agent.tool_running"));
  }
  if (status === "waiting_model" || status === "completed" || type === "observation.returned" || type === "tool.finished") {
    return toolAction
      ? translateUi(locale, "run.live_agent.tool_result_detail", { detail: toolAction })
      : (tool ? translateUi(locale, "run.live_agent.tool_result_named", { tool }) : translateUi(locale, "run.live_agent.tool_result"));
  }
  return "";
}

function buildPlanChecklistItems(plan) {
  return normalizePlanChecklist(plan).map((entry, index) => ({
    id: `plan-${index}-${entry.step}`,
    label: entry.step,
    detail: entry.detail,
    status: normalizeProgressStatus(entry.status),
    source: "plan",
  }));
}

function buildToolProgressGroups(activity) {
  const item = normalizeMessageActivity(activity || {});
  const groups = new Map();
  const ensureGroup = (source, fallbackId, fallbackName, orderIndex) => {
    const sourceItem = source && typeof source === "object" ? source : {};
    const id = toolCallIdentityFromSource(sourceItem, fallbackId || fallbackName || `tool-${orderIndex}`);
    if (!groups.has(id)) {
      groups.set(id, {
        id,
        order_index: orderIndex,
        tool_name: String(
          sourceItem.tool_name
          || sourceItem.tool
          || sourceItem.name
          || ((sourceItem.raw_tool_call || {}).name)
          || fallbackName
          || "tool",
        ).trim(),
        status: "pending",
        trace_types: [],
        raw_tool_call: sourceItem.raw_tool_call && typeof sourceItem.raw_tool_call === "object" ? sourceItem.raw_tool_call : {},
        raw_arguments: sourceItem.raw_arguments,
        normalized_arguments:
          sourceItem.normalized_arguments && typeof sourceItem.normalized_arguments === "object" ? sourceItem.normalized_arguments : {},
        validation_result: sourceItem.validation_result && typeof sourceItem.validation_result === "object" ? sourceItem.validation_result : {},
        schema_validation:
          sourceItem.schema_validation && typeof sourceItem.schema_validation === "object" ? sourceItem.schema_validation : {},
        arguments_preview: String(sourceItem.arguments_preview || "").trim(),
        result_preview: sourceItem.result_preview,
        summary: String(sourceItem.summary || "").trim(),
        detail: "",
        duration_ms: Math.max(0, Number(sourceItem.duration_ms || 0) || 0),
        requested_by_item_id: String(sourceItem.requested_by_item_id || "").trim(),
        tool_call_id: String(sourceItem.tool_call_id || id || "").trim(),
        item_id: String(sourceItem.item_id || "").trim(),
        error_kind: String(sourceItem.error_kind || "").trim(),
        retry_count: Math.max(0, Number(sourceItem.retry_count || 0) || 0),
        recovery_result: String(sourceItem.recovery_result || "").trim(),
      });
    }
    return groups.get(id);
  };

  item.trace_events.forEach((trace, index) => {
    const type = String((trace && trace.type) || "").trim();
    if (!type.startsWith("tool.")) return;
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    const group = ensureGroup(payload, `trace-${index}`, String(payload.tool_name || "").trim(), index);
    group.trace_types.push(type);
    if (!group.raw_tool_call || !Object.keys(group.raw_tool_call).length) {
      group.raw_tool_call = payload.raw_tool_call && typeof payload.raw_tool_call === "object" ? payload.raw_tool_call : group.raw_tool_call;
    }
    if (!group.raw_arguments && Object.prototype.hasOwnProperty.call(payload, "raw_arguments")) {
      group.raw_arguments = payload.raw_arguments;
    }
    if (!Object.keys(group.normalized_arguments).length && payload.normalized_arguments && typeof payload.normalized_arguments === "object") {
      group.normalized_arguments = payload.normalized_arguments;
    }
    if (!Object.keys(group.validation_result).length && payload.validation_result && typeof payload.validation_result === "object") {
      group.validation_result = payload.validation_result;
    }
    if (!Object.keys(group.schema_validation).length && payload.schema_validation && typeof payload.schema_validation === "object") {
      group.schema_validation = payload.schema_validation;
    }
    if (!group.arguments_preview) group.arguments_preview = String(payload.arguments_preview || "").trim();
    if (!hasDisplayValue(group.result_preview) && Object.prototype.hasOwnProperty.call(payload, "result_preview")) {
      group.result_preview = payload.result_preview;
    }
    if (!group.summary) group.summary = String(payload.summary || trace.detail || "").trim();
    if (!group.detail) group.detail = String(trace.detail || "").trim();
    if (!group.duration_ms) group.duration_ms = Math.max(0, Number(trace.duration_ms || payload.duration_ms || 0) || 0);
    if (type === "tool.failed") {
      group.status = "failed";
    } else if (type === "tool.finished" && group.status !== "failed") {
      group.status = "completed";
    } else if (type === "action.blocked") {
      if (payload.validation_result && payload.validation_result.allowed === false) {
        group.status = "blocked";
      } else if (group.status !== "completed" && group.status !== "failed") {
        group.status = "running";
      }
    } else if (group.status === "pending") {
      group.status = "running";
    }
  });

  item.tool_items.forEach((toolItem, index) => {
    const group = ensureGroup(toolItem, `item-${index}`, String(toolItem.tool || toolItem.name || "").trim(), item.trace_events.length + index);
    if (!group.tool_name) group.tool_name = String(toolItem.tool || toolItem.name || "").trim();
    if (!Object.keys(group.raw_tool_call).length) group.raw_tool_call = toolItem.raw_tool_call || {};
    if (!group.raw_arguments && Object.prototype.hasOwnProperty.call(toolItem, "raw_arguments")) {
      group.raw_arguments = toolItem.raw_arguments;
    }
    if (!Object.keys(group.normalized_arguments).length) group.normalized_arguments = toolItem.normalized_arguments || {};
    if (!Object.keys(group.validation_result).length) group.validation_result = toolItem.validation_result || {};
    if (!Object.keys(group.schema_validation).length) group.schema_validation = toolItem.schema_validation || {};
    if (!group.arguments_preview) group.arguments_preview = String(toolItem.arguments_preview || "").trim();
    if (!hasDisplayValue(group.result_preview) && Object.prototype.hasOwnProperty.call(toolItem, "result_preview")) {
      group.result_preview = toolItem.result_preview;
    }
    if (!group.summary) group.summary = String(toolItem.summary || "").trim();
    if (!group.duration_ms) group.duration_ms = Math.max(0, Number(toolItem.duration_ms || 0) || 0);
    if (!group.requested_by_item_id) group.requested_by_item_id = String(toolItem.requested_by_item_id || "").trim();
    if (!group.tool_call_id) group.tool_call_id = String(toolItem.tool_call_id || group.id || "").trim();
    if (!group.item_id) group.item_id = String(toolItem.item_id || "").trim();
    if (!group.error_kind) group.error_kind = String(toolItem.error_kind || "").trim();
    if (!group.retry_count) group.retry_count = Math.max(0, Number(toolItem.retry_count || 0) || 0);
    if (!group.recovery_result) group.recovery_result = String(toolItem.recovery_result || "").trim();
    const toolStatus = normalizeProgressStatus(toolItem.status);
    if (["failed", "blocked", "cancelled"].includes(toolStatus)) {
      group.status = "failed";
    } else if (toolStatus === "completed" && group.status !== "failed") {
      group.status = "completed";
    } else if (["running", "waiting_tool", "validating"].includes(toolStatus) && group.status === "pending") {
      group.status = "running";
    }
  });

  return Array.from(groups.values()).sort((left, right) => left.order_index - right.order_index);
}

function latestTraceTimestampByTypes(traces, types) {
  const wanted = new Set((Array.isArray(types) ? types : [types]).map((item) => String(item || "").trim()).filter(Boolean));
  if (!wanted.size) return 0;
  for (let index = (Array.isArray(traces) ? traces.length : 0) - 1; index >= 0; index -= 1) {
    const trace = traces[index];
    const traceType = String((trace && trace.type) || "").trim();
    if (wanted.has(traceType)) {
      return normalizeActivityTimestamp((trace && trace.timestamp) || 0);
    }
  }
  return 0;
}

function hasTraceType(traces, types) {
  const wanted = new Set((Array.isArray(types) ? types : [types]).map((item) => String(item || "").trim()).filter(Boolean));
  if (!wanted.size) return false;
  return (Array.isArray(traces) ? traces : []).some((trace) => wanted.has(String((trace && trace.type) || "").trim()));
}

function latestModelNameFromTraces(traces) {
  const items = Array.isArray(traces) ? traces : [];
  for (const trace of items.slice().reverse()) {
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    const model = String(payload.effective_model || payload.model || "").trim();
    if (model) return model;
  }
  return "";
}

function liveModelNameFromActivity(activity) {
  const item = activity && typeof activity === "object" ? activity : {};
  return String(item.live_model || item.liveModel || latestModelNameFromTraces(item.trace_events) || "").trim();
}

function buildLiveAgentTimelineItems(activity, locale) {
  const item = normalizeMessageActivity(activity || {});
  if (isActivityTerminalStatus(item.status)) return [];
  return item.live_items.map((liveItem) => {
    const tool = String(liveItem.tool || "").trim();
    const liveStatus = normalizeProgressStatus(liveItem.status);
    const liveType = String(liveItem.type || "").trim();
    const target = shortenActivityTarget(liveItem.detail || "");
    const toolLabel = tool
      ? formatToolProgressLabel(locale, {
          tool_name: tool,
          normalized_arguments: target ? { query: target } : {},
          arguments_preview: target,
          detail: target,
        }, { status: liveStatus, type: liveType })
      : "";
    const labelKeyLabel = liveItem.label_key ? translateUi(locale, liveItem.label_key, { tool }) : "";
    const shouldPreferLabelKey = Boolean(tool && liveStatus === "waiting_model" && labelKeyLabel);
    const fallbackLabel = tool
      ? toolLabel
      : String(liveItem.type || "activity");
    const label = liveItem.label
      || (shouldPreferLabelKey ? labelKeyLabel : (toolLabel || labelKeyLabel))
      || fallbackLabel;
    return {
      id: `live-${liveItem.id}`,
      label,
      detail: liveItem.detail,
      status: liveStatus,
      source: "live",
      type: liveType,
      tool,
      target,
      live_item: liveItem,
    };
  });
}

function buildFallbackProgressItems(activity, locale, nowMs = Date.now()) {
  const item = normalizeMessageActivity(activity || {});
  const traces = item.trace_events.filter(Boolean);
  const progressItems = [];
  const toolGroups = buildToolProgressGroups(item);
  const liveItems = buildLiveAgentTimelineItems(item, locale);
  const groupedCallIds = new Set(
    toolGroups.map((group) => String((group && group.id) || "").trim()).filter(Boolean),
  );
  const visibleLiveItems = liveItems.filter((entry) => {
    const liveItem = entry && entry.live_item && typeof entry.live_item === "object" ? entry.live_item : {};
    const callId = String(liveItem.call_id || "").trim();
    return !callId || !groupedCallIds.has(callId);
  });
  const hasLiveItems = Boolean(visibleLiveItems.length);
  const hasStarted = Boolean(item.turn_started_at || item.started_at || traces.length);
  const llmStartedAt = latestTraceTimestampByTypes(traces, "llm.started");
  const modelWaitStartedAt = llmStartedAt || (
    item.live_model_started
      ? (normalizeActivityTimestamp(item.turn_started_at || item.started_at) || nowMs)
      : 0
  );
  const modelStarted = Boolean(item.live_model_started || llmStartedAt);
  const finalAnswerText = String(item.final_answer || "").trim();
  const hasAnswerStarted = traces.some((trace) => ["answer.started", "answer.delta", "answer.done", "answer.finished"].includes(String(trace.type || "").trim()));
  const hasAnswerReady = Boolean(finalAnswerText) || traces.some((trace) => ["answer.done", "answer.finished", "run.finished"].includes(String(trace.type || "").trim()));
  const hasAnswerDelta = traces.some((trace) => String(trace.type || "").trim() === "answer.delta");
  const turnTerminalError = ["failed", "blocked", "cancelled"].includes(normalizeProgressStatus(item.status));
  if (hasStarted) {
    progressItems.push({
      id: "request-understood",
      label: translateUi(locale, "activity.status.request_understood"),
      status: "completed",
      source: "fallback",
    });
  }
  toolGroups.forEach((group) => {
    progressItems.push({
      id: `tool-${group.id}`,
      label: formatToolProgressLabel(locale, group, { status: group.status }),
      detail: group.detail || group.summary || "",
      status: normalizeProgressStatus(group.status),
      source: "tool",
      tool_group: group,
    });
  });
  visibleLiveItems.forEach((entry) => {
    progressItems.push(entry);
  });
  if (!hasLiveItems && !toolGroups.length && !modelStarted && !hasAnswerStarted && !hasAnswerReady && !turnTerminalError) {
    progressItems.push({
      id: "request-preparing",
      label: translateUi(locale, "activity.status.preparing_request"),
      status: "running",
      source: "fallback",
    });
  } else if (!hasLiveItems && !toolGroups.length && modelStarted && !hasAnswerStarted && !hasAnswerReady && !turnTerminalError) {
    progressItems.push({
      id: "waiting-model",
      label: translateUi(
        locale,
        modelWaitStartedAt && nowMs - modelWaitStartedAt >= MODEL_WAIT_SLOW_HINT_MS
          ? "activity.status.waiting_model_slow"
          : "activity.status.waiting_model",
      ),
      status: "running",
      source: "fallback",
    });
  } else if (!hasLiveItems && !toolGroups.length && !hasAnswerStarted && !hasAnswerReady && !turnTerminalError) {
    progressItems.push({
      id: "thinking",
      label: translateUi(locale, "activity.status.thinking"),
      status: "running",
      source: "fallback",
    });
  }
  if (toolGroups.length && hasAnswerStarted && (!turnTerminalError || hasAnswerReady || hasAnswerDelta)) {
    progressItems.push({
      id: "finalizing-answer",
      label: hasAnswerReady
        ? translateUi(locale, "activity.status.answer_ready")
        : (hasAnswerDelta ? translateUi(locale, "activity.status.answer_streaming") : translateUi(locale, "activity.status.answer_generating")),
      status: hasAnswerReady ? "completed" : (item.status === "failed" ? "failed" : "running"),
      source: "fallback",
    });
  } else if (!toolGroups.length && hasAnswerStarted && (!turnTerminalError || hasAnswerReady || hasAnswerDelta)) {
    progressItems.push({
      id: "answer-direct",
      label: hasAnswerReady
        ? translateUi(locale, "activity.status.answer_ready")
        : (hasAnswerDelta ? translateUi(locale, "activity.status.answer_streaming") : translateUi(locale, "activity.status.answer_generating")),
      status: hasAnswerReady ? "completed" : (item.status === "failed" ? "failed" : "running"),
      source: "fallback",
    });
  }
  return progressItems.filter((entry, index, collection) => (
    collection.findIndex((candidate) => candidate.id === entry.id) === index
  ));
}

function buildMainLiveCards(activity, liveItems = [], runtimeTrace = [], locale = "zh-CN", nowMs = Date.now()) {
  const item = normalizeMessageActivity(activity || {});
  const sourceItems = Array.isArray(liveItems) && liveItems.length
    ? liveItems
    : buildFallbackProgressItems(item, locale, nowMs);
  const traceItems = Array.isArray(runtimeTrace) ? runtimeTrace : [];
  const cards = sourceItems.map((entry, index) => {
    const status = normalizeProgressStatus(entry.status);
    const toolGroup = entry.tool_group && typeof entry.tool_group === "object" ? entry.tool_group : {};
    const trace = traceItems[index] && typeof traceItems[index] === "object" ? traceItems[index] : {};
    const source = String(entry.source || trace.source || "").trim();
    const liveItem = entry.live_item && typeof entry.live_item === "object" ? entry.live_item : {};
    const type = String(entry.type || liveItem.type || trace.type || "").trim();
    const tool = String(entry.tool || toolGroup.tool_name || trace.tool_name || "").trim();
    const target = String(
      entry.target
      || toolCallTargetFromSource(toolGroup)
      || toolGroup.summary
      || toolGroup.arguments_preview
      || "",
    ).trim();
    const title = String(entry.label || entry.title || trace.title || (tool ? formatToolTitle(locale, tool) : "") || "").trim()
      || translateUiOrFallback(locale, "activity.tool_title.use_tool", "调用工具");
    const hasToolSignal = Boolean(tool || source === "tool" || type === "toolCall" || type === "commandExecution" || type === "fileChange" || type === "imageView" || type.startsWith("tool.") || type.startsWith("action.") || type === "observation.returned");
    const detail = String(entry.detail || trace.detail || target || "").trim()
      || (hasToolSignal ? translateUiOrFallback(locale, "activity.detail.recorded_arguments", "参数已记录") : "");
    return {
      id: String(entry.id || trace.id || `main-live-${index}`),
      title,
      label: title,
      status,
      detail,
      tool,
      target,
      source,
      type,
      durationMs: Number(trace.duration_ms || 0) || 0,
      collapsible: true,
      rawRef: entry,
    };
  });
  const modelDraftText = String(item.model_draft || "").trim();
  const finalAnswerText = String(item.final_answer || "").trim();
  const showModelDraft = Boolean(modelDraftText) && (
    !finalAnswerText
  ) && (
    !isActivityTerminalStatus(item.status)
    || normalizeProgressStatus(item.status) === "failed"
  );
  if (showModelDraft) {
    cards.unshift({
      id: "model-draft",
      title: translateUi(locale, "runtime.model_draft.title"),
      label: translateUi(locale, "runtime.model_draft.title"),
      status: normalizeProgressStatus(item.status) === "failed" ? "failed" : "running",
      detail: modelDraftText || translateUi(locale, "runtime.model_draft.empty"),
      tool: "",
      target: "",
      durationMs: 0,
      collapsible: true,
      rawRef: item,
    });
  }
  if (String(item.runtime_error.kind || item.runtime_error.message || "").trim()) {
    const errorMessage = item.runtime_error.kind === "llm_empty_response"
      ? translateUi(locale, "runtime.error.llm_empty_response")
      : (String(item.runtime_error.message || "").trim() || translateUi(locale, "runtime.error.llm_request_failed"));
    const detailLines = [
      `${translateUi(locale, "runtime.error.phase")}：${String(item.runtime_error.phase || "-").trim() || "-"}`,
      `${translateUi(locale, "runtime.error.kind")}：${String(item.runtime_error.kind || "-").trim() || "-"}`,
      errorMessage,
      translateUi(locale, "runtime.error.debug_hint"),
    ].filter(Boolean);
    cards.push({
      id: "runtime-error",
      title: translateUi(locale, "runtime.error.title"),
      label: translateUi(locale, "runtime.error.title"),
      status: "failed",
      detail: detailLines.join("\n"),
      tool: "",
      target: "",
      durationMs: 0,
      collapsible: true,
      rawRef: item.runtime_error,
    });
  }
  return cards.filter((entry, index, collection) => (
    collection.findIndex((candidate) => candidate.id === entry.id) === index
  ));
}

function liveCardSummaryText(card) {
  const item = card && typeof card === "object" ? card : {};
  const title = String(item.title || item.label || "").trim();
  const detail = String(item.detail || item.target || "").trim();
  if (title && detail && detail !== title) return `${title} · ${detail}`;
  return detail || title;
}

function resolveLiveSummary(activity, projection, locale = "zh-CN") {
  const item = normalizeMessageActivity(activity || {});
  const modelDraftText = String(item.model_draft || "").trim();
  const finalAnswerText = String(item.final_answer || "").trim();
  const cards = Array.isArray(projection && projection.main_live_cards) ? projection.main_live_cards : [];
  const reversedCards = cards.slice().reverse();
  const executionCards = reversedCards.filter((card) => String(card && card.id || "") !== "model-draft");
  const meaningful = (card) => Boolean(liveCardSummaryText(card));
  const isToolProgressCard = (card) => {
    const entry = card && typeof card === "object" ? card : {};
    const rawRef = entry.rawRef && typeof entry.rawRef === "object" ? entry.rawRef : {};
    const liveItem = rawRef.live_item && typeof rawRef.live_item === "object" ? rawRef.live_item : {};
    const type = String(entry.type || rawRef.type || liveItem.type || "").trim();
    const source = String(entry.source || rawRef.source || "").trim();
    return Boolean(entry.tool || rawRef.tool || liveItem.tool || source === "tool" || type.startsWith("tool.") || type.startsWith("action.") || type === "observation.returned");
  };
  const latestMeaningfulCurrentCard = executionCards.find((card) => (
    meaningful(card) && ["running", "failed"].includes(normalizeProgressStatus(card && card.status))
  ));
  const latestMeaningfulNonCompletedCard = executionCards.find((card) => (
    meaningful(card) && normalizeProgressStatus(card && card.status) !== "completed"
  ));
  const latestMeaningfulToolResultCard = (!isActivityTerminalStatus(item.status) && !finalAnswerText)
    ? executionCards.find((card) => meaningful(card) && normalizeProgressStatus(card && card.status) === "completed" && isToolProgressCard(card))
    : null;
  const selectedExecutionCard = (
    latestMeaningfulCurrentCard
    || latestMeaningfulNonCompletedCard
    || latestMeaningfulToolResultCard
  );
  const selectedExecutionText = liveCardSummaryText(selectedExecutionCard);
  if (selectedExecutionText) {
    return {
      title: translateUi(locale, "runtime.execution_progress.title"),
      label: translateUi(locale, "runtime.execution_progress.title"),
      text: selectedExecutionText,
      source: "execution_progress",
      card: selectedExecutionCard && typeof selectedExecutionCard === "object" ? selectedExecutionCard : {},
    };
  }
  if (modelDraftText && !finalAnswerText) {
    return {
      title: translateUi(locale, "runtime.model_draft.title"),
      label: translateUi(locale, "runtime.model_draft.title"),
      text: modelDraftText,
      source: "model_draft",
    };
  }
  const latestMeaningfulCard = executionCards.find((card) => meaningful(card));
  const latestCurrentCard = executionCards.find((card) => ["running", "failed"].includes(normalizeProgressStatus(card && card.status)));
  const latestNonCompletedCard = executionCards.find((card) => normalizeProgressStatus(card && card.status) !== "completed");
  const latestCard = executionCards[0] || reversedCards[0] || null;
  const selectedCard = latestMeaningfulCard || latestCurrentCard || latestNonCompletedCard || latestCard;
  const selectedText = liveCardSummaryText(selectedCard);
  if (selectedText) {
    return {
      title: translateUi(locale, "runtime.execution_progress.title"),
      label: translateUi(locale, "runtime.execution_progress.title"),
      text: selectedText,
      source: "execution_progress",
      card: selectedCard && typeof selectedCard === "object" ? selectedCard : {},
    };
  }
  const activitySummary = String(item.activity_summary || "").trim();
  if (activitySummary) {
    return {
      title: "",
      label: "",
      text: activitySummary,
      source: "activity_summary",
    };
  }
  return {
    title: "",
    label: "",
    text: "",
    source: "empty",
  };
}

function formatLiveSummaryText(summary) {
  const item = summary && typeof summary === "object" ? summary : {};
  const text = String(item.text || "").trim();
  const title = String(item.title || item.label || "").trim();
  if (!text) return "";
  if (!title || item.source === "activity_summary") return text;
  if (item.source === "execution_progress") return text;
  return `${title} · ${text}`;
}

function formatPendingAssistantAgentText(summary, activity, locale = "zh-CN") {
  const item = summary && typeof summary === "object" ? summary : {};
  const card = item.card && typeof item.card === "object" ? item.card : {};
  const rawRef = card.rawRef && typeof card.rawRef === "object" ? card.rawRef : {};
  const liveItem = rawRef.live_item && typeof rawRef.live_item === "object" ? rawRef.live_item : {};
  const toolGroup = rawRef.tool_group && typeof rawRef.tool_group === "object" ? rawRef.tool_group : {};
  const activityItem = normalizeMessageActivity(activity || {});
  const status = normalizeProgressStatus(activityItem.status || "");
  const modelStarted = Boolean(activityItem.live_model_started || hasTraceType(activityItem.trace_events, ["llm.started", "answer.started", "answer.delta"]));
  const modelName = liveModelNameFromActivity(activityItem);
  const title = String(card.title || card.label || item.title || item.label || "").trim();
  const tool = String(card.tool || rawRef.tool || liveItem.tool || toolGroup.tool_name || rawRef.name || "").trim();
  const type = String(card.type || rawRef.type || liveItem.type || "").trim();
  const cardSource = String(card.source || rawRef.source || item.source || "").trim();
  const cardStatus = normalizeProgressStatus(card.status || rawRef.status || liveItem.status || toolGroup.status || "");
  const target = String(
    card.target
    || rawRef.target
    || liveItem.detail
    || toolCallTargetFromSource(toolGroup)
    || "",
  ).trim();
  const detail = String(card.detail || target || item.text || "").trim();
  const hasActualTool = Boolean(tool || cardSource === "tool" || (cardSource === "live" && liveItem.tool) || type === "toolCall" || type === "commandExecution" || type === "fileChange" || type === "imageView" || type.startsWith("tool.") || type.startsWith("action.") || type === "observation.returned");
  const toolPhase = toolProgressPhaseFromStatus(cardStatus, type);
  const toolAction = hasActualTool
    ? formatToolProgressLabel(locale, {
        tool_name: tool,
        normalized_arguments: target ? { query: target } : {},
        arguments_preview: target || detail,
        detail: target || detail,
      })
    : "";
  const haystack = [
    item.source,
    title,
    detail,
    type,
    cardSource,
  ].map((value) => String(value || "").toLowerCase()).join(" ");
  const isContextCompactionActivity = Boolean(
    type === "contextCompaction"
    || type === "context.compacted"
    || type.startsWith("compaction.")
    || cardSource === "contextCompaction"
    || item.source === "contextCompaction"
  );
  if (status === "blocked") return translateUi(locale, "run.live_agent.blocked");
  if (status === "failed") return translateUi(locale, "run.live_agent.failed");
  if (item.source === "model_draft") return translateUi(locale, "run.live_agent.writing");
  if (isContextCompactionActivity) {
    return detail
      ? translateUi(locale, "run.live_agent.context_detail", { detail })
      : translateUi(locale, "run.live_agent.context");
  }
  if (hasActualTool && toolPhase === "preparing") {
    return toolAction
      ? translateUi(locale, "run.live_agent.tool_preparing_detail", { detail: toolAction })
      : (tool ? translateUi(locale, "run.live_agent.tool_preparing_named", { tool }) : translateUi(locale, "run.live_agent.tool_preparing"));
  }
  if (hasActualTool && toolPhase === "active") {
    return toolAction
      ? translateUi(locale, "run.live_agent.tool_running_detail", { detail: toolAction })
      : (tool ? translateUi(locale, "run.live_agent.tool_running_named", { tool }) : translateUi(locale, "run.live_agent.tool_running"));
  }
  if (hasActualTool && (cardStatus === "waiting_model" || cardStatus === "completed" || type === "observation.returned" || type === "tool.finished")) {
    return toolAction
      ? translateUi(locale, "run.live_agent.tool_result_detail", { detail: toolAction })
      : (tool ? translateUi(locale, "run.live_agent.tool_result_named", { tool }) : translateUi(locale, "run.live_agent.tool_result"));
  }
  if (status === "waiting_model") {
    return modelStarted
      ? (modelName
        ? translateUi(locale, "run.live_agent.model_detail", { detail: modelName })
        : translateUi(locale, "run.live_agent.model"))
      : translateUi(locale, "run.live_agent.preparing");
  }
  if (status === "background_running") return translateUi(locale, "run.live_agent.preparing");
  if (/answer|stream|final|回复|回答|生成|結果|回答/.test(haystack)) {
    return detail
      ? translateUi(locale, "run.live_agent.writing_detail", { detail })
      : translateUi(locale, "run.live_agent.writing");
  }
  if (status === "waiting_tool" || status === "validating" || status === "running") {
    return detail
      ? translateUi(locale, "run.live_agent.progress_detail", { detail })
      : translateUi(locale, "run.live_agent.default");
  }
  return "";
}

function pendingAssistantFallbackState(item, locale = "zh-CN", nowMs = Date.now()) {
  if (!item || item.role !== "assistant") {
    return {
      text: String((item && item.text) || ""),
      fromSummaryFallback: false,
      suppressNoteText: "",
    };
  }
  const activity = normalizeMessageActivity(item.activity || {});
  const currentText = String(item.text || "");
  const modelDraftText = String(activity.model_draft || "").trim();
  if (item.pending && modelDraftText && currentText.trim()) {
    return {
      text: currentText,
      fromSummaryFallback: false,
      suppressNoteText: "",
    };
  }
  if (!item.pending || String(activity.final_answer || "").trim()) {
    return {
      text: currentText,
      fromSummaryFallback: false,
      suppressNoteText: "",
    };
  }
  const projection = buildActivityProjection(activity, locale, nowMs);
  const liveSummary = resolveLiveSummary(activity, projection, locale);
  const liveSummaryText = formatLiveSummaryText(liveSummary);
  const agentText = formatPendingAssistantAgentText(liveSummary, activity, locale);
  if (agentText) {
    return {
      text: agentText,
      fromSummaryFallback: true,
      suppressNoteText: liveSummaryText,
    };
  }
  if (liveSummaryText) {
    return {
      text: liveSummaryText,
      fromSummaryFallback: true,
      suppressNoteText: liveSummaryText,
    };
  }
  return {
    text: currentText,
    fromSummaryFallback: false,
    suppressNoteText: "",
  };
}

function buildMainCompletionSummary(activity, liveCards = [], toolEvents = [], locale = "zh-CN") {
  const item = normalizeMessageActivity(activity || {});
  const sourceTools = Array.isArray(toolEvents) && toolEvents.length ? toolEvents : item.tool_items;
  const toolNames = sourceTools.map((tool) => String((tool && (tool.name || tool.tool || tool.tool_name)) || "").trim()).filter(Boolean);
  const cardTools = (Array.isArray(liveCards) ? liveCards : [])
    .map((card) => String((card && card.tool) || "").trim())
    .filter(Boolean);
  const allToolNames = toolNames.length ? toolNames : cardTools;
  const searchCount = allToolNames.filter((name) => /search|glob|grep|rg|web/i.test(name)).length;
  const readCount = allToolNames.filter((name) => /read|list|section|extract/i.test(name)).length;
  const commandCount = allToolNames.filter((name) => /exec|shell|command|pytest|apply_patch|patch/i.test(name)).length;
  const failedCount = sourceTools.filter((tool) => ["failed", "error", "blocked"].includes(normalizeProgressStatus((tool && tool.status) || ""))).length
    + (sourceTools.length ? 0 : (Array.isArray(liveCards) ? liveCards : []).filter((card) => ["failed", "blocked"].includes(normalizeProgressStatus((card && card.status) || ""))).length);
  return {
    tool_count: allToolNames.length,
    search_count: searchCount,
    read_count: readCount,
    command_count: commandCount,
    failed_count: failedCount,
    label: translateUiOrFallback(locale, "activity.execution_summary_counts", "执行摘要：搜索 {search} 次，读取 {read} 个文件，运行 {command} 个命令，{failed} 个失败", {
      search: searchCount,
      read: readCount,
      command: commandCount,
      failed: failedCount,
    }),
  };
}

function buildActivityProjection(activity, locale, nowMs = Date.now()) {
  const item = normalizeMessageActivity(activity || {});
  const projectionItem = item.trace_events.length > MAIN_CARD_TRACE_EVENT_LIMIT
    ? normalizeMessageActivity({ ...item, trace_events: item.trace_events.slice(-MAIN_CARD_TRACE_EVENT_LIMIT) })
    : item;
  const revisionSummary = latestRevisionSummary(item);
  const planItems = buildPlanChecklistItems(projectionItem.plan);
  const executionItems = buildFallbackProgressItems(projectionItem, locale, nowMs);
  const executionTrace = latestExecutionTrace(projectionItem);
  const toolGroups = buildToolProgressGroups(projectionItem);
  const mainLiveCards = buildMainLiveCards(projectionItem, executionItems, executionTrace, locale, nowMs);
  return {
    progress_items: executionItems,
    plan_items: planItems,
    execution_items: executionItems,
    main_live_cards: mainLiveCards,
    completion_summary: buildMainCompletionSummary(item, mainLiveCards, item.tool_items, locale),
    revision_summary: revisionSummary,
    revision_badge: formatRevisionSummaryBadge(locale, revisionSummary),
    plan: item.plan,
    plan_explanation: item.plan_explanation,
    trace_events: item.trace_events,
    tool_groups: toolGroups,
    tool_items: item.tool_items,
    model_action: latestActivityPayloadValue(item, ["model_action"]),
    execution_trace: executionTrace,
  };
}

function formatLocaleLabel(locale, value) {
  const normalized = String(value || "").trim();
  if (!normalized) return "-";
  return translateUiOrFallback(locale, `settings.locale.${normalized}`, normalized);
}

function formatRunFieldLabel(locale, key) {
  const normalized = String(key || "").trim();
  return translateUiOrFallback(locale, `run.field.${normalized}`, normalized);
}

function formatRunEnum(locale, group, value, fallback = "-") {
  const normalized = String(value || "").trim();
  if (!normalized) return fallback;
  return translateUiOrFallback(locale, `run.value.${group}.${normalized}`, normalized);
}

function formatRunBoolean(locale, value) {
  return formatRunEnum(locale, "bool", String(Boolean(value)), String(Boolean(value)));
}

function formatPhaseTimingLabel(locale, key) {
  const normalized = String(key || "").trim();
  if (!normalized) return "-";
  const fallback = normalized
    .replace(/_ms$/, "")
    .replaceAll("_", " ");
  return translateUiOrFallback(locale, `activity.phase.${normalized}`, fallback);
}

function formatPhaseTimingMs(value) {
  return `${Math.max(0, Number(value || 0) || 0)} ms`;
}

function formatToolGroupLabel(locale, value) {
  const normalized = String(value || "").trim() || "tool";
  return translateUiOrFallback(locale, `run.value.tool_group.${normalized}`, normalized);
}

function formatContextThresholdSource(locale, value) {
  const normalized = String(value || "").trim() || "estimate";
  return translateUiOrFallback(locale, `context_meter.source.${normalized}`, normalized);
}

function parseCompactionReason(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return null;
  const budgetMatch = normalized.match(/^context_budget_exceeded:(\d+)\/(\d+)$/);
  if (budgetMatch) {
    return {
      kind: "context_budget_exceeded",
      estimated: Math.max(0, Number(budgetMatch[1] || 0) || 0),
      limit: Math.max(0, Number(budgetMatch[2] || 0) || 0),
    };
  }
  return null;
}

function formatCompactionReason(locale, value) {
  const normalized = String(value || "").trim();
  if (!normalized) return "";
  const parsed = parseCompactionReason(normalized);
  if (parsed && parsed.kind === "context_budget_exceeded") {
    return translateUi(locale, "run.compaction_reason.context_budget_exceeded", {
      estimated: formatTokenCount(parsed.estimated),
      limit: formatTokenCount(parsed.limit),
    });
  }
  return normalized;
}

function formatCompactionWarning(locale, compactionStatus, contextMeter) {
  const status = compactionStatus && typeof compactionStatus === "object" ? compactionStatus : {};
  const meter = contextMeter && typeof contextMeter === "object" ? contextMeter : {};
  const contextWindowKnown = Object.prototype.hasOwnProperty.call(status, "context_window_known")
    ? Boolean(status.context_window_known)
    : Boolean(meter.context_window_known);
  if (!contextWindowKnown) {
    return translateUi(locale, "run.compaction_warning.fallback_budget");
  }
  return String(status.warning || meter.warning || "").trim();
}

function formatRuntimeModeLabel(locale, value) {
  const normalized = String(value || "").trim() || "host";
  return translateUiOrFallback(locale, `context_meter.mode.${normalized}`, normalized);
}

function formatRuntimeToggle(locale, value) {
  return translateUi(locale, value ? "context_meter.value.enabled" : "context_meter.value.disabled");
}

function formatRuntimeTokenUsage(locale, value) {
  const usage = value && typeof value === "object" ? value : {};
  const input = Math.max(0, Number(usage.input_tokens || 0) || 0);
  const output = Math.max(0, Number(usage.output_tokens || 0) || 0);
  const total = Math.max(0, Number(usage.total_tokens || 0) || 0);
  if (!input && !output && !total) return translateUi(locale, "context_meter.unknown");
  return translateUi(locale, "context_meter.token_usage_value", {
    input: formatTokenCount(input),
    output: formatTokenCount(output),
    total: formatTokenCount(total || (input + output)),
  });
}

function formatWallClockLimit(seconds) {
  const normalized = Math.max(0, Number(seconds || 0) || 0);
  if (!normalized) return "-";
  if (normalized % 60 === 0) return `${Math.round(normalized / 60)}m`;
  return `${normalized}s`;
}

function isCurrentThreadLiveRun({
  sessionId = "",
  activeRunThreadId = "",
  sending = false,
  activeRunId = "",
  activeRunStartedAt = 0,
  hasRunningActivity = false,
  liveTurnState = {},
}) {
  const currentThreadId = String(sessionId || "").trim();
  const runThreadId = String(activeRunThreadId || "").trim();
  if (!currentThreadId || !runThreadId || currentThreadId !== runThreadId) return false;
  return Boolean(
    sending
    || String(activeRunId || "").trim()
    || normalizeActivityTimestamp(activeRunStartedAt || 0)
    || hasRunningActivity
    || Object.keys(liveTurnState && typeof liveTurnState === "object" ? liveTurnState : {}).length
  );
}

function hasLiveThreadMessages(messages) {
  return (Array.isArray(messages) ? messages : []).some((message) => {
    if (!message || typeof message !== "object") return false;
    const activity = normalizeMessageActivity(message.activity || {});
    if (message.pending) return !isActivityTerminalStatus(activity.status);
    return Boolean(activity.turn_started_at || activity.started_at) && !isActivityTerminalStatus(activity.status);
  });
}

function hasBusyThreadMessages(messages) {
  return (Array.isArray(messages) ? messages : []).some((message) => {
    if (!message || typeof message !== "object" || !message.pending) return false;
    const activity = normalizeMessageActivity(message.activity || {});
    return !isActivityTerminalStatus(activity.status);
  });
}

function isThreadActiveTurnLive(threadId, activeTurn) {
  const key = String(threadId || "").trim();
  if (!key) return false;
  const turn = normalizeThreadActiveTurn(activeTurn);
  if (String(turn.activeRunThreadId || "").trim() !== key) return false;
  return Boolean(
    String(turn.activeRunId || "").trim()
    || normalizeActivityTimestamp(turn.startedAt || 0)
    || normalizeActivityTimestamp(turn.lastLiveProgressAt || 0)
    || normalizeActivityTimestamp((turn.liveHeartbeat || {}).updatedAt || 0)
    || Object.keys(turn.liveTurnState && typeof turn.liveTurnState === "object" ? turn.liveTurnState : {}).length
    || (Array.isArray(turn.liveRunLogs) && turn.liveRunLogs.length)
    || (Array.isArray(turn.stageTimeline) && turn.stageTimeline.length)
  );
}

function isThreadSnapshotLive(threadId, snapshot) {
  const item = snapshot && typeof snapshot === "object" ? snapshot : {};
  return Boolean(
    isThreadActiveTurnLive(threadId, item.activeTurn)
    || hasLiveThreadMessages(item.messages)
  );
}

function isThreadActiveTurnBusy(threadId, activeTurn) {
  const key = String(threadId || "").trim();
  if (!key) return false;
  const turn = normalizeThreadActiveTurn(activeTurn);
  if (turn.sending) return true;
  if (String(turn.activeRunThreadId || "").trim() !== key) return false;
  return Boolean(String(turn.activeRunId || "").trim());
}

function isThreadSnapshotBusy(threadId, snapshot) {
  const item = snapshot && typeof snapshot === "object" ? snapshot : {};
  return Boolean(
    isThreadActiveTurnBusy(threadId, item.activeTurn)
    || hasBusyThreadMessages(item.messages)
  );
}

function formatElapsedSeconds(totalSeconds, locale = "en") {
  const normalized = Math.max(0, Math.floor(Number(totalSeconds || 0) || 0));
  const hours = Math.floor(normalized / 3600);
  const minutes = Math.floor((normalized % 3600) / 60);
  const seconds = normalized % 60;
  if (hours > 0) {
    return translateUi(locale, "duration.hours_minutes_seconds", { hours, minutes, seconds });
  }
  if (minutes > 0) {
    return translateUi(locale, "duration.minutes_seconds", { minutes, seconds });
  }
  return translateUi(locale, "duration.seconds", { seconds });
}

function formatElapsedFromStartedAt(startedAt, nowMs = Date.now(), locale = "en") {
  const anchor = normalizeActivityTimestamp(startedAt || 0);
  if (!anchor) return "";
  return formatElapsedSeconds(Math.max(0, Math.floor((Math.max(anchor, nowMs) - anchor) / 1000)), locale);
}

function latestAssistantActivity(messages) {
  const items = Array.isArray(messages) ? messages : [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index];
    if (String((message && message.role) || "") !== "assistant") continue;
    const activity = normalizeMessageActivity((message && message.activity) || {});
    if (activity.turn_started_at || activity.started_at || activity.run_duration_ms || activity.trace_events.length) {
      return activity;
    }
  }
  return normalizeMessageActivity({});
}

function runtimeToolTimelineForStats({ hasLiveRuntimeState, liveToolTimeline, inspectorToolTimeline, fallbackToolTimeline }) {
  if (hasLiveRuntimeState) {
    return Array.isArray(liveToolTimeline) ? liveToolTimeline : [];
  }
  if (Array.isArray(inspectorToolTimeline) && inspectorToolTimeline.length) {
    return inspectorToolTimeline;
  }
  return Array.isArray(fallbackToolTimeline) ? fallbackToolTimeline : [];
}

function normalizeRuntimeToolOutcome(item) {
  const entry = item && typeof item === "object" ? item : {};
  const rawStatus = String(entry.status || "").trim().toLowerCase();
  const validation = entry.validation_result && typeof entry.validation_result === "object" ? entry.validation_result : {};
  const validationAllowed = validation.allowed === true;
  const resultPreview = entry.result_preview && typeof entry.result_preview === "object" ? entry.result_preview : {};
  const errorKind = String((((resultPreview.error || {}).kind) || "")).trim().toLowerCase();
  if (validation.allowed === false || errorKind === "tool_call_rejected") return "rejected";
  if (validationAllowed && rawStatus === "blocked") return "rejected";
  if (["ok", "completed", "success"].includes(rawStatus)) return "succeeded";
  if (["error", "failed", "blocked"].includes(rawStatus)) return "failed";
  return "unknown";
}

function buildRuntimeStatsSummary({
  locale,
  workspaceLabel,
  runtimeStatus,
  activeModel,
  activeTurnStatus,
  messages,
  activityClockMs,
  hasLiveRuntimeState,
  liveToolTimeline,
  inspectorToolTimeline,
  fallbackToolTimeline,
  contextMeter,
  maxOutputTokens,
  tokenUsage,
  permissionProfile,
  boundaryModelView: boundaryModelViewOverride,
  sessionId = "",
  activeRunThreadId = "",
  activeRunStartedAt = 0,
  sending = false,
  hasRunningActivity = false,
  liveTurnState = {},
}) {
  const currentRuntimeStatus = runtimeStatus && typeof runtimeStatus === "object" ? runtimeStatus : {};
  const safeguards = (currentRuntimeStatus.loop_safeguards && typeof currentRuntimeStatus.loop_safeguards === "object")
    ? currentRuntimeStatus.loop_safeguards
    : {};
  const providerDiagnostics = (currentRuntimeStatus.provider_diagnostics && typeof currentRuntimeStatus.provider_diagnostics === "object")
    ? currentRuntimeStatus.provider_diagnostics
    : {};
  const workspaceBoundary = (currentRuntimeStatus.workspace_boundary && typeof currentRuntimeStatus.workspace_boundary === "object")
    ? currentRuntimeStatus.workspace_boundary
    : {};
  const boundaryViewOverride = boundaryModelViewOverride && typeof boundaryModelViewOverride === "object" ? boundaryModelViewOverride : {};
  const boundaryModelView = Object.keys(boundaryViewOverride).length
    ? boundaryViewOverride
    : ((workspaceBoundary.model_view && typeof workspaceBoundary.model_view === "object") ? workspaceBoundary.model_view : {});
  const activity = latestAssistantActivity(messages);
  const toolTimeline = runtimeToolTimelineForStats({
    hasLiveRuntimeState,
    liveToolTimeline,
    inspectorToolTimeline,
    fallbackToolTimeline,
  });
  let succeeded = 0;
  let failed = 0;
  let rejected = 0;
  for (const item of toolTimeline) {
    const outcome = normalizeRuntimeToolOutcome(item);
    if (outcome === "succeeded") succeeded += 1;
    else if (outcome === "rejected") rejected += 1;
    else if (outcome === "failed") failed += 1;
  }
  const latestTool = toolTimeline.length
    ? (
      hasLiveRuntimeState
        ? toolTimeline[0]
        : toolTimeline[toolTimeline.length - 1]
    )
    : null;
  const latestToolName = String(
    ((latestTool && (latestTool.tool || latestTool.name || latestTool.type)) || "")
  ).trim() || "-";
  const safeContextMeter = contextMeter && typeof contextMeter === "object" ? contextMeter : {};
  const estimatedTokens = Math.max(0, Number(safeContextMeter.estimated_tokens || 0) || 0);
  const contextWindow = Math.max(0, Number(safeContextMeter.context_window || 0) || 0);
  const usedRatioByWindow = contextWindow > 0 ? Math.min(1, estimatedTokens / contextWindow) : 0;
  const usedPercent = contextWindow > 0
    ? Math.max(0, Math.min(100, Math.round(usedRatioByWindow * 100)))
    : null;
  const remainingPercent = usedPercent == null ? null : Math.max(0, 100 - usedPercent);
  const contextUsage = contextWindow > 0
    ? `${formatTokenCount(estimatedTokens)} / ${formatTokenCount(contextWindow)}`
    : translateUi(locale, "context_meter.unknown");
  const compactUsage = usedPercent == null
    ? translateUi(locale, "context_meter.compact_usage_unknown")
    : translateUi(locale, "context_meter.compact_usage", { used: usedPercent, remaining: remainingPercent });
  const compactTokens = contextWindow > 0
    ? translateUi(locale, "context_meter.compact_tokens", {
      used: formatTokenCount(estimatedTokens),
      total: formatTokenCount(contextWindow),
    })
    : translateUi(locale, "context_meter.compact_tokens_unknown");
  const isCurrentThreadActiveRun = isCurrentThreadLiveRun({
    sessionId,
    activeRunThreadId,
    sending,
    activeRunStartedAt,
    hasRunningActivity,
    liveTurnState,
  });
  const elapsedValue = (
    (isCurrentThreadActiveRun ? formatElapsedFromStartedAt(activeRunStartedAt, activityClockMs || Date.now(), locale) : "")
    || formatActivityDuration(activity, activityClockMs || Date.now(), locale)
    || translateUi(locale, "context_meter.unknown")
  );
  const autoCompactionEnabled = Boolean(safeContextMeter.compaction_enabled || safeguards.context_compaction);
  const effectivePermissionProfile = normalizePermissionProfile(
    permissionProfile
    || currentRuntimeStatus.permission_profile
    || workspaceBoundary.permission_profile
    || boundaryModelView.permission_profile
    || "auto",
  );
  const networkReason = String(boundaryModelView.network_reason || workspaceBoundary.network_reason || "").trim();
  const networkAllowed = Object.prototype.hasOwnProperty.call(boundaryModelView, "network_allowed")
    ? Boolean(boundaryModelView.network_allowed)
    : Boolean(workspaceBoundary.network_allowed);
  const networkValue = networkAllowed
    ? translateUi(locale, "context_meter.network.enabled")
    : translateUiOrFallback(locale, `context_meter.network.${networkReason || "disabled"}`, formatRuntimeToggle(locale, false));
  return {
    compact: [
      { key: "usage", text: compactUsage },
      { key: "tokens", text: compactTokens },
      { key: "elapsed_tools", text: translateUi(locale, "context_meter.compact_elapsed_tools", { elapsed: elapsedValue, count: toolTimeline.length }) },
      { key: "compaction", text: translateUi(locale, "context_meter.compact_auto_compact", { status: formatRuntimeToggle(locale, autoCompactionEnabled) }) },
    ],
    run: [
      { key: "project", label: translateUi(locale, "context_meter.field.project"), value: workspaceLabel || "-" },
      { key: "status", label: translateUi(locale, "context_meter.field.status"), value: formatRunEnum(locale, "turn_status", activeTurnStatus, "-") },
      { key: "model", label: translateUi(locale, "context_meter.field.model"), value: activeModel || "-" },
      { key: "elapsed", label: translateUi(locale, "context_meter.field.elapsed"), value: elapsedValue },
      { key: "runtime_mode", label: translateUi(locale, "context_meter.field.runtime_mode"), value: formatRuntimeModeLabel(locale, currentRuntimeStatus.execution_mode) },
      { key: "permission_profile", label: translateUi(locale, "context_meter.field.permission_profile"), value: translateUi(locale, `settings.permission_profile.${effectivePermissionProfile}`) },
      { key: "file_read_scope", label: translateUi(locale, "context_meter.field.file_read_scope"), value: boundaryModelView.file_read_scope || "-" },
      { key: "file_write_scope", label: translateUi(locale, "context_meter.field.file_write_scope"), value: boundaryModelView.file_write_scope || "-" },
      { key: "command_scope", label: translateUi(locale, "context_meter.field.command_scope"), value: boundaryModelView.command_scope || "-" },
      { key: "network", label: translateUi(locale, "context_meter.field.network"), value: networkValue },
    ],
    tools: [
      { key: "total", label: translateUi(locale, "context_meter.field.tool_total"), value: String(toolTimeline.length) },
      { key: "succeeded", label: translateUi(locale, "context_meter.field.tool_succeeded"), value: String(succeeded) },
      { key: "failed", label: translateUi(locale, "context_meter.field.tool_failed"), value: String(failed) },
      { key: "rejected", label: translateUi(locale, "context_meter.field.tool_rejected"), value: String(rejected) },
      { key: "latest", label: translateUi(locale, "context_meter.field.tool_latest"), value: latestToolName },
    ],
    context: [
      { key: "usage", label: translateUi(locale, "context_meter.field.context_usage"), value: contextUsage },
      { key: "remaining", label: translateUi(locale, "context_meter.field.remaining"), value: formatTokenCount(safeContextMeter.remaining_tokens) },
      { key: "estimate_mode", label: translateUi(locale, "context_meter.field.estimate_mode"), value: String(safeContextMeter.estimate_mode || "-") },
      { key: "compact_recommendation", label: translateUi(locale, "context_meter.field.compact_recommendation"), value: String(safeContextMeter.compact_recommendation || "none") },
      { key: "output_limit", label: translateUi(locale, "context_meter.field.output_limit"), value: formatTokenCount(maxOutputTokens) },
      { key: "token_usage", label: translateUi(locale, "context_meter.field.token_usage"), value: formatRuntimeTokenUsage(locale, tokenUsage) },
      ...(safeContextMeter.context_window
        ? [{ key: "context_window", label: translateUi(locale, "context_meter.field.context_window"), value: formatTokenCount(safeContextMeter.context_window) }]
        : []),
      ...(safeContextMeter.model_max_context_window > safeContextMeter.context_window
        ? [{ key: "model_max_context_window", label: translateUi(locale, "context_meter.field.model_max_context_window"), value: formatTokenCount(safeContextMeter.model_max_context_window) }]
        : []),
      ...(safeContextMeter.auto_compact_token_limit
        ? [{ key: "auto_compact_limit", label: translateUi(locale, "context_meter.field.auto_compact_limit"), value: formatTokenCount(safeContextMeter.auto_compact_token_limit) }]
        : []),
      ...(safeContextMeter.danger_compact_token_limit
        ? [{ key: "effective_context_limit", label: translateUi(locale, "context_meter.field.effective_context_limit"), value: formatTokenCount(safeContextMeter.danger_compact_token_limit) }]
        : []),
    ],
    safeguards: [
      { key: "long_task", label: translateUi(locale, "context_meter.field.guard_long_task"), value: formatRuntimeToggle(locale, Boolean(safeguards.long_task_guard)) },
      { key: "progress_signal", label: translateUi(locale, "context_meter.field.guard_progress_signal"), value: formatRuntimeToggle(locale, Boolean(safeguards.progress_signal_guard)) },
      { key: "same_action", label: translateUi(locale, "context_meter.field.guard_same_action"), value: formatRuntimeToggle(locale, Boolean(safeguards.same_action_repeat_guard)) },
      { key: "replan", label: translateUi(locale, "context_meter.field.guard_replan"), value: formatRuntimeToggle(locale, Boolean(safeguards.automatic_replan)) },
      { key: "tool_output", label: translateUi(locale, "context_meter.field.guard_tool_output"), value: formatRuntimeToggle(locale, Boolean(safeguards.tool_output_truncation)) },
      { key: "wall_clock", label: translateUi(locale, "context_meter.field.guard_wall_clock"), value: formatWallClockLimit(safeguards.max_turn_seconds) },
      { key: "user_stop", label: translateUi(locale, "context_meter.field.guard_user_stop"), value: formatRuntimeToggle(locale, Boolean(safeguards.supports_user_cancel)) },
      { key: "compaction", label: translateUi(locale, "context_meter.field.guard_compaction"), value: formatRuntimeToggle(locale, Boolean(safeguards.context_compaction)) },
    ],
    diagnostics: [
      ...(providerDiagnostics.runtime_status_total_ms != null
        ? [{ key: "runtime_status_total_ms", label: translateUi(locale, "context_meter.field.runtime_status_total"), value: formatPhaseTimingMs(providerDiagnostics.runtime_status_total_ms) }]
        : []),
      ...(providerDiagnostics.runtime_status_runtime_meta_ms != null
        ? [{ key: "runtime_status_runtime_meta_ms", label: translateUi(locale, "context_meter.field.runtime_status_runtime_meta"), value: formatPhaseTimingMs(providerDiagnostics.runtime_status_runtime_meta_ms) }]
        : []),
      ...(providerDiagnostics.runtime_status_provider_options_ms != null
        ? [{ key: "runtime_status_provider_options_ms", label: translateUi(locale, "context_meter.field.runtime_status_provider_options"), value: formatPhaseTimingMs(providerDiagnostics.runtime_status_provider_options_ms) }]
        : []),
      ...(providerDiagnostics.runtime_status_auth_summary_ms != null
        ? [{ key: "runtime_status_auth_summary_ms", label: translateUi(locale, "context_meter.field.runtime_status_auth_summary"), value: formatPhaseTimingMs(providerDiagnostics.runtime_status_auth_summary_ms) }]
        : []),
    ],
  };
}

function nextRuntimeStatusPollIntervalMs({ sending, activeRunId, drawerView, contextMeterOpen }) {
  if (sending || String(activeRunId || "").trim()) return RUNTIME_STATUS_ACTIVE_INTERVAL_MS;
  if (contextMeterOpen) return RUNTIME_STATUS_IDLE_INTERVAL_MS;
  return 0;
}

function mergeRunSnapshot(prev, snapshot) {
  const next = snapshot && typeof snapshot === "object" ? snapshot : {};
  return {
    ...prev,
    ...next,
    plan: Array.isArray(next.plan) ? next.plan : (Array.isArray(prev.plan) ? prev.plan : []),
    pending_user_input:
      next.pending_user_input && typeof next.pending_user_input === "object"
        ? next.pending_user_input
        : (prev.pending_user_input || {}),
    pending_approval:
      next.pending_approval && typeof next.pending_approval === "object"
        ? next.pending_approval
        : (prev.pending_approval || {}),
  };
}

function isCommandExecutionApproval(value) {
  return Boolean(
    value
    && typeof value === "object"
    && String(value.type || "") === "command_execution"
    && String(value.command || "").trim(),
  );
}

function clearCommandExecutionApprovalState(value) {
  const state = value && typeof value === "object" ? value : {};
  const next = { ...state };
  if (isCommandExecutionApproval(next.pending_approval)) {
    next.pending_approval = {};
  }
  const pendingInput = next.pending_user_input && typeof next.pending_user_input === "object"
    ? next.pending_user_input
    : {};
  if (isCommandExecutionApproval(pendingInput.approval_request)) {
    next.pending_user_input = {};
  }
  return next;
}

function clearCommandExecutionApprovalResponse(value) {
  if (!value || typeof value !== "object") return value;
  const next = clearCommandExecutionApprovalState(value);
  const inspector = next.inspector && typeof next.inspector === "object" ? next.inspector : null;
  const runState = inspector && inspector.run_state && typeof inspector.run_state === "object"
    ? inspector.run_state
    : null;
  if (!runState) return next;
  return {
    ...next,
    inspector: {
      ...inspector,
      run_state: clearCommandExecutionApprovalState(runState),
    },
  };
}

function toolTimelineSummary(item, locale) {
  if (!item || typeof item !== "object") return translateUi(locale, "labels.no_summary");
  const status = String(item.status || "").trim().toLowerCase();
  if (status === "failed" || status === "error") {
    const failureSummary = toolFailureSummary(item, locale);
    if (failureSummary) return failureSummary;
  }
  const base = String(item.summary || item.output_preview || translateUi(locale, "labels.no_summary")).trim();
  const diagnostics = item.diagnostics && typeof item.diagnostics === "object" ? item.diagnostics : {};
  const visibleText = String(diagnostics.visible_text_preview || "").trim().replaceAll("\n", " / ");
  const validation = item.schema_validation && typeof item.schema_validation === "object" ? item.schema_validation : {};
  const validationStatus = String(validation.status || "").trim();
  const validationSuffix = validationStatus && validationStatus !== "valid"
    ? ` · ${formatValidationStatus(locale, validationStatus)}`
    : "";
  if (visibleText) return `${base} · ${visibleText}${validationSuffix}`;
  return `${base || translateUi(locale, "labels.no_summary")}${validationSuffix}`;
}

function compactFailureText(value, limit = 240) {
  const text = String(value == null ? "" : value).trim();
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function toolFailureSummary(item, locale) {
  const result = item.result_preview && typeof item.result_preview === "object" ? item.result_preview : {};
  const validationResult = item.validation_result && typeof item.validation_result === "object" ? item.validation_result : {};
  const returncode = result.returncode ?? item.returncode ?? null;
  const errorText = compactFailureText(
    result.error
    || item.error
    || item.preview_error
    || validationResult.message
    || item.summary,
  );
  const stderrText = compactFailureText(result.stderr || item.stderr || "");
  const cwdText = compactFailureText(result.cwd || item.cwd || "");
  const commandText = compactFailureText(result.command || item.command || "");
  const lines = [];
  if (errorText) lines.push(`${translateUi(locale, "tool.failure.error")}: ${errorText}`);
  if (stderrText && stderrText !== errorText) lines.push(`${translateUi(locale, "tool.failure.stderr")}: ${stderrText}`);
  if (returncode != null && String(returncode).trim() !== "") {
    lines.push(`${translateUi(locale, "tool.failure.returncode")}: ${returncode}`);
  }
  if (cwdText) lines.push(`${translateUi(locale, "tool.failure.cwd")}: ${cwdText}`);
  if (commandText) lines.push(`${translateUi(locale, "tool.failure.command")}: ${commandText}`);
  return lines.slice(0, 5).join("\n");
}

function isRuntimeFailureToolItem(item) {
  const source = item && typeof item === "object" ? item : {};
  const status = String(source.status || "").trim().toLowerCase();
  const type = String(source.type || "").trim().toLowerCase();
  const validation = source.validation_result && typeof source.validation_result === "object"
    ? source.validation_result
    : {};
  if (["failed", "error", "rejected"].includes(status)) return true;
  if (["tool_failed", "tool_rejected"].includes(type)) return true;
  return validation.allowed === false && String(validation.code || "").trim().toLowerCase() !== "tool_skipped";
}

function buildRuntimeOutcomeSummary(activity, locale) {
  const item = normalizeMessageActivity(activity || {});
  const terminal = item.runtime_outcome && typeof item.runtime_outcome === "object"
    ? item.runtime_outcome
    : {};
  const runtimeError = item.runtime_error && typeof item.runtime_error === "object"
    ? item.runtime_error
    : {};
  const failures = normalizeActivityToolItems(item.tool_items)
    .filter(isRuntimeFailureToolItem)
    .slice(-4)
    .reverse()
    .map((toolItem) => ({
      id: String(toolItem.id || toolItem.tool_call_id || toolItem.name || "tool-failure"),
      tool: String(toolItem.tool || toolItem.name || "tool").trim() || "tool",
      errorKind: String(
        toolItem.error_kind
        || ((toolItem.diagnostics || {}).error_kind)
        || ((toolItem.validation_result || {}).code)
        || "",
      ).trim(),
      retryCount: Math.max(0, Number(toolItem.retry_count || 0) || 0),
      recoveryResult: String(toolItem.recovery_result || "").trim(),
      summary: toolFailureSummary(toolItem, locale)
        || compactFailureText(toolItem.summary || toolItem.preview_error || ""),
    }));
  const durationMs = Math.max(
    0,
    Number(item.final_elapsed_ms || 0) || 0,
    Number(item.run_duration_ms || 0) || 0,
  );
  return {
    loaded: Boolean(item.activity_loaded),
    status: normalizeProgressStatus(terminal.status || item.status || "completed"),
    duration: durationMs ? formatElapsedSeconds(Math.max(0, Math.round(durationMs / 1000)), locale) : "",
    toolCount: Math.max(0, Number(item.tool_count || 0) || 0),
    failures,
    errorKind: String(terminal.error_kind || runtimeError.kind || "").trim(),
    errorMessage: String(terminal.error_message || runtimeError.message || "").trim(),
    stopReason: String(terminal.stop_reason || "").trim(),
  };
}

function latestAssistantMessage(messages, options = {}) {
  const list = Array.isArray(messages) ? messages : [];
  const preferPending = options.preferPending !== false;
  const reversed = list.slice().reverse();
  if (preferPending) {
    const pending = reversed.find((item) => item && item.role === "assistant" && item.pending);
    if (pending) return pending;
  }
  return reversed.find((item) => item && item.role === "assistant") || null;
}

function messagesForLiveGuidanceDisplay(messages, liveAssistantMessageId) {
  const list = Array.isArray(messages) ? [...messages] : [];
  const liveId = String(liveAssistantMessageId || "").trim();
  if (!liveId) return list;
  const liveIndex = list.findIndex((item) => (
    item
    && item.role === "assistant"
    && String(item.id || "").trim() === liveId
  ));
  if (liveIndex < 0) return list;

  let displayAfterIndex = liveIndex;
  for (let index = liveIndex + 1; index < list.length; index += 1) {
    const item = list[index] && typeof list[index] === "object" ? list[index] : {};
    const steerStatus = String(((item.activity || {}).status) || "").trim();
    if (
      item.role === "user"
      && ["steer_queued", "steer_accepted", "steer_rejected"].includes(steerStatus)
    ) {
      displayAfterIndex = index;
      continue;
    }
    break;
  }
  if (displayAfterIndex === liveIndex) return list;

  const [liveAssistant] = list.splice(liveIndex, 1);
  list.splice(displayAfterIndex, 0, liveAssistant);
  return list;
}

function currentChecklistStepLabel(plan, checkpoint = {}) {
  const entries = normalizePlanChecklist(plan);
  const inProgress = entries.find((item) => normalizeProgressStatus(item.status) === "running");
  if (inProgress && inProgress.step) return inProgress.step;
  const pending = entries.find((item) => normalizeProgressStatus(item.status) === "pending");
  if (pending && pending.step) return pending.step;
  return String(
    checkpoint.next_action
    || checkpoint.current_step_id
    || checkpoint.goal
    || "",
  ).trim();
}

function executionProgressCommandFromSource(source) {
  const item = source && typeof source === "object" ? source : {};
  const rawToolCall = item.raw_tool_call && typeof item.raw_tool_call === "object" ? item.raw_tool_call : {};
  const rawCallArguments = rawToolCall.arguments && typeof rawToolCall.arguments === "object" ? rawToolCall.arguments : {};
  const rawArguments = item.raw_arguments && typeof item.raw_arguments === "object" ? item.raw_arguments : {};
  const normalizedArguments = item.normalized_arguments && typeof item.normalized_arguments === "object" ? item.normalized_arguments : {};
  const resultPreview = item.result_preview && typeof item.result_preview === "object" ? item.result_preview : {};
  const candidates = [
    resultPreview.command,
    item.command,
    normalizedArguments.command,
    normalizedArguments.cmd,
    rawArguments.command,
    rawArguments.cmd,
    rawCallArguments.command,
    rawCallArguments.cmd,
  ];
  for (const candidate of candidates) {
    const text = shortenActivityTarget(candidate, 160);
    if (text) return text;
  }
  return "";
}

function formatRunProgressStatus(locale, status) {
  const normalized = String(status || "").trim();
  if (!normalized) return "-";
  return translateUiOrFallback(locale, `run.progress.status.${normalized}`, normalized);
}

function buildRunExecutionProgress({
  messages,
  plan,
  checkpoint = {},
  logs,
  sending = false,
  activeRunId = "",
  activeRunThreadId = "",
  sessionId = "",
  locale = "zh-CN",
  liveToolTimeline = [],
  liveHeartbeat = {},
  lastProgressAt = 0,
  runStartedAt = 0,
  hasRunningActivity = false,
  liveTurnState = {},
  nowMs = Date.now(),
}) {
  const assistantMessage = latestAssistantMessage(messages, { preferPending: true });
  const activity = normalizeMessageActivity((assistantMessage && assistantMessage.activity) || {});
  const heartbeat = normalizeLiveHeartbeat(liveHeartbeat);
  const liveItems = normalizeLiveRunItems(activity.live_items);
  const traces = Array.isArray(activity.trace_events) ? activity.trace_events : [];
  const modelStarted = hasTraceType(traces, ["llm.started", "answer.started", "answer.delta"]) || String(heartbeat.source || "") === "model";
  const modelName = String(heartbeat.model || liveModelNameFromActivity(activity) || "").trim();
  const liveToolEntry = Array.isArray(liveToolTimeline) && liveToolTimeline.length
    ? ((liveToolTimeline[0] && typeof liveToolTimeline[0] === "object") ? liveToolTimeline[0] : {})
    : {};
  const reversedLiveItems = liveItems.slice().reverse();
  const priorityStatuses = new Set(["validating", "running", "waiting_tool", "waiting_model", "failed", "blocked", "completed"]);
  const currentItem = reversedLiveItems.find((item) => priorityStatuses.has(normalizeProgressStatus(item.status))) || reversedLiveItems[0] || null;
  const lastTrace = traces.length ? traces[traces.length - 1] : null;
  const lastTracePayload = lastTrace && lastTrace.payload && typeof lastTrace.payload === "object" ? lastTrace.payload : {};
  const currentSource = currentItem && currentItem.raw && currentItem.raw.payload && typeof currentItem.raw.payload === "object"
    ? currentItem.raw.payload
    : ((currentItem && currentItem.raw && typeof currentItem.raw === "object") ? currentItem.raw : {});
  const toolName = String(
    heartbeat.tool
    || (currentItem && currentItem.tool)
    || liveToolEntry.tool
    || liveToolEntry.name
    || liveToolEntry.type
    || lastTracePayload.tool_name
    || lastTracePayload.tool
    || lastTracePayload.name
    || ((lastTracePayload.raw_tool_call || {}).name)
    || "",
  ).trim();
  const command = (
    heartbeat.command
    || executionProgressCommandFromSource(currentSource)
    || executionProgressCommandFromSource(liveToolEntry)
    || executionProgressCommandFromSource(lastTracePayload)
  );
  let status = heartbeat.status
    ? normalizeProgressStatus(heartbeat.status)
    : (currentItem ? normalizeProgressStatus(currentItem.status) : "");
  let currentAction = String(
    heartbeat.action
    || command
    || ((currentItem && (currentItem.label || currentItem.detail)) || "")
    || String(liveToolEntry.summary || liveToolEntry.output_preview || "").trim()
    || ((lastTrace && (lastTrace.title || lastTrace.detail)) || "")
    || "",
  ).trim();
  let recentEvent = String(
    heartbeat.recentEvent
    || ((Array.isArray(logs) && logs[0] && logs[0].text) || "")
    || ((lastTrace && (lastTrace.title || lastTrace.detail)) || "")
    || ((currentItem && (currentItem.label || currentItem.detail)) || "")
    || "",
  ).trim();
  const isCurrentThreadActiveRun = isCurrentThreadLiveRun({
    sessionId,
    activeRunThreadId,
    sending,
    activeRunId,
    activeRunStartedAt: runStartedAt,
    hasRunningActivity,
    liveTurnState,
  });
  const lastProgressAtMs = normalizeActivityTimestamp(
    heartbeat.updatedAt
    || lastProgressAt
    || ((currentItem && (currentItem.completed_at || currentItem.started_at)) || 0)
    || ((lastTrace && lastTrace.timestamp) || 0)
    || (activity.turn_started_at || activity.started_at || 0),
  );
  if (!status) {
    const traceType = String((lastTrace && lastTrace.type) || "").trim();
    if (traceType === "observation.returned" || traceType.startsWith("llm.") || traceType === "answer.started" || traceType === "answer.delta") {
      status = "waiting_model";
    } else if (traceType.startsWith("tool.") || traceType.startsWith("action.") || traceType.startsWith("tool_drain.")) {
      status = "waiting_tool";
    } else if (isCurrentThreadActiveRun) {
      status = "background_running";
    } else {
      status = normalizeProgressStatus(activity.status || "");
    }
  }
  if (status === "waiting_model" && !modelStarted && !toolName && String(heartbeat.source || "") !== "tool") {
    status = "background_running";
  }
  const progressIsStale = Boolean(
    isCurrentThreadActiveRun
    && lastProgressAtMs
    && (nowMs - lastProgressAtMs) >= LIVE_PROGRESS_STALE_AFTER_MS,
  );
  if (progressIsStale) {
    currentAction = "";
    recentEvent = "";
    const fallbackSource = String(heartbeat.source || "").trim();
    const traceType = String((lastTrace && lastTrace.type) || "").trim();
    if (fallbackSource === "model" || traceType === "observation.returned" || traceType.startsWith("llm.") || traceType === "answer.started" || traceType === "answer.delta") {
      status = "waiting_model";
    } else if (fallbackSource === "tool" || fallbackSource === "validator" || toolName || traceType.startsWith("tool.") || traceType.startsWith("action.") || traceType.startsWith("tool_drain.")) {
      status = "waiting_tool";
    } else {
      status = "background_running";
    }
  }
  if (status === "waiting_model" && !modelStarted && !toolName && String(heartbeat.source || "") !== "tool") {
    status = "background_running";
  }
  if (status === "waiting_model" && modelStarted) {
    currentAction = translateUi(locale, "activity.status.waiting_model");
    recentEvent = modelName
      ? translateUi(locale, "run.live_agent.model_detail", { detail: modelName })
      : translateUi(locale, "run.live_agent.model");
  } else if (status === "background_running" && !modelStarted) {
    currentAction = translateUi(locale, "activity.status.preparing_request");
    recentEvent = translateUi(locale, "run.live_agent.preparing");
  }
  if (!currentAction) {
    if (status === "waiting_model") {
      currentAction = translateUi(locale, "run.progress.waiting_model");
    } else if (status === "waiting_tool" || status === "validating") {
      currentAction = translateUi(locale, "run.progress.waiting_tool");
    } else if (status === "background_running") {
      currentAction = translateUi(locale, "run.progress.background_running");
    } else if (status === "completed") {
      currentAction = String(activity.final_answer || activity.summary || translateUi(locale, "activity.live.answer_done")).trim();
    }
  }
  if (!recentEvent) {
    if (status === "waiting_model") {
      recentEvent = translateUi(locale, "run.progress.recent_event_waiting_model");
    } else if (status === "waiting_tool" || status === "validating") {
      recentEvent = translateUi(locale, "run.progress.recent_event_waiting_tool");
    } else if (status === "background_running") {
      recentEvent = translateUi(locale, "run.progress.recent_event_background");
    } else if (status === "completed") {
      recentEvent = translateUi(locale, "run.progress.recent_event_completed");
    }
  }
  const elapsed = formatElapsedFromStartedAt(
    runStartedAt || activity.turn_started_at || activity.started_at || 0,
    nowMs,
    locale,
  );
  const lastProgressAgeSeconds = lastProgressAtMs
    ? Math.max(0, Math.floor((nowMs - lastProgressAtMs) / 1000))
    : null;
  const transportAnchor = Math.max(
    normalizeActivityTimestamp(heartbeat.connectionAt || 0),
    lastProgressAtMs || 0,
  );
  const connectionFresh = Boolean(
    isCurrentThreadActiveRun
    && transportAnchor
    && (nowMs - transportAnchor) < 25_000
  );
  const connectionState = isCurrentThreadActiveRun
    ? (connectionFresh ? "connected" : "stale")
    : "idle";
  return {
    currentStep: currentChecklistStepLabel(plan, checkpoint),
    currentTool: toolName,
    currentAction,
    status,
    statusLabel: formatRunProgressStatus(locale, status),
    command,
    recentEvent,
    elapsed,
    lastProgressAgo: lastProgressAgeSeconds == null
      ? "-"
      : translateUiOrFallback(locale, "run.progress.seconds_ago", `${lastProgressAgeSeconds}s ago`, { seconds: lastProgressAgeSeconds }),
    connectionState,
    connectionLabel: translateUiOrFallback(locale, `run.connection.${connectionState}`, connectionState),
  };
}

function activityStatusFromTraceType(type, fallback = "thinking", eventStatus = "") {
  const normalized = String(type || "").trim();
  if (!normalized) return fallback;
  if (normalized.startsWith("activity.")) return "thinking";
  if (normalized === "llm.started") return "waiting_model";
  if (
    normalized === "tool.started" ||
    normalized === "tool.finished" ||
    normalized === "tool.call_detected" ||
    normalized === "action.detected" ||
    normalized === "action.validating" ||
    normalized === "action.allowed" ||
    normalized === "observation.returned"
  ) return "tooling";
  if (normalized === "answer.started" || normalized === "answer.finished" || normalized === "answer.done" || normalized === "answer.delta") return "answering";
  if (normalized === "approval.required" || normalized === "blocked" || normalized === "action.blocked" || normalized === "loop.safeguard") return "blocked";
  if (normalized === "run.finished") {
    const finishedStatus = normalizeProgressStatus(eventStatus);
    return ["completed", "failed", "blocked", "cancelled"].includes(finishedStatus)
      ? finishedStatus
      : "completed";
  }
  if (normalized === "tool.failed") return "tooling";
  if (normalized === "llm.failed") return "background_running";
  if (normalized === "run.failed") return "failed";
  if (normalized === "cancelled") return "cancelled";
  return fallback;
}

function mergeActivityState(previous, patch = {}) {
  const prev = normalizeMessageActivity(previous || {});
  const nextPatch = patch && typeof patch === "object" ? patch : {};
  const nextRuntimeError = normalizeRuntimeErrorPayload(nextPatch.runtime_error);
  const nextRuntimeErrorDefined = Object.values(nextRuntimeError).some((value) => value !== "" && value !== null && value !== 0);
  const nextTraceEvents = Array.isArray(nextPatch.trace_events)
    ? nextPatch.trace_events.map(normalizeTraceEvent)
    : prev.trace_events;
  const nextPlan = Array.isArray(nextPatch.plan)
    ? normalizePlanChecklist(nextPatch.plan)
    : prev.plan;
  const replaceExecutionDetails = nextPatch.replace_execution_details === true;
  const nextToolItems = Object.prototype.hasOwnProperty.call(nextPatch, "tool_items")
    ? (
        replaceExecutionDetails
          ? reconcileAuthoritativeActivityToolItems(prev.tool_items, nextPatch.tool_items)
          : mergeActivityToolItems(prev.tool_items, nextPatch.tool_items)
      )
    : prev.tool_items;
  const nextLiveItems = Object.prototype.hasOwnProperty.call(nextPatch, "live_items")
    ? (
        replaceExecutionDetails
          ? normalizeLiveRunItems(nextPatch.live_items)
          : mergeLiveRunItems(prev.live_items, nextPatch.live_items)
      )
    : prev.live_items;
  const nextLlmExchanges = Object.prototype.hasOwnProperty.call(nextPatch, "llm_exchanges")
    ? (Array.isArray(nextPatch.llm_exchanges) ? nextPatch.llm_exchanges : [])
    : prev.llm_exchanges;
  const nextStatus = String(nextPatch.status || prev.status || "");
  const terminalFinishedAt = isActivityTerminalStatus(nextStatus) ? Date.now() : 0;
  const nextStartedAtCandidate = normalizeActivityTimestamp(
    nextPatch.started_at || (nextTraceEvents[0] && nextTraceEvents[0].timestamp) || 0,
  );
  const nextStartedAt = prev.started_at || nextStartedAtCandidate || 0;
  const nextTurnStartedAtCandidate = normalizeActivityTimestamp(nextPatch.turn_started_at || nextPatch.turnStartedAt || 0);
  const nextTurnStartedAt = prev.turn_started_at || nextTurnStartedAtCandidate || nextStartedAt || 0;
  const nextFinishedAt = normalizeActivityTimestamp(
    nextPatch.finished_at
    || prev.finished_at
    || terminalFinishedAt
    || 0,
  );
  const nextRunDurationMs = Math.max(0, Number(
    nextPatch.run_duration_ms != null ? nextPatch.run_duration_ms : prev.run_duration_ms,
  ) || 0);
  const nextModelDraft = Object.prototype.hasOwnProperty.call(nextPatch, "model_draft")
    ? String(nextPatch.model_draft || "")
    : String(prev.model_draft || "");
  const nextFinalAnswer = Object.prototype.hasOwnProperty.call(nextPatch, "final_answer")
    ? String(nextPatch.final_answer || "")
    : String(prev.final_answer || "");
  const nextFinalElapsedMs = isActivityTerminalStatus(nextStatus)
    ? Math.max(
      0,
      Number(prev.final_elapsed_ms || 0) || 0,
      Number(nextPatch.final_elapsed_ms || 0) || 0,
      nextRunDurationMs,
      nextTurnStartedAt && nextFinishedAt ? Math.max(0, nextFinishedAt - nextTurnStartedAt) : 0,
    )
    : 0;
  return {
    ...prev,
    ...nextPatch,
    run_id: String(nextPatch.run_id || prev.run_id || ""),
    status: nextStatus,
    started_at: nextStartedAt,
    turn_started_at: nextTurnStartedAt,
    finished_at: nextFinishedAt,
    run_duration_ms: isActivityTerminalStatus(nextStatus) ? Math.max(nextRunDurationMs, nextFinalElapsedMs) : nextRunDurationMs,
    final_elapsed_ms: nextFinalElapsedMs,
    summary: String(nextPatch.summary || prev.summary || ""),
    activity_loaded: Boolean(nextPatch.activity_loaded || nextPatch.activityLoaded || prev.activity_loaded || nextPatch.full_loaded || nextPatch.fullLoaded),
    debug_loaded: Boolean(nextPatch.debug_loaded || nextPatch.debugLoaded || prev.debug_loaded || nextPatch.full_loaded || nextPatch.fullLoaded),
    full_loaded: Boolean(nextPatch.full_loaded || nextPatch.fullLoaded || prev.full_loaded),
    activity_summary: String(nextPatch.activity_summary || prev.activity_summary || ""),
    live_model_started: Boolean(nextPatch.live_model_started || nextPatch.liveModelStarted || prev.live_model_started),
    live_model: String(nextPatch.live_model || nextPatch.liveModel || prev.live_model || ""),
    model_draft: nextModelDraft,
    final_answer: nextFinalAnswer,
    runtime_error: nextRuntimeErrorDefined ? nextRuntimeError : prev.runtime_error,
    runtime_inspector:
      nextPatch.runtime_inspector && typeof nextPatch.runtime_inspector === "object"
        ? nextPatch.runtime_inspector
        : prev.runtime_inspector,
    tool_boundary_clean:
      typeof nextPatch.tool_boundary_clean === "boolean"
        ? nextPatch.tool_boundary_clean
        : prev.tool_boundary_clean,
    llm_exchanges: nextLlmExchanges,
    plan: nextPlan,
    plan_explanation: String(nextPatch.plan_explanation || prev.plan_explanation || ""),
    tool_items: nextToolItems,
    live_items: nextLiveItems,
    trace_events: nextTraceEvents,
  };
}

function buildLiveDisplayActivity(activity, options = {}) {
  const item = normalizeMessageActivity(activity || {});
  const isLiveRun = isCurrentThreadLiveRun({
    sessionId: options.sessionId,
    activeRunThreadId: options.activeRunThreadId,
    sending: options.sending,
    activeRunId: options.activeRunId,
    activeRunStartedAt: options.activeRunStartedAt,
    hasRunningActivity: options.hasRunningActivity,
    liveTurnState: options.liveTurnState,
  });
  if (!isLiveRun) return item;
  const heartbeat = normalizeLiveHeartbeat(options.liveHeartbeat || {});
  const heartbeatStatus = normalizeProgressStatus(heartbeat.status);
  const heartbeatSource = String(heartbeat.source || "").trim();
  const heartbeatCanOwnLiveStatus = ["validating", "running", "waiting_tool", "waiting_model", "background_running", "blocked", "failed"].includes(heartbeatStatus);
  const hasVisibleFinalAnswer = Boolean(String(item.final_answer || "").trim());
  const shouldSuppressTerminalDisplay = normalizeProgressStatus(item.status) === "completed" && !hasVisibleFinalAnswer;
  const filteredTraceEvents = item.trace_events.filter((trace) => {
    const traceType = String((trace && trace.type) || "").trim();
    return !["run.finished", "answer.done", "answer.finished"].includes(traceType);
  });
  return normalizeMessageActivity({
    ...item,
    status: shouldSuppressTerminalDisplay || heartbeatCanOwnLiveStatus
      ? (
        ["validating", "running", "waiting_tool", "waiting_model", "background_running", "blocked", "failed"].includes(heartbeatStatus)
          ? heartbeatStatus
          : "running"
      )
      : item.status,
    started_at: item.started_at || options.activeRunStartedAt || 0,
    turn_started_at: item.turn_started_at || options.activeRunStartedAt || item.started_at || 0,
    finished_at: shouldSuppressTerminalDisplay ? 0 : item.finished_at,
    final_elapsed_ms: shouldSuppressTerminalDisplay ? 0 : item.final_elapsed_ms,
    live_model_started: Boolean(item.live_model_started || (heartbeatStatus === "waiting_model" && heartbeatSource === "model")),
    live_model: String(item.live_model || heartbeat.model || "").trim(),
    trace_events: filteredTraceEvents,
  });
}

function appendActivityTrace(activity, trace, options = {}) {
  const current = normalizeMessageActivity(activity || {});
  const normalizedTrace = normalizeTraceEvent(trace);
  const payload = normalizedTrace.payload && typeof normalizedTrace.payload === "object"
    ? normalizedTrace.payload
    : {};
  const nextTraceEvents = [...current.trace_events, normalizedTrace];
  const nextLiveItem = liveRunItemFromTrace(normalizedTrace);
  const nextLiveItems = nextLiveItem
    ? mergeLiveRunItems(current.live_items, [nextLiveItem])
    : current.live_items;
  const nextStatus = String(
    options.status
    || current.status
    || activityStatusFromTraceType(normalizedTrace.type, "thinking", normalizedTrace.status),
  );
  const finishedAt = isActivityTerminalStatus(nextStatus)
    ? (normalizedTrace.timestamp || current.finished_at || Date.now())
    : current.finished_at;
  const startedAt = current.started_at || normalizedTrace.timestamp || Date.now();
  const turnStartedAt = current.turn_started_at || current.started_at || normalizedTrace.timestamp || Date.now();
  const finalElapsedMs = isActivityTerminalStatus(nextStatus)
    ? Math.max(
      0,
      Number(current.final_elapsed_ms || 0) || 0,
      Number(current.run_duration_ms || 0) || 0,
      finishedAt && turnStartedAt ? Math.max(0, finishedAt - turnStartedAt) : 0,
    )
    : 0;
  const payloadRuntimeError = normalizedTrace.type === "llm.failed"
    ? normalizeRuntimeErrorPayload(payload)
    : normalizeRuntimeErrorPayload(payload.runtime_error);
  const payloadRuntimeErrorDefined = Object.values(payloadRuntimeError).some((value) => value !== "" && value !== null && value !== 0);
  const traceModel = String(payload.effective_model || payload.model || "").trim();
  return {
    ...current,
    run_id: String(normalizedTrace.run_id || current.run_id || ""),
    status: nextStatus,
    started_at: startedAt,
    turn_started_at: turnStartedAt,
    finished_at: finishedAt,
    run_duration_ms: isActivityTerminalStatus(nextStatus)
      ? Math.max(
        Number(current.run_duration_ms || 0) || 0,
        finishedAt && turnStartedAt ? Math.max(0, finishedAt - turnStartedAt) : 0,
      )
      : current.run_duration_ms,
    final_elapsed_ms: finalElapsedMs,
    model_draft: String(payload.model_draft || current.model_draft || ""),
    final_answer: String(payload.final_answer || current.final_answer || ""),
    runtime_error: payloadRuntimeErrorDefined ? payloadRuntimeError : current.runtime_error,
    live_model_started: Boolean(current.live_model_started || normalizedTrace.type === "llm.started"),
    live_model: traceModel || current.live_model,
    tool_boundary_clean:
      typeof payload.tool_boundary_clean === "boolean"
        ? payload.tool_boundary_clean
        : current.tool_boundary_clean,
    llm_exchanges: current.llm_exchanges,
    live_items: nextLiveItems,
    trace_events: nextTraceEvents.slice(-64),
    activity_summary: String(current.activity_summary || ""),
  };
}

function formatActivityDuration(activity, nowMs = Date.now(), locale = "en") {
  const item = normalizeMessageActivity(activity || {});
  const turnStartedAt = item.turn_started_at || item.started_at;
  if (!turnStartedAt) return "";
  const frozenElapsedMs = isActivityTerminalStatus(item.status)
    ? Math.max(0, Number(item.final_elapsed_ms || 0) || 0)
    : 0;
  const durationMs = frozenElapsedMs || (
    item.finished_at
      ? Math.max(
        0,
        Number(item.run_duration_ms || 0) || 0,
        Math.max(0, item.finished_at - turnStartedAt),
      )
      : Math.max(0, nowMs - turnStartedAt)
  );
  return formatElapsedSeconds(Math.max(0, Math.round(durationMs / 1000)), locale);
}

function activityPillLabel(locale, activity, nowMs = Date.now()) {
  const item = normalizeMessageActivity(activity || {});
  const status = String(item.status || "");
  const duration = formatActivityDuration(item, nowMs, locale);
  if (status === "failed") return `${translateUi(locale, "activity.failed")}${duration ? ` ${duration}` : ""}`;
  if (status === "blocked") return translateUi(locale, "activity.blocked");
  if (status === "cancelled") return `${translateUi(locale, "activity.cancelled")}${duration ? ` ${duration}` : ""}`;
  if (status === "completed") return `${translateUi(locale, "activity.title")}${duration ? ` ${duration}` : ""}`;
  return `${translateUi(locale, "activity.running")}${duration ? ` ${duration}` : ""}`;
}

function activityToneClass(status) {
  const normalized = String(status || "").trim();
  if (normalized === "failed") return "failed";
  if (normalized === "blocked") return "blocked";
  if (normalized === "cancelled") return "cancelled";
  if (normalized === "completed") return "completed";
  return "running";
}

function resolveStateValue(current, nextValue) {
  return typeof nextValue === "function" ? nextValue(current) : nextValue;
}

function updateStateAtPath(state, path, nextValue) {
  if (!Array.isArray(path) || !path.length) return state;
  const [head, ...rest] = path;
  if (!rest.length) {
    return {
      ...state,
      [head]: resolveStateValue(state ? state[head] : undefined, nextValue),
    };
  }
  return {
    ...state,
    [head]: updateStateAtPath(
      (state && typeof state[head] === "object" && state[head] !== null) ? state[head] : {},
      rest,
      nextValue,
    ),
  };
}

function createInitialAppState() {
  return {
    bootstrap: {
      health: null,
      runtimeStatus: {},
    },
    projectIndex: {
      projects: [],
      currentProjectId: "",
    },
    threadIndex: {
      threads: [],
      currentThreadId: "",
      sessionRuntimeState: {},
      loading: false,
    },
    items: {
      messages: [],
      byId: {},
      order: [],
      activeAgentMessageId: "",
    },
    activeTurn: {
      sending: false,
      activeRunThreadId: "",
      startedAt: 0,
      liveHeartbeat: createEmptyLiveHeartbeat(),
      liveRunLogs: [],
      lastResponse: null,
      toolTimeline: [],
      liveTurnState: {},
      liveEvidence: {},
      liveToolTimeline: [],
      stageTimeline: [],
      pendingGuidance: [],
      activeRunId: "",
      stoppingRun: false,
    },
    panelCache: {
      tasks: { status: "idle", data: [] },
      tools: { status: "idle", data: [] },
      skills: { status: "idle", data: [] },
      specs: { status: "idle", data: [] },
    },
  };
}

function appStateReducer(state, action) {
  if (!action || typeof action !== "object") return state;
  if (action.type === "update") {
    return updateStateAtPath(state, action.path, action.value);
  }
  if (action.type === "items/reset") {
    return {
      ...state,
      items: {
        messages: [],
        byId: {},
        order: [],
        activeAgentMessageId: "",
      },
    };
  }
  if (action.type === "items/register") {
    const item = action.item && typeof action.item === "object" ? action.item : {};
    const itemId = String(item.id || "").trim();
    if (!itemId) return state;
    const previous = state.items.byId[itemId] && typeof state.items.byId[itemId] === "object" ? state.items.byId[itemId] : {};
    const nextOrder = state.items.order.includes(itemId) ? state.items.order : [...state.items.order, itemId];
    return {
      ...state,
      items: {
        ...state.items,
        byId: {
          ...state.items.byId,
          [itemId]: { ...previous, ...item },
        },
        order: nextOrder,
        activeAgentMessageId:
          item.type === "agentMessage"
            ? itemId
            : state.items.activeAgentMessageId,
      },
    };
  }
  if (action.type === "items/agentDelta") {
    const itemId = String(action.itemId || state.items.activeAgentMessageId || "").trim();
    if (!itemId) return state;
    const previous = state.items.byId[itemId] && typeof state.items.byId[itemId] === "object" ? state.items.byId[itemId] : {};
    return {
      ...state,
      items: {
        ...state.items,
        byId: {
          ...state.items.byId,
          [itemId]: {
            ...previous,
            id: itemId,
            type: "agentMessage",
            text: `${String(previous.text || "")}${String(action.delta || "")}`,
            status: String(action.status || previous.status || "inProgress"),
          },
        },
        order: state.items.order.includes(itemId) ? state.items.order : [...state.items.order, itemId],
        activeAgentMessageId: itemId,
      },
    };
  }
  return state;
}

function mergeHealthSlices(previousHealth, bootstrapData, runtimeData) {
  const prev = previousHealth && typeof previousHealth === "object" ? previousHealth : {};
  const bootstrap = bootstrapData && typeof bootstrapData === "object" ? bootstrapData : {};
  const runtime = runtimeData && typeof runtimeData === "object" ? runtimeData : {};
  return {
    ...prev,
    ...bootstrap,
    runtime_status: runtime.runtime_status || prev.runtime_status || {},
    ocr_status: runtime.ocr_status || prev.ocr_status || {},
    context_meter: runtime.context_meter || prev.context_meter || {},
    compaction_status: runtime.compaction_status || prev.compaction_status || {},
    default_project_id: bootstrap.default_project_id || prev.default_project_id || runtime.project_id || "",
  };
}

function normalizeThreadListPayload(data) {
  const source = Array.isArray(data && data.threads)
    ? data.threads
    : (Array.isArray(data && data.sessions) ? data.sessions : []);
  return source.map((item) => ({
    ...item,
    thread_id: String(item.thread_id || item.session_id || ""),
    session_id: String(item.session_id || item.thread_id || ""),
    status: String(item.status || "idle"),
    activity_at: String(item.activity_at || item.updated_at || item.created_at || ""),
    activity_revision: Math.max(0, Number(item.activity_revision || 0) || 0),
    activity_kind: String(item.activity_kind || ""),
  }));
}

function threadActivityTimestamp(item) {
  const row = item && typeof item === "object" ? item : {};
  const parsed = Date.parse(String(row.activity_at || row.updated_at || row.created_at || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function compareThreadFreshness(incoming, existing) {
  const next = incoming && typeof incoming === "object" ? incoming : {};
  const current = existing && typeof existing === "object" ? existing : {};
  const nextRevision = Math.max(0, Number(next.activity_revision || 0) || 0);
  const currentRevision = Math.max(0, Number(current.activity_revision || 0) || 0);
  if (nextRevision !== currentRevision) return nextRevision > currentRevision ? 1 : -1;
  const nextAt = threadActivityTimestamp(next);
  const currentAt = threadActivityTimestamp(current);
  if (nextAt !== currentAt) return nextAt > currentAt ? 1 : -1;
  return 0;
}

function mergeThreadRow(existing, incoming) {
  const current = existing && typeof existing === "object" ? existing : {};
  const next = incoming && typeof incoming === "object" ? incoming : {};
  if (Object.keys(current).length && compareThreadFreshness(next, current) < 0) {
    return current;
  }
  return { ...current, ...next };
}

function sortThreadRows(rows) {
  return (Array.isArray(rows) ? [...rows] : []).sort((left, right) => {
    const activityDelta = threadActivityTimestamp(right) - threadActivityTimestamp(left);
    if (activityDelta) return activityDelta;
    const leftId = String((left && (left.thread_id || left.session_id)) || "");
    const rightId = String((right && (right.thread_id || right.session_id)) || "");
    return rightId.localeCompare(leftId);
  });
}

function mergeAuthoritativeThreadRows(incomingRows, existingRows) {
  const existingById = new Map(
    (Array.isArray(existingRows) ? existingRows : []).map((item) => [threadListItemId(item), item]),
  );
  const merged = (Array.isArray(incomingRows) ? incomingRows : []).map((item) => {
    const key = threadListItemId(item);
    return mergeThreadRow(existingById.get(key), item);
  });
  return sortThreadRows(merged);
}

function normalizeThreadDetailPayload(data) {
  const payload = data && typeof data === "object" ? data : {};
  return {
    ...payload,
    thread_id: String(payload.thread_id || payload.session_id || ""),
    session_id: String(payload.session_id || payload.thread_id || ""),
    status: String(payload.status || "idle"),
    turns: Array.isArray(payload.turns) ? payload.turns : [],
  };
}

function threadListItemId(item) {
  const value = item && typeof item === "object" ? item : {};
  return String(value.session_id || value.thread_id || "").trim();
}

function starterPromptChips(locale, setDraft, handleSend) {
  return translateUiList(locale, "starter.prompts").map((text) =>
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

class AppErrorBoundary extends ReactRuntime.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    window.console.error(error);
  }

  render() {
    if (this.state.error) {
      const detail = String(
        (this.state.error && this.state.error.stack) ||
        this.state.error ||
        "Unknown frontend error",
      );
      return html`
        <div style=${{
          padding: "24px",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          color: "#1f2328",
        }}>
          <h2 style=${{ marginTop: 0 }}>Frontend render error</h2>
          <p>The UI crashed while rendering. You can reset the saved locale and reload.</p>
          <pre style=${{
            whiteSpace: "pre-wrap",
            background: "#f6f8fa",
            padding: "12px",
            borderRadius: "8px",
          }}>${detail}</pre>
          <button
            type="button"
            onClick=${() => {
              window.localStorage.removeItem(LOCALE_STORAGE_KEY);
              window.location.reload();
            }}
          >
            Reset locale and reload
          </button>
        </div>
      `;
    }
    return this.props.children;
  }
}

function App() {
  const [appState, dispatch] = useReducer(appStateReducer, undefined, createInitialAppState);
  const health = appState.bootstrap.health;
  const projects = appState.projectIndex.projects;
  const projectId = appState.projectIndex.currentProjectId;
  const sessions = appState.threadIndex.threads;
  const sessionId = appState.threadIndex.currentThreadId;
  const sessionRuntimeState = appState.threadIndex.sessionRuntimeState;
  const messages = appState.items.messages;
  const [draft, setDraft] = useState("");
  const sending = Boolean(appState.activeTurn.sending);
  const loadingSession = Boolean(appState.threadIndex.loading);
  const [drawerView, setDrawerView] = useState("");
  const [logs, setLogs] = useState([]);
  const liveRunLogs = appState.activeTurn.liveRunLogs;
  const lastResponse = appState.activeTurn.lastResponse;
  const [pendingUploads, setPendingUploads] = useState([]);
  const [chatSettings, setChatSettings] = useState(() => ({
    ...DEFAULT_SETTINGS,
    locale: readStoredLocale(I18nRuntime.SUPPORTED_LOCALES),
  }));
  const [themeColor, setThemeColor] = useState(readStoredThemeColor);
  const [modelTouched, setModelTouched] = useState(false);
  const [permissionProfileTouched, setPermissionProfileTouched] = useState(false);
  const [selectedPresetModel, setSelectedPresetModel] = useState("");
  const [uiError, setUiError] = useState(null);
  const toolTimeline = appState.activeTurn.toolTimeline;
  const liveTurnState = appState.activeTurn.liveTurnState;
  const liveEvidence = appState.activeTurn.liveEvidence;
  const liveToolTimeline = appState.activeTurn.liveToolTimeline;
  const stageTimeline = appState.activeTurn.stageTimeline;
  const activeRunId = appState.activeTurn.activeRunId;
  const activeRunThreadId = appState.activeTurn.activeRunThreadId;
  const activeRunStartedAt = normalizeActivityTimestamp(appState.activeTurn.startedAt || 0);
  const activeRunProgressAt = normalizeActivityTimestamp(appState.activeTurn.lastLiveProgressAt || 0);
  const activeLiveHeartbeat = normalizeLiveHeartbeat(appState.activeTurn.liveHeartbeat || {});
  const hasLiveTurnState = Boolean(Object.keys(liveTurnState || {}).length);
  const hasConnectionHeartbeat = Boolean(activeLiveHeartbeat.connectionAt || activeLiveHeartbeat.updatedAt);
  const stoppingRun = Boolean(appState.activeTurn.stoppingRun);
  const pendingGuidance = Array.isArray(appState.activeTurn.pendingGuidance)
    ? appState.activeTurn.pendingGuidance
    : [];
  const tasks = appState.panelCache.tasks.data;
  const tasksPanelStatus = String(appState.panelCache.tasks.status || "idle");
  const [loadingTaskId, setLoadingTaskId] = useState("");
  const workbenchTools = appState.panelCache.tools.data;
  const skills = appState.panelCache.skills.data;
  const skillsPanelStatus = String(appState.panelCache.skills.status || "idle");
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [skillEditor, setSkillEditor] = useState("");
  const specs = appState.panelCache.specs.data;
  const [selectedSpecName, setSelectedSpecName] = useState("soul.md");
  const [specEditor, setSpecEditor] = useState("");
  const [savingWorkbench, setSavingWorkbench] = useState(false);
  const [mobileThreadsOpen, setMobileThreadsOpen] = useState(false);
  const [selectedThreadIds, setSelectedThreadIds] = useState(() => new Set());
  const [threadSelectionAnchorId, setThreadSelectionAnchorId] = useState("");
  const [bulkDeletingThreads, setBulkDeletingThreads] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectPathDraft, setProjectPathDraft] = useState("");
  const [projectTitleDraft, setProjectTitleDraft] = useState("");
  const [projectFormError, setProjectFormError] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [evalDialogOpen, setEvalDialogOpen] = useState(false);
  const [evalCatalog, setEvalCatalog] = useState([]);
  const [evalRuns, setEvalRuns] = useState([]);
  const [evalSubmitting, setEvalSubmitting] = useState(false);
  const [evalError, setEvalError] = useState("");
  const [modelPresetRefreshing, setModelPresetRefreshing] = useState(false);
  const [modelPresetRefreshMessage, setModelPresetRefreshMessage] = useState("");
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [evalForm, setEvalForm] = useState({
    cases: "evals/agent_workflow_cases.json",
    name: "",
    repeat: 3,
    provider: "",
    model: "",
    output: "",
    live: false,
    keep_workspaces: false,
  });
  const [creatingThread, setCreatingThread] = useState(false);
  const [appUpdateState, setAppUpdateState] = useState({ status: "idle", result: null, error: null });
  const [bootState, setBootState] = useState({ active: true, phase: "workspace" });
  const [loadingEarlierTurns, setLoadingEarlierTurns] = useState(false);
  const [composerDragActive, setComposerDragActive] = useState(false);
  const [contextMeterOpen, setContextMeterOpen] = useState(false);
  const [slashCommandActiveIndex, setSlashCommandActiveIndex] = useState(0);
  const [projectMenu, setProjectMenu] = useState(null);
  const [threadMenu, setThreadMenu] = useState(null);
  const [renameDialog, setRenameDialog] = useState(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renameError, setRenameError] = useState("");
  const [renamingThread, setRenamingThread] = useState(false);
  const [activityOpenByMessageId, setActivityOpenByMessageId] = useState({});
  const [debugOpenByMessageId, setDebugOpenByMessageId] = useState({});
  const [activityClockMs, setActivityClockMs] = useState(Date.now());
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [threadRunIndicators, setThreadRunIndicators] = useState({});
  const fileInputRef = useRef(null);
  const chatListRef = useRef(null);
  const autoScrollEnabledRef = useRef(true);
  const chatScrollRafRef = useRef(0);
  const contextMeterRef = useRef(null);
  const contextMeterCloseTimerRef = useRef(null);
  const bootReadyRef = useRef(false);
  const permissionProfileInitializedRef = useRef(false);
  const composerDragDepthRef = useRef(0);
  const projectMenuRef = useRef(null);
  const projectLongPressRef = useRef({ timer: null, consumed: false });
  const threadMenuRef = useRef(null);
  const threadLongPressRef = useRef({ timer: null, consumed: false });
  const projectsRequestSeqRef = useRef(0);
  const projectsInFlightRef = useRef(null);
  const projectsLastFetchedAtRef = useRef(0);
  const sessionsRequestSeqRef = useRef(0);
  const activeThreadRequestSeqRef = useRef(0);
  const activeThreadAbortRef = useRef(null);
  const threadDetailCacheRef = useRef(new Map());
  const activeSendThreadIdsRef = useRef(new Set());
  const runDetailRequestRef = useRef(new Set());
  const composerInputRef = useRef(null);
  const activeSessionIdRef = useRef("");
  const pendingThreadCreationPromiseRef = useRef(null);
  const pendingTempThreadIdRef = useRef("");
  const tasksRequestSeqRef = useRef(0);
  const skillsRequestSeqRef = useRef(0);
  const runtimeStatusRequestSeqRef = useRef(0);
  const runtimeStatusAbortRef = useRef(null);
  const runtimeStatusInFlightRef = useRef({ key: "", promise: null });
  const runtimeStatusLastFetchedAtRef = useRef(0);
  const selectedSkillIdRef = useRef("");
  const skillDraftModeRef = useRef(false);
  const copiedMessageTimerRef = useRef(0);
  const setHealth = (value) => dispatch({ type: "update", path: ["bootstrap", "health"], value });
  const setProjects = (value) => dispatch({ type: "update", path: ["projectIndex", "projects"], value });
  const setProjectId = (value) => dispatch({ type: "update", path: ["projectIndex", "currentProjectId"], value });
  const setSessions = (value) => dispatch({ type: "update", path: ["threadIndex", "threads"], value });
  const setSessionId = (value) => {
    if (typeof value !== "function") activeSessionIdRef.current = String(value || "");
    dispatch({ type: "update", path: ["threadIndex", "currentThreadId"], value });
  };
  const setSessionRuntimeState = (value) => dispatch({ type: "update", path: ["threadIndex", "sessionRuntimeState"], value });
  const setMessages = (value) => dispatch({ type: "update", path: ["items", "messages"], value });
  const setSending = (value) => dispatch({ type: "update", path: ["activeTurn", "sending"], value });
  const setLoadingSession = (value) => dispatch({ type: "update", path: ["threadIndex", "loading"], value });
  const setLiveRunLogs = (value) => dispatch({ type: "update", path: ["activeTurn", "liveRunLogs"], value });
  const setPendingGuidance = (value) => dispatch({ type: "update", path: ["activeTurn", "pendingGuidance"], value });
  const hasRunningActivity = useMemo(
    () => messages.some((item) => {
      if (!item || item.role !== "assistant") return false;
      const activity = normalizeMessageActivity(item.activity || {});
      return Boolean(activity.turn_started_at || activity.started_at) && !isActivityTerminalStatus(activity.status);
    }),
    [messages],
  );
  const currentThreadBusy = isThreadSnapshotBusy(sessionId, {
    activeTurn: appState.activeTurn,
    messages,
  });
  const canQueueGuidance = Boolean(
    currentThreadBusy
    && activeRunId
    && String(activeRunThreadId || "").trim() === String(sessionId || "").trim()
  );
  const anyThreadBusy = (() => {
    if (currentThreadBusy) return true;
    for (const [threadId, snapshot] of threadDetailCacheRef.current.entries()) {
      if (String(threadId || "").trim() === String(sessionId || "").trim()) continue;
      if (isThreadSnapshotBusy(threadId, snapshot)) return true;
    }
    return false;
  })();
  const setLastResponse = (value) => dispatch({ type: "update", path: ["activeTurn", "lastResponse"], value });
  const setToolTimeline = (value) => dispatch({ type: "update", path: ["activeTurn", "toolTimeline"], value });
  const setLiveTurnState = (value) => dispatch({ type: "update", path: ["activeTurn", "liveTurnState"], value });
  const setLiveEvidence = (value) => dispatch({ type: "update", path: ["activeTurn", "liveEvidence"], value });
  const setLiveToolTimeline = (value) => dispatch({ type: "update", path: ["activeTurn", "liveToolTimeline"], value });
  const setStageTimeline = (value) => dispatch({ type: "update", path: ["activeTurn", "stageTimeline"], value });
  const setActiveRunId = (value) => dispatch({ type: "update", path: ["activeTurn", "activeRunId"], value });
  const setActiveRunThreadId = (value) => dispatch({ type: "update", path: ["activeTurn", "activeRunThreadId"], value });
  const setActiveRunStartedAt = (value) => dispatch({ type: "update", path: ["activeTurn", "startedAt"], value });
  const setLastLiveProgressAt = (value) => dispatch({ type: "update", path: ["activeTurn", "lastLiveProgressAt"], value });
  const setLiveHeartbeat = (value) => dispatch({ type: "update", path: ["activeTurn", "liveHeartbeat"], value });
  const setStoppingRun = (value) => dispatch({ type: "update", path: ["activeTurn", "stoppingRun"], value });
  const setTasks = (value) => dispatch({ type: "update", path: ["panelCache", "tasks", "data"], value });

  function markThreadRunIndicator(targetThreadId, status) {
    const key = String(targetThreadId || "").trim();
    const nextStatus = String(status || "").trim();
    if (!key) return;
    setThreadRunIndicators((prev) => {
      const current = prev && typeof prev === "object" ? prev : {};
      if (!nextStatus) {
        if (!Object.prototype.hasOwnProperty.call(current, key)) return current;
        const next = { ...current };
        delete next[key];
        return next;
      }
      return {
        ...current,
        [key]: {
          status: nextStatus,
          updatedAt: Date.now(),
        },
      };
    });
  }

  function clearThreadRunIndicator(targetThreadId) {
    const key = String(targetThreadId || "").trim();
    if (!key) return;
    setThreadRunIndicators((prev) => {
      const current = prev && typeof prev === "object" ? prev : {};
      const indicator = current[key];
      if (!indicator || indicator.status !== "completed_unread") return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function finishThreadRunIndicator(targetThreadId) {
    const key = String(targetThreadId || "").trim();
    if (!key) return;
    if (String(activeSessionIdRef.current || "").trim() === key) {
      markThreadRunIndicator(key, "");
      return;
    }
    markThreadRunIndicator(key, "completed_unread");
  }

  function threadRunIndicatorStatus(targetThreadId) {
    const key = String(targetThreadId || "").trim();
    if (!key) return "";
    const cachedSnapshot = threadDetailCacheRef.current.get(key) || {};
    const rowBusy = key === String(sessionId || "").trim()
      ? currentThreadBusy
      : isThreadSnapshotBusy(key, cachedSnapshot);
    if (rowBusy) return "running";
    if (key === String(activeSessionIdRef.current || "").trim()) return "";
    const indicator = threadRunIndicators[key];
    return indicator && indicator.status === "completed_unread" ? "completed_unread" : "";
  }
  const setWorkbenchTools = (value) => dispatch({ type: "update", path: ["panelCache", "tools", "data"], value });
  const setPanelStatus = (panel, value) => dispatch({ type: "update", path: ["panelCache", panel, "status"], value });
  const setSkills = (value) => dispatch({ type: "update", path: ["panelCache", "skills", "data"], value });
  const setSpecs = (value) => dispatch({ type: "update", path: ["panelCache", "specs", "data"], value });
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
  const supportedLocales = useMemo(
    () => dedupeStrings(Array.isArray(health && health.supported_locales) ? health.supported_locales : I18nRuntime.SUPPORTED_LOCALES),
    [health],
  );
  const defaultLocale = normalizeLocaleValue((health && health.default_locale) || "ja-JP", supportedLocales, "ja-JP");
  const uiLocale = normalizeLocaleValue(chatSettings.locale || "", supportedLocales, defaultLocale);
  const t = (key, replacements = null) => translateUi(uiLocale, key, replacements);
  const currentTabLabel = (tab) => translateUi(uiLocale, `tabs.${tab}`);
  const selectedEvalSuite = evalCatalog.find((item) => String(item.path || "") === String(evalForm.cases || "")) || evalCatalog[0] || null;
  const selectedEvalRequiresLive = !selectedEvalSuite || selectedEvalSuite.requires_live !== false;
  const selectedEvalSupportsRepeat = !selectedEvalSuite || selectedEvalSuite.supports_repeat !== false;
  const selectedEvalSupportsProvider = !selectedEvalSuite || selectedEvalSuite.supports_provider !== false;
  const selectedEvalSupportsModel = !selectedEvalSuite || selectedEvalSuite.supports_model !== false;
  const selectedEvalSupportsWorkspaces = !selectedEvalSuite || selectedEvalSuite.supports_workspaces !== false;
  const activeEvalRun = evalRuns.find((item) => ["queued", "running"].includes(String(item.status || ""))) || null;
  const evalButtonLabel = activeEvalRun
    ? t("eval.button_progress", {
        completed: Number(activeEvalRun.completed_attempts || 0),
        total: Number(activeEvalRun.total_attempts || 0),
      })
    : t("tabs.eval");

  function isNearChatBottom(element, threshold = CHAT_AUTO_SCROLL_THRESHOLD_PX) {
    const el = element || chatListRef.current;
    if (!el) return true;
    return (el.scrollHeight - el.scrollTop - el.clientHeight) < threshold;
  }

  function syncChatScrollState(element) {
    const el = element || chatListRef.current;
    if (!el) return true;
    const nearBottom = isNearChatBottom(el);
    autoScrollEnabledRef.current = nearBottom;
    setShowJumpToLatest((prev) => (prev === !nearBottom ? prev : !nearBottom));
    return nearBottom;
  }

  function scrollChatToBottom(options = {}) {
    const el = chatListRef.current;
    if (!el) return;
    const behavior = String(options.behavior || "auto");
    autoScrollEnabledRef.current = true;
    setShowJumpToLatest(false);
    if (chatScrollRafRef.current) {
      window.cancelAnimationFrame(chatScrollRafRef.current);
      chatScrollRafRef.current = 0;
    }
    chatScrollRafRef.current = window.requestAnimationFrame(() => {
      chatScrollRafRef.current = 0;
      if (!chatListRef.current) return;
      chatListRef.current.scrollTo({
        top: chatListRef.current.scrollHeight,
        behavior,
      });
      syncChatScrollState(chatListRef.current);
    });
  }

  function jumpToLatest() {
    scrollChatToBottom({ behavior: "smooth" });
  }

  useEffect(() => {
    if (!health) return;
    const currentLocale = normalizeLocaleValue(chatSettings.locale || "", supportedLocales, "");
    const preferredLocale = currentLocale || resolveInitialLocale({
      supportedLocales,
      serverLocale: (health && health.default_locale) || "",
      fallbackLocale: defaultLocale,
    });
    setChatSettings((prev) => (
      String(prev.locale || "").trim() === preferredLocale
        ? prev
        : { ...prev, locale: preferredLocale }
    ));
  }, [health, supportedLocales, defaultLocale, chatSettings.locale]);

  useEffect(() => {
    document.documentElement.lang = uiLocale;
    document.title = translateUi(uiLocale, "app.title");
  }, [uiLocale]);

  useEffect(() => {
    const option = applyThemeColor(themeColor);
    if (themeColor !== option.id) {
      setThemeColor(option.id);
      return;
    }
    window.localStorage.setItem(THEME_COLOR_STORAGE_KEY, option.id);
  }, [themeColor]);

  useEffect(() => () => {
    if (copiedMessageTimerRef.current) window.clearTimeout(copiedMessageTimerRef.current);
  }, []);

  useEffect(() => {
    if (!bootReadyRef.current) return;
    if (!projectId) {
      window.localStorage.removeItem(PROJECT_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId);
  }, [projectId]);

  useEffect(() => {
    activeSessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    setSlashCommandActiveIndex(0);
  }, [draft]);

  useEffect(() => {
    if (!bootReadyRef.current) return;
    if (!projectId) return;
    const storageKey = sessionStorageKeyForProject(projectId);
    if (!sessionId || isTempThreadId(sessionId)) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(storageKey, sessionId);
  }, [projectId, sessionId]);

  useEffect(() => {
    if (!projectMenu) return undefined;
    const closeMenu = () => setProjectMenu(null);
    const handlePointerDown = (event) => {
      const node = projectMenuRef.current;
      if (node && node.contains(event.target)) return;
      closeMenu();
    };
    const handleKeyDown = (event) => {
      if (event.key === "Escape") closeMenu();
    };
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [projectMenu]);

  useEffect(() => {
    if (!threadMenu) return undefined;
    const closeMenu = () => setThreadMenu(null);
    const handlePointerDown = (event) => {
      const node = threadMenuRef.current;
      if (node && node.contains(event.target)) return;
      closeMenu();
    };
    const handleKeyDown = (event) => {
      if (event.key === "Escape") closeMenu();
    };
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [threadMenu]);

  useEffect(() => {
    const availableIds = new Set((Array.isArray(sessions) ? sessions : []).map(
      (item) => String(item.session_id || item.thread_id || "").trim(),
    ).filter(Boolean));
    setSelectedThreadIds((prev) => {
      const current = prev instanceof Set ? prev : new Set();
      const next = new Set([...current].filter((id) => availableIds.has(String(id || "").trim())));
      if (next.size === current.size && [...next].every((id) => current.has(id))) return current;
      return next;
    });
    setThreadSelectionAnchorId((current) => (availableIds.has(String(current || "").trim()) ? current : ""));
  }, [sessions]);

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
    if (!health) return;
    const serverDefault = Number(health.default_max_output_tokens || 0);
    if (!Number.isFinite(serverDefault) || serverDefault <= 0) return;
    setChatSettings((prev) => (
      Number(prev.max_output_tokens || 0) === Number(DEFAULT_SETTINGS.max_output_tokens || 0)
        ? { ...prev, max_output_tokens: serverDefault }
        : prev
    ));
  }, [health]);

  useEffect(() => {
    if (!health) return;
    if (permissionProfileTouched || permissionProfileInitializedRef.current) return;
    const serverProfile = normalizePermissionProfile(health.default_permission_profile || "auto");
    if (!["default", "auto", "full_access"].includes(serverProfile)) return;
    permissionProfileInitializedRef.current = true;
    setChatSettings((prev) => (
      !prev.permission_profile || normalizePermissionProfile(prev.permission_profile) === DEFAULT_SETTINGS.permission_profile
        ? { ...prev, permission_profile: serverProfile }
        : prev
    ));
  }, [health, permissionProfileTouched]);

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
    const el = chatListRef.current;
    if (!el) return undefined;
    const handleScroll = () => {
      syncChatScrollState(el);
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => {
      el.removeEventListener("scroll", handleScroll);
    };
  }, []);

  useEffect(() => {
    if (!autoScrollEnabledRef.current) {
      syncChatScrollState(chatListRef.current);
      return undefined;
    }
    scrollChatToBottom();
    return undefined;
  }, [messages]);

  useEffect(() => {
    return () => {
      if (chatScrollRafRef.current) {
        window.cancelAnimationFrame(chatScrollRafRef.current);
        chatScrollRafRef.current = 0;
      }
      if (contextMeterCloseTimerRef.current) {
        window.clearTimeout(contextMeterCloseTimerRef.current);
        contextMeterCloseTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const activeRunBelongsToCurrentThread = Boolean(
      String(activeRunThreadId || "").trim()
      && String(activeRunThreadId || "").trim() === String(sessionId || "").trim()
    );
    const shouldTickActivityClock = Boolean(
      currentThreadBusy
      || (
        activeRunBelongsToCurrentThread
        && (
          Boolean(activeRunId)
          || Boolean(activeRunStartedAt)
          || hasConnectionHeartbeat
          || hasRunningActivity
        )
      )
    );
    if (!shouldTickActivityClock) {
      setActivityClockMs(Date.now());
      return undefined;
    }
    const syncActivityClock = () => setActivityClockMs(Date.now());
    const syncVisibleActivityClock = () => {
      if (document.visibilityState !== "hidden") syncActivityClock();
    };
    syncActivityClock();
    const intervalId = window.setInterval(() => setActivityClockMs(Date.now()), 1000);
    window.addEventListener("focus", syncActivityClock);
    document.addEventListener("visibilitychange", syncVisibleActivityClock);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", syncActivityClock);
      document.removeEventListener("visibilitychange", syncVisibleActivityClock);
    };
  }, [sessionId, activeRunId, activeRunThreadId, activeRunStartedAt, currentThreadBusy, hasRunningActivity, hasConnectionHeartbeat]);

  useEffect(() => {
    function handlePointerDown(event) {
      if (!contextMeterRef.current || contextMeterRef.current.contains(event.target)) return;
      setContextMeterOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  useEffect(() => {
    let disposed = false;
    async function boot() {
      setBootState({ active: true, phase: "workspace" });
      try {
        const [bootstrapData, projectsList] = await Promise.all([refreshBootstrap(), refreshProjects()]);
        const storedProjectId = window.localStorage.getItem(PROJECT_STORAGE_KEY) || "";
        const storedProjectExists = (projectsList || []).some((item) => String(item.project_id || "") === storedProjectId);
        const initialProjectId =
          (storedProjectExists ? storedProjectId : "") ||
          String((bootstrapData && bootstrapData.default_project_id) || "").trim() ||
          String(((projectsList || [])[0] || {}).project_id || "").trim();
        bootReadyRef.current = true;
        if (initialProjectId) {
          if (!disposed) setBootState({ active: true, phase: "thread" });
          await selectProject(initialProjectId, { silentNotFound: true, fromBoot: true });
        } else {
          refreshRuntimeStatus("", { background: true });
        }
      } finally {
        if (!disposed) {
          setBootState((prev) => ({ ...prev, active: false }));
        }
      }
    }
    boot();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (drawerView === "tasks") refreshTasks();
    if (drawerView === "tools") refreshWorkbenchTools();
    if (drawerView === "skills") refreshSkills();
    if (drawerView === "agent") refreshSpecs();
  }, [drawerView, uiLocale, projectId]);

  useEffect(() => {
    if (!bootReadyRef.current) return undefined;
    let disposed = false;

    const refreshVisibleState = async () => {
      if (disposed || document.visibilityState === "hidden") return;
      await Promise.all([
        refreshProjectsIfStale({ minAgeMs: PROJECTS_REFRESH_STALE_MS }),
        refreshRuntimeStatus(projectId, { background: true }),
      ]);
    };

    const handleWindowFocus = () => {
      refreshVisibleState();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshVisibleState();
      }
    };

    window.addEventListener("focus", handleWindowFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      disposed = true;
      window.removeEventListener("focus", handleWindowFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [projectId, chatSettings.model, chatSettings.max_output_tokens]);

  useEffect(() => {
    if (!bootReadyRef.current || document.visibilityState === "hidden") return undefined;
    refreshRuntimeStatus(projectId, { background: true });
    const intervalMs = nextRuntimeStatusPollIntervalMs({
      sending: anyThreadBusy,
      activeRunId,
      drawerView,
      contextMeterOpen,
    });
    if (!intervalMs) return undefined;
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      refreshRuntimeStatus(projectId, { background: true });
    }, intervalMs);
    return () => window.clearInterval(intervalId);
  }, [projectId, chatSettings.model, chatSettings.max_output_tokens, anyThreadBusy, activeRunId, drawerView, contextMeterOpen]);

  useEffect(() => {
    refreshEvalRuns({ background: true });
  }, []);

  useEffect(() => {
    const hasActiveEval = evalRuns.some((item) => ["queued", "running"].includes(String(item.status || "")));
    if (!hasActiveEval) return undefined;
    const intervalId = window.setInterval(() => {
      refreshEvalRuns({ background: true });
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [evalRuns.some((item) => ["queued", "running"].includes(String(item.status || "")))]);

  function clearUiError() {
    setUiError(null);
  }

  function applyUiError(errorLike, fallbackSummary = null, fallback = {}) {
    const normalized = normalizeUiError(uiLocale, errorLike, fallbackSummary, fallback);
    setUiError(normalized);
    return normalized;
  }

  function openContextMeter() {
    if (contextMeterCloseTimerRef.current) {
      window.clearTimeout(contextMeterCloseTimerRef.current);
      contextMeterCloseTimerRef.current = null;
    }
    setContextMeterOpen(true);
  }

  function scheduleContextMeterClose() {
    if (contextMeterCloseTimerRef.current) {
      window.clearTimeout(contextMeterCloseTimerRef.current);
    }
    contextMeterCloseTimerRef.current = window.setTimeout(() => {
      contextMeterCloseTimerRef.current = null;
      setContextMeterOpen(false);
    }, 160);
  }

  function summarizeContextStatus(meterLike, compactionLike) {
    const meter = meterLike && typeof meterLike === "object" ? meterLike : {};
    const compaction = compactionLike && typeof compactionLike === "object" ? compactionLike : {};
    const recommendation = String(meter.compact_recommendation || compaction.compact_recommendation || "none");
    const stale = Boolean(meter.stale);
    const usedPercent = Math.max(0, Number(meter.used_percent || 0) || 0);
    const used = formatTokenCount(meter.estimated_tokens || compaction.estimated_context_tokens || 0);
    const total = formatTokenCount(meter.context_window || compaction.effective_context_window || 0);
    const mode = String(meter.estimate_mode || compaction.estimate_mode || "quick");
    const status = stale
      ? t("context_meter.status.updating")
      : (recommendation === "required" || recommendation === "suggested" || usedPercent >= 80)
        ? t("context_meter.status.tight")
        : t("context_meter.status.enough");
    const compact = recommendation === "required"
      ? t("context_meter.compact.required")
      : recommendation === "suggested"
        ? t("context_meter.compact.suggested")
        : t("context_meter.compact.none");
    return `${status} · ${compact} · ${used} / ${total} · ${mode}`;
  }

  function appendLocalAssistantMessage(text, options = {}) {
    const baseActivity = {
      status: String(options.status || "completed"),
      final_answer: text,
      started_at: Date.now(),
      finished_at: Date.now(),
    };
    const message = createMessage("assistant", text, {
      id: options.id,
      activity: { ...baseActivity, ...((options && options.activity) || {}) },
    });
    setMessages((prev) => {
      const nextMessages = [...prev, message];
      const ownerId = String(sessionId || activeSessionIdRef.current || "").trim();
      if (ownerId) {
        updateThreadSnapshot(ownerId, (existing) => ({
          ...existing,
          messages: nextMessages,
        }));
      }
      return nextMessages;
    });
    return message;
  }

  function updateCurrentSessionRuntimeState(value) {
    const ownerId = String(sessionId || activeSessionIdRef.current || "").trim();
    const resolveNextState = (current) => resolveStateValue(
      current && typeof current === "object" ? current : {},
      value,
    );
    if (ownerId) {
      updateThreadSnapshot(ownerId, (existing) => ({
        ...existing,
        sessionRuntimeState: resolveNextState(existing.sessionRuntimeState),
      }));
    }
    if (!ownerId || String(activeSessionIdRef.current || "").trim() === ownerId) {
      setSessionRuntimeState((prev) => resolveNextState(prev));
    }
  }

  async function handleStatusCommand() {
    if (currentThreadBusy) return;
    const sid = String(sessionId || activeSessionIdRef.current || "").trim();
    let data = null;
    try {
      if (sid && !isTempThreadId(sid)) {
        const params = new URLSearchParams();
        const modelName = String(activeModel || chatSettings.model || "").trim();
        if (modelName) params.set("model", modelName);
        params.set("max_output_tokens", String(chatSettings.max_output_tokens || DEFAULT_SETTINGS.max_output_tokens));
        const query = params.toString();
        data = await fetchJson(`/api/sessions/${encodeURIComponent(sid)}/context-status${query ? `?${query}` : ""}`);
      } else {
        data = await refreshRuntimeStatus(projectId, { background: false });
      }
    } catch (err) {
      try {
        data = await refreshRuntimeStatus(projectId, { background: false });
      } catch {
        const nextError = applyUiError(err, t("slash.status.failed"));
        appendLocalAssistantMessage(nextError.summary || t("slash.status.failed"), { status: "failed" });
        return;
      }
    }
    const meter = (data && data.context_meter) || (health && health.context_meter) || {};
    const compaction = (data && data.compaction_status) || (health && health.compaction_status) || {};
    if (data && (data.context_meter || data.compaction_status)) {
      setHealth((prev) => (
        prev
          ? { ...prev, context_meter: data.context_meter || prev.context_meter, compaction_status: data.compaction_status || prev.compaction_status }
          : prev
      ));
      updateCurrentSessionRuntimeState((prev) => ({
        ...(prev || {}),
        context_meter: data.context_meter || (prev && prev.context_meter) || {},
        compaction_status: data.compaction_status || (prev && prev.compaction_status) || {},
      }));
    }
    setContextMeterOpen(true);
    appendLocalAssistantMessage(t("slash.status.summary", { summary: summarizeContextStatus(meter, compaction) }));
  }

  async function handleCompactCommand() {
    if (currentThreadBusy) return;
    const sid = String(sessionId || activeSessionIdRef.current || "").trim();
    if (!sid || isTempThreadId(sid)) {
      const summary = t("slash.compact.no_session");
      setUiError(normalizeUiError(uiLocale, { detail: summary }, summary));
      appendLocalAssistantMessage(summary, { status: "failed" });
      return;
    }
    const compactionItemId = `local-context-compaction-${Date.now()}`;
    appendLocalAssistantMessage(t("slash.compact.started"), {
      status: "running",
      activity: {
        live_items: [{
          id: compactionItemId,
          type: "contextCompaction",
          status: "inProgress",
          phase: "manual",
          summary: t("slash.compact.started"),
        }],
      },
    });
    try {
      const data = await fetchJson(`/api/sessions/${encodeURIComponent(sid)}/compact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger: "manual" }),
      });
      setHealth((prev) => (
        prev
          ? { ...prev, context_meter: data.context_meter || prev.context_meter, compaction_status: data.compaction_status || prev.compaction_status }
          : prev
      ));
      updateCurrentSessionRuntimeState((prev) => ({
        ...(prev || {}),
        context_meter: data.context_meter || (prev && prev.context_meter) || {},
        compaction_status: data.compaction_status || (prev && prev.compaction_status) || {},
      }));
      setContextMeterOpen(true);
      const summary = data.compacted
        ? (data.summary || t("slash.compact.done"))
        : t("slash.compact.skipped");
      appendLocalAssistantMessage(summary, {
        activity: {
          live_items: [{
            id: compactionItemId,
            type: "contextCompaction",
            status: "completed",
            phase: "manual",
            generation: Number(((data.compaction_status || {}).generation) || 0),
            summary,
          }],
        },
      });
    } catch (err) {
      const nextError = applyUiError(err, t("slash.compact.failed"));
      const summary = nextError.summary || t("slash.compact.failed");
      appendLocalAssistantMessage(summary, {
        status: "failed",
        activity: {
          live_items: [{
            id: compactionItemId,
            type: "contextCompaction",
            status: "failed",
            phase: "manual",
            summary,
          }],
        },
      });
    }
  }

  function updateModelSelection(nextModel, options = {}) {
    const normalized = String(nextModel || "").trim();
    if (options.markTouched !== false) setModelTouched(true);
    setChatSettings((prev) => ({ ...prev, model: normalized }));
    setSelectedPresetModel(resolvePresetModelValue(normalized, modelOptions, allowCustomModel));
  }

  function updateLocaleSelection(nextLocale) {
    const normalized = normalizeLocaleValue(nextLocale, supportedLocales, "");
    if (!normalized) {
      window.localStorage.removeItem(LOCALE_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(LOCALE_STORAGE_KEY, normalized);
    setChatSettings((prev) => (
      String(prev.locale || "").trim() === normalized
        ? prev
        : { ...prev, locale: normalized }
    ));
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

  async function refreshModelPresets() {
    if (modelPresetRefreshing || !activeProvider || activeProvider === "default") return;
    setModelPresetRefreshing(true);
    setModelPresetRefreshMessage("");
    try {
      const payload = await fetchJson(
        `/api/providers/${encodeURIComponent(activeProvider)}/models/refresh`,
        { method: "POST" },
      );
      const nextProviderOptions = Array.isArray(payload.provider_options) ? payload.provider_options : [];
      const nextModelOptions = dedupeStrings(Array.isArray(payload.model_options) ? payload.model_options : []);
      setHealth((prev) => ({
        ...(prev || {}),
        provider_options: nextProviderOptions.length
          ? nextProviderOptions
          : (Array.isArray(prev && prev.provider_options) ? prev.provider_options : []),
        model_options: nextModelOptions.length
          ? nextModelOptions
          : (Array.isArray(prev && prev.model_options) ? prev.model_options : []),
      }));
      const currentModel = String(chatSettings.model || "").trim();
      setSelectedPresetModel(resolvePresetModelValue(currentModel, nextModelOptions, allowCustomModel));
      setModelPresetRefreshMessage(t("settings.model_presets.updated", { count: nextModelOptions.length }));
      clearUiError();
    } catch (err) {
      const nextError = applyUiError(err, t("settings.model_presets.failed"));
      setModelPresetRefreshMessage(nextError.summary || t("settings.model_presets.failed"));
    } finally {
      setModelPresetRefreshing(false);
    }
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
        uiLocale,
        payload && Object.prototype.hasOwnProperty.call(payload, "detail") ? payload.detail : payload,
        t("errors.request_failed"),
        { status_code: res.status },
      );
      throw errorWithUiError(uiError);
    }
    return res.json();
  }

  async function refreshEvalCatalog(options = {}) {
    try {
      const data = await fetchJson("/api/evals/catalog");
      const suites = Array.isArray(data.suites) ? data.suites : [];
      setEvalCatalog(suites);
      return suites;
    } catch (err) {
      if (!options.background) setEvalError(normalizeUiError(uiLocale, err, t("eval.errors.catalog")).summary);
      return [];
    }
  }

  async function refreshEvalRuns(options = {}) {
    try {
      const data = await fetchJson("/api/evals/runs?limit=20");
      const runs = Array.isArray(data.runs) ? data.runs : [];
      setEvalRuns(runs);
      return runs;
    } catch (err) {
      if (!options.background) setEvalError(normalizeUiError(uiLocale, err, t("eval.errors.runs")).summary);
      return [];
    }
  }

  async function openEvalDialog() {
    setEvalDialogOpen(true);
    setEvalError("");
    setEvalForm((prev) => ({
      ...prev,
      provider: String(prev.provider || activeProvider || ""),
      model: String(
        prev.model
        || chatSettings.model
        || (activeProviderProfile && activeProviderProfile.default_model)
        || (health && health.default_model)
        || "",
      ),
    }));
    await Promise.all([refreshEvalCatalog(), refreshEvalRuns()]);
  }

  async function startEvalRun() {
    if (evalSubmitting) return;
    setEvalSubmitting(true);
    setEvalError("");
    try {
      const job = await fetchJson("/api/evals/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...evalForm,
          repeat: Math.max(1, Math.min(10, Number(evalForm.repeat || 1))),
        }),
      });
      setEvalRuns((prev) => [job, ...prev.filter((item) => String(item.id || "") !== String(job.id || ""))]);
    } catch (err) {
      setEvalError(normalizeUiError(uiLocale, err, t("eval.errors.start")).summary);
    } finally {
      setEvalSubmitting(false);
    }
  }

  function applyHealthSlices(bootstrapData, runtimeData) {
    let merged = null;
    setHealth((prev) => {
      merged = mergeHealthSlices(prev, bootstrapData, runtimeData);
      return merged;
    });
    return merged;
  }

  async function refreshBootstrap() {
    try {
      const data = await fetchJson("/api/bootstrap");
      clearUiError();
      applyHealthSlices(data, null);
      return data;
    } catch (err) {
      const nextError = applyUiError(err, t("errors.refresh_state_failed"));
      pushLogWithLimit(setLogs, "error", t("log.refresh_state_failed", { summary: nextError.summary }));
      return null;
    }
  }

  async function refreshRuntimeStatus(targetProjectId = projectId, options = {}) {
    const background = Boolean(options.background);
    const params = new URLSearchParams();
    const normalizedProjectId = String(targetProjectId || "").trim();
    const normalizedModel = String(chatSettings.model || "").trim();
    if (normalizedProjectId) params.set("project_id", normalizedProjectId);
    if (normalizedModel) params.set("model", normalizedModel);
    params.set("max_output_tokens", String(chatSettings.max_output_tokens || DEFAULT_SETTINGS.max_output_tokens));
    const requestKey = params.toString();
    const currentInFlight = runtimeStatusInFlightRef.current;
    if (currentInFlight && currentInFlight.key === requestKey && currentInFlight.promise) {
      return currentInFlight.promise;
    }
    if (runtimeStatusAbortRef.current) {
      runtimeStatusAbortRef.current.abort();
      runtimeStatusAbortRef.current = null;
    }
    const requestSeq = ++runtimeStatusRequestSeqRef.current;
    const controller = new AbortController();
    runtimeStatusAbortRef.current = controller;
    const requestPromise = (async () => {
      try {
        const data = await fetchJson(`/api/runtime-status?${requestKey}`, { signal: controller.signal });
        if (requestSeq !== runtimeStatusRequestSeqRef.current) return data;
        if (!background) clearUiError();
        applyHealthSlices(null, data);
        dispatch({ type: "update", path: ["bootstrap", "runtimeStatus"], value: data });
        runtimeStatusLastFetchedAtRef.current = Date.now();
        return data;
      } catch (err) {
        if (err && err.name === "AbortError") return null;
        if (requestSeq !== runtimeStatusRequestSeqRef.current) return null;
        const nextError = background
          ? normalizeUiError(uiLocale, err, t("errors.refresh_state_failed"))
          : applyUiError(err, t("errors.refresh_state_failed"));
        pushLogWithLimit(setLogs, "error", t("log.refresh_state_failed", { summary: nextError.summary }));
        return null;
      } finally {
        if (runtimeStatusAbortRef.current === controller) {
          runtimeStatusAbortRef.current = null;
        }
        if (runtimeStatusInFlightRef.current && runtimeStatusInFlightRef.current.promise === requestPromise) {
          runtimeStatusInFlightRef.current = { key: "", promise: null };
        }
      }
    })();
    runtimeStatusInFlightRef.current = { key: requestKey, promise: requestPromise };
    return requestPromise;
  }

  async function refreshHealth() {
    const [bootstrapData, runtimeData] = await Promise.all([
      refreshBootstrap(),
      refreshRuntimeStatus(projectId, { background: true }),
    ]);
    return mergeHealthSlices(null, bootstrapData, runtimeData);
  }

  async function handleAppUpdate() {
    if (appUpdateState.status === "running" || anyThreadBusy) return;
    setAppUpdateState({ status: "running", result: null, error: null });
    try {
      const data = await fetchJson("/api/app/update", { method: "POST" });
      setAppUpdateState({ status: data && data.ok ? "success" : "failed", result: data, error: null });
      pushLogWithLimit(
        setLogs,
        data && data.ok ? "system" : "error",
        data && data.ok ? t("update.success") : `${t("update.failed")}: ${String((data && data.message) || "")}`,
      );
      if (data && data.ok) clearUiError();
    } catch (err) {
      const nextError = normalizeUiError(uiLocale, err, t("update.failed"));
      setAppUpdateState({ status: "failed", result: null, error: nextError });
      pushLogWithLimit(setLogs, "error", `${t("update.failed")}: ${nextError.summary}`);
    }
  }

  function setSkillSelectionState(skillId, content, options = {}) {
    const nextSkillId = String(skillId || "").trim();
    selectedSkillIdRef.current = nextSkillId;
    skillDraftModeRef.current = Boolean(options.draft) || !nextSkillId;
    setSelectedSkillId(nextSkillId);
    setSkillEditor(String(content || ""));
  }

  function startNewSkillDraft(content = defaultSkillTemplate(uiLocale)) {
    setSkillSelectionState("", content, { draft: true });
  }

  async function selectSkillFromList(skillId, list = skills) {
    const sid = String(skillId || "").trim();
    if (!sid) {
      startNewSkillDraft();
      return false;
    }
    const safeList = shallowSkillList(list);
    const hit = safeList.find((item) => skillKey(item) === sid || skillName(item) === sid);
    if (!hit) return false;
    clearUiError();
    const hitKey = skillKey(hit);
    setSkillSelectionState(hitKey, String(hit.content || ""));
    if (!String(hit.content || "").trim()) {
      try {
        const payload = normalizeSkillDescriptor(await fetchJson(workbenchSkillUrl(hit)));
        setSkills(safeList.map((item) => (skillKey(item) === hitKey ? { ...item, ...payload } : item)));
        setSkillSelectionState(skillKey(payload) || hitKey, String(payload.content || ""));
      } catch (err) {
        const nextError = applyUiError(err, t("errors.read_skill_failed"));
        pushLogWithLimit(setLogs, "error", t("errors.read_skill_failed"));
      }
    }
    return true;
  }

  async function syncSkillSelection(list, preferredSkillId) {
    const safeList = shallowSkillList(list);
    const explicitPreferred = typeof preferredSkillId === "string" ? String(preferredSkillId).trim() : null;
    const activeSkillId = explicitPreferred !== null ? explicitPreferred : String(selectedSkillIdRef.current || "").trim();
    if (activeSkillId && await selectSkillFromList(activeSkillId, safeList)) {
      return;
    }
    if ((explicitPreferred === "" || (explicitPreferred === null && skillDraftModeRef.current)) && !activeSkillId) {
      startNewSkillDraft(skillEditor || defaultSkillTemplate(uiLocale));
      return;
    }
    if (safeList.length) {
      await selectSkillFromList(skillKey(safeList[0]), safeList);
      return;
    }
    startNewSkillDraft(skillEditor || defaultSkillTemplate(uiLocale));
  }

  function clearLiveRunUi() {
    setSending(false);
    setLastResponse(null);
    setToolTimeline([]);
    setLiveToolTimeline([]);
    setLiveTurnState({});
    setLiveEvidence({});
    setLiveRunLogs([]);
    setStageTimeline([]);
    setActiveRunId("");
    setActiveRunThreadId("");
    setActiveRunStartedAt(0);
    setLiveHeartbeat(createEmptyLiveHeartbeat());
    setStoppingRun(false);
    setPendingGuidance([]);
    setContextMeterOpen(false);
  }

  function resetItemDomain() {
    dispatch({ type: "items/reset" });
  }

  function threadCacheKey(threadId) {
    return String(threadId || "").trim();
  }

  function visibleThreadActiveTurnSnapshot() {
    return normalizeThreadActiveTurn({
      sending,
      activeRunId,
      activeRunThreadId,
      startedAt: activeRunStartedAt,
      lastLiveProgressAt: activeRunProgressAt,
      liveHeartbeat: activeLiveHeartbeat,
      stoppingRun,
      lastResponse,
      toolTimeline,
      liveToolTimeline,
      liveTurnState,
      liveEvidence,
      liveRunLogs,
      stageTimeline,
      pendingGuidance,
    });
  }

  function storeThreadSnapshot(threadId, snapshot) {
    const key = threadCacheKey(threadId);
    if (!key || isTempThreadId(key) || !snapshot) return null;
    if (threadDetailCacheRef.current.has(key)) threadDetailCacheRef.current.delete(key);
    threadDetailCacheRef.current.set(key, {
      activeTurn: normalizeThreadActiveTurn(snapshot.activeTurn),
      cachedAt: Date.now(),
      detail: snapshot.detail || null,
      messages: Array.isArray(snapshot.messages) ? snapshot.messages : [],
      sessionRuntimeState: snapshot.sessionRuntimeState && typeof snapshot.sessionRuntimeState === "object"
        ? snapshot.sessionRuntimeState
        : {},
    });
    while (threadDetailCacheRef.current.size > THREAD_DETAIL_CACHE_LIMIT) {
      const oldestKey = threadDetailCacheRef.current.keys().next().value;
      threadDetailCacheRef.current.delete(oldestKey);
    }
    return threadDetailCacheRef.current.get(key) || null;
  }

  function updateThreadSnapshot(threadId, updater) {
    const key = threadCacheKey(threadId);
    if (!key || isTempThreadId(key)) return null;
    const existing = threadDetailCacheRef.current.get(key) || {
      detail: null,
      messages: [],
      sessionRuntimeState: {},
      activeTurn: createEmptyThreadActiveTurn(),
      cachedAt: 0,
    };
    const nextValue = typeof updater === "function" ? updater(existing) : updater;
    if (!nextValue) return existing;
    return storeThreadSnapshot(key, { ...existing, ...nextValue });
  }

  function updateThreadPendingGuidance(threadId, updater) {
    const key = threadCacheKey(threadId);
    if (!key || isTempThreadId(key)) return;
    const resolvePending = (items) => {
      const current = Array.isArray(items) ? items : [];
      const next = resolveStateValue(current, updater);
      return Array.isArray(next) ? next : current;
    };
    if (String(activeSessionIdRef.current || "").trim() === key) {
      setPendingGuidance((prev) => {
        const nextPending = resolvePending(prev);
        updateThreadSnapshot(key, (existing) => ({
          ...existing,
          activeTurn: normalizeThreadActiveTurn({
            ...normalizeThreadActiveTurn(existing.activeTurn || {}),
            pendingGuidance: nextPending,
          }),
        }));
        return nextPending;
      });
      return;
    }
    updateThreadSnapshot(key, (existing) => {
      const activeTurn = normalizeThreadActiveTurn(existing.activeTurn || {});
      return {
        ...existing,
        activeTurn: normalizeThreadActiveTurn({
          ...activeTurn,
          pendingGuidance: resolvePending(activeTurn.pendingGuidance),
        }),
      };
    });
  }

  function rememberVisibleThreadSnapshot(targetThreadId = sessionId) {
    const key = threadCacheKey(targetThreadId);
    if (!key || isTempThreadId(key)) return null;
    return updateThreadSnapshot(key, (existing) => {
      const currentMessages = Array.isArray(messages) ? messages : [];
      const currentRuntimeState = sessionRuntimeState && typeof sessionRuntimeState === "object" ? sessionRuntimeState : {};
      const currentActiveTurn = visibleThreadActiveTurnSnapshot();
      const existingActiveTurn = normalizeThreadActiveTurn(existing.activeTurn);
      const existingIsLive = isThreadSnapshotLive(key, existing);
      const currentIsLive = isThreadActiveTurnLive(key, currentActiveTurn) || hasLiveThreadMessages(currentMessages);
      const shouldPreserveLiveSnapshot = existingIsLive && !currentIsLive;
      return {
        ...existing,
        messages: shouldPreserveLiveSnapshot ? (existing.messages || []) : currentMessages,
        sessionRuntimeState: shouldPreserveLiveSnapshot && Object.keys(existing.sessionRuntimeState || {}).length
          ? existing.sessionRuntimeState
          : currentRuntimeState,
        activeTurn: shouldPreserveLiveSnapshot ? existingActiveTurn : currentActiveTurn,
      };
    });
  }

  function applyVisibleThreadActiveTurn(activeTurnSnapshot) {
    const next = normalizeThreadActiveTurn(activeTurnSnapshot);
    setSending(next.sending);
    setLastResponse(next.lastResponse);
    setToolTimeline(next.toolTimeline);
    setLiveToolTimeline(next.liveToolTimeline);
    setLiveTurnState(next.liveTurnState);
    setLiveEvidence(next.liveEvidence);
    setLiveRunLogs(next.liveRunLogs);
    setStageTimeline(next.stageTimeline);
    setPendingGuidance(next.pendingGuidance);
    setActiveRunId(next.activeRunId);
    setActiveRunThreadId(next.activeRunThreadId);
    setActiveRunStartedAt(next.startedAt);
    setLastLiveProgressAt(next.lastLiveProgressAt);
    setLiveHeartbeat(next.liveHeartbeat);
    setStoppingRun(next.stoppingRun);
    setContextMeterOpen(false);
  }

  function mergeSessionRuntimeStateSnapshot(existingState, incomingState, options = {}) {
    const existing = existingState && typeof existingState === "object" ? existingState : {};
    const incoming = incomingState && typeof incomingState === "object" ? incomingState : {};
    if (!Object.keys(incoming).length) return existing;
    if (options.preferExisting) return { ...incoming, ...existing };
    return { ...existing, ...incoming };
  }

  function snapshotFromThreadDetail(data, options = {}) {
    const detail = normalizeThreadDetailPayload(data);
    const existingSnapshot = options.existingSnapshot || null;
    const preserveActiveTurn = Boolean(options.preserveActiveTurn && existingSnapshot);
    const preserveMessages = Boolean(options.preserveMessages && existingSnapshot);
    const preserveRuntimeState = Boolean(options.preserveRuntimeState && existingSnapshot);
    const detailMessages = extractSessionMessages(detail);
    const existingMessagesById = new Map(
      ((existingSnapshot && Array.isArray(existingSnapshot.messages)) ? existingSnapshot.messages : [])
        .map((item) => [String(item.id || ""), item]),
    );
    return {
      detail,
      messages: preserveMessages
        ? (existingSnapshot.messages || [])
        : detailMessages.map((message) => {
            const previous = existingMessagesById.get(String(message.id || ""));
            if (!previous) return message;
            return {
              ...message,
              activity: mergeActivityState(message.activity || {}, previous.activity || {}),
              answerBundle:
                (previous.answerBundle && Object.keys(previous.answerBundle || {}).length)
                  ? previous.answerBundle
                  : message.answerBundle,
              runArtifact:
                (previous.runArtifact && Object.keys(previous.runArtifact || {}).length)
                  ? previous.runArtifact
                  : message.runArtifact,
              runActivityLoading: Boolean(previous.runActivityLoading),
              runActivityError: String(previous.runActivityError || ""),
              runDebugLoading: Boolean(previous.runDebugLoading),
              runDebugError: String(previous.runDebugError || ""),
            };
          }),
      sessionRuntimeState: preserveRuntimeState
        ? mergeSessionRuntimeStateSnapshot(
            (existingSnapshot && existingSnapshot.sessionRuntimeState) || {},
            (detail && detail.agent_state) || {},
            { preferExisting: true },
          )
        : mergeSessionRuntimeStateSnapshot(
            (existingSnapshot && existingSnapshot.sessionRuntimeState) || {},
            (detail && detail.agent_state) || {},
          ),
      activeTurn: preserveActiveTurn
        ? normalizeThreadActiveTurn(existingSnapshot.activeTurn)
        : createEmptyThreadActiveTurn(),
      cachedAt: Date.now(),
    };
  }

  function rememberThreadDetail(threadId, data, options = {}) {
    const key = threadCacheKey(threadId);
    if (!key || isTempThreadId(key)) return null;
    const snapshot = snapshotFromThreadDetail(data, {
      existingSnapshot: threadDetailCacheRef.current.get(key) || null,
      preserveActiveTurn: Boolean(options.preserveActiveTurn),
      preserveMessages: Boolean(options.preserveMessages),
      preserveRuntimeState: Boolean(options.preserveRuntimeState),
    });
    return storeThreadSnapshot(key, snapshot);
  }

  function applyThreadSnapshot(threadId, snapshot) {
    if (!snapshot) return;
    const key = threadCacheKey(threadId);
    resetItemDomain();
    setMessages(snapshot.messages || []);
    setSessionRuntimeState(snapshot.sessionRuntimeState || {});
    applyVisibleThreadActiveTurn(snapshot.activeTurn || createEmptyThreadActiveTurn());
    autoScrollEnabledRef.current = true;
    setShowJumpToLatest(false);
    if (snapshot.messages && snapshot.messages.length) {
      scrollChatToBottom();
    }
    if (snapshot.detail) {
      updateThreadStatus(key, String(snapshot.detail.status || "idle"));
    }
  }

  function replaceThreadRow(tempThreadId, rawItem) {
    const tempKey = String(tempThreadId || "").trim();
    const normalized = normalizeSingleThread(rawItem);
    if (!tempKey || !normalized) return;
    const threadKey = String(normalized.thread_id || normalized.session_id || "").trim();
    if (!threadKey) return;
    setSessions((prev) => {
      const previousList = Array.isArray(prev) ? prev : [];
      const hasTemp = previousList.some((entry) => String(entry.thread_id || entry.session_id || "").trim() === tempKey);
      const merged = { ...normalized, thread_id: threadKey, session_id: String(normalized.session_id || threadKey) };
      if (hasTemp) {
        const next = [];
        let inserted = false;
        previousList.forEach((entry) => {
          const key = String(entry.thread_id || entry.session_id || "").trim();
          if (key === tempKey) {
            if (!inserted) {
              next.push(merged);
              inserted = true;
            }
            return;
          }
          if (key === threadKey) return;
          next.push(entry);
        });
        return sortThreadRows(next);
      }
      const realIndex = previousList.findIndex((entry) => String(entry.thread_id || entry.session_id || "").trim() === threadKey);
      if (realIndex >= 0) {
        const next = previousList.slice();
        next[realIndex] = merged;
        return sortThreadRows(next);
      }
      return sortThreadRows([merged, ...previousList]);
    });
  }

  function normalizeSingleThread(item) {
    return normalizeThreadListPayload({ threads: [item] })[0] || null;
  }

  function upsertThreadRow(rawItem, options = {}) {
    const normalized = normalizeSingleThread(rawItem);
    if (!normalized) return;
    const threadKey = String(normalized.thread_id || normalized.session_id || "").trim();
    if (!threadKey) return;
    const activeProjectId = String(projectId || "").trim();
    if (activeProjectId && normalized.project_id && String(normalized.project_id || "").trim() !== activeProjectId) {
      return;
    }
    const promote = options.promote === true;
    setSessions((prev) => {
      const previousList = Array.isArray(prev) ? prev : [];
      const existingIndex = previousList.findIndex((entry) => String(entry.thread_id || entry.session_id || "").trim() === threadKey);
      const existing = existingIndex >= 0 ? previousList[existingIndex] : {};
      const candidate = {
        ...normalized,
        thread_id: threadKey,
        session_id: String(normalized.session_id || threadKey),
      };
      const merged = mergeThreadRow(existing, candidate);
      if (existingIndex >= 0) {
        const remainder = previousList.filter((_, index) => index !== existingIndex);
        return sortThreadRows([merged, ...remainder]);
      }
      return sortThreadRows(promote ? [merged, ...previousList] : [...previousList, merged]);
    });
  }

  function removeThreadRow(targetThreadId) {
    const normalizedThreadId = String(targetThreadId || "").trim();
    if (!normalizedThreadId) return;
    threadDetailCacheRef.current.delete(threadCacheKey(normalizedThreadId));
    setSessions((prev) => (Array.isArray(prev) ? prev : []).filter(
      (entry) => String(entry.thread_id || entry.session_id || "").trim() !== normalizedThreadId,
    ));
  }

  function updateThreadStatus(targetThreadId, status) {
    const normalizedThreadId = String(targetThreadId || "").trim();
    if (!normalizedThreadId) return;
    const nextStatus = String(status || "idle").trim() || "idle";
    setSessions((prev) => {
      const previousList = Array.isArray(prev) ? prev : [];
      let found = false;
      const nextList = previousList.map((entry) => {
        if (String(entry.thread_id || entry.session_id || "").trim() !== normalizedThreadId) return entry;
        found = true;
        return { ...entry, status: nextStatus };
      });
      if (found) return nextList;
      const nowIso = new Date().toISOString();
      return [
        {
          thread_id: normalizedThreadId,
          session_id: normalizedThreadId,
          title: "",
          has_custom_title: false,
          preview: "",
          turn_count: 0,
          project_id: String(projectId || "").trim(),
          project_title: String((currentProject && currentProject.title) || ""),
          project_root: String((currentProject && currentProject.root_path) || runtimeStatus.project_root || ""),
          git_branch: String((currentProject && currentProject.git_branch) || runtimeStatus.git_branch || ""),
          cwd: String(runtimeStatus.project_root || ""),
          updated_at: nowIso,
          created_at: nowIso,
          status: nextStatus,
        },
        ...nextList,
      ];
    });
  }

  function closeThreadMenu() {
    setThreadMenu(null);
  }

  function closeRenameDialog() {
    if (renamingThread) return;
    setRenameDialog(null);
    setRenameDraft("");
    setRenameError("");
  }

  function closeProjectMenu() {
    setProjectMenu(null);
  }

  function cancelProjectLongPress() {
    const current = projectLongPressRef.current;
    if (current && current.timer) {
      window.clearTimeout(current.timer);
    }
    projectLongPressRef.current = { timer: null, consumed: Boolean(current && current.consumed) };
  }

  function openProjectMenuAt(position, item) {
    if (!item || currentThreadBusy || item.is_default) return;
    closeThreadMenu();
    setProjectMenu({
      projectId: String(item.project_id || ""),
      title: String(item.title || item.project_id || ""),
      x: Math.max(12, Number((position && position.x) || 0) || 0),
      y: Math.max(12, Number((position && position.y) || 0) || 0),
    });
  }

  function handleProjectContextMenu(event, item) {
    event.preventDefault();
    openProjectMenuAt({ x: event.clientX, y: event.clientY }, item);
  }

  function handleProjectTouchStart(event, item) {
    if (currentThreadBusy || (item && item.is_default)) return;
    cancelProjectLongPress();
    const touch = (event.touches && event.touches[0]) || null;
    projectLongPressRef.current = {
      consumed: false,
      timer: window.setTimeout(() => {
        projectLongPressRef.current = { timer: null, consumed: true };
        openProjectMenuAt(
          {
            x: touch ? touch.clientX : 24,
            y: touch ? touch.clientY : 24,
          },
          item,
        );
      }, 480),
    };
  }

  function handleProjectClick(event, targetProjectId) {
    if (projectLongPressRef.current && projectLongPressRef.current.consumed) {
      projectLongPressRef.current = { timer: null, consumed: false };
      event.preventDefault();
      return;
    }
    selectProject(targetProjectId);
  }

  function cancelThreadLongPress() {
    const current = threadLongPressRef.current;
    if (current && current.timer) {
      window.clearTimeout(current.timer);
    }
    threadLongPressRef.current = { timer: null, consumed: Boolean(current && current.consumed) };
  }

  function openThreadMenuAt(position, item) {
    if (!item || isTempThreadId(item.session_id || item.thread_id)) return;
    closeProjectMenu();
    setThreadMenu({
      sessionId: String(item.session_id || ""),
      title: String(item.title || t("labels.new_thread")),
      x: Math.max(12, Number((position && position.x) || 0) || 0),
      y: Math.max(12, Number((position && position.y) || 0) || 0),
    });
  }

  function handleThreadContextMenu(event, item) {
    event.preventDefault();
    openThreadMenuAt({ x: event.clientX, y: event.clientY }, item);
  }

  function handleThreadTouchStart(event, item) {
    if (isTempThreadId(item && (item.session_id || item.thread_id))) return;
    cancelThreadLongPress();
    const touch = (event.touches && event.touches[0]) || null;
    threadLongPressRef.current = {
      consumed: false,
      timer: window.setTimeout(() => {
        threadLongPressRef.current = { timer: null, consumed: true };
        openThreadMenuAt(
          {
            x: touch ? touch.clientX : 24,
            y: touch ? touch.clientY : 24,
          },
          item,
        );
      }, 480),
    };
  }

  function handleThreadClick(event, targetSessionId) {
    if (threadLongPressRef.current && threadLongPressRef.current.consumed) {
      threadLongPressRef.current = { timer: null, consumed: false };
      event.preventDefault();
      return;
    }
    const sid = String(targetSessionId || "").trim();
    if (!sid) return;
    if (event && event.shiftKey) {
      event.preventDefault();
      closeThreadMenu();
      selectThreadRange(sid);
      return;
    }
    setThreadSelectionAnchorId(sid);
    if (selectedThreadIds.size) setSelectedThreadIds(new Set());
    clearThreadRunIndicator(sid);
    loadSession(targetSessionId);
  }

  function openRenameThreadDialog(targetSessionId) {
    const sid = String(targetSessionId || "").trim();
    if (!sid || isTempThreadId(sid)) return;
    const cached = threadDetailCacheRef.current.get(sid);
    const existingCustomTitle = String((((cached || {}).detail || {}).title) || "").trim();
    setRenameDialog({
      sessionId: sid,
      displayTitle: String((((cached || {}).detail || {}).display_title) || sessionTitleFromList(sessions, sid, uiLocale) || ""),
    });
    setRenameDraft(existingCustomTitle);
    setRenameError("");
    closeThreadMenu();
  }

  async function refreshProjects() {
    if (projectsInFlightRef.current) return projectsInFlightRef.current;
    const requestSeq = ++projectsRequestSeqRef.current;
    const requestPromise = (async () => {
      try {
        const data = await fetchJson("/api/projects");
        const list = Array.isArray(data.projects) ? data.projects : [];
        if (requestSeq !== projectsRequestSeqRef.current) return list;
        clearUiError();
        setProjects(list);
        projectsLastFetchedAtRef.current = Date.now();
        return list;
      } catch (err) {
        if (requestSeq !== projectsRequestSeqRef.current) return [];
        const nextError = applyUiError(err, t("errors.refresh_projects_failed"));
        pushLogWithLimit(setLogs, "error", t("log.refresh_projects_failed", { summary: nextError.summary }));
        return [];
      } finally {
        if (projectsInFlightRef.current === requestPromise) {
          projectsInFlightRef.current = null;
        }
      }
    })();
    projectsInFlightRef.current = requestPromise;
    return requestPromise;
  }

  async function refreshProjectsIfStale(options = {}) {
    const minAgeMs = Math.max(0, Number(options.minAgeMs || 0) || 0);
    if (projectsInFlightRef.current) return projectsInFlightRef.current;
    const lastFetchedAt = Number(projectsLastFetchedAtRef.current || 0) || 0;
    if (minAgeMs && lastFetchedAt && (Date.now() - lastFetchedAt) < minAgeMs) {
      return Array.isArray(projects) ? projects : [];
    }
    return refreshProjects();
  }

  async function refreshSessions(targetProjectId = projectId, options = {}) {
    const requestSeq = ++sessionsRequestSeqRef.current;
    const background = Boolean(options.background);
    try {
      const suffix = targetProjectId ? `&project_id=${encodeURIComponent(targetProjectId)}` : "";
      const data = await fetchJson(`/api/threads?limit=80${suffix}`);
      const list = normalizeThreadListPayload(data);
      if (requestSeq !== sessionsRequestSeqRef.current) return list;
      if (!background) clearUiError();
      setSessions((prev) => mergeAuthoritativeThreadRows(list, prev));
      return list;
    } catch (err) {
      if (requestSeq !== sessionsRequestSeqRef.current) return [];
      const nextError = background
        ? normalizeUiError(uiLocale, err, t("errors.refresh_threads_failed"))
        : applyUiError(err, t("errors.refresh_threads_failed"));
      pushLogWithLimit(setLogs, "error", t("log.refresh_threads_failed", { summary: nextError.summary }));
      return [];
    }
  }

  async function selectProject(nextProjectId, options = {}) {
    const targetProjectId = String(nextProjectId || "").trim();
    if (!targetProjectId) return false;
    setProjectId(targetProjectId);
    setTasks([]);
    setSessionId("");
    resetItemDomain();
    setSessionRuntimeState({});
    clearLiveRunUi();
    setStageTimeline([]);
    setMobileThreadsOpen(false);
    closeProjectMenu();
    closeThreadMenu();
    clearUiError();
    const list = await refreshSessions(targetProjectId);
    refreshRuntimeStatus(targetProjectId, { background: true });
    const storedSessionId = window.localStorage.getItem(sessionStorageKeyForProject(targetProjectId)) || "";
    const preferredSessionId =
      storedSessionId && list.some((item) => String(item.session_id || item.thread_id || "") === storedSessionId)
        ? storedSessionId
        : String((((list || [])[0] || {}).session_id) || (((list || [])[0] || {}).thread_id) || "").trim();
    if (preferredSessionId) {
      return loadSession(preferredSessionId, { silentNotFound: Boolean(options.silentNotFound), projectIdOverride: targetProjectId });
    }
    if (!options.fromBoot) {
      pushLogWithLimit(setLogs, "system", t("log.project_switched", { project_id: targetProjectId.slice(0, 8) }));
      return true;
    }
    return true;
  }

  async function refreshTasks() {
    const requestSeq = ++tasksRequestSeqRef.current;
    setPanelStatus("tasks", "loading");
    if (!projectId) {
      setTasks([]);
      setPanelStatus("tasks", "fresh");
      return [];
    }
    try {
      const data = await fetchJson(`/api/tasks?project_id=${encodeURIComponent(projectId)}`);
      const list = Array.isArray(data.tasks) ? data.tasks.map(normalizeTaskDescriptor) : [];
      if (requestSeq !== tasksRequestSeqRef.current) return list;
      clearUiError();
      setTasks(list);
      setPanelStatus("tasks", "fresh");
      return list;
    } catch (err) {
      if (requestSeq !== tasksRequestSeqRef.current) return [];
      setPanelStatus("tasks", "error");
      const nextError = applyUiError(err, t("errors.refresh_tasks_failed"));
      pushLogWithLimit(setLogs, "error", t("log.refresh_tasks_failed", { summary: nextError.summary }));
      return [];
    }
  }

  async function refreshWorkbenchTools() {
    setPanelStatus("tools", "loading");
    try {
      const data = await fetchJson("/api/workbench/tools");
      clearUiError();
      setWorkbenchTools(Array.isArray(data.tools) ? data.tools : []);
      setPanelStatus("tools", "fresh");
      return data;
    } catch (err) {
      setPanelStatus("tools", "error");
      const nextError = applyUiError(err, t("errors.refresh_tools_failed"));
      pushLogWithLimit(setLogs, "error", t("log.refresh_tools_failed", { summary: nextError.summary }));
      return null;
    }
  }

  async function refreshSkills(preferredSkillId) {
    const requestSeq = ++skillsRequestSeqRef.current;
    setPanelStatus("skills", "loading");
    try {
      const data = await fetchJson("/api/workbench/skills");
      const list = shallowSkillList(data.skills);
      if (requestSeq !== skillsRequestSeqRef.current) return list;
      clearUiError();
      setSkills(list);
      await syncSkillSelection(list, preferredSkillId);
      setPanelStatus("skills", "fresh");
      return list;
    } catch (err) {
      if (requestSeq !== skillsRequestSeqRef.current) return [];
      setPanelStatus("skills", "error");
      const nextError = applyUiError(err, t("errors.refresh_skills_failed"));
      pushLogWithLimit(setLogs, "error", t("log.refresh_skills_failed", { summary: nextError.summary }));
      return [];
    }
  }

  async function refreshSpecs() {
    setPanelStatus("specs", "loading");
    try {
      const data = await fetchJson(workbenchSpecUrl("", uiLocale));
      const list = Array.isArray(data.specs) ? data.specs : [];
      clearUiError();
      setSpecs(list);
      const preferred = list.find((item) => item.name === selectedSpecName) || list[0];
      if (preferred) {
        await loadSpecDetail(String(preferred.name || ""));
      }
      setPanelStatus("specs", "fresh");
      return list;
    } catch (err) {
      setPanelStatus("specs", "error");
      const nextError = applyUiError(err, t("errors.refresh_specs_failed"));
      pushLogWithLimit(setLogs, "error", t("log.refresh_specs_failed", { summary: nextError.summary }));
      return [];
    }
  }

  async function createProjectFromDraft() {
    const rootPath = String(projectPathDraft || "").trim();
    const title = String(projectTitleDraft || "").trim();
    if (!rootPath) {
      setProjectFormError(t("errors.absolute_path_required"));
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
      await refreshProjects();
      clearUiError();
      setProjectDialogOpen(false);
      setProjectPathDraft("");
      setProjectTitleDraft("");
      closeProjectMenu();
      await selectProject(String(payload.project_id || ""));
      pushLogWithLimit(setLogs, "system", t("log.project_added", { title: payload.title || payload.project_id }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.add_project_failed"));
      setProjectFormError(nextError.summary);
      pushLogWithLimit(setLogs, "error", t("errors.add_project_failed"));
    } finally {
      setSavingProject(false);
    }
  }

  async function createSession(targetProjectId = projectId, options = {}) {
    if (pendingThreadCreationPromiseRef.current) {
      return pendingThreadCreationPromiseRef.current;
    }
    const resolvedTargetProjectId = String(targetProjectId || "").trim();
    const previousSnapshot = {
      sessionId,
      messages,
      sessionRuntimeState,
    };
    const projectRecord = projects.find((item) => String(item.project_id || "") === resolvedTargetProjectId) || currentProject || null;
    const nowIso = new Date().toISOString();
    const tempId = `${TEMP_THREAD_PREFIX}${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    pendingTempThreadIdRef.current = tempId;
    setCreatingThread(true);
    activeThreadRequestSeqRef.current += 1;
    if (activeThreadAbortRef.current) {
      activeThreadAbortRef.current.abort();
      activeThreadAbortRef.current = null;
    }
    setLoadingSession(false);
    if (resolvedTargetProjectId) setProjectId(resolvedTargetProjectId);
    setSessionId(tempId);
    resetItemDomain();
    setMessages([]);
    setSessionRuntimeState({});
    clearLiveRunUi();
    clearUiError();
    closeProjectMenu();
    closeThreadMenu();
    upsertThreadRow(
      {
        thread_id: tempId,
        session_id: tempId,
        title: t("labels.new_thread"),
        preview: "",
        turn_count: 0,
        project_id: resolvedTargetProjectId,
        project_title: String((projectRecord && projectRecord.title) || ""),
        project_root: String((projectRecord && projectRecord.root_path) || runtimeStatus.project_root || ""),
        git_branch: String((projectRecord && projectRecord.git_branch) || runtimeStatus.git_branch || ""),
        cwd: String((projectRecord && projectRecord.root_path) || runtimeStatus.project_root || ""),
        updated_at: nowIso,
        created_at: nowIso,
        activity_at: nowIso,
        activity_revision: 0,
        activity_kind: "created",
        status: "idle",
      },
      { promote: true },
    );

    const creationPromise = (async () => {
      try {
        const data = await fetchJson("/api/thread/new", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_id: resolvedTargetProjectId || "" }),
        });
        const sid = String(data.thread_id || data.session_id || "").trim();
        const resolvedProjectId = String(data.project_id || resolvedTargetProjectId || "").trim();
        if (!sid) throw new Error("session id missing");
        replaceThreadRow(tempId, {
          thread_id: sid,
          session_id: sid,
          title: "",
          preview: "",
          turn_count: 0,
          project_id: resolvedProjectId,
          project_title: String((projectRecord && projectRecord.title) || ""),
          project_root: String((projectRecord && projectRecord.root_path) || runtimeStatus.project_root || ""),
          git_branch: String((projectRecord && projectRecord.git_branch) || runtimeStatus.git_branch || ""),
          cwd: String((projectRecord && projectRecord.root_path) || runtimeStatus.project_root || ""),
          updated_at: nowIso,
          created_at: nowIso,
          activity_at: nowIso,
          activity_revision: 0,
          activity_kind: "created",
          status: "idle",
        });
        if (activeSessionIdRef.current === tempId) activeSessionIdRef.current = sid;
        setSessionId((current) => (current === tempId ? sid : current));
        if (resolvedProjectId) setProjectId(resolvedProjectId);
        pushLogWithLimit(setLogs, "system", t("log.thread_created", { session_id: sid.slice(0, 8) }));
        return sid;
      } catch (err) {
        removeThreadRow(tempId);
        if (activeSessionIdRef.current === tempId && options.restoreOnFailure !== false) {
          setSessionId(previousSnapshot.sessionId || "");
          setMessages(previousSnapshot.messages || []);
          setSessionRuntimeState(previousSnapshot.sessionRuntimeState || {});
        }
        throw err;
      } finally {
        if (pendingTempThreadIdRef.current === tempId) pendingTempThreadIdRef.current = "";
        pendingThreadCreationPromiseRef.current = null;
        setCreatingThread(false);
      }
    })();
    pendingThreadCreationPromiseRef.current = creationPromise;
    return creationPromise;
  }

  async function loadSession(targetSessionId, options = {}) {
    const sid = String(targetSessionId || "").trim();
    if (!sid) return false;
    if (isTempThreadId(sid)) return true;
    if (sessionId && sessionId !== sid) {
      rememberVisibleThreadSnapshot(sessionId);
    }
    const requestSeq = ++activeThreadRequestSeqRef.current;
    if (activeThreadAbortRef.current) {
      activeThreadAbortRef.current.abort();
      activeThreadAbortRef.current = null;
    }
    const controller = new AbortController();
    activeThreadAbortRef.current = controller;
    setLoadingSession(true);
    setSessionId(sid);
    setMobileThreadsOpen(false);
    closeThreadMenu();
    const cached = threadDetailCacheRef.current.get(sid);
    if (cached) {
      applyThreadSnapshot(sid, cached);
    } else {
      resetItemDomain();
      setMessages([]);
      setSessionRuntimeState({});
      applyVisibleThreadActiveTurn(createEmptyThreadActiveTurn());
    }
    try {
      const data = normalizeThreadDetailPayload(await fetchJson(
        `/api/thread/${encodeURIComponent(sid)}?view=summary&max_turns=${THREAD_DETAIL_PAGE_SIZE}`,
        { signal: controller.signal },
      ));
      if (requestSeq !== activeThreadRequestSeqRef.current) return false;
      const existingSnapshot = threadDetailCacheRef.current.get(sid) || null;
      const existingActiveTurn = normalizeThreadActiveTurn((existingSnapshot && existingSnapshot.activeTurn) || {});
      const preserveLiveSnapshot = Boolean(
        existingSnapshot
        && (
          isThreadSnapshotLive(sid, existingSnapshot)
          || isCurrentThreadLiveRun({
            sessionId: sid,
            activeRunThreadId,
            sending,
            activeRunId: String(existingActiveTurn.activeRunId || activeRunId || "").trim(),
            activeRunStartedAt: existingActiveTurn.startedAt || activeRunStartedAt || 0,
            hasRunningActivity: Boolean(existingActiveTurn.startedAt || existingActiveTurn.lastLiveProgressAt || existingActiveTurn.liveHeartbeat.updatedAt),
            liveTurnState: existingActiveTurn.liveTurnState || liveTurnState || {},
          })
        ),
      );
      const snapshot = rememberThreadDetail(sid, data, {
        preserveActiveTurn: preserveLiveSnapshot,
        preserveMessages: preserveLiveSnapshot,
        preserveRuntimeState: preserveLiveSnapshot,
      });
      applyThreadSnapshot(sid, snapshot);
      setSessionId(String(data.thread_id || data.session_id || sid));
      const resolvedProjectId = String((data && data.project_id) || options.projectIdOverride || "").trim();
      if (resolvedProjectId) setProjectId(resolvedProjectId);
      updateThreadStatus(String(data.thread_id || data.session_id || sid), String(data.status || "idle"));
      clearUiError();
      if (!options.silentLog) {
        pushLogWithLimit(setLogs, "system", t("log.thread_loaded", { session_id: sid.slice(0, 8) }));
      }
      return true;
    } catch (err) {
      if (err && err.name === "AbortError") return false;
      if (requestSeq !== activeThreadRequestSeqRef.current) return false;
      if (options.silentNotFound && String(err.message || "").includes("404")) return false;
      const nextError = applyUiError(err, t("errors.load_thread_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.load_thread_failed"));
      return false;
    } finally {
      if (requestSeq === activeThreadRequestSeqRef.current) {
        setLoadingSession(false);
        if (activeThreadAbortRef.current === controller) activeThreadAbortRef.current = null;
      }
    }
  }

  async function loadEarlierTurns() {
    const sid = String(sessionId || "").trim();
    if (!sid || isTempThreadId(sid) || loadingEarlierTurns || !messages.length) return;
    const beforeTurnId = String(messages[0].id || "").trim();
    if (!beforeTurnId) return;
    setLoadingEarlierTurns(true);
    try {
      const data = normalizeThreadDetailPayload(await fetchJson(
        `/api/thread/${encodeURIComponent(sid)}?view=summary&max_turns=${THREAD_DETAIL_PAGE_SIZE}&before_turn_id=${encodeURIComponent(beforeTurnId)}`,
      ));
      if (activeSessionIdRef.current !== sid) return;
      const olderMessages = extractSessionMessages(data);
      setMessages((prev) => {
        const existingIds = new Set((Array.isArray(prev) ? prev : []).map((item) => String(item.id || "")));
        const merged = [
          ...olderMessages.filter((item) => !existingIds.has(String(item.id || ""))),
          ...(Array.isArray(prev) ? prev : []),
        ];
        updateThreadSnapshot(sid, (existing) => ({
          ...existing,
          detail: data,
          messages: merged,
          sessionRuntimeState: mergeSessionRuntimeStateSnapshot(sessionRuntimeState || {}, (data && data.agent_state) || {}),
        }));
        return merged;
      });
      setSessionRuntimeState((prev) => mergeSessionRuntimeStateSnapshot(prev || sessionRuntimeState || {}, (data && data.agent_state) || {}));
      updateThreadStatus(String(data.thread_id || data.session_id || sid), String(data.status || "idle"));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.load_thread_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.load_thread_failed"));
    } finally {
      setLoadingEarlierTurns(false);
    }
  }

  async function handleNewSession() {
    if (creatingThread) return;
    try {
      await createSession(projectId);
    } catch (err) {
      const nextError = applyUiError(err, t("errors.new_thread_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.new_thread_failed"));
    }
  }

  async function handleDeleteSession(targetSessionId) {
    const sid = String(targetSessionId || "").trim();
    const targetBusy = String(sid || "").trim() === String(sessionId || "").trim()
      ? currentThreadBusy
      : isThreadSnapshotBusy(sid, threadDetailCacheRef.current.get(sid) || {});
    if (!sid || targetBusy || isTempThreadId(sid)) return;
    const item = sessions.find((entry) => String(entry.session_id || entry.thread_id || "") === sid) || null;
    const title = String((item && item.title) || t("labels.new_thread")).trim() || t("labels.new_thread");
    if (!window.confirm(t("confirm.delete_thread", { title }))) {
      closeThreadMenu();
      return;
    }
    try {
      await fetchJson(`/api/thread/${encodeURIComponent(sid)}`, { method: "DELETE" });
      closeThreadMenu();
      const storageKey = sessionStorageKeyForProject(projectId);
      const remaining = sessions.filter((entry) => String(entry.session_id || entry.thread_id || "") !== sid);
      removeThreadRow(sid);
      if (sid === sessionId) {
        if (remaining.length) {
          const nextId = String(remaining[0].session_id || remaining[0].thread_id || "").trim();
          if (nextId) {
            window.localStorage.setItem(storageKey, nextId);
            await loadSession(nextId, { projectIdOverride: projectId });
          }
        } else {
          window.localStorage.removeItem(storageKey);
          setSessionId("");
          resetItemDomain();
          setSessionRuntimeState({});
          clearLiveRunUi();
        }
      } else {
        const stored = window.localStorage.getItem(storageKey) || "";
        if (stored === sid) {
          if (remaining.length) {
            window.localStorage.setItem(storageKey, String(remaining[0].session_id || remaining[0].thread_id || ""));
          } else {
            window.localStorage.removeItem(storageKey);
          }
        }
      }
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.thread_deleted", { session_id: sid.slice(0, 8) }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.delete_thread_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.delete_thread_failed"));
    }
  }

  function selectThreadRange(targetThreadId) {
    const sid = String(targetThreadId || "").trim();
    if (!sid || isTempThreadId(sid)) return;
    const selectable = sessions.map(threadListItemId).filter((id) => id && !isTempThreadId(id));
    if (!selectable.length) return;
    const anchorCandidate = String(threadSelectionAnchorId || sessionId || "").trim();
    const anchor = selectable.includes(anchorCandidate) ? anchorCandidate : sid;
    const anchorIndex = selectable.indexOf(anchor);
    const targetIndex = selectable.indexOf(sid);
    if (anchorIndex < 0 || targetIndex < 0) {
      setSelectedThreadIds(new Set([sid]));
      setThreadSelectionAnchorId(sid);
      return;
    }
    const start = Math.min(anchorIndex, targetIndex);
    const end = Math.max(anchorIndex, targetIndex);
    setSelectedThreadIds(new Set(selectable.slice(start, end + 1)));
    setThreadSelectionAnchorId(anchor);
  }

  function toggleAllVisibleThreadsSelected() {
    setSelectedThreadIds((prev) => {
      const current = prev instanceof Set ? prev : new Set();
      const selectable = sessions.map(threadListItemId).filter((id) => id && !isTempThreadId(id));
      const allSelected = Boolean(selectable.length && selectable.every((id) => current.has(id)));
      if (allSelected) return new Set();
      return new Set(selectable);
    });
  }

  async function handleBulkDeleteThreads() {
    const selectedIds = [...selectedThreadIds].filter((id) => id && !isTempThreadId(id));
    const selectedHasBusyThread = selectedIds.some((sid) => (
      String(sid || "").trim() === String(sessionId || "").trim()
        ? currentThreadBusy
        : isThreadSnapshotBusy(sid, threadDetailCacheRef.current.get(sid) || {})
    ));
    if (!selectedIds.length || selectedHasBusyThread || bulkDeletingThreads) return;
    if (!window.confirm(t("confirm.delete_threads", { count: selectedIds.length }))) return;
    setBulkDeletingThreads(true);
    try {
      for (const sid of selectedIds) {
        await fetchJson(`/api/thread/${encodeURIComponent(sid)}`, { method: "DELETE" });
      }
      const deleted = new Set(selectedIds);
      selectedIds.forEach((sid) => {
        removeThreadRow(sid);
        threadDetailCacheRef.current.delete(threadCacheKey(sid));
      });
      const storageKey = sessionStorageKeyForProject(projectId);
      const remaining = sessions.filter((entry) => !deleted.has(threadListItemId(entry)));
      const deletedCurrentThread = deleted.has(String(sessionId || "").trim());
      if (deletedCurrentThread) {
        if (remaining.length) {
          const nextId = threadListItemId(remaining[0]);
          if (nextId) {
            window.localStorage.setItem(storageKey, nextId);
            await loadSession(nextId, { projectIdOverride: projectId });
          }
        } else {
          window.localStorage.removeItem(storageKey);
          setSessionId("");
          resetItemDomain();
          setSessionRuntimeState({});
          clearLiveRunUi();
        }
      } else {
        const stored = window.localStorage.getItem(storageKey) || "";
        if (deleted.has(stored)) {
          if (remaining.length) window.localStorage.setItem(storageKey, threadListItemId(remaining[0]));
          else window.localStorage.removeItem(storageKey);
        }
      }
      setSelectedThreadIds(new Set());
      setThreadSelectionAnchorId("");
      closeThreadMenu();
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.threads_deleted", { count: selectedIds.length }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.delete_threads_failed"));
      pushLogWithLimit(setLogs, "error", nextError.summary || t("errors.delete_threads_failed"));
    } finally {
      setBulkDeletingThreads(false);
    }
  }

  async function handleRenameSession() {
    const sid = String((renameDialog && renameDialog.sessionId) || "").trim();
    if (!sid || renamingThread) return;
    setRenamingThread(true);
    setRenameError("");
    try {
      const payload = await fetchJson(`/api/session/${encodeURIComponent(sid)}/title`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: String(renameDraft || "").trim().slice(0, 120) }),
      });
      const displayTitle = String(payload.display_title || payload.title || t("labels.new_thread")).trim() || t("labels.new_thread");
      const customTitle = String(payload.title || "").trim();
      setSessions((prev) => (Array.isArray(prev) ? prev : []).map((entry) => (
        String(entry.session_id || entry.thread_id || "") === sid
          ? {
              ...entry,
              title: displayTitle,
              display_title: displayTitle,
              has_custom_title: Boolean(payload.has_custom_title),
              updated_at: new Date().toISOString(),
            }
          : entry
      )));
      updateThreadSnapshot(sid, (existing) => ({
        ...existing,
        detail: {
          ...((existing && existing.detail) || {}),
          thread_id: sid,
          session_id: sid,
          title: customTitle,
          display_title: displayTitle,
          has_custom_title: Boolean(payload.has_custom_title),
        },
      }));
      closeRenameDialog();
      pushLogWithLimit(
        setLogs,
        "system",
        Boolean(payload.has_custom_title)
          ? t("log.thread_renamed", { title: displayTitle })
          : t("log.thread_title_reset", { title: displayTitle }),
      );
    } catch (err) {
      const nextError = normalizeUiError(uiLocale, err, t("errors.rename_thread_failed"));
      setRenameError(nextError.summary);
    } finally {
      setRenamingThread(false);
    }
  }

  async function handleDeleteProject(targetProjectId) {
    const pid = String(targetProjectId || "").trim();
    if (!pid || anyThreadBusy) return;
    const item = projects.find((entry) => String(entry.project_id || "") === pid) || null;
    if (!item || item.is_default) {
      closeProjectMenu();
      return;
    }
    const title = String(item.title || item.project_id || pid).trim() || pid;
    if (!window.confirm(t("confirm.delete_project", { title }))) {
      closeProjectMenu();
      return;
    }
    try {
      const payload = await fetchJson(`/api/projects/${encodeURIComponent(pid)}`, { method: "DELETE" });
      closeProjectMenu();
      window.localStorage.removeItem(sessionStorageKeyForProject(pid));
      const deletingCurrentProject = pid === String(projectId || "").trim();
      const list = await refreshProjects();
      if (deletingCurrentProject) {
        window.localStorage.removeItem(PROJECT_STORAGE_KEY);
        setSessionId("");
        resetItemDomain();
        setSessionRuntimeState({});
        setLogs([]);
        clearLiveRunUi();
        const nextProjectId =
          String(((list || []).find((entry) => String(entry.project_id || "").trim() !== pid) || {}).project_id || "").trim() ||
          String((((list || [])[0] || {}).project_id) || "").trim();
        if (nextProjectId) {
          await selectProject(nextProjectId, { silentNotFound: true });
        } else {
          setProjectId("");
          setSessions([]);
          await refreshRuntimeStatus("", { background: true });
        }
      }
      clearUiError();
      pushLogWithLimit(
        setLogs,
        "system",
        t("log.project_deleted", {
          title,
          deleted_session_count: Number((payload && payload.deleted_session_count) || 0) || 0,
        }),
      );
    } catch (err) {
      const nextError = applyUiError(err, t("errors.delete_project_failed"));
      pushLogWithLimit(setLogs, "error", t("log.delete_project_failed", { summary: nextError.summary }));
    }
  }

  function createPendingUploadItem(rawFile, index) {
    const file = ensureNamedUploadFile(rawFile, index);
    const fileName = String((file && file.name) || "").trim() || `upload-${Date.now()}-${index + 1}.bin`;
    return {
      id: `pending-${Date.now()}-${index}-${Math.random().toString(36).slice(2, 8)}`,
      name: fileName,
      mime: String((file && file.type) || ""),
      size: Number((file && file.size) || 0),
      kind: "other",
      uploading: true,
      uploadFailed: false,
      error: "",
    };
  }

  async function uploadFiles(files, pendingItems = []) {
    const prepared = Array.from(files || []).map((rawFile, index) => {
      const file = ensureNamedUploadFile(rawFile, index);
      const pending = pendingItems[index] || createPendingUploadItem(file, index);
      return { file, pending, index };
    });
    const uploaded = [];
    const failed = [];
    let cursor = 0;

    async function uploadOne(entry) {
      const form = new FormData();
      const fileName = String((entry.file && entry.file.name) || entry.pending.name || "").trim() || `upload-${Date.now()}-${entry.index + 1}.bin`;
      form.append("file", entry.file, fileName);
      try {
        const payload = await fetchJson("/api/upload", { method: "POST", body: form });
        uploaded.push(payload);
        setPendingUploads((prev) =>
          prev.map((item) => (item.id === entry.pending.id ? payload : item)),
        );
      } catch (err) {
        const normalized = normalizeUiError(uiLocale, err, t("errors.upload_failed"));
        failed.push({ fileName, error: normalized });
        setPendingUploads((prev) =>
          prev.map((item) => (
            item.id === entry.pending.id
              ? { ...item, uploading: false, uploadFailed: true, error: normalized.summary || t("errors.upload_failed") }
              : item
          )),
        );
      }
    }

    async function worker() {
      while (cursor < prepared.length) {
        const entry = prepared[cursor];
        cursor += 1;
        await uploadOne(entry);
      }
    }

    const workerCount = Math.min(UPLOAD_CONCURRENCY, prepared.length);
    await Promise.all(Array.from({ length: workerCount }, () => worker()));
    return { uploaded, failed };
  }

  async function processSelectedFiles(files, options = {}) {
    const nextFiles = Array.from(files || []);
    if (!nextFiles.length) return;
    const pendingItems = nextFiles.map((file, index) => createPendingUploadItem(file, index));
    setPendingUploads((prev) => [...prev, ...pendingItems]);
    const { uploaded, failed } = await uploadFiles(nextFiles, pendingItems);
    if (failed.length) {
      const summary = failed.length === nextFiles.length
        ? t("errors.upload_failed")
        : t("errors.upload_partial_failed", { failed: failed.length, total: nextFiles.length });
      setUiError(normalizeUiError(uiLocale, { detail: summary }, summary));
      pushLogWithLimit(setLogs, "error", summary);
    } else {
      clearUiError();
    }
    if (uploaded.length) {
      const sourceLabel = String(options.source || "").trim();
      pushLogWithLimit(
        setLogs,
        "system",
        sourceLabel === "paste"
          ? t("log.attachments_pasted", { count: uploaded.length })
          : t("log.attachments_added", { count: uploaded.length }),
      );
    }
  }

  async function handleSelectFiles(event) {
    const files = Array.from(event.currentTarget.files || []);
    if (!files.length) return;
    try {
      await processSelectedFiles(files);
    } finally {
      event.currentTarget.value = "";
    }
  }

  function handleComposerDragEnter(event) {
    if (!dragEventHasFiles(event)) return;
    event.preventDefault();
    composerDragDepthRef.current += 1;
    setComposerDragActive(true);
  }

  function handleComposerDragOver(event) {
    if (!dragEventHasFiles(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    if (!composerDragActive) setComposerDragActive(true);
  }

  function handleComposerDragLeave(event) {
    if (!dragEventHasFiles(event)) return;
    event.preventDefault();
    composerDragDepthRef.current = Math.max(0, composerDragDepthRef.current - 1);
    if (composerDragDepthRef.current === 0) {
      setComposerDragActive(false);
    }
  }

  async function handleComposerDrop(event) {
    if (!dragEventHasFiles(event)) return;
    event.preventDefault();
    composerDragDepthRef.current = 0;
    setComposerDragActive(false);
    const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
    if (!files.length) return;
    await processSelectedFiles(files);
  }

  async function handleComposerPaste(event) {
    const files = clipboardEventFiles(event);
    if (!files.length) return;
    event.preventDefault();
    await processSelectedFiles(files, { source: "paste" });
  }

  function removeUpload(fileId) {
    setPendingUploads((prev) => prev.filter((item) => item.id !== fileId));
  }

  async function handleStopRun() {
    const runId = String(activeRunId || "").trim();
    if (!runId || !currentThreadBusy || stoppingRun || String(activeRunThreadId || "").trim() !== String(sessionId || "").trim()) return;
    setStoppingRun(true);
    try {
      const payload = await fetchJson(`/api/chat/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
      });
      const detail = Boolean(payload.cancelled)
        ? t("log.stop_requested")
        : t("log.stop_no_active_run");
      pushLogWithLimit(setLogs, "system", detail);
    } catch (err) {
      const nextError = applyUiError(err, t("errors.stop_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.stop_failed"));
      setStoppingRun(false);
    }
  }

  async function handleLoadTask(task) {
    const normalized = normalizeTaskDescriptor(task);
    if (!normalized.task_id || loadingTaskId || currentThreadBusy) return;
    setLoadingTaskId(normalized.task_id);
    setDrawerView("");
    try {
      await handleSend(t("tasks.load_prompt"), undefined, { taskId: normalized.task_id });
    } catch (err) {
      applyUiError(err, t("errors.load_task_failed"));
    } finally {
      setLoadingTaskId("");
    }
  }

  async function handleSummarizeCurrentTask() {
    if (currentThreadBusy) return;
    setDrawerView("");
    await handleSend(t("tasks.summarize_prompt"));
  }

  async function handleSend(overrideText, userInputResponse) {
    const options = arguments[2] && typeof arguments[2] === "object" ? arguments[2] : {};
    const messageText = String(overrideText != null ? overrideText : draft).trim();
    if (!messageText) return;
    const explicitUserInputResponse = userInputResponse && typeof userInputResponse === "object"
      ? userInputResponse
      : {};
    const storedPendingInput = sessionRuntimeState.pending_user_input
      && typeof sessionRuntimeState.pending_user_input === "object"
      ? sessionRuntimeState.pending_user_input
      : {};
    const structuredUserInputResponse = Object.keys(explicitUserInputResponse).length
      ? explicitUserInputResponse
      : (String(storedPendingInput.type || "") === "request_user_input"
        ? {
            type: "request_user_input",
            tool_call_id: String(storedPendingInput.tool_call_id || ""),
            response: messageText,
          }
        : {});
    const isTurnResume = ["command_execution", "request_user_input"]
      .includes(String(structuredUserInputResponse.type || ""));
    const pendingResumeStateOption = options.pendingResumeState && typeof options.pendingResumeState === "object"
      ? options.pendingResumeState
      : {};
    const resumePendingState = isTurnResume
      ? {
          turn_status: String(pendingResumeStateOption.turn_status || sessionRuntimeState.turn_status || "needs_user_input"),
          pending_user_input: {
            ...((sessionRuntimeState.pending_user_input && typeof sessionRuntimeState.pending_user_input === "object") ? sessionRuntimeState.pending_user_input : {}),
            ...((pendingResumeStateOption.pending_user_input && typeof pendingResumeStateOption.pending_user_input === "object") ? pendingResumeStateOption.pending_user_input : {}),
          },
          pending_approval: {
            ...((sessionRuntimeState.pending_approval && typeof sessionRuntimeState.pending_approval === "object") ? sessionRuntimeState.pending_approval : {}),
            ...((pendingResumeStateOption.pending_approval && typeof pendingResumeStateOption.pending_approval === "object") ? pendingResumeStateOption.pending_approval : {}),
          },
        }
      : null;
    if (currentThreadBusy && !isTurnResume) {
      if (!canQueueGuidance) return;
      if (pendingUploads.some((item) => item && (item.uploading || (!item.uploadFailed && item.id)))) {
        const summary = t("errors.steer_attachments_not_supported");
        setUiError(normalizeUiError(uiLocale, { detail: summary }, summary));
        return;
      }
      const steerId = `steer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const steerOwnerThreadId = String(sessionId || "").trim();
      const queuedGuidance = {
        id: steerId,
        message: messageText,
        status: "queued",
        queuedAt: Date.now(),
      };
      updateThreadPendingGuidance(steerOwnerThreadId, (prev) => [...prev, queuedGuidance]);
      if (overrideText == null) setDraft("");
      clearUiError();
      try {
        const queued = await fetchJson(`/api/chat/runs/${encodeURIComponent(String(activeRunId || ""))}/steer`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: messageText, client_steer_id: steerId }),
        });
        const queuedAt = normalizeActivityTimestamp(queued.queued_at || 0) || Date.now();
        updateThreadPendingGuidance(steerOwnerThreadId, (prev) => prev.map((item) => (
          String(item.id || "") === steerId
            ? { ...item, status: "queued", queuedAt }
            : item
        )));
      } catch (err) {
        updateThreadPendingGuidance(
          steerOwnerThreadId,
          (prev) => prev.filter((item) => String(item.id || "") !== steerId),
        );
        if (overrideText == null && String(activeSessionIdRef.current || "").trim() === steerOwnerThreadId) {
          setDraft((current) => String(current || "").trim() ? current : messageText);
        }
        applyUiError(err, t("errors.steer_failed"));
      }
      return;
    }
    const slashCommand = normalizeSlashCommandText(messageText);
    if (slashCommand) {
      setDraft("");
      if (slashCommand === "/status") {
        await handleStatusCommand();
      } else if (slashCommand === "/compact") {
        await handleCompactCommand();
      }
      return;
    }
    const clientSubmittedAtMs = Date.now();
    const uploadsInFlight = pendingUploads.some((item) => item && item.uploading);
    if (uploadsInFlight) {
      const summary = t("errors.upload_in_progress");
      setUiError(normalizeUiError(uiLocale, { detail: summary }, summary));
      pushLogWithLimit(setLogs, "error", summary);
      return;
    }
    const readyAttachmentIds = pendingUploads
      .filter((item) => item && !item.uploadFailed && !item.uploading && !String(item.id || "").startsWith("pending-"))
      .map((item) => item.id);

    setContextMeterOpen(false);
    setStoppingRun(false);
    setActiveRunId("");
    setActiveRunStartedAt(clientSubmittedAtMs);
    clearUiError();
    setToolTimeline([]);
    setLiveToolTimeline([]);
    setLiveTurnState({});
    setLiveEvidence({});
    setLiveRunLogs([]);
    setStageTimeline([]);

    let sid = sessionId;
    let pendingMessage = null;
    let runOwnerThreadId = "";
    let ownerThreadVisible = () => false;
    let updateOwnerMessages = null;
    let updateOwnerSessionRuntimeState = null;
    let updateOwnerActiveTurn = null;
    let lockedRunOwnerThreadId = "";
    let cancelAssistantDeltaFlush = () => {};
    let uiFinalized = false;
    try {
      if (isTempThreadId(sid) && pendingThreadCreationPromiseRef.current) {
        sid = await pendingThreadCreationPromiseRef.current;
      }
      if (!sid) sid = await createSession(projectId);
      runOwnerThreadId = String(sid || "").trim();
      ownerThreadVisible = () => String(activeSessionIdRef.current || "").trim() === runOwnerThreadId;
      const ownerSnapshot = threadDetailCacheRef.current.get(runOwnerThreadId);
      const ownerBusy = ownerThreadVisible()
        ? isThreadSnapshotBusy(runOwnerThreadId, { activeTurn: visibleThreadActiveTurnSnapshot(), messages })
        : isThreadSnapshotBusy(runOwnerThreadId, ownerSnapshot || {});
      if (ownerBusy && !isTurnResume) return;
      if (isTurnResume && activeSendThreadIdsRef.current.has(runOwnerThreadId)) {
        const unlockDeadline = Date.now() + 3000;
        while (activeSendThreadIdsRef.current.has(runOwnerThreadId) && Date.now() < unlockDeadline) {
          await new Promise((resolve) => window.setTimeout(resolve, 25));
        }
      }
      if (activeSendThreadIdsRef.current.has(runOwnerThreadId)) return;
      activeSendThreadIdsRef.current.add(runOwnerThreadId);
      lockedRunOwnerThreadId = runOwnerThreadId;
      markThreadRunIndicator(runOwnerThreadId, "running");
      if (ownerThreadVisible()) {
        setSending(true);
        setActiveRunThreadId(runOwnerThreadId);
      }

      const userMessage = isTurnResume ? null : createMessage("user", messageText);
      const runModelName = String(
        chatSettings.model ||
        (activeProviderProfile && activeProviderProfile.default_model) ||
        (health && health.default_model) ||
        "",
      ).trim();
      pendingMessage = createMessage("assistant", t("labels.processing"), {
        pending: true,
        activity: {
          status: "background_running",
          started_at: clientSubmittedAtMs,
          turn_started_at: clientSubmittedAtMs,
          live_model: runModelName,
          trace_events: [],
        },
      });
      const nextInitialRuntimeState = {
        goal: isTurnResume ? String(sessionRuntimeState.goal || messageText) : messageText,
        permission_profile: normalizePermissionProfile(chatSettings.permission_profile || "auto"),
        turn_status: "running",
        plan: isTurnResume && Array.isArray(sessionRuntimeState.plan) ? sessionRuntimeState.plan : [],
        pending_user_input: {},
        pending_approval: {},
      };
      const initialLiveHeartbeat = normalizeLiveHeartbeat({
        status: "background_running",
        action: t("activity.status.preparing_request"),
        recentEvent: t("run.live_agent.preparing"),
        model: runModelName,
        updatedAt: clientSubmittedAtMs,
        source: "runtime",
      });
      const initialActiveTurn = (existingActiveTurn) => {
        const existingTurn = normalizeThreadActiveTurn(existingActiveTurn);
        return normalizeThreadActiveTurn({
          ...createEmptyThreadActiveTurn(),
          sending: true,
          activeRunThreadId: runOwnerThreadId,
          startedAt: clientSubmittedAtMs,
          lastLiveProgressAt: clientSubmittedAtMs,
          liveHeartbeat: initialLiveHeartbeat,
          lastResponse: existingTurn.lastResponse || lastResponse || null,
          liveTurnState: nextInitialRuntimeState,
          liveEvidence: { status: "not_needed" },
        });
      };
      updateThreadSnapshot(runOwnerThreadId, (existing) => ({
        ...existing,
        messages: appendMessagesOnceById(
          Array.isArray(existing.messages) && existing.messages.length
            ? existing.messages
            : (ownerThreadVisible() ? messages : []),
          [userMessage, pendingMessage].filter(Boolean),
        ),
        sessionRuntimeState: mergeSessionRuntimeStateSnapshot(existing.sessionRuntimeState || {}, nextInitialRuntimeState),
        activeTurn: initialActiveTurn(existing.activeTurn),
      }));
      if (ownerThreadVisible()) {
        setMessages((prev) => (
          ownerThreadVisible()
            ? appendMessagesOnceById(prev, [userMessage, pendingMessage].filter(Boolean))
            : prev
        ));
        setLiveTurnState(nextInitialRuntimeState);
        setLiveEvidence({ status: "not_needed" });
        setLastLiveProgressAt(clientSubmittedAtMs);
        setLiveHeartbeat(initialLiveHeartbeat);
      }
      if (overrideText == null) setDraft("");

      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sid,
          project_id: projectId,
          task_id: String(options.taskId || "").trim() || null,
          message: messageText,
          client_message_id: String((userMessage && userMessage.id) || ""),
          client_submitted_at_ms: clientSubmittedAtMs,
          attachment_ids: readyAttachmentIds,
          user_input_response: structuredUserInputResponse,
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
            uiLocale,
            payload && Object.prototype.hasOwnProperty.call(payload, "detail") ? payload.detail : payload,
            t("errors.request_failed"),
            { status_code: res.status },
          ),
        );
      }
      if (!res.body) {
        throw errorWithUiError(normalizeUiError(uiLocale, { detail: "stream body unavailable" }, t("errors.request_failed")));
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload = null;
      let assistantMessageStarted = false;
      let modelRequestStarted = false;
      let assistantText = "";
      let assistantDeltaBuffer = "";
      let assistantDeltaItemId = "";
      let assistantDeltaFlushTimer = 0;
      let latestThreadId = String(sid || "");
      let latestRunSnapshot = {};
      let latestEvidenceState = { status: "not_needed" };
      let latestToolEvents = [];
      let latestTokenUsage = {};
      let latestSessionTokenTotals = {};
      let latestGlobalTokenTotals = {};
      let completedTurnPayload = null;
      let latestActivity = normalizeMessageActivity(pendingMessage.activity);
      ownerThreadVisible = () => String(activeSessionIdRef.current || "").trim() === runOwnerThreadId;
      updateOwnerMessages = (value) => {
        if (ownerThreadVisible()) {
          setMessages((prev) => {
            const nextMessages = resolveStateValue(Array.isArray(prev) ? prev : [], value);
            updateThreadSnapshot(runOwnerThreadId, (existing) => ({ ...existing, messages: nextMessages }));
            return nextMessages;
          });
          return;
        }
        updateThreadSnapshot(runOwnerThreadId, (existing) => ({
          ...existing,
          messages: resolveStateValue(Array.isArray(existing.messages) ? existing.messages : [], value),
        }));
      };
      updateOwnerSessionRuntimeState = (value) => {
        if (ownerThreadVisible()) {
          setSessionRuntimeState((prev) => {
            const nextState = resolveStateValue(prev && typeof prev === "object" ? prev : {}, value);
            updateThreadSnapshot(runOwnerThreadId, (existing) => ({ ...existing, sessionRuntimeState: nextState }));
            return nextState;
          });
          return;
        }
        updateThreadSnapshot(runOwnerThreadId, (existing) => ({
          ...existing,
          sessionRuntimeState: resolveStateValue(existing.sessionRuntimeState && typeof existing.sessionRuntimeState === "object" ? existing.sessionRuntimeState : {}, value),
        }));
      };
      updateOwnerActiveTurn = (value) => {
        const currentVisible = visibleThreadActiveTurnSnapshot();
        const cachedSnapshot = threadDetailCacheRef.current.get(runOwnerThreadId);
        const base = normalizeThreadActiveTurn(
          (cachedSnapshot && cachedSnapshot.activeTurn)
          || (ownerThreadVisible() ? currentVisible : createEmptyThreadActiveTurn()),
        );
        const resolvedCandidate = resolveStateValue(base, value);
        const resolvedTurn = resolvedCandidate && typeof resolvedCandidate === "object" ? resolvedCandidate : base;
        const resolvedActiveRunThreadId = Object.prototype.hasOwnProperty.call(resolvedTurn, "activeRunThreadId")
          ? String(resolvedTurn.activeRunThreadId || "")
          : runOwnerThreadId;
        const resolvedStartedAt = Object.prototype.hasOwnProperty.call(resolvedTurn, "startedAt")
          ? (Number(resolvedTurn.startedAt || 0) || 0)
          : (Number(base.startedAt || clientSubmittedAtMs || 0) || 0);
        const nextTurn = normalizeThreadActiveTurn({
          ...resolvedTurn,
          activeRunThreadId: resolvedActiveRunThreadId,
          startedAt: resolvedStartedAt,
        });
        updateThreadSnapshot(runOwnerThreadId, (existing) => ({ ...existing, activeTurn: nextTurn }));
        if (!ownerThreadVisible()) return;
        setSending(nextTurn.sending);
        setLastResponse(nextTurn.lastResponse);
        setToolTimeline(nextTurn.toolTimeline);
        setLiveToolTimeline(nextTurn.liveToolTimeline);
        setLiveTurnState(nextTurn.liveTurnState);
        setLiveEvidence(nextTurn.liveEvidence);
        setLiveRunLogs(nextTurn.liveRunLogs);
        setStageTimeline(nextTurn.stageTimeline);
        setPendingGuidance(nextTurn.pendingGuidance);
        setActiveRunId(nextTurn.activeRunId);
        setActiveRunThreadId(nextTurn.activeRunThreadId);
        setActiveRunStartedAt(nextTurn.startedAt);
        setLastLiveProgressAt(nextTurn.lastLiveProgressAt);
        setLiveHeartbeat(nextTurn.liveHeartbeat);
        setStoppingRun(nextTurn.stoppingRun);
      };
      const reconcileCompletedThreadMessages = async (threadId) => {
        const ownerId = String(threadId || runOwnerThreadId || "").trim();
        if (!ownerId || isTempThreadId(ownerId)) return false;
        try {
          const detail = normalizeThreadDetailPayload(await fetchJson(
            `/api/thread/${encodeURIComponent(ownerId)}?view=summary&max_turns=${THREAD_DETAIL_PAGE_SIZE}`,
          ));
          const authoritativeMessages = extractSessionMessages(detail);
          if (!authoritativeMessages.length) return false;
          updateOwnerMessages((prev) => (
            mergeAuthoritativeThreadMessages(authoritativeMessages, prev, {
              optimisticMessageIds: userMessage ? [String(userMessage.id || "")] : [],
            })
          ));
          updateThreadSnapshot(ownerId, (existing) => ({ ...existing, detail }));
          return true;
        } catch {
          return false;
        }
      };
      const updateOwnerLiveHeartbeat = (value) => {
        const heartbeatAt = Date.now();
        updateOwnerActiveTurn((prev) => {
          const base = normalizeLiveHeartbeat(prev.liveHeartbeat || {});
          const nextPatch = typeof value === "function" ? value(base) : value;
          const normalizedPatch = nextPatch && typeof nextPatch === "object" ? nextPatch : {};
          const updatedAt = normalizeActivityTimestamp(
            normalizedPatch.updatedAt
            || normalizedPatch.updated_at
            || heartbeatAt,
          ) || heartbeatAt;
          return {
            ...prev,
            lastLiveProgressAt: updatedAt,
            liveHeartbeat: normalizeLiveHeartbeat({
              ...base,
              ...normalizedPatch,
              updatedAt,
            }),
          };
        });
      };
      const markOwnerConnectionHeartbeat = (value) => {
        const connectionAt = normalizeActivityTimestamp(value || 0) || Date.now();
        updateOwnerActiveTurn((prev) => ({
          ...prev,
          liveHeartbeat: normalizeLiveHeartbeat({
            ...normalizeLiveHeartbeat(prev.liveHeartbeat || {}),
            connectionAt,
          }),
        }));
      };
      const syncHeartbeatFromTrace = (trace) => {
        const item = trace && typeof trace === "object" ? trace : {};
        const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
        const traceType = String(item.type || "").trim();
        const detail = String(item.detail || item.title || payload.summary || "").trim();
        const target = toolCallTargetFromSource(payload) || detail;
        const tool = String(
          payload.tool_name
          || payload.tool
          || payload.name
          || ((payload.raw_tool_call || {}).name)
          || "",
        ).trim();
        const command = executionProgressCommandFromSource(payload);
        const agentToolAction = (status) => formatLiveAgentToolActionText(uiLocale, {
          tool,
          type: traceType,
          status,
          target,
          detail,
          command,
        });
        if (traceType === "run.finished" || traceType === "answer.done" || traceType === "answer.finished") {
          return;
        }
        if (traceType === "run.failed") {
          updateOwnerLiveHeartbeat({
            status: "failed",
            tool,
            command,
            action: detail || t("activity.failed"),
            recentEvent: detail || t("activity.failed"),
            source: "runtime",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "llm.started") {
          const traceModel = String(payload.effective_model || payload.model || runModelName || "").trim();
          updateOwnerLiveHeartbeat({
            status: "waiting_model",
            tool,
            model: traceModel,
            command,
            action: t("activity.status.waiting_model"),
            recentEvent: traceModel
              ? t("run.live_agent.model_detail", { detail: traceModel })
              : t("run.live_agent.model"),
            source: "model",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "action.blocked") {
          updateOwnerLiveHeartbeat({
            status: "blocked",
            tool,
            command,
            action: detail || t("activity.blocked"),
            recentEvent: detail || t("activity.blocked"),
            source: "validator",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "tool.failed") {
          updateOwnerLiveHeartbeat({
            status: "tooling",
            tool,
            command,
            action: detail || t("activity.failed"),
            recentEvent: detail || t("activity.failed"),
            source: "tool",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "llm.failed") {
          updateOwnerLiveHeartbeat({
            status: "background_running",
            tool,
            command,
            action: detail || t("activity.failed"),
            recentEvent: detail || t("activity.failed"),
            source: "model",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "action.validating") {
          const action = agentToolAction("validating");
          updateOwnerLiveHeartbeat({
            status: "validating",
            tool,
            command,
            action: action || detail || t("run.progress.waiting_tool"),
            recentEvent: detail || t("run.progress.recent_event_waiting_tool"),
            source: "validator",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "tool.started" || traceType === "action.allowed" || traceType === "action.detected" || traceType === "tool.call_detected") {
          const nextStatus = traceType === "tool.started" ? "running" : "waiting_tool";
          const action = agentToolAction(nextStatus);
          updateOwnerLiveHeartbeat({
            status: nextStatus,
            tool,
            command,
            action: action || detail || command || t("run.progress.waiting_tool"),
            recentEvent: detail || command || t("run.progress.recent_event_waiting_tool"),
            source: "tool",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "tool.finished") {
          const action = agentToolAction("waiting_model");
          updateOwnerLiveHeartbeat({
            status: "waiting_model",
            tool,
            command,
            action: action || detail || t("activity.live.tool_finished", { tool: tool || "tool" }),
            recentEvent: detail || t("run.progress.recent_event_waiting_model"),
            source: "tool",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
        if (traceType === "observation.returned" || traceType === "llm.finished") {
          const action = traceType === "observation.returned" ? agentToolAction("waiting_model") : "";
          updateOwnerLiveHeartbeat({
            status: "waiting_model",
            tool,
            command,
            action: action || detail || t("run.progress.waiting_model"),
            recentEvent: detail || t("run.progress.recent_event_waiting_model"),
            source: "model",
            updatedAt: item.timestamp || Date.now(),
          });
          return;
        }
      };
      const syncHeartbeatFromStreamItem = (item, eventName = "") => {
        const entry = item && typeof item === "object" ? item : {};
        const itemType = String(entry.type || "").trim();
        const tool = String(entry.tool || entry.name || "").trim();
        const command = executionProgressCommandFromSource(entry);
        const detail = String(entry.detail || entry.summary || entry.title || entry.text || "").trim();
        const isCompleted = String(eventName || "").trim() === "item/completed";
        const toolAction = formatLiveAgentToolActionText(uiLocale, {
          tool,
          type: itemType,
          status: isCompleted ? normalizeProgressStatus(entry.status || "completed") : normalizeProgressStatus(entry.status || "running"),
          target: detail,
          detail,
          command,
        });
        if (itemType === "agentMessage") {
          const agentMessageCompleted = isCompleted || normalizeProgressStatus(entry.status) === "completed";
          if (agentMessageCompleted) return;
          updateOwnerLiveHeartbeat({
            status: "waiting_model",
            action: t("activity.live.answer_streaming"),
            recentEvent: detail || t("activity.live.answer_streaming"),
            source: "model",
          });
          return;
        }
        if (itemType === "contextCompaction") {
          updateOwnerLiveHeartbeat({
            status: isCompleted ? "background_running" : "running",
            action: detail || t(isCompleted ? "activity.live.context_compacted" : "activity.live.context_compacting"),
            recentEvent: detail || t(isCompleted ? "activity.live.context_compacted" : "activity.live.context_compacting"),
            source: "runtime",
          });
          return;
        }
        if (itemType === "userInputRequest") {
          updateOwnerLiveHeartbeat({
            status: "blocked",
            action: detail || t("labels.pending_input"),
            recentEvent: detail || t("labels.pending_input"),
            source: "runtime",
          });
          return;
        }
        if (!["toolCall", "commandExecution", "fileChange", "imageView"].includes(itemType) && !tool) return;
        updateOwnerLiveHeartbeat({
          status: isCompleted ? normalizeProgressStatus(entry.status || "completed") : normalizeProgressStatus(entry.status || "running"),
          tool,
          command,
          action: toolAction || detail || command || tool || t("run.progress.background_running"),
          recentEvent: detail || command || tool || t("run.progress.recent_event_background"),
          source: "tool",
        });
      };

      const replacePendingText = (text, options = {}) => {
        if (options.onlyWhileWaiting && assistantMessageStarted) return;
        if (options.skipAfterModelStarted && modelRequestStarted) return;
        updateOwnerMessages((prev) =>
          prev.map((item) => (item.id === pendingMessage.id ? { ...item, text } : item)),
        );
      };
      const patchPendingActivity = (updater) => {
        updateOwnerMessages((prev) =>
          prev.map((item) => {
            if (!pendingMessage || item.id !== pendingMessage.id) return item;
            const nextActivity = typeof updater === "function"
              ? normalizeMessageActivity(updater(item.activity))
              : normalizeMessageActivity(updater);
            latestActivity = nextActivity;
            return { ...item, activity: nextActivity };
          }),
        );
      };
      const flushAssistantDelta = () => {
        if (assistantDeltaFlushTimer) {
          window.clearTimeout(assistantDeltaFlushTimer);
          assistantDeltaFlushTimer = 0;
        }
        const delta = assistantDeltaBuffer;
        const itemId = assistantDeltaItemId;
        assistantDeltaBuffer = "";
        assistantDeltaItemId = "";
        if (!delta) return;
        assistantText += delta;
        const progressAt = Date.now();
        latestActivity = mergeActivityState(latestActivity, {
          model_draft: assistantText,
        });
        updateOwnerMessages((prev) => prev.map((item) => (
          pendingMessage && item.id === pendingMessage.id
            ? {
                ...item,
                text: assistantText,
                activity: mergeActivityState(item.activity, { model_draft: assistantText }),
              }
            : item
        )));
        updateOwnerActiveTurn((prev) => ({
          ...prev,
          lastLiveProgressAt: progressAt,
          liveHeartbeat: normalizeLiveHeartbeat({
            ...normalizeLiveHeartbeat(prev.liveHeartbeat || {}),
            status: "waiting_model",
            action: t("activity.live.answer_streaming"),
            recentEvent: t("activity.live.answer_streaming"),
            source: "model",
            updatedAt: progressAt,
          }),
        }));
        if (ownerThreadVisible() && itemId) {
          dispatch({ type: "items/agentDelta", itemId, delta, status: "inProgress" });
        }
      };
      const queueAssistantDelta = (delta, itemId = "") => {
        const text = String(delta || "");
        if (!text) return;
        assistantDeltaBuffer += text;
        assistantDeltaItemId = String(itemId || assistantDeltaItemId || "");
        if (assistantDeltaFlushTimer) return;
        assistantDeltaFlushTimer = window.setTimeout(
          flushAssistantDelta,
          STREAM_UI_FLUSH_INTERVAL_MS,
        );
      };
      cancelAssistantDeltaFlush = () => {
        if (assistantDeltaFlushTimer) window.clearTimeout(assistantDeltaFlushTimer);
        assistantDeltaFlushTimer = 0;
        assistantDeltaBuffer = "";
        assistantDeltaItemId = "";
      };
      const completePendingText = (text) => {
        updateOwnerMessages((prev) =>
          prev.map((item) => (
            item.id === pendingMessage.id
              ? createMessage(item.role === "runtime" ? "runtime" : "assistant", text, {
                  id: item.id,
                  activity: item.activity,
                  answerBundle: item.answerBundle,
                  runArtifact: item.runArtifact,
                  runActivityLoading: item.runActivityLoading,
                  runActivityError: item.runActivityError,
                  runDebugLoading: item.runDebugLoading,
                  runDebugError: item.runDebugError,
                })
              : item
          )),
        );
      };
      const markPendingAsRuntimeNotice = (text) => {
        const noticeText = String(text || t("labels.pending_input"));
        updateOwnerMessages((prev) =>
          prev.map((item) => (
            item.id === pendingMessage.id
              ? createMessage("runtime", noticeText, {
                  id: item.id,
                  activity: item.activity,
                  answerBundle: item.answerBundle,
                  runArtifact: item.runArtifact,
                  runActivityLoading: item.runActivityLoading,
                  runActivityError: item.runActivityError,
                  runDebugLoading: item.runDebugLoading,
                  runDebugError: item.runDebugError,
                })
              : item
          )),
        );
        pendingMessage = { ...pendingMessage, role: "runtime", text: noticeText };
      };
      const completeCurrentAssistantSegment = (segment) => {
        flushAssistantDelta();
        const item = segment && typeof segment === "object" ? segment : {};
        const currentId = String((pendingMessage && pendingMessage.id) || "");
        if (!currentId) return;
        const segmentId = String(item.id || currentId);
        const segmentText = String(item.text || assistantText || "").trim();
        const completedAt = normalizeActivityTimestamp(item.completed_at || 0) || Date.now();
        updateOwnerMessages((prev) => {
          const previous = Array.isArray(prev) ? prev : [];
          if (!segmentText) {
            return previous.filter((message) => String(message.id || "") !== currentId);
          }
          return previous.map((message) => {
            if (String(message.id || "") !== currentId) return message;
            const previousActivity = normalizeMessageActivity(message.activity || latestActivity);
            const startedAt = normalizeActivityTimestamp(
              previousActivity.turn_started_at || previousActivity.started_at || 0,
            );
            const segmentActivity = normalizeMessageActivity({
              status: "completed",
              run_id: String(previousActivity.run_id || activeRunId || ""),
              started_at: startedAt || undefined,
              turn_started_at: startedAt || undefined,
              finished_at: completedAt,
              run_duration_ms: startedAt ? Math.max(0, completedAt - startedAt) : 0,
              final_answer: segmentText,
              model_draft: "",
            });
            return createMessage("assistant", segmentText, {
              id: segmentId,
              activity: segmentActivity,
              answerBundle: message.answerBundle,
              runArtifact: {},
            });
          });
        });
        pendingMessage = { ...pendingMessage, id: segmentId, pending: false };
      };
      const beginNextAssistantSegment = (nextSegmentId = "") => {
        flushAssistantDelta();
        const startedAt = Date.now();
        const carriedActivity = normalizeMessageActivity(latestActivity || {});
        const nextPending = createMessage("assistant", t("labels.processing"), {
          id: String(nextSegmentId || "").trim() || undefined,
          pending: true,
          activity: mergeActivityState(carriedActivity, {
            status: "waiting_model",
            run_id: String(activeRunId || ""),
            started_at: startedAt,
            turn_started_at: startedAt,
            live_model: runModelName,
            final_answer: "",
            model_draft: "",
          }),
        });
        updateOwnerMessages((prev) => {
          const next = Array.isArray(prev) ? [...prev] : [];
          const nextQueuedIndex = next.findIndex((message) => (
            message
            && message.role === "user"
            && String(((message.activity || {}).status) || "") === "steer_queued"
          ));
          if (nextQueuedIndex >= 0) next.splice(nextQueuedIndex, 0, nextPending);
          else next.push(nextPending);
          return next;
        });
        pendingMessage = nextPending;
        latestActivity = normalizeMessageActivity(nextPending.activity);
        latestRunSnapshot = {
          ...latestRunSnapshot,
          turn_status: "running",
          final_answer: "",
          model_draft: "",
        };
        assistantText = "";
        assistantMessageStarted = false;
        modelRequestStarted = false;
      };
      const resolveStableAssistantText = (options = {}) => {
        const allowDraft = Boolean(options.allowDraft);
        const candidates = [
          assistantText,
          latestRunSnapshot.final_answer,
          latestActivity.final_answer,
        ];
        if (allowDraft) {
          candidates.push(
            latestRunSnapshot.model_draft,
            latestActivity.model_draft,
          );
        }
        return String(candidates.find((item) => String(item || "").trim()) || "").trim();
      };
      const hasVisibleFinalAnswer = () => Boolean(String(
        assistantText
        || latestActivity.final_answer
        || latestRunSnapshot.final_answer
        || "",
      ).trim());
      const stabilizePendingAssistant = (options = {}) => {
        const nextStatus = String(options.status || latestActivity.status || "running").trim() || "running";
        const durationMs = Math.max(0, Number(options.durationMs || 0) || 0);
        const fallbackLabel = String(options.fallbackLabel || "").trim();
        const stableText = resolveStableAssistantText({ allowDraft: Boolean(options.allowDraft) });
        if (stableText) {
          assistantText = stableText;
          assistantMessageStarted = true;
          completePendingText(stableText);
        } else if (fallbackLabel) {
          replacePendingText(fallbackLabel, { onlyWhileWaiting: false });
        }
        patchPendingActivity((activity) => mergeActivityState(activity, {
          status: nextStatus,
          finished_at: isActivityTerminalStatus(nextStatus) ? Date.now() : 0,
          run_duration_ms: durationMs || activity.run_duration_ms || 0,
          final_elapsed_ms: durationMs || activity.final_elapsed_ms || activity.run_duration_ms || 0,
          final_answer: stableText || activity.final_answer || "",
          model_draft: String(stableText || activity.final_answer || "").trim()
            ? ""
            : String(latestRunSnapshot.model_draft || activity.model_draft || ""),
        }));
        return Boolean(stableText);
      };
      const previewPendingAssistant = (options = {}) => {
        const fallbackLabel = String(options.fallbackLabel || "").trim();
        const stableText = resolveStableAssistantText({ allowDraft: Boolean(options.allowDraft) });
        const completeWhenStable = Boolean(options.completeWhenStable);
        if (stableText) {
          assistantText = stableText;
          assistantMessageStarted = true;
          if (completeWhenStable) {
            completePendingText(stableText);
          } else {
            replacePendingText(stableText, { onlyWhileWaiting: false });
          }
        } else if (fallbackLabel) {
          replacePendingText(fallbackLabel, { onlyWhileWaiting: false });
        }
        patchPendingActivity((activity) => {
          const nextStatus = String(
            completeWhenStable && stableText
              ? "completed"
              : (activity.status || options.status || "running"),
          ).trim() || "running";
          const nextFinalAnswer = completeWhenStable && stableText
            ? stableText
            : String(activity.final_answer || "");
          return mergeActivityState(activity, {
            status: nextStatus,
            final_answer: nextFinalAnswer,
            model_draft: String(nextFinalAnswer).trim()
              ? ""
              : String(latestRunSnapshot.model_draft || activity.model_draft || stableText || ""),
          });
        });
        return Boolean(stableText);
      };
      const cleanupRunUi = async () => {
        if (uiFinalized) return;
        uiFinalized = true;
        if (runOwnerThreadId) {
          activeSendThreadIdsRef.current.delete(runOwnerThreadId);
          finishThreadRunIndicator(runOwnerThreadId);
        }
        if (updateOwnerActiveTurn) {
          updateOwnerActiveTurn((prev) => ({
            ...prev,
            sending: false,
            activeRunId: "",
            activeRunThreadId: "",
            startedAt: 0,
            lastLiveProgressAt: 0,
            liveHeartbeat: createEmptyLiveHeartbeat(),
            stoppingRun: false,
            pendingGuidance: [],
          }));
        } else {
          setActiveRunId("");
          setActiveRunThreadId("");
          setActiveRunStartedAt(0);
          setLastLiveProgressAt(0);
          setLiveHeartbeat(createEmptyLiveHeartbeat());
          setPendingGuidance([]);
          setSending(false);
          setStoppingRun(false);
        }
      };
      const collapseLiveRunUi = () => {
        if (updateOwnerActiveTurn) {
          updateOwnerActiveTurn((prev) => ({
            ...prev,
            activeRunId: "",
            activeRunThreadId: "",
            startedAt: 0,
            lastLiveProgressAt: 0,
            liveHeartbeat: createEmptyLiveHeartbeat(),
            stoppingRun: false,
          }));
        } else {
          setActiveRunId("");
          setActiveRunThreadId("");
          setActiveRunStartedAt(0);
          setLastLiveProgressAt(0);
          setLiveHeartbeat(createEmptyLiveHeartbeat());
          setStoppingRun(false);
        }
      };
      const pushLiveLog = (type, text) => {
        const progressAt = Date.now();
        updateOwnerActiveTurn((prev) => ({
          ...prev,
          lastLiveProgressAt: progressAt,
          liveRunLogs: [createLog(type, text), ...(Array.isArray(prev.liveRunLogs) ? prev.liveRunLogs : [])].slice(0, 32),
        }));
      };
      const applySnapshot = (snapshot) => {
        if (!snapshot || typeof snapshot !== "object") return;
        latestRunSnapshot = mergeRunSnapshot(latestRunSnapshot, snapshot);
        updateOwnerActiveTurn((prev) => ({
          ...prev,
          lastLiveProgressAt: Date.now(),
          liveTurnState: mergeRunSnapshot(prev.liveTurnState || {}, snapshot),
        }));
        if (Object.prototype.hasOwnProperty.call(snapshot, "evidence_status")) {
          latestEvidenceState = {
            ...latestEvidenceState,
            status: String(snapshot.evidence_status || latestEvidenceState.status || "not_needed"),
          };
          updateOwnerActiveTurn((prev) => ({
            ...prev,
            liveEvidence: {
              ...(prev.liveEvidence || {}),
              status: String(snapshot.evidence_status || ((prev.liveEvidence || {}).status) || "not_needed"),
            },
          }));
        }
        if (String(snapshot.turn_status || "").trim() === "running") {
          updateOwnerLiveHeartbeat({
            status: "background_running",
            recentEvent: t("run.progress.recent_event_background"),
            source: "runtime",
          });
        }
        if (snapshot.context_meter && typeof snapshot.context_meter === "object") {
          setHealth((prev) => (
            prev
              ? { ...prev, context_meter: snapshot.context_meter }
              : prev
          ));
          updateOwnerSessionRuntimeState((prev) => ({ ...(prev || {}), context_meter: snapshot.context_meter }));
        }
        if (snapshot.compaction_status && typeof snapshot.compaction_status === "object") {
          setHealth((prev) => (
            prev
              ? { ...prev, compaction_status: snapshot.compaction_status }
              : prev
          ));
          updateOwnerSessionRuntimeState((prev) => ({ ...(prev || {}), compaction_status: snapshot.compaction_status }));
        }
      };
      const recordToolItem = (item) => {
        if (!item || typeof item !== "object") return;
        latestToolEvents = [item, ...latestToolEvents.filter((entry) => String(entry.id || "") !== String(item.id || ""))].slice(0, 24);
        updateOwnerActiveTurn((prev) => ({
          ...prev,
          toolTimeline: [item, ...(Array.isArray(prev.toolTimeline) ? prev.toolTimeline : []).filter((entry) => String(entry.id || "") !== String(item.id || ""))].slice(0, 24),
          liveToolTimeline: [item, ...(Array.isArray(prev.liveToolTimeline) ? prev.liveToolTimeline : []).filter((entry) => String(entry.id || "") !== String(item.id || ""))].slice(0, 24),
        }));
        patchPendingActivity((activity) => mergeActivityState(activity, {
          tool_items: [item],
        }));
        const toolName = String(item.tool || item.name || item.type || "tool");
        const summary = toolTimelineSummary(
          { ...item, name: toolName, summary: item.summary || item.output_preview || toolName },
          uiLocale,
        );
        updateOwnerLiveHeartbeat({
          status: normalizeProgressStatus(item.status || "completed"),
          tool: toolName,
          command: executionProgressCommandFromSource(item),
          action: summary || toolName,
          recentEvent: summary || toolName,
          source: "tool",
        });
        pushLogWithLimit(setLogs, "tool", `${toolName}: ${summary}`);
        pushLiveLog("tool", `${toolName}: ${summary}`);
      };
      const buildFallbackFinalPayload = () => ({
        session_id: latestThreadId || sid,
        thread_id: latestThreadId || sid,
        turn_id: String(latestRunSnapshot.turn_id || ""),
        run_id: String(((completedTurnPayload || {}).id) || activeRunId || ""),
        agent_id: "vintage_programmer",
        effective_model: String(
          chatSettings.model ||
          (activeProviderProfile && activeProviderProfile.default_model) ||
          (health && health.default_model) ||
          "",
        ).trim(),
        text: resolveStableAssistantText({ allowDraft: true }) || "",
        final_answer: String(latestRunSnapshot.final_answer || ""),
        model_draft: String(latestRunSnapshot.model_draft || (latestRunSnapshot.turn_status === "completed" ? "" : assistantText || "")),
        runtime_error: latestRunSnapshot.runtime_error || {},
        tool_boundary_clean:
          typeof latestRunSnapshot.tool_boundary_clean === "boolean"
            ? latestRunSnapshot.tool_boundary_clean
            : null,
        tool_events: latestToolEvents,
        permission_profile: normalizePermissionProfile(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "auto"),
        turn_status: String(((completedTurnPayload || {}).status) || latestRunSnapshot.turn_status || "completed"),
        plan: Array.isArray(latestRunSnapshot.plan) ? latestRunSnapshot.plan : [],
        pending_user_input: latestRunSnapshot.pending_user_input || {},
        pending_approval: latestRunSnapshot.pending_approval || {},
        activity: latestActivity,
        context_meter: latestRunSnapshot.context_meter || {},
        compaction_status: latestRunSnapshot.compaction_status || {},
        token_usage: latestTokenUsage,
        session_token_totals: latestSessionTokenTotals,
        global_token_totals: latestGlobalTokenTotals,
        inspector: {
          run_state: latestRunSnapshot,
          evidence: latestEvidenceState,
          tool_timeline: latestToolEvents,
          session: {
            session_id: latestThreadId || sid,
            context_meter: latestRunSnapshot.context_meter || {},
            compaction_status: latestRunSnapshot.compaction_status || {},
          },
          loaded_skills: [],
        },
      });

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
            if (payload && payload.run_id) {
              updateOwnerActiveTurn((prev) => ({ ...prev, activeRunId: String(payload.run_id || prev.activeRunId || "") }));
            }
            if (payload && payload.thread_id) {
              latestThreadId = String(payload.thread_id || latestThreadId || "");
            }
            if (payload && payload.session_id && !payload.thread_id) {
              latestThreadId = String(payload.session_id || latestThreadId || "");
            }
            if (payload && payload.run_snapshot) {
              applySnapshot(payload.run_snapshot);
            }
            if (event === "heartbeat") {
              // Transport liveness is deliberately separate from semantic
              // progress, so an idle connection does not reset "last progress".
              markOwnerConnectionHeartbeat(payload.ts || Date.now());
            } else if (event === "run_started") {
              modelRequestStarted = true;
              patchPendingActivity((activity) => mergeActivityState(activity, {
                run_id: String(payload.run_id || ""),
                status: "waiting_model",
                live_model_started: true,
                live_model: runModelName,
              }));
              replacePendingText(t("activity.status.waiting_model"), { onlyWhileWaiting: true });
              updateOwnerActiveTurn((prev) => ({ ...prev, activeRunId: String(payload.run_id || prev.activeRunId || ""), lastLiveProgressAt: Date.now() }));
              updateOwnerLiveHeartbeat({
                status: "waiting_model",
                model: runModelName,
                action: t("activity.status.waiting_model"),
                recentEvent: runModelName
                  ? t("run.live_agent.model_detail", { detail: runModelName })
                  : t("run.live_agent.model"),
                source: "model",
              });
            } else if (event === "run_finished") {
              flushAssistantDelta();
              const hasVisibleAnswer = hasVisibleFinalAnswer();
              const displayedAnswer = previewPendingAssistant({
                status: hasVisibleAnswer ? "completed" : (latestActivity.status || "thinking"),
                durationMs: Math.max(0, Number(payload.duration_ms || 0) || 0),
                allowDraft: !hasVisibleAnswer,
                completeWhenStable: true,
                fallbackLabel: hasVisibleAnswer ? "" : t("buttons.saving"),
              });
              if (hasVisibleAnswer || displayedAnswer) {
                collapseLiveRunUi();
              } else {
                updateOwnerLiveHeartbeat({
                  status: "waiting_model",
                  action: t("run.progress.waiting_model"),
                  recentEvent: t("run.progress.recent_event_waiting_model"),
                  source: "model",
                });
              }
            } else if (event === "run_failed") {
              flushAssistantDelta();
              stabilizePendingAssistant({
                status: "failed",
                allowDraft: true,
              });
              updateOwnerLiveHeartbeat({
                status: "failed",
                action: t("activity.failed"),
                recentEvent: t("activity.failed"),
                source: "runtime",
              });
            } else if (event === "trace_event") {
              const trace = normalizeTraceEvent(payload.trace || {});
              if (trace.id) {
                if (String(trace.type || "").trim() === "llm.started") {
                  modelRequestStarted = true;
                  replacePendingText(t("activity.status.waiting_model"), { onlyWhileWaiting: true });
                }
                const nextStatus = activityStatusFromTraceType(trace.type, latestActivity.status || "thinking", trace.status);
                patchPendingActivity((activity) => appendActivityTrace(activity, trace, { status: nextStatus }));
                syncHeartbeatFromTrace(trace);
              }
              const detail = String(trace.title || trace.detail || "");
              if (detail) {
                pushLogWithLimit(setLogs, "trace", detail);
                pushLiveLog("trace", detail);
              }
            } else if (event === "thread/started") {
              if (payload.thread) upsertThreadRow(payload.thread);
            } else if (event === "thread/status/changed") {
              updateThreadStatus(payload.thread_id, ((payload.status || {}).type) || "idle");
            } else if (event === "thread/updated") {
              if (payload.thread) upsertThreadRow(payload.thread);
            } else if (event === "thread/tokenUsage/updated") {
              latestTokenUsage = payload.token_usage && typeof payload.token_usage === "object" ? payload.token_usage : latestTokenUsage;
              latestSessionTokenTotals = payload.session_token_totals && typeof payload.session_token_totals === "object"
                ? payload.session_token_totals
                : latestSessionTokenTotals;
              latestGlobalTokenTotals = payload.global_token_totals && typeof payload.global_token_totals === "object"
                ? payload.global_token_totals
                : latestGlobalTokenTotals;
              if (payload.context_meter && typeof payload.context_meter === "object") {
                applySnapshot({ context_meter: payload.context_meter });
              }
            } else if (event === "turn/started") {
              const turn = payload.turn && typeof payload.turn === "object" ? payload.turn : {};
              const turnId = String(turn.id || "");
              if (turnId) updateOwnerActiveTurn((prev) => ({ ...prev, activeRunId: turnId }));
              if (String(turn.threadId || "").trim()) {
                latestThreadId = String(turn.threadId || "").trim();
                updateThreadStatus(latestThreadId, "active");
              }
              applySnapshot({
                permission_profile: normalizePermissionProfile(payload.permission_profile || chatSettings.permission_profile || "auto"),
                turn_status: "running",
              });
              updateOwnerLiveHeartbeat({
                status: "background_running",
                action: t("activity.status.preparing_request"),
                recentEvent: t("run.live_agent.preparing"),
                source: "runtime",
              });
            } else if (event === "turn/plan/updated") {
              const nextPlan = Array.isArray(payload.plan) ? payload.plan : [];
              applySnapshot({ plan: nextPlan });
              updateOwnerSessionRuntimeState((prev) => ({
                ...(prev || {}),
                permission_profile: normalizePermissionProfile((latestRunSnapshot.permission_profile) || chatSettings.permission_profile || "auto"),
                turn_status: String((latestRunSnapshot.turn_status) || "running"),
                plan: nextPlan,
              }));
              const explanation = String(payload.explanation || "checklist updated");
              patchPendingActivity((activity) => mergeActivityState(activity, {
                plan: nextPlan,
                plan_explanation: explanation,
              }));
              updateOwnerLiveHeartbeat({
                status: "running",
                action: explanation,
                recentEvent: explanation,
                source: "model",
              });
              pushLogWithLimit(setLogs, "system", explanation);
              pushLiveLog("system", explanation);
            } else if (event === "turn/segment/completed") {
              const segment = payload.segment && typeof payload.segment === "object" ? payload.segment : {};
              completeCurrentAssistantSegment(segment);
            } else if (event === "turn/steer/accepted") {
              const steer = payload.steer && typeof payload.steer === "object" ? payload.steer : {};
              const steerId = String(steer.id || "");
              if (steerId) {
                const acceptedAt = normalizeActivityTimestamp(steer.accepted_at || 0) || Date.now();
                const acceptedMessage = createMessage("user", String(steer.message || ""), {
                  id: steerId,
                  activity: {
                    status: "steer_accepted",
                    run_id: String(activeRunId || ""),
                    steer_id: steerId,
                    queued_at: normalizeActivityTimestamp(steer.queued_at || 0),
                    accepted_at: acceptedAt,
                  },
                });
                updateOwnerMessages((prev) => {
                  const previous = Array.isArray(prev) ? prev : [];
                  const existingIndex = previous.findIndex((item) => (
                    String(((item.activity || {}).steer_id) || "") === steerId
                  ));
                  if (existingIndex < 0) return [...previous, acceptedMessage];
                  return previous.map((item, index) => (
                    index === existingIndex
                      ? { ...item, activity: { ...(item.activity || {}), ...acceptedMessage.activity } }
                      : item
                  ));
                });
                updateOwnerActiveTurn((prev) => ({
                  ...prev,
                  pendingGuidance: (Array.isArray(prev.pendingGuidance) ? prev.pendingGuidance : [])
                    .filter((item) => String(item.id || "") !== steerId),
                }));
              }
              if (Boolean(payload.starts_next_response)) {
                beginNextAssistantSegment(String(payload.next_segment_id || ""));
              }
              updateOwnerLiveHeartbeat({
                status: "waiting_model",
                action: t("steer.accepted"),
                recentEvent: t("steer.accepted"),
                source: "user",
                updatedAt: steer.accepted_at || Date.now(),
              });
            } else if (event === "turn/completed") {
              flushAssistantDelta();
              completedTurnPayload = payload.turn && typeof payload.turn === "object" ? payload.turn : {};
              const completionStatus = String((completedTurnPayload && completedTurnPayload.status) || latestRunSnapshot.turn_status || "completed");
              applySnapshot({ turn_status: completionStatus });
              const hasVisibleAnswer = hasVisibleFinalAnswer();
              const displayedAnswer = previewPendingAssistant({
                status: hasVisibleAnswer ? "completed" : (latestActivity.status || "thinking"),
                allowDraft: !hasVisibleAnswer,
                completeWhenStable: true,
                fallbackLabel: hasVisibleAnswer ? "" : t("buttons.saving"),
              });
              if (hasVisibleAnswer || displayedAnswer) {
                collapseLiveRunUi();
              } else {
                updateOwnerLiveHeartbeat({
                  status: "waiting_model",
                  action: t("buttons.saving"),
                  recentEvent: t("run.progress.recent_event_waiting_model"),
                  source: "model",
                });
              }
            } else if (event === "item/started") {
              const item = payload.item && typeof payload.item === "object" ? payload.item : {};
              if (item.id) {
                patchPendingActivity((activity) => mergeActivityState(activity, {
                  live_items: [liveRunItemFromStreamItem(item, event)],
                }));
              }
              syncHeartbeatFromStreamItem(item, event);
              if (item.id) {
                if (ownerThreadVisible()) {
                  dispatch({
                    type: "items/register",
                    item: {
                      ...item,
                      threadId: String(payload.thread_id || latestThreadId || ""),
                      turnId: String(payload.turn_id || activeRunId || ""),
                    },
                  });
                }
              }
              if (String(item.type || "") === "agentMessage") {
                assistantMessageStarted = true;
              }
            } else if (event === "item/agentMessage/delta") {
              assistantMessageStarted = true;
              const delta = String(payload.delta || "");
              if (delta) {
                queueAssistantDelta(delta, String(payload.item_id || ""));
              }
            } else if (event === "item/completed") {
              const item = payload.item && typeof payload.item === "object" ? payload.item : {};
              if (String(item.type || "") === "agentMessage") flushAssistantDelta();
              if (item.id) {
                patchPendingActivity((activity) => mergeActivityState(activity, {
                  live_items: [liveRunItemFromStreamItem(item, event)],
                }));
              }
              syncHeartbeatFromStreamItem(item, event);
              if (item.id) {
                if (ownerThreadVisible()) {
                  dispatch({
                    type: "items/register",
                    item: {
                      ...item,
                      threadId: String(payload.thread_id || latestThreadId || ""),
                      turnId: String(payload.turn_id || activeRunId || ""),
                    },
                  });
                }
              }
              const itemType = String(item.type || "");
              if (itemType === "agentMessage") {
                assistantMessageStarted = true;
                assistantText = String(item.text || assistantText || "");
                patchPendingActivity((activity) => mergeActivityState(activity, {
                  status: "waiting_model",
                  final_answer: "",
                  model_draft: assistantText,
                }));
                if (assistantText) replacePendingText(assistantText);
              } else if (itemType === "userInputRequest") {
                const itemApprovalRequest = item.approval_request && typeof item.approval_request === "object"
                  ? item.approval_request
                  : {};
                const nextPending = {
                  summary: String(item.summary || ""),
                  questions: Array.isArray(item.questions) ? item.questions : [],
                  approval_request: itemApprovalRequest,
                };
                const nextApproval = Object.keys(itemApprovalRequest).length ? itemApprovalRequest : {};
                applySnapshot({
                  permission_profile: normalizePermissionProfile(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "auto"),
                  turn_status: "needs_user_input",
                  pending_user_input: nextPending,
                  pending_approval: nextApproval,
                });
                updateOwnerSessionRuntimeState((prev) => ({
                  ...(prev || {}),
                  permission_profile: normalizePermissionProfile(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "auto"),
                  turn_status: "needs_user_input",
                  pending_user_input: nextPending,
                  pending_approval: nextApproval,
                }));
                if (isCommandExecutionApproval(nextApproval)) {
                  markPendingAsRuntimeNotice(String(nextPending.summary || t("labels.pending_input")));
                } else {
                  replacePendingText(String(nextPending.summary || t("labels.pending_input")));
                }
                updateOwnerLiveHeartbeat({
                  status: "blocked",
                  action: String(nextPending.summary || t("labels.pending_input")),
                  recentEvent: String(nextPending.summary || t("labels.pending_input")),
                  source: "runtime",
                });
                pushLogWithLimit(setLogs, "system", String(nextPending.summary || "user input required"));
                pushLiveLog("system", String(nextPending.summary || "user input required"));
              } else if (["toolCall", "commandExecution", "fileChange", "imageView"].includes(itemType)) {
                recordToolItem(item);
              }
            } else if (event === "request_user_input") {
              const nextPending = payload.pending_user_input && typeof payload.pending_user_input === "object"
                ? payload.pending_user_input
                : {};
              const nextApproval = payload.pending_approval && typeof payload.pending_approval === "object"
                ? payload.pending_approval
                : ((nextPending.approval_request && typeof nextPending.approval_request === "object") ? nextPending.approval_request : {});
              applySnapshot({
                permission_profile: normalizePermissionProfile(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "auto"),
                turn_status: String(payload.turn_status || "needs_user_input"),
                pending_user_input: nextPending,
                pending_approval: nextApproval,
              });
              updateOwnerSessionRuntimeState((prev) => ({
                ...(prev || {}),
                permission_profile: normalizePermissionProfile(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "auto"),
                turn_status: String(payload.turn_status || "needs_user_input"),
                pending_user_input: nextPending,
                pending_approval: nextApproval,
              }));
              if (isCommandExecutionApproval(nextApproval)) {
                markPendingAsRuntimeNotice(String(nextPending.summary || t("labels.pending_input")));
              } else {
                replacePendingText(String(nextPending.summary || t("labels.pending_input")));
              }
              updateOwnerLiveHeartbeat({
                status: "blocked",
                action: String(nextPending.summary || t("labels.pending_input")),
                recentEvent: String(nextPending.summary || t("labels.pending_input")),
                source: "runtime",
              });
              pushLogWithLimit(setLogs, "system", String(nextPending.summary || "user input required"));
              pushLiveLog("system", String(nextPending.summary || "user input required"));
            } else if (event === "stage") {
              const detail = String(payload.detail || payload.label || payload.code || t("labels.processing"));
              updateOwnerActiveTurn((prev) => ({
                ...prev,
                stageTimeline: [
                  {
                    id: String(payload.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
                    label: String(payload.label || payload.code || "stage"),
                    detail,
                    status: String(payload.status || "running"),
                    at: Date.now(),
                  },
                  ...(Array.isArray(prev.stageTimeline) ? prev.stageTimeline : []),
                ].slice(0, 24),
              }));
              updateOwnerLiveHeartbeat((prev) => ({
                ...prev,
                status: ["validating", "running", "waiting_tool", "waiting_model", "background_running"].includes(normalizeProgressStatus(prev.status))
                  ? prev.status
                  : "background_running",
                action: normalizeProgressStatus(prev.status) === "waiting_model" && String(prev.source || "") === "model"
                  ? (prev.action || t("activity.status.waiting_model"))
                  : detail,
                recentEvent: normalizeProgressStatus(prev.status) === "waiting_model" && String(prev.source || "") === "model"
                  ? (prev.recentEvent || t("run.live_agent.model"))
                  : detail,
                source: normalizeProgressStatus(prev.status) === "waiting_model" && String(prev.source || "") === "model"
                  ? prev.source
                  : "stage",
              }));
              replacePendingText(detail, { onlyWhileWaiting: true, skipAfterModelStarted: true });
              pushLogWithLimit(setLogs, "stage", detail);
              pushLiveLog("stage", detail);
            } else if (event === "trace") {
              const detail = String(payload.message || payload.raw || "");
              if (detail) {
                updateOwnerLiveHeartbeat((prev) => ({
                  ...prev,
                  recentEvent: detail,
                  source: prev.source || "stage",
                }));
                pushLogWithLimit(setLogs, "trace", detail);
                pushLiveLog("trace", detail);
              }
            } else if (event === "final") {
              finalPayload = payload.response || null;
            } else if (event === "error") {
              throw errorWithUiError(normalizeUiError(uiLocale, payload, t("errors.request_failed")));
            }
          }
          splitIndex = buffer.indexOf("\n\n");
        }
        if (done) break;
      }

      flushAssistantDelta();
      if (!finalPayload && (completedTurnPayload || assistantText || Object.keys(latestRunSnapshot).length)) {
        finalPayload = buildFallbackFinalPayload();
      }
      if (!finalPayload) throw new Error("missing final payload");
      const finalActivitySourceStatus = normalizeProgressStatus(
        finalPayload.turn_status
        || (((finalPayload.inspector || {}).run_state || {}).turn_status)
        || ((completedTurnPayload || {}).status)
        || latestRunSnapshot.turn_status
        || ((finalPayload.activity || {}).status)
        || latestActivity.status
        || "",
      );
      const finalActivityStatus = isActivityTerminalStatus(finalActivitySourceStatus)
        ? finalActivitySourceStatus
        : "completed";
      const finalActivity = mergeActivityState(finalPayload.activity || latestActivity, {
        status: finalActivityStatus,
        finished_at: Date.now(),
        plan: Array.isArray(finalPayload.plan) ? finalPayload.plan : (Array.isArray(latestRunSnapshot.plan) ? latestRunSnapshot.plan : []),
        plan_explanation: String(latestActivity.plan_explanation || ""),
        tool_items: latestActivity.tool_items,
      });
      const previousPendingMessageId = pendingMessage.id;
      const finalizedTurnId = String(finalPayload.turn_id || latestRunSnapshot.turn_id || previousPendingMessageId || "").trim() || previousPendingMessageId;
      const finalPendingApproval = finalPayload.pending_approval
        || (((finalPayload.inspector || {}).run_state || {}).pending_approval)
        || {};
      const finalMessageRole = isCommandExecutionApproval(finalPendingApproval) || pendingMessage.role === "runtime"
        ? "runtime"
        : "assistant";
      updateOwnerMessages((prev) =>
        prev.map((item) =>
          item.id === previousPendingMessageId
            ? createMessage(finalMessageRole, String(finalPayload.text || assistantText || "(empty response)"), {
              id: finalizedTurnId,
              activity: finalActivity,
              answerBundle: finalPayload.answer_bundle || item.answerBundle || {},
              runArtifact: finalPayload.run_artifact || item.runArtifact || {},
            })
            : item,
        ),
      );
      pendingMessage = { ...pendingMessage, id: finalizedTurnId };
      updateOwnerActiveTurn((prev) => ({ ...prev, lastResponse: finalPayload }));
      setPendingUploads([]);
      clearUiError();
      if (finalPayload.thread_id || finalPayload.session_id) {
        latestThreadId = String(finalPayload.thread_id || finalPayload.session_id || latestThreadId || "");
        if (latestThreadId && ownerThreadVisible()) setSessionId(latestThreadId);
      }
      updateOwnerActiveTurn((prev) => ({
        ...prev,
        lastResponse: finalPayload,
        liveTurnState: mergeRunSnapshot(prev.liveTurnState || {}, {
          ...(((finalPayload.inspector || {}).run_state) || {}),
          permission_profile: normalizePermissionProfile(finalPayload.permission_profile || (((finalPayload.inspector || {}).run_state || {}).permission_profile) || chatSettings.permission_profile || "auto"),
          turn_status: String(finalPayload.turn_status || (((finalPayload.inspector || {}).run_state || {}).turn_status) || "completed"),
          model_draft: String(finalPayload.model_draft || (((finalPayload.inspector || {}).run_state || {}).model_draft) || ""),
          final_answer: String(finalPayload.final_answer || (((finalPayload.inspector || {}).run_state || {}).final_answer) || ""),
          runtime_error: finalPayload.runtime_error || (((finalPayload.inspector || {}).run_state || {}).runtime_error) || {},
          context_meter: finalPayload.context_meter || (((finalPayload.inspector || {}).run_state || {}).context_meter) || (((finalPayload.inspector || {}).session || {}).context_meter) || {},
          plan: Array.isArray(finalPayload.plan) ? finalPayload.plan : ((((finalPayload.inspector || {}).run_state || {}).plan) || []),
          pending_user_input: finalPayload.pending_user_input || (((finalPayload.inspector || {}).run_state || {}).pending_user_input) || {},
          pending_approval: finalPayload.pending_approval || (((finalPayload.inspector || {}).run_state || {}).pending_approval) || {},
        }),
        liveEvidence: {
          ...(prev.liveEvidence || {}),
          ...latestEvidenceState,
          ...(((finalPayload.inspector || {}).evidence) || {}),
        },
        liveToolTimeline: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events : latestToolEvents,
      }));
      if (latestThreadId) updateThreadStatus(latestThreadId, "idle");
      setHealth((prev) => (
        prev
          ? {
              ...prev,
              context_meter: finalPayload.context_meter || (((finalPayload.inspector || {}).run_state || {}).context_meter) || prev.context_meter,
              compaction_status: finalPayload.compaction_status || (((finalPayload.inspector || {}).run_state || {}).compaction_status) || prev.compaction_status,
            }
          : prev
      ));
      updateOwnerSessionRuntimeState({
        ...(finalPayload.inspector || {}).run_state,
        ...(finalPayload.inspector || {}).evidence,
        ...(finalPayload.inspector || {}).session,
        ...{
          agent: ((finalPayload.inspector || {}).agent) || sessionAgentInfo || {},
          agent_id: finalPayload.agent_id || "vintage_programmer",
          agent_title: String((((finalPayload.inspector || {}).agent) || {}).title || sessionRuntimeState.agent_title || "Vintage Programmer"),
          goal: String((((finalPayload.inspector || {}).run_state || {}).goal) || messageText),
          current_goal: String((((finalPayload.inspector || {}).run_state || {}).goal) || messageText),
          permission_profile: normalizePermissionProfile(finalPayload.permission_profile || (((finalPayload.inspector || {}).run_state || {}).permission_profile) || chatSettings.permission_profile || "auto"),
          turn_status: String(finalPayload.turn_status || (((finalPayload.inspector || {}).run_state || {}).turn_status) || "completed"),
          model_draft: String(finalPayload.model_draft || (((finalPayload.inspector || {}).run_state || {}).model_draft) || ""),
          final_answer: String(finalPayload.final_answer || (((finalPayload.inspector || {}).run_state || {}).final_answer) || ""),
          runtime_error: finalPayload.runtime_error || (((finalPayload.inspector || {}).run_state || {}).runtime_error) || {},
          plan: Array.isArray(finalPayload.plan) ? finalPayload.plan : ((((finalPayload.inspector || {}).run_state || {}).plan) || []),
          pending_user_input: finalPayload.pending_user_input || (((finalPayload.inspector || {}).run_state || {}).pending_user_input) || {},
          pending_approval: finalPayload.pending_approval || (((finalPayload.inspector || {}).run_state || {}).pending_approval) || {},
          phase: String((((finalPayload.inspector || {}).run_state || {}).phase) || "report"),
          last_run_id: String(finalPayload.run_id || ""),
          last_model: String(finalPayload.effective_model || ""),
          context_meter: finalPayload.context_meter || (((finalPayload.inspector || {}).run_state || {}).context_meter) || (((finalPayload.inspector || {}).session || {}).context_meter) || {},
          tool_hits: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events : [],
          tool_count: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0,
          evidence_status: String((((finalPayload.inspector || {}).evidence || {}).status) || "not_needed"),
          loaded_skills: Array.isArray((finalPayload.inspector || {}).loaded_skills) ? finalPayload.inspector.loaded_skills : sessionLoadedSkills,
          enabled_skill_ids: Array.isArray((finalPayload.inspector || {}).loaded_skills)
            ? finalPayload.inspector.loaded_skills.map((item) => item.key || item.name || item.id)
            : [],
        },
      });
      pushLogWithLimit(
        setLogs,
        "response",
        t("log.reply_received", { count: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0 }),
      );
      pushLiveLog(
        "response",
        t("log.reply_received", { count: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0 }),
      );
      const reconciledMessages = await reconcileCompletedThreadMessages(latestThreadId || runOwnerThreadId);
      if (!reconciledMessages) {
        updateOwnerMessages((prev) => (
          messagesForLiveGuidanceDisplay(prev, String((pendingMessage && pendingMessage.id) || ""))
        ));
      }
      await cleanupRunUi();
    } catch (err) {
      const nextError = applyUiError(err, t("errors.request_failed"));
      pushLogWithLimit(setLogs, "error", t("log.send_failed", { summary: nextError.summary }));
      if (updateOwnerMessages) {
        updateOwnerMessages((prev) => prev.filter((item) => !(pendingMessage && item.id === pendingMessage.id)));
      } else {
        setMessages((prev) => prev.filter((item) => !(pendingMessage && item.id === pendingMessage.id)));
      }
      if (resumePendingState && runOwnerThreadId) {
        updateThreadSnapshot(runOwnerThreadId, (existing) => ({
          ...existing,
          sessionRuntimeState: mergeSessionRuntimeStateSnapshot(existing.sessionRuntimeState || {}, resumePendingState),
        }));
        if (String(activeSessionIdRef.current || "").trim() === runOwnerThreadId) {
          setSessionRuntimeState((prev) => mergeSessionRuntimeStateSnapshot(prev || {}, resumePendingState));
        }
      }
    } finally {
      cancelAssistantDeltaFlush();
      if (!uiFinalized) {
        if (lockedRunOwnerThreadId) {
          finishThreadRunIndicator(lockedRunOwnerThreadId);
        }
        if (updateOwnerActiveTurn) {
          updateOwnerActiveTurn((prev) => ({
            ...prev,
            sending: false,
            activeRunId: "",
            activeRunThreadId: "",
            startedAt: 0,
            lastLiveProgressAt: 0,
            liveHeartbeat: createEmptyLiveHeartbeat(),
            stoppingRun: false,
          }));
        } else {
          setActiveRunId("");
          setActiveRunThreadId("");
          setActiveRunStartedAt(0);
          setLastLiveProgressAt(0);
          setLiveHeartbeat(createEmptyLiveHeartbeat());
          setSending(false);
          setStoppingRun(false);
        }
      }
      if (lockedRunOwnerThreadId) {
        activeSendThreadIdsRef.current.delete(lockedRunOwnerThreadId);
      }
    }
  }

  async function loadSpecDetail(name) {
    const specName = String(name || "").trim();
    if (!specName) return;
    try {
      const payload = await fetchJson(workbenchSpecUrl(specName, uiLocale));
      clearUiError();
      setSelectedSpecName(specName);
      setSpecEditor(String(payload.content || ""));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.read_spec_failed"));
      pushLogWithLimit(setLogs, "error", t("log.spec_read_failed", { summary: nextError.summary }));
    }
  }

  async function saveSkill() {
    if (!skillEditor.trim()) return;
    setSavingWorkbench(true);
    try {
      const targetSkillKey = String(selectedSkillIdRef.current || "").trim();
      const targetSkill = shallowSkillList(skills).find((item) => skillKey(item) === targetSkillKey) || null;
      if (targetSkill && targetSkill.read_only) {
        throw new Error(t("errors.skill_read_only"));
      }
      const targetName = targetSkill ? skillName(targetSkill) : "";
      const method = targetName ? "PUT" : "POST";
      const url = targetName
        ? workbenchSkillUrl(targetName, "team")
        : "/api/workbench/skills";
      const payload = await fetchJson(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: skillEditor }),
      });
      const nextSkill = normalizeSkillDescriptor(payload);
      const nextSkillId = skillKey(nextSkill) || targetSkillKey || "";
      setSkillSelectionState(nextSkillId, String(payload.content || ""));
      await refreshSkills(nextSkillId);
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.skill_saved", { skill_id: skillName(nextSkill) || "new-skill" }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.save_skill_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.save_skill_failed"));
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function toggleSelectedSkill(nextEnabled) {
    const targetSkillKey = String(selectedSkillIdRef.current || "").trim();
    const targetSkill = shallowSkillList(skills).find((item) => skillKey(item) === targetSkillKey) || null;
    if (!targetSkill) return;
    const targetName = skillName(targetSkill);
    if (!targetName) return;
    setSavingWorkbench(true);
    try {
      const payload = await fetchJson(workbenchSkillActionUrl(targetName, skillScope(targetSkill), "toggle"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      const nextSkill = normalizeSkillDescriptor(payload);
      const nextSkillId = skillKey(nextSkill) || targetSkillKey;
      setSkillSelectionState(nextSkillId, String(payload.content || ""));
      await refreshSkills(nextSkillId);
      clearUiError();
      pushLogWithLimit(
        setLogs,
        "system",
        t("log.skill_toggled", {
          status: payload.enabled ? t("skills.status.enabled") : t("skills.status.disabled"),
          skill_id: skillName(nextSkill) || targetName,
        }),
      );
    } catch (err) {
      const nextError = applyUiError(err, t("errors.skill_toggle_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.skill_toggle_failed"));
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function handleDeleteSelectedSkill() {
    const targetSkillKey = String(selectedSkillIdRef.current || "").trim();
    if (!targetSkillKey) return;
    const safeSkills = shallowSkillList(skills);
    const targetSkill = safeSkills.find((item) => skillKey(item) === targetSkillKey) || null;
    if (!targetSkill || targetSkill.read_only) return;
    const targetName = skillName(targetSkill);
    if (!targetName) return;
    const currentIndex = safeSkills.findIndex((item) => skillKey(item) === targetSkillKey);
    const fallbackSkillId =
      skillKey((currentIndex >= 0 ? safeSkills[currentIndex + 1] : null) || {}) ||
      skillKey((currentIndex > 0 ? safeSkills[currentIndex - 1] : null) || {});
    if (!window.confirm(t("confirm.delete_skill", { skill_id: targetName }))) {
      return;
    }
    setSavingWorkbench(true);
    try {
      await fetchJson(workbenchSkillUrl(targetName, "team"), { method: "DELETE" });
      if (fallbackSkillId) {
        skillDraftModeRef.current = false;
      }
      await refreshSkills(fallbackSkillId);
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.skill_deleted", { skill_id: targetName }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.delete_skill_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.delete_skill_failed"));
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function saveSpec() {
    if (!selectedSpecName || !specEditor.trim()) return;
    setSavingWorkbench(true);
    try {
      const payload = await fetchJson(workbenchSpecUrl(selectedSpecName, uiLocale), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: specEditor }),
      });
      setSpecEditor(String(payload.content || ""));
      await refreshSpecs();
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.spec_saved", { spec_name: selectedSpecName }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.save_spec_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.save_spec_failed"));
    } finally {
      setSavingWorkbench(false);
    }
  }

  function handleComposerKeyDown(event) {
    if (
      event.isComposing
      || (event.nativeEvent && event.nativeEvent.isComposing)
      || (event.nativeEvent && event.nativeEvent.keyCode === 229)
    ) {
      return;
    }
    if (currentThreadBusy && !canQueueGuidance) return;
    if (slashCommandSuggestions.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSlashCommandActiveIndex((prev) => (prev + 1) % slashCommandSuggestions.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSlashCommandActiveIndex((prev) => (
          (prev - 1 + slashCommandSuggestions.length) % slashCommandSuggestions.length
        ));
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setDraft("");
        setSlashCommandActiveIndex(0);
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        const selectedIndex = Math.min(
          Math.max(0, slashCommandActiveIndex),
          slashCommandSuggestions.length - 1,
        );
        handleSend(slashCommandSuggestions[selectedIndex].command);
        return;
      }
    }
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
  const sessionAgentInfo = sessionRuntimeState && sessionRuntimeState.agent && typeof sessionRuntimeState.agent === "object"
    ? sessionRuntimeState.agent
    : {};
  const sessionLoadedSkills = Array.isArray(sessionRuntimeState && sessionRuntimeState.loaded_skills)
    ? sessionRuntimeState.loaded_skills
    : [];
  const hasSessionAgentInfo = Boolean(Object.keys(sessionAgentInfo).length);
  const hasSessionLoadedSkills = Boolean(sessionLoadedSkills.length);
  const agentInfo = (lastResponse && lastResponse.inspector && lastResponse.inspector.agent)
    || (hasSessionAgentInfo ? sessionAgentInfo : null)
    || (health && health.agent)
    || {};
  const loadedSkills = Array.isArray((lastResponse && lastResponse.inspector && lastResponse.inspector.loaded_skills))
    ? lastResponse.inspector.loaded_skills
    : (hasSessionLoadedSkills
      ? sessionLoadedSkills
      : (Array.isArray((health && health.agent && health.agent.loaded_skills))
        ? health.agent.loaded_skills
        : []));
  const lastInspector = (lastResponse && lastResponse.inspector) || {};
  const completedRuntimeState = lastInspector.run_state || {};
  const isActiveRunVisible = Boolean(sessionId && activeRunThreadId && sessionId === activeRunThreadId);
  const hasLiveRuntimeState = isCurrentThreadLiveRun({
    sessionId,
    activeRunThreadId,
    sending,
    activeRunId,
    activeRunStartedAt,
    hasRunningActivity,
    liveTurnState,
  });
  const liveAssistantMessageId = hasLiveRuntimeState
    ? String((((latestAssistantMessage(messages, { preferPending: true })) || {}).id) || "").trim()
    : "";
  const conversationMessages = messagesForLiveGuidanceDisplay(
    appendMessagesOnceById([], messages),
    liveAssistantMessageId,
  );
  const runState = hasLiveRuntimeState ? liveTurnState : completedRuntimeState;
  const activePlan = Array.isArray(runState.plan) && runState.plan.length
    ? runState.plan
    : (Array.isArray(sessionRuntimeState.plan) ? sessionRuntimeState.plan : []);
  const currentPlanStep = activePlan.find((item) => String((item && item.status) || "") === "in_progress") || null;
  const activeTaskCheckpoint = {
    task_id: "",
    goal: String(runState.goal || sessionRuntimeState.goal || ""),
    status: String(runState.turn_status || sessionRuntimeState.turn_status || ""),
    current_step_id: String((currentPlanStep && (currentPlanStep.id || currentPlanStep.step)) || ""),
    cwd: String(runState.cwd || sessionRuntimeState.cwd || ""),
    next_action: String((currentPlanStep && (currentPlanStep.step || currentPlanStep.title || currentPlanStep.content)) || ""),
    blocked_reason: String((runState.runtime_error || {}).message || runState.blocked_reason || ""),
    active_files: [],
    active_attachments: [],
    completed_steps: activePlan.filter((item) => String((item && item.status) || "") === "completed"),
    failed_attempts: [],
    completed_steps_count: activePlan.filter((item) => String((item && item.status) || "") === "completed").length,
    failed_attempts_count: 0,
    progress_basis: [],
    evidence_refs: [],
    validation_warnings: [],
  };
  const selectedThemeColor = themeColorOptionById(themeColor).id;
  const selectedPermissionProfile = normalizePermissionProfile(chatSettings.permission_profile || "auto");
  const selectedPermissionProfileClass = selectedPermissionProfile.replaceAll("_", "-");
  const selectedPermissionDescription = t(`settings.permission_profile.${selectedPermissionProfile}.help`);
  const selectedPermissionAriaLabel = `${t("settings.permission_profile")}: ${selectedPermissionDescription}`;
  const activePermissionProfile = normalizePermissionProfile(
    (hasLiveRuntimeState ? runState.permission_profile : "")
    || selectedPermissionProfile
    || "auto",
  );
  const activeBoundaryModelView = (
    runState.runtime_boundary_model_view && typeof runState.runtime_boundary_model_view === "object"
  )
    ? runState.runtime_boundary_model_view
    : {};
  const activeTurnStatus = String(runState.turn_status || sessionRuntimeState.turn_status || "idle");
  const activePendingInput =
    (runState.pending_user_input && typeof runState.pending_user_input === "object")
      ? runState.pending_user_input
      : ((sessionRuntimeState.pending_user_input && typeof sessionRuntimeState.pending_user_input === "object") ? sessionRuntimeState.pending_user_input : {});
  const activePendingApproval = (() => {
    // Hide the consumed approval while its resume request is in flight. The
    // persisted snapshot stays intact so a failed submission can show it again.
    if (approvalSubmitting) return {};
    const candidates = [
      runState.pending_approval,
      sessionRuntimeState.pending_approval,
      activePendingInput.approval_request,
    ];
    for (const candidate of candidates) {
      if (!candidate || typeof candidate !== "object") continue;
      if (String(candidate.type || "") !== "command_execution") continue;
      if (!String(candidate.command || "").trim()) continue;
      return candidate;
    }
    return {};
  })();
  const hasCommandApproval = Boolean(
    activePendingApproval
    && typeof activePendingApproval === "object"
    && String(activePendingApproval.type || "") === "command_execution"
    && String(activePendingApproval.command || "").trim(),
  );
  const pendingRuntimeQuestions = Array.isArray(activePendingInput.questions)
    ? activePendingInput.questions.filter((item) => item && typeof item === "object")
    : [];
  const hasPendingRuntimeInput = Boolean(
    !approvalSubmitting
    && !hasCommandApproval
    && String(activePendingInput.type || "") === "request_user_input"
    && pendingRuntimeQuestions.length
  );
  const runtimeAttentionCount = Number(hasCommandApproval) + Number(hasPendingRuntimeInput);
  const runtimeInteractionKey = hasCommandApproval
    ? `approval:${String(activePendingApproval.tool_call_id || activePendingApproval.command || "")}`
    : (hasPendingRuntimeInput
      ? `input:${String(activePendingInput.tool_call_id || pendingRuntimeQuestions[0].id || "")}`
      : "");
  useEffect(() => {
    if (runtimeInteractionKey) setDrawerView("run");
  }, [runtimeInteractionKey]);
  const commandApprovalRisks = hasCommandApproval && Array.isArray(activePendingApproval.risks)
    ? activePendingApproval.risks
    : [];
  const commandApprovalFiles = hasCommandApproval && Array.isArray(activePendingApproval.files)
    ? activePendingApproval.files
    : [];
  const handleCommandApproval = async (action) => {
    if (!hasCommandApproval || approvalSubmitting) return;
    const normalizedAction = action === "approve_once" ? "approve_once" : "cancel";
    const command = String(activePendingApproval.command || "").trim();
    const cwd = String(activePendingApproval.cwd || "").trim();
    const approvalToken = String(activePendingApproval.approval_token || "").trim();
    const toolCallId = String(activePendingApproval.tool_call_id || "").trim();
    if (!command) return;
    if (normalizedAction === "approve_once" && !approvalToken) return;
    const message = normalizedAction === "approve_once"
      ? t("approval_modal.approve_message", { command })
      : t("approval_modal.cancel_message", { command });
    setApprovalSubmitting(true);
    try {
      await handleSend(message, {
        type: "command_execution",
        action: normalizedAction,
        approval_token: approvalToken,
        tool_call_id: toolCallId,
        command,
        cwd,
      }, {
        pendingResumeState: {
          turn_status: "needs_user_input",
          pending_user_input: activePendingInput,
          pending_approval: activePendingApproval,
        },
      });
    } finally {
      setApprovalSubmitting(false);
    }
  };
  const activeToolTimeline = hasLiveRuntimeState
    ? liveToolTimeline
    : (Array.isArray(lastInspector.tool_timeline) && lastInspector.tool_timeline.length
      ? lastInspector.tool_timeline
      : toolTimeline);
  const activeRunLogs = hasLiveRuntimeState ? liveRunLogs : logs;
  const runtimeActivityMessage = latestAssistantMessage(messages, { preferPending: true });
  const runtimeActivity = normalizeMessageActivity((runtimeActivityMessage && runtimeActivityMessage.activity) || {});
  const runtimeOutcome = buildRuntimeOutcomeSummary(runtimeActivity, uiLocale);
  const runtimeActivityHasOutcomeDetails = runtimeActivity.tool_count > 0
    ? Boolean(runtimeActivity.tool_items.length)
    : Boolean(
        Object.keys(runtimeActivity.runtime_outcome || {}).length
        || runtimeActivity.runtime_error.kind
        || runtimeActivity.runtime_error.message
      );
  const runtimeOutcomeNeedsLoad = Boolean(
    runtimeActivityMessage
    && !runtimeActivityMessage.pending
    && !runtimeActivity.activity_loaded
    && !runtimeActivityHasOutcomeDetails
    && (runtimeActivity.trace_ref || runtimeActivity.run_id)
    && (
      runtimeActivity.tool_count > 0
      || ["failed", "blocked", "cancelled"].includes(normalizeProgressStatus(runtimeActivity.status))
    )
  );
  const runtimeOperational = Boolean(hasLiveRuntimeState || currentThreadBusy || runtimeAttentionCount || approvalSubmitting);
  useEffect(() => {
    if (drawerView !== "run" || hasLiveRuntimeState || !runtimeOutcomeNeedsLoad) return;
    const messageId = String((runtimeActivityMessage && runtimeActivityMessage.id) || "").trim();
    if (messageId) ensureRunActivity(messageId);
  }, [
    drawerView,
    hasLiveRuntimeState,
    runtimeOutcomeNeedsLoad,
    sessionId,
    String((runtimeActivityMessage && runtimeActivityMessage.id) || ""),
  ]);
  const activeRuntimeUnits = buildLiveAgentTimelineItems(runtimeActivity, uiLocale)
    .filter((item) => !isActivityTerminalStatus(item.status))
    .slice(-8)
    .reverse();
  const runtimeControlTraceEvents = runtimeActivity.trace_events
    .filter((item) => /^(approval\.|run\.|loop\.|replan\.|subagent\.|llm\.failed|tool\.failed)/.test(String((item && item.type) || "")))
    .slice(-8)
    .reverse();
  const runtimeDecisionEvents = runtimeControlTraceEvents.length
    ? runtimeControlTraceEvents.map((item, index) => ({
        id: String(item.id || `${item.type || "runtime"}-${index}`),
        type: String(item.type || "runtime"),
        text: String(item.title || item.detail || item.type || "runtime"),
        createdAt: item.timestamp ? new Date(item.timestamp).toISOString() : "",
      }))
    : activeRunLogs
        .filter((item) => ["stage", "system", "error"].includes(String((item && item.type) || "")))
        .slice(0, 8);
  const latestRuntimeDebugMessage = (Array.isArray(messages) ? messages : [])
    .slice()
    .reverse()
    .find((item) => item && item.role === "assistant" && !item.pending) || null;
  const baseRunExecutionProgress = buildRunExecutionProgress({
    messages,
    plan: activePlan,
    checkpoint: activeTaskCheckpoint,
    logs: activeRunLogs,
    sending: hasLiveRuntimeState || sending,
    activeRunId,
    activeRunThreadId,
    sessionId,
    locale: uiLocale,
    liveToolTimeline: activeToolTimeline,
    liveHeartbeat: activeLiveHeartbeat,
    lastProgressAt: activeRunProgressAt,
    runStartedAt: activeRunStartedAt,
    hasRunningActivity,
    liveTurnState,
    nowMs: activityClockMs || Date.now(),
  });
  const runExecutionProgress = approvalSubmitting
    ? {
        ...baseRunExecutionProgress,
        status: "approval_submitting",
        statusLabel: t("runtime_panel.approval_submitting"),
        currentAction: t("runtime_panel.approval_submitting"),
      }
    : (hasCommandApproval
      ? {
          ...baseRunExecutionProgress,
          status: "waiting_approval",
          statusLabel: t("runtime_panel.approval_required"),
          currentAction: String(activePendingApproval.purpose || t("runtime_panel.approval_required")),
          command: String(activePendingApproval.command || baseRunExecutionProgress.command || ""),
        }
      : baseRunExecutionProgress);
  const activeProviderAuthValue =
    activeProviderProfile && Object.prototype.hasOwnProperty.call(activeProviderProfile, "auth_ready")
      ? activeProviderProfile.auth_ready
      : (Object.prototype.hasOwnProperty.call(runtimeStatus, "auth_ready") ? runtimeStatus.auth_ready : true);
  const activeProviderAuthReady = activeProviderAuthValue !== false;
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
  const activeContextMeter = normalizeContextMeter(
    (runState && runState.context_meter) ||
    (lastResponse && lastResponse.context_meter) ||
    (sessionRuntimeState && sessionRuntimeState.context_meter) ||
    (health && health.context_meter) ||
    {},
  );
  const activeCompactionStatus = normalizeCompactionStatus(
    (runState && runState.compaction_status) ||
    (lastResponse && lastResponse.compaction_status) ||
    (sessionRuntimeState && sessionRuntimeState.compaction_status) ||
    (health && health.compaction_status) ||
    {},
  );
  const compactionWarningText = formatCompactionWarning(uiLocale, activeCompactionStatus, activeContextMeter);
  const compactionReasonText = formatCompactionReason(uiLocale, activeCompactionStatus.last_compaction_reason);
  const contextMeterColor = resolveContextMeterColor(activeContextMeter);
  const contextStatusSummary = summarizeContextStatus(activeContextMeter, activeCompactionStatus);
  const slashCommandQuery = slashCommandQueryFromDraft(draft);
  const slashCommandSuggestions = slashCommandQuery
    ? SLASH_COMMANDS.filter((item) => item.command.startsWith(slashCommandQuery))
    : [];
  const slashCommandSelectedIndex = slashCommandSuggestions.length
    ? Math.min(Math.max(0, slashCommandActiveIndex), slashCommandSuggestions.length - 1)
    : 0;
  const groupedTools = useMemo(() => groupTools(workbenchTools), [workbenchTools]);
  const groupedSkills = useMemo(() => groupSkillsByScope(skills), [skills]);
  const selectedSkill = shallowSkillList(skills).find((item) => skillKey(item) === selectedSkillId) || null;
  const selectedSkillReadOnly = Boolean(selectedSkill && selectedSkill.read_only);
  const selectedSpec = specs.find((item) => String(item.name || "") === selectedSpecName) || null;
  const displayVersion = normalizeReleaseVersion((health && health.app_version) || "");
  const appUpdateRunning = appUpdateState.status === "running";
  const appUpdateResult = appUpdateState.result && typeof appUpdateState.result === "object" ? appUpdateState.result : null;
  const appUpdateCommands = Array.isArray(appUpdateResult && appUpdateResult.commands) ? appUpdateResult.commands : [];
  const appUpdateErrorText = appUpdateState.error ? String(appUpdateState.error.detail || appUpdateState.error.summary || "") : "";
  const currentThread = sessions.find((item) => String(item.session_id || item.thread_id || "") === String(sessionId || "")) || null;
  const selectableThreadIds = sessions.map(threadListItemId).filter((id) => id && !isTempThreadId(id));
  const selectedThreadIdList = [...selectedThreadIds].filter((id) => selectableThreadIds.includes(id));
  const selectedThreadCount = selectedThreadIdList.length;
  const allVisibleThreadsSelected = Boolean(selectableThreadIds.length && selectedThreadCount === selectableThreadIds.length);
  const totalTurnsForCurrentThread = Math.max(0, Number((currentThread && currentThread.turn_count) || 0) || 0);
  const canLoadEarlierTurns = Boolean(
    sessionId &&
    !isTempThreadId(sessionId) &&
    messages.length > 0 &&
    totalTurnsForCurrentThread > messages.length,
  );
  const showThreadDetailLoading = Boolean(loadingSession && sessionId && !isTempThreadId(sessionId));
  const bootLoadingActive = Boolean(bootState.active);
  const bootLoadingText = bootState.phase === "thread" ? t("boot.loading_thread") : t("boot.loading_workspace");
  const headTitle = sessionId ? sessionTitleFromList(sessions, sessionId, uiLocale) : (workspaceLabel || t("labels.start_building"));
  const headBreadcrumb = [
    workspaceLabel || "",
    currentProjectRoot ? compactPath(currentProjectRoot) : "",
    currentProjectBranch || "",
    loadedSkills.length ? `skills:${loadedSkills.length}` : "no skills",
  ].filter(Boolean).join(" · ");
  const currentThreadLive = isCurrentThreadLiveRun({
    sessionId,
    activeRunThreadId,
    sending,
    activeRunId,
    activeRunStartedAt,
    hasRunningActivity,
    liveTurnState,
  });
  const statusSummary = [
    workspaceLabel || "-",
    activeProviderLabel || activeProvider || "-",
  ].filter(Boolean).join(" · ");
  const showEmptyLivePanel = Boolean(currentThreadLive && !messages.length && !showThreadDetailLoading);
  const runtimeStats = useMemo(() => buildRuntimeStatsSummary({
    locale: uiLocale,
    workspaceLabel,
    runtimeStatus,
    activeModel,
    activeTurnStatus,
    messages,
    activityClockMs,
    hasLiveRuntimeState,
    liveToolTimeline,
    inspectorToolTimeline: lastInspector.tool_timeline,
    fallbackToolTimeline: toolTimeline,
    contextMeter: activeContextMeter,
    maxOutputTokens: chatSettings.max_output_tokens || DEFAULT_SETTINGS.max_output_tokens,
    tokenUsage: (lastResponse && lastResponse.token_usage) || {},
    permissionProfile: activePermissionProfile,
    boundaryModelView: activeBoundaryModelView,
    sessionId,
    activeRunThreadId,
    activeRunStartedAt,
    sending,
    hasRunningActivity,
    liveTurnState,
  }), [
    uiLocale,
    workspaceLabel,
    runtimeStatus,
    activeModel,
    activeTurnStatus,
    messages,
    activityClockMs,
    hasLiveRuntimeState,
    liveToolTimeline,
    lastInspector,
    toolTimeline,
    activeContextMeter,
    chatSettings.max_output_tokens,
    activePermissionProfile,
    activeBoundaryModelView,
    lastResponse,
    sessionId,
    activeRunThreadId,
    activeRunStartedAt,
    sending,
    hasRunningActivity,
    liveTurnState,
  ]);

  async function ensureRunDetail(messageId, view) {
    const sid = String(sessionId || "").trim();
    const turnId = String(messageId || "").trim();
    const detailView = view === "debug" ? "debug" : "activity";
    if (!sid || !turnId || isTempThreadId(sid)) return;
    const currentMessage = (Array.isArray(messages) ? messages : []).find((entry) => String(entry.id || "") === turnId);
    if (!currentMessage || currentMessage.role !== "assistant") return;
    if (currentMessage.pending) return;
    const currentActivity = normalizeMessageActivity(currentMessage.activity || {});
    const alreadyLoaded = detailView === "debug"
      ? Boolean(currentActivity.debug_loaded)
      : Boolean(currentActivity.activity_loaded);
    if (alreadyLoaded || (!currentActivity.trace_ref && !currentActivity.run_id)) return;
    const requestKey = `${sid}:${turnId}:${detailView}`;
    if (runDetailRequestRef.current.has(requestKey)) return;
    runDetailRequestRef.current.add(requestKey);
    setMessages((prev) => {
      const nextMessages = (Array.isArray(prev) ? prev : []).map((entry) => (
        String(entry.id || "") === turnId
          ? {
              ...entry,
              ...(detailView === "debug"
                ? { runDebugLoading: true, runDebugError: "" }
                : { runActivityLoading: true, runActivityError: "" }),
            }
          : entry
      ));
      updateThreadSnapshot(sid, (existing) => ({ ...existing, messages: nextMessages }));
      return nextMessages;
    });
    try {
      const payload = await fetchJson(`/api/thread/${encodeURIComponent(sid)}/turn/${encodeURIComponent(turnId)}?view=${detailView}`);
      const loadedActivity = normalizeMessageActivity({
        ...((payload && payload.activity) || {}),
        activity_loaded: true,
        debug_loaded: detailView === "debug",
      });
      setMessages((prev) => {
        const nextMessages = (Array.isArray(prev) ? prev : []).map((entry) => (
          String(entry.id || "") === turnId
            ? {
                ...entry,
                activity: mergeActivityState(entry.activity || {}, {
                  ...loadedActivity,
                  replace_execution_details: true,
                }),
                ...(detailView === "debug"
                  ? { runDebugLoading: false, runDebugError: "" }
                  : { runActivityLoading: false, runActivityError: "" }),
              }
            : entry
        ));
        const cached = threadDetailCacheRef.current.get(sid);
        if (cached) {
          threadDetailCacheRef.current.set(sid, {
            ...cached,
            messages: nextMessages,
            cachedAt: Date.now(),
          });
        }
        return nextMessages;
      });
    } catch (err) {
      const nextError = normalizeUiError(uiLocale, err, t("errors.load_thread_failed"));
      setMessages((prev) => {
        const nextMessages = (Array.isArray(prev) ? prev : []).map((entry) => (
          String(entry.id || "") === turnId
            ? {
                ...entry,
                ...(detailView === "debug"
                  ? { runDebugLoading: false, runDebugError: String(nextError.summary || t("errors.load_thread_failed")) }
                  : { runActivityLoading: false, runActivityError: String(nextError.summary || t("errors.load_thread_failed")) }),
              }
            : entry
        ));
        updateThreadSnapshot(sid, (existing) => ({ ...existing, messages: nextMessages }));
        return nextMessages;
      });
      pushLogWithLimit(setLogs, "error", t("log.refresh_state_failed", { summary: nextError.summary }));
    } finally {
      runDetailRequestRef.current.delete(requestKey);
    }
  }

  const ensureRunActivity = (messageId) => ensureRunDetail(messageId, "activity");
  const ensureRunDebug = (messageId) => ensureRunDetail(messageId, "debug");

  const toggleMessageActivity = (messageId) => {
    const willOpen = !activityOpenByMessageId[messageId];
    setActivityOpenByMessageId((prev) => ({
      ...prev,
      [messageId]: !prev[messageId],
    }));
    if (willOpen) {
      ensureRunActivity(messageId);
    }
  };

  const toggleMessageDebug = (messageId, open) => {
    const isOpen = Boolean(open);
    setDebugOpenByMessageId((prev) => ({ ...prev, [messageId]: isOpen }));
    if (isOpen) ensureRunDebug(messageId);
  };

  const focusRuntimeInput = () => {
    setDrawerView("");
    window.requestAnimationFrame(() => {
      if (composerInputRef.current) composerInputRef.current.focus();
    });
  };

  const openLatestRuntimeDebug = () => {
    const messageId = String((latestRuntimeDebugMessage && latestRuntimeDebugMessage.id) || "").trim();
    if (!messageId) return;
    setActivityOpenByMessageId((prev) => ({ ...prev, [messageId]: true }));
    setDebugOpenByMessageId((prev) => ({ ...prev, [messageId]: true }));
    setDrawerView("");
    ensureRunDebug(messageId);
  };

  const renderDetailBlock = (label, value, options = {}) => {
    if (!hasDisplayValue(value)) return null;
    const text = displayValueText(value);
    if (!text) return null;
    return html`
      <details className="activity-payload" open=${options.open ? true : undefined}>
        <summary>${label}</summary>
        <pre>${text}</pre>
      </details>
    `;
  };

  const renderToolAuditDetails = (source) => {
    const item = source && typeof source === "object" ? source : {};
    const rawArguments = hasDisplayValue(item.raw_arguments) ? item.raw_arguments : item.input;
    const normalizedArguments = hasDisplayValue(item.normalized_arguments) ? item.normalized_arguments : item.input;
    const validation = item.schema_validation && typeof item.schema_validation === "object" ? item.schema_validation : {};
    const sections = [
      renderDetailBlock(t("activity.raw_tool_call"), item.raw_tool_call),
      renderDetailBlock(t("activity.raw_arguments"), rawArguments),
      renderDetailBlock(t("activity.normalized_arguments"), normalizedArguments),
      renderDetailBlock(t("activity.validation_result"), item.validation_result),
      renderDetailBlock(t("activity.arguments_preview"), item.arguments_preview),
      renderDetailBlock(t("activity.preview_error"), item.preview_error),
      renderDetailBlock(
        `${t("activity.schema_validation")} · ${formatValidationStatus(uiLocale, validation.status || "missing")}`,
        validation,
      ),
      renderDetailBlock(t("activity.result_preview"), item.result_preview),
      renderDetailBlock(t("activity.stream_diagnostics"), item.stream_diagnostics),
    ].filter(Boolean);
    if (!sections.length) return null;
    return html`<div className="activity-structured-details">${sections}</div>`;
  };

  const renderPlanDetails = (label, source) => {
    const item = source && typeof source === "object" ? source : {};
    if (!Object.keys(item).length) return null;
    return renderDetailBlock(label, item);
  };

  const renderRevisionSummaryDetails = (source) => {
    const summary = source && typeof source === "object" ? source : {};
    const items = Array.isArray(summary.items) ? summary.items : [];
    if (!items.length) return null;
    return html`
      <details className="activity-payload" open>
        <summary>${t("activity.revision_summary")}</summary>
        <div className="activity-structured-details">
          ${items.map((entry, index) => {
            const item = entry && typeof entry === "object" ? entry : {};
            const lines = [];
            if (item.original_excerpt) lines.push(`${t("activity.original_excerpt")}: ${String(item.original_excerpt)}`);
            if (item.result_excerpt) lines.push(`${t("activity.result_excerpt")}: ${String(item.result_excerpt)}`);
            if (item.reason) lines.push(`${t("activity.reason")}: ${String(item.reason)}`);
            if (item.task_type || summary.task_type) lines.push(`task_type: ${String(item.task_type || summary.task_type || "")}`);
            return html`
              <details key=${`revision-summary-${index}`} className="activity-payload" open=${index === 0 ? true : undefined}>
                <summary>${String(item.label || `${t("activity.revision_summary")} ${index + 1}`)}</summary>
                <pre>${lines.join("\n")}</pre>
              </details>
            `;
          })}
        </div>
      </details>
    `;
  };

  const renderExecutionTraceDetails = (source) => {
    const entries = Array.isArray(source) ? source : [];
    if (!entries.length) return null;
    return html`
      <details className="activity-payload" open>
        <summary>${t("activity.execution_trace")}</summary>
        <div className="activity-structured-details">
          ${entries.map((entry, index) => {
            const item = entry && typeof entry === "object" ? entry : {};
            const lines = [];
            if (item.action_type) lines.push(`action_type: ${String(item.action_type)}`);
            if (item.status) lines.push(`status: ${String(item.status)}`);
            if (item.tool_name) lines.push(`tool_name: ${String(item.tool_name)}`);
            if (Array.isArray(item.tool_names) && item.tool_names.length) lines.push(`tool_names: ${item.tool_names.join(", ")}`);
            if (item.result_summary) lines.push(`${t("activity.result_preview")}: ${String(item.result_summary)}`);
            if (item.observation_summary) lines.push(`${t("activity.observation_summary")}: ${String(item.observation_summary)}`);
            if (item.error) lines.push(`error: ${String(item.error)}`);
            return html`
              <details key=${`execution-trace-${index}`} className="activity-payload" open=${index === entries.length - 1 ? true : undefined}>
                <summary>${String(item.title || `${t("activity.execution_trace")} ${index + 1}`)}</summary>
                <pre>${lines.join("\n")}</pre>
              </details>
            `;
          })}
        </div>
      </details>
    `;
  };

  const renderActivityPayload = (trace, options = {}) => {
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    const rawOnly = Boolean(options.rawOnly);
    const modelAction = payload.model_action;
    const executionTrace = Array.isArray(payload.execution_trace)
      ? payload.execution_trace
      : (payload.execution_trace_entry ? [payload.execution_trace_entry] : []);
    const structuredSections = rawOnly
      ? [
          renderToolAuditDetails(payload),
        ].filter(Boolean)
      : [
          renderPlanDetails(t("activity.model_action"), modelAction),
          renderExecutionTraceDetails(executionTrace),
          renderRevisionSummaryDetails(payload.revision_summary),
          renderToolAuditDetails(payload),
          renderPlanDetails(t("activity.runtime_boundary"), payload.runtime_boundary),
        ].filter(Boolean);
    const payloadText = stringifyCompactJson(payload);
    const hasPayloadText = Boolean(payloadText && payloadText !== "{}");
    if (!structuredSections.length && !hasPayloadText) return null;
    return html`
      <div className="activity-payload-group">
        ${structuredSections}
        ${hasPayloadText
          ? html`
              <details className="activity-payload">
                <summary>${t("labels.payload")}</summary>
                <pre>${payloadText}</pre>
              </details>
            `
          : null}
      </div>
    `;
  };

  const renderActivityProgressList = (projection, activity, options = {}) => {
    const item = normalizeMessageActivity(activity || {});
    const progressItems = Array.isArray(projection && projection.progress_items) ? projection.progress_items : [];
    const planItems = Array.isArray(projection && projection.plan_items) ? projection.plan_items : [];
    const mainLiveCards = Array.isArray(projection && projection.main_live_cards) ? projection.main_live_cards : progressItems;
    const completionSummary = (projection && projection.completion_summary && typeof projection.completion_summary === "object")
      ? projection.completion_summary
      : {};
    const preview = Boolean(options.preview);
    const suppressNoteText = String(options.suppressNoteText || "").trim();
    const isTerminal = isActivityTerminalStatus(item.status);
    const normalizedStatus = normalizeProgressStatus(item.status);
    const suppressPreview = Boolean(options.suppressPreview) && preview;
    const suppressCompletedPreview = Boolean(options.suppressCompletedPreview) && preview && normalizedStatus === "completed";
    const toolGroups = Array.isArray(projection && projection.tool_groups) ? projection.tool_groups : [];
    const isToolProgressEntry = (entry) => {
      const item = entry && typeof entry === "object" ? entry : {};
      const rawRef = item.rawRef && typeof item.rawRef === "object" ? item.rawRef : {};
      const liveItem = item.live_item && typeof item.live_item === "object"
        ? item.live_item
        : (rawRef.live_item && typeof rawRef.live_item === "object" ? rawRef.live_item : {});
      const type = String(item.type || rawRef.type || liveItem.type || "").trim();
      return Boolean(
        item.source === "tool"
        || rawRef.source === "tool"
        || item.tool_group
        || rawRef.tool_group
        || item.tool
        || liveItem.tool
        || type.startsWith("tool.")
        || type.startsWith("action.")
        || type === "observation.returned"
      );
    };
    const expandedProgressItems = toolGroups.length
      ? progressItems.filter((entry) => !isToolProgressEntry(entry))
      : progressItems;
    const recentExecutionItems = (preview ? mainLiveCards : expandedProgressItems).slice(-MAIN_LIVE_CARD_LIMIT);
    const visibleItems = preview
      ? (suppressPreview || isTerminal ? [] : recentExecutionItems)
      : recentExecutionItems;
    const visiblePlanItems = preview
      ? (isTerminal ? [] : planItems.slice(0, COMPACT_PLAN_ITEM_LIMIT))
      : planItems;
    const planCompletedCount = planItems.filter((entry) => normalizeProgressStatus(entry.status) === "completed").length;
    const showPlanSummary = Boolean(planItems.length);
    const planProgressLabel = showPlanSummary
      ? translateUi(uiLocale, "run.plan_progress", { completed: planCompletedCount, total: planItems.length })
      : "";
    const planOverflowCount = preview && !isTerminal
      ? Math.max(0, planItems.length - visiblePlanItems.length)
      : 0;
    const showLiveStatusPanel = Boolean(
      preview
      && showPlanSummary
      && !isTerminal
      && (hasLiveRuntimeState || currentThreadBusy),
    );
    const showExecutionDivider = Boolean(
      showPlanSummary && (visibleItems.length || showLiveStatusPanel),
    );
    const durationLabel = formatActivityDuration(item, activityClockMs || Date.now(), uiLocale);
    const liveSummary = resolveLiveSummary(item, projection, uiLocale);
    const liveSummaryText = suppressPreview || suppressCompletedPreview ? "" : formatLiveSummaryText(liveSummary);
    const note = String(
      (suppressPreview ? "" : (projection && projection.revision_badge))
      || (!suppressPreview && normalizedStatus === "completed" && !suppressCompletedPreview ? completionSummary.label : "")
      || liveSummaryText
      || (suppressPreview ? "" : item.activity_summary)
      || "",
    ).trim();
    const showNote = Boolean(note) && !(preview && suppressNoteText && note === suppressNoteText);
    if (!visibleItems.length && !visiblePlanItems.length && !showNote && !showPlanSummary) return null;
    const markerForStatus = (status) => {
      const normalized = normalizeProgressStatus(status);
      if (normalized === "completed") return "✓";
      if (normalized === "failed" || normalized === "blocked" || normalized === "cancelled") return "!";
      return "○";
    };
    const renderProgressItems = (entries) => entries.length
      ? html`
          <div className="activity-progress-list">
            ${entries.map((entry) => {
              const status = normalizeProgressStatus(entry.status);
              const tone = activityToneClass(status);
              const title = String(entry.label || entry.title || "").trim()
                || translateUiOrFallback(uiLocale, "activity.tool_title.use_tool", "调用工具");
              const detail = String(entry.detail || entry.target || "").trim();
              return html`
                <div key=${entry.id} className=${`activity-progress-item tone-${tone} status-${status}`}>
                  <span className="activity-progress-marker" aria-hidden="true">${markerForStatus(status)}</span>
                  <div className="activity-progress-copy">
                    <div className="activity-progress-label">${title}</div>
                    ${detail ? html`<div className="activity-progress-detail">${detail}</div>` : null}
                  </div>
                </div>
              `;
            })}
          </div>
        `
      : null;
    return html`
      <div className="activity-progress">
        ${preview
          ? null
          : html`
              <div className="activity-progress-head">
                <div className="activity-progress-title">${t("activity.progress_title")}</div>
                ${durationLabel ? html`<div className="activity-progress-duration">${durationLabel}</div>` : null}
              </div>
            `}
        ${showPlanSummary
          ? html`
              <div className="activity-progress-section-title">
                ${preview ? planProgressLabel : `${t("run.checklist")} · ${planProgressLabel}`}
              </div>
            `
          : null}
        ${renderProgressItems(visiblePlanItems)}
        ${planOverflowCount
          ? html`<div className="activity-flow-note">${t("activity.more_steps", { count: planOverflowCount })}</div>`
          : null}
        ${showExecutionDivider
          ? html`<div className="activity-progress-divider" role="separator" aria-hidden="true"></div>`
          : null}
        ${showLiveStatusPanel
          ? html`
              <div className="activity-live-status" role="status" aria-live="polite">
                <div className="activity-live-status-head">
                  <span className=${`live-run-dot status-${runExecutionProgress.status || "running"}`} aria-hidden="true"></span>
                  <strong>${runExecutionProgress.statusLabel || t("activity.running")}</strong>
                  ${runExecutionProgress.elapsed ? html`<span>${runExecutionProgress.elapsed}</span>` : null}
                </div>
                <div className="activity-live-status-action">
                  ${runExecutionProgress.currentAction || runExecutionProgress.recentEvent || t("run.progress.background_running")}
                </div>
                <div className="activity-live-status-meta">
                  ${runExecutionProgress.currentStep
                    ? html`<span>${formatRunFieldLabel(uiLocale, "current_step")}: ${runExecutionProgress.currentStep}</span>`
                    : null}
                  ${runExecutionProgress.currentTool
                    ? html`<span>${formatRunFieldLabel(uiLocale, "current_tool")}: ${runExecutionProgress.currentTool}</span>`
                    : null}
                  <span>${formatRunFieldLabel(uiLocale, "connection")}: ${runExecutionProgress.connectionLabel}</span>
                  ${runExecutionProgress.recentEvent && runExecutionProgress.recentEvent !== runExecutionProgress.currentAction
                    ? html`<span>${runExecutionProgress.recentEvent}</span>`
                    : null}
                </div>
              </div>
            `
          : null}
        ${!preview && visibleItems.length ? html`<div className="activity-progress-section-title">${t("run.execution_progress")}</div>` : null}
        ${renderProgressItems(visibleItems)}
        ${showNote ? html`<div className="activity-flow-note">${note}</div>` : null}
      </div>
    `;
  };

  const traceDurationLabel = (durationMs) => {
    const value = Math.max(0, Number(durationMs || 0) || 0);
    if (!value) return "-";
    if (value < 1000) return `${Math.round(value)} ms`;
    return formatElapsedSeconds(Math.max(1, Math.round(value / 1000)), uiLocale);
  };

  const renderTraceDetails = (step) => {
    if (!step || typeof step !== "object") return null;
    const rows = [
      [t("activity.debug.trace_status"), String(step.status || "-")],
      [t("activity.debug.trace_duration"), traceDurationLabel(step.duration_ms)],
      ...(hasDisplayValue(step.validation)
        ? [[t("activity.debug.trace_validation"), displayValueText(step.validation)]]
        : []),
      [t("activity.debug.trace_error_kind"), String(step.error_kind || "-")],
      [t("activity.debug.trace_retry"), String(step.retry_count || 0)],
      [t("activity.debug.trace_recovery"), String(step.recovery_result || "-")],
      ["assistant_item_id", String(step.requested_by_item_id || "-")],
      ["tool_call_id", String(step.tool_call_id || step.id || "-")],
      ["tool_result_item_id", String(step.item_id || "-")],
    ];
    return html`
      <div className="thread-trace-grid">
        ${rows.map(([label, value]) => html`
          <div className="thread-trace-row" key=${label}>
            <span>${label}</span>
            <code>${value}</code>
          </div>
        `)}
      </div>
    `;
  };

  const renderActivityToolDetails = (message, projection) => {
    const messageId = String((message && message.id) || "");
    const toolGroups = Array.isArray(projection && projection.tool_groups) ? projection.tool_groups : [];
    if (!toolGroups.length) return null;
    return html`
      <details className="activity-tool-transactions">
        <summary>${t("activity.debug.tool_execution")} · ${toolGroups.length}</summary>
        <div className="activity-tool-transaction-list">
          ${toolGroups.map((toolItem, index) => {
            const status = normalizeProgressStatus(toolItem.status);
            const marker = status === "completed" ? "✓" : (["failed", "blocked", "cancelled"].includes(status) ? "!" : "○");
            const target = toolCallTargetFromSource(toolItem);
            const toolName = String(toolItem.tool_name || "tool");
            const transactionLabel = target && target !== toolName ? `${toolName} · ${target}` : toolName;
            const rawArguments = hasDisplayValue(toolItem.raw_arguments) ? toolItem.raw_arguments : {};
            const normalizedArguments = hasDisplayValue(toolItem.normalized_arguments) ? toolItem.normalized_arguments : {};
            const effectiveArguments = hasDisplayValue(normalizedArguments) ? normalizedArguments : rawArguments;
            const argumentsChanged = Boolean(
              hasDisplayValue(rawArguments)
              && hasDisplayValue(normalizedArguments)
              && displayValueText(rawArguments) !== displayValueText(normalizedArguments),
            );
            const resultSummary = String(toolItem.summary || toolItem.detail || "").trim();
            const durationLabel = traceDurationLabel(toolItem.duration_ms);
            const statusLabel = formatRunEnum(uiLocale, "turn_status", status, status || "-");
            return html`
              <details
                key=${toolItem.id || `${messageId}-tool-${index}`}
                className=${`activity-tool-transaction status-${status}`}
              >
                <summary>
                  <span className="activity-tool-transaction-marker" aria-hidden="true">${marker}</span>
                  <span>${transactionLabel}</span>
                </summary>
                <div className="activity-tool-transaction-body">
                  <div className="activity-tool-transaction-summary">
                    <span>${statusLabel}</span>
                    ${durationLabel !== "-" ? html`<span>${durationLabel}</span>` : null}
                  </div>
                  ${resultSummary ? html`<div className="activity-tool-result-summary">${resultSummary}</div>` : null}
                  ${renderDetailBlock(t("activity.parameters"), effectiveArguments)}
                  ${renderDetailBlock(t("activity.result_preview"), toolItem.result_preview, {
                    open: ["failed", "blocked", "cancelled"].includes(status),
                  })}
                  <details className="activity-tool-trace-details">
                    <summary>${t("activity.debug.view_trace")}</summary>
                    <div className="activity-tool-trace-body">
                      <div className="activity-tool-call-id">
                        <span>${t("activity.debug.tool_call_id")}</span>
                        <code>${toolItem.id || "-"}</code>
                      </div>
                      ${argumentsChanged ? renderDetailBlock(t("activity.raw_arguments"), rawArguments) : null}
                      ${argumentsChanged ? renderDetailBlock(t("activity.normalized_arguments"), normalizedArguments) : null}
                      ${renderDetailBlock(t("activity.validation_result"), toolItem.validation_result)}
                      ${renderDetailBlock(
                        `${t("activity.schema_validation")} · ${formatValidationStatus(uiLocale, (toolItem.schema_validation || {}).status || "missing")}`,
                        toolItem.schema_validation,
                      )}
                      ${renderTraceDetails(toolItem)}
                    </div>
                  </details>
                </div>
              </details>
            `;
          })}
        </div>
      </details>
    `;
  };

  const renderActivityDebugDetails = (message) => {
    const activity = normalizeMessageActivity((message && message.activity) || {});
    const messageId = String((message && message.id) || "");
    const threadItems = Array.isArray(activity.thread_items) ? activity.thread_items : [];
    const turnTrace = activity.turn_trace && typeof activity.turn_trace === "object" ? activity.turn_trace : {};
    const traceSteps = Array.isArray(turnTrace.steps) ? turnTrace.steps : [];
    const contexts = Array.isArray(turnTrace.contexts) ? turnTrace.contexts : [];
    const legacyExchanges = Array.isArray(activity.llm_exchanges) ? activity.llm_exchanges : [];
    const runtimeInspector = activity.runtime_inspector && typeof activity.runtime_inspector === "object"
      ? activity.runtime_inspector
      : {};
    const runtimeRunState = runtimeInspector.run_state && typeof runtimeInspector.run_state === "object"
      ? runtimeInspector.run_state
      : {};
    const debugPendingApproval = runtimeRunState.pending_approval && typeof runtimeRunState.pending_approval === "object"
      ? runtimeRunState.pending_approval
      : {};
    const debugPendingInput = runtimeRunState.pending_user_input && typeof runtimeRunState.pending_user_input === "object"
      ? runtimeRunState.pending_user_input
      : {};
    const runtimeControlEvents = activity.trace_events.filter((item) => (
      /^(approval\.|run\.|loop\.|replan\.|subagent\.|llm\.failed|tool\.failed)/
        .test(String((item && item.type) || ""))
    ));
    const traceStepByItemId = new Map(
      traceSteps
        .filter((step) => step && step.item_id)
        .map((step) => [String(step.item_id), step]),
    );
    const toolCallOwner = new Map();
    threadItems.forEach((item) => {
      if (String((item && item.role) || "") !== "assistant") return;
      (Array.isArray(item.tool_calls) ? item.tool_calls : []).forEach((call) => {
        const callId = String((call && call.id) || "");
        if (callId) toolCallOwner.set(callId, item);
      });
    });

    const roleLabel = (role) => translateUiOrFallback(
      uiLocale,
      `activity.debug.thread_role.${String(role || "")}`,
      String(role || ""),
    );
    const renderThreadItem = (item, index) => {
      const role = String((item && item.role) || "");
      const itemId = String((item && item.id) || `thread-item-${index}`);
      const content = String((item && item.content) || "");
      const toolCalls = Array.isArray(item && item.tool_calls) ? item.tool_calls : [];
      const traceStep = traceStepByItemId.get(itemId) || null;
      const toolCallId = String((item && item.tool_call_id) || "");
      const owner = toolCallOwner.get(toolCallId) || null;
      return html`
        <div className=${`thread-history-item role-${role}`} key=${itemId}>
          <div className="thread-history-item-head">
            <strong>${roleLabel(role)}${role === "tool" && item.name ? ` · ${item.name}` : ""}</strong>
            <code>${itemId}</code>
          </div>
          ${content ? html`<pre className="thread-history-content">${content}</pre>` : null}
          ${toolCalls.map((call, callIndex) => html`
            <details className="thread-tool-call" key=${String(call.id || `${itemId}-call-${callIndex}`)}>
              <summary>${t("activity.debug.tool_call")} · ${String(call.name || "tool")}</summary>
              <div className="thread-tool-call-meta"><code>${String(call.id || "-")}</code></div>
              ${renderDetailBlock(t("activity.raw_arguments"), call.args || {})}
            </details>
          `)}
          ${role === "tool" && owner ? html`
            <div className="thread-tool-link">
              ${t("activity.debug.requested_by")} <code>${String(owner.id || "-")}</code>
            </div>
          ` : null}
          ${role === "tool" && traceStep ? html`
            <details className="thread-trace-details">
              <summary>${t("activity.debug.view_trace")}</summary>
              ${renderTraceDetails(traceStep)}
            </details>
          ` : null}
        </div>
      `;
    };

    const threadHistory = threadItems.length
      ? html`
          <section className="thread-history-debug">
            <div className="thread-history-title">${t("activity.debug.thread_history")}</div>
            <div className="thread-history-list">
              ${threadItems.map(renderThreadItem)}
            </div>
          </section>
        `
      : null;

    const safeApprovalDebug = Object.keys(debugPendingApproval).length
      ? {
          type: String(debugPendingApproval.type || ""),
          tool_call_id: String(debugPendingApproval.tool_call_id || ""),
          purpose: String(debugPendingApproval.purpose || ""),
          command: String(debugPendingApproval.command || ""),
          cwd: String(debugPendingApproval.cwd || ""),
          risk_count: Array.isArray(debugPendingApproval.risks) ? debugPendingApproval.risks.length : 0,
          file_count: Array.isArray(debugPendingApproval.files) ? debugPendingApproval.files.length : 0,
        }
      : {};
    const safePendingInputDebug = Object.keys(debugPendingInput).length && !Object.keys(debugPendingApproval).length
      ? {
          type: String(debugPendingInput.type || ""),
          tool_call_id: String(debugPendingInput.tool_call_id || ""),
          summary: String(debugPendingInput.summary || ""),
          questions: (Array.isArray(debugPendingInput.questions) ? debugPendingInput.questions : []).map((item) => ({
            id: String((item && item.id) || ""),
            header: String((item && item.header) || ""),
            question: String((item && item.question) || ""),
            options: (Array.isArray(item && item.options) ? item.options : []).map((option) => String((option && option.label) || "")).filter(Boolean),
          })),
        }
      : {};
    const runtimeControls = Object.keys(runtimeRunState).length || runtimeControlEvents.length
      ? html`
          <section className="thread-runtime-debug">
            <div className="thread-history-title">${t("activity.debug.runtime_controls")}</div>
            <div className="thread-trace-grid">
              <div className="thread-trace-row">
                <span>${t("activity.debug.runtime_phase")}</span>
                <code>${String(runtimeRunState.phase || "-")}</code>
              </div>
              <div className="thread-trace-row">
                <span>${t("activity.debug.trace_status")}</span>
                <code>${String(runtimeRunState.turn_status || activity.status || "-")}</code>
              </div>
              ${runtimeRunState.blocked_reason
                ? html`
                    <div className="thread-trace-row">
                      <span>${t("activity.debug.blocked_reason")}</span>
                      <code>${String(runtimeRunState.blocked_reason)}</code>
                    </div>
                  `
                : null}
            </div>
            ${renderDetailBlock(t("activity.debug.pending_approval"), safeApprovalDebug, { open: true })}
            ${renderDetailBlock(t("activity.debug.pending_user_input"), safePendingInputDebug, { open: true })}
            ${runtimeControlEvents.length
              ? html`
                  <details className="activity-payload" open>
                    <summary>${t("activity.debug.control_events")} · ${runtimeControlEvents.length}</summary>
                    <div className="runtime-debug-event-list">
                      ${runtimeControlEvents.map((item, index) => html`
                        <div key=${item.id || `${item.type || "runtime"}-${index}`} className="runtime-debug-event-row">
                          <code>${String(item.type || "runtime")}</code>
                          <span>${String(item.title || item.detail || item.status || "")}</span>
                        </div>
                      `)}
                    </div>
                  </details>
                `
              : null}
          </section>
        `
      : null;

    const legacySystemMessages = legacyExchanges
      .flatMap((exchange) => Array.isArray(exchange && exchange.sent_messages_exact) ? exchange.sent_messages_exact : [])
      .filter((item) => String((item && item.role) || "") === "system")
      .map((item) => String((item && item.content) || ""))
      .filter(Boolean);
    const systemPromptContexts = contexts.length
      ? contexts
      : (legacySystemMessages.length ? [{ context_id: "legacy-context", system_message: legacySystemMessages[0] }] : []);
    const systemPromptGroupsByText = new Map();
    systemPromptContexts.forEach((context, index) => {
      const systemMessage = String((context && context.system_message) || "");
      const groupKey = systemMessage || `empty-system-prompt-${index}`;
      const normalizedContext = {
        ...context,
        context_id: String((context && context.context_id) || `context-${index + 1}`),
        supporting_messages: Array.isArray(context && context.supporting_messages) ? context.supporting_messages : [],
        tool_names: Array.isArray(context && context.tool_names) ? context.tool_names : [],
      };
      if (systemPromptGroupsByText.has(groupKey)) {
        systemPromptGroupsByText.get(groupKey).contexts.push(normalizedContext);
      } else {
        systemPromptGroupsByText.set(groupKey, {
          system_message: systemMessage,
          contexts: [normalizedContext],
        });
      }
    });
    const systemPromptGroups = Array.from(systemPromptGroupsByText.values());
    const systemPrompt = systemPromptGroups.length
      ? html`
          <details className="system-prompt-debug">
            <summary>${t("activity.debug.view_system_prompt")}</summary>
            ${systemPromptGroups.map((group, groupIndex) => html`
              <div className="system-prompt-context" key=${`system-prompt-${groupIndex}`}>
                <div className="system-prompt-context-head">
                  <strong>${t("activity.debug.base_system_prompt")}</strong>
                  ${group.contexts.length > 1
                    ? html`<code>${group.contexts.map((context) => context.context_id).join(" · ")}</code>`
                    : null}
                </div>
                <pre>${group.system_message}</pre>
                ${group.contexts.length > 1
                  ? html`
                      <div className="system-prompt-variants">
                        <div className="system-prompt-variants-title">${t("activity.debug.context_variants")}</div>
                        ${group.contexts.map((context) => html`
                          <details className="system-prompt-variant" key=${context.context_id}>
                            <summary>
                              <code>${context.context_id}</code>
                              <span>${t("activity.debug.context_summary", {
                                messages: context.supporting_messages.length,
                                tools: context.tool_names.length,
                              })}</span>
                            </summary>
                            ${renderDetailBlock(t("activity.debug.supporting_messages"), context.supporting_messages)}
                            ${renderDetailBlock(t("activity.debug.available_tools"), context.tool_names)}
                          </details>
                        `)}
                      </div>
                    `
                  : null}
              </div>
            `)}
          </details>
        `
      : null;
    const loadError = String((message && message.runDebugError) || "").trim();
    const loading = Boolean(message && message.runDebugLoading);
    const canLoad = Boolean(activity.trace_ref || activity.run_id);
    if (!canLoad && !threadHistory && !runtimeControls && !systemPrompt && !loadError && !loading) return null;
    return html`
      <details
        className="activity-debug-drawer"
        open=${Boolean(debugOpenByMessageId[messageId])}
        onToggle=${(event) => toggleMessageDebug(messageId, Boolean(event.currentTarget && event.currentTarget.open))}
      >
        <summary>${t("activity.debug_details")}</summary>
        <div className="activity-debug-sections">
          ${loading ? html`<div className="activity-flow-note">${t("activity.debug_loading")}</div>` : null}
          ${loadError ? html`<div className="status-error">${loadError}</div>` : null}
          ${threadHistory}
          ${runtimeControls}
          ${systemPrompt}
        </div>
      </details>
    `;
  };

  const renderMessageActivity = (item) => {
    if (!item || item.role !== "assistant") return null;
    const activity = normalizeMessageActivity(item.activity || {});
    const isDisplayLiveAssistant = Boolean(
      hasLiveRuntimeState
      && liveAssistantMessageId
      && String(item.id || "") === liveAssistantMessageId
    );
    const displayActivity = isDisplayLiveAssistant
      ? buildLiveDisplayActivity(activity, {
          sessionId,
          activeRunThreadId,
          sending,
          activeRunId,
          activeRunStartedAt,
          hasRunningActivity,
          liveTurnState,
          liveHeartbeat: activeLiveHeartbeat,
        })
      : activity;
    const projection = buildActivityProjection(displayActivity, uiLocale, activityClockMs || Date.now());
    const hasActivity = Boolean(
      projection.progress_items.length
      || projection.trace_events.length
      || displayActivity.llm_exchanges.length
      || displayActivity.turn_started_at
      || displayActivity.started_at
      || displayActivity.status
      || displayActivity.run_duration_ms
      || displayActivity.activity_summary,
    );
    if (!hasActivity) return null;
    const isOpen = Boolean(activityOpenByMessageId[item.id]);
    const tone = activityToneClass(displayActivity.status);
    const pillLabel = activityPillLabel(uiLocale, displayActivity, activityClockMs || Date.now());
    const pendingFallback = pendingAssistantFallbackState({ ...item, activity: displayActivity }, uiLocale, activityClockMs || Date.now());
    const hasVisibleAnswerContent = Boolean(String(
      displayActivity.final_answer
      || displayActivity.model_draft
      || (!item.pending ? item.text : "")
      || "",
    ).trim());
    const subagentCards = displayActivity.live_items
      .filter((liveItem) => String(liveItem.type || "") === "subagent")
      .map((liveItem, index) => {
        const raw = liveItem.raw && typeof liveItem.raw === "object" ? liveItem.raw : {};
        const running = !isActivityTerminalStatus(liveItem.status);
        const role = String(raw.role || "explorer");
        const title = String(raw.label || liveItem.label || raw.task || t("subagent.title"));
        const summary = String(raw.summary || liveItem.detail || "");
        return html`
          <details
            key=${liveItem.id || `${item.id}-subagent-${index}`}
            className=${`subagent-card ${running ? "running" : "completed"}`}
            open=${running}
          >
            <summary>
              <span>${t("subagent.title")} · ${role}</span>
              <span>${running ? t("subagent.running") : t("subagent.completed")}</span>
            </summary>
            <div className="subagent-card-task">${title}</div>
            ${summary
              ? html`<div className="subagent-card-result message-markdown" dangerouslySetInnerHTML=${{ __html: renderMessageHtml(summary, `${item.id}-subagent-${index}`) }}></div>`
              : html`<div className="subagent-card-result muted">${t("subagent.waiting_result")}</div>`}
          </details>
        `;
      });
    return html`
      <div className=${`message-activity tone-${tone} ${isOpen ? "open" : ""}`}>
        <button
          className=${`activity-pill tone-${tone}`}
          type="button"
          aria-expanded=${isOpen ? "true" : "false"}
          onClick=${() => toggleMessageActivity(item.id)}
        >
          <span>${pillLabel}</span>
          <span className="activity-pill-arrow">${isOpen ? "−" : ">"}</span>
        </button>
        ${subagentCards.length ? html`<div className="subagent-card-list">${subagentCards}</div>` : null}
        ${!isOpen
          ? renderActivityProgressList(projection, displayActivity, {
              preview: true,
              suppressPreview: hasVisibleAnswerContent,
              suppressCompletedPreview: Boolean(!item.pending && String(displayActivity.final_answer || item.text || "").trim()),
              suppressNoteText: pendingFallback.fromSummaryFallback ? (pendingFallback.suppressNoteText || pendingFallback.text) : "",
            })
          : null}
        ${isOpen
          ? html`
              <div className="activity-panel">
                <div className="activity-panel-head">
                  <div className="activity-panel-title">${t("activity.title")}</div>
                  <div className=${`activity-badge tone-${tone}`}>${pillLabel}</div>
                </div>
                ${item.runActivityLoading ? html`<div className="activity-flow-note">${t("activity.loading_execution")}</div>` : null}
                ${item.runActivityError ? html`<div className="status-error">${item.runActivityError}</div>` : null}
                ${renderActivityProgressList(projection, displayActivity)}
                ${renderActivityToolDetails(item, projection)}
                ${renderActivityDebugDetails(item)}
              </div>
            `
          : null}
      </div>
    `;
  };

  const renderSteerStatus = (item) => {
    if (!item || item.role !== "user") return null;
    const status = String(((item.activity || {}).status) || "");
    if (!["steer_queued", "steer_accepted", "steer_rejected"].includes(status)) return null;
    const label = status === "steer_accepted"
      ? t("steer.accepted")
      : (status === "steer_rejected" ? t("steer.rejected") : t("steer.queued"));
    return html`<div className=${`steer-status ${status}`}>${label}</div>`;
  };

  const messageBodyText = (item) => {
    const isDisplayLiveAssistant = Boolean(
      item
      && item.role === "assistant"
      && hasLiveRuntimeState
      && liveAssistantMessageId
      && String(item.id || "") === liveAssistantMessageId
    );
    if (isDisplayLiveAssistant) {
      const displayActivity = buildLiveDisplayActivity(item.activity || {}, {
        sessionId,
        activeRunThreadId,
        sending,
        activeRunId,
        activeRunStartedAt,
        hasRunningActivity,
        liveTurnState,
        liveHeartbeat: activeLiveHeartbeat,
      });
      return pendingAssistantFallbackState({ ...item, activity: displayActivity }, uiLocale, activityClockMs || Date.now()).text;
    }
    return pendingAssistantFallbackState(item, uiLocale, activityClockMs || Date.now()).text;
  };

  const handleCopyMessage = async (item) => {
    const messageId = String((item && item.id) || "");
    const text = String(messageBodyText(item) || "");
    if (!messageId || !text.trim()) return;
    const copied = await copyTextToClipboard(text);
    if (!copied) return;
    setCopiedMessageId(messageId);
    if (copiedMessageTimerRef.current) window.clearTimeout(copiedMessageTimerRef.current);
    copiedMessageTimerRef.current = window.setTimeout(() => {
      setCopiedMessageId((current) => (current === messageId ? "" : current));
    }, 1400);
  };

  return html`
    <div className="app-root-frame">
    <div className="workspace-shell" id="appShell" aria-hidden=${bootLoadingActive ? "true" : undefined}>
      <aside className=${`thread-rail ${mobileThreadsOpen ? "mobile-open" : ""}`} id="threadSidebar">
        <div className="rail-brand">
          <div className="brand-mark">VP</div>
          <div>
            <div className="brand-title">Vintage Programmer</div>
            <div className="brand-subline">
              <div className="brand-sub">${workspaceLabel || t("brand.no_project_selected")}</div>
              ${displayVersion ? html`<span className="brand-version-badge">${displayVersion}</span>` : null}
            </div>
          </div>
          <button className="rail-close mobile-only" type="button" onClick=${() => setMobileThreadsOpen(false)}>×</button>
        </div>

        <div className="rail-actions">
          <button className="solid-btn" type="button" onClick=${handleNewSession} disabled=${creatingThread}>${t("buttons.new_thread")}</button>
          <button
            className="ghost-btn"
            type="button"
            onClick=${handleAppUpdate}
            disabled=${anyThreadBusy || appUpdateRunning}
            title=${t("update.discards_local_changes")}
          >
            ${appUpdateRunning ? t("update.running") : t("update.button")}
          </button>
        </div>

        ${appUpdateState.status !== "idle"
          ? html`
              <section className=${`rail-update-result status-${appUpdateState.status}`}>
                <div className="rail-update-title">
                  ${appUpdateRunning ? t("update.running") : (appUpdateResult && appUpdateResult.ok ? t("update.success") : t("update.failed"))}
                </div>
                ${appUpdateResult
                  ? html`
                      <div className="rail-update-line">${String(appUpdateResult.before || "-")} → ${String(appUpdateResult.after || "-")}</div>
                      <div className="rail-update-line">${t("update.branch")}: ${String(appUpdateResult.branch || "-")}</div>
                      <div className="rail-update-hint">${appUpdateResult.ok ? t("update.restart_hint") : String(appUpdateResult.message || "")}</div>
                    `
                  : null}
                ${appUpdateErrorText ? html`<div className="rail-update-hint">${appUpdateErrorText}</div>` : null}
                ${appUpdateCommands.length
                  ? html`
                      <details className="rail-update-details">
                        <summary>${t("update.details")}</summary>
                        ${appUpdateCommands.map((item, index) => html`
                          <div key=${`${item.command || "cmd"}-${index}`} className="rail-update-command">
                            <div>${t("update.command")}: ${String(item.command || "")}</div>
                            <div>${t("update.exit_code")}: ${String(item.exit_code ?? "")}</div>
                            ${item.stdout ? html`<pre>${t("update.stdout")}: ${String(item.stdout).slice(0, 4000)}</pre>` : null}
                            ${item.stderr ? html`<pre>${t("update.stderr")}: ${String(item.stderr).slice(0, 4000)}</pre>` : null}
                          </div>
                        `)}
                      </details>
                    `
                  : null}
              </section>
            `
          : null}

        <section className="rail-section" id="projectSection">
          <div className="section-head">
            <span>Projects</span>
            <button className="ghost-btn compact-btn" type="button" onClick=${() => setProjectDialogOpen(true)}>${t("buttons.add")}</button>
          </div>
          <div className="project-list">
                ${projects.length
                  ? projects.map(
                      (item) => html`
                        <button
                          key=${item.project_id}
                          className=${`project-row ${item.project_id === projectId ? "active" : ""}`}
                          type="button"
                          onClick=${(event) => handleProjectClick(event, item.project_id)}
                          onContextMenu=${(event) => handleProjectContextMenu(event, item)}
                          onTouchStart=${(event) => handleProjectTouchStart(event, item)}
                          onTouchEnd=${cancelProjectLongPress}
                          onTouchMove=${cancelProjectLongPress}
                          onTouchCancel=${cancelProjectLongPress}
                          disabled=${currentThreadBusy}
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
              : html`<div className="thread-empty">${t("threads.none")}</div>`}
          </div>
        </section>
        ${projectMenu
          ? html`
              <div
                className="thread-context-menu"
                ref=${projectMenuRef}
                style=${{ left: `${projectMenu.x}px`, top: `${projectMenu.y}px` }}
              >
                <button className="thread-context-item danger" type="button" onClick=${() => handleDeleteProject(projectMenu.projectId)}>
                  ${t("buttons.delete_project")}
                </button>
              </div>
            `
          : null}

        <section className="rail-section rail-section-fill">
          <div className="section-head thread-section-head">
            <span>Threads</span>
            <div className="thread-bulk-actions">
              ${selectedThreadCount
                ? html`
                    <button className="ghost-btn compact-btn" type="button" onClick=${toggleAllVisibleThreadsSelected} disabled=${bulkDeletingThreads || !selectableThreadIds.length}>
                      ${allVisibleThreadsSelected ? t("buttons.clear_thread_selection") : t("buttons.select_all_threads")}
                    </button>
                    <button className="ghost-btn compact-btn danger-btn" type="button" onClick=${handleBulkDeleteThreads} disabled=${bulkDeletingThreads || !selectedThreadCount}>
                      ${bulkDeletingThreads ? t("buttons.deleting") : t("buttons.delete_selected_threads", { count: selectedThreadCount })}
                    </button>
                    <button className="ghost-btn compact-btn" type="button" onClick=${() => setSelectedThreadIds(new Set())} disabled=${bulkDeletingThreads}>
                      ${t("buttons.cancel")}
                    </button>
                  `
                : html`<span className="section-meta">${workspaceLabel || "-"}</span>`}
            </div>
          </div>
          ${selectedThreadCount
            ? html`<div className="thread-selection-summary">${t("threads.selected_count", { count: selectedThreadCount })}</div>`
            : null}
          <div className="thread-list">
                ${sessions.length
                  ? sessions.map(
                      (item) => {
                        const itemId = threadListItemId(item);
                        const itemSelected = selectedThreadIds.has(itemId);
                        const indicatorStatus = threadRunIndicatorStatus(itemId);
                        return html`
                        <button
                          key=${itemId || item.session_id}
                          className=${`thread-row ${item.session_id === sessionId ? "active" : ""} ${selectedThreadCount ? "selectable" : ""} ${itemSelected ? "selected" : ""} ${indicatorStatus ? `has-run-indicator indicator-${indicatorStatus}` : ""}`}
                          type="button"
                          onClick=${(event) => handleThreadClick(event, itemId)}
                          onContextMenu=${(event) => handleThreadContextMenu(event, item)}
                          onTouchStart=${(event) => handleThreadTouchStart(event, item)}
                          onTouchEnd=${cancelThreadLongPress}
                          onTouchMove=${cancelThreadLongPress}
                          onTouchCancel=${cancelThreadLongPress}
                          aria-pressed=${selectedThreadCount ? itemSelected : undefined}
                        >
                          ${selectedThreadCount
                            ? html`<span className="thread-select-box" role="checkbox" aria-checked=${itemSelected}>${itemSelected ? "✓" : ""}</span>`
                            : null}
                          <span className="thread-row-body">
                            <span className="thread-row-title">${item.title || t("labels.new_thread")}</span>
                            <span className="thread-row-meta">${formatTime(item.updated_at, uiLocale)} · ${item.turn_count || 0}</span>
                          </span>
                          ${indicatorStatus
                            ? html`<span className=${`thread-run-indicator status-${indicatorStatus}`} aria-hidden="true"></span>`
                            : null}
                        </button>
                      `;
                      },
                )
              : html`<div className="thread-empty">${workspaceLabel ? t("threads.none_for_project", { workspace: workspaceLabel }) : t("threads.select_project_first")}</div>`}
          </div>
        </section>
        ${threadMenu
          ? html`
              <div
                className="thread-context-menu"
                ref=${threadMenuRef}
                style=${{ left: `${threadMenu.x}px`, top: `${threadMenu.y}px` }}
              >
                <button className="thread-context-item" type="button" onClick=${() => openRenameThreadDialog(threadMenu.sessionId)}>
                  ${t("buttons.rename_thread")}
                </button>
                <button className="thread-context-item danger" type="button" onClick=${() => handleDeleteSession(threadMenu.sessionId)}>
                  ${t("buttons.delete_thread")}
                </button>
              </div>
            `
          : null}
      </aside>

      <main className="workspace-main" id="chatPane">
        <header className="workspace-head">
          <div className="head-left">
            <button className="ghost-btn mobile-only" type="button" onClick=${() => setMobileThreadsOpen(true)}>${t("buttons.threads")}</button>
            <div className="head-stack">
              <div className="main-head-title">${headTitle}</div>
              <div className="main-head-sub" title=${currentProjectRoot || workspaceLabel || ""}>
                ${agentInfo.title || sessionRuntimeState.agent_title || "Vintage Programmer"}
                ${headBreadcrumb ? ` · ${headBreadcrumb}` : ""}
              </div>
            </div>
          </div>
          <div className="head-actions">
            <button
              className=${`mini-btn runtime-nav-btn ${drawerView === "run" ? "active" : ""} ${runtimeAttentionCount ? "needs-attention" : ""}`}
              type="button"
              onClick=${() => setDrawerView(drawerView === "run" ? "" : "run")}
            >
              <span>${currentTabLabel("run")}</span>
              ${runtimeAttentionCount
                ? html`<span className="runtime-attention-badge" aria-label=${t("runtime_panel.attention_count", { count: runtimeAttentionCount })}>${runtimeAttentionCount}</span>`
                : null}
            </button>
            <button className=${`mini-btn ${drawerView === "tools" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "tools" ? "" : "tools")}>${currentTabLabel("tools")}</button>
            <button className=${`mini-btn ${drawerView === "skills" ? "active" : ""}`} type="button" onClick=${() => {
              setDrawerView(drawerView === "skills" ? "" : "skills");
              if (!skills.length) refreshSkills();
            }}>${currentTabLabel("skills")}</button>
            <button className=${`mini-btn ${drawerView === "agent" ? "active" : ""}`} type="button" onClick=${() => {
              setDrawerView(drawerView === "agent" ? "" : "agent");
              if (!specs.length) refreshSpecs();
            }}>${currentTabLabel("agent")}</button>
            <button className=${`mini-btn ${drawerView === "settings" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "settings" ? "" : "settings")}>${currentTabLabel("settings")}</button>
            <button
              className=${`mini-btn eval-nav-btn ${activeEvalRun ? "is-running" : ""}`}
              type="button"
              onClick=${openEvalDialog}
            >
              ${evalButtonLabel}
            </button>
          </div>
        </header>

        <section className="conversation-plane" id="messageList" ref=${chatListRef}>
          ${showThreadDetailLoading && messages.length
            ? html`
                <div className="thread-loading-strip" role="status" aria-label="Loading thread">
                  <span className="thread-loading-spinner" aria-hidden="true"></span>
                </div>
              `
            : null}
          ${canLoadEarlierTurns
            ? html`
                <div className="load-earlier-row">
                  <button className="ghost-btn compact-btn" type="button" onClick=${loadEarlierTurns} disabled=${loadingEarlierTurns}>
                    ${loadingEarlierTurns ? t("buttons.running") : t("buttons.load_earlier")}
                  </button>
                </div>
              `
            : null}
          ${conversationMessages.length
            ? conversationMessages.map(
                (item) => {
                  const messageId = String(item.id || "");
                  const copied = Boolean(messageId && copiedMessageId === messageId);
                  const copyLabel = copied ? t("labels.copied") : t("buttons.copy_message");
                  const liveAgentMessage = Boolean(
                    item.role === "assistant"
                    && item.pending
                    && hasLiveRuntimeState
                    && liveAssistantMessageId
                    && String(item.id || "") === liveAssistantMessageId
                  );
                  return html`
                    <article key=${item.id} className=${`message-article role-${item.role} ${item.pending ? "pending" : ""} ${item.error ? "error" : ""} ${liveAgentMessage ? "live-agent-card" : ""}`}>
                      <div className="message-meta">
                        <span className="message-role">${roleLabel(item.role, uiLocale)}</span>
                        ${item.createdAt ? html`<span className="message-time">${formatTime(item.createdAt, uiLocale)}</span>` : null}
                      </div>
                      <div className="message-card">
                        ${renderMessageActivity(item)}
                        ${renderSteerStatus(item)}
                        <div
                          className="message-card-body message-markdown"
                          dangerouslySetInnerHTML=${{ __html: renderMessageHtml(messageBodyText(item), item.id) }}
                        ></div>
                      </div>
                      <div className="message-copy-row">
                        <button
                          className=${`message-copy-btn ${copied ? "copied" : ""}`}
                          type="button"
                          onClick=${() => handleCopyMessage(item)}
                          title=${copyLabel}
                          aria-label=${copyLabel}
                        >
                          <span className="message-copy-icon" aria-hidden="true"></span>
                        </button>
                      </div>
                    </article>
                  `;
                },
              )
            : showThreadDetailLoading
              ? html`
                  <section className="thread-loading-panel" role="status" aria-label="Loading thread">
                    <span className="thread-loading-spinner" aria-hidden="true"></span>
                  </section>
                `
            : showEmptyLivePanel
              ? html`
                  <section className="empty-panel empty-live-panel" role="status" aria-live="polite">
                    <div className="live-run-eyebrow">
                      <span className=${`live-run-dot status-${runExecutionProgress.status || "running"}`} aria-hidden="true"></span>
                      <span>${runExecutionProgress.statusLabel || t("activity.running")}</span>
                    </div>
                    <div className="empty-title">${t("run.live_panel.title")}</div>
                    <div className="live-run-action">${runExecutionProgress.currentAction || runExecutionProgress.recentEvent || t("run.progress.background_running")}</div>
                    ${runExecutionProgress.command
                      ? html`<code className="live-run-command">${runExecutionProgress.command}</code>`
                      : null}
                    <div className="live-run-meta">
                      ${runExecutionProgress.currentStep ? html`<span>${formatRunFieldLabel(uiLocale, "current_step")}: ${runExecutionProgress.currentStep}</span>` : null}
                      ${runExecutionProgress.currentTool ? html`<span>${formatRunFieldLabel(uiLocale, "current_tool")}: ${runExecutionProgress.currentTool}</span>` : null}
                      ${runExecutionProgress.elapsed ? html`<span>${formatRunFieldLabel(uiLocale, "elapsed")}: ${runExecutionProgress.elapsed}</span>` : null}
                      <span>${formatRunFieldLabel(uiLocale, "connection")}: ${runExecutionProgress.connectionLabel}</span>
                      ${runExecutionProgress.recentEvent ? html`<span>${runExecutionProgress.recentEvent}</span>` : null}
                    </div>
                  </section>
                `
            : html`
                <section className="empty-panel">
                  <div className="empty-kicker">Native Tools · Model-led Workspace</div>
                  <div className="empty-title" id="emptyPromptLine">${t("empty.prompt_title")}</div>
                  <p className="empty-copy">
                    ${t("labels.current_project")}
                    <strong>${workspaceLabel || t("labels.unselected")}</strong>
                    ${currentProjectRoot ? ` · ${compactPath(currentProjectRoot)}` : ""}
                    ${t("empty.prompt_body")}<strong>vintage_programmer</strong>${t("empty.prompt_suffix")}
                  </p>
                  <div className="starter-list">${starterPromptChips(uiLocale, setDraft, handleSend)}</div>
                </section>
              `}
          ${showJumpToLatest && messages.length
            ? html`
                <div className="jump-latest-row">
                  <button className="ghost-btn compact-btn" type="button" onClick=${jumpToLatest}>
                    ${t("buttons.jump_to_latest")}
                  </button>
                </div>
              `
            : null}
        </section>

        <section
          className=${`composer-shell ${composerDragActive ? "drag-active" : ""}`}
          id="composerShell"
          onDragEnter=${handleComposerDragEnter}
          onDragOver=${handleComposerDragOver}
          onDragLeave=${handleComposerDragLeave}
          onDrop=${handleComposerDrop}
        >
          ${pendingGuidance.length
            ? html`
                <div className="pending-guidance-strip" role="status" aria-live="polite">
                  <div className="pending-guidance-head">
                    <span>${t("steer.pending_title")}</span>
                    <small>${pendingGuidance.length}</small>
                  </div>
                  <div className="pending-guidance-list">
                    ${pendingGuidance.map((item) => html`
                      <div key=${item.id} className="pending-guidance-item">
                        <span>${item.message}</span>
                        <small>${t("steer.pending_waiting")}</small>
                      </div>
                    `)}
                  </div>
                </div>
              `
            : null}
          ${pendingUploads.length
	            ? html`
	                <div className="attachment-strip">
	                  ${pendingUploads.map(
	                    (item) => html`
	                      <div
                          key=${item.id}
                          className=${`attachment-chip ${item.uploading ? "is-uploading" : ""} ${item.uploadFailed ? "is-failed" : ""}`}
                          title=${item.error || ""}
                        >
	                        <span>${item.name}</span>
                          ${item.uploading ? html`<small>${t("labels.uploading")}</small>` : null}
                          ${item.uploadFailed ? html`<small>${t("labels.failed")}</small>` : null}
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
                      ${uiError.retryable ? ` · ${t("labels.retryable")}` : ""}
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
                            ${t("labels.copy_detail")}
                          </button>
                        `
                      : null}
                    ${uiError.detail
                      ? html`
                          <details className="composer-error-details">
                            <summary>${t("labels.detail")}</summary>
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
              <button className="icon-btn" type="button" onClick=${() => fileInputRef.current && fileInputRef.current.click()} disabled=${currentThreadBusy}>+</button>
              <input ref=${fileInputRef} type="file" multiple hidden onChange=${handleSelectFiles} />
              <label
                className="composer-permission-profile"
                title=${selectedPermissionDescription}
              >
                <select
                  className=${`composer-profile-select profile-${selectedPermissionProfileClass}`}
                  value=${selectedPermissionProfile}
                  onChange=${(event) => {
                    const target = event.currentTarget;
                    const nextValue = normalizePermissionProfile(target ? target.value : "auto");
                    setPermissionProfileTouched(true);
                    setChatSettings((prev) => ({ ...prev, permission_profile: nextValue }));
                  }}
                  disabled=${currentThreadBusy}
                  title=${selectedPermissionDescription}
                  aria-label=${selectedPermissionAriaLabel}
                >
                  <option value="default" title=${t("settings.permission_profile.default.help")}>${t("settings.permission_profile.default")}</option>
                  <option value="auto" title=${t("settings.permission_profile.auto.help")}>${t("settings.permission_profile.auto")}</option>
                  <option value="full_access" title=${t("settings.permission_profile.full_access.help")}>${t("settings.permission_profile.full_access")}</option>
                </select>
              </label>
            </div>
            <div className="composer-toolbar-right">
              ${currentThreadBusy && activeRunId && String(activeRunThreadId || "").trim() === String(sessionId || "").trim()
                ? html`
                    <button className="ghost-btn" type="button" onClick=${handleStopRun} disabled=${stoppingRun}>
                      ${stoppingRun ? t("buttons.stopping") : t("buttons.stop")}
                    </button>
                  `
                : null}
              <button className=${`ghost-btn tasks-entry-btn ${drawerView === "tasks" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "tasks" ? "" : "tasks")}>${t("buttons.tasks")}</button>
            </div>
          </div>

          <div className="composer-frame">
            ${slashCommandSuggestions.length
              ? html`
                <div className="slash-command-menu" role="listbox" aria-label=${t("slash.menu.label")}>
                  ${slashCommandSuggestions.map((item) => html`
                    <button
                      key=${item.command}
                      className=${`slash-command-item ${slashCommandSuggestions[slashCommandSelectedIndex] === item ? "is-active" : ""}`}
                      type="button"
                      role="option"
                      aria-selected=${slashCommandSuggestions[slashCommandSelectedIndex] === item ? "true" : "false"}
                      onMouseDown=${(event) => event.preventDefault()}
                      onMouseEnter=${() => setSlashCommandActiveIndex(slashCommandSuggestions.indexOf(item))}
                      onClick=${() => handleSend(item.command)}
                    >
                      <span className="slash-command-name">${item.command}</span>
                      <span className="slash-command-copy">
                        <strong>${t(item.labelKey)}</strong>
                        <small>${t(item.descriptionKey)}</small>
                      </span>
                    </button>
                  `)}
                </div>
              `
              : null}
            <textarea
              ref=${composerInputRef}
              value=${draft}
              onInput=${(event) => setDraft(event.currentTarget.value)}
              onKeyDown=${handleComposerKeyDown}
              onPaste=${handleComposerPaste}
              placeholder=${t("composer.placeholder")}
            ></textarea>
	            <button
                className="send-btn"
                type="button"
                onClick=${() => handleSend()}
                disabled=${(currentThreadBusy && !canQueueGuidance) || !draft.trim() || pendingUploads.some((item) => item && item.uploading)}
              >
	              ${canQueueGuidance ? t("buttons.steer") : (currentThreadBusy ? t("buttons.running") : (pendingUploads.some((item) => item && item.uploading) ? t("labels.uploading") : t("buttons.send")))}
	            </button>
          </div>
          <div className="status-bar status-inline" id="statusBar">
            <div className="status-summary">${statusSummary}</div>
            <div className="status-right">
              <div className="status-meta-group">
                ${currentProjectBranch ? html`<span>${currentProjectBranch}</span>` : null}
                ${!activeProviderAuthReady ? html`<span className="status-inline-note">auth missing</span>` : null}
              </div>
              <div
                className="context-meter-wrap"
                ref=${contextMeterRef}
                onMouseEnter=${openContextMeter}
                onMouseLeave=${scheduleContextMeterClose}
              >
                <button
                  className="context-meter-trigger"
                  type="button"
                  aria-label=${t("context_meter.aria")}
                  aria-expanded=${contextMeterOpen ? "true" : "false"}
                  onClick=${(event) => {
                    event.stopPropagation();
                    if (contextMeterCloseTimerRef.current) {
                      window.clearTimeout(contextMeterCloseTimerRef.current);
                      contextMeterCloseTimerRef.current = null;
                    }
                    setContextMeterOpen((prev) => !prev);
                  }}
                >
                  <span
                    className="context-meter-ring"
                    style=${{
                      "--meter-pct": `${activeContextMeter.used_percent}%`,
                      "--meter-color": contextMeterColor,
                    }}
                  ></span>
                  <span className="status-model-label">${contextStatusSummary}</span>
                </button>
                ${contextMeterOpen
                  ? html`
                      <div
                        className="context-meter-popover"
                        role="dialog"
                        aria-label=${t("context_meter.title")}
                        onMouseEnter=${openContextMeter}
                        onMouseLeave=${scheduleContextMeterClose}
                      >
                        <div className="context-meter-title">${t("context_meter.title")}</div>
                        <div className="context-meter-compact">
                          ${runtimeStats.compact.map(
                            (row) => html`<div key=${row.key} className="context-meter-line">${row.text}</div>`,
                          )}
                        </div>
                        <details className="context-meter-details">
                          <summary className="context-meter-details-toggle">${t("context_meter.details_toggle")}</summary>
                          <div className="context-meter-details-body">
                            ${[
                              [t("context_meter.section.run"), runtimeStats.run],
                              [t("context_meter.section.tools"), runtimeStats.tools],
                              [t("context_meter.section.context"), runtimeStats.context],
                              [t("context_meter.section.safeguards"), runtimeStats.safeguards],
                              [t("context_meter.section.diagnostics"), runtimeStats.diagnostics],
                            ].filter(([, rows]) => Array.isArray(rows) && rows.length).map(
                              ([sectionTitle, rows]) => html`
                                <div className="context-meter-section" key=${sectionTitle}>
                                  <div className="context-meter-section-title">${sectionTitle}</div>
                                  ${rows.map(
                                    (row) => html`
                                      <div key=${row.key} className="context-meter-kv">
                                        <span className="context-meter-label">${row.label}</span>
                                        <span className="context-meter-value">${row.value}</span>
                                      </div>
                                    `,
                                  )}
                                </div>
                              `,
                            )}
                          </div>
                        </details>
                      </div>
                    `
                  : null}
              </div>
            </div>
            ${uiError ? html`<span className="status-alert" title=${uiError.summary}>${t("labels.status_error")}</span>` : null}
          </div>
        </section>
	      </main>

		      ${evalDialogOpen
	        ? html`
	            <div className="project-modal-backdrop" id="evalModal">
	              <div className="project-modal eval-modal">
	                <div className="eval-modal-head">
	                  <div>
	                    <div className="panel-title">${t("eval.title")}</div>
	                    <div className="path-hint">${t("eval.hint")}</div>
	                  </div>
	                  <button className="drawer-close" type="button" onClick=${() => setEvalDialogOpen(false)}>${t("buttons.close")}</button>
	                </div>
	                <div className="eval-form-grid">
	                  <label className="form-field eval-form-wide">
	                    <span>${t("eval.suite")}</span>
	                    <select
	                      className="drawer-input"
	                      value=${evalForm.cases}
	                      onChange=${(event) => {
	                        const cases = event.currentTarget.value;
	                        const nextSuite = evalCatalog.find((item) => String(item.path || "") === String(cases || "")) || null;
	                        const requiresLive = !nextSuite || nextSuite.requires_live !== false;
	                        setEvalForm((prev) => ({
	                          ...prev,
	                          cases,
	                          name: "",
	                          repeat: nextSuite && nextSuite.supports_repeat === false ? 1 : prev.repeat,
	                          live: requiresLive ? prev.live : false,
	                          keep_workspaces: nextSuite && nextSuite.supports_workspaces === false ? false : prev.keep_workspaces,
	                        }));
	                      }}
	                    >
	                      ${evalCatalog.length
	                        ? evalCatalog.map((item) => html`<option key=${item.path} value=${item.path}>${item.suite} · ${item.case_count}</option>`)
	                        : html`<option value=${evalForm.cases}>${evalForm.cases}</option>`}
	                    </select>
	                  </label>
	                  <label className="form-field eval-form-wide">
	                    <span>${t("eval.case")}</span>
	                    <select
	                      className="drawer-input"
	                      value=${evalForm.name}
	                      onChange=${(event) => setEvalForm((prev) => ({ ...prev, name: event.currentTarget.value }))}
	                    >
	                      <option value="">${t("eval.all_cases")}</option>
	                      ${(selectedEvalSuite && Array.isArray(selectedEvalSuite.cases) ? selectedEvalSuite.cases : []).map(
	                        (caseName) => html`<option key=${caseName} value=${caseName}>${caseName}</option>`,
	                      )}
	                    </select>
	                  </label>
	                  <label className="form-field">
	                    <span>${t("eval.repeat")}</span>
	                    <input
	                      className="drawer-input"
	                      type="number"
	                      min="1"
	                      max="10"
	                      value=${evalForm.repeat}
	                      disabled=${!selectedEvalSupportsRepeat}
	                      onInput=${(event) => setEvalForm((prev) => ({ ...prev, repeat: event.currentTarget.value }))}
	                    />
	                  </label>
	                  <label className="form-field">
	                    <span>${t("eval.provider")}</span>
	                    <select
	                      className="drawer-input"
	                      value=${evalForm.provider}
	                      disabled=${!selectedEvalSupportsProvider}
	                      onChange=${(event) => setEvalForm((prev) => ({ ...prev, provider: event.currentTarget.value }))}
	                    >
	                      ${dedupeStrings([evalForm.provider, ...availableProviders]).map(
	                        (providerName) => html`<option key=${providerName} value=${providerName}>${providerName}</option>`,
	                      )}
	                    </select>
	                  </label>
	                  <label className="form-field eval-form-wide">
	                    <span>${t("eval.model")}</span>
	                    <input
	                      className="drawer-input"
	                      type="text"
	                      value=${evalForm.model}
	                      disabled=${!selectedEvalSupportsModel}
	                      onInput=${(event) => setEvalForm((prev) => ({ ...prev, model: event.currentTarget.value }))}
	                    />
	                  </label>
	                  <label className="form-field eval-form-wide">
	                    <span>${t("eval.output")}</span>
	                    <input
	                      className="drawer-input"
	                      type="text"
	                      value=${evalForm.output}
	                      placeholder=${t("eval.output_auto")}
	                      onInput=${(event) => setEvalForm((prev) => ({ ...prev, output: event.currentTarget.value }))}
	                    />
	                  </label>
	                </div>
	                ${selectedEvalRequiresLive ? null : html`<div className="path-hint">${t("eval.deterministic_hint")}</div>`}
	                <div className="eval-options">
	                  <label>
	                    <input
	                      type="checkbox"
	                      checked=${Boolean(evalForm.live)}
	                      disabled=${!selectedEvalRequiresLive}
	                      onChange=${(event) => setEvalForm((prev) => ({ ...prev, live: event.currentTarget.checked }))}
	                    />
	                    <span>${t("eval.live")}</span>
	                  </label>
	                  <label>
	                    <input
	                      type="checkbox"
	                      checked=${Boolean(evalForm.keep_workspaces)}
	                      disabled=${!selectedEvalSupportsWorkspaces}
	                      onChange=${(event) => setEvalForm((prev) => ({ ...prev, keep_workspaces: event.currentTarget.checked }))}
	                    />
	                    <span>${t("eval.keep_workspaces")}</span>
	                  </label>
	                </div>
	                ${evalError ? html`<div className="status-error">${evalError}</div>` : null}
	                <div className="modal-actions eval-actions">
	                  <button className="ghost-btn" type="button" onClick=${() => refreshEvalRuns()} disabled=${evalSubmitting}>${t("buttons.refresh")}</button>
	                  <button className="solid-btn" type="button" onClick=${startEvalRun} disabled=${evalSubmitting || (selectedEvalRequiresLive && !evalForm.live)}>
	                    ${evalSubmitting ? t("eval.starting") : t("eval.start")}
	                  </button>
	                </div>
	                <div className="eval-run-list">
	                  <div className="panel-title">${t("eval.recent_runs")}</div>
	                  ${evalRuns.length
	                    ? evalRuns.map((job) => {
	                        const status = String(job.status || "queued");
	                        const summary = job.summary && typeof job.summary === "object" ? job.summary : {};
	                        const progress = `${Number(job.completed_attempts || 0)}/${Number(job.total_attempts || 0)}`;
	                        return html`
	                          <div key=${job.id} className=${`eval-run-row status-${status}`}>
	                            <div className="eval-run-main">
	                              <strong>${job.suite || job.cases_path}</strong>
	                              <span>${t(`eval.status.${status}`)} · ${progress}</span>
	                            </div>
	                            ${job.current_case
	                              ? html`<div className="eval-run-detail">${job.current_case} · attempt ${job.current_attempt}</div>`
	                              : null}
	                            ${Object.keys(summary).length
	                              ? html`<div className="eval-run-detail">${t("eval.result_summary", { passed: Number(summary.passed || 0), failed: Number(summary.failed || 0), blocked: Number(summary.blocked || 0) })}</div>`
	                              : null}
	                            ${job.error ? html`<div className="eval-run-detail tone-error">${job.error}</div>` : null}
	                            ${job.report_path ? html`<div className="eval-run-path">${job.report_path}</div>` : null}
	                          </div>
	                        `;
	                      })
	                    : html`<div className="path-hint">${t("eval.no_runs")}</div>`}
	                </div>
	              </div>
	            </div>
	          `
	        : null}

	      ${projectDialogOpen
	        ? html`
	            <div className="project-modal-backdrop" id="projectModal">
              <div className="project-modal">
                <div className="panel-title">${t("project_modal.title")}</div>
                <label className="form-field">
                  <span>${t("project_modal.root_path")}</span>
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
                  <span>${t("project_modal.display_name")}</span>
                  <input
                    className="drawer-input"
                    type="text"
                    value=${projectTitleDraft}
                    placeholder=${t("project_modal.display_name_placeholder")}
                    onInput=${(event) => setProjectTitleDraft(event.currentTarget.value)}
                    disabled=${savingProject}
                  />
                </label>
                <div className="path-hint">${t("project_modal.hint")}</div>
                ${projectFormError ? html`<div className="status-error">${projectFormError}</div>` : null}
                <div className="modal-actions">
                  <button className="ghost-btn" type="button" onClick=${() => setProjectDialogOpen(false)} disabled=${savingProject}>${t("buttons.cancel")}</button>
                  <button className="solid-btn" type="button" onClick=${createProjectFromDraft} disabled=${savingProject}>${savingProject ? t("buttons.adding") : t("buttons.add_project")}</button>
                </div>
              </div>
            </div>
          `
        : null}

      ${renameDialog
        ? html`
            <div className="project-modal-backdrop" id="renameThreadModal">
              <div className="project-modal">
                <div className="panel-title">${t("thread_modal.rename_title")}</div>
                <label className="form-field">
                  <span>${t("thread_modal.display_name")}</span>
                  <input
                    className="drawer-input"
                    type="text"
                    value=${renameDraft}
                    maxLength="120"
                    placeholder=${t("thread_modal.display_name_placeholder")}
                    onInput=${(event) => setRenameDraft(event.currentTarget.value)}
                    disabled=${renamingThread}
                  />
                </label>
                <div className="path-hint">${t("thread_modal.hint", { title: String((renameDialog && renameDialog.displayTitle) || "") })}</div>
                ${renameError ? html`<div className="status-error">${renameError}</div>` : null}
                <div className="modal-actions">
                  <button className="ghost-btn" type="button" onClick=${closeRenameDialog} disabled=${renamingThread}>${t("buttons.cancel")}</button>
                  <button className="solid-btn" type="button" onClick=${handleRenameSession} disabled=${renamingThread}>
                    ${renamingThread ? t("buttons.saving") : t("buttons.save")}
                  </button>
                </div>
              </div>
            </div>
          `
        : null}

      ${drawerView
        ? html`<aside className=${`workbench-drawer open ${drawerView === "tasks" ? "tasks-drawer" : ""}`} id="workbenchDrawer">
        <div className="workbench-head">
          <div className="workbench-title">${drawerView === "tasks" ? t("tasks.title") : "Workbench"}</div>
          ${drawerView === "tasks"
            ? html`<div className="workbench-subtitle">${t("tasks.subtitle")}</div>`
            : html`
                <div className="workbench-tabs">
                  ${WORKBENCH_TABS.map(
                    (tab) => html`
                      <button
                        key=${tab}
                        className=${`tab-btn ${drawerView === tab ? "active" : ""}`}
                        type="button"
                        onClick=${() => setDrawerView(tab)}
                      >
                        ${currentTabLabel(tab)}
                      </button>
                    `,
                  )}
                </div>
              `}
          <button className="drawer-close" type="button" onClick=${() => setDrawerView("")}>${t("buttons.close")}</button>
        </div>

        ${drawerView === "tasks"
          ? html`
              <div className="workbench-scroll tasks-scroll">
                <div className="tasks-toolbar">
                  <button
                    className="solid-btn"
                    type="button"
                    onClick=${handleSummarizeCurrentTask}
                    disabled=${currentThreadBusy || !sessionId}
                  >
                    ${t("tasks.summarize")}
                  </button>
                  <button className="ghost-btn" type="button" onClick=${refreshTasks} disabled=${tasksPanelStatus === "loading"}>
                    ${t("buttons.refresh")}
                  </button>
                </div>
                <div className="task-list">
                  ${tasks.length
                    ? tasks.map((task) => html`
                        <article key=${task.task_id} className=${`task-card status-${task.status}`}>
                          <div className="task-card-head">
                            <div>
                              <div className="task-card-title">${task.title || task.goal}</div>
                              <div className="task-card-time">${formatTime(task.updated_at, uiLocale)}</div>
                            </div>
                            <span className=${`task-status status-${task.status}`}>${t(`tasks.status.${task.status}`)}</span>
                          </div>
                          <div className="task-card-summary">${task.summary || task.goal}</div>
                          ${task.next_steps.length
                            ? html`
                                <div className="task-card-section">
                                  <div className="task-card-label">${t("tasks.next_steps")}</div>
                                  <ul>${task.next_steps.slice(0, 3).map((item) => html`<li key=${item}>${item}</li>`)}</ul>
                                </div>
                              `
                            : null}
                          ${task.blockers.length
                            ? html`
                                <div className="task-card-section task-blockers">
                                  <div className="task-card-label">${t("tasks.blockers")}</div>
                                  <ul>${task.blockers.slice(0, 2).map((item) => html`<li key=${item}>${item}</li>`)}</ul>
                                </div>
                              `
                            : null}
                          <div className="task-card-actions">
                            <button
                              className="solid-btn"
                              type="button"
                              onClick=${() => handleLoadTask(task)}
                              disabled=${Boolean(loadingTaskId) || currentThreadBusy}
                            >
                              ${loadingTaskId === task.task_id ? t("buttons.loading_task") : t("buttons.load_task")}
                            </button>
                          </div>
                        </article>
                      `)
                    : html`<div className="empty-inline task-empty">${tasksPanelStatus === "loading" ? t("labels.processing") : t("tasks.none")}</div>`}
                </div>
              </div>
            `
          : null}

        ${drawerView === "run"
          ? html`
              <div className="workbench-scroll runtime-control-center">
                <section className=${`panel-card runtime-overview-card status-${runExecutionProgress.status || "idle"}`}>
                  <div className="runtime-panel-heading">
                    <div>
                      <div className="panel-title">${t("runtime_panel.title")}</div>
                      <div className="runtime-panel-subtitle">${t("runtime_panel.subtitle")}</div>
                    </div>
                    <span className=${`run-progress-state status-${runExecutionProgress.status || "idle"}`}>
                      ${runtimeOperational
                        ? (runExecutionProgress.statusLabel || formatRunEnum(uiLocale, "turn_status", activeTurnStatus, "idle"))
                        : formatRunEnum(uiLocale, "turn_status", "idle", "idle")}
                    </span>
                  </div>
                  <div className="runtime-current-action">
                    ${runtimeOperational
                      ? (runExecutionProgress.currentAction || runExecutionProgress.recentEvent || t("runtime_panel.idle"))
                      : t("runtime_panel.idle")}
                  </div>
                  ${runtimeOperational && runExecutionProgress.command
                    ? html`<code className="run-progress-command runtime-current-command">${runExecutionProgress.command}</code>`
                    : null}
                  ${runtimeOperational
                    ? html`
                        <div className="runtime-status-grid">
                          <div>
                            <span>${formatRunFieldLabel(uiLocale, "current_tool")}</span>
                            <strong>${runExecutionProgress.currentTool || "-"}</strong>
                          </div>
                          <div>
                            <span>${formatRunFieldLabel(uiLocale, "elapsed")}</span>
                            <strong>${runExecutionProgress.elapsed || "-"}</strong>
                          </div>
                          <div>
                            <span>${formatRunFieldLabel(uiLocale, "last_progress")}</span>
                            <strong>${runExecutionProgress.lastProgressAgo || "-"}</strong>
                          </div>
                          <div>
                            <span>${formatRunFieldLabel(uiLocale, "connection")}</span>
                            <strong>${runExecutionProgress.connectionLabel || "-"}</strong>
                          </div>
                        </div>
                      `
                    : null}
                  ${runtimeOperational && activeTaskCheckpoint.blocked_reason
                    ? html`<div className="runtime-blocked-reason">${activeTaskCheckpoint.blocked_reason}</div>`
                    : null}
                </section>

                ${runtimeAttentionCount
                  ? html`
                      <section className="panel-card runtime-attention-card">
                        <div className="panel-title">${t("runtime_panel.action_required")}</div>
                        ${hasCommandApproval
                          ? html`
                              <div className="runtime-interaction-block">
                                <div className="runtime-interaction-title">${t("runtime_panel.approval_required")}</div>
                                ${String(activePendingApproval.purpose || "").trim()
                                  ? html`<div className="timeline-detail">${String(activePendingApproval.purpose || "").trim()}</div>`
                                  : null}
                                <code className="run-progress-command">${String(activePendingApproval.command || "")}</code>
                                ${String(activePendingApproval.cwd || "").trim()
                                  ? html`<div className="timeline-detail">${t("approval_modal.cwd")}: ${String(activePendingApproval.cwd || "").trim()}</div>`
                                  : null}
                                ${(commandApprovalRisks.length || commandApprovalFiles.length)
                                  ? html`
                                      <details className="runtime-approval-details">
                                        <summary>${t("runtime_panel.approval_details", { risks: commandApprovalRisks.length, files: commandApprovalFiles.length })}</summary>
                                        <div className="timeline-list">
                                          ${commandApprovalRisks.map((risk, index) => html`
                                            <div key=${`runtime-risk-${index}`} className="timeline-row">
                                              <div className="timeline-head">
                                                <span>${String(risk.category || risk.kind || t("approval_modal.risk"))}</span>
                                                <span>${String(risk.operation || risk.base_command || "")}</span>
                                              </div>
                                              <div className="timeline-detail">${String(risk.message || "")}</div>
                                            </div>
                                          `)}
                                          ${commandApprovalFiles.map((file, index) => html`
                                            <div key=${`runtime-file-${index}`} className="timeline-row">
                                              <div className="timeline-head">
                                                <span>${String(file.path || "")}</span>
                                                <span>${String(file.source_domain || "network")}</span>
                                              </div>
                                              <div className="timeline-detail">${String(file.source_url || "")}</div>
                                            </div>
                                          `)}
                                        </div>
                                      </details>
                                    `
                                  : null}
                                <div className="runtime-control-actions">
                                  <button className="ghost-btn" type="button" onClick=${() => handleCommandApproval("cancel")} disabled=${approvalSubmitting}>
                                    ${t("approval_modal.cancel")}
                                  </button>
                                  <button className="solid-btn" type="button" onClick=${() => handleCommandApproval("approve_once")} disabled=${approvalSubmitting || !String(activePendingApproval.approval_token || "").trim()}>
                                    ${t("approval_modal.approve_once")}
                                  </button>
                                </div>
                              </div>
                            `
                          : null}
                        ${hasPendingRuntimeInput
                          ? html`
                              <div className="runtime-interaction-block">
                                <div className="runtime-interaction-title">${t("runtime_panel.user_input_required")}</div>
                                ${activePendingInput.summary
                                  ? html`<div className="timeline-detail">${activePendingInput.summary}</div>`
                                  : null}
                                <div className="timeline-list runtime-question-list">
                                  ${pendingRuntimeQuestions.map((item) => html`
                                    <div key=${item.id || item.header || item.question} className="timeline-row">
                                      <div className="timeline-head">
                                        <span>${item.header || item.id || t("runtime_panel.question")}</span>
                                      </div>
                                      <div className="timeline-detail">${item.question || ""}</div>
                                      ${Array.isArray(item.options) && item.options.length
                                        ? html`<div className="timeline-detail">${item.options.map((option) => option.label).filter(Boolean).join(" / ")}</div>`
                                        : null}
                                    </div>
                                  `)}
                                </div>
                                <div className="runtime-control-actions">
                                  <button className="solid-btn" type="button" onClick=${focusRuntimeInput}>${t("runtime_panel.reply_in_composer")}</button>
                                </div>
                              </div>
                            `
                          : null}
                      </section>
                    `
                  : null}

                ${!runtimeOperational && runtimeActivityMessage
                  ? html`
                      <section className=${`panel-card runtime-outcome-card status-${runtimeOutcome.status || "completed"}`}>
                        <div className="runtime-panel-heading">
                          <div className="panel-title">${t("runtime_panel.last_run")}</div>
                          <span className=${`run-progress-state status-${runtimeOutcome.status || "completed"}`}>
                            ${formatRunProgressStatus(uiLocale, runtimeOutcome.status || "completed")}
                          </span>
                        </div>
                        <div className="runtime-outcome-stats">
                          <div>
                            <span>${formatRunFieldLabel(uiLocale, "elapsed")}</span>
                            <strong>${runtimeOutcome.duration || "-"}</strong>
                          </div>
                          <div>
                            <span>${t("context_meter.field.tool_total")}</span>
                            <strong>${runtimeOutcome.toolCount}</strong>
                          </div>
                          <div>
                            <span>${t("runtime_panel.failed_tools")}</span>
                            <strong>${runtimeOutcome.failures.length}</strong>
                          </div>
                        </div>
                        ${runtimeOutcomeNeedsLoad || Boolean(runtimeActivityMessage.runActivityLoading)
                          ? html`<div className="runtime-outcome-note">${t("runtime_panel.last_run_loading")}</div>`
                          : null}
                        ${runtimeActivityMessage.runActivityError
                          ? html`<div className="runtime-outcome-error">${String(runtimeActivityMessage.runActivityError)}</div>`
                          : null}
                        ${runtimeOutcome.errorKind || runtimeOutcome.errorMessage || runtimeOutcome.stopReason
                          ? html`
                              <div className="runtime-outcome-error">
                                ${runtimeOutcome.errorKind
                                  ? html`<strong>${t("runtime.error.kind")}: ${runtimeOutcome.errorKind}</strong>`
                                  : null}
                                ${runtimeOutcome.errorMessage ? html`<div>${runtimeOutcome.errorMessage}</div>` : null}
                                ${runtimeOutcome.stopReason
                                  ? html`<div>${t("activity.debug.blocked_reason")}: ${runtimeOutcome.stopReason}</div>`
                                  : null}
                              </div>
                            `
                          : null}
                        ${runtimeOutcome.failures.length
                          ? html`
                              <div className="runtime-failure-list">
                                ${runtimeOutcome.failures.map((failure) => html`
                                  <div className="runtime-failure-row" key=${failure.id}>
                                    <div className="runtime-failure-title">
                                      <strong>${failure.tool}</strong>
                                      ${failure.errorKind ? html`<code>${failure.errorKind}</code>` : null}
                                    </div>
                                    ${failure.retryCount || failure.recoveryResult
                                      ? html`
                                          <div className="runtime-failure-meta">
                                            ${failure.retryCount
                                              ? html`<span>${t("activity.debug.trace_retry")}: ${failure.retryCount}</span>`
                                              : null}
                                            ${failure.recoveryResult
                                              ? html`<span>${t("activity.debug.trace_recovery")}: ${failure.recoveryResult}</span>`
                                              : null}
                                          </div>
                                        `
                                      : null}
                                    ${failure.summary
                                      ? html`<pre className="runtime-failure-summary">${failure.summary}</pre>`
                                      : null}
                                  </div>
                                `)}
                              </div>
                            `
                          : (!runtimeOutcomeNeedsLoad && !runtimeActivityMessage.runActivityLoading
                            ? html`<div className="runtime-outcome-note">${t("runtime_panel.no_tool_failures")}</div>`
                            : null)}
                      </section>
                    `
                  : (!runtimeOperational
                    ? html`<section className="panel-card"><div className="empty-inline">${t("runtime_panel.no_last_run")}</div></section>`
                    : null)}

                ${runtimeOperational
                  ? html`<section className="panel-card runtime-active-work-card">
                  <div className="panel-title">${t("runtime_panel.active_work")}</div>
                  <div className="runtime-unit-list">
                    ${activeRuntimeUnits.length
                      ? activeRuntimeUnits.map((item) => html`
                          <div key=${item.id} className="runtime-unit-row">
                            <span className=${`live-run-dot status-${item.status || "running"}`} aria-hidden="true"></span>
                            <div>
                              <strong>${item.label || item.tool || item.type || t("runtime_panel.work_item")}</strong>
                              ${item.detail ? html`<div className="timeline-detail">${item.detail}</div>` : null}
                            </div>
                            <span className=${`run-progress-state status-${item.status || "running"}`}>${formatRunProgressStatus(uiLocale, item.status || "running")}</span>
                          </div>
                        `)
                      : html`<div className="empty-inline">${t("runtime_panel.no_active_work")}</div>`}
                  </div>
                </section>`
                  : null}

                ${runtimeOperational
                  ? html`<section className="panel-card runtime-events-card">
                  <div className="panel-title">${t("runtime_panel.recent_events")}</div>
                  <div className="runtime-event-list">
                    ${runtimeDecisionEvents.length
                      ? runtimeDecisionEvents.map((item) => html`
                          <div key=${item.id} className=${`runtime-event-row tone-${item.type || "runtime"}`}>
                            <span>${formatTime(item.createdAt, uiLocale)}</span>
                            <strong>${item.text}</strong>
                          </div>
                        `)
                      : html`<div className="empty-inline">${t("runtime_panel.no_recent_events")}</div>`}
                  </div>
                </section>`
                  : null}

                <section className="panel-card runtime-controls-card">
                  <div className="panel-title">${t("runtime_panel.controls")}</div>
                  <div className="runtime-control-actions">
                    ${currentThreadBusy && activeRunId && String(activeRunThreadId || "").trim() === String(sessionId || "").trim()
                      ? html`
                          <button className="ghost-btn danger-btn" type="button" onClick=${handleStopRun} disabled=${stoppingRun}>
                            ${stoppingRun ? t("buttons.stopping") : t("buttons.stop")}
                          </button>
                        `
                      : null}
                    <button className="ghost-btn" type="button" onClick=${openLatestRuntimeDebug} disabled=${!latestRuntimeDebugMessage}>
                      ${t("runtime_panel.open_developer_debug")}
                    </button>
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
                              <div className="tool-summary">${item.summary || t("tools.no_summary")}</div>
                              <div className="tool-flags">
                                <span>${item.read_only ? t("tool.read_only") : t("tool.write")}</span>
                                <span>${item.requires_evidence ? t("tool.evidence") : t("tool.no_evidence")}</span>
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
                    <div className="panel-title">${t("skills.title")}</div>
                    <div className="editor-actions">
                      <button className="ghost-btn" type="button" onClick=${() => {
                        startNewSkillDraft();
                      }}>${t("skills.new_team")}</button>
                      <button className="solid-btn" type="button" onClick=${saveSkill} disabled=${savingWorkbench || selectedSkillReadOnly || !skillEditor.trim()}>${t("buttons.save")}</button>
                      ${selectedSkill
                        ? html`
                            <button
                              className="ghost-btn"
                              type="button"
                              onClick=${() => toggleSelectedSkill(!selectedSkill.enabled)}
                              disabled=${savingWorkbench}
                            >
                              ${selectedSkill.enabled ? t("buttons.disable") : t("buttons.enable")}
                            </button>
                            <button
                              className="ghost-btn danger-btn"
                              type="button"
                              onClick=${handleDeleteSelectedSkill}
                              disabled=${savingWorkbench || selectedSkillReadOnly}
                            >
                              ${t("buttons.delete")}
                            </button>
                          `
                        : null}
                    </div>
                  </div>

                  <div className="meta-line">
                    ${skillsPanelStatus === "loading" ? t("skills.loading") : t("skills.global_catalog")}
                  </div>

                  <div className="resource-list">
                    ${skills.length
                      ? ["builtin", "team"].map((scope) => {
                          const scopedItems = groupedSkills[scope] || [];
                          if (!scopedItems.length) return null;
                          return html`
                            <div key=${scope} className="resource-group-label">${scope === "builtin" ? t("skills.group.builtin") : t("skills.group.team")}</div>
                            ${scopedItems.map(
                              (item) => {
                                const itemKey = skillKey(item);
                                return html`
                                  <button
                                    key=${itemKey}
                                    className=${`resource-row ${selectedSkillId === itemKey ? "active" : ""}`}
                                    type="button"
                                    onClick=${() => selectSkillFromList(itemKey)}
                                  >
                                    <div className="resource-row-title">${skillName(item)}</div>
                                    <div className="resource-row-meta">
                                      ${item.enabled ? t("skills.status.enabled") : t("skills.status.disabled")}
                                      · ${item.read_only ? t("skills.read_only") : t("skills.editable")}
                                      · ${formatValidationStatus(uiLocale, item.validation_status)}
                                    </div>
                                  </button>
                                `;
                              },
                            )}
                          `;
                        })
                      : html`<div className="empty-inline">${t("skills.none")}</div>`}
                  </div>

                  <textarea
                    className="editor-textarea"
                    value=${skillEditor}
                    onInput=${(event) => setSkillEditor(event.currentTarget.value)}
                    placeholder=${t("skills.placeholder")}
                    readOnly=${selectedSkillReadOnly}
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
                    <div className="panel-title">${t("agent.title")}</div>
                    <div className="editor-actions">
                      <button className="solid-btn" type="button" onClick=${saveSpec} disabled=${savingWorkbench || !specEditor.trim()}>${t("buttons.save")}</button>
                    </div>
                  </div>

                  ${selectedSpec
                    ? html`
                        <div className="meta-line">${t("agent.editing_locale")}: ${formatLocaleLabel(uiLocale, selectedSpec.locale || uiLocale)}</div>
                        <div className="meta-line">${t("agent.target_path")}: ${compactPath(selectedSpec.path || "-")}</div>
                        <div className="timeline-detail">
                          ${selectedSpec.fallback_from_base
                            ? t("agent.source_fallback", { path: compactPath(selectedSpec.resolved_path || selectedSpec.path || "-") })
                            : t("agent.source_localized", { path: compactPath(selectedSpec.resolved_path || selectedSpec.path || "-") })}
                        </div>
                      `
                    : null}

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
                          <div className="resource-row-meta">
                            ${formatLocaleLabel(uiLocale, item.locale || uiLocale)} · ${formatValidationStatus(uiLocale, item.validation_status)}
                            ${item.fallback_from_base ? ` · ${t("agent.badge.fallback")}` : ""}
                          </div>
                        </button>
                      `,
                    )}
                  </div>

                  <textarea
                    className="editor-textarea"
                    value=${specEditor}
                    onInput=${(event) => setSpecEditor(event.currentTarget.value)}
                    placeholder=${t("agent.placeholder")}
                  ></textarea>
                </section>
              </div>
            `
          : null}

        ${drawerView === "settings"
          ? html`
              <div className="workbench-scroll" id="settingsPanel">
                <section className="panel-card">
                  <div className="panel-title">${t("settings.title")}</div>
                  ${availableProviders.length
                    ? html`
                        <label className="form-field">
                          <span>${t("settings.provider")}</span>
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
                  <div className="form-field">
                    <div className="model-preset-heading">
                      <span>${t("settings.model_preset")}</span>
                      <button
                        className="mini-btn model-preset-refresh-btn"
                        type="button"
                        disabled=${modelPresetRefreshing || !activeProvider || activeProvider === "default"}
                        onClick=${refreshModelPresets}
                      >
                        ${modelPresetRefreshing
                          ? t("settings.model_presets.refreshing")
                          : t("settings.model_presets.refresh")}
                      </button>
                    </div>
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
                      ${allowCustomModel ? html`<option value=${CUSTOM_MODEL_VALUE}>${t("labels.custom")}</option>` : null}
                    </select>
                    <div className="field-help">${modelPresetRefreshMessage || t("settings.model_presets.help")}</div>
                  </div>
                  <label className="form-field">
                    <span>${t("settings.locale")}</span>
                    <select
                      className="drawer-input"
                      value=${uiLocale}
                      onChange=${(event) => {
                        const target = event.currentTarget;
                        const nextLocale = target ? target.value : "";
                        updateLocaleSelection(nextLocale);
                      }}
                    >
                      ${supportedLocales.map((item) => html`
                        <option key=${item} value=${item}>${t(`settings.locale.${item}`)}</option>
                      `)}
                    </select>
                  </label>
                  <div className="form-field">
                    <span>${t("settings.theme_color")}</span>
                    <div className="theme-color-options" role="group" aria-label=${t("settings.theme_color")}>
                      ${THEME_COLOR_OPTIONS.map((item) => html`
                        <button
                          key=${item.id}
                          className=${`theme-color-option ${selectedThemeColor === item.id ? "active" : ""}`}
                          type="button"
                          aria-pressed=${selectedThemeColor === item.id}
                          title=${t(`settings.theme_color.${item.id}`)}
                          onClick=${() => setThemeColor(item.id)}
                          style=${{
                            "--theme-option-color": item.accent,
                            "--theme-option-soft": item.accentSoft,
                          }}
                        >
                          <span className="theme-color-swatch" aria-hidden="true"></span>
                          <span className="theme-color-name">${t(`settings.theme_color.${item.id}`)}</span>
                        </button>
                      `)}
                    </div>
                  </div>
                  <label className="form-field">
                    <span>${t("settings.model_name")}</span>
                    <input
                      className="drawer-input"
                      id="modelInput"
                      type="text"
                      value=${chatSettings.model}
                      onInput=${(event) => updateModelSelection(event.currentTarget.value)}
                    />
                  </label>
                  <label className="form-field">
                    <span>${t("settings.response_style")}</span>
                    <select
                      className="drawer-input"
                      value=${chatSettings.response_style}
                      onChange=${(event) => {
                        const target = event.currentTarget;
                        const nextValue = target ? target.value : "";
                        setChatSettings((prev) => ({ ...prev, response_style: nextValue }));
                      }}
                    >
                      <option value="short">${t("settings.response_style.short")}</option>
                      <option value="normal">${t("settings.response_style.normal")}</option>
                      <option value="long">${t("settings.response_style.long")}</option>
                    </select>
                  </label>
                  <label className="tool-toggle drawer-toggle">
                    <input
                      type="checkbox"
                      checked=${chatSettings.enable_tools}
                      onChange=${(event) => {
                        const target = event.currentTarget;
                        const nextValue = Boolean(target && target.checked);
                        setChatSettings((prev) => ({ ...prev, enable_tools: nextValue }));
                      }}
                    />
                    ${t("settings.enable_tools")}
                  </label>
                  <label className="tool-toggle drawer-toggle">
                    <input
                      type="checkbox"
                      checked=${chatSettings.debug_raw}
                      onChange=${(event) => {
                        const target = event.currentTarget;
                        const nextValue = Boolean(target && target.checked);
                        setChatSettings((prev) => ({ ...prev, debug_raw: nextValue }));
                      }}
                    />
                    ${t("settings.debug_raw")}
                  </label>
                  <label className="form-field">
                    <span>${t("settings.output_limit")}</span>
                    <input
                      className="drawer-input"
                      type="number"
                      value=${chatSettings.max_output_tokens}
                      onInput=${(event) => {
                        const target = event.currentTarget;
                        const nextValue = Number((target && target.value) || 0) || 1024;
                        setChatSettings((prev) => ({ ...prev, max_output_tokens: nextValue }));
                      }}
                    />
                  </label>
                  <label className="form-field">
                    <span>${t("settings.context_turns")}</span>
                    <span className="field-hint">${t("settings.context_turns.help")}</span>
                    <input
                      className="drawer-input"
                      type="number"
                      value=${chatSettings.max_context_turns}
                      onInput=${(event) => {
                        const target = event.currentTarget;
                        const nextValue = Number((target && target.value) || 0) || 20;
                        setChatSettings((prev) => ({ ...prev, max_context_turns: nextValue }));
                      }}
                    />
                  </label>
                </section>
              </div>
            `
          : null}
      </aside>`
        : null}
    </div>
    ${bootLoadingActive
      ? html`
          <main className="app-boot-screen app-boot-screen-overlay" role="status" aria-live="polite" aria-label=${bootLoadingText}>
            <div className="app-boot-card">
              <div className="app-boot-mark" aria-hidden="true">VP</div>
              <div className="app-boot-copy">
                <div className="app-boot-title">Vintage Programmer</div>
                <div className="app-boot-status">
                  <span className="app-boot-ring" aria-hidden="true"></span>
                  <span>${bootLoadingText}</span>
                </div>
              </div>
            </div>
          </main>
        `
      : null}
    </div>
  `;
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");
createRoot(root).render(html`<${AppErrorBoundary}><${App} /></${AppErrorBoundary}>`);
