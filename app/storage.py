from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile


_SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    return _SAFE_NAME_PATTERN.sub("_", name).strip("._") or "file"


class SessionStore:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _default_agent_state(self) -> dict[str, Any]:
        return {
            "agent_id": "vintage_programmer",
            "goal": "",
            "current_goal": "",
            "phase": "idle",
            "last_run_id": "",
            "last_model": "",
            "current_task_focus": {},
            "task_checkpoint": {},
            "thread_memory": {},
            "recent_tasks": [],
            "artifact_memory_preview": [],
            "tool_hits": [],
            "tool_count": 0,
            "tool_names": [],
            "evidence_status": "not_needed",
            "enabled_skill_ids": [],
            "updated_at": now_iso(),
        }

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _normalize_session(
        self,
        session: dict[str, Any],
        *,
        default_project: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        changed = False
        payload = dict(session or {})

        if not str(payload.get("id") or "").strip():
            payload["id"] = str(uuid.uuid4())
            changed = True
        if not str(payload.get("created_at") or "").strip():
            payload["created_at"] = now_iso()
            changed = True
        if not str(payload.get("updated_at") or "").strip():
            payload["updated_at"] = str(payload.get("created_at") or now_iso())
            changed = True
        if not isinstance(payload.get("turns"), list):
            payload["turns"] = []
            changed = True
        if not isinstance(payload.get("active_attachment_ids"), list):
            payload["active_attachment_ids"] = []
            changed = True
        if not isinstance(payload.get("route_state"), dict):
            payload["route_state"] = {}
            changed = True
        if not isinstance(payload.get("attachment_route_states"), dict):
            payload["attachment_route_states"] = {}
            changed = True
        if not isinstance(payload.get("current_task_focus"), dict):
            payload["current_task_focus"] = {}
            changed = True
        if not isinstance(payload.get("thread_memory"), dict):
            payload["thread_memory"] = {}
            changed = True
        if not isinstance(payload.get("artifact_memory"), list):
            payload["artifact_memory"] = []
            changed = True
        agent_state = payload.get("agent_state")
        if not isinstance(agent_state, dict):
            payload["agent_state"] = self._default_agent_state()
            changed = True
        else:
            merged_state = {**self._default_agent_state(), **agent_state}
            if merged_state != agent_state:
                payload["agent_state"] = merged_state
                changed = True

        if default_project:
            default_project_id = str(default_project.get("project_id") or "").strip()
            default_project_title = str(default_project.get("title") or "").strip()
            default_project_root = str(default_project.get("root_path") or "").strip()
            default_git_branch = str(default_project.get("git_branch") or "").strip()
            if not str(payload.get("project_id") or "").strip():
                payload["project_id"] = default_project_id
                changed = True
            if not str(payload.get("project_title") or "").strip():
                payload["project_title"] = default_project_title
                changed = True
            if not str(payload.get("project_root") or "").strip():
                payload["project_root"] = default_project_root
                changed = True
            if not str(payload.get("git_branch") or "").strip():
                payload["git_branch"] = default_git_branch
                changed = True
        if not str(payload.get("cwd") or "").strip():
            payload["cwd"] = str(payload.get("project_root") or "")
            changed = True

        from app import session_context as session_context_impl

        if session_context_impl.sync_session_memory_state(payload):
            changed = True

        return payload, changed

    def create(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = str(project.get("project_id") or "").strip()
        project_title = str(project.get("title") or "").strip()
        project_root = str(project.get("root_path") or "").strip()
        git_branch = str(project.get("git_branch") or "").strip()
        session = {
            "id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "title": "",
            "summary": "",
            "project_id": project_id,
            "project_title": project_title,
            "project_root": project_root,
            "git_branch": git_branch,
            "cwd": project_root,
            "turns": [],
            "active_attachment_ids": [],
            "attachment_context_cleared": False,
            "agent_state": self._default_agent_state(),
            "route_state": {},
            "attachment_route_states": {},
            "current_task_focus": {},
            "thread_memory": {},
            "artifact_memory": [],
        }
        self.save(session)
        return session

    def load(self, session_id: str, *, default_project: dict[str, Any] | None = None) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        with self._lock:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        normalized, changed = self._normalize_session(loaded, default_project=default_project)
        if changed:
            self.save(normalized, touch=False)
        return normalized

    def load_or_create(
        self,
        session_id: str | None,
        *,
        project: dict[str, Any] | None = None,
        default_project: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not session_id:
            if not project and not default_project:
                raise ValueError("project is required to create a session")
            return self.create(project or default_project or {})
        loaded = self.load(session_id, default_project=default_project)
        if not loaded:
            if not project and not default_project:
                raise ValueError("project is required to create a session")
            return self.create(project or default_project or {})
        return loaded

    def save(self, session: dict[str, Any], *, touch: bool = True) -> None:
        if touch:
            session["updated_at"] = now_iso()
        path = self._path(session["id"])
        with self._lock:
            path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_turn(
        self,
        session: dict[str, Any],
        role: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        answer_bundle: dict[str, Any] | None = None,
    ) -> None:
        session.setdefault("turns", []).append(
            {
                "id": str(uuid.uuid4()),
                "role": role,
                "text": text,
                "attachments": attachments or [],
                "answer_bundle": answer_bundle or {},
                "created_at": now_iso(),
            }
        )

    def list_sessions(
        self,
        limit: int = 50,
        *,
        project_id: str | None = None,
        default_project: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        max_items = max(1, min(500, int(limit)))
        wanted_project_id = str(project_id or "").strip()
        files = sorted(
            self.sessions_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        out: list[dict[str, Any]] = []
        for path in files:
            if len(out) >= max_items:
                break
            try:
                with self._lock:
                    session = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            session, changed = self._normalize_session(session, default_project=default_project)
            if changed:
                self.save(session, touch=False)

            sid = str(session.get("id") or path.stem)
            turns = session.get("turns", [])
            if not isinstance(turns, list):
                turns = []
            if wanted_project_id and str(session.get("project_id") or "").strip() != wanted_project_id:
                continue

            custom_title = str(session.get("title") or "").strip()
            title = custom_title
            if not title:
                title = "新会话"
                for turn in turns:
                    if isinstance(turn, dict) and str(turn.get("role") or "") == "user":
                        text = str(turn.get("text") or "").strip()
                        if text:
                            title = text.replace("\n", " ")[:48]
                        break

            preview = ""
            if turns:
                last = turns[-1]
                if isinstance(last, dict):
                    preview = str(last.get("text") or "").replace("\n", " ").strip()[:80]

            out.append(
                {
                    "session_id": sid,
                    "title": title,
                    "has_custom_title": bool(custom_title),
                    "preview": preview,
                    "turn_count": len(turns),
                    "project_id": str(session.get("project_id") or ""),
                    "project_title": str(session.get("project_title") or ""),
                    "project_root": str(session.get("project_root") or ""),
                    "git_branch": str(session.get("git_branch") or ""),
                    "cwd": str(session.get("cwd") or ""),
                    "updated_at": str(session.get("updated_at") or ""),
                    "created_at": str(session.get("created_at") or ""),
                }
            )

        return out

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        try:
            with self._lock:
                path.unlink(missing_ok=False)
            return True
        except Exception:
            return False

    def migrate_missing_project(self, default_project: dict[str, Any]) -> int:
        migrated = 0
        for path in sorted(self.sessions_dir.glob("*.json")):
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            normalized, changed = self._normalize_session(payload, default_project=default_project)
            if not changed:
                continue
            self.save(normalized, touch=False)
            migrated += 1
        return migrated


def _project_id_for_root(root_path: Path) -> str:
    digest = uuid.uuid5(uuid.NAMESPACE_URL, str(root_path.resolve()))
    return f"project_{str(digest).replace('-', '')[:16]}"


def _git_output(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _git_metadata(root: Path) -> dict[str, Any]:
    git_root = _git_output(root, "rev-parse", "--show-toplevel")
    branch = _git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
    git_dir = _git_output(root, "rev-parse", "--path-format=absolute", "--git-dir")
    common_dir = _git_output(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return {
        "git_root": git_root,
        "git_branch": branch,
        "is_worktree": bool(git_root and git_dir and common_dir and Path(git_dir).resolve() != Path(common_dir).resolve()),
    }


class ProjectStore:
    def __init__(self, registry_path: Path, *, default_root: Path) -> None:
        self.registry_path = registry_path
        self.default_root = default_root.resolve()
        self._lock = threading.Lock()
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write({"projects": {}, "default_project_id": "", "updated_at": now_iso()})

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except Exception:
                return {"projects": {}, "default_project_id": "", "updated_at": now_iso()}

    def _write(self, payload: dict[str, Any]) -> None:
        body = dict(payload or {})
        body["updated_at"] = now_iso()
        with self._lock:
            self.registry_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        root_path = Path(str(payload.get("root_path") or self.default_root)).expanduser().resolve()
        git_meta = _git_metadata(root_path)
        return {
            "project_id": str(payload.get("project_id") or _project_id_for_root(root_path)),
            "title": str(payload.get("title") or root_path.name or str(root_path)).strip() or (root_path.name or str(root_path)),
            "root_path": str(root_path),
            "created_at": str(payload.get("created_at") or now_iso()),
            "updated_at": str(payload.get("updated_at") or now_iso()),
            "last_opened_at": str(payload.get("last_opened_at") or payload.get("updated_at") or now_iso()),
            "pinned": bool(payload.get("pinned")),
            "is_default": bool(payload.get("is_default")),
            "git_root": str(payload.get("git_root") or git_meta.get("git_root") or ""),
            "git_branch": str(payload.get("git_branch") or git_meta.get("git_branch") or ""),
            "is_worktree": bool(payload.get("is_worktree")) or bool(git_meta.get("is_worktree")),
        }

    def ensure_default_project(self) -> dict[str, Any]:
        data = self._read()
        projects = data.setdefault("projects", {})
        default_id = str(data.get("default_project_id") or "").strip()
        expected = self._normalize_record(
            {
                "project_id": default_id or _project_id_for_root(self.default_root),
                "title": self.default_root.name or str(self.default_root),
                "root_path": str(self.default_root),
                "pinned": True,
                "is_default": True,
            }
        )
        record = projects.get(expected["project_id"]) if expected["project_id"] else None
        normalized = self._normalize_record({**expected, **(record or {})})
        normalized["pinned"] = True
        normalized["is_default"] = True
        projects[normalized["project_id"]] = normalized
        data["default_project_id"] = normalized["project_id"]
        self._write(data)
        return normalized

    def _sorted(self, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            projects,
            key=lambda item: (
                1 if bool(item.get("is_default")) else 0,
                1 if bool(item.get("pinned")) else 0,
                str(item.get("last_opened_at") or ""),
                str(item.get("title") or ""),
            ),
            reverse=True,
        )

    def list_projects(self) -> list[dict[str, Any]]:
        default_project = self.ensure_default_project()
        data = self._read()
        projects = [self._normalize_record(item) for item in (data.get("projects") or {}).values() if isinstance(item, dict)]
        by_id = {item["project_id"]: item for item in projects}
        by_id.setdefault(default_project["project_id"], default_project)
        return self._sorted(list(by_id.values()))

    def all_project_roots(self) -> list[Path]:
        return [Path(item["root_path"]).resolve() for item in self.list_projects()]

    def get(self, project_id: str | None) -> dict[str, Any] | None:
        wanted = str(project_id or "").strip()
        if not wanted:
            return self.ensure_default_project()
        for item in self.list_projects():
            if item["project_id"] == wanted:
                return item
        return None

    def create(self, *, root_path: str, title: str = "") -> dict[str, Any]:
        root = Path(str(root_path or "").strip()).expanduser()
        if not root.is_absolute():
            raise ValueError("root_path must be an absolute local path")
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(f"Path not found: {root}")
        if not root.is_dir():
            raise ValueError(f"Path is not a directory: {root}")
        data = self._read()
        projects = data.setdefault("projects", {})
        for item in projects.values():
            existing_root = Path(str((item or {}).get("root_path") or "")).expanduser()
            if existing_root and existing_root.resolve() == root:
                raise FileExistsError(f"Project already exists for path: {root}")
        payload = self._normalize_record(
            {
                "project_id": _project_id_for_root(root),
                "title": title.strip() or root.name or str(root),
                "root_path": str(root),
                "pinned": False,
                "is_default": False,
            }
        )
        projects[payload["project_id"]] = payload
        self._write(data)
        return payload

    def update(self, project_id: str, *, title: str | None = None, pinned: bool | None = None) -> dict[str, Any]:
        data = self._read()
        projects = data.setdefault("projects", {})
        current = projects.get(project_id)
        if not isinstance(current, dict):
            raise FileNotFoundError(f"Project not found: {project_id}")
        payload = self._normalize_record(current)
        if title is not None:
            cleaned_title = str(title or "").strip()
            if cleaned_title:
                payload["title"] = cleaned_title[:120]
        if pinned is not None:
            payload["pinned"] = bool(pinned)
        payload["updated_at"] = now_iso()
        projects[project_id] = payload
        self._write(data)
        return payload

    def touch(self, project_id: str) -> dict[str, Any]:
        data = self._read()
        projects = data.setdefault("projects", {})
        current = projects.get(project_id)
        if not isinstance(current, dict):
            default_project = self.ensure_default_project()
            if default_project["project_id"] == project_id:
                return default_project
            raise FileNotFoundError(f"Project not found: {project_id}")
        payload = self._normalize_record(current)
        stamp = now_iso()
        payload["updated_at"] = stamp
        payload["last_opened_at"] = stamp
        projects[project_id] = payload
        self._write(data)
        return payload

    def delete(self, project_id: str) -> None:
        data = self._read()
        default_project_id = str(data.get("default_project_id") or "").strip()
        if project_id == default_project_id:
            raise ValueError("Default project cannot be deleted")
        projects = data.setdefault("projects", {})
        if project_id not in projects:
            raise FileNotFoundError(f"Project not found: {project_id}")
        del projects[project_id]
        self._write(data)


class UploadStore:
    def __init__(self, uploads_dir: Path) -> None:
        self.uploads_dir = uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.uploads_dir / "index.json"
        self._lock = threading.Lock()

        if not self.index_path.exists():
            self.index_path.write_text("{}", encoding="utf-8")

    def _load_index(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _save_index(self, index: dict[str, Any]) -> None:
        with self._lock:
            self.index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    async def save_upload(self, upload: UploadFile) -> dict[str, Any]:
        file_id = str(uuid.uuid4())
        original_name = upload.filename or "upload.bin"
        safe_name = _safe_name(original_name)
        stored_name = f"{file_id}__{safe_name}"
        target_path = (self.uploads_dir / stored_name).resolve()

        content = await upload.read()
        target_path.write_bytes(content)

        mime = upload.content_type or "application/octet-stream"
        suffix = Path(original_name).suffix.lower()
        kind = "other"
        if mime.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"}:
            kind = "image"
        elif mime.lower() in {"application/vnd.ms-outlook", "application/x-msg"}:
            kind = "document"
        elif mime.lower() in {"application/atom+xml", "application/rss+xml", "application/xml", "text/xml"}:
            kind = "document"
        elif suffix in {
            ".atom",
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".pdf",
            ".docx",
            ".msg",
            ".zip",
            ".doc",
            ".xlsx",
            ".xlsm",
            ".xltx",
            ".xltm",
            ".xls",
            ".pptx",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".yaml",
            ".yml",
            ".log",
            ".xml",
            ".rss",
        }:
            kind = "document"

        meta = {
            "id": file_id,
            "original_name": original_name,
            "safe_name": safe_name,
            "mime": mime,
            "suffix": suffix,
            "kind": kind,
            "size": len(content),
            "path": str(target_path),
            "created_at": now_iso(),
        }

        index = self._load_index()
        index[file_id] = meta
        self._save_index(index)
        return meta

    def get_many(self, file_ids: list[str]) -> list[dict[str, Any]]:
        index = self._load_index()
        out: list[dict[str, Any]] = []
        for file_id in file_ids:
            meta = index.get(file_id)
            if meta:
                out.append(meta)
        return out

    def delete(self, file_id: str) -> None:
        index = self._load_index()
        meta = index.pop(file_id, None)
        if meta and meta.get("path"):
            try:
                Path(meta["path"]).unlink(missing_ok=True)
            except Exception:
                pass
        self._save_index(index)


class ShadowLogStore:
    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path_for_day(self, day: str) -> Path:
        safe_day = re.sub(r"[^0-9-]+", "_", str(day or "").strip()) or "unknown"
        return self.logs_dir / f"{safe_day}.jsonl"

    def append(self, record: dict[str, Any], *, day: str | None = None) -> Path:
        stamp = now_iso()
        day_key = str(day or stamp[:10]).strip() or stamp[:10]
        payload = dict(record or {})
        payload.setdefault("logged_at", stamp)
        target = self._path_for_day(day_key)
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")
        return target

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        max_items = max(1, min(200, int(limit)))
        files = sorted(self.logs_dir.glob("*.jsonl"), key=lambda path: path.name, reverse=True)
        out: list[dict[str, Any]] = []
        for path in files:
            try:
                with self._lock:
                    lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for raw in reversed(lines):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    out.append(payload)
                if len(out) >= max_items:
                    return out
        return out

    def find_run(self, run_id: str) -> dict[str, Any] | None:
        wanted = str(run_id or "").strip()
        if not wanted:
            return None
        for record in self.list_recent(limit=500):
            if str(record.get("run_id") or "").strip() == wanted:
                return record
        return None


def _empty_totals() -> dict[str, int | float]:
    return {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


class TokenStatsStore:
    def __init__(self, stats_path: Path) -> None:
        self.stats_path = stats_path
        self._lock = threading.Lock()
        if not self.stats_path.exists():
            self._write(self._new_state())

    def _new_state(self) -> dict[str, Any]:
        return {
            "totals": _empty_totals(),
            "sessions": {},
            "records": [],
            "updated_at": now_iso(),
        }

    def _read(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(self.stats_path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            data["updated_at"] = now_iso()
            self.stats_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self._write(self._new_state())

    def _normalize_usage(self, usage: dict[str, Any]) -> dict[str, float]:
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
            "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0) or 0.0),
        }

    def add_usage(self, session_id: str, usage: dict[str, Any], model: str | None = None) -> dict[str, Any]:
        data = self._read()
        norm = self._normalize_usage(usage)

        totals = data.setdefault("totals", _empty_totals())
        totals["requests"] = int(totals.get("requests", 0) or 0) + 1
        totals["input_tokens"] = int(totals.get("input_tokens", 0) or 0) + norm["input_tokens"]
        totals["output_tokens"] = int(totals.get("output_tokens", 0) or 0) + norm["output_tokens"]
        totals["total_tokens"] = int(totals.get("total_tokens", 0) or 0) + norm["total_tokens"]
        totals["estimated_cost_usd"] = float(totals.get("estimated_cost_usd", 0.0) or 0.0) + norm["estimated_cost_usd"]

        sessions = data.setdefault("sessions", {})
        sess = sessions.setdefault(session_id, _empty_totals())
        sess["requests"] = int(sess.get("requests", 0) or 0) + 1
        sess["input_tokens"] = int(sess.get("input_tokens", 0) or 0) + norm["input_tokens"]
        sess["output_tokens"] = int(sess.get("output_tokens", 0) or 0) + norm["output_tokens"]
        sess["total_tokens"] = int(sess.get("total_tokens", 0) or 0) + norm["total_tokens"]
        sess["estimated_cost_usd"] = float(sess.get("estimated_cost_usd", 0.0) or 0.0) + norm["estimated_cost_usd"]

        records = data.setdefault("records", [])
        records.append(
            {
                "ts": now_iso(),
                "session_id": session_id,
                "model": model,
                "input_tokens": norm["input_tokens"],
                "output_tokens": norm["output_tokens"],
                "total_tokens": norm["total_tokens"],
                "llm_calls": int(usage.get("llm_calls", 0) or 0),
                "estimated_cost_usd": norm["estimated_cost_usd"],
                "pricing_known": bool(usage.get("pricing_known", False)),
                "pricing_model": usage.get("pricing_model"),
                "input_price_per_1m": usage.get("input_price_per_1m"),
                "output_price_per_1m": usage.get("output_price_per_1m"),
            }
        )

        self._write(data)
        return data

    def get_stats(self, max_records: int = 300) -> dict[str, Any]:
        data = self._read()
        records = data.get("records", [])
        if max_records > 0 and len(records) > max_records:
            data["records"] = records[-max_records:]
        return data
