const state = {
  sessionId: null,
  uploading: false,
  sendingSessionIds: new Set(),
  attachments: [],
  drilling: false,
  evaluating: false,
};
const SESSION_STORAGE_KEY = "officetool.session_id";

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
const tokenStatsView = document.getElementById("tokenStatsView");
const clearStatsBtn = document.getElementById("clearStatsBtn");
const appVersionView = document.getElementById("appVersionView");

const modelInput = document.getElementById("modelInput");
const execModeInput = document.getElementById("execModeInput");
const tokenInput = document.getElementById("tokenInput");
const ctxInput = document.getElementById("ctxInput");
const styleInput = document.getElementById("styleInput");
const toolInput = document.getElementById("toolInput");
const rawDebugInput = document.getElementById("rawDebugInput");
const presetGeneralBtn = document.getElementById("presetGeneralBtn");
const presetCodingBtn = document.getElementById("presetCodingBtn");
const modeStatus = document.getElementById("modeStatus");
const backendPolicyView = document.getElementById("backendPolicyView");
const runStageBadge = document.getElementById("runStageBadge");
const runStageText = document.getElementById("runStageText");
const runStepList = document.getElementById("runStepList");
const runPayloadView = document.getElementById("runPayloadView");
const runTraceView = document.getElementById("runTraceView");
const runAgentPanelsView = document.getElementById("runAgentPanelsView");
const runAnswerBundleView = document.getElementById("runAnswerBundleView");
const runLlmFlowView = document.getElementById("runLlmFlowView");

const RUN_FLOW_STEPS = [
  { id: "prepare", label: "1. 准备请求" },
  { id: "send", label: "2. 发送请求" },
  { id: "wait", label: "3. 模型处理中" },
  { id: "parse", label: "4. 解析结果" },
  { id: "done", label: "5. 完成" },
];

const LLM_FLOW_STAGE_LABELS = {
  frontend_prepare: "前端组包",
  frontend_error: "前端错误",
  backend_ingress: "后端接收输入",
  backend_to_llm: "后端编排器 -> 模型角色",
  llm_to_backend: "模型角色 -> 后端编排器",
  backend_tool: "后端编排器执行工具",
  backend_prefetch: "后端编排器预取",
  llm_final: "模型角色输出",
  llm_error: "模型角色错误",
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

function hasAnswerBundleContent(bundle) {
  if (!bundle || typeof bundle !== "object") return false;
  return Boolean(
    String(bundle.summary || "").trim() ||
      (Array.isArray(bundle.claims) && bundle.claims.length) ||
      (Array.isArray(bundle.citations) && bundle.citations.length) ||
      (Array.isArray(bundle.warnings) && bundle.warnings.length)
  );
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
      warningNode.textContent = `warning: ${warning}`;
      item.appendChild(warningNode);
    }
    section.appendChild(item);
  });

  wrap.appendChild(section);
}

function buildAnswerBundleNode(bundle) {
  const wrap = document.createElement("div");
  wrap.className = "answer-bundle";

  const summary = String(bundle?.summary || "").trim();
  if (summary) {
    const summaryNode = document.createElement("div");
    summaryNode.className = "answer-bundle-summary";
    summaryNode.textContent = summary;
    wrap.appendChild(summaryNode);
  }

  const claims = Array.isArray(bundle?.claims) ? bundle.claims : [];
  if (claims.length) {
    const section = document.createElement("div");
    section.className = "answer-bundle-section";
    const title = document.createElement("div");
    title.className = "answer-bundle-title";
    title.textContent = "Claims";
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
  appendCitationSection(wrap, evidence.length ? "Evidence" : "Sources", evidence);
  appendCitationSection(wrap, "Search Candidates", candidates, "这些链接仅是搜索候选，尚未抓取正文。");

  const warnings = Array.isArray(bundle?.warnings) ? bundle.warnings : [];
  if (warnings.length) {
    const section = document.createElement("div");
    section.className = "answer-bundle-section";
    const title = document.createElement("div");
    title.className = "answer-bundle-title";
    title.textContent = "Warnings";
    section.appendChild(title);
    warnings.slice(0, 5).forEach((warning) => {
      const item = document.createElement("div");
      item.className = "answer-bundle-warning";
      item.textContent = String(warning || "");
      section.appendChild(item);
    });
    wrap.appendChild(section);
  }

  return wrap;
}

function addBubble(role, text, answerBundle = null) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  const value = typeof text === "string" ? text : String(text ?? "");
  if (role === "assistant") {
    const content = document.createElement("div");
    content.innerHTML = renderAssistantMarkdown(value);
    bubble.appendChild(content);
    if (hasAnswerBundleContent(answerBundle)) {
      bubble.appendChild(buildAnswerBundleNode(answerBundle));
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

function renderAssistantMarkdown(text) {
  const source = String(text ?? "");
  const markedApi = window.marked;
  const purifyApi = window.DOMPurify;

  if (markedApi && purifyApi && typeof markedApi.parse === "function") {
    try {
      const html = markedApi.parse(source, {
        gfm: true,
        breaks: true,
      });
      return purifyApi.sanitize(html, { USE_PROFILES: { html: true } });
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

  let html = escapeHtml(withCodeTokens);
  html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/\n/g, "<br>");

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
  const defaultExtraRoots = Array.isArray(health.default_extra_allowed_roots) ? health.default_extra_allowed_roots : [];
  const source = String(health.extra_allowed_roots_source || "platform_default").trim().toLowerCase();
  const sourceLabel = source === "env_override" ? "环境变量覆盖" : "平台默认";

  const lines = [
    `平台: ${platformName}`,
    `路径策略: ${allowAnyPath ? "不限制（ALLOW_ANY_PATH）" : "只允许已配置根目录"}`,
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

      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.className = "session-history-item";
      if (sid === state.sessionId) openBtn.classList.add("active");

      const title = document.createElement("div");
      title.className = "session-history-title";
      title.textContent = String(item?.title || "新会话");
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
      });
      sessionHistoryView.appendChild(openBtn);
    });
    return sessions;
  } catch {
    sessionHistoryView.textContent = "历史会话加载失败";
    return [];
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

  const activeIndex = RUN_FLOW_STEPS.findIndex((step) => step.id === activeStepId);
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
  if (runStageBadge) {
    runStageBadge.textContent = stageLabel;
    runStageBadge.className = `stage-badge stage-${tone}`;
  }
  if (runStageText) {
    runStageText.textContent = text;
  }
  renderRunSteps(stepId, tone === "error");
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
      lines.push(`${idx + 1}. ${tool?.name || "unknown"}(${args})${modeSuffix}`);
    });
  }

  runTraceView.textContent = lines.join("\n");
}

function renderAgentPanels(panels = [], plan = []) {
  if (!runAgentPanelsView) return;

  const lines = [];
  if (Array.isArray(plan) && plan.length) {
    lines.push("Execution Plan:");
    plan.forEach((item, idx) => {
      lines.push(`${idx + 1}. ${String(item || "")}`);
    });
    lines.push("");
  }

  if (Array.isArray(panels) && panels.length) {
    panels.forEach((panel, idx) => {
      const role = String(panel?.role || `agent_${idx + 1}`);
      const title = String(panel?.title || role);
      const summary = String(panel?.summary || "").trim();
      const bullets = Array.isArray(panel?.bullets) ? panel.bullets : [];
      lines.push(`[${idx + 1}] ${title} (${role})`);
      if (summary) lines.push(summary);
      bullets.forEach((item) => lines.push(`- ${String(item || "")}`));
      lines.push("");
    });
  }

  if (!lines.length) {
    runAgentPanelsView.textContent = "暂无多 Agent 摘要";
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
    lines.push("claims:");
    claims.slice(0, 5).forEach((claim, idx) => {
      const ids = Array.isArray(claim?.citation_ids) ? claim.citation_ids.join(", ") : "";
      lines.push(`${idx + 1}. ${String(claim?.statement || "").trim()}`);
      lines.push(`   status=${String(claim?.status || "supported")} confidence=${String(claim?.confidence || "medium")} citations=${ids || "(none)"}`);
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
      if (citation?.warning) lines.push(`  warning: ${citation.warning}`);
    });
    lines.push("");
  };
  appendCitationLines(evidence.length ? "evidence" : "citations", evidence);
  appendCitationLines("search_candidates", candidates, "候选链接，尚未抓取正文");

  const warnings = Array.isArray(bundle?.warnings) ? bundle.warnings : [];
  if (warnings.length) {
    lines.push("warnings:");
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

async function createSession() {
  const res = await fetch("/api/session/new", { method: "POST" });
  if (!res.ok) throw new Error(`create session failed: ${res.status}`);
  const data = await res.json();
  state.sessionId = data.session_id;
  refreshSession();
  await refreshTokenStatsFromServer();
  await refreshSessionHistory();
}

async function uploadSingle(file) {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch("/api/upload", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`上传失败 ${file.name}: ${res.status} ${text}`);
  }
  return res.json();
}

async function handleFiles(files) {
  if (!files || !files.length) return;

  state.uploading = true;
  updateSendAvailability();
  addBubble("system", `正在上传 ${files.length} 个文件...`);

  try {
    for (const file of files) {
      const uploaded = await uploadSingle(file);
      state.attachments.push(uploaded);
    }
    refreshFileList();
    const names = state.attachments.map((x) => x.name).join("，");
    addBubble("system", `上传完成，共 ${files.length} 个文件。\n当前附件：${names}`);
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
  setRunStage("进行中", `开始沙盒演练，执行环境 ${modeLabel}`, "prepare", "working");
  if (runPayloadView) {
    runPayloadView.textContent = `sandbox drill payload:\n${formatJsonPreview(payload)}`;
  }
  renderRunTrace(["沙盒演练请求已发送。"], []);
  renderAgentPanels([], []);
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
    renderAgentPanels([], []);
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
    renderRunTrace([msg], []);
    renderAgentPanels([], []);
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
  setRunStage("进行中", "开始回归测试（默认非 optional 用例）", "prepare", "working");
  if (runPayloadView) {
    runPayloadView.textContent = `eval harness payload:\n${formatJsonPreview(payload)}`;
  }
  renderRunTrace(["回归测试请求已发送。"], []);
  renderAgentPanels([], []);
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
    renderAgentPanels(panels, []);
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
    renderRunTrace([msg], []);
    renderAgentPanels([], []);
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
  }
}

async function sendMessage() {
  const message = messageInput.value.trim();
  if (!message) return;
  let requestSessionId = currentSessionKey();
  if (requestSessionId && isSessionSending(requestSessionId)) return;
  let stopWaitTicker = null;
  const isForegroundSession = () => currentSessionKey() === requestSessionId;

  setRunStage("进行中", "正在准备本轮请求参数", "prepare", "working");

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
    renderRunPayload(
      body,
      state.attachments.map((x) => x.name)
    );
    const liveTrace = ["客户端已组装请求，等待发送。"];
    const liveToolEvents = [];
    let liveExecutionPlan = [];
    let liveAgentPanels = [];
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
    renderAgentPanels([], []);
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
        liveTrace.push(line);
        renderRunTrace(liveTrace, liveToolEvents);
      },
      onDebug: (payload) => {
        if (!isForegroundSession()) return;
        const item = payload?.item;
        if (!item || typeof item !== "object") return;
        liveFlow.push(item);
        renderLlmFlow(liveFlow);
      },
      onToolEvent: (payload) => {
        if (!isForegroundSession()) return;
        const item = payload?.item;
        if (!item || typeof item !== "object") return;
        liveToolEvents.push(item);
        renderRunTrace(liveTrace, liveToolEvents);
      },
      onAgentState: (payload) => {
        if (!isForegroundSession()) return;
        liveExecutionPlan = Array.isArray(payload?.execution_plan) ? payload.execution_plan : liveExecutionPlan;
        liveAgentPanels = Array.isArray(payload?.panels) ? payload.panels : liveAgentPanels;
        renderAgentPanels(liveAgentPanels, liveExecutionPlan);
      },
      onHeartbeat: () => {
        if (!isForegroundSession()) return;
        heartbeatCount += 1;
        if (heartbeatCount === 1 || heartbeatCount % 3 === 0) {
          liveTrace.push(
            `后端心跳：仍在处理中（约 ${heartbeatCount * 10}s 无新事件，连接正常）`
          );
          renderRunTrace(liveTrace, liveToolEvents);
        }
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

      renderRunTrace(data.execution_trace || [], data.tool_events || []);
      renderAgentPanels(data.agent_panels || [], data.execution_plan || []);
      renderAnswerBundle(data.answer_bundle || {});
      renderLlmFlow(data.debug_flow || []);
      addBubble("assistant", data.text, data.answer_bundle || null);
    }
    await refreshSessionHistory();
    if (isForegroundSession()) {
      renderTokenStats({
        last: data.token_usage || {},
        session: data.session_token_totals || {},
        global: data.global_token_totals || {},
      });
      setRunStage("完成", "本轮已完成", "done", "done");
    }
  } catch (err) {
    if (typeof stopWaitTicker === "function") {
      stopWaitTicker();
      stopWaitTicker = null;
    }
    if (isForegroundSession()) {
      renderRunTrace([`请求失败: ${String(err)}`], []);
      renderAgentPanels([], []);
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

if (presetGeneralBtn) {
  presetGeneralBtn.addEventListener("click", () => applyModePreset("general"));
}

if (presetCodingBtn) {
  presetCodingBtn.addEventListener("click", () => applyModePreset("coding"));
}

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

newSessionBtn.addEventListener("click", async () => {
  await createSession();
  state.attachments = [];
  refreshFileList();
  clearChat();
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
  setRunStage("空闲", "等待发送请求", null, "idle");
  updateDrillAvailability();
  updateEvalAvailability();
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
  renderAgentPanels([], []);
  renderLlmFlow([]);
  try {
    const health = await fetch("/api/health").then((r) => r.json());
    renderAppVersion(health);
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
      const allowAllWebDomains = Boolean(health.web_allow_all_domains);
      const webDomains = Array.isArray(health.web_allowed_domains) ? health.web_allowed_domains : [];
      const pathPolicyTip = Boolean(health.allow_any_path)
        ? "文件路径：不限制（ALLOW_ANY_PATH）"
        : `文件根目录：${Array.isArray(health.allowed_roots) && health.allowed_roots.length ? health.allowed_roots.join(", ") : "(空)"}`;
      const webPolicyTip = allowAllWebDomains
        ? "联网域名：不限制"
        : `联网域名白名单：${webDomains.length ? webDomains.join(", ") : "(空)"}`;
      addBubble(
        "system",
        `服务已启动，版本：${String(health.build_version || health.app_version || "unknown")}；默认模型：${health.model_default}；默认执行环境：${backendExecMode}（${dockerTip}）。\n${pathPolicyTip}\n${webPolicyTip}${dockerMsg ? `\nDocker: ${dockerMsg}` : ""}`
      );
    }
    await refreshTokenStatsFromServer();
  } catch {
    addBubble("system", "健康检查失败，请确认后端已运行。", null);
  }
})();
