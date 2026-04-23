from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.local_tools import LocalToolExecutor


class ChatProductRuntime:
    """
    Thin runtime surface for the current chat product.

    This intentionally exposes only the live capabilities that the chat UI and
    product APIs need.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._executor_cache: dict[str, LocalToolExecutor] = {}
        self._runtime_meta_cache: tuple[float, dict[str, Any]] = (0.0, {})

    @property
    def config(self) -> AppConfig:
        return self._config

    def _executor_cache_key(self) -> str:
        return "::".join(
            [
                str(Path(self._config.workspace_root).resolve()),
                str(Path(self._config.projects_registry_path).resolve()),
                str(Path(self._config.sessions_dir).resolve()),
                str(Path(self._config.uploads_dir).resolve()),
            ]
        )

    @property
    def tool_executor(self) -> LocalToolExecutor:
        key = self._executor_cache_key()
        with self._lock:
            cached = self._executor_cache.get(key)
            if cached is not None:
                return cached
            executor = LocalToolExecutor(self._config)
            self._executor_cache = {key: executor}
            return executor

    def docker_status(self) -> tuple[bool, str]:
        return self.tool_executor.docker_status()

    def ocr_status(self) -> dict[str, Any]:
        return dict(self.tool_executor.ocr_status() or {})

    def runtime_meta(self) -> dict[str, Any]:
        now = time.monotonic()
        cached_at, cached = self._runtime_meta_cache
        if cached and now - cached_at < 10.0:
            return dict(cached)
        docker_ok, docker_msg = self.docker_status()
        payload = {
            "docker_available": bool(docker_ok),
            "docker_message": str(docker_msg or ""),
            "ocr_status": self.ocr_status(),
        }
        self._runtime_meta_cache = (now, dict(payload))
        return payload
