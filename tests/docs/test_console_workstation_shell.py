from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "app" / "static" / "index.html"
APP_JS = REPO_ROOT / "app" / "static" / "app.js"


def test_workstation_shell_mounts_exist() -> None:
    html = INDEX_HTML.read_text()
    script = APP_JS.read_text()

    assert 'data-app="vintage-programmer"' in html
    required_tokens = [
        'id="appShell"',
        'id="threadSidebar"',
        'id="chatPane"',
        'id="inspectorPane"',
        'id="messageList"',
        'id="composerShell"',
        'id="settingsModal"',
    ]
    for token in required_tokens:
        assert token in script, token


def test_workstation_shell_behaviors_are_wired() -> None:
    script = APP_JS.read_text()
    required_tokens = [
        "SESSION_STORAGE_KEY",
        "parseSseChunk(",
        'fetch("/api/chat/stream"',
        'fetch("/api/upload"',
        'fetch("/api/sessions?limit=80")',
        "setInspectorOpen((prev) => !prev)",
        "handleSelectFiles",
    ]
    for token in required_tokens:
        assert token in script, token
    assert "/api/agent-plugins" not in script
