import React, { useEffect, useRef, useState } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

const SESSION_STORAGE_KEY = "vintage_programmer.session_id";
const DEFAULT_SETTINGS = {
  model: "",
  max_output_tokens: 128000,
  max_context_turns: 2000,
  enable_tools: true,
  response_style: "normal",
};

function createMessage(role, text, options = {}) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    pending: Boolean(options.pending),
    error: Boolean(options.error),
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

function formatSessionTime(raw) {
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
    return {
      event,
      payload: JSON.parse(dataLines.join("\n")),
    };
  } catch {
    return {
      event,
      payload: { raw: dataLines.join("\n") },
    };
  }
}

function roleLabel(role) {
  if (role === "user") return "你";
  if (role === "assistant") return "Vintage Programmer";
  return "系统";
}

function pushLogWithLimit(setter, type, text) {
  setter((prev) => [createLog(type, text), ...prev].slice(0, 20));
}

function fileNameFromHealth(health) {
  const path = String((health && health.workspace_root) || "").trim();
  if (!path) return "workspace";
  const parts = path.split("/");
  return parts[parts.length - 1] || "workspace";
}

function App() {
  const [health, setHealth] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [logs, setLogs] = useState([]);
  const [lastResponse, setLastResponse] = useState(null);
  const [pendingUploads, setPendingUploads] = useState([]);
  const [chatSettings, setChatSettings] = useState(DEFAULT_SETTINGS);
  const [modelTouched, setModelTouched] = useState(false);
  const [lastError, setLastError] = useState("");
  const fileInputRef = useRef(null);
  const chatListRef = useRef(null);

  useEffect(() => {
    const stored = window.localStorage.getItem(SESSION_STORAGE_KEY) || "";
    if (stored) setSessionId(stored);
  }, []);

  useEffect(() => {
    if (!sessionId) {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!health || modelTouched) return;
    setChatSettings((prev) => ({
      ...prev,
      model: String(prev.model || health.default_model || "").trim(),
    }));
  }, [health, modelTouched]);

  useEffect(() => {
    if (!chatListRef.current) return;
    chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    async function boot() {
      await refreshHealth();
      await refreshSessions();
      const stored = window.localStorage.getItem(SESSION_STORAGE_KEY) || "";
      if (stored) {
        await loadSession(stored, { silentNotFound: true });
      }
    }
    boot();
  }, []);

  async function refreshHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`health ${res.status}`);
      const data = await res.json();
      setHealth(data);
      return data;
    } catch (err) {
      const detail = String(err.message || err);
      setLastError(detail);
      pushLogWithLimit(setLogs, "error", `刷新状态失败：${detail}`);
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
      const detail = String(err.message || err);
      setLastError(detail);
      pushLogWithLimit(setLogs, "error", `刷新线程失败：${detail}`);
      return [];
    }
  }

  async function createSession() {
    const res = await fetch("/api/session/new", { method: "POST" });
    if (!res.ok) throw new Error(`create session ${res.status}`);
    const data = await res.json();
    const sid = String(data.session_id || "").trim();
    if (!sid) throw new Error("session id missing");
    setSessionId(sid);
    setMessages([]);
    setLastResponse(null);
    await refreshSessions();
    pushLogWithLimit(setLogs, "system", `已创建新线程 ${sid.slice(0, 8)}`);
    return sid;
  }

  async function loadSession(targetSessionId, options = {}) {
    const sid = String(targetSessionId || "").trim();
    if (!sid) return false;
    setLoadingSession(true);
    try {
      const res = await fetch(`/api/session/${encodeURIComponent(sid)}?max_turns=120`);
      if (!res.ok) {
        if (res.status === 404 && options.silentNotFound) return false;
        throw new Error(`session ${res.status}`);
      }
      const data = await res.json();
      const turns = Array.isArray(data.turns) ? data.turns : [];
      const normalized = turns.map((turn) =>
        createMessage(
          String(turn.role || "").toLowerCase() === "user" ? "user" : "assistant",
          String(turn.text || ""),
        ),
      );
      setMessages(normalized);
      setSessionId(sid);
      setLastResponse(null);
      pushLogWithLimit(setLogs, "system", `已载入线程 ${sid.slice(0, 8)}`);
      return true;
    } catch (err) {
      const detail = String(err.message || err);
      setLastError(detail);
      pushLogWithLimit(setLogs, "error", `载入线程失败：${detail}`);
      return false;
    } finally {
      setLoadingSession(false);
    }
  }

  async function handleNewSession() {
    try {
      await createSession();
    } catch (err) {
      const detail = String(err.message || err);
      setLastError(detail);
      pushLogWithLimit(setLogs, "error", `新线程失败：${detail}`);
    }
  }

  async function uploadFiles(files) {
    const uploaded = [];
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/upload", {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        let detail = `upload ${res.status}`;
        try {
          const payload = await res.json();
          if (payload.detail) detail = String(payload.detail);
        } catch {
          // ignore parse errors
        }
        throw new Error(`${file.name}: ${detail}`);
      }
      uploaded.push(await res.json());
    }
    return uploaded;
  }

  async function handleSelectFiles(event) {
    const files = Array.from(event.currentTarget.files || []);
    if (!files.length) return;
    try {
      const uploaded = await uploadFiles(files);
      setPendingUploads((prev) => [...prev, ...uploaded]);
      pushLogWithLimit(setLogs, "system", `已添加 ${uploaded.length} 个附件`);
    } catch (err) {
      const detail = String(err.message || err);
      setLastError(detail);
      pushLogWithLimit(setLogs, "error", `附件上传失败：${detail}`);
    } finally {
      event.currentTarget.value = "";
    }
  }

  function removeUpload(fileId) {
    setPendingUploads((prev) => prev.filter((item) => item.id !== fileId));
  }

  async function handleSend() {
    const messageText = draft.trim();
    if (!messageText || sending) return;

    setSending(true);
    setLastError("");

    let sid = sessionId;
    let pendingMessage = null;
    try {
      if (!sid) sid = await createSession();

      const userMessage = createMessage("user", messageText);
      pendingMessage = createMessage("assistant", "正在准备上下文...", { pending: true });
      setMessages((prev) => [...prev, userMessage, pendingMessage]);
      setDraft("");

      const body = {
        session_id: sid,
        message: messageText,
        attachment_ids: pendingUploads.map((item) => item.id),
        settings: {
          ...chatSettings,
          model: String(chatSettings.model || (health && health.default_model) || "").trim(),
        },
      };

      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok || !res.body) {
        throw new Error(`stream ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload = null;

      const replacePendingText = (text) => {
        setMessages((prev) =>
          prev.map((item) =>
            item.id === pendingMessage.id
              ? {
                  ...item,
                  text,
                }
              : item,
          ),
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
              const detail = String(payload.detail || payload.code || "处理中...");
              replacePendingText(detail);
              pushLogWithLimit(setLogs, "stage", detail);
            } else if (event === "trace") {
              const detail = String(payload.message || payload.raw || "");
              if (detail) pushLogWithLimit(setLogs, "trace", detail);
            } else if (event === "tool") {
              const name = String((payload.item || {}).name || "tool");
              pushLogWithLimit(setLogs, "tool", `工具调用：${name}`);
            } else if (event === "final") {
              finalPayload = payload.response || null;
            } else if (event === "error") {
              throw new Error(String(payload.detail || "stream error"));
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
      setInspectorOpen(true);
      pushLogWithLimit(
        setLogs,
        "response",
        `收到回复，工具 ${Array.isArray(finalPayload.tool_events) ? finalPayload.tool_events.length : 0} 次`,
      );
      await Promise.all([refreshSessions(), refreshHealth()]);
    } catch (err) {
      const detail = String(err.message || err);
      setLastError(detail);
      pushLogWithLimit(setLogs, "error", `发送失败：${detail}`);
      setMessages((prev) => {
        const next = prev.filter((item) => !(pendingMessage && item.id === pendingMessage.id));
        next.push(createMessage("system", `请求失败：${detail}`, { error: true }));
        return next;
      });
    } finally {
      setSending(false);
    }
  }

  function handleComposerKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  }

  const workspaceLabel = fileNameFromHealth(health);
  const activeInspector = lastResponse ? lastResponse.inspector || {} : {};
  const agentInfo = activeInspector.agent || (health && health.agent) || {};
  const toolEvents = Array.isArray(lastResponse && lastResponse.tool_events) ? lastResponse.tool_events : [];
  const tokenUsage = (lastResponse && lastResponse.token_usage) || {};

  return html`
    <div className=${`shell ${inspectorOpen ? "inspector-open" : "inspector-closed"}`} id="appShell">
      <aside className="thread-sidebar" id="threadSidebar">
        <div className="rail-head">
          <div>
            <div className="rail-kicker">线程</div>
            <div className="rail-title">${workspaceLabel}</div>
          </div>
          <div className="rail-actions">
            <button className="ghost-btn" type="button" onClick=${refreshSessions} disabled=${loadingSession || sending}>刷新</button>
            <button className="primary-btn" type="button" onClick=${handleNewSession} disabled=${loadingSession || sending}>新线程</button>
          </div>
        </div>

        <div className="thread-list">
          ${sessions.length
            ? sessions.map(
                (item) => html`
                  <button
                    key=${item.session_id}
                    className=${`thread-item ${item.session_id === sessionId ? "active" : ""}`}
                    type="button"
                    onClick=${() => loadSession(item.session_id)}
                    disabled=${loadingSession || sending}
                  >
                    <div className="thread-title">${item.title || "新线程"}</div>
                    <div className="thread-meta">${formatSessionTime(item.updated_at)} · ${item.turn_count || 0} 轮</div>
                    <div className="thread-preview">${item.preview || "暂无预览"}</div>
                  </button>
                `,
              )
            : html`<div className="thread-empty">还没有线程。</div>`}
        </div>

        <button className="settings-entry" type="button" onClick=${() => setSettingsOpen(true)}>设置</button>
      </aside>

      <main className="chat-pane" id="chatPane">
        <header className="chat-head">
          <div>
            <div className="chat-head-title">开始构建</div>
            <div className="chat-head-sub">${workspaceLabel}</div>
          </div>
          <button className="ghost-btn" type="button" onClick=${() => setInspectorOpen((prev) => !prev)}>
            ${inspectorOpen ? "隐藏检查栏" : "打开检查栏"}
          </button>
        </header>

        <section className="message-list" id="messageList" ref=${chatListRef}>
          ${messages.length
            ? messages.map(
                (item) => html`
                  <article key=${item.id} className=${`message-row role-${item.role} ${item.pending ? "pending" : ""} ${item.error ? "error" : ""}`}>
                    <div className="message-label">${roleLabel(item.role)}</div>
                    <div className="message-bubble">${item.text}</div>
                  </article>
                `,
              )
            : html`
                <div className="empty-state" id="emptyState">
                  <div className="empty-icon">✦</div>
                  <div className="empty-title">Vintage Programmer</div>
                  <div className="empty-copy">一个默认只有单主 agent 的本地工作台。线程在左边，聊天在中间，检查信息在右边。</div>
                </div>
              `}
        </section>

        <section className="composer-shell" id="composerShell">
          <div className="composer-toolbar">
            <button className="icon-btn" type="button" onClick=${() => fileInputRef.current && fileInputRef.current.click()} disabled=${sending}>+</button>
            <select
              value=${chatSettings.response_style}
              onChange=${(event) => setChatSettings((prev) => ({ ...prev, response_style: event.currentTarget.value }))}
              disabled=${sending}
            >
              <option value="short">简短</option>
              <option value="normal">正常</option>
              <option value="long">详细</option>
            </select>
            <input
              className="model-input"
              type="text"
              value=${chatSettings.model}
              onInput=${(event) => {
                setModelTouched(true);
                setChatSettings((prev) => ({ ...prev, model: event.currentTarget.value }));
              }}
              placeholder=${(health && health.default_model) || "模型名"}
              disabled=${sending}
            />
            <label className="tool-toggle">
              <input
                type="checkbox"
                checked=${chatSettings.enable_tools}
                onChange=${(event) => setChatSettings((prev) => ({ ...prev, enable_tools: event.currentTarget.checked }))}
                disabled=${sending}
              />
              工具
            </label>
          </div>

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

          <div className="composer-row">
            <textarea
              value=${draft}
              onInput=${(event) => setDraft(event.currentTarget.value)}
              onKeyDown=${handleComposerKeyDown}
              placeholder="输入消息。Enter 发送，Shift+Enter 换行。"
              disabled=${sending}
            ></textarea>
            <button className="send-btn" type="button" onClick=${handleSend} disabled=${sending || !draft.trim()}>
              ${sending ? "发送中" : "发送"}
            </button>
          </div>
          <input ref=${fileInputRef} type="file" multiple hidden onChange=${handleSelectFiles} />
        </section>
      </main>

      <aside className="inspector-pane" id="inspectorPane">
        <button className="inspector-tab" type="button" onClick=${() => setInspectorOpen((prev) => !prev)} id="inspectorToggle">
          ${inspectorOpen ? "›" : "‹"}
        </button>
        <div className="inspector-body">
          <section className="inspector-card">
            <div className="inspector-title">Agent</div>
            <div className="inspector-value">${agentInfo.title || "Vintage Programmer"}</div>
            <div className="inspector-meta">id=${agentInfo.agent_id || "vintage_programmer"}</div>
            <div className="inspector-meta">model=${(lastResponse && lastResponse.effective_model) || (health && health.default_model) || "-"}</div>
            <div className="inspector-meta">tools=${Array.isArray(agentInfo.allowed_tools) ? agentInfo.allowed_tools.length : 0}</div>
          </section>

          <section className="inspector-card">
            <div className="inspector-title">Session</div>
            <div className="inspector-meta">session=${sessionId || "(未创建)"}</div>
            <div className="inspector-meta">turns=${messages.length}</div>
            <div className="inspector-meta">attachments=${pendingUploads.length}</div>
          </section>

          <section className="inspector-card">
            <div className="inspector-title">Token</div>
            <div className="inspector-meta">input=${tokenUsage.input_tokens || 0}</div>
            <div className="inspector-meta">output=${tokenUsage.output_tokens || 0}</div>
            <div className="inspector-meta">total=${tokenUsage.total_tokens || 0}</div>
            <div className="inspector-meta">cost=${tokenUsage.estimated_cost_usd || 0}</div>
          </section>

          <section className="inspector-card">
            <div className="inspector-title">Tool Events</div>
            <div className="tool-event-list" id="toolEventList">
              ${toolEvents.length
                ? toolEvents.map(
                    (item, index) => html`
                      <div key=${`${item.name}-${index}`} className="tool-event">
                        <div className="tool-event-name">${item.name}</div>
                        <div className="tool-event-preview">${item.output_preview || "no preview"}</div>
                      </div>
                    `,
                  )
                : html`<div className="inspector-empty">这一轮没有工具调用。</div>`}
            </div>
          </section>

          <section className="inspector-card">
            <div className="inspector-title">Notes</div>
            <div className="note-list">
              ${Array.isArray(activeInspector.notes) && activeInspector.notes.length
                ? activeInspector.notes.map((item, index) => html`<div key=${index} className="note-item">${item}</div>`)
                : html`<div className="inspector-empty">暂无附加说明。</div>`}
            </div>
          </section>

          <section className="inspector-card">
            <div className="inspector-title">Recent Logs</div>
            <div className="note-list" id="logPanel">
              ${logs.length
                ? logs.map(
                    (item) => html`
                      <div key=${item.id} className=${`note-item tone-${item.type}`}>
                        <span>${item.text}</span>
                      </div>
                    `,
                  )
                : html`<div className="inspector-empty">暂无日志。</div>`}
            </div>
          </section>

          ${lastError
            ? html`
                <section className="inspector-card error-card">
                  <div className="inspector-title">Last Error</div>
                  <div className="error-text">${lastError}</div>
                </section>
              `
            : null}
        </div>
      </aside>

      ${settingsOpen
        ? html`
            <div className="modal-backdrop" onClick=${() => setSettingsOpen(false)}>
              <div className="settings-modal" id="settingsModal" onClick=${(event) => event.stopPropagation()}>
                <div className="modal-head">
                  <div>
                    <div className="rail-kicker">设置</div>
                    <div className="rail-title">运行参数</div>
                  </div>
                  <button className="ghost-btn" type="button" onClick=${() => setSettingsOpen(false)}>关闭</button>
                </div>
                <label className="settings-field">
                  <span>模型</span>
                  <input
                    type="text"
                    value=${chatSettings.model}
                    onInput=${(event) => {
                      setModelTouched(true);
                      setChatSettings((prev) => ({ ...prev, model: event.currentTarget.value }));
                    }}
                  />
                </label>
                <label className="settings-field">
                  <span>最大输出 Token</span>
                  <input
                    type="number"
                    value=${chatSettings.max_output_tokens}
                    onInput=${(event) =>
                      setChatSettings((prev) => ({ ...prev, max_output_tokens: Number(event.currentTarget.value || 0) || 128000 }))
                    }
                  />
                </label>
                <label className="settings-field">
                  <span>上下文轮数</span>
                  <input
                    type="number"
                    value=${chatSettings.max_context_turns}
                    onInput=${(event) =>
                      setChatSettings((prev) => ({ ...prev, max_context_turns: Number(event.currentTarget.value || 0) || 2000 }))
                    }
                  />
                </label>
                <div className="settings-summary">
                  workspace=${(health && health.workspace_root) || "-"}<br />
                  auth=${(health && health.auth_mode) || "-"} · provider=${(health && health.llm_provider) || "-"}
                </div>
              </div>
            </div>
          `
        : null}
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
