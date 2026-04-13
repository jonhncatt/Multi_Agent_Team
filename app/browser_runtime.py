from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any


@dataclass
class _BrowserSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    touched_at: float


class BrowserToolManager:
    def __init__(self, *, artifacts_dir: Path) -> None:
        self._artifacts_dir = artifacts_dir.resolve()
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sessions: dict[str, _BrowserSession] = {}

    def _import_playwright(self) -> tuple[Any, Any]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        return sync_playwright, PlaywrightTimeoutError

    def _cleanup_stale_locked(self, *, ttl_sec: int = 1800) -> None:
        now = time.time()
        stale = [
            session_id
            for session_id, item in self._sessions.items()
            if (now - float(item.touched_at or 0)) > ttl_sec
        ]
        for session_id in stale:
            self._close_locked(session_id)

    def _close_locked(self, session_id: str) -> None:
        item = self._sessions.pop(session_id, None)
        if item is None:
            return
        for resource in (item.page, item.context, item.browser, item.playwright):
            try:
                resource.close()
            except Exception:
                try:
                    resource.stop()
                except Exception:
                    pass

    def _ensure_session(self, session_id: str) -> _BrowserSession:
        sid = str(session_id or "__anon__").strip() or "__anon__"
        with self._lock:
            self._cleanup_stale_locked()
            existing = self._sessions.get(sid)
            if existing is not None:
                existing.touched_at = time.time()
                return existing

            sync_playwright, _ = self._import_playwright()
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 960},
                locale="zh-CN",
            )
            page = context.new_page()
            created = _BrowserSession(
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
                touched_at=time.time(),
            )
            self._sessions[sid] = created
            return created

    def open(self, *, session_id: str, url: str, timeout_ms: int = 20000) -> dict[str, Any]:
        sync_playwright, PlaywrightTimeoutError = self._import_playwright()
        _ = sync_playwright
        session = self._ensure_session(session_id)
        try:
            session.page.goto(str(url), wait_until="domcontentloaded", timeout=max(1000, int(timeout_ms)))
            session.touched_at = time.time()
            return self.snapshot(session_id=session_id, max_chars=6000)
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "error": f"browser_open timed out: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"browser_open failed: {exc}"}

    def click(self, *, session_id: str, selector: str, timeout_ms: int = 12000) -> dict[str, Any]:
        _, PlaywrightTimeoutError = self._import_playwright()
        session = self._ensure_session(session_id)
        try:
            session.page.locator(str(selector)).first.click(timeout=max(1000, int(timeout_ms)))
            session.touched_at = time.time()
            return self.snapshot(session_id=session_id, max_chars=4000)
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "error": f"browser_click timed out: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"browser_click failed: {exc}"}

    def type(
        self,
        *,
        session_id: str,
        selector: str,
        text: str,
        submit: bool = False,
        clear: bool = True,
        timeout_ms: int = 12000,
    ) -> dict[str, Any]:
        _, PlaywrightTimeoutError = self._import_playwright()
        session = self._ensure_session(session_id)
        try:
            locator = session.page.locator(str(selector)).first
            if clear:
                locator.fill(str(text), timeout=max(1000, int(timeout_ms)))
            else:
                locator.type(str(text), timeout=max(1000, int(timeout_ms)))
            if submit:
                locator.press("Enter", timeout=max(1000, int(timeout_ms)))
            session.touched_at = time.time()
            return self.snapshot(session_id=session_id, max_chars=4000)
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "error": f"browser_type timed out: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"browser_type failed: {exc}"}

    def wait(
        self,
        *,
        session_id: str,
        selector: str = "",
        timeout_ms: int = 5000,
        state: str = "visible",
    ) -> dict[str, Any]:
        _, PlaywrightTimeoutError = self._import_playwright()
        session = self._ensure_session(session_id)
        try:
            timeout_value = max(250, int(timeout_ms))
            if str(selector or "").strip():
                session.page.locator(str(selector)).first.wait_for(
                    timeout=timeout_value,
                    state=str(state or "visible"),
                )
            else:
                session.page.wait_for_timeout(timeout_value)
            session.touched_at = time.time()
            return self.snapshot(session_id=session_id, max_chars=4000)
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "error": f"browser_wait timed out: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"browser_wait failed: {exc}"}

    def snapshot(self, *, session_id: str, max_chars: int = 12000) -> dict[str, Any]:
        session = self._ensure_session(session_id)
        try:
            page = session.page
            title = page.title()
            url = page.url
            body_text = page.locator("body").inner_text(timeout=4000)
            links = page.locator("a").evaluate_all(
                """els => els.slice(0, 12).map(el => ({
                    text: (el.innerText || "").trim(),
                    href: el.href || ""
                }))"""
            )
            text = str(body_text or "").strip()
            if len(text) > max(400, int(max_chars)):
                text = text[: max(400, int(max_chars))].rstrip() + "…"
            session.touched_at = time.time()
            return {
                "ok": True,
                "url": url,
                "title": title,
                "text": text,
                "links": links if isinstance(links, list) else [],
                "summary": f"{title or url} · {len(text)} chars",
            }
        except Exception as exc:
            return {"ok": False, "error": f"browser_snapshot failed: {exc}"}

    def screenshot(
        self,
        *,
        session_id: str,
        target_path: Path,
        full_page: bool = True,
    ) -> dict[str, Any]:
        session = self._ensure_session(session_id)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            session.page.screenshot(path=str(target_path), full_page=bool(full_page))
            session.touched_at = time.time()
            return {
                "ok": True,
                "path": str(target_path),
                "url": str(session.page.url or ""),
                "summary": f"screenshot saved to {target_path.name}",
            }
        except Exception as exc:
            return {"ok": False, "error": f"browser_screenshot failed: {exc}"}

    def default_screenshot_path(self, *, session_id: str) -> Path:
        safe_session = str(session_id or "__anon__").strip().replace("/", "_")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        return self._artifacts_dir / safe_session / f"{stamp}.png"
