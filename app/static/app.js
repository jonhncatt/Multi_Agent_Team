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
const MAIN_LIVE_CARD_LIMIT = 8;
const messageHtmlCache = new Map();
const DEFAULT_SETTINGS = {
  provider: "",
  model: "",
  locale: "",
  max_output_tokens: 4096,
  max_context_turns: 2000,
  enable_tools: true,
  permission_profile: "code",
  response_style: "normal",
};

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
  const usedRatio = limit > 0
    ? Math.min(1, Math.max(0, Number.isFinite(rawRatio) ? rawRatio : (estimated / limit)))
    : 0;
  const remainingRatio = Math.max(0, 1 - usedRatio);
  const usedPercent = Math.max(0, Math.min(100, Math.round(Number(meter.used_percent || (usedRatio * 100)) || 0)));
  const remainingPercent = Math.max(0, Math.min(100, Math.round(Number(meter.remaining_percent || (remainingRatio * 100)) || 0)));
  return {
    estimated_tokens: estimated,
    estimated_payload_tokens: payload,
    overhead_tokens: overhead,
    auto_compact_token_limit: limit,
    context_window: contextWindow,
    used_ratio: usedRatio,
    remaining_ratio: remainingRatio,
    used_percent: usedPercent,
    remaining_percent: remainingPercent,
    threshold_source: String(meter.threshold_source || "").trim(),
    context_window_known: Boolean(meter.context_window_known),
    compaction_enabled: Boolean(meter.compaction_enabled),
    last_compacted_at: String(meter.last_compacted_at || "").trim(),
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
    effective_context_window: Math.max(0, Number(status.effective_context_window || 0) || 0),
    auto_compact_token_limit: Math.max(0, Number(status.auto_compact_token_limit || 0) || 0),
    threshold_source: String(status.threshold_source || "").trim(),
    context_window_known: Boolean(status.context_window_known),
    last_compacted_at: String(status.last_compacted_at || "").trim(),
    last_compaction_reason: String(status.last_compaction_reason || "").trim(),
    last_compaction_phase: String(status.last_compaction_phase || "").trim(),
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
  return turns.map((turn, index) =>
    createMessage(
      String(turn.role || "").toLowerCase() === "user" ? "user" : "assistant",
      String(turn.text || ""),
      {
        id: String(turn.id || `${index}-${turn.role || "turn"}-${turn.created_at || ""}`),
        createdAt: String(turn.created_at || ""),
        activity: turn.activity || {},
      },
    ),
  );
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
  const resolvedId = String(
    rawToolCall.id
    || validationResult.call_id
    || item.id
    || item.tool_call_id
    || item.call_id
    || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  ).trim();
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
      status: "running",
      label: item.title || "",
      label_key: "activity.live.model_thinking",
      detail: item.detail || String(payload.model || ""),
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
      status: type === "tool_drain.finished" ? "completed" : "running",
      label: item.title || "",
      label_key: type === "tool_drain.finished" ? "activity.live.waiting_next_model" : "activity.live.tool_running",
      detail: item.detail || "",
      started_at: item.timestamp,
      completed_at: type === "tool_drain.finished" ? item.timestamp : 0,
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
  return null;
}

function isActivityTerminalStatus(status) {
  const normalized = String(status || "").trim();
  return normalized === "completed" || normalized === "failed" || normalized === "blocked" || normalized === "cancelled";
}

function normalizeMessageActivity(raw) {
  const item = raw && typeof raw === "object" ? raw : {};
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
  return {
    run_id: String(item.run_id || ""),
    status,
    started_at: startedAt,
    turn_started_at: turnStartedAt,
    finished_at: finishedAt,
    run_duration_ms: runDurationMs,
    final_elapsed_ms: finalElapsedMs,
    activity_summary: String(item.activity_summary || ""),
    triggering_user_message: String(item.triggering_user_message || item.triggeringUserMessage || ""),
    triggering_user_turn_id: String(item.triggering_user_turn_id || item.triggeringUserTurnId || ""),
    session_id: String(item.session_id || item.sessionId || ""),
    thread_id: String(item.thread_id || item.threadId || ""),
    plan: normalizePlanChecklist(item.plan),
    plan_explanation: String(item.plan_explanation || ""),
    tool_items: normalizeActivityToolItems(item.tool_items),
    live_items: normalizeLiveRunItems(item.live_items),
    trace_events: traceEvents,
  };
}

function defaultSkillTemplate(locale) {
  return [
    "---",
    "id: new_skill",
    `title: ${translateUi(locale, "skill_template.title")}`,
    "enabled: false",
    "bind_to:",
    "  - vintage_programmer",
    `summary: ${translateUi(locale, "skill_template.summary")}`,
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
  return hit ? hit.title || translateUi(locale, "labels.new_thread") : translateUi(locale, "labels.start_building");
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
  if (["in_progress", "inprogress", "running", "active", "working"].includes(normalized)) return "running";
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
  const resolved = String(
    rawToolCall.id
    || validationResult.call_id
    || item.tool_call_id
    || item.call_id
    || item.id
    || fallback,
  ).trim();
  return resolved;
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

function formatToolProgressLabel(locale, group) {
  const item = group && typeof group === "object" ? group : {};
  const toolName = String(item.tool_name || "").trim();
  const target = toolCallTargetFromSource(item);
  const labelValue = target || toolName || "tool";
  const readTools = new Set(["read_file", "read_section", "image_read", "image_inspect", "table_extract"]);
  const listTools = new Set(["list_dir"]);
  const globTools = new Set(["glob_file_search"]);
  const searchTools = new Set(["search_contents_in_file", "search_contents_in_file_multi", "search_codebase", "fact_check_file", "web_search", "web_fetch", "web_download"]);
  const commandTools = new Set(["exec_command", "run_shell", "run_command", "shell", "bash"]);
  const patchTools = new Set(["apply_patch", "write_skill", "read_skill", "list_skills"]);
  if (readTools.has(toolName)) return translateUi(locale, "activity.progress.read", { target: labelValue });
  if (listTools.has(toolName)) return translateUi(locale, "activity.progress.list_dir", { target: labelValue });
  if (globTools.has(toolName)) return translateUi(locale, "activity.progress.glob_file_search", { target: labelValue });
  if (searchTools.has(toolName)) return translateUi(locale, "activity.progress.search", { target: labelValue });
  if (commandTools.has(toolName)) return translateUi(locale, "activity.progress.execute_command", { target: labelValue });
  if (patchTools.has(toolName)) return translateUi(locale, "activity.progress.apply_patch", { target: labelValue });
  return translateUi(locale, "activity.progress.use_tool", { tool: labelValue });
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
    if (toolItem.status === "error" || toolItem.status === "failed") {
      group.status = "failed";
    } else if (toolItem.status === "ok" && group.status !== "failed") {
      group.status = "completed";
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

function buildLiveAgentTimelineItems(activity, locale) {
  const item = normalizeMessageActivity(activity || {});
  if (isActivityTerminalStatus(item.status)) return [];
  return item.live_items.map((liveItem) => {
    const tool = String(liveItem.tool || "").trim();
    const target = shortenActivityTarget(liveItem.detail || "");
    const toolLabel = tool
      ? formatToolProgressLabel(locale, {
          tool_name: tool,
          normalized_arguments: target ? { query: target } : {},
          arguments_preview: target,
          detail: target,
        })
      : "";
    const fallbackLabel = tool
      ? toolLabel
      : String(liveItem.type || "activity");
    const label = liveItem.label
      || (toolLabel || (liveItem.label_key ? translateUi(locale, liveItem.label_key, { tool }) : ""))
      || fallbackLabel;
    return {
      id: `live-${liveItem.id}`,
      label,
      detail: liveItem.detail,
      status: normalizeProgressStatus(liveItem.status),
      source: "live",
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
  const hasLiveItems = Boolean(liveItems.length);
  const hasStarted = Boolean(item.turn_started_at || item.started_at || traces.length);
  const llmStartedAt = latestTraceTimestampByTypes(traces, "llm.started");
  const hasAnswerStarted = traces.some((trace) => ["answer.started", "answer.delta", "answer.done", "answer.finished"].includes(String(trace.type || "").trim()));
  const hasAnswerReady = traces.some((trace) => ["answer.done", "answer.finished", "run.finished"].includes(String(trace.type || "").trim()));
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
      label: formatToolProgressLabel(locale, group),
      detail: group.detail || group.summary || "",
      status: normalizeProgressStatus(group.status),
      source: "tool",
      tool_group: group,
    });
  });
  liveItems.forEach((entry) => {
    progressItems.push(entry);
  });
  if (!hasLiveItems && !toolGroups.length && !llmStartedAt && !hasAnswerStarted && !hasAnswerReady && !turnTerminalError) {
    progressItems.push({
      id: "request-understanding",
      label: translateUi(locale, "activity.status.request_understanding"),
      status: "running",
      source: "fallback",
    });
  } else if (!hasLiveItems && !toolGroups.length && llmStartedAt && !hasAnswerStarted && !hasAnswerReady && !turnTerminalError) {
    progressItems.push({
      id: "waiting-model",
      label: translateUi(
        locale,
        nowMs - llmStartedAt >= MODEL_WAIT_SLOW_HINT_MS
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
  const sourceItems = Array.isArray(liveItems) && liveItems.length
    ? liveItems
    : buildFallbackProgressItems(activity, locale, nowMs);
  const traceItems = Array.isArray(runtimeTrace) ? runtimeTrace : [];
  return sourceItems.map((entry, index) => {
    const status = normalizeProgressStatus(entry.status);
    const toolGroup = entry.tool_group && typeof entry.tool_group === "object" ? entry.tool_group : {};
    const trace = traceItems[index] && typeof traceItems[index] === "object" ? traceItems[index] : {};
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
    const detail = String(entry.detail || trace.detail || target || "").trim()
      || translateUiOrFallback(locale, "activity.detail.recorded_arguments", "参数已记录");
    return {
      id: String(entry.id || trace.id || `main-live-${index}`),
      title,
      label: title,
      status,
      detail,
      tool,
      target,
      durationMs: Number(trace.duration_ms || 0) || 0,
      collapsible: true,
      rawRef: entry,
    };
  }).filter((entry, index, collection) => (
    collection.findIndex((candidate) => candidate.id === entry.id) === index
  ));
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
  const revisionSummary = latestRevisionSummary(item);
  const progressItems = item.plan.length
    ? buildPlanChecklistItems(item.plan)
    : buildFallbackProgressItems(item, locale, nowMs);
  const executionTrace = latestExecutionTrace(item);
  const toolGroups = buildToolProgressGroups(item);
  const mainLiveCards = buildMainLiveCards(item, progressItems, executionTrace, locale, nowMs);
  return {
    progress_items: progressItems,
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

function buildStructuredDebugView(activity, inspector = {}, locale = "zh-CN") {
  const item = normalizeMessageActivity(activity || {});
  const traces = item.trace_events.filter(Boolean);
  const toolGroups = buildToolProgressGroups(item);
  const modelRounds = [];
  let currentRound = null;
  traces.forEach((trace) => {
    const type = String(trace.type || "").trim();
    const payload = trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    if (type === "llm.started") {
      currentRound = {
        index: modelRounds.length + 1,
        model: String(payload.model || ""),
        phase: String(payload.phase || payload.stream_stage || ""),
        status: "running",
        decision: "",
        tool_count_total: 0,
        events: [trace],
      };
      modelRounds.push(currentRound);
      return;
    }
    if (!currentRound && (type.startsWith("llm.") || type === "model_action" || type.startsWith("tool_drain.") || type.startsWith("answer."))) {
      currentRound = {
        index: modelRounds.length + 1,
        model: String(payload.model || ""),
        phase: String(payload.phase || ""),
        status: "running",
        decision: "",
        tool_count_total: 0,
        events: [],
      };
      modelRounds.push(currentRound);
    }
    if (!currentRound) return;
    currentRound.events.push(trace);
    if (payload.model && !currentRound.model) currentRound.model = String(payload.model || "");
    if ((payload.phase || payload.stream_stage) && !currentRound.phase) currentRound.phase = String(payload.phase || payload.stream_stage || "");
    const modelAction = payload.model_action && typeof payload.model_action === "object" ? payload.model_action : {};
    if (modelAction.action_type) currentRound.decision = String(modelAction.action_type || "");
    if (type === "tool_drain.started" || type === "tool_drain.finished") {
      currentRound.decision = "tool_call";
      currentRound.tool_count_total = Math.max(
        Number(currentRound.tool_count_total || 0) || 0,
        Number(payload.tool_count_total || payload.tool_count_drained || 0) || 0,
      );
    }
    if (type === "answer.started" || type === "answer.delta" || type === "answer.done" || type === "answer.finished") {
      currentRound.decision = currentRound.decision || "final_answer";
    }
    if (type === "llm.finished" || type === "answer.done" || type === "answer.finished") {
      currentRound.status = "completed";
    } else if (type === "llm.failed") {
      currentRound.status = "failed";
    }
  });
  const latestHarnessPayload = [...traces].reverse().find((trace) => {
    const payload = trace && trace.payload && typeof trace.payload === "object" ? trace.payload : {};
    return Object.prototype.hasOwnProperty.call(payload, "tool_boundary_clean")
      || Object.prototype.hasOwnProperty.call(payload, "blocked_reason")
      || Object.prototype.hasOwnProperty.call(payload, "turn_status")
      || Object.prototype.hasOwnProperty.call(payload, "usage")
      || Object.prototype.hasOwnProperty.call(payload, "token_usage");
  });
  const latestHarness = latestHarnessPayload && latestHarnessPayload.payload && typeof latestHarnessPayload.payload === "object"
    ? latestHarnessPayload.payload
    : {};
  const inspectorRunState = inspector && inspector.run_state && typeof inspector.run_state === "object"
    ? inspector.run_state
    : {};
  const sentToModel = inspectorRunState.model_context && typeof inspectorRunState.model_context === "object"
    ? inspectorRunState.model_context
    : ((inspector && inspector.sent_to_model && typeof inspector.sent_to_model === "object") ? inspector.sent_to_model : {});
  const runtimeBoundary = inspectorRunState.runtime_boundary && typeof inspectorRunState.runtime_boundary === "object"
    ? inspectorRunState.runtime_boundary
    : {};
  const explicitBoundaryModelView = inspectorRunState.runtime_boundary_model_view && typeof inspectorRunState.runtime_boundary_model_view === "object"
    ? inspectorRunState.runtime_boundary_model_view
    : {};
  const boundaryModelView = Object.keys(explicitBoundaryModelView).length
    ? explicitBoundaryModelView
    : ((runtimeBoundary.model_view && typeof runtimeBoundary.model_view === "object") ? runtimeBoundary.model_view : runtimeBoundary);
  const modelPermissions = sentToModel.permissions && typeof sentToModel.permissions === "object"
    ? sentToModel.permissions
    : {};
  return {
    sent_to_model: sentToModel,
    user_context: {
      triggering_user_message: item.triggering_user_message,
      triggering_user_turn_id: item.triggering_user_turn_id,
      session_id: item.session_id,
      thread_id: item.thread_id,
      project: (inspector && inspector.project) || {},
      model: latestHarness.model || "",
      provider: latestHarness.provider || "",
      attachments_count: Number(latestHarness.attachments_count || latestHarness.attachment_count || 0) || 0,
      permission_profile: latestHarness.permission_profile || inspectorRunState.permission_profile || "",
    },
    model_rounds: modelRounds,
    tool_groups: toolGroups.map((group) => ({
      call_id: group.id,
      tool: group.tool_name,
      status: normalizeProgressStatus(group.status),
      arguments: group.raw_arguments,
      normalized_arguments: group.normalized_arguments,
      validation: group.validation_result,
      schema_validation: group.schema_validation,
      result_summary: group.summary,
      result_preview: group.result_preview,
      trace_types: group.trace_types,
    })),
    harness: {
      permission_profile:
        latestHarness.permission_profile
        || inspectorRunState.permission_profile
        || modelPermissions.profile
        || boundaryModelView.permission_profile
        || "",
      file_read_scope: boundaryModelView.file_read_scope || modelPermissions.read || "",
      file_write_scope: boundaryModelView.file_write_scope || modelPermissions.write || "",
      command_scope: boundaryModelView.command_scope || modelPermissions.shell || "",
      network_allowed: boundaryModelView.network_allowed,
      network_reason: boundaryModelView.network_reason || "",
      tool_boundary_clean: latestHarness.tool_boundary_clean,
      compaction_happened: traces.some((trace) => String(trace.type || "") === "context.compacted"),
      retry_happened: traces.some((trace) => String(trace.type || "").startsWith("llm.retry")),
      blocked_reason: latestHarness.blocked_reason || "",
      pending_user_input: latestHarness.pending_user_input || {},
      turn_status: latestHarness.turn_status || item.status,
      context_version: Number(inspectorRunState.context_version || 0) || 0,
      run_duration_ms: item.run_duration_ms || item.final_elapsed_ms || 0,
      token_usage: latestHarness.token_usage || latestHarness.usage || {},
    },
    final_status: {
      status: item.status,
      activity_summary: item.activity_summary,
      finished_at: item.finished_at,
      run_duration_ms: item.run_duration_ms || item.final_elapsed_ms || 0,
    },
    raw: {
      activity: item,
      inspector: inspector || {},
      trace_events: traces,
      locale,
    },
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

function runtimeToolTimelineForStats({ hasLiveRunState, liveToolTimeline, inspectorToolTimeline, fallbackToolTimeline }) {
  if (hasLiveRunState) {
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
  hasLiveRunState,
  liveToolTimeline,
  inspectorToolTimeline,
  fallbackToolTimeline,
  contextMeter,
  maxOutputTokens,
  tokenUsage,
  permissionProfile,
  boundaryModelView: boundaryModelViewOverride,
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
    hasLiveRunState,
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
      hasLiveRunState
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
  const elapsedValue = formatActivityDuration(activity, activityClockMs || Date.now()) || translateUi(locale, "context_meter.unknown");
  const autoCompactionEnabled = Boolean(safeContextMeter.compaction_enabled || safeguards.context_compaction);
  const effectivePermissionProfile = String(
    permissionProfile
    || currentRuntimeStatus.permission_profile
    || workspaceBoundary.permission_profile
    || boundaryModelView.permission_profile
    || "code",
  ).trim();
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
      { key: "output_limit", label: translateUi(locale, "context_meter.field.output_limit"), value: formatTokenCount(maxOutputTokens) },
      { key: "token_usage", label: translateUi(locale, "context_meter.field.token_usage"), value: formatRuntimeTokenUsage(locale, tokenUsage) },
      ...(safeContextMeter.context_window
        ? [{ key: "context_window", label: translateUi(locale, "context_meter.field.context_window"), value: formatTokenCount(safeContextMeter.context_window) }]
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
  if (drawerView === "run" || contextMeterOpen) return RUNTIME_STATUS_IDLE_INTERVAL_MS;
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

function activityStatusFromTraceType(type, fallback = "thinking") {
  const normalized = String(type || "").trim();
  if (!normalized) return fallback;
  if (normalized.startsWith("activity.")) return "thinking";
  if (
    normalized === "tool.started" ||
    normalized === "tool.call_detected" ||
    normalized === "action.detected" ||
    normalized === "action.validating" ||
    normalized === "action.allowed" ||
    normalized === "observation.returned"
  ) return "tooling";
  if (normalized === "answer.started" || normalized === "answer.finished" || normalized === "answer.done" || normalized === "answer.delta") return "answering";
  if (normalized === "approval.required" || normalized === "blocked" || normalized === "action.blocked" || normalized === "loop.safeguard") return "blocked";
  if (normalized === "run.finished") return "completed";
  if (normalized === "run.failed") return "failed";
  if (normalized === "cancelled") return "cancelled";
  return fallback;
}

function mergeActivityState(previous, patch = {}) {
  const prev = normalizeMessageActivity(previous || {});
  const nextPatch = patch && typeof patch === "object" ? patch : {};
  const nextTraceEvents = Array.isArray(nextPatch.trace_events)
    ? nextPatch.trace_events.map(normalizeTraceEvent)
    : prev.trace_events;
  const nextPlan = Array.isArray(nextPatch.plan)
    ? normalizePlanChecklist(nextPatch.plan)
    : prev.plan;
  const nextToolItems = Object.prototype.hasOwnProperty.call(nextPatch, "tool_items")
    ? mergeActivityToolItems(prev.tool_items, nextPatch.tool_items)
    : prev.tool_items;
  const nextLiveItems = Object.prototype.hasOwnProperty.call(nextPatch, "live_items")
    ? mergeLiveRunItems(prev.live_items, nextPatch.live_items)
    : prev.live_items;
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
  const nextFinalElapsedMs = isActivityTerminalStatus(nextStatus)
    ? Math.max(
      0,
      Number(prev.final_elapsed_ms || 0) || 0,
      Number(nextPatch.final_elapsed_ms || 0) || 0,
      nextRunDurationMs,
      nextTurnStartedAt && nextFinishedAt ? Math.max(0, nextFinishedAt - nextTurnStartedAt) : 0,
    )
    : Math.max(0, Number(prev.final_elapsed_ms || 0) || 0);
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
    activity_summary: String(nextPatch.activity_summary || prev.activity_summary || ""),
    plan: nextPlan,
    plan_explanation: String(nextPatch.plan_explanation || prev.plan_explanation || ""),
    tool_items: nextToolItems,
    live_items: nextLiveItems,
    trace_events: nextTraceEvents,
  };
}

function appendActivityTrace(activity, trace, options = {}) {
  const current = normalizeMessageActivity(activity || {});
  const normalizedTrace = normalizeTraceEvent(trace);
  const nextTraceEvents = [...current.trace_events, normalizedTrace];
  const nextLiveItem = liveRunItemFromTrace(normalizedTrace);
  const nextLiveItems = nextLiveItem
    ? mergeLiveRunItems(current.live_items, [nextLiveItem])
    : current.live_items;
  const nextStatus = String(
    options.status
    || current.status
    || activityStatusFromTraceType(normalizedTrace.type, "thinking"),
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
    : Math.max(0, Number(current.final_elapsed_ms || 0) || 0);
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
    live_items: nextLiveItems,
    trace_events: nextTraceEvents.slice(-64),
    activity_summary: String(current.activity_summary || ""),
  };
}

function formatActivityDuration(activity, nowMs = Date.now()) {
  const item = normalizeMessageActivity(activity || {});
  const turnStartedAt = item.turn_started_at || item.started_at;
  if (!turnStartedAt) return "";
  const frozenElapsedMs = Math.max(0, Number(item.final_elapsed_ms || 0) || 0);
  const durationMs = frozenElapsedMs || (
    item.finished_at
      ? Math.max(
        0,
        Number(item.run_duration_ms || 0) || 0,
        Math.max(0, item.finished_at - turnStartedAt),
      )
      : Math.max(0, nowMs - turnStartedAt)
  );
  return `${Math.max(0, Math.round(durationMs / 1000))}s`;
}

function activityPillLabel(locale, activity, nowMs = Date.now()) {
  const item = normalizeMessageActivity(activity || {});
  const status = String(item.status || "");
  const duration = formatActivityDuration(item, nowMs);
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
      sessionRunState: {},
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
      liveRunLogs: [],
      lastResponse: null,
      toolTimeline: [],
      liveTurnState: {},
      liveEvidence: {},
      liveToolTimeline: [],
      stageTimeline: [],
      activeRunId: "",
      stoppingRun: false,
    },
    panelCache: {
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
  if (Array.isArray(data && data.threads)) return data.threads;
  if (!Array.isArray(data && data.sessions)) return [];
  return data.sessions.map((item) => ({
    ...item,
    thread_id: String(item.thread_id || item.session_id || ""),
    session_id: String(item.session_id || item.thread_id || ""),
    status: String(item.status || "idle"),
  }));
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
  const sessionRunState = appState.threadIndex.sessionRunState;
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
  const [modelTouched, setModelTouched] = useState(false);
  const [selectedPresetModel, setSelectedPresetModel] = useState("");
  const [uiError, setUiError] = useState(null);
  const toolTimeline = appState.activeTurn.toolTimeline;
  const liveTurnState = appState.activeTurn.liveTurnState;
  const liveEvidence = appState.activeTurn.liveEvidence;
  const liveToolTimeline = appState.activeTurn.liveToolTimeline;
  const stageTimeline = appState.activeTurn.stageTimeline;
  const activeRunId = appState.activeTurn.activeRunId;
  const stoppingRun = Boolean(appState.activeTurn.stoppingRun);
  const workbenchTools = appState.panelCache.tools.data;
  const skills = appState.panelCache.skills.data;
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [skillEditor, setSkillEditor] = useState("");
  const specs = appState.panelCache.specs.data;
  const [selectedSpecName, setSelectedSpecName] = useState("soul.md");
  const [specEditor, setSpecEditor] = useState("");
  const [savingWorkbench, setSavingWorkbench] = useState(false);
  const [mobileThreadsOpen, setMobileThreadsOpen] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectPathDraft, setProjectPathDraft] = useState("");
  const [projectTitleDraft, setProjectTitleDraft] = useState("");
  const [projectFormError, setProjectFormError] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [creatingThread, setCreatingThread] = useState(false);
  const [appUpdateState, setAppUpdateState] = useState({ status: "idle", result: null, error: null });
  const [loadingEarlierTurns, setLoadingEarlierTurns] = useState(false);
  const [composerDragActive, setComposerDragActive] = useState(false);
  const [contextMeterOpen, setContextMeterOpen] = useState(false);
  const [projectMenu, setProjectMenu] = useState(null);
  const [threadMenu, setThreadMenu] = useState(null);
  const [activityOpenByMessageId, setActivityOpenByMessageId] = useState({});
  const [activityClockMs, setActivityClockMs] = useState(Date.now());
  const fileInputRef = useRef(null);
  const chatListRef = useRef(null);
  const contextMeterRef = useRef(null);
  const contextMeterCloseTimerRef = useRef(null);
  const bootReadyRef = useRef(false);
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
  const activeSessionIdRef = useRef("");
  const pendingThreadCreationPromiseRef = useRef(null);
  const pendingTempThreadIdRef = useRef("");
  const skillsRequestSeqRef = useRef(0);
  const runtimeStatusRequestSeqRef = useRef(0);
  const runtimeStatusAbortRef = useRef(null);
  const runtimeStatusInFlightRef = useRef({ key: "", promise: null });
  const runtimeStatusLastFetchedAtRef = useRef(0);
  const selectedSkillIdRef = useRef("");
  const skillDraftModeRef = useRef(false);
  const setHealth = (value) => dispatch({ type: "update", path: ["bootstrap", "health"], value });
  const setProjects = (value) => dispatch({ type: "update", path: ["projectIndex", "projects"], value });
  const setProjectId = (value) => dispatch({ type: "update", path: ["projectIndex", "currentProjectId"], value });
  const setSessions = (value) => dispatch({ type: "update", path: ["threadIndex", "threads"], value });
  const setSessionId = (value) => {
    if (typeof value !== "function") activeSessionIdRef.current = String(value || "");
    dispatch({ type: "update", path: ["threadIndex", "currentThreadId"], value });
  };
  const setSessionRunState = (value) => dispatch({ type: "update", path: ["threadIndex", "sessionRunState"], value });
  const setMessages = (value) => dispatch({ type: "update", path: ["items", "messages"], value });
  const setSending = (value) => dispatch({ type: "update", path: ["activeTurn", "sending"], value });
  const setLoadingSession = (value) => dispatch({ type: "update", path: ["threadIndex", "loading"], value });
  const setLiveRunLogs = (value) => dispatch({ type: "update", path: ["activeTurn", "liveRunLogs"], value });
  const hasRunningActivity = useMemo(
    () => messages.some((item) => {
      if (!item || item.role !== "assistant") return false;
      const activity = normalizeMessageActivity(item.activity || {});
      return Boolean(activity.turn_started_at || activity.started_at) && !isActivityTerminalStatus(activity.status);
    }),
    [messages],
  );
  const setLastResponse = (value) => dispatch({ type: "update", path: ["activeTurn", "lastResponse"], value });
  const setToolTimeline = (value) => dispatch({ type: "update", path: ["activeTurn", "toolTimeline"], value });
  const setLiveTurnState = (value) => dispatch({ type: "update", path: ["activeTurn", "liveTurnState"], value });
  const setLiveEvidence = (value) => dispatch({ type: "update", path: ["activeTurn", "liveEvidence"], value });
  const setLiveToolTimeline = (value) => dispatch({ type: "update", path: ["activeTurn", "liveToolTimeline"], value });
  const setStageTimeline = (value) => dispatch({ type: "update", path: ["activeTurn", "stageTimeline"], value });
  const setActiveRunId = (value) => dispatch({ type: "update", path: ["activeTurn", "activeRunId"], value });
  const setStoppingRun = (value) => dispatch({ type: "update", path: ["activeTurn", "stoppingRun"], value });
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
    const serverProfile = String(health.default_permission_profile || "").trim();
    if (!["chat", "code", "full_dev"].includes(serverProfile)) return;
    setChatSettings((prev) => (
      !prev.permission_profile || prev.permission_profile === DEFAULT_SETTINGS.permission_profile
        ? { ...prev, permission_profile: serverProfile }
        : prev
    ));
  }, [health]);

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
    return () => {
      if (contextMeterCloseTimerRef.current) {
        window.clearTimeout(contextMeterCloseTimerRef.current);
        contextMeterCloseTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const shouldTickActivityClock = hasRunningActivity || sending || Boolean(activeRunId);
    if (!shouldTickActivityClock) {
      setActivityClockMs(Date.now());
      return undefined;
    }
    setActivityClockMs(Date.now());
    const intervalId = window.setInterval(() => setActivityClockMs(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [activeRunId, hasRunningActivity, sending]);

  useEffect(() => {
    function handlePointerDown(event) {
      if (!contextMeterRef.current || contextMeterRef.current.contains(event.target)) return;
      setContextMeterOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  useEffect(() => {
    async function boot() {
      const [bootstrapData, projectsList] = await Promise.all([refreshBootstrap(), refreshProjects()]);
      const storedProjectId = window.localStorage.getItem(PROJECT_STORAGE_KEY) || "";
      const storedProjectExists = (projectsList || []).some((item) => String(item.project_id || "") === storedProjectId);
      const initialProjectId =
        (storedProjectExists ? storedProjectId : "") ||
        String((bootstrapData && bootstrapData.default_project_id) || "").trim() ||
        String(((projectsList || [])[0] || {}).project_id || "").trim();
      bootReadyRef.current = true;
      if (initialProjectId) {
        await selectProject(initialProjectId, { silentNotFound: true, fromBoot: true });
      } else {
        await refreshRuntimeStatus("", { background: true });
      }
    }
    boot();
  }, []);

  useEffect(() => {
    if (drawerView === "tools") refreshWorkbenchTools();
    if (drawerView === "skills") refreshSkills();
    if (drawerView === "agent") refreshSpecs();
  }, [drawerView, uiLocale]);

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
      sending,
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
  }, [projectId, chatSettings.model, chatSettings.max_output_tokens, sending, activeRunId, drawerView, contextMeterOpen]);

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
    if (appUpdateState.status === "running") return;
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

  function selectSkillFromList(skillId, list = skills) {
    const sid = String(skillId || "").trim();
    if (!sid) {
      startNewSkillDraft();
      return false;
    }
    const hit = shallowSkillList(list).find((item) => String(item.id || "") === sid);
    if (!hit) return false;
    clearUiError();
    setSkillSelectionState(sid, String(hit.content || ""));
    return true;
  }

  function syncSkillSelection(list, preferredSkillId) {
    const safeList = shallowSkillList(list);
    const explicitPreferred = typeof preferredSkillId === "string" ? String(preferredSkillId).trim() : null;
    const activeSkillId = explicitPreferred !== null ? explicitPreferred : String(selectedSkillIdRef.current || "").trim();
    if (activeSkillId && selectSkillFromList(activeSkillId, safeList)) {
      return;
    }
    if ((explicitPreferred === "" || (explicitPreferred === null && skillDraftModeRef.current)) && !activeSkillId) {
      startNewSkillDraft(skillEditor || defaultSkillTemplate(uiLocale));
      return;
    }
    if (safeList.length) {
      selectSkillFromList(String(safeList[0].id || ""), safeList);
      return;
    }
    startNewSkillDraft(skillEditor || defaultSkillTemplate(uiLocale));
  }

  function clearLiveRunUi() {
    setLastResponse(null);
    setToolTimeline([]);
    setLiveToolTimeline([]);
    setLiveTurnState({});
    setLiveEvidence({});
    setLiveRunLogs([]);
    setStageTimeline([]);
    setActiveRunId("");
    setStoppingRun(false);
    setContextMeterOpen(false);
  }

  function resetItemDomain() {
    dispatch({ type: "items/reset" });
  }

  function threadCacheKey(threadId) {
    return String(threadId || "").trim();
  }

  function snapshotFromThreadDetail(data) {
    const detail = normalizeThreadDetailPayload(data);
    return {
      detail,
      messages: extractSessionMessages(detail),
      sessionRunState: (detail && detail.agent_state) || {},
      cachedAt: Date.now(),
    };
  }

  function rememberThreadDetail(threadId, data) {
    const key = threadCacheKey(threadId);
    if (!key || isTempThreadId(key)) return null;
    const snapshot = snapshotFromThreadDetail(data);
    if (threadDetailCacheRef.current.has(key)) threadDetailCacheRef.current.delete(key);
    threadDetailCacheRef.current.set(key, snapshot);
    while (threadDetailCacheRef.current.size > THREAD_DETAIL_CACHE_LIMIT) {
      const oldestKey = threadDetailCacheRef.current.keys().next().value;
      threadDetailCacheRef.current.delete(oldestKey);
    }
    return snapshot;
  }

  function applyThreadSnapshot(threadId, snapshot) {
    if (!snapshot) return;
    const key = threadCacheKey(threadId);
    resetItemDomain();
    setMessages(snapshot.messages || []);
    setSessionRunState(snapshot.sessionRunState || {});
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
      const withoutTemp = previousList.filter(
        (entry) => String(entry.thread_id || entry.session_id || "").trim() !== tempKey,
      );
      const withoutReal = withoutTemp.filter(
        (entry) => String(entry.thread_id || entry.session_id || "").trim() !== threadKey,
      );
      return [{ ...normalized, thread_id: threadKey, session_id: String(normalized.session_id || threadKey) }, ...withoutReal];
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
    const promote = options.promote !== false;
    setSessions((prev) => {
      const previousList = Array.isArray(prev) ? prev : [];
      const existing = previousList.find((entry) => String(entry.thread_id || entry.session_id || "").trim() === threadKey) || {};
      const merged = { ...existing, ...normalized, thread_id: threadKey, session_id: String(normalized.session_id || threadKey) };
      const remainder = previousList.filter((entry) => String(entry.thread_id || entry.session_id || "").trim() !== threadKey);
      return promote ? [merged, ...remainder] : [...remainder, merged];
    });
  }

  function removeThreadRow(targetThreadId) {
    const normalizedThreadId = String(targetThreadId || "").trim();
    if (!normalizedThreadId) return;
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
    if (!item || sending || item.is_default) return;
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
    if (sending || (item && item.is_default)) return;
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
    if (!item || sending || isTempThreadId(item.session_id || item.thread_id)) return;
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
    if (sending || isTempThreadId(item && (item.session_id || item.thread_id))) return;
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
    loadSession(targetSessionId);
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
      setSessions(list);
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
    setSessionId("");
    resetItemDomain();
    setSessionRunState({});
    clearLiveRunUi();
    setStageTimeline([]);
    setMobileThreadsOpen(false);
    closeProjectMenu();
    closeThreadMenu();
    clearUiError();
    const [list] = await Promise.all([
      refreshSessions(targetProjectId),
      refreshRuntimeStatus(targetProjectId, { background: true }),
    ]);
    const storedSessionId = window.localStorage.getItem(sessionStorageKeyForProject(targetProjectId)) || "";
    const preferredSessionId =
      storedSessionId && list.some((item) => String(item.session_id || item.thread_id || "") === storedSessionId)
        ? storedSessionId
        : String((((list || [])[0] || {}).session_id) || (((list || [])[0] || {}).thread_id) || "").trim();
    if (preferredSessionId) {
      await loadSession(preferredSessionId, { silentNotFound: Boolean(options.silentNotFound), projectIdOverride: targetProjectId });
      return true;
    }
    if (!options.fromBoot) {
      pushLogWithLimit(setLogs, "system", t("log.project_switched", { project_id: targetProjectId.slice(0, 8) }));
    }
    return true;
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
      syncSkillSelection(list, preferredSkillId);
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
      sessionRunState,
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
    setSessionRunState({});
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
          setSessionRunState(previousSnapshot.sessionRunState || {});
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
    clearLiveRunUi();
    const cached = threadDetailCacheRef.current.get(sid);
    if (cached) {
      applyThreadSnapshot(sid, cached);
    } else {
      resetItemDomain();
      setMessages([]);
      setSessionRunState({});
    }
    try {
      const data = normalizeThreadDetailPayload(await fetchJson(
        `/api/thread/${encodeURIComponent(sid)}?max_turns=${THREAD_DETAIL_PAGE_SIZE}`,
        { signal: controller.signal },
      ));
      if (requestSeq !== activeThreadRequestSeqRef.current) return false;
      const snapshot = rememberThreadDetail(sid, data);
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
        `/api/thread/${encodeURIComponent(sid)}?max_turns=${THREAD_DETAIL_PAGE_SIZE}&before_turn_id=${encodeURIComponent(beforeTurnId)}`,
      ));
      if (activeSessionIdRef.current !== sid) return;
      const olderMessages = extractSessionMessages(data);
      setMessages((prev) => {
        const existingIds = new Set((Array.isArray(prev) ? prev : []).map((item) => String(item.id || "")));
        const merged = [
          ...olderMessages.filter((item) => !existingIds.has(String(item.id || ""))),
          ...(Array.isArray(prev) ? prev : []),
        ];
        threadDetailCacheRef.current.set(sid, {
          detail: data,
          messages: merged,
          sessionRunState: (data && data.agent_state) || sessionRunState || {},
          cachedAt: Date.now(),
        });
        while (threadDetailCacheRef.current.size > THREAD_DETAIL_CACHE_LIMIT) {
          const oldestKey = threadDetailCacheRef.current.keys().next().value;
          threadDetailCacheRef.current.delete(oldestKey);
        }
        return merged;
      });
      setSessionRunState((data && data.agent_state) || sessionRunState || {});
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
    if (!sid || sending || isTempThreadId(sid)) return;
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
          setSessionRunState({});
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

  async function handleDeleteProject(targetProjectId) {
    const pid = String(targetProjectId || "").trim();
    if (!pid || sending) return;
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
        setSessionRunState({});
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
    if (!runId || !sending || stoppingRun) return;
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

  async function handleSend(overrideText) {
    const messageText = String(overrideText != null ? overrideText : draft).trim();
    if (!messageText || sending) return;
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

    setSending(true);
    setContextMeterOpen(false);
    setStoppingRun(false);
    setActiveRunId("");
    clearUiError();
    setToolTimeline([]);
    setLiveToolTimeline([]);
    setLiveTurnState({});
    setLiveEvidence({});
    setLiveRunLogs([]);
    setStageTimeline([]);

    let sid = sessionId;
    let pendingMessage = null;
    try {
      if (isTempThreadId(sid) && pendingThreadCreationPromiseRef.current) {
        sid = await pendingThreadCreationPromiseRef.current;
      }
      if (!sid) sid = await createSession(projectId);

      const userMessage = createMessage("user", messageText);
      pendingMessage = createMessage("assistant", t("labels.processing"), {
        pending: true,
        activity: {
          status: "thinking",
          started_at: Date.now(),
          turn_started_at: Date.now(),
          trace_events: [],
        },
      });
      setMessages((prev) => [...prev, userMessage, pendingMessage]);
      setLiveTurnState({
        goal: messageText,
        permission_profile: chatSettings.permission_profile || "code",
        turn_status: "running",
        plan: [],
        pending_user_input: {},
      });
      setLiveEvidence({ status: "not_needed" });
      if (overrideText == null) setDraft("");

      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sid,
          project_id: projectId,
          message: messageText,
          client_submitted_at_ms: clientSubmittedAtMs,
          attachment_ids: readyAttachmentIds,
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
      let assistantText = "";
      let latestThreadId = String(sid || "");
      let latestRunSnapshot = {};
      let latestEvidenceState = { status: "not_needed" };
      let latestToolEvents = [];
      let latestTokenUsage = {};
      let latestSessionTokenTotals = {};
      let latestGlobalTokenTotals = {};
      let completedTurnPayload = null;
      let latestActivity = normalizeMessageActivity(pendingMessage.activity);

      const replacePendingText = (text, options = {}) => {
        if (options.onlyWhileWaiting && assistantMessageStarted) return;
        setMessages((prev) =>
          prev.map((item) => (item.id === pendingMessage.id ? { ...item, text } : item)),
        );
      };
      const patchPendingActivity = (updater) => {
        setMessages((prev) =>
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
      const completePendingText = (text) => {
        setMessages((prev) =>
          prev.map((item) => (
            item.id === pendingMessage.id
              ? createMessage("assistant", text, { id: item.id, activity: item.activity })
              : item
          )),
        );
      };
      const pushLiveLog = (type, text) => {
        setLiveRunLogs((prev) => [createLog(type, text), ...prev].slice(0, 32));
      };
      const applySnapshot = (snapshot) => {
        if (!snapshot || typeof snapshot !== "object") return;
        latestRunSnapshot = mergeRunSnapshot(latestRunSnapshot, snapshot);
        setLiveTurnState((prev) => mergeRunSnapshot(prev, snapshot));
        if (Object.prototype.hasOwnProperty.call(snapshot, "evidence_status")) {
          latestEvidenceState = {
            ...latestEvidenceState,
            status: String(snapshot.evidence_status || latestEvidenceState.status || "not_needed"),
          };
          setLiveEvidence((prev) => ({
            ...prev,
            status: String(snapshot.evidence_status || prev.status || "not_needed"),
          }));
        }
        if (snapshot.context_meter && typeof snapshot.context_meter === "object") {
          setHealth((prev) => (
            prev
              ? { ...prev, context_meter: snapshot.context_meter }
              : prev
          ));
          setSessionRunState((prev) => ({ ...(prev || {}), context_meter: snapshot.context_meter }));
        }
        if (snapshot.compaction_status && typeof snapshot.compaction_status === "object") {
          setHealth((prev) => (
            prev
              ? { ...prev, compaction_status: snapshot.compaction_status }
              : prev
          ));
          setSessionRunState((prev) => ({ ...(prev || {}), compaction_status: snapshot.compaction_status }));
        }
      };
      const recordToolItem = (item) => {
        if (!item || typeof item !== "object") return;
        latestToolEvents = [item, ...latestToolEvents.filter((entry) => String(entry.id || "") !== String(item.id || ""))].slice(0, 24);
        setToolTimeline((prev) => [item, ...prev.filter((entry) => String(entry.id || "") !== String(item.id || ""))].slice(0, 24));
        setLiveToolTimeline((prev) => [item, ...prev.filter((entry) => String(entry.id || "") !== String(item.id || ""))].slice(0, 24));
        patchPendingActivity((activity) => mergeActivityState(activity, {
          tool_items: [item],
        }));
        const toolName = String(item.tool || item.name || item.type || "tool");
        const summary = toolTimelineSummary(
          { ...item, name: toolName, summary: item.summary || item.output_preview || toolName },
          uiLocale,
        );
        pushLogWithLimit(setLogs, "tool", `${toolName}: ${summary}`);
        pushLiveLog("tool", `${toolName}: ${summary}`);
      };
      const buildFallbackFinalPayload = () => ({
        session_id: latestThreadId || sid,
        thread_id: latestThreadId || sid,
        run_id: String(((completedTurnPayload || {}).id) || activeRunId || ""),
        agent_id: "vintage_programmer",
        effective_model: String(
          chatSettings.model ||
          (activeProviderProfile && activeProviderProfile.default_model) ||
          (health && health.default_model) ||
          "",
        ).trim(),
        text: assistantText || "",
        tool_events: latestToolEvents,
        permission_profile: String(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "code"),
        turn_status: String(((completedTurnPayload || {}).status) || latestRunSnapshot.turn_status || "completed"),
        plan: Array.isArray(latestRunSnapshot.plan) ? latestRunSnapshot.plan : [],
        pending_user_input: latestRunSnapshot.pending_user_input || {},
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
              setActiveRunId(String(payload.run_id || ""));
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
            if (event === "run_started") {
              patchPendingActivity((activity) => mergeActivityState(activity, {
                run_id: String(payload.run_id || ""),
                status: "thinking",
              }));
            } else if (event === "run_finished") {
              const nextStatus = String(payload.turn_status || latestRunSnapshot.turn_status || "completed");
              patchPendingActivity((activity) => mergeActivityState(activity, {
                run_id: String(payload.run_id || ""),
                status: nextStatus === "needs_user_input" ? "blocked" : (nextStatus || "completed"),
                finished_at: Date.now(),
                run_duration_ms: Math.max(0, Number(payload.duration_ms || 0) || 0),
                final_elapsed_ms: Math.max(0, Number(payload.duration_ms || 0) || 0),
              }));
              setSending(false);
              setStoppingRun(false);
              setActiveRunId("");
            } else if (event === "run_failed") {
              patchPendingActivity((activity) => mergeActivityState(activity, {
                run_id: String(payload.run_id || ""),
                status: "failed",
                finished_at: Date.now(),
              }));
              setSending(false);
              setStoppingRun(false);
              setActiveRunId("");
            } else if (event === "trace_event") {
              const trace = normalizeTraceEvent(payload.trace || {});
              if (trace.id) {
                const nextStatus = activityStatusFromTraceType(trace.type, latestActivity.status || "thinking");
                patchPendingActivity((activity) => appendActivityTrace(activity, trace, { status: nextStatus }));
              }
              const detail = String(trace.title || trace.detail || "");
              if (detail) {
                pushLogWithLimit(setLogs, "trace", detail);
                pushLiveLog("trace", detail);
              }
            } else if (event === "thread/started") {
              if (payload.thread) upsertThreadRow(payload.thread, { promote: true });
            } else if (event === "thread/status/changed") {
              updateThreadStatus(payload.thread_id, ((payload.status || {}).type) || "idle");
            } else if (event === "thread/updated") {
              if (payload.thread) upsertThreadRow(payload.thread, { promote: true });
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
              if (turnId) setActiveRunId(turnId);
              if (String(turn.threadId || "").trim()) {
                latestThreadId = String(turn.threadId || "").trim();
                updateThreadStatus(latestThreadId, "active");
              }
              applySnapshot({
                permission_profile: String(payload.permission_profile || chatSettings.permission_profile || "code"),
                turn_status: "running",
              });
            } else if (event === "turn/plan/updated") {
              const nextPlan = Array.isArray(payload.plan) ? payload.plan : [];
              applySnapshot({ plan: nextPlan });
              setSessionRunState((prev) => ({
                ...(prev || {}),
                permission_profile: String((latestRunSnapshot.permission_profile) || chatSettings.permission_profile || "code"),
                turn_status: String((latestRunSnapshot.turn_status) || "running"),
                plan: nextPlan,
              }));
              const explanation = String(payload.explanation || "checklist updated");
              patchPendingActivity((activity) => mergeActivityState(activity, {
                plan: nextPlan,
                plan_explanation: explanation,
              }));
              pushLogWithLimit(setLogs, "system", explanation);
              pushLiveLog("system", explanation);
            } else if (event === "turn/completed") {
              completedTurnPayload = payload.turn && typeof payload.turn === "object" ? payload.turn : {};
              const completionStatus = String((completedTurnPayload && completedTurnPayload.status) || latestRunSnapshot.turn_status || "completed");
              applySnapshot({ turn_status: completionStatus });
              patchPendingActivity((activity) => mergeActivityState(activity, {
                status: completionStatus === "needs_user_input" ? "blocked" : (completionStatus || "completed"),
                finished_at: Date.now(),
              }));
              if (assistantText) completePendingText(assistantText);
              setSending(false);
              setStoppingRun(false);
              setActiveRunId("");
            } else if (event === "item/started") {
              const item = payload.item && typeof payload.item === "object" ? payload.item : {};
              if (item.id) {
                patchPendingActivity((activity) => mergeActivityState(activity, {
                  live_items: [liveRunItemFromStreamItem(item, event)],
                }));
              }
              if (item.id) {
                dispatch({
                  type: "items/register",
                  item: {
                    ...item,
                    threadId: String(payload.thread_id || latestThreadId || ""),
                    turnId: String(payload.turn_id || activeRunId || ""),
                  },
                });
              }
              if (String(item.type || "") === "agentMessage") {
                assistantMessageStarted = true;
              }
            } else if (event === "item/agentMessage/delta") {
              assistantMessageStarted = true;
              const delta = String(payload.delta || "");
              if (delta) {
                assistantText += delta;
                dispatch({ type: "items/agentDelta", itemId: String(payload.item_id || ""), delta, status: "inProgress" });
                replacePendingText(assistantText);
              }
            } else if (event === "item/completed") {
              const item = payload.item && typeof payload.item === "object" ? payload.item : {};
              if (item.id) {
                patchPendingActivity((activity) => mergeActivityState(activity, {
                  live_items: [liveRunItemFromStreamItem(item, event)],
                }));
              }
              if (item.id) {
                dispatch({
                  type: "items/register",
                  item: {
                    ...item,
                    threadId: String(payload.thread_id || latestThreadId || ""),
                    turnId: String(payload.turn_id || activeRunId || ""),
                  },
                });
              }
              const itemType = String(item.type || "");
              if (itemType === "agentMessage") {
                assistantMessageStarted = true;
                assistantText = String(item.text || assistantText || "");
                if (assistantText) completePendingText(assistantText);
              } else if (itemType === "userInputRequest") {
                const nextPending = {
                  summary: String(item.summary || ""),
                  questions: Array.isArray(item.questions) ? item.questions : [],
                };
                applySnapshot({
                  permission_profile: String(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "code"),
                  turn_status: "needs_user_input",
                  pending_user_input: nextPending,
                });
                setSessionRunState((prev) => ({
                  ...(prev || {}),
                  permission_profile: String(latestRunSnapshot.permission_profile || chatSettings.permission_profile || "code"),
                  turn_status: "needs_user_input",
                  pending_user_input: nextPending,
                }));
                replacePendingText(String(nextPending.summary || t("labels.pending_input")));
                pushLogWithLimit(setLogs, "system", String(nextPending.summary || "user input required"));
                pushLiveLog("system", String(nextPending.summary || "user input required"));
              } else if (["toolCall", "commandExecution", "fileChange", "imageView"].includes(itemType)) {
                recordToolItem(item);
              }
            } else if (event === "stage") {
              const detail = String(payload.detail || payload.label || payload.code || t("labels.processing"));
              replacePendingText(detail, { onlyWhileWaiting: true });
              pushLogWithLimit(setLogs, "stage", detail);
              pushLiveLog("stage", detail);
            } else if (event === "trace") {
              const detail = String(payload.message || payload.raw || "");
              if (detail) {
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

      if (!finalPayload && (completedTurnPayload || assistantText || Object.keys(latestRunSnapshot).length)) {
        finalPayload = buildFallbackFinalPayload();
      }
      if (!finalPayload) throw new Error("missing final payload");
      const finalActivity = mergeActivityState(finalPayload.activity || latestActivity, {
        plan: Array.isArray(finalPayload.plan) ? finalPayload.plan : (Array.isArray(latestRunSnapshot.plan) ? latestRunSnapshot.plan : []),
        plan_explanation: String(latestActivity.plan_explanation || ""),
        tool_items: latestActivity.tool_items,
      });
      setMessages((prev) =>
        prev.map((item) =>
          item.id === pendingMessage.id
            ? createMessage("assistant", String(finalPayload.text || assistantText || "(empty response)"), {
              id: item.id,
              activity: finalActivity,
            })
            : item,
        ),
      );
      setLastResponse(finalPayload);
      setPendingUploads([]);
      clearUiError();
      if (finalPayload.thread_id || finalPayload.session_id) {
        latestThreadId = String(finalPayload.thread_id || finalPayload.session_id || latestThreadId || "");
        if (latestThreadId) setSessionId(latestThreadId);
      }
      setActiveRunId(String(finalPayload.run_id || ""));
      setLiveTurnState((prev) => mergeRunSnapshot(prev, {
        ...(((finalPayload.inspector || {}).run_state) || {}),
        permission_profile: String(finalPayload.permission_profile || (((finalPayload.inspector || {}).run_state || {}).permission_profile) || chatSettings.permission_profile || "code"),
        turn_status: String(finalPayload.turn_status || (((finalPayload.inspector || {}).run_state || {}).turn_status) || "completed"),
        context_meter: finalPayload.context_meter || (((finalPayload.inspector || {}).run_state || {}).context_meter) || (((finalPayload.inspector || {}).session || {}).context_meter) || {},
        plan: Array.isArray(finalPayload.plan) ? finalPayload.plan : ((((finalPayload.inspector || {}).run_state || {}).plan) || []),
        pending_user_input: finalPayload.pending_user_input || (((finalPayload.inspector || {}).run_state || {}).pending_user_input) || {},
      }));
      setLiveEvidence((prev) => ({
        ...prev,
        ...latestEvidenceState,
        ...(((finalPayload.inspector || {}).evidence) || {}),
      }));
      setLiveToolTimeline(Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events : latestToolEvents);
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
      setSessionRunState({
        ...(finalPayload.inspector || {}).run_state,
        ...(finalPayload.inspector || {}).evidence,
        ...(finalPayload.inspector || {}).session,
        ...{
          agent_id: finalPayload.agent_id || "vintage_programmer",
          goal: String((((finalPayload.inspector || {}).run_state || {}).goal) || messageText),
          current_goal: String((((finalPayload.inspector || {}).run_state || {}).goal) || messageText),
          permission_profile: String(finalPayload.permission_profile || (((finalPayload.inspector || {}).run_state || {}).permission_profile) || chatSettings.permission_profile || "code"),
          turn_status: String(finalPayload.turn_status || (((finalPayload.inspector || {}).run_state || {}).turn_status) || "completed"),
          plan: Array.isArray(finalPayload.plan) ? finalPayload.plan : ((((finalPayload.inspector || {}).run_state || {}).plan) || []),
          pending_user_input: finalPayload.pending_user_input || (((finalPayload.inspector || {}).run_state || {}).pending_user_input) || {},
          phase: String((((finalPayload.inspector || {}).run_state || {}).phase) || "report"),
          last_run_id: String(finalPayload.run_id || ""),
          last_model: String(finalPayload.effective_model || ""),
          context_meter: finalPayload.context_meter || (((finalPayload.inspector || {}).run_state || {}).context_meter) || (((finalPayload.inspector || {}).session || {}).context_meter) || {},
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
        t("log.reply_received", { count: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0 }),
      );
      pushLiveLog(
        "response",
        t("log.reply_received", { count: Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0 }),
      );
      setSending(false);
      setStoppingRun(false);
      setActiveRunId("");
    } catch (err) {
      const nextError = applyUiError(err, t("errors.request_failed"));
      pushLogWithLimit(setLogs, "error", t("log.send_failed", { summary: nextError.summary }));
      setMessages((prev) => prev.filter((item) => !(pendingMessage && item.id === pendingMessage.id)));
    } finally {
      setSending(false);
      setStoppingRun(false);
      setActiveRunId("");
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
      const targetSkillId = String(selectedSkillIdRef.current || "").trim();
      const method = targetSkillId ? "PUT" : "POST";
      const url = targetSkillId
        ? `/api/workbench/skills/${encodeURIComponent(targetSkillId)}`
        : "/api/workbench/skills";
      const payload = await fetchJson(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: skillEditor }),
      });
      const nextSkillId = String(payload.id || targetSkillId || "").trim();
      setSkillSelectionState(nextSkillId, String(payload.content || ""));
      await refreshSkills(nextSkillId);
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.skill_saved", { skill_id: nextSkillId || "new_skill" }));
    } catch (err) {
      const nextError = applyUiError(err, t("errors.save_skill_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.save_skill_failed"));
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function toggleSelectedSkill(nextEnabled) {
    const targetSkillId = String(selectedSkillIdRef.current || "").trim();
    if (!targetSkillId) return;
    setSavingWorkbench(true);
    try {
      const payload = await fetchJson(`/api/workbench/skills/${encodeURIComponent(targetSkillId)}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      const nextSkillId = String(payload.id || targetSkillId || "").trim();
      setSkillSelectionState(nextSkillId, String(payload.content || ""));
      await refreshSkills(nextSkillId);
      clearUiError();
      pushLogWithLimit(
        setLogs,
        "system",
        t("log.skill_toggled", {
          status: payload.enabled ? t("skills.status.enabled") : t("skills.status.disabled"),
          skill_id: nextSkillId,
        }),
      );
    } catch (err) {
      const nextError = applyUiError(err, t("errors.toggle_skill_failed"));
      pushLogWithLimit(setLogs, "error", t("errors.toggle_skill_failed"));
    } finally {
      setSavingWorkbench(false);
    }
  }

  async function handleDeleteSelectedSkill() {
    const targetSkillId = String(selectedSkillIdRef.current || "").trim();
    if (!targetSkillId) return;
    const currentIndex = skills.findIndex((item) => String(item.id || "") === targetSkillId);
    const fallbackSkillId =
      String(((currentIndex >= 0 ? skills[currentIndex + 1] : null) || {}).id || "").trim() ||
      String(((currentIndex > 0 ? skills[currentIndex - 1] : null) || {}).id || "").trim();
    if (!window.confirm(t("confirm.delete_skill", { skill_id: targetSkillId }))) {
      return;
    }
    setSavingWorkbench(true);
    try {
      await fetchJson(`/api/workbench/skills/${encodeURIComponent(targetSkillId)}`, { method: "DELETE" });
      if (fallbackSkillId) {
        skillDraftModeRef.current = false;
      }
      await refreshSkills(fallbackSkillId);
      clearUiError();
      pushLogWithLimit(setLogs, "system", t("log.skill_deleted", { skill_id: targetSkillId }));
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
  const completedRunState = lastInspector.run_state || {};
  const completedEvidence = lastInspector.evidence || {};
  const hasLiveRunState = Boolean(sending || (activeRunId && Object.keys(liveTurnState || {}).length));
  const runState = hasLiveRunState ? liveTurnState : completedRunState;
  const evidence = hasLiveRunState ? liveEvidence : completedEvidence;
  const modelContextForRun = (
    runState.model_context && typeof runState.model_context === "object"
  )
    ? runState.model_context
    : ((lastInspector.sent_to_model && typeof lastInspector.sent_to_model === "object") ? lastInspector.sent_to_model : {});
  const modelContextTask = modelContextForRun.task && typeof modelContextForRun.task === "object" ? modelContextForRun.task : {};
  const modelContextWorkspace = modelContextForRun.workspace && typeof modelContextForRun.workspace === "object" ? modelContextForRun.workspace : {};
  const modelContextMemory = modelContextForRun.memory && typeof modelContextForRun.memory === "object" ? modelContextForRun.memory : {};
  const activeTaskCheckpoint = {
    goal: String(modelContextTask.goal || modelContextTask.user_request || runState.goal || sessionRunState.goal || ""),
    cwd: String(modelContextWorkspace.cwd || runState.cwd || sessionRunState.cwd || ""),
    next_action: String(modelContextTask.next_action || modelContextTask.current_step || ""),
    active_files: Array.isArray(modelContextMemory.active_files) ? modelContextMemory.active_files : [],
    active_attachments: [],
  };
  const ocrStatus = (health && health.ocr_status && typeof health.ocr_status === "object") ? health.ocr_status : {};
  const selectedPermissionProfile = String(chatSettings.permission_profile || "code");
  const selectedPermissionProfileClass = selectedPermissionProfile.replaceAll("_", "-");
  const selectedPermissionDescription = t(`settings.permission_profile.${selectedPermissionProfile}.help`);
  const selectedPermissionAriaLabel = `${t("settings.permission_profile")}: ${selectedPermissionDescription}`;
  const activePermissionProfile = String(
    (hasLiveRunState ? runState.permission_profile : "")
    || selectedPermissionProfile
    || "code",
  );
  const activeBoundaryModelView = (
    runState.runtime_boundary_model_view && typeof runState.runtime_boundary_model_view === "object"
  )
    ? runState.runtime_boundary_model_view
    : {};
  const activeTurnStatus = String(runState.turn_status || sessionRunState.turn_status || "idle");
  const activePlan = Array.isArray(runState.plan) && runState.plan.length
    ? runState.plan
    : (Array.isArray(sessionRunState.plan) ? sessionRunState.plan : []);
  const activePendingInput =
    (runState.pending_user_input && typeof runState.pending_user_input === "object")
      ? runState.pending_user_input
      : ((sessionRunState.pending_user_input && typeof sessionRunState.pending_user_input === "object") ? sessionRunState.pending_user_input : {});
  const activeToolTimeline = hasLiveRunState
    ? liveToolTimeline
    : (Array.isArray(lastInspector.tool_timeline) && lastInspector.tool_timeline.length
      ? lastInspector.tool_timeline
      : toolTimeline);
  const activeRunLogs = hasLiveRunState ? liveRunLogs : logs;
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
  const activeContextMeter = normalizeContextMeter(
    (runState && runState.context_meter) ||
    (lastResponse && lastResponse.context_meter) ||
    (sessionRunState && sessionRunState.context_meter) ||
    (health && health.context_meter) ||
    {},
  );
  const activeCompactionStatus = normalizeCompactionStatus(
    (runState && runState.compaction_status) ||
    (lastResponse && lastResponse.compaction_status) ||
    (sessionRunState && sessionRunState.compaction_status) ||
    (health && health.compaction_status) ||
    {},
  );
  const compactionWarningText = formatCompactionWarning(uiLocale, activeCompactionStatus, activeContextMeter);
  const compactionReasonText = formatCompactionReason(uiLocale, activeCompactionStatus.last_compaction_reason);
  const contextMeterColor = resolveContextMeterColor(activeContextMeter);
  const groupedTools = useMemo(() => groupTools(workbenchTools), [workbenchTools]);
  const selectedSkill = skills.find((item) => item.id === selectedSkillId) || null;
  const selectedSpec = specs.find((item) => String(item.name || "") === selectedSpecName) || null;
  const displayVersion = normalizeReleaseVersion((health && health.app_version) || "");
  const appUpdateRunning = appUpdateState.status === "running";
  const appUpdateResult = appUpdateState.result && typeof appUpdateState.result === "object" ? appUpdateState.result : null;
  const appUpdateCommands = Array.isArray(appUpdateResult && appUpdateResult.commands) ? appUpdateResult.commands : [];
  const appUpdateErrorText = appUpdateState.error ? String(appUpdateState.error.detail || appUpdateState.error.summary || "") : "";
  const currentThread = sessions.find((item) => String(item.session_id || item.thread_id || "") === String(sessionId || "")) || null;
  const totalTurnsForCurrentThread = Math.max(0, Number((currentThread && currentThread.turn_count) || 0) || 0);
  const canLoadEarlierTurns = Boolean(
    sessionId &&
    !isTempThreadId(sessionId) &&
    messages.length > 0 &&
    totalTurnsForCurrentThread > messages.length,
  );
  const headTitle = sessionId ? sessionTitleFromList(sessions, sessionId, uiLocale) : (workspaceLabel || t("labels.start_building"));
  const headBreadcrumb = [
    workspaceLabel || "",
    currentProjectRoot ? compactPath(currentProjectRoot) : "",
    currentProjectBranch || "",
    loadedSkills.length ? `skills:${loadedSkills.length}` : "no skills",
  ].filter(Boolean).join(" · ");
  const statusSummary = [
    workspaceLabel || "-",
    activeProviderLabel || activeProvider || "-",
  ].filter(Boolean).join(" · ");
  const runtimeStats = useMemo(() => buildRuntimeStatsSummary({
    locale: uiLocale,
    workspaceLabel,
    runtimeStatus,
    activeModel,
    activeTurnStatus,
    messages,
    activityClockMs,
    hasLiveRunState,
    liveToolTimeline,
    inspectorToolTimeline: lastInspector.tool_timeline,
    fallbackToolTimeline: toolTimeline,
    contextMeter: activeContextMeter,
    maxOutputTokens: chatSettings.max_output_tokens || DEFAULT_SETTINGS.max_output_tokens,
    tokenUsage: (lastResponse && lastResponse.token_usage) || {},
    permissionProfile: activePermissionProfile,
    boundaryModelView: activeBoundaryModelView,
  }), [
    uiLocale,
    workspaceLabel,
    runtimeStatus,
    activeModel,
    activeTurnStatus,
    messages,
    activityClockMs,
    hasLiveRunState,
    liveToolTimeline,
    lastInspector,
    toolTimeline,
    activeContextMeter,
    chatSettings.max_output_tokens,
    activePermissionProfile,
    activeBoundaryModelView,
    lastResponse,
  ]);

  const toggleMessageActivity = (messageId) => {
    setActivityOpenByMessageId((prev) => ({
      ...prev,
      [messageId]: !prev[messageId],
    }));
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
    const mainLiveCards = Array.isArray(projection && projection.main_live_cards) ? projection.main_live_cards : progressItems;
    const completionSummary = (projection && projection.completion_summary && typeof projection.completion_summary === "object")
      ? projection.completion_summary
      : {};
    const preview = Boolean(options.preview);
    const isTerminal = isActivityTerminalStatus(item.status);
    const visibleItems = preview
      ? (isTerminal ? [] : mainLiveCards.slice(0, MAIN_LIVE_CARD_LIMIT))
      : progressItems;
    const overflowCount = preview && !isTerminal
      ? Math.max(0, mainLiveCards.length - visibleItems.length)
      : 0;
    const durationLabel = formatActivityDuration(item, activityClockMs || Date.now());
    const note = String(
      (projection && projection.revision_badge)
      || (isTerminal ? completionSummary.label : "")
      || item.activity_summary
      || "",
    ).trim();
    if (!visibleItems.length && !note) return null;
    const markerForStatus = (status) => {
      const normalized = normalizeProgressStatus(status);
      if (normalized === "completed") return "✓";
      if (normalized === "failed" || normalized === "blocked" || normalized === "cancelled") return "!";
      return "○";
    };
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
        ${visibleItems.length
          ? html`
              <div className="activity-progress-list">
                ${visibleItems.map((entry) => {
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
          : null}
        ${overflowCount
          ? html`<div className="activity-flow-note">${t("activity.more_steps", { count: overflowCount })}</div>`
          : null}
        ${note ? html`<div className="activity-flow-note">${note}</div>` : null}
      </div>
    `;
  };

  const renderActivityDebugDetails = (activity, projection, messageId) => {
    const item = normalizeMessageActivity(activity || {});
    const structured = buildStructuredDebugView(item, lastInspector || {}, uiLocale);
    const traces = Array.isArray((projection && projection.trace_events)) ? projection.trace_events : [];
    const sentToModelDetails = renderDetailBlock(t("activity.debug.sent_to_model"), structured.sent_to_model, { open: true });
    const modelOutputSections = [
      renderDetailBlock(t("activity.triggering_user_message"), item.triggering_user_message),
      item.plan.length
        ? renderDetailBlock(t("run.checklist"), {
            explanation: item.plan_explanation,
            plan: item.plan,
          })
        : null,
      renderPlanDetails(t("activity.model_action"), projection.model_action),
      renderRevisionSummaryDetails(projection.revision_summary),
    ].filter(Boolean);
    const modelRoundDetails = structured.model_rounds.length
      ? html`
          <details className="activity-payload" open>
            <summary>${t("activity.debug.model_rounds")}</summary>
            <div className="activity-structured-details">
              ${structured.model_rounds.map((round) => html`
                <details key=${`round-${round.index}`} className="activity-payload">
                  <summary>${t("activity.debug.round_n", { n: round.index })} · ${round.status || "-"}</summary>
                  ${renderDetailBlock(t("labels.payload"), {
                    model: round.model,
                    phase: round.phase,
                    status: round.status,
                    decision: round.decision,
                    tool_count_total: round.tool_count_total,
                  })}
                </details>
              `)}
            </div>
          </details>
        `
      : null;
    const toolDebugDetails = structured.tool_groups.length
      ? html`
          <details className="activity-payload">
            <summary>${t("activity.debug.tool_execution")}</summary>
            <div className="activity-structured-details">
              ${structured.tool_groups.map((toolItem, index) => html`
                <details key=${toolItem.call_id || `${messageId}-tool-${index}`} className="activity-payload">
                  <summary>${toolItem.tool || "tool"} · ${toolItem.call_id || "-"}</summary>
                  ${renderToolAuditDetails({
                    raw_arguments: toolItem.arguments,
                    normalized_arguments: toolItem.normalized_arguments,
                    validation_result: toolItem.validation,
                    schema_validation: toolItem.schema_validation,
                    result_preview: toolItem.result_preview,
                  })}
                  ${renderDetailBlock(t("labels.payload"), toolItem)}
                </details>
              `)}
            </div>
          </details>
        `
      : null;
    const harnessDetails = renderDetailBlock(t("activity.debug.runtime"), structured.harness, { open: true });
    const finalStatusDetails = renderDetailBlock(t("activity.debug.final_status"), structured.final_status);
    const modelOutputDetails = modelRoundDetails || modelOutputSections.length || finalStatusDetails
      ? html`
          <details className="activity-payload" open>
            <summary>${t("activity.debug.model_output")}</summary>
            <div className="activity-structured-details">
              ${modelOutputSections}
              ${modelRoundDetails}
              ${finalStatusDetails}
            </div>
          </details>
        `
      : null;
    const rawTraceList = traces.length
      ? html`
          <details className="activity-payload">
            <summary>${t("activity.debug.advanced_raw")}</summary>
            ${renderDetailBlock(t("activity.debug.raw_json"), structured.raw)}
          </details>
        `
      : null;
    if (!sentToModelDetails && !modelOutputDetails && !toolDebugDetails && !harnessDetails && !rawTraceList) return null;
    return html`
      <details className="activity-debug-drawer">
        <summary>${t("activity.debug_details")}</summary>
        <div className="activity-debug-sections">
          ${sentToModelDetails}
          ${modelOutputDetails}
          ${toolDebugDetails}
          ${harnessDetails}
          ${rawTraceList}
        </div>
      </details>
    `;
  };

  const renderMessageActivity = (item) => {
    if (!item || item.role !== "assistant") return null;
    const activity = normalizeMessageActivity(item.activity || {});
    const projection = buildActivityProjection(activity, uiLocale, activityClockMs || Date.now());
    const hasActivity = Boolean(
      projection.progress_items.length
      || projection.trace_events.length
      || activity.turn_started_at
      || activity.started_at
      || activity.status
      || activity.run_duration_ms
      || activity.activity_summary,
    );
    if (!hasActivity) return null;
    const isOpen = Boolean(activityOpenByMessageId[item.id]);
    const tone = activityToneClass(activity.status);
    const pillLabel = activityPillLabel(uiLocale, activity, activityClockMs || Date.now());
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
        ${!isOpen ? renderActivityProgressList(projection, activity, { preview: true }) : null}
        ${isOpen
          ? html`
              <div className="activity-panel">
                <div className="activity-panel-head">
                  <div className="activity-panel-title">${t("activity.title")}</div>
                  <div className=${`activity-badge tone-${tone}`}>${pillLabel}</div>
                </div>
                ${renderActivityProgressList(projection, activity)}
                ${renderActivityDebugDetails(activity, projection, item.id)}
              </div>
            `
          : null}
      </div>
    `;
  };

  return html`
    <div className="workspace-shell" id="appShell">
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
          <button className="solid-btn" type="button" onClick=${handleNewSession} disabled=${creatingThread || sending}>${t("buttons.new_thread")}</button>
          <button
            className="ghost-btn"
            type="button"
            onClick=${handleAppUpdate}
            disabled=${sending || appUpdateRunning}
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
                          disabled=${sending}
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
                          onClick=${(event) => handleThreadClick(event, item.session_id)}
                          onContextMenu=${(event) => handleThreadContextMenu(event, item)}
                          onTouchStart=${(event) => handleThreadTouchStart(event, item)}
                          onTouchEnd=${cancelThreadLongPress}
                          onTouchMove=${cancelThreadLongPress}
                          onTouchCancel=${cancelThreadLongPress}
                          disabled=${sending}
                        >
                          <div className="thread-row-title">${item.title || t("labels.new_thread")}</div>
                          <div className="thread-row-meta">${formatTime(item.updated_at, uiLocale)} · ${item.turn_count || 0}</div>
                        </button>
                  `,
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
                ${agentInfo.title || "Vintage Programmer"}
                ${headBreadcrumb ? ` · ${headBreadcrumb}` : ""}
              </div>
            </div>
          </div>
          <div className="head-actions">
            <button className=${`mini-btn ${drawerView === "run" ? "active" : ""}`} type="button" onClick=${() => setDrawerView(drawerView === "run" ? "" : "run")}>${currentTabLabel("run")}</button>
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
          </div>
        </header>

        <section className="conversation-plane" id="messageList" ref=${chatListRef}>
          ${canLoadEarlierTurns
            ? html`
                <div className="load-earlier-row">
                  <button className="ghost-btn compact-btn" type="button" onClick=${loadEarlierTurns} disabled=${loadingEarlierTurns}>
                    ${loadingEarlierTurns ? t("buttons.running") : t("buttons.load_earlier")}
                  </button>
                </div>
              `
            : null}
          ${messages.length
            ? messages.map(
                (item) => html`
                  <article key=${item.id} className=${`message-article role-${item.role} ${item.pending ? "pending" : ""} ${item.error ? "error" : ""}`}>
                    <div className="message-meta">
                      <span className="message-role">${roleLabel(item.role, uiLocale)}</span>
                      ${item.createdAt ? html`<span className="message-time">${formatTime(item.createdAt, uiLocale)}</span>` : null}
                    </div>
                    <div className="message-card">
                      ${renderMessageActivity(item)}
                      <div
                        className="message-card-body message-markdown"
                        dangerouslySetInnerHTML=${{ __html: renderMessageHtml(item.text, item.id) }}
                      ></div>
                    </div>
                  </article>
                `,
              )
            : html`
                <section className="empty-panel">
                  <div className="empty-kicker">OpenClaw-first Tools · Codex-style Workspace</div>
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
        </section>

        <section
          className=${`composer-shell ${composerDragActive ? "drag-active" : ""}`}
          id="composerShell"
          onDragEnter=${handleComposerDragEnter}
          onDragOver=${handleComposerDragOver}
          onDragLeave=${handleComposerDragLeave}
          onDrop=${handleComposerDrop}
        >
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
              <button className="icon-btn" type="button" onClick=${() => fileInputRef.current && fileInputRef.current.click()} disabled=${sending}>+</button>
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
                    const nextValue = target ? target.value : "code";
                    setChatSettings((prev) => ({ ...prev, permission_profile: nextValue }));
                  }}
                  disabled=${sending}
                  title=${selectedPermissionDescription}
                  aria-label=${selectedPermissionAriaLabel}
                >
                  <option value="chat" title=${t("settings.permission_profile.chat.help")}>${t("settings.permission_profile.chat")}</option>
                  <option value="code" title=${t("settings.permission_profile.code.help")}>${t("settings.permission_profile.code")}</option>
                  <option value="full_dev" title=${t("settings.permission_profile.full_dev.help")}>${t("settings.permission_profile.full_dev")}</option>
                </select>
              </label>
            </div>
            <div className="composer-toolbar-right">
              ${sending && activeRunId
                ? html`
                    <button className="ghost-btn" type="button" onClick=${handleStopRun} disabled=${stoppingRun}>
                      ${stoppingRun ? t("buttons.stopping") : t("buttons.stop")}
                    </button>
                  `
                : null}
              <button className="ghost-btn" type="button" onClick=${() => setDrawerView(drawerView ? "" : "run")}>Workbench</button>
            </div>
          </div>

          <div className="composer-frame">
            <textarea
              value=${draft}
              onInput=${(event) => setDraft(event.currentTarget.value)}
              onKeyDown=${handleComposerKeyDown}
              onPaste=${handleComposerPaste}
              placeholder=${t("composer.placeholder")}
              disabled=${sending}
            ></textarea>
	            <button
                className="send-btn"
                type="button"
                onClick=${() => handleSend()}
                disabled=${sending || !draft.trim() || pendingUploads.some((item) => item && item.uploading)}
              >
	              ${sending ? t("buttons.running") : (pendingUploads.some((item) => item && item.uploading) ? t("labels.uploading") : t("buttons.send"))}
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
                  <span className="status-model-label">${activeModel || "-"}</span>
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
                  ${currentTabLabel(tab)}
                </button>
              `,
            )}
          </div>
          <button className="drawer-close" type="button" onClick=${() => setDrawerView("")}>${t("buttons.close")}</button>
        </div>

        ${drawerView === "run"
          ? html`
              <div className="workbench-scroll">
                <section className="panel-card">
                  <div className="panel-title">${t("run.title")}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "goal")}: ${runState.goal || sessionRunState.goal || sessionRunState.current_goal || "-"}</div>
                  <div className="meta-line">${t("settings.permission_profile")}: ${t(`settings.permission_profile.${activePermissionProfile}`)}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "turn_status")}: ${formatRunEnum(uiLocale, "turn_status", activeTurnStatus, "idle")}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "evidence")}: ${formatRunEnum(uiLocale, "evidence", evidence.status || sessionRunState.evidence_status || "not_needed", "not_needed")}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "inline_document")}: ${formatRunBoolean(uiLocale, runState.inline_document)}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "ocr")}: ${formatRunEnum(uiLocale, "ocr_engine", ocrStatus.default_engine || "unavailable", "unavailable")}</div>
                  <div className="meta-line">
                    ${formatRunFieldLabel(uiLocale, "compaction")}: ${formatRunEnum(uiLocale, "compaction_mode", activeCompactionStatus.mode || "token_budget", "token_budget")}
                    ${activeCompactionStatus.last_compaction_phase ? ` · ${formatRunEnum(uiLocale, "compaction_phase", activeCompactionStatus.last_compaction_phase, activeCompactionStatus.last_compaction_phase)}` : ""}
                  </div>
                  <div className="meta-line">
                    ${formatRunFieldLabel(uiLocale, "context")}: ${formatTokenCount(activeCompactionStatus.estimated_context_tokens || activeContextMeter.estimated_tokens)}
                    /
                    ${formatTokenCount(activeCompactionStatus.auto_compact_token_limit || activeContextMeter.auto_compact_token_limit)}
                  </div>
                  <div className="meta-line">
                    ${formatRunFieldLabel(uiLocale, "generation")}: ${activeCompactionStatus.generation || 0}
                    · ${formatRunFieldLabel(uiLocale, "retained_turns")}: ${activeCompactionStatus.retained_turn_count || 0}
                  </div>
                  ${ocrStatus.warning ? html`<div className="timeline-detail">${ocrStatus.warning}</div>` : null}
                  ${compactionReasonText
                    ? html`<div className="timeline-detail">${compactionReasonText}</div>`
                    : null}
                  ${compactionWarningText
                    ? html`<div className="timeline-detail">${compactionWarningText}</div>`
                    : null}
                </section>

                <section className="panel-card">
                  <div className="panel-title">${t("run.current_focus")}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "task_id")}: ${activeTaskCheckpoint.task_id || "-"}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "goal")}: ${activeTaskCheckpoint.goal || runState.goal || sessionRunState.goal || "-"}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "cwd")}: ${activeTaskCheckpoint.cwd || sessionRunState.cwd || "-"}</div>
                  <div className="meta-line">${formatRunFieldLabel(uiLocale, "next_action")}: ${activeTaskCheckpoint.next_action || "-"}</div>
                  ${Array.isArray(activeTaskCheckpoint.active_files) && activeTaskCheckpoint.active_files.length
                    ? html`
                        <div className="timeline-detail">
                          ${formatRunFieldLabel(uiLocale, "files")}: ${activeTaskCheckpoint.active_files.slice(0, 6).map((item) => compactPath(item)).join(" · ")}
                        </div>
                      `
                    : null}
                  ${Array.isArray(activeTaskCheckpoint.active_attachments) && activeTaskCheckpoint.active_attachments.length
                    ? html`
                        <div className="timeline-detail">
                          ${formatRunFieldLabel(uiLocale, "attachments")}: ${activeTaskCheckpoint.active_attachments
                            .slice(0, 6)
                            .map((item) => item.name || compactPath(item.path || item.id || "attachment"))
                            .join(" · ")}
                        </div>
                      `
                    : null}
                </section>

                ${activePlan.length
                  ? html`
                      <section className="panel-card">
                        <div className="panel-title">${t("run.checklist")}</div>
                        <div className="timeline-list">
                          ${activePlan.map(
                            (item) => html`
                              <div key=${`${item.step || "step"}-${item.status || ""}`} className="timeline-row">
                                <div className="timeline-head">
                                  <span>${item.step || "step"}</span>
                                  <span>${formatRunEnum(uiLocale, "plan_status", item.status || "pending", item.status || "pending")}</span>
                                </div>
                              </div>
                            `,
                          )}
                        </div>
                      </section>
                    `
                  : null}

                ${Array.isArray(activePendingInput.questions) && activePendingInput.questions.length
                  ? html`
                      <section className="panel-card">
                        <div className="panel-title">${t("run.pending_input")}</div>
                        <div className="timeline-list">
                          ${activePendingInput.questions.map(
                            (item) => html`
                              <div key=${item.id || item.header || item.question} className="timeline-row">
                                <div className="timeline-head">
                                  <span>${item.header || item.id || "question"}</span>
                                  <span>${(item.options || []).length} ${formatRunFieldLabel(uiLocale, "options")}</span>
                                </div>
                                <div className="timeline-detail">${item.question || ""}</div>
                                <div className="timeline-detail">
                                  ${(Array.isArray(item.options) ? item.options : []).map((option) => option.label).join(" / ")}
                                </div>
                              </div>
                            `,
                          )}
                        </div>
                      </section>
                    `
                  : null}

                <section className="panel-card">
                  <div className="panel-title">${t("run.recent_tools")}</div>
                  <div className="timeline-list">
                    ${activeToolTimeline.length
                      ? activeToolTimeline.map(
                          (item, index) => html`
                            <div key=${`${item.name || "tool"}-${index}`} className="timeline-row">
                              <div className="timeline-head">
                                <span>${item.name || "tool"}</span>
                                <span>${formatToolGroupLabel(uiLocale, item.group || item.module_group || "tool")}</span>
                              </div>
                              <div className="timeline-detail">${toolTimelineSummary(item, uiLocale)}</div>
                              ${renderToolAuditDetails(item)}
                              ${item.diagnostics && typeof item.diagnostics === "object" && Object.keys(item.diagnostics).length
                                ? html`
                                    <details className="timeline-details">
                                      <summary>${t("run.diagnostics")}</summary>
                                      <pre>${stringifyCompactJson(item.diagnostics)}</pre>
                                    </details>
                                  `
                                : null}
                            </div>
                          `,
                        )
                      : html`<div className="empty-inline">${t("run.no_tools")}</div>`}
                  </div>
                </section>

                <section className="panel-card">
                  <div className="panel-title">${t("run.logs")}</div>
                  <div className="timeline-list">
                    ${activeRunLogs.length
                      ? activeRunLogs.map((item) => html`<div key=${item.id} className=${`log-row tone-${item.type}`}>${item.text}</div>`)
                      : html`<div className="empty-inline">${t("run.no_logs")}</div>`}
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
                      }}>${t("buttons.new")}</button>
                      <button className="solid-btn" type="button" onClick=${saveSkill} disabled=${savingWorkbench || !skillEditor.trim()}>${t("buttons.save")}</button>
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
                              disabled=${savingWorkbench}
                            >
                              ${t("buttons.delete")}
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
                              onClick=${() => selectSkillFromList(item.id)}
                            >
                              <div className="resource-row-title">${item.title || item.id}</div>
                              <div className="resource-row-meta">${item.enabled ? t("skills.status.enabled") : t("skills.status.disabled")} · ${formatValidationStatus(uiLocale, item.validation_status)}</div>
                            </button>
                          `,
                        )
                      : html`<div className="empty-inline">${t("skills.none")}</div>`}
                  </div>

                  <textarea
                    className="editor-textarea"
                    value=${skillEditor}
                    onInput=${(event) => setSkillEditor(event.currentTarget.value)}
                    placeholder=${t("skills.placeholder")}
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
                  <label className="form-field">
                    <span>${t("settings.model_preset")}</span>
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
                  </label>
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
  `;
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");
createRoot(root).render(html`<${AppErrorBoundary}><${App} /></${AppErrorBoundary}>`);
