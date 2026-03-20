from __future__ import annotations


SPECIALIST_LABELS = {
    "researcher": "Researcher",
    "file_reader": "FileReader",
    "summarizer": "Summarizer",
    "fixer": "Fixer",
}


ROLE_KINDS = {
    "router": "hybrid",
    "coordinator": "processor",
    "pipeline_hooks": "processor",
    "planner": "agent",
    "researcher": "agent",
    "file_reader": "agent",
    "summarizer": "agent",
    "fixer": "agent",
    "worker": "agent",
    "conflict_detector": "agent",
    "reviewer": "agent",
    "revision": "agent",
    "structurer": "agent",
}
