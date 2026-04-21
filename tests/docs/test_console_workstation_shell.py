from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "app" / "static" / "index.html"
APP_JS = REPO_ROOT / "app" / "static" / "app.js"


def test_workstation_shell_mounts_exist() -> None:
    html = INDEX_HTML.read_text()
    script = APP_JS.read_text()

    assert 'data-app="vintage-programmer"' in html
    assert "/static/vendor/marked.umd.js" in html
    assert "/static/vendor/purify.min.js" in html
    required_tokens = [
        'id="appShell"',
        'id="threadSidebar"',
        'id="projectSection"',
        'id="chatPane"',
        'id="messageList"',
        'id="emptyPromptLine"',
        'id="composerShell"',
        'id="composerError"',
        'id="providerSelect"',
        'id="modelPresetSelect"',
        'id="modelInput"',
        'id="projectModal"',
        'id="workbenchDrawer"',
        'id="statusBar"',
        'id="settingsPanel"',
    ]
    for token in required_tokens:
        assert token in script, token


def test_workstation_shell_behaviors_are_wired() -> None:
    script = APP_JS.read_text()
    required_tokens = [
        "SESSION_STORAGE_KEY",
        "PROJECT_STORAGE_KEY",
        "PROVIDER_STORAGE_KEY",
        "MODEL_STORAGE_KEY",
        "CUSTOM_MODEL_VALUE",
        "parseSseChunk(",
        "normalizeUiError(",
        "renderMessageHtml(",
        "resolvePresetModelValue(",
        "updateProviderSelection(",
        'fetch("/api/chat/stream"',
        '"/api/upload"',
        'fetchJson("/api/projects")',
        'fetchJson(`/api/sessions?limit=80${suffix}`)',
        'fetchJson("/api/workbench/tools")',
        'fetchJson("/api/workbench/skills")',
        'fetchJson("/api/workbench/specs")',
        "selectProject(",
        "setDrawerView(",
        "handleSelectFiles",
        "processSelectedFiles(",
        "handleComposerDrop",
        "handleComposerPaste",
        "dragEventHasFiles(",
        "clipboardEventFiles(",
        "ensureNamedUploadFile(",
        "composerDragActive",
        '"copy"',
        "onPaste=${handleComposerPaste}",
        "status-alert",
        "dangerouslySetInnerHTML",
        "DOMPurifyRuntime.sanitize",
        "modelStorageKeyForProvider(",
        "health && health.provider_options",
    ]
    for token in required_tokens:
        assert token in script, token
    assert 'createMessage("system", `请求失败：${detail}`' not in script
    assert "/api/agent-plugins" not in script
