from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from app.serialization import dump_model


@dataclass
class DemoDataclass:
    name: str


class DemoModel(BaseModel):
    name: str


class LegacyModel:
    def dict(self) -> dict[str, bool]:
        return {"legacy": True}


def test_dump_model_handles_primitives() -> None:
    assert dump_model("hello") == "hello"
    assert dump_model(1) == 1
    assert dump_model(1.5) == 1.5
    assert dump_model(True) is True
    assert dump_model(None) is None


def test_dump_model_handles_dicts_and_sequences() -> None:
    assert dump_model({"a": 1}) == {"a": 1}
    assert dump_model(["a", 1]) == ["a", 1]
    assert dump_model(("a", 1)) == ["a", 1]
    assert sorted(dump_model({"a", "b"})) == ["a", "b"]


def test_dump_model_handles_path_and_temporal_values() -> None:
    assert dump_model(Path("/tmp/example")) == "/tmp/example"
    assert dump_model(date(2026, 5, 14)) == "2026-05-14"
    assert dump_model(datetime(2026, 5, 14, 12, 30, 0)) == "2026-05-14T12:30:00"


def test_dump_model_handles_dataclass() -> None:
    assert dump_model(DemoDataclass(name="demo")) == {"name": "demo"}


def test_dump_model_handles_pydantic_v2_model() -> None:
    assert dump_model(DemoModel(name="demo")) == {"name": "demo"}


def test_dump_model_handles_legacy_dict_objects() -> None:
    assert dump_model(LegacyModel()) == {"legacy": True}


def test_dump_model_handles_nested_mixed_values() -> None:
    payload = {
        "path": Path("/tmp/a"),
        "items": [DemoModel(name="x")],
        "legacy": LegacyModel(),
    }

    assert dump_model(payload) == {
        "path": "/tmp/a",
        "items": [{"name": "x"}],
        "legacy": {"legacy": True},
    }
