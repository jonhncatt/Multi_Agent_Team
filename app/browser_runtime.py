from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any, Awaitable, Callable


@dataclass
class _BrowserSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    touched_at: float


def _merge_nested_dict(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, dict):
                existing = {}
            target[key] = _merge_nested_dict(existing, value)
        else:
            target[key] = value
    return target


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


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
        disable_password_manager: bool = True,
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
        self._disable_password_manager = bool(disable_password_manager)
        self._sessions: dict[str, _BrowserSession] = {}
        self._worker_lock = threading.Lock()
        self._worker_ready = threading.Event()
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_thread: threading.Thread | None = None
        self._async_lock: asyncio.Lock | None = None

    def _import_playwright(self) -> tuple[Any, Any]:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        return async_playwright, PlaywrightTimeoutError

    def _ensure_worker(self) -> asyncio.AbstractEventLoop:
        with self._worker_lock:
            if self._worker_thread is not None and self._worker_thread.is_alive() and self._worker_loop is not None:
                return self._worker_loop
            self._worker_ready.clear()
            worker = threading.Thread(
                target=self._worker_main,
                name="vp-browser-tool-worker",
                daemon=True,
            )
            self._worker_thread = worker
            worker.start()

        if not self._worker_ready.wait(timeout=5):
            raise RuntimeError("Browser worker did not start within 5 seconds.")
        loop = self._worker_loop
        if loop is None:
            raise RuntimeError("Browser worker loop is unavailable.")
        return loop

    def _worker_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_loop = loop
        self._worker_ready.set()
        loop.run_forever()

    async def _run_locked(self, func: Callable[[], Awaitable[Any]]) -> Any:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            return await func()

    def _run_async(self, func: Callable[[], Awaitable[Any]]) -> Any:
        loop = self._ensure_worker()
        future = asyncio.run_coroutine_threadsafe(self._run_locked(func), loop)
        return future.result()

    async def _cleanup_stale(self, *, ttl_sec: int = 1800) -> None:
        now = time.time()
        stale = [
            session_id
            for session_id, item in self._sessions.items()
            if (now - float(item.touched_at or 0)) > ttl_sec
        ]
        for session_id in stale:
            await self._close_session(session_id)

    async def _close_session(self, session_id: str) -> None:
        item = self._sessions.pop(session_id, None)
        if item is None:
            return
        for resource in (item.page, item.context, item.browser, item.playwright):
            if resource is None:
                continue
            for method_name in ("close", "stop"):
                method = getattr(resource, method_name, None)
                if not callable(method):
                    continue
                try:
                    await _maybe_await(method())
                    break
                except Exception:
                    continue

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

    def _prepare_chrome_profile(self, user_data_dir: Path) -> None:
        if not self._disable_password_manager:
            return
        preferences_path = user_data_dir / "Default" / "Preferences"
        preferences_path.parent.mkdir(parents=True, exist_ok=True)
        preferences: dict[str, Any] = {}
        if preferences_path.exists():
            try:
                loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    preferences = loaded
            except Exception:
                preferences = {}
        _merge_nested_dict(
            preferences,
            {
                "credentials_enable_service": False,
                "profile": {
                    "password_manager_enabled": False,
                    "password_manager_leak_detection": False,
                },
            },
        )
        preferences_path.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _launch_playwright_context(self, playwright: Any) -> tuple[Any, Any, Any]:
        context_options = self._context_options()
        if self._mode == "chrome_profile":
            user_data_dir = self._user_data_dir or (self._artifacts_dir / "chrome-profile")
            user_data_dir.mkdir(parents=True, exist_ok=True)
            self._prepare_chrome_profile(user_data_dir)
            launch_options: dict[str, Any] = {
                **context_options,
                "headless": self._headless,
                "chromium_sandbox": self._chromium_sandbox,
            }
            if self._executable_path:
                launch_options["executable_path"] = self._executable_path
            elif self._channel:
                launch_options["channel"] = self._channel
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                **launch_options,
            )
            pages = list(getattr(context, "pages", []) or [])
            page = pages[0] if pages else await context.new_page()
            return getattr(context, "browser", None), context, page

        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        return browser, context, page

    async def _ensure_session(self, session_id: str) -> _BrowserSession:
        sid = str(session_id or "__anon__").strip() or "__anon__"
        await self._cleanup_stale()
        existing = self._sessions.get(sid)
        if existing is not None:
            if self._session_alive(existing):
                existing.touched_at = time.time()
                return existing
            await self._close_session(sid)

        async_playwright, _ = self._import_playwright()
        playwright = await async_playwright().start()
        try:
            browser, context, page = await self._launch_playwright_context(playwright)
        except Exception:
            try:
                await _maybe_await(playwright.stop())
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
        return self._run_async(lambda: self._open_impl(session_id=session_id, url=url, timeout_ms=timeout_ms))

    async def _open_impl(self, *, session_id: str, url: str, timeout_ms: int = 20000) -> dict[str, Any]:
        _, PlaywrightTimeoutError = self._import_playwright()
        session = await self._ensure_session(session_id)
        try:
            await session.page.goto(str(url), wait_until="domcontentloaded", timeout=max(1000, int(timeout_ms)))
            session.touched_at = time.time()
            return await self._snapshot_impl(session_id=session_id, max_chars=6000)
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "error": f"browser_open timed out: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"browser_open failed: {exc}"}

    def click(self, *, session_id: str, selector: str, timeout_ms: int = 12000) -> dict[str, Any]:
        return self._run_async(lambda: self._click_impl(session_id=session_id, selector=selector, timeout_ms=timeout_ms))

    async def _click_impl(self, *, session_id: str, selector: str, timeout_ms: int = 12000) -> dict[str, Any]:
        _, PlaywrightTimeoutError = self._import_playwright()
        session = await self._ensure_session(session_id)
        try:
            await session.page.locator(str(selector)).first.click(timeout=max(1000, int(timeout_ms)))
            session.touched_at = time.time()
            return await self._snapshot_impl(session_id=session_id, max_chars=4000)
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
        return self._run_async(
            lambda: self._type_impl(
                session_id=session_id,
                selector=selector,
                text=text,
                submit=submit,
                clear=clear,
                timeout_ms=timeout_ms,
            )
        )

    async def _type_impl(
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
        session = await self._ensure_session(session_id)
        try:
            locator = session.page.locator(str(selector)).first
            if clear:
                await locator.fill(str(text), timeout=max(1000, int(timeout_ms)))
            else:
                await locator.type(str(text), timeout=max(1000, int(timeout_ms)))
            if submit:
                await locator.press("Enter", timeout=max(1000, int(timeout_ms)))
            session.touched_at = time.time()
            return await self._snapshot_impl(session_id=session_id, max_chars=4000)
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
        return self._run_async(
            lambda: self._wait_impl(
                session_id=session_id,
                selector=selector,
                timeout_ms=timeout_ms,
                state=state,
            )
        )

    async def _wait_impl(
        self,
        *,
        session_id: str,
        selector: str = "",
        timeout_ms: int = 5000,
        state: str = "visible",
    ) -> dict[str, Any]:
        _, PlaywrightTimeoutError = self._import_playwright()
        session = await self._ensure_session(session_id)
        try:
            timeout_value = max(250, int(timeout_ms))
            if str(selector or "").strip():
                await session.page.locator(str(selector)).first.wait_for(
                    timeout=timeout_value,
                    state=str(state or "visible"),
                )
            else:
                await session.page.wait_for_timeout(timeout_value)
            session.touched_at = time.time()
            return await self._snapshot_impl(session_id=session_id, max_chars=4000)
        except PlaywrightTimeoutError as exc:
            return {"ok": False, "error": f"browser_wait timed out: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"browser_wait failed: {exc}"}

    def snapshot(self, *, session_id: str, max_chars: int = 12000) -> dict[str, Any]:
        return self._run_async(lambda: self._snapshot_impl(session_id=session_id, max_chars=max_chars))

    async def _snapshot_impl(self, *, session_id: str, max_chars: int = 12000) -> dict[str, Any]:
        session = await self._ensure_session(session_id)
        try:
            page = session.page
            title = await page.title()
            url = page.url
            body_text = await page.locator("body").inner_text(timeout=4000)
            links = await page.locator("a").evaluate_all(
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
        return self._run_async(
            lambda: self._screenshot_impl(
                session_id=session_id,
                target_path=target_path,
                full_page=full_page,
            )
        )

    async def _screenshot_impl(
        self,
        *,
        session_id: str,
        target_path: Path,
        full_page: bool = True,
    ) -> dict[str, Any]:
        session = await self._ensure_session(session_id)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            await session.page.screenshot(path=str(target_path), full_page=bool(full_page))
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
