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
    def __init__(
        self,
        *,
        artifacts_dir: Path,
        mode: str = "playwright",
        channel: str = "chrome",
        headless: bool = True,
        user_data_dir: Path | None = None,
        executable_path: str = "",
        proxy_server: str = "",
        ignore_https_errors: bool = False,
        chromium_sandbox: bool = False,
    ) -> None:
        self._artifacts_dir = artifacts_dir.resolve()
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._mode = str(mode or "playwright").strip().lower()
        if self._mode not in {"playwright", "chrome_profile"}:
            self._mode = "playwright"
        self._channel = str(channel or "chrome").strip()
        self._headless = bool(headless)
        self._user_data_dir = user_data_dir.expanduser().resolve() if user_data_dir is not None else None
        self._executable_path = str(executable_path or "").strip()
        self._proxy_server = str(proxy_server or "").strip()
        self._ignore_https_errors = bool(ignore_https_errors)
        self._chromium_sandbox = bool(chromium_sandbox)
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

    @staticmethod
    def _session_alive(item: _BrowserSession) -> bool:
        try:
            page = item.page
            is_closed = getattr(page, "is_closed", None)
            if callable(is_closed) and bool(is_closed()):
                return False
        except Exception:
            return False

        browser = item.browser
        if browser is not None:
            try:
                is_connected = getattr(browser, "is_connected", None)
                if callable(is_connected) and not bool(is_connected()):
                    return False
            except Exception:
                return False

        return True

    def _context_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "viewport": {"width": 1440, "height": 960},
            "locale": "zh-CN",
            "ignore_https_errors": self._ignore_https_errors,
        }
        if self._proxy_server:
            options["proxy"] = {"server": self._proxy_server}
        return options

    def _launch_playwright_context(self, playwright: Any) -> tuple[Any, Any, Any]:
        context_options = self._context_options()
        if self._mode == "chrome_profile":
            user_data_dir = self._user_data_dir or (self._artifacts_dir / "chrome-profile")
            user_data_dir.mkdir(parents=True, exist_ok=True)
            launch_options: dict[str, Any] = {
                **context_options,
                "headless": self._headless,
                "chromium_sandbox": self._chromium_sandbox,
            }
            if self._executable_path:
                launch_options["executable_path"] = self._executable_path
            elif self._channel:
                launch_options["channel"] = self._channel
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                **launch_options,
            )
            pages = list(getattr(context, "pages", []) or [])
            page = pages[0] if pages else context.new_page()
            return getattr(context, "browser", None), context, page

        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(**context_options)
        page = context.new_page()
        return browser, context, page

    def _ensure_session(self, session_id: str) -> _BrowserSession:
        sid = str(session_id or "__anon__").strip() or "__anon__"
        with self._lock:
            self._cleanup_stale_locked()
            existing = self._sessions.get(sid)
            if existing is not None:
                if self._session_alive(existing):
                    existing.touched_at = time.time()
                    return existing
                self._close_locked(sid)

            sync_playwright, _ = self._import_playwright()
            playwright = sync_playwright().start()
            try:
                browser, context, page = self._launch_playwright_context(playwright)
            except Exception:
                try:
                    playwright.stop()
                except Exception:
                    pass
                raise
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
