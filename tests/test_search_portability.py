from __future__ import annotations

import io
import locale
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from scripts.benchmark_local_search import extract_repository_archive, utf8_output
from tests.test_code_search import _search


def test_benchmark_utf8_output_ignores_cp932_locale(monkeypatch):
    monkeypatch.setattr(locale, "getpreferredencoding", lambda *args: "cp932")
    monkeypatch.setattr(locale, "getencoding", lambda: "cp932")
    text = "# 日本語と测试文件.py\n"
    command = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({text.encode('utf-8')!r})"]
    assert utf8_output(command) == text
    with pytest.raises(UnicodeDecodeError):
        utf8_output([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"])


def test_tar_extraction_detects_old_and_new_signatures(tmp_path):
    calls = []
    class Python3112Tar:
        def extractall(self, path):
            calls.append((path, "legacy"))
    class ModernTar:
        def extractall(self, path, *, filter=None):
            calls.append((path, filter))
    extract_repository_archive(Python3112Tar(), tmp_path)
    extract_repository_archive(ModernTar(), tmp_path)
    assert calls == [(tmp_path, "legacy"), (tmp_path, "data")]


@pytest.mark.parametrize("legacy", [False, True])
def test_tar_extraction_non_ascii_and_spaces(tmp_path, legacy):
    buffer = io.BytesIO()
    names = ["测试文件.py", "日本語.txt", "folder with spaces/foo.py"]
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name in names:
            entry = tarfile.TarInfo(name)
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"text"))
    buffer.seek(0)
    root = tmp_path / "日本語 repository with spaces"
    root.mkdir()
    with tarfile.open(fileobj=buffer) as archive:
        class LegacyAdapter:
            def extractall(self, path):
                archive.extractall(path)
        extract_repository_archive(LegacyAdapter() if legacy else archive, root)
    assert all((root / name).read_text(encoding="utf-8") == "text" for name in names)


@pytest.mark.parametrize("rg", [False, True])
def test_search_non_ascii_repository_and_file_paths(tmp_path, monkeypatch, rg):
    if rg and not shutil.which("rg"):
        pytest.skip("rg not installed")
    root = tmp_path / "日本語 repository with spaces"
    root.mkdir()
    tools = _search(root, monkeypatch, rg=rg)
    names = ["测试文件.py", "日本語.txt", "folder with spaces/foo.py"]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unique_portable_marker\n", encoding="utf-8")
    result = tools.search_codebase("unique_portable_marker")
    assert result["ok"]
    assert {item["path"] for item in result["matches"]} == set(names)
    assert tools.search_files("测试")["matches"][0]["path"] == "测试文件.py"
