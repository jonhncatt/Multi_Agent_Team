from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from app.serialization import dump_model, safe_model_dump


@dataclass
class DemoDataclass:
    name: str
    value: int = 0


class DemoModel(BaseModel):
    name: str
    value: int = 0


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
    assert dump_model({"a": None}) == {"a": None}
    assert dump_model(["a", 1]) == ["a", 1]
    assert dump_model(("a", 1)) == ["a", 1]
    assert sorted(dump_model({"a", "b"})) == ["a", "b"]


def test_dump_model_handles_path_and_temporal_values() -> None:
    assert dump_model(Path("/tmp/example")) == "/tmp/example"
    assert dump_model(date(2026, 5, 14)) == "2026-05-14"
    assert dump_model(datetime(2026, 5, 14, 12, 30, 0)) == "2026-05-14T12:30:00"


def test_dump_model_handles_dataclass() -> None:
    assert dump_model(DemoDataclass(name="demo", value=1)) == {"name": "demo", "value": 1}


def test_dump_model_handles_pydantic_v2_model() -> None:
    assert dump_model(DemoModel(name="demo", value=1)) == {"name": "demo", "value": 1}


def test_dump_model_handles_legacy_dict_objects() -> None:
    assert dump_model(LegacyModel()) == {"legacy": True}


class PlainObject:
    def __str__(self) -> str:
        return "plain-object"


def test_dump_model_handles_plain_object_fallback() -> None:
    assert dump_model(PlainObject()) == "plain-object"


def test_dump_model_handles_nested_mixed_values() -> None:
    payload = {
        "none": None,
        "path": Path("/tmp/a"),
        "items": [None, {"x": 1}, DemoModel(name="x", value=2)],
        "legacy": LegacyModel(),
        "data": DemoDataclass(name="d", value=3),
    }

    assert dump_model(payload) == {
        "none": None,
        "path": "/tmp/a",
        "items": [None, {"x": 1}, {"name": "x", "value": 2}],
        "legacy": {"legacy": True},
        "data": {"name": "d", "value": 3},
    }


class BrokenModelDump:
    def model_dump(self) -> dict[str, str]:
        raise AttributeError("'NoneType' object has no attribute 'model_dump'")

    def __str__(self) -> str:
        return "broken-model-dump"


def test_safe_model_dump_handles_none() -> None:
    assert safe_model_dump(None) is None


def test_safe_model_dump_falls_back_when_model_dump_raises() -> None:
    assert safe_model_dump(BrokenModelDump()) == "broken-model-dump"
